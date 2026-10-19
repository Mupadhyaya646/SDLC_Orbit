"""Chat-model factory: Anthropic (via ``langchain-anthropic``).

Each agent asks for an "opus" or "sonnet" tier (preserved from the original Cortex
registrations). Defaults are the latest generation: ``claude-opus-5-5`` and
``claude-sonnet-5-5`` (see config.py); override per tier with ``LLM_MODEL_OPUS`` /
``LLM_MODEL_SONNET``, or both at once with ``LLM_MODEL``.

Notes from Anthropic's 5.5 model docs that shape this module:
* Adaptive thinking is always on for Opus 5.5, so ``temperature`` is not sent unless
  ``LLM_TEMPERATURE`` is set, and the agent loop never forces tool use (forced tool
  use errors on Opus 5.5).
* Thinking blocks are tied to the model that produced them. Each agent's thread stays
  on one model, so do NOT change the model ids while sessions are mid-run: a resumed
  thread would carry thinking blocks the new model may not accept. Finish or abandon
  in-flight sessions first.
* ``ANTHROPIC_BASE_URL`` lets you point at an Anthropic-compatible gateway.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from .config import LlmSettings, llm_settings

logger = logging.getLogger("sdlc_orbit.llm")


def _tier_model(s: LlmSettings, tier: str) -> str:
    return s.model_sonnet if tier == "sonnet" else s.model_opus


def _build_anthropic(s: LlmSettings, model: str):
    from langchain_anthropic import ChatAnthropic

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": s.api_key,
        "max_tokens": s.max_tokens,
        "timeout": s.request_timeout,
        "max_retries": 3,
    }
    if s.temperature is not None:
        kwargs["temperature"] = s.temperature
    if s.base_url:
        kwargs["base_url"] = s.base_url
    if s.extra_headers:
        kwargs["default_headers"] = s.extra_headers
    return ChatAnthropic(**kwargs)


@lru_cache(maxsize=4)
def _cached(tier: str):
    s = llm_settings()
    model = _tier_model(s, tier)
    logger.info("building chat model tier=%s model=%s", tier, model)
    return _build_anthropic(s, model)


def get_chat_model(tier: str = "opus"):
    """Return the (cached) chat model for ``tier`` ("opus" | "sonnet")."""
    return _cached(tier)


def clear_model_cache() -> None:
    """Test hook: forget cached models (e.g. after changing env vars)."""
    _cached.cache_clear()
