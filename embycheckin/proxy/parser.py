from __future__ import annotations

import base64
from typing import Any
from urllib.parse import parse_qs, urlsplit


def _b64decode_text(value: str) -> str:
    v = (value or "").strip()
    v = v.replace("-", "+").replace("_", "/")
    pad = (-len(v)) % 4
    if pad:
        v += "=" * pad
    return base64.b64decode(v.encode()).decode()


def _first_qs(qs: dict[str, list[str]], key: str) -> str | None:
    values = qs.get(key)
    if not values:
        return None
    v = (values[0] or "").strip()
    return v or None


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes"}


def parse_proxy_url(url: str) -> tuple[str, dict[str, Any] | None]:
    if not url or not str(url).strip():
        raise ValueError("proxy url is empty")

    raw = str(url).strip()
    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()

    if scheme in {"http", "https", "socks5"}:
        return scheme, None

    if scheme == "ss":
        if not parts.hostname or not parts.port:
            raise ValueError("invalid ss url: missing host/port")

        method: str | None = None
        password: str | None = None

        if parts.username and parts.password:
            method = parts.username
            password = parts.password
        elif parts.username and not parts.password:
            decoded = _b64decode_text(parts.username)
            if ":" not in decoded:
                raise ValueError("invalid ss url: base64 must decode to method:password")
            method, password = decoded.split(":", 1)

        if not method or not password:
            raise ValueError("invalid ss url: missing method/password")

        return scheme, {
            "scheme": scheme,
            "server": parts.hostname,
            "server_port": int(parts.port),
            "method": method,
            "password": password,
        }

    if scheme == "vless":
        if not parts.username:
            raise ValueError("invalid vless url: missing uuid")
        if not parts.hostname or not parts.port:
            raise ValueError("invalid vless url: missing host/port")

        qs = parse_qs(parts.query or "", keep_blank_values=True)
        security = (_first_qs(qs, "security") or "").lower() or None
        transport = (_first_qs(qs, "type") or "").lower() or None
        flow = _first_qs(qs, "flow")

        return scheme, {
            "scheme": scheme,
            "uuid": parts.username,
            "server": parts.hostname,
            "server_port": int(parts.port),
            "security": security,
            "sni": _first_qs(qs, "sni"),
            "fp": _first_qs(qs, "fp"),
            "pbk": _first_qs(qs, "pbk"),
            "sid": _first_qs(qs, "sid"),
            "type": transport,
            "flow": flow,
        }

    if scheme == "hysteria2":
        if not parts.hostname or not parts.port:
            raise ValueError("invalid hysteria2 url: missing host/port")

        password = parts.username or parts.password
        if not password:
            raise ValueError("invalid hysteria2 url: missing password")

        qs = parse_qs(parts.query or "", keep_blank_values=True)

        return scheme, {
            "scheme": scheme,
            "server": parts.hostname,
            "server_port": int(parts.port),
            "password": password,
            "sni": _first_qs(qs, "sni"),
            "insecure": _truthy(_first_qs(qs, "insecure")),
        }

    raise ValueError(f"unsupported proxy scheme: {scheme!r}")
