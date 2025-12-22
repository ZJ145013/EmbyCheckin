from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from pyrogram import Client

from ..settings import settings


class TelegramClientManager:
    def __init__(self, sessions_dir: str = "sessions") -> None:
        self._sessions_dir = Path(sessions_dir)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._clients: dict[str, Client] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, session_name: str) -> asyncio.Lock:
        if session_name not in self._locks:
            self._locks[session_name] = asyncio.Lock()
        return self._locks[session_name]

    def _create_client(self, session_name: str) -> Client:
        return Client(
            name=str(self._sessions_dir / session_name),
            api_id=settings.api_id,
            api_hash=settings.api_hash,
        )

    @asynccontextmanager
    async def client(self, session_name: str) -> AsyncIterator[Client]:
        lock = self._get_lock(session_name)
        async with lock:
            if session_name in self._clients:
                yield self._clients[session_name]
                return

            client = self._create_client(session_name)
            try:
                await client.start()
                self._clients[session_name] = client
                yield client
            except Exception:
                if client.is_connected:
                    await client.stop()
                raise

    async def get_or_start(self, session_name: str) -> Client:
        lock = self._get_lock(session_name)
        async with lock:
            if session_name in self._clients:
                return self._clients[session_name]

            client = self._create_client(session_name)
            await client.start()
            self._clients[session_name] = client
            return client

    async def stop_all(self) -> None:
        for session_name, client in list(self._clients.items()):
            try:
                if client.is_connected:
                    await client.stop()
            except Exception:
                pass
            self._clients.pop(session_name, None)

    def is_connected(self, session_name: str) -> bool:
        client = self._clients.get(session_name)
        return client is not None and client.is_connected
