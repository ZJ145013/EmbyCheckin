from __future__ import annotations

import asyncio
import random
import re
import unicodedata
from io import BytesIO
from typing import Any, Optional

from pydantic import BaseModel, Field
from loguru import logger

from .base import TaskHandler, TaskContext, TaskResult, register_task_handler


class MessagePattern(BaseModel):
    """消息匹配模式配置"""
    keywords: list[str] = Field(default_factory=list, description="关键词列表，任一匹配即触发")
    regex: Optional[str] = Field(default=None, description="正则表达式匹配")
    extract_regex: Optional[str] = Field(default=None, description="用于提取数据的正则（如积分）")


class BotCheckinConfig(BaseModel):
    """通用机器人签到配置"""
    # 基础配置
    command: str = Field(default="/checkin", description="签到命令")
    random_delay_min: float = Field(default=2.0, description="发送前最小随机延迟(秒)")
    random_delay_max: float = Field(default=5.0, description="发送前最大随机延迟(秒)")
    timeout: int = Field(default=60, description="等待响应超时时间(秒)")

    # AI 验证码配置
    use_ai: bool = Field(default=False, description="是否使用AI识别验证码")
    captcha_has_image: bool = Field(default=True, description="验证码是否包含图片")
    captcha_has_buttons: bool = Field(default=True, description="验证码是否有按钮选项")

    # 消息识别模式
    success_patterns: MessagePattern = Field(
        default_factory=lambda: MessagePattern(
            keywords=["签到成功", "成功签到", "获得", "积分", "恭喜", "完成签到"],
            extract_regex=r"[+＋]?\s*(\d+)\s*[积分点]"
        ),
        description="签到成功的消息模式"
    )
    already_checked_patterns: MessagePattern = Field(
        default_factory=lambda: MessagePattern(
            keywords=["今天已签到", "已经签到", "今日已签到", "已签到", "重复签到", "签到机会已用完", "已用完"]
        ),
        description="已签到的消息模式"
    )
    fail_patterns: MessagePattern = Field(
        default_factory=lambda: MessagePattern(
            keywords=["失败", "错误", "验证码错误", "回答错误", "超时", "过期", "无效"]
        ),
        description="签到失败的消息模式"
    )
    ignore_patterns: MessagePattern = Field(
        default_factory=lambda: MessagePattern(
            keywords=["会话已取消", "没有活跃的会话"]
        ),
        description="需要忽略的消息模式"
    )
    account_error_patterns: MessagePattern = Field(
        default_factory=lambda: MessagePattern(
            keywords=["黑名单", "封禁", "禁止", "未注册", "不存在", "未绑定"]
        ),
        description="账号问题的消息模式"
    )


def _clean_text(text: str) -> str:
    cleaned = ''.join(
        c for c in text
        if unicodedata.category(c) not in ('So', 'Mn', 'Mc', 'Me')
    )
    return cleaned.replace(" ", "").lower()


def _match_pattern(text: str, pattern: MessagePattern) -> tuple[bool, Optional[str]]:
    """检查文本是否匹配模式，返回 (是否匹配, 提取的数据)"""
    if not text:
        return False, None

    # 关键词匹配
    if pattern.keywords and any(kw in text for kw in pattern.keywords):
        extracted = None
        if pattern.extract_regex:
            match = re.search(pattern.extract_regex, text)
            if match:
                extracted = match.group(1)
        return True, extracted

    # 正则匹配
    if pattern.regex:
        match = re.search(pattern.regex, text)
        if match:
            extracted = None
            if pattern.extract_regex:
                extract_match = re.search(pattern.extract_regex, text)
                if extract_match:
                    extracted = extract_match.group(1)
            return True, extracted

    return False, None


def _find_best_match(answer: str, options: list[str]) -> Optional[str]:
    if not answer or not options:
        return None

    answer_clean = answer.lower().strip()

    for opt in options:
        if opt.lower().strip() == answer_clean:
            return opt

    for opt in options:
        if answer_clean in opt.lower() or opt.lower() in answer_clean:
            return opt

    answer_cleaned = _clean_text(answer)
    for opt in options:
        opt_cleaned = _clean_text(opt)
        if opt_cleaned == answer_cleaned:
            return opt
        if answer_cleaned in opt_cleaned or opt_cleaned in answer_cleaned:
            return opt

    return None


@register_task_handler
class BotCheckinTask(TaskHandler[BotCheckinConfig]):
    """通用机器人签到任务"""
    type = "bot_checkin"
    ConfigModel = BotCheckinConfig

    async def execute(self, ctx: TaskContext, cfg: BotCheckinConfig) -> TaskResult:
        from ..telegram import TelegramClientManager, ConversationRouter

        manager: TelegramClientManager = ctx.resources.get("telegram_manager")
        router: ConversationRouter = ctx.resources.get("conversation_router")

        if not manager or not router:
            return TaskResult(success=False, message="Telegram manager or router not available")

        try:
            async with manager.client(ctx.account.session_name) as client:
                router.register_handler(client, ctx.account.id)

                bot = await client.get_users(ctx.task.target)
                bot_id = bot.id

                router.clear_queue(ctx.account.id, bot_id)

                # 随机延迟
                delay = random.uniform(cfg.random_delay_min, cfg.random_delay_max)
                await asyncio.sleep(delay)

                # 发送签到命令
                await client.send_message(ctx.task.target, cfg.command)
                logger.info(f"[{ctx.task.name}] Sent '{cfg.command}' to {ctx.task.target}")

                result = await self._wait_for_result(ctx, client, router, bot_id, cfg)
                return result

        except asyncio.TimeoutError:
            return TaskResult(success=False, message="Timeout waiting for bot response")
        except Exception as e:
            return TaskResult(success=False, message=f"{type(e).__name__}: {e}")

    async def _wait_for_result(
        self,
        ctx: TaskContext,
        client: Any,
        router: Any,
        bot_id: int,
        cfg: BotCheckinConfig,
    ) -> TaskResult:
        deadline = asyncio.get_event_loop().time() + cfg.timeout

        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break

            try:
                msg = await router.wait_for(
                    ctx.account.id,
                    bot_id,
                    predicate=lambda m: m.from_user and m.from_user.id == bot_id,
                    timeout=min(remaining, 10),
                )
            except asyncio.TimeoutError:
                continue

            text = msg.text or msg.caption or ""
            logger.debug(f"[{ctx.task.name}] Received: {text[:100]}")

            # 检查忽略模式
            matched, _ = _match_pattern(text, cfg.ignore_patterns)
            if matched:
                continue

            # 检查是否需要处理验证码
            if cfg.use_ai and msg.photo and (cfg.captcha_has_buttons and msg.reply_markup):
                captcha_result = await self._handle_captcha(ctx, client, msg, cfg)
                if captcha_result:
                    return captcha_result
                continue

            # 检查已签到
            matched, _ = _match_pattern(text, cfg.already_checked_patterns)
            if matched:
                return TaskResult(success=True, message="Already checked in today", data={"already_checked": True, "response": text})

            # 检查成功
            matched, extracted = _match_pattern(text, cfg.success_patterns)
            if matched:
                return TaskResult(
                    success=True,
                    message=f"Checkin success, extracted: {extracted or 'N/A'}",
                    data={"extracted": extracted, "response": text}
                )

            # 检查失败
            matched, _ = _match_pattern(text, cfg.fail_patterns)
            if matched:
                return TaskResult(success=False, message=f"Checkin failed: {text[:100]}", data={"response": text})

            # 检查账号问题
            matched, _ = _match_pattern(text, cfg.account_error_patterns)
            if matched:
                return TaskResult(success=False, message=f"Account issue: {text[:100]}", data={"response": text})

        return TaskResult(success=False, message="Timeout waiting for checkin result")

    async def _handle_captcha(
        self,
        ctx: TaskContext,
        client: Any,
        msg: Any,
        cfg: BotCheckinConfig,
    ) -> Optional[TaskResult]:
        from ..ai import analyze_captcha

        try:
            if not msg.reply_markup or not msg.reply_markup.inline_keyboard:
                return TaskResult(success=False, message="No captcha options found")

            options = []
            for row in msg.reply_markup.inline_keyboard:
                for button in row:
                    if button.text:
                        options.append(button.text)

            if not options:
                return TaskResult(success=False, message="Empty captcha options")

            # Build index-preserving mapping
            option_pairs = [(opt, _clean_text(opt)) for opt in options]
            options_cleaned = [cleaned for _, cleaned in option_pairs if cleaned]

            logger.info(f"[{ctx.task.name}] Captcha options: {options}")

            photo_data = await client.download_media(msg, in_memory=True)
            if isinstance(photo_data, BytesIO):
                image_bytes = photo_data.getvalue()
            else:
                image_bytes = photo_data

            answer, error = await analyze_captcha(image_bytes, options_cleaned, ctx.settings)

            if error:
                logger.error(f"[{ctx.task.name}] Captcha recognition failed: {error}")
                return None

            logger.info(f"[{ctx.task.name}] AI answer: {answer}")

            matched = _find_best_match(answer, options)
            if not matched:
                matched_clean = _find_best_match(answer, options_cleaned)
                if matched_clean:
                    for orig, cleaned in option_pairs:
                        if cleaned == matched_clean:
                            matched = orig
                            break

            if not matched:
                logger.error(f"[{ctx.task.name}] Cannot match answer '{answer}' to options")
                return None

            logger.info(f"[{ctx.task.name}] Clicking: {matched}")
            await asyncio.sleep(random.uniform(1, 3))
            await msg.click(matched)
            return None

        except Exception as e:
            logger.error(f"[{ctx.task.name}] Captcha handling error: {e}")
            return None
