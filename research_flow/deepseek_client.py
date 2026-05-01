from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .prompting import build_prompt
from .schemas import analysis_schema


DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
ANALYSIS_SCHEMA_NAME = "literature_note_analysis"
DEFAULT_SCHEMA_NAME = "structured_output"


class DeepSeekResponseError(RuntimeError):
    pass


def _build_deepseek_body(
    *, prompt: str, schema: Dict[str, Any], model: str, schema_name: str,
) -> Dict[str, Any]:
    schema_instruction = (
        "You MUST respond with a single JSON object that conforms to the following JSON Schema. "
        "Do not include any text outside the JSON.\n\n"
        f"```json\n{json.dumps(schema, ensure_ascii=False)}\n```"
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": schema_instruction},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }


def _parse_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    choices = payload.get("choices", [])
    if not choices:
        raise DeepSeekResponseError("DeepSeek response did not include any choices")

    message = choices[0].get("message", {})
    refusal = message.get("refusal")
    if refusal:
        raise DeepSeekResponseError(f"Model refusal: {refusal}")

    content = message.get("content")
    if not content:
        raise DeepSeekResponseError("DeepSeek response did not include content")

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise DeepSeekResponseError("DeepSeek response was not valid JSON") from exc


def _do_request(body: Dict[str, Any], api_key: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, context=ssl.create_default_context()
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DeepSeekResponseError(f"DeepSeek API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise DeepSeekResponseError(f"DeepSeek API request failed: {exc}") from exc


def create_analysis(paper, model: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekResponseError("DEEPSEEK_API_KEY is required for synthesize")

    body = _build_deepseek_body(
        prompt=build_prompt(paper),
        schema=analysis_schema(),
        model=model,
        schema_name=ANALYSIS_SCHEMA_NAME,
    )
    payload = _do_request(body, api_key)
    return _parse_response(payload)


def call_deepseek(
    *,
    prompt: str,
    schema: Dict[str, Any],
    model: str,
    api_key: Optional[str] = None,
    schema_name: str = DEFAULT_SCHEMA_NAME,
) -> Dict[str, Any]:
    """Generic DeepSeek call with arbitrary prompt and schema."""
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekResponseError("DEEPSEEK_API_KEY is required")

    body = _build_deepseek_body(
        prompt=prompt, schema=schema, model=model, schema_name=schema_name,
    )
    payload = _do_request(body, api_key)
    return _parse_response(payload)
