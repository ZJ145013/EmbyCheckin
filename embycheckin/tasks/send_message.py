from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from .base import TaskHandler, TaskContext, TaskResult, register_task_handler


class SendMessageConfig(BaseModel):
    message: str = Field(min_length=1)
    wait_for_reply: bool = Field(default=False)
    timeout: int = Field(default=30, ge=1)


@register_task_handler
class SendMessageTask(TaskHandler[SendMessageConfig]):
    type = "send_message"
    ConfigModel = SendMessageConfig

    async def execute(self, ctx: TaskContext, cfg: SendMessageConfig) -> TaskResult:
        from ..telegram import TelegramClientManager, ConversationRouter

        manager: TelegramClientManager = ctx.resources.get("telegram_manager")
        if not manager:
            return TaskResult(success=False, message="Telegram manager not available")

        router: ConversationRouter = ctx.resources.get("conversation_router")
        if cfg.wait_for_reply and not router:
            return TaskResult(success=False, message="Conversation router not available")

        try:
            async with manager.client(ctx.account.session_name) as client:
                target_id = None
                if cfg.wait_for_reply:
                    router.register_handler(client, ctx.account.id)
                    entity = await client.get_users(ctx.task.target)
                    target_id = entity.id
                    router.clear_queue(ctx.account.id, target_id)

                await client.send_message(ctx.task.target, cfg.message)

                data = {"target": ctx.task.target, "message": cfg.message}

                if cfg.wait_for_reply:
                    try:
                        msg = await router.wait_for(
                            ctx.account.id,
                            target_id,
                            predicate=lambda m: m.from_user and m.from_user.id == target_id,
                            timeout=float(cfg.timeout),
                        )
                        data["response"] = msg.text or msg.caption or ""
                    except asyncio.TimeoutError:
                        return TaskResult(
                            success=False,
                            message=f"Timeout waiting for response from {ctx.task.target}",
                            data=data,
                        )

                return TaskResult(
                    success=True,
                    message=f"Message sent to {ctx.task.target}",
                    data=data,
                )
        except Exception as e:
            return TaskResult(success=False, message=str(e))
