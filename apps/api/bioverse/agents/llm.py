"""Model access for Bioverse agents.

Providers are tried in the order of settings.ai_providers (BIOVERSE_AI_PROVIDER):

- **medgemma**: Google's open medical model (MedGemma) on a Vertex AI endpoint in this project.
  See bioverse/agents/medgemma.py.
- **claude**: the Anthropic API, with structured output and server-side refusal fallbacks.

Every call returns structured output validated by Pydantic, so agents receive typed data, never free
text they have to parse. When every provider fails (no credentials, network, refusal, invalid output),
parse raises LLMUnavailable, and every caller has a deterministic rules path to fall back to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import anthropic
from pydantic import BaseModel

from bioverse.agents import medgemma
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


def providers() -> list[str]:
    """Providers to try, in order. A test-injected Claude client counts as configured."""
    chosen = list(get_settings().ai_providers)
    if _client is not None and "claude" not in chosen:
        chosen.append("claude")
    return chosen


def active_provider() -> str | None:
    """The first provider in use, for status displays ("medgemma", "claude"), or None in rules mode."""
    if not ai_enabled():
        return None
    chosen = providers()
    return chosen[0] if chosen else None


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
    chosen = providers()
    if not chosen:
        raise LLMUnavailable("no AI provider configured")
    reasons = []
    for i, provider in enumerate(chosen):
        try:
            if provider == "medgemma":
                output = medgemma.parse(system=system, messages=messages, output_format=output_format,
                                        max_tokens=max_tokens)
                return LLMResult(output=output, model=medgemma.model_label(), fell_back=i > 0)
            if provider == "claude":
                result = _claude(system=system, messages=messages, output_format=output_format,
                                 effort=effort, max_tokens=max_tokens)
                result.fell_back = result.fell_back or i > 0
                return result
        except (LLMUnavailable, medgemma.MedGemmaUnavailable) as exc:
            reasons.append((provider, str(exc)))
    # One provider: keep its reason as is ("refusal", "rate limited"...), which audit and tests rely on.
    if len(reasons) == 1:
        raise LLMUnavailable(reasons[0][1])
    raise LLMUnavailable("; ".join(f"{p}: {r}" for p, r in reasons))


def _claude(
    *,
    system: str,
    messages: list[dict[str, Any]],
    output_format: type[T],
    effort: str,
    max_tokens: int,
) -> LLMResult[T]:
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
