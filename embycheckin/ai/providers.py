from __future__ import annotations

import base64
from typing import Any, Optional

import httpx
from loguru import logger


async def analyze_captcha(
    image_bytes: bytes,
    options: list[str],
    settings: Any,
) -> tuple[str, Optional[str]]:
    provider = settings.ai_provider.lower()

    prompt = f"""请识别图片中的内容，并从以下选项中选择最匹配的答案。
选项: {', '.join(options)}
只需要回复选项内容，不要解释。"""

    if provider == "gemini":
        return await _call_gemini(prompt, settings, image_bytes)
    elif provider == "openai":
        return await _call_openai(prompt, settings, image_bytes)
    elif provider == "claude":
        return await _call_claude(prompt, settings, image_bytes)
    else:
        return "", f"Unknown AI provider: {provider}"


async def generate_text(
    prompt: str,
    settings: Any,
) -> tuple[str, Optional[str]]:
    provider = settings.ai_provider.lower()

    if provider == "gemini":
        return await _call_gemini(prompt, settings)
    elif provider == "openai":
        return await _call_openai(prompt, settings)
    elif provider == "claude":
        return await _call_claude(prompt, settings)
    else:
        return "", f"Unknown AI provider: {provider}"


async def _call_gemini(
    prompt: str,
    settings: Any,
    image_bytes: Optional[bytes] = None,
) -> tuple[str, Optional[str]]:
    if not settings.gemini_api_key:
        return "", "GEMINI_API_KEY not configured"

    base_url = settings.gemini_base_url.rstrip("/")
    if "/v1beta" not in base_url and "/v1" not in base_url:
        base_url = f"{base_url}/v1beta"
    model = settings.gemini_model
    url = f"{base_url}/models/{model}:generateContent"

    parts = [{"text": prompt}]
    if image_bytes:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})

    payload = {"contents": [{"parts": parts}]}
    params = {"key": settings.gemini_api_key}

    try:
        async with httpx.AsyncClient(timeout=30, verify=settings.ai_ssl_verify) as client:
            resp = await client.post(url, json=payload, params=params)
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            return "", "Gemini returned empty candidates"

        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        answer = "".join(text_parts).strip()
        return answer, None

    except Exception as e:
        return "", f"Gemini API error: {e}"


async def _call_openai(
    prompt: str,
    settings: Any,
    image_bytes: Optional[bytes] = None,
) -> tuple[str, Optional[str]]:
    if not settings.openai_api_key:
        return "", "OPENAI_API_KEY not configured"

    base_url = settings.openai_base_url.rstrip("/")
    url = f"{base_url}/chat/completions"

    content = [{"type": "text", "text": prompt}]
    if image_bytes:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})

    payload = {
        "model": settings.openai_model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 500,
    }

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30, verify=settings.ai_ssl_verify) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            return "", "OpenAI returned empty choices"

        content = choices[0].get("message", {}).get("content", "")
        return content.strip(), None

    except Exception as e:
        return "", f"OpenAI API error: {e}"


async def _call_claude(
    prompt: str,
    settings: Any,
    image_bytes: Optional[bytes] = None,
) -> tuple[str, Optional[str]]:
    if not settings.claude_api_key:
        return "", "CLAUDE_API_KEY not configured"

    base_url = settings.claude_base_url.rstrip("/")
    url = f"{base_url}/v1/messages"

    content = []
    if image_bytes:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
    content.append({"type": "text", "text": prompt})

    payload = {
        "model": settings.claude_model,
        "max_tokens": settings.claude_max_tokens,
        "messages": [{"role": "user", "content": content}],
    }

    headers = {
        "x-api-key": settings.claude_api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30, verify=settings.ai_ssl_verify) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = data.get("content", [])
        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        answer = "".join(text_parts).strip()
        return answer, None

    except Exception as e:
        return "", f"Claude API error: {e}"
