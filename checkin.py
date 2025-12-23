#!/usr/bin/env python3
"""
终点站 (Terminus) Telegram 自动签到脚本
使用可选 AI 提供方识别验证码（OpenAI / Gemini / Claude）
"""

import asyncio
import argparse
import base64
import json
import os
import random
import re
import ssl
import sys
from datetime import datetime, time, timedelta
from io import BytesIO
from typing import TYPE_CHECKING, Any, Optional, Tuple

try:
    import httpx
except ModuleNotFoundError as e:
    raise SystemExit(
        "缺少依赖 httpx，无法调用 AI 接口。\n"
        "请先安装最小依赖：pip install 'httpx==0.27.0' 'loguru==0.7.2'\n"
        "或直接使用 Docker 镜像在容器内运行。"
    ) from e

try:
    from loguru import logger
except ModuleNotFoundError as e:
    raise SystemExit(
        "缺少依赖 loguru，无法输出日志。\n"
        "请先安装最小依赖：pip install 'httpx==0.27.0' 'loguru==0.7.2'"
    ) from e

if TYPE_CHECKING:
    from pyrogram import Client  # pragma: no cover
    from pyrogram.types import Message  # pragma: no cover
else:
    Client = Any
    Message = Any

# ==================== 配置 ====================

# Telegram 配置
API_ID = int(os.getenv("API_ID", "2040"))
API_HASH = os.getenv("API_HASH", "b18441a1ff607e10a989891a5462e627")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")  # 首次登录需要

# ==================== AI 提供方选择 ====================
# 支持：openai / gemini / claude
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").strip().lower()

# OpenAI（或 OpenAI 兼容接口）配置
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# Gemini 官方 REST API 配置
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta",
).strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

# Claude（Anthropic）配置
CLAUDE_BASE_URL = os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com").strip()
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022").strip()

# ==================== TLS/证书（httpx）配置 ====================

def _env_get_optional(name: str) -> Optional[str]:
    if name not in os.environ:
        return None
    return os.environ.get(name, "").strip()


def _parse_env_bool(name: str, default: bool) -> bool:
    raw = _env_get_optional(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    logger.warning(f"环境变量 {name} 值非法：{raw!r}，将按默认值 {default} 处理")
    return default


def _parse_env_int(name: str, default: int) -> int:
    raw = _env_get_optional(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"环境变量 {name} 值非法：{raw!r}，将按默认值 {default} 处理")
        return default


def _httpx_verify_from_env(provider: str) -> Tuple[object, Optional[str]]:
    """
    统一处理 httpx TLS 校验配置。

    规则：
    - 默认校验证书（不降低安全基线）
    - 支持通过 CA 文件/目录信任企业代理或自签证书
    - 仅在显式设置 *_SSL_VERIFY=false 时关闭校验（不推荐）

    环境变量（provider 为 OPENAI/GEMINI/CLAUDE）：
    - AI_SSL_VERIFY（全局开关，默认 true）
    - AI_CA_FILE / AI_CA_DIR（全局 CA 文件/目录）
    - {provider}_SSL_VERIFY / {provider}_CA_FILE / {provider}_CA_DIR（单提供方覆盖）
    """
    provider = (provider or "").strip().upper()
    if not provider:
        return True, "TLS 配置错误：provider 为空"

    ssl_verify = _parse_env_bool(
        f"{provider}_SSL_VERIFY",
        _parse_env_bool("AI_SSL_VERIFY", True),
    )
    if not ssl_verify:
        return False, None

    ca_file = _env_get_optional(f"{provider}_CA_FILE")
    if ca_file is None:
        ca_file = _env_get_optional("AI_CA_FILE") or ""
    ca_dir = _env_get_optional(f"{provider}_CA_DIR")
    if ca_dir is None:
        ca_dir = _env_get_optional("AI_CA_DIR") or ""

    if ca_file:
        if not os.path.isfile(ca_file):
            return True, f"{provider}_CA_FILE 指向的文件不存在：{ca_file}"
        return ca_file, None
    if ca_dir:
        if not os.path.isdir(ca_dir):
            return True, f"{provider}_CA_DIR 指向的目录不存在：{ca_dir}"
        return ca_dir, None

    return True, None


def _is_cert_verify_failed(exc: Exception) -> bool:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    msg = str(exc)
    return ("CERTIFICATE_VERIFY_FAILED" in msg) or ("certificate verify failed" in msg.lower())


def _tls_troubleshooting_hint(provider: str) -> str:
    provider = (provider or "").strip().upper()
    return (
        f"{provider} API SSL 证书校验失败（常见于企业代理/自签证书）。"
        f"建议：1) 配置 {provider}_CA_FILE=/path/to/ca.pem 或 {provider}_CA_DIR=/path/to/certs；"
        f"2) 或配置全局 AI_CA_FILE/AI_CA_DIR；"
        f"3) 临时（不推荐）设置 {provider}_SSL_VERIFY=false 关闭校验。"
    )


def _normalize_gemini_base_url(base_url: str) -> str:
    """
    兼容两类写法：
    - 直接给完整版本前缀：https://host/v1beta
    - 只给 host：https://host（将自动补 /v1beta）
    """
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        return "https://generativelanguage.googleapis.com/v1beta"
    if ("/v1beta" in raw) or ("/v1" in raw):
        return raw
    return f"{raw}/v1beta"


def _gemini_auth_mode_from_env() -> str:
    # 官方与多数网关都支持 `x-goog-api-key`，且避免 key 出现在 URL，默认用 header
    mode = os.getenv("GEMINI_API_KEY_MODE", "header").strip().lower()
    if mode not in {"query", "header", "both"}:
        logger.warning(f"环境变量 GEMINI_API_KEY_MODE 值非法：{mode!r}，将回退为 'query'")
        return "query"
    return mode


def _gemini_use_stream_from_env() -> bool:
    return _parse_env_bool("GEMINI_USE_STREAM", False)


def _gemini_extra_headers_from_env() -> dict[str, str]:
    headers: dict[str, str] = {}
    http_referer = _env_get_optional("GEMINI_HTTP_REFERER")
    if http_referer:
        headers["http-referer"] = http_referer
    x_title = _env_get_optional("GEMINI_X_TITLE")
    if x_title:
        headers["x-title"] = x_title
    user_agent = _env_get_optional("GEMINI_USER_AGENT")
    if user_agent:
        headers["user-agent"] = user_agent
    return headers


def _extract_gemini_answer_from_response_obj(obj: dict) -> tuple[str, Optional[str]]:
    candidates = obj.get("candidates") or []
    if not candidates:
        return "", "Gemini 返回为空（无 candidates）"
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text_parts: list[str] = []
    for part in parts:
        if isinstance(part, str):
            text_parts.append(part)
            continue
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            text_parts.append(text)
            continue
        thought = part.get("thought")
        if isinstance(thought, str) and thought.strip():
            text_parts.append(thought)
    return "".join(text_parts).strip(), None


def _extract_gemini_answer_from_sse_text(sse_text: str) -> tuple[str, Optional[str]]:
    """
    解析 `text/event-stream`（SSE）返回：累积所有 data: JSON 片段中的文本。
    """
    accumulated = []
    for raw_line in (sse_text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        chunk, _ = _extract_gemini_answer_from_response_obj(obj)
        if chunk:
            accumulated.append(chunk)
    answer = "".join(accumulated).strip()
    if not answer:
        return "", "Gemini SSE 返回为空（无可解析 data 文本）"
    return answer, None


def _openai_use_stream_from_env() -> bool:
    return _parse_env_bool("OPENAI_USE_STREAM", False)


def _openai_stream_include_usage_from_env() -> bool:
    return _parse_env_bool("OPENAI_STREAM_INCLUDE_USAGE", True)


def _openai_extra_headers_from_env() -> dict[str, str]:
    headers: dict[str, str] = {}
    http_referer = _env_get_optional("OPENAI_HTTP_REFERER")
    if http_referer:
        headers["http-referer"] = http_referer
    x_title = _env_get_optional("OPENAI_X_TITLE")
    if x_title:
        headers["x-title"] = x_title
    user_agent = _env_get_optional("OPENAI_USER_AGENT")
    if user_agent:
        headers["user-agent"] = user_agent
    return headers


def _extract_openai_chat_answer_from_response_obj(obj: dict) -> tuple[str, Optional[str]]:
    choices = obj.get("choices") or []
    if not choices:
        return "", "OpenAI 兼容接口返回为空（无 choices）"
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content") or ""
    return str(content).strip(), None


def _extract_openai_chat_answer_from_sse_text(sse_text: str) -> tuple[str, Optional[str]]:
    """
    解析 OpenAI Chat Completions 的 SSE：累积 choices[].delta.content。
    """
    accumulated: list[str] = []
    for raw_line in (sse_text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        for choice in obj.get("choices") or []:
            delta = (choice or {}).get("delta") or {}
            content = delta.get("content")
            if content:
                accumulated.append(str(content))
    answer = "".join(accumulated).strip()
    if not answer:
        return "", "OpenAI 兼容接口 SSE 返回为空（无可解析 delta.content）"
    return answer, None


def _claude_use_stream_from_env() -> bool:
    return _parse_env_bool("CLAUDE_USE_STREAM", False)


def _claude_extra_headers_from_env() -> dict[str, str]:
    headers: dict[str, str] = {}
    http_referer = _env_get_optional("CLAUDE_HTTP_REFERER")
    if http_referer:
        headers["http-referer"] = http_referer
    x_title = _env_get_optional("CLAUDE_X_TITLE")
    if x_title:
        headers["x-title"] = x_title
    user_agent = _env_get_optional("CLAUDE_USER_AGENT")
    if user_agent:
        headers["user-agent"] = user_agent
    return headers


def _claude_thinking_from_env() -> Optional[dict]:
    if not _parse_env_bool("CLAUDE_THINKING_ENABLED", False):
        return None
    budget = _parse_env_int("CLAUDE_THINKING_BUDGET_TOKENS", 1024)
    return {"type": "enabled", "budget_tokens": budget}


def _extract_claude_answer_from_sse_text(sse_text: str) -> tuple[str, Optional[str]]:
    """
    解析 Anthropic /v1/messages 的 SSE：累积 content_block_* 事件中的文本。
    """
    accumulated: list[str] = []
    for raw_line in (sse_text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue

        event_type = obj.get("type")
        if event_type == "content_block_delta":
            delta = obj.get("delta") or {}
            text = delta.get("text")
            if text:
                accumulated.append(str(text))
        elif event_type == "content_block_start":
            content_block = obj.get("content_block") or {}
            text = content_block.get("text")
            if text:
                accumulated.append(str(text))

    answer = "".join(accumulated).strip()
    if not answer:
        return "", "Claude SSE 返回为空（无可解析 content_block 文本）"
    return answer, None


# 签到配置
BOT_USERNAME = "EmbyPublicBot"
CHECKIN_HOUR = int(os.getenv("CHECKIN_HOUR", "9"))  # 每天签到时间（小时）
CHECKIN_MINUTE = int(os.getenv("CHECKIN_MINUTE", "0"))  # 每天签到时间（分钟）
RETRY_TIMES = int(os.getenv("RETRY_TIMES", "3"))  # 重试次数
SESSION_NAME = os.getenv("SESSION_NAME", "terminus_checkin")

# ==================== 日志配置 ====================

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    level="INFO",
)
logger.add(
    "logs/checkin_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    level="DEBUG",
    rotation="1 day",
    retention="7 days",
)


# ==================== 验证码识别（多提供方） ====================

def _normalize_answer_text(answer: str) -> str:
    cleaned = (answer or "").strip()
    cleaned = cleaned.strip("「」\"'")
    cleaned = re.sub(r"^[选择]?[项]?[:：]?\s*", "", cleaned)
    return cleaned.strip()


def _build_captcha_prompt(options: list[str]) -> str:
    options_text = "、".join([f"「{opt}」" for opt in options])
    return f"""这是一个验证码图片，请仔细观察图片内容。

可选答案有：{options_text}

请根据图片内容，从上述选项中选择最匹配的一个答案。
只需要回复选项内容本身，不要有任何其他文字、标点或解释。

例如，如果答案是「猫」，就只回复：猫"""


def _guess_image_mime_type(image_data: bytes) -> str:
    """
    基于文件头做最小集合的图片类型识别，避免硬编码 image/jpeg 导致 PNG/WebP 截图无法解析。
    """
    if not image_data:
        return "application/octet-stream"
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_data.startswith(b"GIF87a") or image_data.startswith(b"GIF89a"):
        return "image/gif"
    if len(image_data) >= 12 and image_data[0:4] == b"RIFF" and image_data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _openai_compat_config_from_env() -> tuple[str, str, str]:
    """
    OpenAI（或 OpenAI 兼容接口）配置。
    为了兼容旧配置：当 OPENAI_* 未设置时，回退使用 GEMINI_BASE_URL / GEMINI_API_KEY / GEMINI_MODEL。
    """
    base_url = OPENAI_BASE_URL or GEMINI_BASE_URL
    api_key = OPENAI_API_KEY or GEMINI_API_KEY
    model = OPENAI_MODEL or GEMINI_MODEL
    return base_url, api_key, model


async def _analyze_image_openai_compatible(
    image_base64: str,
    prompt: str,
    mime_type: str,
) -> Tuple[Optional[str], Optional[str]]:
    base_url, api_key, model = _openai_compat_config_from_env()
    if not api_key:
        return None, "OPENAI_API_KEY 未配置（或旧变量 GEMINI_API_KEY 未配置）"

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(_openai_extra_headers_from_env())

    use_stream = _openai_use_stream_from_env()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 100,
        "temperature": 0.1,
    }
    reasoning_effort = _env_get_optional("OPENAI_REASONING_EFFORT")
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    verbosity = _env_get_optional("OPENAI_VERBOSITY")
    if verbosity:
        payload["verbosity"] = verbosity
    if use_stream:
        payload["stream"] = True
        if _openai_stream_include_usage_from_env():
            payload["stream_options"] = {"include_usage": True}

    try:
        verify, verify_error = _httpx_verify_from_env("OPENAI")
        if verify_error:
            return None, verify_error

        async with httpx.AsyncClient(timeout=30, verify=verify, trust_env=True) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            if use_stream:
                answer, err = _extract_openai_chat_answer_from_sse_text(response.text)
                if err:
                    return None, err
                return _normalize_answer_text(answer), None

            result = response.json()
            answer, err = _extract_openai_chat_answer_from_response_obj(result)
            if err:
                return None, err
            return _normalize_answer_text(answer), None
    except httpx.HTTPStatusError as e:
        return None, f"OpenAI 兼容接口 HTTP 错误: {e.response.status_code}"
    except Exception as e:
        if _is_cert_verify_failed(e):
            return None, f"{_tls_troubleshooting_hint('OPENAI')} 原始错误：{str(e)}"
        return None, f"OpenAI 兼容接口调用失败: {str(e)}"


async def _analyze_image_gemini_official(
    image_base64: str,
    prompt: str,
    mime_type: str,
) -> Tuple[Optional[str], Optional[str]]:
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY 未配置"

    base_url = _normalize_gemini_base_url(GEMINI_BASE_URL)
    use_stream = _gemini_use_stream_from_env()
    method = "streamGenerateContent" if use_stream else "generateContent"

    # Gemini REST API：
    # - 非流式：POST /v1beta/models/{model}:generateContent
    # - SSE 流式：POST /v1beta/models/{model}:streamGenerateContent?alt=sse
    url = f"{base_url.rstrip('/')}/models/{GEMINI_MODEL}:{method}"
    headers = {"Content-Type": "application/json"}
    headers.update(_gemini_extra_headers_from_env())

    auth_mode = _gemini_auth_mode_from_env()
    params: dict[str, str] = {}
    if use_stream:
        params["alt"] = "sse"
    if auth_mode in {"query", "both"}:
        params["key"] = GEMINI_API_KEY
    if auth_mode in {"header", "both"}:
        headers["x-goog-api-key"] = GEMINI_API_KEY

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": image_base64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 100,
        },
    }

    try:
        verify, verify_error = _httpx_verify_from_env("GEMINI")
        if verify_error:
            return None, verify_error

        async with httpx.AsyncClient(timeout=30, verify=verify, trust_env=True) as client:
            response = await client.post(
                url,
                headers=headers,
                params=params,
                json=payload,
            )
            response.raise_for_status()
            if use_stream:
                answer, err = _extract_gemini_answer_from_sse_text(response.text)
                if err:
                    return None, err
                return _normalize_answer_text(answer), None

            result = response.json()
            answer, err = _extract_gemini_answer_from_response_obj(result)
            if err:
                return None, err
            return _normalize_answer_text(answer), None
    except httpx.HTTPStatusError as e:
        return None, f"Gemini API HTTP 错误: {e.response.status_code}"
    except Exception as e:
        if _is_cert_verify_failed(e):
            return None, f"{_tls_troubleshooting_hint('GEMINI')} 原始错误：{str(e)}"
        return None, f"Gemini API 调用失败: {str(e)}"


async def _analyze_image_claude(
    image_base64: str,
    prompt: str,
    mime_type: str,
) -> Tuple[Optional[str], Optional[str]]:
    if not CLAUDE_API_KEY:
        return None, "CLAUDE_API_KEY 未配置"

    url = f"{CLAUDE_BASE_URL.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    headers.update(_claude_extra_headers_from_env())
    use_stream = _claude_use_stream_from_env()
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": _parse_env_int("CLAUDE_MAX_TOKENS", 100),
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_base64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    thinking = _claude_thinking_from_env()
    if thinking:
        payload["thinking"] = thinking
    if use_stream:
        payload["stream"] = True

    try:
        verify, verify_error = _httpx_verify_from_env("CLAUDE")
        if verify_error:
            return None, verify_error

        async with httpx.AsyncClient(timeout=30, verify=verify, trust_env=True) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            if use_stream:
                answer, err = _extract_claude_answer_from_sse_text(response.text)
                if err:
                    return None, err
                return _normalize_answer_text(answer), None

            result = response.json()
            content = result.get("content") or []
            if not content:
                return None, "Claude 返回为空（无 content）"
            answer = content[0].get("text", "")
            return _normalize_answer_text(answer), None
    except httpx.HTTPStatusError as e:
        return None, f"Claude API HTTP 错误: {e.response.status_code}"
    except Exception as e:
        if _is_cert_verify_failed(e):
            return None, f"{_tls_troubleshooting_hint('CLAUDE')} 原始错误：{str(e)}"
        return None, f"Claude API 调用失败: {str(e)}"

async def analyze_image(
    image_data: bytes,
    options: list[str]
) -> Tuple[Optional[str], Optional[str]]:
    """
    使用可选 AI 提供方分析验证码图片

    Args:
        image_data: 图片二进制数据
        options: 可选的答案列表

    Returns:
        (答案, 错误信息)
    """
    try:
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        mime_type = _guess_image_mime_type(image_data)
        prompt = _build_captcha_prompt(options)

        if AI_PROVIDER == "openai":
            answer, error = await _analyze_image_openai_compatible(image_base64, prompt, mime_type)
        elif AI_PROVIDER == "gemini":
            answer, error = await _analyze_image_gemini_official(image_base64, prompt, mime_type)
        elif AI_PROVIDER == "claude":
            answer, error = await _analyze_image_claude(image_base64, prompt, mime_type)
        else:
            return None, f"不支持的 AI_PROVIDER: {AI_PROVIDER}（应为 openai/gemini/claude）"

        if answer:
            logger.debug(f"AI({AI_PROVIDER}) 原始回答: {answer}")
        return answer, error
    except Exception as e:
        error_msg = f"AI 调用失败: {str(e)}"
        logger.error(error_msg)
        return None, error_msg


def find_best_match(answer: str, options: list[str]) -> Optional[str]:
    """
    从选项中找到最匹配的答案
    """
    if not answer or not options:
        return None

    answer_clean = answer.lower().strip()

    # 精确匹配
    for opt in options:
        if opt.lower().strip() == answer_clean:
            return opt

    # 包含匹配
    for opt in options:
        if answer_clean in opt.lower() or opt.lower() in answer_clean:
            return opt

    # 模糊匹配（去除 emoji 和空格后比较）
    def clean_text(text: str) -> str:
        # 移除 emoji 和特殊字符
        import unicodedata
        cleaned = ''.join(
            c for c in text
            if unicodedata.category(c) not in ('So', 'Mn', 'Mc', 'Me')
        )
        return cleaned.replace(" ", "").lower()

    answer_cleaned = clean_text(answer)
    for opt in options:
        if clean_text(opt) == answer_cleaned:
            return opt
        if answer_cleaned in clean_text(opt) or clean_text(opt) in answer_cleaned:
            return opt

    logger.warning(f"无法匹配答案 '{answer}' 到选项 {options}")
    return None


# ==================== 签到逻辑 ====================

class TerminusCheckin:
    def __init__(self, client: Client):
        self.client = client
        self.finished = asyncio.Event()
        self.success = False
        self.already_checked = False  # 今日已签到标记
        self.message_to_click: Optional[Message] = None

    async def start(self) -> bool:
        """执行签到流程"""
        from pyrogram.errors import FloodWait
        self.finished.clear()
        self.success = False
        self.already_checked = False
        self.message_to_click = None

        logger.info("开始终点站签到...")

        # 只尝试一次，不重复发送命令
        try:
            # 随机延迟 2-5 秒，模拟人工操作
            delay = random.uniform(2, 5)
            logger.debug(f"等待 {delay:.1f} 秒...")
            await asyncio.sleep(delay)

            # 直接发送签到命令（不发 /cancel，减少请求）
            await self.client.send_message(BOT_USERNAME, "/checkin")
            logger.info("已发送签到命令，等待机器人响应...")

            # 等待签到完成（超时60秒）
            try:
                await asyncio.wait_for(self.finished.wait(), timeout=60)
            except asyncio.TimeoutError:
                logger.warning("签到超时")
                return False

            if self.success or self.already_checked:
                if self.already_checked:
                    logger.info("今日已签到，无需重复")
                else:
                    logger.info("签到成功！")
                return True
            else:
                # 签到失败，只在验证码错误时重试
                logger.warning("签到失败")
                return False

        except FloodWait as e:
            logger.warning(f"触发 Telegram 限制，等待 {e.value} 秒")
            await asyncio.sleep(e.value)
            return False
        except Exception as e:
            logger.error(f"签到出错: {e}")
            return False

    async def handle_message(self, client: Client, message: Message):
        """处理机器人消息"""
        try:
            text = message.text or message.caption or ""

            # 记录所有收到的消息
            logger.info(f"收到机器人消息: {text[:200] if text else '[图片/媒体]'}")

            # 忽略的消息
            if any(kw in text for kw in ["会话已取消", "没有活跃的会话"]):
                logger.debug(f"忽略消息: {text[:50]}")
                return

            # 处理验证码图片（优先处理）
            if message.photo and message.reply_markup:
                await self.handle_captcha(message)
                return

            # 仅有图片没有按钮
            if message.photo:
                logger.info("收到图片但没有按钮，等待后续消息...")
                return

            # 已签到的各种表述
            already_checked_keywords = [
                "今天已签到", "已经签到", "今日已签到", "已签到",
                "重复签到", "已经签过", "签过到了", "已完成签到",
                "签到机会已用完", "已用完"
            ]
            if any(kw in text for kw in already_checked_keywords):
                # 尝试提取总分
                match = re.search(r"总分[：:]\s*(\d+)", text)
                if match:
                    logger.info(f"今日已签到，当前总分: {match.group(1)}")
                else:
                    logger.info(f"今日已签到: {text[:100]}")
                self.already_checked = True
                self.finished.set()
                return

            # 签到成功的各种表述
            success_keywords = [
                "签到成功", "成功签到", "获得", "+", "积分",
                "恭喜", "完成签到", "签到完成"
            ]
            if any(kw in text for kw in success_keywords):
                # 尝试提取积分信息
                match = re.search(r"[+＋]?\s*(\d+)\s*[积分点]", text)
                if match:
                    logger.info(f"签到成功！获得 {match.group(1)} 积分")
                else:
                    # 尝试其他格式
                    match2 = re.search(r"(\d+)", text)
                    if match2:
                        logger.info(f"签到成功！积分相关: {match2.group(1)}")
                    else:
                        logger.info(f"签到成功！{text[:100]}")
                self.success = True
                self.finished.set()
                return

            # 签到失败/错误的各种表述
            fail_keywords = [
                "失败", "错误", "验证码错误", "回答错误",
                "答案错误", "超时", "过期", "无效"
            ]
            if any(kw in text for kw in fail_keywords):
                logger.warning(f"签到失败: {text[:100]}")
                self.success = False
                self.finished.set()
                return

            # 账号问题
            account_fail_keywords = [
                "黑名单", "封禁", "禁止", "未注册", "不存在",
                "未绑定", "请先绑定", "请先注册"
            ]
            if any(kw in text for kw in account_fail_keywords):
                logger.error(f"账号问题: {text[:100]}")
                self.success = False
                self.finished.set()
                return

            # 其他未识别的消息，记录但不结束
            logger.warning(f"未识别的消息类型: {text[:200]}")

        except Exception as e:
            logger.error(f"处理消息出错: {e}")

    async def handle_captcha(self, message: Message):
        """处理验证码"""
        from pyrogram.errors import RPCError
        try:
            logger.info("收到验证码图片，正在识别...")

            # 获取按钮选项
            if not message.reply_markup or not message.reply_markup.inline_keyboard:
                logger.error("没有找到选项按钮")
                return

            options = []
            for row in message.reply_markup.inline_keyboard:
                for button in row:
                    if button.text:
                        options.append(button.text)

            if not options:
                logger.error("选项为空")
                return

            # 清理选项文本（用于 API 识别）
            def clean_option(text: str) -> str:
                # 移除 emoji
                import unicodedata
                cleaned = ''.join(
                    c for c in text
                    if unicodedata.category(c) not in ('So', 'Mn', 'Mc', 'Me')
                )
                return cleaned.replace(" ", "").strip()

            options_cleaned = [clean_option(opt) for opt in options]
            options_cleaned = [opt for opt in options_cleaned if opt]  # 移除空字符串

            logger.info(f"选项: {options}")
            logger.debug(f"清理后选项: {options_cleaned}")

            # 下载图片
            photo_data = await self.client.download_media(message, in_memory=True)
            if isinstance(photo_data, BytesIO):
                image_bytes = photo_data.getvalue()
            else:
                image_bytes = photo_data

            # 调用 Gemini 识别
            answer, error = await analyze_image(image_bytes, options_cleaned)

            if error:
                logger.error(f"验证码识别失败: {error}")
                self.finished.set()
                return

            logger.info(f"Gemini 识别结果: {answer}")

            # 匹配答案到原始选项
            matched_option = find_best_match(answer, options)

            if not matched_option:
                # 尝试用清理后的选项匹配
                matched_clean = find_best_match(answer, options_cleaned)
                if matched_clean:
                    idx = options_cleaned.index(matched_clean)
                    matched_option = options[idx]

            if not matched_option:
                logger.error(f"无法匹配答案 '{answer}' 到选项")
                self.finished.set()
                return

            logger.info(f"点击选项: {matched_option}")

            # 随机延迟，模拟人工操作
            await asyncio.sleep(random.uniform(1, 3))

            # 点击按钮
            try:
                await message.click(matched_option)
            except RPCError as e:
                logger.error(f"点击按钮失败: {e}")
                self.finished.set()

        except Exception as e:
            logger.error(f"处理验证码出错: {e}")
            self.finished.set()


# ==================== 定时任务 ====================

async def wait_until_next_checkin() -> None:
    """等待到下一次签到时间"""
    now = datetime.now()
    target_time = now.replace(
        hour=CHECKIN_HOUR,
        minute=CHECKIN_MINUTE,
        second=0,
        microsecond=0
    )

    # 如果今天的签到时间已过，等到明天
    if now >= target_time:
        target_time += timedelta(days=1)

    wait_seconds = (target_time - now).total_seconds()

    # 添加随机延迟（0-30分钟），避免被检测
    random_delay = random.randint(0, 1800)
    wait_seconds += random_delay

    logger.info(
        f"下次签到时间: {target_time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"(随机延迟 {random_delay // 60} 分钟)"
    )
    logger.info(f"等待 {wait_seconds / 3600:.2f} 小时...")

    await asyncio.sleep(wait_seconds)


async def run_scheduled_checkin(client: Client, checkin: TerminusCheckin):
    """运行定时签到任务"""
    while True:
        try:
            # 先等待到签到时间
            await wait_until_next_checkin()

            # 再执行签到
            await checkin.start()

        except asyncio.CancelledError:
            logger.info("定时任务已取消")
            break
        except Exception as e:
            logger.error(f"定时任务出错: {e}")
            # 出错后等待1小时再重试
            await asyncio.sleep(3600)


# ==================== 主程序 ====================

async def main():
    """主函数"""
    from pyrogram import Client, filters
    from pyrogram.types import Message
    logger.info("=" * 50)
    logger.info("终点站 (Terminus) 自动签到")
    logger.info("=" * 50)

    # 确保日志目录存在
    os.makedirs("logs", exist_ok=True)
    os.makedirs("sessions", exist_ok=True)

    # 创建客户端
    client = Client(
        name=f"sessions/{SESSION_NAME}",
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=PHONE_NUMBER if PHONE_NUMBER else None,
    )

    checkin = TerminusCheckin(client)

    async with client:
        logger.info(f"已登录: {client.me.first_name} (@{client.me.username})")

        # 获取机器人信息
        try:
            bot = await client.get_users(BOT_USERNAME)
            logger.info(f"目标机器人: {bot.first_name} (@{bot.username}, ID: {bot.id})")
        except Exception as e:
            logger.error(f"获取机器人信息失败: {e}")
            return

        # 注册消息处理器 - 使用机器人 ID 确保匹配
        @client.on_message(filters.user(bot.id) & filters.private)
        async def message_handler(client: Client, message: Message):
            await checkin.handle_message(client, message)

        # 检查是否需要立即签到
        run_now = os.getenv("RUN_NOW", "false").lower() == "true"
        if run_now:
            logger.info("立即执行签到...")
            await checkin.start()
        else:
            logger.info("跳过立即签到，等待定时任务...")

        # 启动定时任务
        logger.info(f"启动定时签到任务，每天 {CHECKIN_HOUR:02d}:{CHECKIN_MINUTE:02d} 执行")
        await run_scheduled_checkin(client, checkin)


def _parse_test_options(raw: str) -> list[str]:
    """
    解析离线测试的选项列表：
    - 允许使用逗号/顿号/分号/换行分隔
    """
    if not raw:
        return []
    parts = re.split(r"[,\n;；、]+", raw)
    return [p.strip() for p in parts if p.strip()]


async def _run_test_captcha(image_path: str, options_raw: str) -> int:
    if not image_path:
        logger.error("缺少图片路径：请使用 --image 指定验证码图片文件")
        return 2
    if not os.path.isfile(image_path):
        logger.error(f"图片文件不存在：{image_path}")
        return 2

    options = _parse_test_options(options_raw)
    if not options:
        logger.error("缺少选项列表：请使用 --options 提供候选项（用逗号/顿号分隔）")
        return 2

    with open(image_path, "rb") as f:
        image_data = f.read()

    logger.info(f"离线测试：AI_PROVIDER={AI_PROVIDER}，候选项={options}")
    answer, error = await analyze_image(image_data, options)
    if error:
        logger.error(f"验证码识别失败：{error}")
        return 1

    matched = find_best_match(answer or "", options)
    logger.info(f"AI 原始回答: {answer}")
    logger.info(f"匹配到的选项: {matched}")
    if not matched:
        return 1
    print(matched)
    return 0


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="终点站 (Terminus) Telegram 自动签到脚本")
        parser.add_argument(
            "--test-captcha",
            action="store_true",
            help="离线测试验证码识别：读取本地图片并输出匹配到的选项（不会触发签到流程）",
        )
        parser.add_argument("--image", default="", help="验证码图片路径（配合 --test-captcha 使用）")
        parser.add_argument(
            "--options",
            default="",
            help="候选项列表（逗号/顿号分隔，配合 --test-captcha 使用）",
        )
        args = parser.parse_args()

        if args.test_captcha:
            exit_code = asyncio.run(_run_test_captcha(args.image, args.options))
            raise SystemExit(exit_code)

        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序已退出")
