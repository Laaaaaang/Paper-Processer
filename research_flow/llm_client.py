from __future__ import annotations

from typing import Any, Dict, Optional

from .config import AppConfig
from .deepseek_client import DeepSeekResponseError, call_deepseek, create_analysis as create_deepseek_analysis
from .gemini_client import GeminiResponseError, call_gemini, create_analysis as create_gemini_analysis
from .openai_client import OpenAIResponseError, call_openai, create_analysis as create_openai_analysis

_PROVIDER_ERRORS = (OpenAIResponseError, GeminiResponseError, DeepSeekResponseError)


class LLMResponseError(RuntimeError):
    pass


def provider_label(provider: str) -> str:
    return {"openai": "OpenAI", "gemini": "Gemini / Google AI Studio", "deepseek": "DeepSeek"}.get(
        provider, provider
    )


def default_model_for_provider(provider: str) -> str:
    return {"openai": "gpt-5.4", "gemini": "gemini-2.5-flash", "deepseek": "deepseek-chat"}.get(
        provider, "gemini-2.5-flash"
    )


def create_analysis_for_provider(
    paper,
    *,
    provider: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_model = model or default_model_for_provider(provider)
    try:
        if provider == "openai":
            return create_openai_analysis(paper, model=resolved_model, api_key=api_key)
        if provider == "gemini":
            return create_gemini_analysis(paper, model=resolved_model, api_key=api_key)
        if provider == "deepseek":
            return create_deepseek_analysis(paper, model=resolved_model, api_key=api_key)
    except _PROVIDER_ERRORS as exc:
        raise LLMResponseError(str(exc)) from exc
    raise LLMResponseError(f"Unsupported LLM provider: {provider}")


def create_analysis_for_config(paper, config: AppConfig) -> Dict[str, Any]:
    return create_analysis_for_provider(
        paper,
        provider=config.llm_provider,
        model=config.active_llm_model(),
        api_key=config.active_llm_api_key(),
    )


def call_llm(
    *,
    prompt: str,
    schema: Dict[str, Any],
    config: AppConfig,
    schema_name: str = "structured_output",
) -> Dict[str, Any]:
    """Generic LLM call with arbitrary prompt and schema."""
    provider = config.llm_provider
    model = config.active_llm_model()
    api_key = config.active_llm_api_key()
    try:
        if provider == "openai":
            return call_openai(
                prompt=prompt, schema=schema, model=model,
                api_key=api_key, schema_name=schema_name,
            )
        if provider == "gemini":
            return call_gemini(
                prompt=prompt, schema=schema, model=model, api_key=api_key,
            )
        if provider == "deepseek":
            return call_deepseek(
                prompt=prompt, schema=schema, model=model,
                api_key=api_key, schema_name=schema_name,
            )
    except _PROVIDER_ERRORS as exc:
        raise LLMResponseError(str(exc)) from exc
    raise LLMResponseError(f"Unsupported LLM provider: {provider}")
