from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .prompting import build_prompt
from .schemas import analysis_schema


def _build_gemini_body(*, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }


GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiResponseError(RuntimeError):
    pass


def build_gemini_request_body(paper) -> Dict[str, Any]:
    return _build_gemini_body(prompt=build_prompt(paper), schema=analysis_schema())


def _extract_text(payload: Dict[str, Any]) -> str:
    prompt_feedback = payload.get("promptFeedback") or {}
    block_reason = prompt_feedback.get("blockReason")
    if block_reason:
        raise GeminiResponseError(f"Gemini blocked the prompt: {block_reason}")

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise GeminiResponseError("Gemini response did not include any candidates")

    first = candidates[0] if isinstance(candidates[0], dict) else {}
    content = first.get("content") if isinstance(first.get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    text_parts = [
        str(part.get("text"))
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    output_text = "".join(text_parts).strip()
    if not output_text:
        finish_reason = first.get("finishReason")
        if finish_reason:
            raise GeminiResponseError(
                f"Gemini response did not include JSON text. Finish reason: {finish_reason}"
            )
        raise GeminiResponseError("Gemini response did not include any text output")
    return output_text


def create_analysis(paper, model: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise GeminiResponseError("GEMINI_API_KEY or GOOGLE_API_KEY is required for synthesize")

    model_name = model.removeprefix("models/")
    body = build_gemini_request_body(paper)
    request = urllib.request.Request(
        GEMINI_URL_TEMPLATE.format(model=model_name),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, context=ssl.create_default_context()
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GeminiResponseError(f"Gemini API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise GeminiResponseError(f"Gemini API request failed: {exc}") from exc

    output_text = _extract_text(payload)
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise GeminiResponseError("Gemini response was not valid JSON") from exc


def call_gemini(
    *,
    prompt: str,
    schema: Dict[str, Any],
    model: str,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Generic Gemini call with arbitrary prompt and schema."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise GeminiResponseError("GEMINI_API_KEY or GOOGLE_API_KEY is required")

    model_name = model.removeprefix("models/")
    body = _build_gemini_body(prompt=prompt, schema=schema)
    request = urllib.request.Request(
        GEMINI_URL_TEMPLATE.format(model=model_name),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, context=ssl.create_default_context()
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GeminiResponseError(f"Gemini API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise GeminiResponseError(f"Gemini API request failed: {exc}") from exc

    output_text = _extract_text(payload)
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise GeminiResponseError("Gemini response was not valid JSON") from exc
