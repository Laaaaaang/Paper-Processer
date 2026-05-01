from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .io_utils import load_json, save_json


@dataclass
class AppConfig:
    zotero_user_id: str = ""
    zotero_api_key: str = ""
    zotero_library_type: str = "users"
    zotero_collection_key: Optional[str] = None
    zotero_connector_url: str = "http://127.0.0.1:23119"
    zotero_desktop_target_id: Optional[str] = None
    llm_provider: str = "openai"
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-5.4"
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    deepseek_api_key: Optional[str] = None
    deepseek_model: str = "deepseek-chat"
    obsidian_vault_path: Optional[str] = None
    obsidian_rest_url: Optional[str] = None
    obsidian_rest_api_key: Optional[str] = None
    packet_dir: Optional[str] = None
    note_subdir: str = "Literature"
    default_item_type: str = "journalArticle"
    default_status: str = "inbox"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        filtered: Dict[str, Any] = {}
        for field_name in cls.__dataclass_fields__:
            if field_name in data and data[field_name] is not None:
                filtered[field_name] = data[field_name]
        config = cls(**filtered)
        config.validate()
        return config

    @classmethod
    def from_path(cls, path: Path) -> "AppConfig":
        if not path.exists():
            return cls()
        data = load_json(path)
        if not isinstance(data, dict):
            raise ValueError("config file must contain a JSON object")
        return cls.from_dict(data)

    def validate(self) -> None:
        if self.zotero_library_type not in {"users", "groups"}:
            raise ValueError("zotero_library_type must be 'users' or 'groups'")
        if self.llm_provider not in {"openai", "gemini", "deepseek"}:
            raise ValueError("llm_provider must be 'openai', 'gemini', or 'deepseek'")
        if not self.zotero_connector_url:
            raise ValueError("zotero_connector_url cannot be empty")
        if not self.note_subdir:
            raise ValueError("note_subdir cannot be empty")
        if not self.default_item_type:
            raise ValueError("default_item_type cannot be empty")
        if not self.default_status:
            raise ValueError("default_status cannot be empty")

    def require_zotero(self) -> None:
        if not self.zotero_user_id or not self.zotero_api_key:
            raise ValueError("Zotero user ID and API key are required")

    def require_openai(self) -> None:
        if not self.openai_api_key:
            raise ValueError("OpenAI API key is required")

    def require_llm(self) -> None:
        if self.llm_provider == "openai":
            if not (self.openai_api_key or os.environ.get("OPENAI_API_KEY")):
                raise ValueError("OpenAI API key is required")
            return
        if self.llm_provider == "deepseek":
            if not (self.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY")):
                raise ValueError("DeepSeek API key is required")
            return
        if not (
            self.gemini_api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        ):
            raise ValueError("Gemini / Google AI Studio API key is required")

    def active_llm_model(self) -> str:
        if self.llm_provider == "openai":
            return self.openai_model
        if self.llm_provider == "deepseek":
            return self.deepseek_model
        return self.gemini_model

    def active_llm_api_key(self) -> Optional[str]:
        if self.llm_provider == "openai":
            return self.openai_api_key or os.environ.get("OPENAI_API_KEY")
        if self.llm_provider == "deepseek":
            return self.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY")
        return (
            self.gemini_api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )

    def active_llm_label(self) -> str:
        if self.llm_provider == "openai":
            return "OpenAI"
        if self.llm_provider == "deepseek":
            return "DeepSeek"
        return "Gemini / Google AI Studio"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        save_json(path, self.as_dict())
