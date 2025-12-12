#!/usr/bin/env python3
"""
浏览器配置器（零第三方依赖）

用途：
- 通过浏览器表单生成 `.env`（包含密钥）与 `docker-compose.local.yml`
- 面向小白：不需要编辑 YAML/环境变量

说明：
- `.env` 已在仓库 `.gitignore` 中忽略，请勿提交密钥
- 默认按“官方协议、非流式”生成配置；高级项（CA/SSL）可选
"""

from __future__ import annotations

import argparse
import html
import os
import textwrap
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse


DEFAULTS: dict[str, Any] = {
    "AI_PROVIDER": "gemini",
    "TZ": "Asia/Shanghai",
    "PHONE_NUMBER": "",
    "SESSION_NAME": "terminus_checkin",
    "CHECKIN_HOUR": "9",
    "CHECKIN_MINUTE": "0",
    "RUN_NOW": "false",
    "AI_SSL_VERIFY": "true",
    "AI_CA_FILE": "",
    "AI_CA_DIR": "",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "gpt-4o-mini",
    "OPENAI_USE_STREAM": "false",
    "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "GEMINI_API_KEY_MODE": "header",
    "GEMINI_USE_STREAM": "false",
    "CLAUDE_BASE_URL": "https://api.anthropic.com",
    "CLAUDE_API_KEY": "",
    "CLAUDE_MODEL": "claude-3-5-sonnet-20241022",
    "CLAUDE_USE_STREAM": "false",
    "CLAUDE_THINKING_ENABLED": "false",
    "CLAUDE_THINKING_BUDGET_TOKENS": "1024",
    "CLAUDE_MAX_TOKENS": "100",
    "PLATFORM_AMD64": "true",
}

UI_VERSION = "2025-12-13.4"


def _to_bool(raw: str, default: bool = False) -> bool:
    if raw is None:
        return default
    val = str(raw).strip().lower()
    if val in {"1", "true", "yes", "y", "on"}:
        return True
    if val in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _env_escape(value: str) -> str:
    """
    docker compose 的 .env 解析较宽松，但为了稳妥：
    - 含空白/#/引号/反斜杠时用双引号包裹并转义
    """
    value = "" if value is None else str(value)
    needs_quote = any(ch.isspace() for ch in value) or any(ch in value for ch in ['#', '"', "\\"])
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f"\"{escaped}\""


def _pick(form: dict[str, str], key: str) -> str:
    val = form.get(key, "")
    if val is None:
        return ""
    return str(val).strip()


def _normalize_provider(provider: str) -> str:
    provider = (provider or "").strip().lower()
    if provider in {"openai", "gemini", "claude"}:
        return provider
    return "gemini"


def _validate(form: dict[str, str]) -> list[str]:
    errors: list[str] = []
    provider = _normalize_provider(form.get("AI_PROVIDER", "gemini"))

    if provider == "openai":
        if not _pick(form, "OPENAI_API_KEY"):
            errors.append("OpenAI：缺少 OPENAI_API_KEY")
        if not _pick(form, "OPENAI_BASE_URL"):
            errors.append("OpenAI：缺少 OPENAI_BASE_URL")
        if not _pick(form, "OPENAI_MODEL"):
            errors.append("OpenAI：缺少 OPENAI_MODEL")
    elif provider == "gemini":
        if not _pick(form, "GEMINI_API_KEY"):
            errors.append("Gemini：缺少 GEMINI_API_KEY")
        if not _pick(form, "GEMINI_BASE_URL"):
            errors.append("Gemini：缺少 GEMINI_BASE_URL")
        if not _pick(form, "GEMINI_MODEL"):
            errors.append("Gemini：缺少 GEMINI_MODEL")
    elif provider == "claude":
        if not _pick(form, "CLAUDE_API_KEY"):
            errors.append("Claude：缺少 CLAUDE_API_KEY")
        if not _pick(form, "CLAUDE_BASE_URL"):
            errors.append("Claude：缺少 CLAUDE_BASE_URL")
        if not _pick(form, "CLAUDE_MODEL"):
            errors.append("Claude：缺少 CLAUDE_MODEL")

    # 基础数值检查（宽松：仅避免空）
    if _pick(form, "CHECKIN_HOUR") == "":
        errors.append("签到时间：缺少 CHECKIN_HOUR")
    if _pick(form, "CHECKIN_MINUTE") == "":
        errors.append("签到时间：缺少 CHECKIN_MINUTE")

    return errors


def _build_env(form: dict[str, str]) -> str:
    provider = _normalize_provider(form.get("AI_PROVIDER", "gemini"))

    env: dict[str, str] = {}
    # 通用
    env["AI_PROVIDER"] = provider
    env["TZ"] = _pick(form, "TZ") or DEFAULTS["TZ"]
    env["PHONE_NUMBER"] = _pick(form, "PHONE_NUMBER")
    env["SESSION_NAME"] = _pick(form, "SESSION_NAME") or DEFAULTS["SESSION_NAME"]
    env["CHECKIN_HOUR"] = _pick(form, "CHECKIN_HOUR") or DEFAULTS["CHECKIN_HOUR"]
    env["CHECKIN_MINUTE"] = _pick(form, "CHECKIN_MINUTE") or DEFAULTS["CHECKIN_MINUTE"]
    env["RUN_NOW"] = "true" if _to_bool(form.get("RUN_NOW", "false")) else "false"

    # TLS（可选）
    env["AI_SSL_VERIFY"] = "true" if _to_bool(form.get("AI_SSL_VERIFY", "true"), True) else "false"
    env["AI_CA_FILE"] = _pick(form, "AI_CA_FILE")
    env["AI_CA_DIR"] = _pick(form, "AI_CA_DIR")

    # 统一：配置文件显式非流式
    env["OPENAI_USE_STREAM"] = "false"
    env["GEMINI_USE_STREAM"] = "false"
    env["CLAUDE_USE_STREAM"] = "false"

    # OpenAI
    env["OPENAI_BASE_URL"] = _pick(form, "OPENAI_BASE_URL") or DEFAULTS["OPENAI_BASE_URL"]
    env["OPENAI_API_KEY"] = _pick(form, "OPENAI_API_KEY")
    env["OPENAI_MODEL"] = _pick(form, "OPENAI_MODEL") or DEFAULTS["OPENAI_MODEL"]

    # Gemini（默认按官方协议用 header）
    env["GEMINI_BASE_URL"] = _pick(form, "GEMINI_BASE_URL") or DEFAULTS["GEMINI_BASE_URL"]
    env["GEMINI_API_KEY"] = _pick(form, "GEMINI_API_KEY")
    env["GEMINI_MODEL"] = _pick(form, "GEMINI_MODEL") or DEFAULTS["GEMINI_MODEL"]
    env["GEMINI_API_KEY_MODE"] = _pick(form, "GEMINI_API_KEY_MODE") or DEFAULTS["GEMINI_API_KEY_MODE"]

    # Claude
    env["CLAUDE_BASE_URL"] = _pick(form, "CLAUDE_BASE_URL") or DEFAULTS["CLAUDE_BASE_URL"]
    env["CLAUDE_API_KEY"] = _pick(form, "CLAUDE_API_KEY")
    env["CLAUDE_MODEL"] = _pick(form, "CLAUDE_MODEL") or DEFAULTS["CLAUDE_MODEL"]
    env["CLAUDE_MAX_TOKENS"] = _pick(form, "CLAUDE_MAX_TOKENS") or DEFAULTS["CLAUDE_MAX_TOKENS"]
    env["CLAUDE_THINKING_ENABLED"] = (
        "true" if _to_bool(form.get("CLAUDE_THINKING_ENABLED", "false")) else "false"
    )
    env["CLAUDE_THINKING_BUDGET_TOKENS"] = (
        _pick(form, "CLAUDE_THINKING_BUDGET_TOKENS") or DEFAULTS["CLAUDE_THINKING_BUDGET_TOKENS"]
    )

    # 输出顺序（更友好）
    ordered_keys = [
        "AI_PROVIDER",
        "TZ",
        "PHONE_NUMBER",
        "SESSION_NAME",
        "CHECKIN_HOUR",
        "CHECKIN_MINUTE",
        "RUN_NOW",
        "AI_SSL_VERIFY",
        "AI_CA_FILE",
        "AI_CA_DIR",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_USE_STREAM",
        "GEMINI_BASE_URL",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GEMINI_API_KEY_MODE",
        "GEMINI_USE_STREAM",
        "CLAUDE_BASE_URL",
        "CLAUDE_API_KEY",
        "CLAUDE_MODEL",
        "CLAUDE_MAX_TOKENS",
        "CLAUDE_THINKING_ENABLED",
        "CLAUDE_THINKING_BUDGET_TOKENS",
        "CLAUDE_USE_STREAM",
    ]

    lines: list[str] = [
        "# 本文件包含密钥，请勿提交到仓库",
        "# 由 tools/config_ui.py 自动生成",
        "",
    ]
    for key in ordered_keys:
        if key not in env:
            continue
        lines.append(f"{key}={_env_escape(env[key])}")
    lines.append("")
    return "\n".join(lines)


def _mask_secret(value: str) -> str:
    value = "" if value is None else str(value)
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


def _build_env_preview(form: dict[str, str]) -> str:
    """
    生成用于页面展示的 .env 预览（对密钥做脱敏）。
    """
    content = _build_env(form)
    lines: list[str] = []
    for line in content.splitlines():
        if "=" not in line or line.strip().startswith("#"):
            lines.append(line)
            continue
        k, v = line.split("=", 1)
        key = k.strip().upper()
        if key.endswith("API_KEY"):
            raw_val = v.strip().strip('"')
            lines.append(f"{k}={_mask_secret(raw_val)}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _build_compose(form: dict[str, str]) -> str:
    platform_amd64 = _to_bool(form.get("PLATFORM_AMD64", "true"), True)
    lines = [
        "services:",
        "  terminus-checkin:",
        "    image: ghcr.io/zj145013/embycheckin:latest",
    ]
    if platform_amd64:
        lines.append("    platform: linux/amd64")
    lines.extend(
        [
            "    container_name: terminus-checkin",
            "    restart: unless-stopped",
            "    ports:",
            '      - "127.0.0.1:8765:8765"',
            "    env_file:",
            "      - .env",
            "    volumes:",
            "      - ./sessions:/app/sessions",
            "      - ./logs:/app/logs",
            "    stdin_open: true",
            "    tty: true",
            "",
        ]
    )
    return "\n".join(lines)


def _page_template(title: str, body_html: str) -> bytes:
    html_doc = f"""<!doctype html>
<html lang="zh-CN" data-theme="light">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>{html.escape(title)}</title>
    <style>
      :root {{
        color-scheme: light dark;
        --bg0: rgba(255,255,255,.70);
        --bg1: rgba(255,255,255,.55);
        --border: rgba(127,127,127,.28);
        --shadow: 0 16px 60px rgba(0,0,0,.18);
        --primary: #2563eb;
        --primary2: #7c3aed;
        --danger: #ef4444;
        --muted: rgba(127,127,127,.9);
        --page0: #f6f8ff;
        --page1: rgba(15,23,42,.06);
        --grid: rgba(15,23,42,.06);
      }}
      *, *::before, *::after {{ box-sizing: border-box; }}
      /* 主题：
         - 默认 light（避免整体偏黑）
         - dark：手动暗色
         - auto：跟随系统
      */
      html[data-theme="dark"] {{
        --bg0: rgba(17,24,39,.56);
        --bg1: rgba(17,24,39,.42);
        --border: rgba(148,163,184,.22);
        --shadow: 0 18px 70px rgba(0,0,0,.45);
        --muted: rgba(226,232,240,.78);
        --page0: #0b1222;
        --page1: rgba(148,163,184,.12);
        --grid: rgba(226,232,240,.08);
      }}
      html[data-theme="auto"] {{
        /* auto 默认为 light，暗色系统下由 media query 覆盖 */
      }}
      @media (prefers-color-scheme: dark) {{
        html[data-theme="auto"] {{
          --bg0: rgba(17,24,39,.56);
          --bg1: rgba(17,24,39,.42);
          --border: rgba(148,163,184,.22);
          --shadow: 0 18px 70px rgba(0,0,0,.45);
          --muted: rgba(226,232,240,.78);
          --page0: #0b1222;
          --page1: rgba(148,163,184,.12);
          --grid: rgba(226,232,240,.08);
        }}
      }}
      body {{
        font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;
        margin: 0;
        line-height: 1.55;
        min-height: 100vh;
        background:
          radial-gradient(900px 420px at 18% 8%, rgba(37,99,235,.38), transparent 62%),
          radial-gradient(880px 420px at 84% 6%, rgba(124,58,237,.34), transparent 60%),
          radial-gradient(1200px 560px at 50% 100%, rgba(14,165,233,.22), transparent 60%),
          radial-gradient(900px 520px at 50% 40%, rgba(34,197,94,.10), transparent 70%),
          linear-gradient(180deg, rgba(255,255,255,.35), transparent 55%),
          var(--page0);
        background-attachment: fixed;
      }}
      body::before {{
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background:
          repeating-linear-gradient(
            0deg,
            transparent 0 23px,
            var(--grid) 23px 24px
          ),
          repeating-linear-gradient(
            90deg,
            transparent 0 23px,
            var(--grid) 23px 24px
          );
        opacity: .55;
        mask-image: radial-gradient(circle at 22% 12%, rgba(0,0,0,1), rgba(0,0,0,0) 68%);
      }}
      body::after {{
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background:
          radial-gradient(600px 240px at 40% 14%, rgba(255,255,255,.10), transparent 70%),
          radial-gradient(520px 220px at 78% 18%, rgba(255,255,255,.08), transparent 72%),
          radial-gradient(520px 240px at 58% 86%, rgba(255,255,255,.06), transparent 70%);
        opacity: .6;
        mix-blend-mode: overlay;
      }}
      .wrap {{ padding: 28px 18px 48px; }}
      .card {{
        max-width: 1060px;
        margin: 0 auto;
        padding: 24px 24px;
        border: 1px solid var(--border);
        border-radius: 18px;
        background: linear-gradient(180deg, var(--bg0), var(--bg1));
        backdrop-filter: blur(10px);
        box-shadow: var(--shadow);
        position: relative;
      }}
      .card::before {{
        content: "";
        position: absolute;
        inset: 0;
        border-radius: 18px;
        padding: 1px;
        background: linear-gradient(
          135deg,
          rgba(37,99,235,.55),
          rgba(124,58,237,.50),
          rgba(14,165,233,.42)
        );
        -webkit-mask:
          linear-gradient(#000 0 0) content-box,
          linear-gradient(#000 0 0);
        -webkit-mask-composite: xor;
        mask-composite: exclude;
        pointer-events: none;
        opacity: .65;
      }}
      .header {{ display:flex; align-items:flex-start; justify-content: space-between; gap: 18px; margin-bottom: 14px; }}
      h1 {{ font-size: 20px; margin: 0; letter-spacing: .2px; }}
      .tagline {{ font-size: 13px; opacity: .80; margin: 4px 0 0; }}
      .steps {{ display:flex; gap: 10px; flex-wrap: wrap; justify-content:flex-end; }}
      .step {{
        font-size: 12px; padding: 6px 10px; border-radius: 999px;
        border: 1px solid var(--border); background: rgba(255,255,255,.22);
      }}
      .step b {{ font-weight: 800; }}
      .toolbar {{ display:flex; gap: 10px; align-items:center; justify-content:flex-end; flex-wrap: wrap; }}
      .seg {{
        display:flex;
        border: 1px solid var(--border);
        border-radius: 999px;
        overflow: hidden;
        background: rgba(255,255,255,.16);
      }}
      .seg button {{
        padding: 7px 10px;
        border-radius: 0;
        border: 0;
        background: transparent;
        color: inherit;
        font-weight: 800;
        cursor: pointer;
      }}
      .seg button.active {{
        background: linear-gradient(135deg, rgba(37,99,235,.28), rgba(124,58,237,.22));
      }}
      h2 {{ font-size: 14px; margin: 18px 0 10px; }}
      .section {{
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 14px 14px;
        background: rgba(255,255,255,.16);
      }}
      label {{ display: block; font-weight: 700; margin: 10px 0 6px; font-size: 13px; }}
      .hint {{ font-size: 12px; opacity: .78; margin-top: 4px; color: var(--muted); }}
      input, select {{
        width: 100%;
        padding: 10px 12px;
        border-radius: 12px;
        border: 1px solid var(--border);
        background: rgba(255,255,255,.12);
        outline: none;
        min-width: 0;
      }}
      input:focus, select:focus {{
        border-color: rgba(37,99,235,.55);
        box-shadow: 0 0 0 3px rgba(37,99,235,.18);
      }}
      .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
      .row > div {{ min-width: 0; }}
      @media (max-width: 860px) {{ .row {{ grid-template-columns: 1fr; }} .steps {{ justify-content:flex-start; }} }}
      .muted {{ opacity: .75; font-size: 13px; }}
      .actions {{ display: flex; gap: 10px; align-items: center; margin-top: 16px; flex-wrap: wrap; }}
      button {{
        padding: 10px 14px;
        border-radius: 12px;
        border: 1px solid rgba(37,99,235,.35);
        background: linear-gradient(135deg, var(--primary), var(--primary2));
        color: white; font-weight: 800; cursor: pointer;
      }}
      button.secondary {{
        background: transparent;
        color: inherit;
        border-color: var(--border);
        font-weight: 700;
      }}
      button.secondary:hover {{ border-color: rgba(37,99,235,.35); }}
      .err {{ background: rgba(239,68,68,.10); border: 1px solid rgba(239,68,68,.25); padding: 10px 12px; border-radius: 12px; }}
      code, pre {{ font-family: ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace; }}
      pre {{ padding: 12px; border-radius: 12px; border: 1px solid var(--border); overflow: auto; background: rgba(255,255,255,.12); }}
      .hidden {{ display: none; }}
      .check {{ display:flex; gap:10px; align-items:center; margin-top:10px; }}
      .check input {{ width:auto; }}
      .pill {{
        display:inline-block; padding: 6px 10px; border-radius: 999px;
        border: 1px solid var(--border); background: rgba(255,255,255,.18);
        font-size: 12px; opacity: .85;
      }}
      .pw-wrap {{
        display: flex;
        align-items: center;
        gap: 10px;
      }}
      .pw-wrap input {{
        flex: 1;
      }}
      .pw-btn {{
        padding: 9px 12px;
        border-radius: 12px;
        border: 1px solid var(--border);
        background: rgba(255,255,255,.14);
        color: inherit;
        font-weight: 800;
        cursor: pointer;
        white-space: nowrap;
      }}
      .pw-btn:hover {{ border-color: rgba(37,99,235,.35); }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        {body_html}
      </div>
    </div>
  </body>
</html>
"""
    return html_doc.encode("utf-8")


def _render_form(values: dict[str, str], errors: Optional[list[str]] = None) -> bytes:
    provider = _normalize_provider(values.get("AI_PROVIDER", DEFAULTS["AI_PROVIDER"]))
    err_html = ""
    if errors:
        items = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
        err_html = f"<div class='err'><b>请修正以下问题：</b><ul>{items}</ul></div>"

    def v(key: str) -> str:
        return html.escape(values.get(key, DEFAULTS.get(key, "")) or "")

    def selected(key: str, option: str) -> str:
        return "selected" if (values.get(key, DEFAULTS.get(key, "")) == option) else ""

    def checked(key: str) -> str:
        return "checked" if _to_bool(values.get(key, DEFAULTS.get(key, "false"))) else ""

    body = f"""
<div class="header">
  <div>
    <h1>EmbyCheckin 可视化配置器</h1>
    <div class="tagline">生成 <code>.env</code>（含密钥）与 <code>docker-compose.local.yml</code>，默认按官方协议、非流式。</div>
    <div class="tagline">为避免刷新丢失，页面会把填写内容保存在本机浏览器（localStorage）；点“重置为默认”可清空。</div>
    <div class="tagline">版本：<code>{html.escape(UI_VERSION)}</code></div>
  </div>
  <div class="toolbar">
    <div class="seg" aria-label="主题切换">
      <button type="button" id="theme_light" onclick="setTheme('light')">亮色</button>
      <button type="button" id="theme_auto" onclick="setTheme('auto')">自动</button>
      <button type="button" id="theme_dark" onclick="setTheme('dark')">暗色</button>
    </div>
    <div class="steps">
      <div class="step"><b>1</b> 填写配置</div>
      <div class="step"><b>2</b> 生成文件</div>
      <div class="step"><b>3</b> docker compose 启动</div>
    </div>
  </div>
</div>
{err_html}
<form method="post" action="/generate">
  <div class="section">
  <h2>基础</h2>
  <div class="row">
    <div>
      <label>AI 提供方（AI_PROVIDER）</label>
      <select name="AI_PROVIDER" id="AI_PROVIDER" onchange="toggleProvider()">
        <option value="gemini" {selected("AI_PROVIDER","gemini")}>gemini</option>
        <option value="openai" {selected("AI_PROVIDER","openai")}>openai</option>
        <option value="claude" {selected("AI_PROVIDER","claude")}>claude</option>
      </select>
      <div class="hint">按“官方协议”调用，仅 BASE_URL 不同。</div>
    </div>
    <div>
      <label>时区（TZ）</label>
      <input name="TZ" value="{v("TZ")}" placeholder="Asia/Shanghai" />
      <div class="hint">默认 Asia/Shanghai；VPS 在海外也可自行调整。</div>
    </div>
  </div>

  <div class="row">
    <div>
      <label>手机号（PHONE_NUMBER，首次登录需要，可留空）</label>
      <input name="PHONE_NUMBER" value="{v("PHONE_NUMBER")}" placeholder="+8613800138000" />
      <div class="hint">首次交互式登录需要；登录成功后可留空。</div>
    </div>
    <div>
      <label>会话名（SESSION_NAME）</label>
      <input name="SESSION_NAME" value="{v("SESSION_NAME")}" />
      <div class="hint">用于持久化会话文件名（sessions/ 目录）。</div>
    </div>
  </div>

  <div class="row">
    <div>
      <label>签到时间（CHECKIN_HOUR）</label>
      <input name="CHECKIN_HOUR" value="{v("CHECKIN_HOUR")}" />
    </div>
    <div>
      <label>签到时间（CHECKIN_MINUTE）</label>
      <input name="CHECKIN_MINUTE" value="{v("CHECKIN_MINUTE")}" />
    </div>
  </div>

  <div class="check">
    <input type="checkbox" name="RUN_NOW" value="true" {checked("RUN_NOW")} />
    <span>启动后立即签到（RUN_NOW=true，不推荐长期开启）</span>
  </div>
  </div>

  <div class="section" style="margin-top:14px;">
  <h2>TLS（可选）</h2>
  <div class="check">
    <input type="checkbox" name="AI_SSL_VERIFY" value="true" {checked("AI_SSL_VERIFY")} />
    <span>启用证书校验（AI_SSL_VERIFY=true，推荐）</span>
  </div>
  <div class="row">
    <div>
      <label>自定义 CA 文件（AI_CA_FILE，可选）</label>
      <input name="AI_CA_FILE" value="{v("AI_CA_FILE")}" placeholder="/path/to/ca.pem" />
      <div class="hint">企业代理/自签证书时使用，优先配置 CA 而不是关闭校验。</div>
    </div>
    <div>
      <label>自定义 CA 目录（AI_CA_DIR，可选）</label>
      <input name="AI_CA_DIR" value="{v("AI_CA_DIR")}" placeholder="/path/to/certs" />
      <div class="hint">目录内应包含 CA 证书文件。</div>
    </div>
  </div>
  </div>

  <div class="section" style="margin-top:14px;">
  <h2>提供方配置 <span class="pill">只需要改 BASE_URL / KEY / MODEL</span></h2>

  <div id="provider_openai" class="{'' if provider=='openai' else 'hidden'}">
    <label>OpenAI Base URL（OPENAI_BASE_URL）</label>
    <input name="OPENAI_BASE_URL" value="{v("OPENAI_BASE_URL")}" />
    <label>OpenAI Key（OPENAI_API_KEY）</label>
    <div class="pw-wrap">
      <input id="OPENAI_API_KEY" type="password" name="OPENAI_API_KEY" value="{v("OPENAI_API_KEY")}" placeholder="sk-..." autocomplete="off" />
      <button type="button" class="pw-btn" onclick="toggleSecret('OPENAI_API_KEY')">显示</button>
    </div>
    <label>模型（OPENAI_MODEL）</label>
    <input name="OPENAI_MODEL" value="{v("OPENAI_MODEL")}" />
    <p class="muted">说明：脚本固定使用 <code>/chat/completions</code>；只需要把 BASE_URL 指到 <code>.../v1</code> 即可。</p>
  </div>

  <div id="provider_gemini" class="{'' if provider=='gemini' else 'hidden'}">
    <label>Gemini Base URL（GEMINI_BASE_URL）</label>
    <input name="GEMINI_BASE_URL" value="{v("GEMINI_BASE_URL")}" />
    <label>Gemini Key（GEMINI_API_KEY）</label>
    <div class="pw-wrap">
      <input id="GEMINI_API_KEY" type="password" name="GEMINI_API_KEY" value="{v("GEMINI_API_KEY")}" placeholder="AIza... 或 sk-..." autocomplete="off" />
      <button type="button" class="pw-btn" onclick="toggleSecret('GEMINI_API_KEY')">显示</button>
    </div>
    <label>模型（GEMINI_MODEL）</label>
    <input name="GEMINI_MODEL" value="{v("GEMINI_MODEL")}" />
    <input type="hidden" name="GEMINI_API_KEY_MODE" value="{v("GEMINI_API_KEY_MODE") or "header"}" />
    <p class="muted">说明：默认用 <code>x-goog-api-key</code> 头鉴权（GEMINI_API_KEY_MODE=header）。</p>
  </div>

  <div id="provider_claude" class="{'' if provider=='claude' else 'hidden'}">
    <label>Claude Base URL（CLAUDE_BASE_URL）</label>
    <input name="CLAUDE_BASE_URL" value="{v("CLAUDE_BASE_URL")}" />
    <label>Claude Key（CLAUDE_API_KEY）</label>
    <div class="pw-wrap">
      <input id="CLAUDE_API_KEY" type="password" name="CLAUDE_API_KEY" value="{v("CLAUDE_API_KEY")}" placeholder="sk-..." autocomplete="off" />
      <button type="button" class="pw-btn" onclick="toggleSecret('CLAUDE_API_KEY')">显示</button>
    </div>
    <label>模型（CLAUDE_MODEL）</label>
    <input name="CLAUDE_MODEL" value="{v("CLAUDE_MODEL")}" />
    <div class="row">
      <div>
        <label>最大输出（CLAUDE_MAX_TOKENS）</label>
        <input name="CLAUDE_MAX_TOKENS" value="{v("CLAUDE_MAX_TOKENS")}" />
      </div>
      <div>
        <label>thinking 预算（可选，CLAUDE_THINKING_BUDGET_TOKENS）</label>
        <input name="CLAUDE_THINKING_BUDGET_TOKENS" value="{v("CLAUDE_THINKING_BUDGET_TOKENS")}" />
      </div>
    </div>
    <div class="check">
      <input type="checkbox" name="CLAUDE_THINKING_ENABLED" value="true" {checked("CLAUDE_THINKING_ENABLED")} />
      <span>启用 thinking（CLAUDE_THINKING_ENABLED=true，可选）</span>
    </div>
  </div>
  </div>

  <div class="section" style="margin-top:14px;">
  <h2>Docker</h2>
  <div class="check">
    <input type="checkbox" name="PLATFORM_AMD64" value="true" {checked("PLATFORM_AMD64")} />
    <span>强制使用 linux/amd64（Apple Silicon 推荐勾选，镜像通常仅提供 amd64）</span>
  </div>
  <div class="check">
    <input type="checkbox" name="FORCE_OVERWRITE" value="true" />
    <span>覆盖写入（如果目标文件已存在）</span>
  </div>

  <div class="actions">
    <button type="submit">生成配置文件</button>
    <button type="button" class="secondary" onclick="resetAll()">重置为默认</button>
  </div>
</div>
</form>

<script>
const STORAGE_KEY = "EmbyCheckin.ConfigUI.v1";
const THEME_KEY = "EmbyCheckin.ConfigUI.theme";

function toggleProvider() {{
  const v = document.getElementById('AI_PROVIDER').value;
  document.getElementById('provider_openai').classList.toggle('hidden', v !== 'openai');
  document.getElementById('provider_gemini').classList.toggle('hidden', v !== 'gemini');
  document.getElementById('provider_claude').classList.toggle('hidden', v !== 'claude');
}}

function toggleSecret(id) {{
  const el = document.getElementById(id);
  if (!el) return;
  el.type = (el.type === 'password') ? 'text' : 'password';
  const btn = el.parentElement && el.parentElement.querySelector('.pw-btn');
  if (btn) btn.textContent = (el.type === 'password') ? '显示' : '隐藏';
}}

function saveForm() {{
  try {{
    const data = {{}};
    document.querySelectorAll('input, select').forEach((el) => {{
      if (!el.name) return;
      if (el.type === 'checkbox') {{
        data[el.name] = el.checked ? 'true' : 'false';
      }} else {{
        data[el.name] = el.value;
      }}
    }});
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  }} catch (e) {{
    // 忽略（例如无权限的隐私模式）
  }}
}}

function loadForm() {{
  try {{
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    document.querySelectorAll('input, select').forEach((el) => {{
      if (!el.name) return;
      if (!(el.name in data)) return;
      if (el.type === 'checkbox') {{
        el.checked = (String(data[el.name]).toLowerCase() === 'true');
      }} else {{
        el.value = data[el.name];
      }}
    }});
  }} catch (e) {{
    // 忽略
  }}
}}

function resetAll() {{
  try {{ localStorage.removeItem(STORAGE_KEY); }} catch (e) {{}}
  window.location.href = '/';
}}

function applyTheme(theme) {{
  const t = theme || 'light';
  document.documentElement.setAttribute('data-theme', t);
  ['light','auto','dark'].forEach((x) => {{
    const btn = document.getElementById('theme_' + x);
    if (btn) btn.classList.toggle('active', x === t);
  }});
}}

function setTheme(theme) {{
  try {{ localStorage.setItem(THEME_KEY, theme); }} catch (e) {{}}
  applyTheme(theme);
}}

window.addEventListener('DOMContentLoaded', () => {{
  // 默认亮色：避免“看起来偏黑”，用户可手动切到暗色或自动
  let theme = 'light';
  try {{
    const t = localStorage.getItem(THEME_KEY);
    if (t === 'light' || t === 'auto' || t === 'dark') theme = t;
  }} catch (e) {{}}
  applyTheme(theme);

  loadForm();
  toggleProvider();
  document.querySelectorAll('input, select').forEach((el) => {{
    el.addEventListener('input', saveForm);
    el.addEventListener('change', saveForm);
  }});
}});
</script>
"""
    return _page_template("EmbyCheckin 可视化配置器", body)


def _render_success(output_dir: str) -> bytes:
    body = f"""
<div class="header">
  <div>
    <h1>已生成配置文件</h1>
    <div class="tagline">输出目录：<code>{html.escape(output_dir)}</code></div>
  </div>
  <div class="steps">
    <div class="step"><b>✓</b> 生成完成</div>
  </div>
</div>
<ul>
  <li><code>.env</code></li>
  <li><code>docker-compose.local.yml</code></li>
</ul>
<h2>下一步</h2>
<pre id="cmd">docker compose -f docker-compose.local.yml up -d
# 或旧版
docker-compose -f docker-compose.local.yml up -d</pre>
<div class="actions">
  <button type="button" onclick="copyText('cmd')">复制启动命令</button>
  <button type="button" class="secondary" onclick="window.location.href='/'">返回继续修改</button>
</div>
<p class="muted">提示：<code>.env</code> 含密钥，已被 .gitignore 忽略，请勿提交。</p>
<p class="muted">提示：返回后会从本机浏览器（localStorage）恢复你上次填写的内容。</p>
"""
    return _page_template("生成成功", body)


class _Handler(BaseHTTPRequestHandler):
    server_version = "EmbyCheckinConfigUI/1.0"

    def _safe_write(self, payload: bytes) -> None:
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/", "/index.html"}:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._safe_write("404 Not Found".encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._safe_write(_render_form(DEFAULTS))

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/generate":
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._safe_write("404 Not Found".encode("utf-8"))
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        parsed = parse_qs(raw, keep_blank_values=True)
        form: dict[str, str] = {k: (v[0] if v else "") for k, v in parsed.items()}

        # checkbox：未勾选时字段不存在，这里补默认
        for k in ["RUN_NOW", "AI_SSL_VERIFY", "PLATFORM_AMD64", "CLAUDE_THINKING_ENABLED", "FORCE_OVERWRITE"]:
            if k not in form:
                form[k] = "false"

        errors = _validate(form)
        if errors:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._safe_write(_render_form({**DEFAULTS, **form}, errors))
            return

        output_dir = getattr(self.server, "output_dir", os.getcwd())
        force = _to_bool(form.get("FORCE_OVERWRITE", "false"))

        env_path = os.path.join(output_dir, ".env")
        compose_path = os.path.join(output_dir, "docker-compose.local.yml")

        for path in [env_path, compose_path]:
            if os.path.exists(path) and not force:
                self.send_response(409)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self._safe_write(
                    _render_form(
                        {**DEFAULTS, **form},
                        [f"文件已存在：{path}（勾选“覆盖写入”后再生成）"],
                    )
                )
                return

        os.makedirs(output_dir, exist_ok=True)
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(_build_env(form))
        with open(compose_path, "w", encoding="utf-8") as f:
            f.write(_build_compose(form))

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._safe_write(
            _page_template(
                "生成成功",
                _render_success_body(output_dir, form),
            )
        )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # 保持终端输出简洁
        return


def run_server(host: str, port: int, output_dir: str) -> None:
    """
    启动配置器 HTTP 服务（便于在 Docker 入口脚本里复用）。
    """
    output_dir = os.path.abspath(output_dir)
    httpd = HTTPServer((host, port), _Handler)
    setattr(httpd, "output_dir", output_dir)
    url = f"http://{host}:{port}/"
    print(f"配置器已启动：{url}")
    print(f"输出目录：{output_dir}")
    print("按 Ctrl+C 退出")
    httpd.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="EmbyCheckin 可视化配置器（浏览器页面，零第三方依赖）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765）")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="输出目录（生成 .env 与 docker-compose.local.yml，默认当前目录）",
    )
    args = parser.parse_args()

    try:
        run_server(args.host, args.port, args.output_dir)
    except KeyboardInterrupt:
        pass
    return 0


def _render_success_body(output_dir: str, form: dict[str, str]) -> str:
    env_preview = html.escape(_build_env_preview(form))
    compose_preview = html.escape(_build_compose(form))
    return f"""
<div class="header">
  <div>
    <h1>已生成配置文件</h1>
    <div class="tagline">输出目录：<code>{html.escape(output_dir)}</code></div>
    <div class="tagline">版本：<code>{html.escape(UI_VERSION)}</code></div>
  </div>
  <div class="steps">
    <div class="step"><b>✓</b> 生成完成</div>
  </div>
</div>
<ul>
  <li><code>.env</code>（预览已脱敏）</li>
  <li><code>docker-compose.local.yml</code></li>
</ul>

<h2>启动命令</h2>
<pre id="cmd">docker compose -f docker-compose.local.yml up -d
# 或旧版
docker-compose -f docker-compose.local.yml up -d</pre>
<div class="actions">
  <button type="button" onclick="copyText('cmd')">复制启动命令</button>
  <button type="button" class="secondary" onclick="window.location.href='/'">返回继续修改</button>
</div>

<h2>.env 预览（脱敏）</h2>
<pre id="env_preview">{env_preview}</pre>
<div class="actions">
  <button type="button" class="secondary" onclick="copyText('env_preview')">复制 .env 预览</button>
</div>

<h2>docker-compose.local.yml 预览</h2>
<pre id="compose_preview">{compose_preview}</pre>
<div class="actions">
  <button type="button" class="secondary" onclick="copyText('compose_preview')">复制 compose 预览</button>
</div>

<p class="muted">提示：<code>.env</code> 含密钥，已被 .gitignore 忽略，请勿提交。</p>
<p class="muted">提示：返回后会从本机浏览器（localStorage）恢复你上次填写的内容。</p>

<script>
function copyText(id) {{
  const el = document.getElementById(id);
  if (!el) return;
  const txt = el.innerText || el.textContent || '';
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(txt);
    return;
  }}
  const ta = document.createElement('textarea');
  ta.value = txt;
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
}}
</script>
"""


if __name__ == "__main__":
    raise SystemExit(main())
