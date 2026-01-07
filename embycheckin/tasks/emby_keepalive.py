from __future__ import annotations

import asyncio
import contextlib
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from pydantic import BaseModel, Field
from loguru import logger

from .base import TaskHandler, TaskContext, TaskResult, register_task_handler
from ..proxy import LocalProxyRunner


def _sanitize_header_value(value: str) -> str:
    return (value or "").replace("\r", "").replace("\n", "").replace('"', "").strip()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


class EmbyKeepAliveConfig(BaseModel):
    server_url: str = Field(..., description="Emby 服务器地址 (如 http://example.com:8096)")
    username: Optional[str] = Field(default=None, description="用户名")
    password: Optional[str] = Field(default=None, description="密码")
    api_key: Optional[str] = Field(default=None, description="API Key (与用户名密码二选一)")
    proxy_url: Optional[str] = Field(default=None, description="代理地址 (如 http://127.0.0.1:7890)")

    device_name: str = Field(default="EmbyCheckin", description="设备名称")
    device_id: str = Field(default_factory=lambda: f"emby-checkin-{uuid.uuid4().hex[:8]}", description="设备ID")
    client_name: str = Field(default="Emby Web", description="客户端名称")
    client_version: str = Field(default="4.7.14.0", description="客户端版本")

    play_duration: int = Field(default=120, ge=10, description="模拟播放时长(秒)")
    report_interval: int = Field(default=10, ge=5, description="播放进度汇报间隔(秒)")
    random_item: bool = Field(default=True, description="随机选择媒体项目")
    verify_ssl: bool = Field(default=True, description="验证 SSL 证书")


@register_task_handler
class EmbyKeepAliveTask(TaskHandler[EmbyKeepAliveConfig]):
    type = "emby_keepalive"
    ConfigModel = EmbyKeepAliveConfig

    async def execute(self, ctx: TaskContext, cfg: EmbyKeepAliveConfig) -> TaskResult:
        logs: list[str] = []

        def log(msg: str) -> None:
            logs.append(f"[{_ts()}] {msg}")
            logger.info(f"[{ctx.task.name}] {msg}")

        base_url = cfg.server_url.rstrip("/")
        try:
            parsed = httpx.URL(base_url)
        except Exception:
            return TaskResult(success=False, message="Invalid server_url", data={"logs": logs})
        if parsed.scheme not in {"http", "https"} or not parsed.host:
            return TaskResult(success=False, message="server_url must be http(s)://host[:port]", data={"logs": logs})

        log(f"Target: {parsed.host}")

        client_name = _sanitize_header_value(cfg.client_name)
        device_name = _sanitize_header_value(cfg.device_name)
        device_id = _sanitize_header_value(cfg.device_id)
        client_version = _sanitize_header_value(cfg.client_version)

        auth_header = (
            f'MediaBrowser Client="{client_name}", '
            f'Device="{device_name}", '
            f'DeviceId="{device_id}", '
            f'Version="{client_version}"'
        )

        headers = {
            "X-Emby-Authorization": auth_header,
            "Content-Type": "application/json",
        }

        try:
            proxy_runner = LocalProxyRunner(cfg.proxy_url) if cfg.proxy_url else None
            async with contextlib.AsyncExitStack() as stack:
                effective_proxy = None
                if proxy_runner:
                    log("Starting proxy...")
                    effective_proxy = await stack.enter_async_context(proxy_runner)
                    log(f"Proxy ready: {effective_proxy}")

                async with httpx.AsyncClient(
                    headers=headers,
                    timeout=30,
                    verify=cfg.verify_ssl,
                    follow_redirects=True,
                    proxy=effective_proxy,
                ) as client:
                    log("Authenticating...")
                    user_id, access_token = await self._authenticate(client, base_url, cfg, log)
                    if not user_id or not access_token:
                        return TaskResult(success=False, message="Authentication failed", data={"logs": logs})

                    log(f"Authenticated: user_id={user_id[:8]}...")
                    client.headers["X-Emby-Token"] = access_token

                    log("Fetching media items...")
                    item_id, item_name = await self._get_playable_item(client, base_url, user_id, cfg)
                    if not item_id:
                        log("No playable items, reporting capabilities...")
                        await self._report_capabilities(client, base_url, headers)
                        return TaskResult(
                            success=True,
                            message="No playable items found, session kept alive via capabilities report",
                            data={"user_id": user_id, "logs": logs}
                        )

                    log(f"Selected: {item_name or item_id}")
                    await self._simulate_playback(client, base_url, headers, user_id, item_id, cfg, log)

                    return TaskResult(
                        success=True,
                        message=f"Keep-alive successful: played {cfg.play_duration}s",
                        data={"user_id": user_id, "item_id": item_id, "item_name": item_name, "logs": logs}
                    )

        except Exception as e:
            log(f"Error: {type(e).__name__}: {e}")
            return TaskResult(success=False, message=f"{type(e).__name__}: {e}", data={"logs": logs})

    async def _authenticate(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        cfg: EmbyKeepAliveConfig,
        log,
    ) -> tuple[Optional[str], Optional[str]]:
        if cfg.api_key:
            try:
                client.headers["X-Emby-Token"] = cfg.api_key
                resp = await client.get(f"{base_url}/Users")
                resp.raise_for_status()
                users = resp.json()

                if cfg.username:
                    for u in users:
                        if u.get("Name", "").lower() == cfg.username.lower():
                            return u["Id"], cfg.api_key
                    log(f"User '{cfg.username}' not found")
                    return None, None
                if users:
                    return users[0]["Id"], cfg.api_key

            except httpx.HTTPStatusError as e:
                log(f"API key auth failed: HTTP {e.response.status_code}")
            except Exception as e:
                log(f"API key auth failed: {type(e).__name__}")
            return None, None

        if not cfg.username:
            log("No credentials provided")
            return None, None

        try:
            resp = await client.post(
                f"{base_url}/Users/AuthenticateByName",
                json={"Username": cfg.username, "Pw": cfg.password or ""}
            )
            resp.raise_for_status()
            data = resp.json()
            return data["User"]["Id"], data["AccessToken"]

        except httpx.HTTPStatusError as e:
            log(f"Auth failed: HTTP {e.response.status_code}")
        except Exception as e:
            log(f"Auth failed: {type(e).__name__}")
        return None, None

    async def _get_playable_item(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        user_id: str,
        cfg: EmbyKeepAliveConfig,
    ) -> tuple[Optional[str], Optional[str]]:
        try:
            resp = await client.get(
                f"{base_url}/Users/{user_id}/Items",
                params={
                    "IncludeItemTypes": "Movie,Episode",
                    "Recursive": "true",
                    "Limit": 50,
                    "SortBy": "Random" if cfg.random_item else "DateCreated",
                    "SortOrder": "Descending",
                }
            )
            resp.raise_for_status()
            items = resp.json().get("Items", [])

            if items:
                item = random.choice(items) if cfg.random_item else items[0]
                return item["Id"], item.get("Name")

        except Exception as e:
            logger.warning(f"Failed to get items: {type(e).__name__}: {e}")

        return None, None

    async def _report_capabilities(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        headers: dict,
    ) -> None:
        try:
            await client.post(
                f"{base_url}/Sessions/Capabilities/Full",
                headers=headers,
                json={
                    "PlayableMediaTypes": ["Video", "Audio"],
                    "SupportedCommands": [],
                    "SupportsMediaControl": True,
                }
            )
        except Exception:
            pass

    async def _simulate_playback(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        headers: dict,
        user_id: str,
        item_id: str,
        cfg: EmbyKeepAliveConfig,
        log,
    ) -> None:
        play_session_id = uuid.uuid4().hex

        try:
            await client.post(
                f"{base_url}/Sessions/Playing",
                headers=headers,
                json={
                    "ItemId": item_id,
                    "PlaySessionId": play_session_id,
                    "CanSeek": True,
                    "IsPaused": False,
                    "IsMuted": False,
                    "PositionTicks": 0,
                }
            )
            log("Playback started")

        except Exception as e:
            log(f"Failed to start playback: {type(e).__name__}")

        steps = cfg.play_duration // cfg.report_interval
        for i in range(steps):
            await asyncio.sleep(cfg.report_interval)
            elapsed = (i + 1) * cfg.report_interval
            position_ticks = elapsed * 10_000_000

            try:
                await client.post(
                    f"{base_url}/Sessions/Playing/Progress",
                    headers=headers,
                    json={
                        "ItemId": item_id,
                        "PlaySessionId": play_session_id,
                        "PositionTicks": position_ticks,
                        "IsPaused": False,
                        "EventName": "timeupdate",
                    }
                )
                log(f"Progress: {elapsed}s / {cfg.play_duration}s")
            except Exception:
                pass

        try:
            await client.post(
                f"{base_url}/Sessions/Playing/Stopped",
                headers=headers,
                json={
                    "ItemId": item_id,
                    "PlaySessionId": play_session_id,
                    "PositionTicks": cfg.play_duration * 10_000_000,
                }
            )
            log("Playback stopped")

        except Exception:
            pass
