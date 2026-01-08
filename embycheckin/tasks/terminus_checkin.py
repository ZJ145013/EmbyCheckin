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


class TerminusCheckinConfig(BaseModel):
    command: str = Field(default="/checkin")
    random_delay_min: float = Field(default=2.0)
    random_delay_max: float = Field(default=5.0)


def _clean_text(text: str) -> str:
    cleaned = ''.join(
        c for c in text
        if unicodedata.category(c) not in ('So', 'Mn', 'Mc', 'Me')
    )
    return cleaned.replace(" ", "").lower()


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
class TerminusCheckinTask(TaskHandler[TerminusCheckinConfig]):
    type = "terminus_checkin"
    ConfigModel = TerminusCheckinConfig

    async def execute(self, ctx: TaskContext, cfg: TerminusCheckinConfig) -> TaskResult:
        from ..telegram import TelegramClientManager, ConversationRouter
        from ..ai import analyze_captcha

        manager: TelegramClientManager = ctx.resources.get("telegram_manager")
        router: ConversationRouter = ctx.resources.get("conversation_router")

        if not manager or not router:
            return TaskResult(success=False, message="Telegram manager or router not available")

        if not ctx.account:
            return TaskResult(success=False, message="Account not configured for this task")

        try:
            async with manager.client(ctx.account.session_name) as client:
                router.register_handler(client, ctx.account.id)

                bot = await client.get_users(ctx.task.target)
                bot_id = bot.id

                router.clear_queue(ctx.account.id, bot_id)

                if ctx.triggered_by != "manual":
                    delay = random.uniform(cfg.random_delay_min, cfg.random_delay_max)
                    await asyncio.sleep(delay)

                await client.send_message(ctx.task.target, cfg.command)
                logger.info(f"[{ctx.task.name}] Sent {cfg.command} to {ctx.task.target}")

                result = await self._wait_for_result(ctx, client, router, bot_id)
                return result

        except asyncio.TimeoutError:
            return TaskResult(success=False, message="Timeout waiting for bot response")
        except Exception as e:
            return TaskResult(success=False, message=f"{type(e).__name__}: {e}")

    async def _wait_for_result(
        self,
        ctx: TaskContext,
        client: Any,
        router: ConversationRouter,
        bot_id: int,
    ) -> TaskResult:
        from ..ai import analyze_captcha

        deadline = asyncio.get_event_loop().time() + 60

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

            if any(kw in text for kw in ["会话已取消", "没有活跃的会话"]):
                continue

            if msg.photo and msg.reply_markup:
                captcha_result = await self._handle_captcha(ctx, client, msg)
                if captcha_result:
                    return captcha_result
                continue

            already_keywords = [
                "今天已签到", "已经签到", "今日已签到", "已签到",
                "重复签到", "签到机会已用完", "已用完"
            ]
            if any(kw in text for kw in already_keywords):
                return TaskResult(success=True, message="Already checked in today", data={"already_checked": True})

            success_keywords = ["签到成功", "成功签到", "获得", "积分", "恭喜", "完成签到"]
            if any(kw in text for kw in success_keywords):
                match = re.search(r"[+＋]?\s*(\d+)\s*[积分点]", text)
                points = match.group(1) if match else "unknown"
                return TaskResult(success=True, message=f"Checkin success, points: {points}", data={"points": points})

            fail_keywords = ["失败", "错误", "验证码错误", "回答错误", "超时", "过期", "无效"]
            if any(kw in text for kw in fail_keywords):
                return TaskResult(success=False, message=f"Checkin failed: {text[:100]}")

            account_fail = ["黑名单", "封禁", "禁止", "未注册", "不存在", "未绑定"]
            if any(kw in text for kw in account_fail):
                return TaskResult(success=False, message=f"Account issue: {text[:100]}")

        return TaskResult(success=False, message="Timeout waiting for checkin result")

    async def _handle_captcha(self, ctx: TaskContext, client: Any, msg: Any) -> Optional[TaskResult]:
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

            # Build index-preserving mapping: (original_option, cleaned_option)
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
                    # Find original option using the preserved mapping
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
