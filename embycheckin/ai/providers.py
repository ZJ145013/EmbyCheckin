from __future__ import annotations

import base64
import json
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
        return await _analyze_with_gemini(image_bytes, prompt, settings)
    elif provider == "openai":
        return await _analyze_with_openai(image_bytes, prompt, settings)
    elif provider == "claude":
        return await _analyze_with_claude(image_bytes, prompt, settings)
    else:
        return "", f"Unknown AI provider: {provider}"


async def _analyze_with_gemini(
    image_bytes: bytes,
    prompt: str,
    settings: Any,
) -> tuple[str, Optional[str]]:
    if not settings.gemini_api_key:
        return "", "GEMINI_API_KEY not configured"

    base_url = settings.gemini_base_url.rstrip("/")
    if "/v1beta" not in base_url and "/v1" not in base_url:
        base_url = f"{base_url}/v1beta"
    model = settings.gemini_model
    url = f"{base_url}/models/{model}:generateContent"

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
            ]
        }]
    }

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


async def _analyze_with_openai(
    image_bytes: bytes,
    prompt: str,
    settings: Any,
) -> tuple[str, Optional[str]]:
    if not settings.openai_api_key:
        return "", "OPENAI_API_KEY not configured"

    base_url = settings.openai_base_url.rstrip("/")
    url = f"{base_url}/chat/completions"

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": settings.openai_model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ],
        }],
        "max_tokens": 100,
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


async def _analyze_with_claude(
    image_bytes: bytes,
    prompt: str,
    settings: Any,
) -> tuple[str, Optional[str]]:
    if not settings.claude_api_key:
        return "", "CLAUDE_API_KEY not configured"

    base_url = settings.claude_base_url.rstrip("/")
    url = f"{base_url}/v1/messages"

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": settings.claude_model,
        "max_tokens": settings.claude_max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
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
