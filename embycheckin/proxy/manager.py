from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import socket
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from loguru import logger

from .parser import parse_proxy_url


def _pick_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def _redact_proxy_url(url: str) -> str:
    try:
        p = urlsplit(url)
        if p.hostname and p.port:
            return f"{p.scheme}://...@{p.hostname}:{p.port}"
    except Exception:
        pass
    return "proxy://..."


def _generate_singbox_config(parsed: dict[str, Any], local_port: int) -> dict[str, Any]:
    scheme = parsed["scheme"]
    outbound: dict[str, Any]

    if scheme == "ss":
        outbound = {
            "type": "shadowsocks",
            "tag": "proxy",
            "server": parsed["server"],
            "server_port": parsed["server_port"],
            "method": parsed["method"],
            "password": parsed["password"],
        }
    elif scheme == "vless":
        outbound = {
            "type": "vless",
            "tag": "proxy",
            "server": parsed["server"],
            "server_port": parsed["server_port"],
            "uuid": parsed["uuid"],
        }
        if parsed.get("flow"):
            outbound["flow"] = parsed["flow"]

        transport = parsed.get("type")
        if transport:
            outbound["transport"] = {"type": transport}

        security = parsed.get("security")
        if security:
            tls: dict[str, Any] = {"enabled": True}
            if parsed.get("sni"):
                tls["server_name"] = parsed["sni"]
            if parsed.get("fp"):
                tls["utls"] = {"enabled": True, "fingerprint": parsed["fp"]}
            if security == "reality":
                reality: dict[str, Any] = {"enabled": True}
                if parsed.get("pbk"):
                    reality["public_key"] = parsed["pbk"]
                if parsed.get("sid"):
                    reality["short_id"] = parsed["sid"]
                tls["reality"] = reality
            outbound["tls"] = tls
    elif scheme == "hysteria2":
        tls: dict[str, Any] = {"enabled": True}
        if parsed.get("sni"):
            tls["server_name"] = parsed["sni"]
        if parsed.get("insecure"):
            tls["insecure"] = True
        outbound = {
            "type": "hysteria2",
            "tag": "proxy",
            "server": parsed["server"],
            "server_port": parsed["server_port"],
            "password": parsed["password"],
            "tls": tls,
        }
    else:
        raise ValueError(f"unsupported scheme: {scheme}")

    return {
        "log": {"disabled": True},
        "inbounds": [{
            "type": "socks",
            "tag": "socks-in",
            "listen": "127.0.0.1",
            "listen_port": local_port,
        }],
        "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
        "route": {"rules": [{"inbound": ["socks-in"], "outbound": "proxy"}]},
    }


class LocalProxyRunner:
    def __init__(
        self,
        proxy_url: str,
        singbox_path: str | None = None,
        start_timeout: float = 8.0,
    ) -> None:
        self._proxy_url = proxy_url
        self._singbox_path = singbox_path or os.environ.get("SINGBOX_PATH") or "sing-box"
        self._start_timeout = start_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._temp_dir: str | None = None
        self._local_url: str | None = None

    async def __aenter__(self) -> str:
        scheme, parsed = parse_proxy_url(self._proxy_url)
        if parsed is None:
            return self._proxy_url

        port = _pick_free_port()
        cfg = _generate_singbox_config(parsed, port)

        self._temp_dir = tempfile.mkdtemp(prefix="embycheckin-proxy-")
        config_path = Path(self._temp_dir) / "config.json"
        config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

        logger.info(f"Starting sing-box for {_redact_proxy_url(self._proxy_url)}")

        try:
            self._proc = await asyncio.create_subprocess_exec(
                self._singbox_path, "run", "-c", str(config_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as e:
            await self._cleanup()
            raise RuntimeError(f"sing-box not found: {self._singbox_path}") from e

        self._local_url = f"socks5://127.0.0.1:{port}"
        await self._wait_ready(port)
        return self._local_url

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._cleanup()

    async def _wait_ready(self, port: int) -> None:
        deadline = asyncio.get_running_loop().time() + self._start_timeout
        while asyncio.get_running_loop().time() < deadline:
            if self._proc and self._proc.returncode is not None:
                raise RuntimeError("sing-box exited unexpectedly")
            try:
                r, w = await asyncio.open_connection("127.0.0.1", port)
                w.close()
                await w.wait_closed()
                return
            except OSError:
                await asyncio.sleep(0.1)
        raise RuntimeError(f"sing-box not ready within {self._start_timeout}s")

    async def _cleanup(self) -> None:
        proc = self._proc
        self._proc = None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                with contextlib.suppress(Exception):
                    await proc.wait()

        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
