from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded

from ..settings import settings


class LoginSession:
    """管理登录会话状态"""
    def __init__(self, client: Client, phone_code_hash: str):
        self.client = client
        self.phone_code_hash = phone_code_hash


class TelegramClientManager:
    def __init__(self, sessions_dir: str = "sessions") -> None:
        self._sessions_dir = Path(sessions_dir)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._clients: dict[str, Client] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._login_sessions: dict[str, LoginSession] = {}

    def _get_lock(self, session_name: str) -> asyncio.Lock:
        if session_name not in self._locks:
            self._locks[session_name] = asyncio.Lock()
        return self._locks[session_name]

    def _create_client(self, session_name: str, phone_number: str = None) -> Client:
        return Client(
            name=str(self._sessions_dir / session_name),
            api_id=settings.api_id,
            api_hash=settings.api_hash,
            phone_number=phone_number,
        )

    async def send_code(self, session_name: str, phone_number: str) -> dict:
        """发送验证码，返回登录会话信息"""
        client = self._create_client(session_name, phone_number)
        await client.connect()

        try:
            sent_code = await client.send_code(phone_number)
            self._login_sessions[session_name] = LoginSession(client, sent_code.phone_code_hash)
            return {
                "session_name": session_name,
                "phone_code_hash": sent_code.phone_code_hash,
                "status": "code_sent"
            }
        except Exception as e:
            await client.disconnect()
            raise e

    async def sign_in(self, session_name: str, phone_number: str, code: str) -> dict:
        """使用验证码登录"""
        login_session = self._login_sessions.get(session_name)
        if not login_session:
            raise ValueError("No pending login session found")

        client = login_session.client
        try:
            await client.sign_in(phone_number, login_session.phone_code_hash, code)
            me = await client.get_me()
            await client.disconnect()
            del self._login_sessions[session_name]
            return {
                "status": "success",
                "user": {
                    "id": me.id,
                    "first_name": me.first_name,
                    "username": me.username
                }
            }
        except SessionPasswordNeeded:
            return {
                "status": "2fa_required",
                "message": "Two-factor authentication required"
            }
        except Exception as e:
            await client.disconnect()
            del self._login_sessions[session_name]
            raise e

    async def sign_in_2fa(self, session_name: str, password: str) -> dict:
        """使用两步验证密码登录"""
        login_session = self._login_sessions.get(session_name)
        if not login_session:
            raise ValueError("No pending login session found")

        client = login_session.client
        try:
            await client.check_password(password)
            me = await client.get_me()
            await client.disconnect()
            del self._login_sessions[session_name]
            return {
                "status": "success",
                "user": {
                    "id": me.id,
                    "first_name": me.first_name,
                    "username": me.username
                }
            }
        except Exception as e:
            await client.disconnect()
            del self._login_sessions[session_name]
            raise e

    async def cancel_login(self, session_name: str) -> None:
        """取消登录会话"""
        login_session = self._login_sessions.get(session_name)
        if login_session:
            try:
                await login_session.client.disconnect()
            except:
                pass
            del self._login_sessions[session_name]

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
