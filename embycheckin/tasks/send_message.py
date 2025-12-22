from __future__ import annotations

from pydantic import BaseModel, Field

from .base import TaskHandler, TaskContext, TaskResult, register_task_handler


class SendMessageConfig(BaseModel):
    message: str = Field(min_length=1)


@register_task_handler
class SendMessageTask(TaskHandler[SendMessageConfig]):
    type = "send_message"
    ConfigModel = SendMessageConfig

    async def execute(self, ctx: TaskContext, cfg: SendMessageConfig) -> TaskResult:
        from ..telegram import TelegramClientManager

        manager: TelegramClientManager = ctx.resources.get("telegram_manager")
        if not manager:
            return TaskResult(success=False, message="Telegram manager not available")

        try:
            async with manager.client(ctx.account.session_name) as client:
                await client.send_message(ctx.task.target, cfg.message)
                return TaskResult(
                    success=True,
                    message=f"Message sent to {ctx.task.target}",
                    data={"target": ctx.task.target, "message": cfg.message},
                )
        except Exception as e:
            return TaskResult(success=False, message=str(e))
