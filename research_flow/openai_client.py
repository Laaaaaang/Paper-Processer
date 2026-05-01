from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .prompting import build_prompt
from .schemas import analysis_schema


OPENAI_URL = "https://api.openai.com/v1/responses"
ANALYSIS_SCHEMA_NAME = "literature_note_analysis"
DEFAULT_SCHEMA_NAME = "structured_output"


class OpenAIResponseError(RuntimeError):
    pass


def build_openai_request_body(paper, model: str) -> Dict[str, Any]:
    return _build_openai_body(
        prompt=build_prompt(paper),
        schema=analysis_schema(),
        model=model,
        schema_name=ANALYSIS_SCHEMA_NAME,
    )


def _build_openai_body(
    *, prompt: str, schema: Dict[str, Any], model: str, schema_name: str,
) -> Dict[str, Any]:
    return {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    }
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": True,
            }
        },
    }


def create_analysis(paper, model: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIResponseError("OPENAI_API_KEY is required for synthesize")

    body = build_openai_request_body(paper, model)

    request = urllib.request.Request(
        OPENAI_URL,
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
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if "text.format.name" in detail:
            detail = (
                f"{detail}\nHint: the running app may still be using stale code. "
                "Fully stop the current `python3 -m research_flow gui` process and restart it."
            )
        raise OpenAIResponseError(f"OpenAI API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise OpenAIResponseError(f"OpenAI API request failed: {exc}") from exc

    output = payload.get("output", [])
    if output:
        content = output[0].get("content", [])
        if content and content[0].get("type") == "refusal":
            refusal = content[0].get("refusal", "Model refused the request.")
            raise OpenAIResponseError(f"Model refusal: {refusal}")

    output_text = payload.get("output_text")
    if not output_text:
        raise OpenAIResponseError("OpenAI response did not include output_text")

    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIResponseError("OpenAI response was not valid JSON") from exc


def call_openai(
    *,
    prompt: str,
    schema: Dict[str, Any],
    model: str,
    api_key: Optional[str] = None,
    schema_name: str = DEFAULT_SCHEMA_NAME,
) -> Dict[str, Any]:
    """Generic OpenAI call with arbitrary prompt and schema."""
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIResponseError("OPENAI_API_KEY is required")

    body = _build_openai_body(
        prompt=prompt, schema=schema, model=model, schema_name=schema_name,
    )
    request = urllib.request.Request(
        OPENAI_URL,
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
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OpenAIResponseError(f"OpenAI API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise OpenAIResponseError(f"OpenAI API request failed: {exc}") from exc

    output = payload.get("output", [])
    if output:
        content = output[0].get("content", [])
        if content and content[0].get("type") == "refusal":
            refusal = content[0].get("refusal", "Model refused the request.")
            raise OpenAIResponseError(f"Model refusal: {refusal}")

    output_text = payload.get("output_text")
    if not output_text:
        raise OpenAIResponseError("OpenAI response did not include output_text")

    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIResponseError("OpenAI response was not valid JSON") from exc
