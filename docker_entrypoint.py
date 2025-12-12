#!/usr/bin/env python3
"""
Docker 入口脚本（首次部署友好）：

- 启动时先检查配置是否缺失/明显不正确
- 若缺失/不正确：不执行签到，改为启动可视化配置器（容器内）
- 若配置正确：正常运行 checkin 主程序

约定：
- 配置器默认监听 0.0.0.0:8765，可通过 CONFIG_UI_PORT 调整
- 配置器生成的文件默认写到 /app（可通过 CONFIG_UI_OUTPUT_DIR 调整）
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in {"1", "true", "yes", "y", "on"}:
        return True
    if val in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _validate_config() -> list[str]:
    errors: list[str] = []

    provider = _env("AI_PROVIDER", "openai").lower()
    if provider not in {"openai", "gemini", "claude"}:
        errors.append(f"AI_PROVIDER 值非法：{provider!r}（应为 openai/gemini/claude）")
        provider = "openai"

    # TLS 可选：若配置了 CA 路径则要求存在（避免“配置不正确”）
    ca_file = _env("AI_CA_FILE")
    if ca_file and not os.path.isfile(ca_file):
        errors.append(f"AI_CA_FILE 指向的文件不存在：{ca_file}")
    ca_dir = _env("AI_CA_DIR")
    if ca_dir and not os.path.isdir(ca_dir):
        errors.append(f"AI_CA_DIR 指向的目录不存在：{ca_dir}")

    # 提供方必填项（尽量与 checkin.py 的容错一致）
    if provider == "openai":
        openai_api_key = _env("OPENAI_API_KEY")
        legacy_key = _env("GEMINI_API_KEY")
        if not (openai_api_key or legacy_key):
            errors.append("OpenAI：缺少 OPENAI_API_KEY（或旧变量 GEMINI_API_KEY）")
        if not (_env("OPENAI_BASE_URL") or _env("GEMINI_BASE_URL")):
            errors.append("OpenAI：缺少 OPENAI_BASE_URL（或旧变量 GEMINI_BASE_URL）")
        if not (_env("OPENAI_MODEL") or _env("GEMINI_MODEL")):
            errors.append("OpenAI：缺少 OPENAI_MODEL（或旧变量 GEMINI_MODEL）")
    elif provider == "gemini":
        if not _env("GEMINI_API_KEY"):
            errors.append("Gemini：缺少 GEMINI_API_KEY")
        if not _env("GEMINI_BASE_URL"):
            errors.append("Gemini：缺少 GEMINI_BASE_URL")
        if not _env("GEMINI_MODEL"):
            errors.append("Gemini：缺少 GEMINI_MODEL")
    elif provider == "claude":
        if not _env("CLAUDE_API_KEY"):
            errors.append("Claude：缺少 CLAUDE_API_KEY")
        if not _env("CLAUDE_BASE_URL"):
            errors.append("Claude：缺少 CLAUDE_BASE_URL")
        if not _env("CLAUDE_MODEL"):
            errors.append("Claude：缺少 CLAUDE_MODEL")

    return errors


def _start_config_ui(errors: list[str]) -> None:
    from tools.config_ui import run_server

    port = int(_env("CONFIG_UI_PORT", "8765") or "8765")
    output_dir = _env("CONFIG_UI_OUTPUT_DIR", "/app") or "/app"

    sys.stderr.write("\n配置缺失或不正确，已进入首次部署配置模式（不会执行签到）。\n")
    for err in errors:
        sys.stderr.write(f"- {err}\n")
    sys.stderr.write("\n请在浏览器打开配置页面，生成配置后重启容器。\n")
    sys.stderr.write("安全默认：建议只在本机/内网访问，VPS 可用 SSH 端口转发。\n\n")

    run_server(host="0.0.0.0", port=port, output_dir=output_dir)


def main() -> int:
    # 显式强制进入配置模式
    if _env_bool("CONFIG_UI_ONLY", False):
        _start_config_ui(["CONFIG_UI_ONLY=true"])
        return 0

    errors = _validate_config()
    if errors:
        _start_config_ui(errors)
        return 0

    import checkin

    asyncio.run(checkin.main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

