"""Runtime settings, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load apps/api/.env when present. Real environment variables take precedence.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _has_anthropic_credentials() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _has_medgemma() -> bool:
    return bool(os.getenv("BIOVERSE_MEDGEMMA_ENDPOINT") or os.getenv("BIOVERSE_MEDGEMMA_URL"))


@dataclass(frozen=True)
class Settings:
    database_url: str
    cors_origins: tuple[str, ...]
    ai_enabled: bool
    ai_model: str
    # Which models to try, in order: "medgemma" (Google's medical model on Vertex AI) and/or "claude".
    ai_providers: tuple[str, ...] = ()


@lru_cache
def get_settings() -> Settings:
    ai_setting = os.getenv("BIOVERSE_AI", "auto").lower()
    if ai_setting == "off":
        ai_enabled = False
    elif ai_setting == "on":
        ai_enabled = True
    else:
        ai_enabled = _has_anthropic_credentials() or _has_medgemma()

    # BIOVERSE_AI_PROVIDER: medgemma (default when configured), claude, or a list like "medgemma,claude".
    wanted = os.getenv("BIOVERSE_AI_PROVIDER", "medgemma,claude").lower().replace(" ", "").split(",")
    available = {"medgemma": _has_medgemma(), "claude": _has_anthropic_credentials()}
    ai_providers = tuple(p for p in wanted if available.get(p))

    return Settings(
        database_url=os.getenv(
            "DATABASE_URL", "postgresql://bioverse:bioverse@localhost:5432/bioverse"
        ),
        cors_origins=tuple(
            o.strip()
            for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
            if o.strip()
        ),
        ai_enabled=ai_enabled,
        ai_model=os.getenv("BIOVERSE_MODEL", "claude-opus-5"),
        ai_providers=ai_providers,
    )


def clinic_tz() -> ZoneInfo:
    """The clinic's time zone. Servers (Cloud Run) run in UTC; "today" for patients means the clinic's day."""
    return ZoneInfo(os.getenv("BIOVERSE_CLINIC_TZ", "America/New_York"))


def clinic_today() -> date:
    return datetime.now(clinic_tz()).date()
