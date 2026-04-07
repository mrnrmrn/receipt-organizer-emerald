from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    gemini_model: str = "gemini-2.5-flash"


DEFAULT_CONFIG = AppConfig()
