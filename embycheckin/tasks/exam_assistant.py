from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from loguru import logger

from .base import TaskHandler, TaskContext, TaskResult, register_task_handler


class ExamAssistantConfig(BaseModel):
    keywords: list[str] = Field(
        default=["考核", "题目", "问答", "答题", "quiz", "考试"],
        description="触发关键词列表"
    )
    exclude_keywords: list[str] = Field(
        default=["答案", "正确"],
        description="排除关键词（包含则跳过）"
    )

    auto_reply: bool = Field(default=False, description="是否自动回复答案")
    reply_delay_min: float = Field(default=3.0, ge=0, description="回复最小延迟(秒)")
    reply_delay_max: float = Field(default=8.0, ge=0, description="回复最大延迟(秒)")

    lookback_seconds: int = Field(default=300, ge=30, description="检查过去多少秒的消息")
    max_messages: int = Field(default=30, ge=1, le=100, description="最多检查多少条消息")

    ai_prompt_template: str = Field(
        default="请直接回答以下问题，只给出答案，不需要解释：\n\n{question}",
        description="AI 提示词模板，{question} 会被替换为问题内容"
    )
    ai_max_tokens: int = Field(default=200, ge=50, description="AI 回复最大 token 数")


@register_task_handler
class ExamAssistantTask(TaskHandler[ExamAssistantConfig]):
    type = "exam_assistant"
    ConfigModel = ExamAssistantConfig

    async def execute(self, ctx: TaskContext, cfg: ExamAssistantConfig) -> TaskResult:
        if not ctx.task.target:
            return TaskResult(success=False, message="Target chat is empty")

        from ..telegram import TelegramClientManager
        from ..ai.providers import generate_text

        manager: TelegramClientManager = ctx.resources.get("telegram_manager")
        if not manager:
            return TaskResult(success=False, message="Telegram manager not available")

        if not ctx.account:
            return TaskResult(success=False, message="Account not configured for this task")

        processed = 0
        replied = 0
        answers = []

        try:
            async with manager.client(ctx.account.session_name) as client:
                try:
                    chat = await client.get_chat(ctx.task.target)
                    chat_id = chat.id
                except Exception as e:
                    return TaskResult(success=False, message=f"Cannot find chat {ctx.task.target}: {e}")

                await ctx.log(f"Scanning messages in {ctx.task.target}")
                now = datetime.now(timezone.utc)
                messages = []

                async for msg in client.get_chat_history(chat_id, limit=cfg.max_messages):
                    if not msg.date:
                        continue

                    msg_time = msg.date if msg.date.tzinfo else msg.date.replace(tzinfo=timezone.utc)
                    age = (now - msg_time).total_seconds()
                    if age > cfg.lookback_seconds:
                        break

                    messages.append(msg)

                for msg in reversed(messages):
                    text = msg.text or msg.caption or ""
                    if not text or len(text) < 5:
                        continue

                    if msg.from_user:
                        if getattr(msg.from_user, "is_self", False):
                            continue
                        if getattr(msg.from_user, "is_bot", False):
                            continue

                    if not self._matches_keywords(text, cfg.keywords):
                        continue

                    if self._matches_keywords(text, cfg.exclude_keywords):
                        continue

                    await ctx.log(f"Found question: {text[:60]}...")
                    logger.info(f"[{ctx.task.name}] Found question: {text[:80]}...")

                    template = cfg.ai_prompt_template or "{question}"
                    if "{question}" in template:
                        prompt = template.replace("{question}", text)
                    else:
                        prompt = f"{template.rstrip()}\n\n{text}"
                    answer, error = await generate_text(prompt, ctx.settings)

                    if error:
                        logger.error(f"[{ctx.task.name}] AI error: {error}")
                        continue

                    answer = answer.strip()
                    if not answer:
                        continue

                    await ctx.log(f"AI answered ({len(answer)} chars)")
                    logger.info(f"[{ctx.task.name}] AI answered ({len(answer)} chars)")
                    processed += 1
                    answers.append({"question": text[:100], "answer": answer[:200]})

                    if cfg.auto_reply:
                        delay = random.uniform(cfg.reply_delay_min, cfg.reply_delay_max)
                        await asyncio.sleep(delay)

                        try:
                            await msg.reply(answer[:4000])
                            replied += 1
                            logger.info(f"[{ctx.task.name}] Replied to message {msg.id}")
                        except Exception as e:
                            logger.error(f"[{ctx.task.name}] Reply failed: {e}")

            return TaskResult(
                success=True,
                message=f"Processed {processed} questions, replied {replied}",
                data={"processed": processed, "replied": replied, "answers": answers[:5]}
            )

        except Exception as e:
            logger.error(f"[{ctx.task.name}] Error: {e}")
            return TaskResult(success=False, message=f"{type(e).__name__}: {e}")

    def _matches_keywords(self, text: str, keywords: list[str]) -> bool:
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)
