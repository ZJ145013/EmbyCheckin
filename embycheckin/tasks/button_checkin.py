from __future__ import annotations

import asyncio
import random
from typing import Any, Optional

from pydantic import BaseModel, Field
from loguru import logger

from .base import TaskHandler, TaskContext, TaskResult, register_task_handler


class ButtonCheckinConfig(BaseModel):
    """面板按钮签到配置"""
    # 触发命令
    trigger_command: str = Field(default="/start", description="触发面板的命令")

    # 按钮配置
    button_text: str = Field(default="签到", description="要点击的按钮文本（支持部分匹配）")

    # 延迟配置
    wait_panel_seconds: float = Field(default=2.0, description="等待面板出现的时间(秒)")
    random_delay_min: float = Field(default=1.0, description="点击前最小随机延迟(秒)")
    random_delay_max: float = Field(default=3.0, description="点击前最大随机延迟(秒)")
    timeout: int = Field(default=30, description="等待响应超时时间(秒)")

    # 结果识别
    success_keywords: list[str] = Field(
        default_factory=lambda: ["签到成功", "成功", "获得", "积分", "恭喜", "完成"],
        description="签到成功的关键词"
    )
    already_checked_keywords: list[str] = Field(
        default_factory=lambda: ["已签到", "已经签到", "今天已", "重复"],
        description="已签到的关键词"
    )
    fail_keywords: list[str] = Field(
        default_factory=lambda: ["失败", "错误", "无效"],
        description="签到失败的关键词"
    )


@register_task_handler
class ButtonCheckinTask(TaskHandler[ButtonCheckinConfig]):
    """面板按钮签到任务 - 适用于需要点击内联键盘按钮的机器人"""
    type = "button_checkin"
    ConfigModel = ButtonCheckinConfig

    async def execute(self, ctx: TaskContext, cfg: ButtonCheckinConfig) -> TaskResult:
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

                # 发送触发命令
                logger.info(f"[{ctx.task.name}] Sending '{cfg.trigger_command}' to {ctx.task.target}")
                await client.send_message(ctx.task.target, cfg.trigger_command)

                # 等待面板出现
                await asyncio.sleep(cfg.wait_panel_seconds)

                # 等待带按钮的消息
                panel_msg = await self._wait_for_panel(ctx, router, bot_id, cfg)

                if not panel_msg:
                    return TaskResult(success=False, message="Timeout waiting for panel")

                # 查找并点击按钮
                clicked, callback_text = await self._click_button(ctx, panel_msg, cfg)

                if not clicked:
                    return TaskResult(success=False, message=f"Button '{cfg.button_text}' not found")

                # 如果有回调响应（弹窗），直接用它判断结果
                if callback_text:
                    return self._parse_result(callback_text, cfg)

                # 否则等待新消息
                result = await self._wait_for_result(ctx, router, bot_id, cfg)
                return result

        except asyncio.TimeoutError:
            return TaskResult(success=False, message="Timeout")
        except Exception as e:
            logger.error(f"[{ctx.task.name}] Error: {e}")
            return TaskResult(success=False, message=f"{type(e).__name__}: {e}")

    async def _wait_for_panel(
        self,
        ctx: TaskContext,
        router: Any,
        bot_id: int,
        cfg: ButtonCheckinConfig,
    ) -> Optional[Any]:
        """等待带有内联键盘的消息"""
        try:
            msg = await router.wait_for(
                ctx.account.id,
                bot_id,
                predicate=lambda m: (
                    m.from_user and
                    m.from_user.id == bot_id and
                    m.reply_markup and
                    hasattr(m.reply_markup, 'inline_keyboard')
                ),
                timeout=cfg.timeout,
            )
            return msg
        except asyncio.TimeoutError:
            return None

    def _parse_result(self, text: str, cfg: ButtonCheckinConfig) -> TaskResult:
        """解析响应文本，判断签到结果"""
        # 检查已签到
        for kw in cfg.already_checked_keywords:
            if kw in text:
                return TaskResult(
                    success=True,
                    message="Already checked in today",
                    data={"already_checked": True, "response": text}
                )

        # 检查成功
        for kw in cfg.success_keywords:
            if kw in text:
                return TaskResult(
                    success=True,
                    message=f"Checkin success: {text[:50]}",
                    data={"response": text}
                )

        # 检查失败
        for kw in cfg.fail_keywords:
            if kw in text:
                return TaskResult(success=False, message=f"Checkin failed: {text[:100]}")

        # 默认认为成功（有响应）
        return TaskResult(
            success=True,
            message=f"Got response: {text[:50]}",
            data={"response": text}
        )

    async def _click_button(
        self,
        ctx: TaskContext,
        msg: Any,
        cfg: ButtonCheckinConfig,
    ) -> tuple[bool, str | None]:
        """查找并点击指定按钮，返回 (是否点击成功, 回调响应文本)"""
        if not msg.reply_markup or not msg.reply_markup.inline_keyboard:
            return False, None

        target_text = cfg.button_text.lower()

        for row in msg.reply_markup.inline_keyboard:
            for button in row:
                if button.text and target_text in button.text.lower():
                    # 随机延迟后点击（手动触发时跳过）
                    if ctx.triggered_by != "manual":
                        delay = random.uniform(cfg.random_delay_min, cfg.random_delay_max)
                        await asyncio.sleep(delay)

                    logger.info(f"[{ctx.task.name}] Clicking button: {button.text}")
                    # click() 返回回调查询的响应（弹窗消息）
                    callback_result = await msg.click(button.text)
                    callback_text = None
                    if callback_result:
                        # 回调响应可能是字符串或对象
                        if isinstance(callback_result, str):
                            callback_text = callback_result
                        elif hasattr(callback_result, 'message'):
                            callback_text = callback_result.message
                    if callback_text:
                        logger.info(f"[{ctx.task.name}] Callback response: {callback_text}")
                    return True, callback_text

        # 记录所有可用按钮
        all_buttons = []
        for row in msg.reply_markup.inline_keyboard:
            for button in row:
                if button.text:
                    all_buttons.append(button.text)
        logger.warning(f"[{ctx.task.name}] Button '{cfg.button_text}' not found. Available: {all_buttons}")

        return False, None

    async def _wait_for_result(
        self,
        ctx: TaskContext,
        router: Any,
        bot_id: int,
        cfg: ButtonCheckinConfig,
    ) -> TaskResult:
        """等待签到结果"""
        try:
            msg = await router.wait_for(
                ctx.account.id,
                bot_id,
                predicate=lambda m: m.from_user and m.from_user.id == bot_id,
                timeout=cfg.timeout,
            )

            text = msg.text or msg.caption or ""
            logger.info(f"[{ctx.task.name}] Result: {text[:100]}")
            return self._parse_result(text, cfg)

        except asyncio.TimeoutError:
            return TaskResult(success=False, message="Timeout waiting for result")
