"""Claude access for Bioverse agents.

Every call is structured output validated by Pydantic, so agents receive typed data,
never free text they have to parse. Server-side refusal fallbacks are on: if the
requested model declines on policy grounds, the API re-runs the request on
Anthropic's recommended fallback model inside the same call.

Any failure (no credentials, network, refusal, invalid output) raises LLMUnavailable,
and every caller has a deterministic path to fall back to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import anthropic
from pydantic import BaseModel

from bioverse.config import get_settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailable(Exception):
    """The model could not produce a usable answer. Callers must use their rules path."""


@dataclass
class LLMResult(Generic[T]):
    output: T
    model: str
    fell_back: bool


_client: Any = None


def get_client() -> Any:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=45.0, max_retries=2)
    return _client


def set_client(client: Any) -> None:
    """Test hook: inject a fake client."""
    global _client
    _client = client


def ai_enabled() -> bool:
    return get_settings().ai_enabled


def parse(
    *,
    system: str,
    messages: list[dict[str, Any]],
    output_format: type[T],
    effort: str = "medium",
    max_tokens: int = 4000,
) -> LLMResult[T]:
    if not ai_enabled():
        raise LLMUnavailable("AI is disabled")

    settings = get_settings()
    try:
        response = get_client().beta.messages.parse(
            model=settings.ai_model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_format=output_format,
            output_config={"effort": effort},
            fallbacks="default",
            betas=[FALLBACK_BETA],
        )
    except anthropic.AuthenticationError as exc:
        log.error("Claude authentication failed: %s", exc)
        raise LLMUnavailable("authentication failed") from exc
    except anthropic.RateLimitError as exc:
        log.warning("Claude rate limited: %s", exc)
        raise LLMUnavailable("rate limited") from exc
    except anthropic.APIStatusError as exc:
        log.error("Claude API error %s: %s", exc.status_code, exc.message)
        raise LLMUnavailable(f"api error {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        log.error("Claude unreachable: %s", exc)
        raise LLMUnavailable("connection error") from exc

    # Check the stop reason before reading content: the whole fallback chain can decline.
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None) if response.stop_details else None
        log.warning("Claude declined (category=%s)", category)
        raise LLMUnavailable("refusal")
    if response.stop_reason == "max_tokens":
        raise LLMUnavailable("output truncated")

    parsed = response.parsed_output
    if parsed is None:
        raise LLMUnavailable("output did not match schema")

    fell_back = any(
        getattr(entry, "type", None) == "fallback_message"
        for entry in (getattr(response.usage, "iterations", None) or [])
    )
    return LLMResult(output=parsed, model=response.model, fell_back=fell_back)
