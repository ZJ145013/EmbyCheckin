from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Optional

from pyrogram import Client
from pyrogram.types import Message


Predicate = Callable[[Message], bool]


class ConversationRouter:
    def __init__(self) -> None:
        self._queues: dict[tuple[int, int], asyncio.Queue[Message]] = defaultdict(asyncio.Queue)
        self._handlers_registered: set[int] = set()

    def _queue_key(self, account_id: int, chat_id: int) -> tuple[int, int]:
        return (account_id, chat_id)

    async def route_message(self, account_id: int, message: Message) -> None:
        key = self._queue_key(account_id, message.chat.id)
        await self._queues[key].put(message)

    async def wait_for(
        self,
        account_id: int,
        chat_id: int,
        predicate: Optional[Predicate] = None,
        timeout: float = 60.0,
    ) -> Message:
        key = self._queue_key(account_id, chat_id)
        queue = self._queues[key]

        deadline = asyncio.get_event_loop().time() + timeout
        pending: list[Message] = []

        try:
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError(f"Timeout waiting for message in chat {chat_id}")

                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    raise asyncio.TimeoutError(f"Timeout waiting for message in chat {chat_id}")

                if predicate is None or predicate(msg):
                    return msg

                pending.append(msg)
        finally:
            for msg in reversed(pending):
                await queue.put(msg)

    def register_handler(self, client: Client, account_id: int) -> None:
        if account_id in self._handlers_registered:
            return

        @client.on_message()
        async def _global_handler(c: Client, message: Message) -> None:
            await self.route_message(account_id, message)

        self._handlers_registered.add(account_id)

    def clear_queue(self, account_id: int, chat_id: int) -> None:
        key = self._queue_key(account_id, chat_id)
        if key in self._queues:
            while not self._queues[key].empty():
                try:
                    self._queues[key].get_nowait()
                except asyncio.QueueEmpty:
                    break
