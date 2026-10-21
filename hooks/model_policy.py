"""Shared model policy for the ds-web hooks.

Both hooks must agree on who is blocked, so the rule lives here once.

Policy: block **GPT-series (OpenAI) models only**. Everything else — DeepSeek,
Claude, GLM, Kimi, local models, and anything unrecognised — is allowed.

Override the blocked-pattern list with DSWEB_BLOCK_MODELS (comma-separated
globs, matched case-insensitively against the model slug Codex reports).
"""

from __future__ import annotations

import fnmatch
import os

# Codex model slugs look like: gpt-6-luna, gpt-5.5-codex, gpt-5-codex-mini,
# o3, o4-mini, codex-mini-latest. `gpt*` covers the gpt-* family; the bare
# o-series slugs are listed because they carry no "gpt" prefix.
DEFAULT_BLOCK_MODELS = (
    "gpt*",
    "o1*",
    "o3*",
    "o4*",
    "codex-mini*",
)

BLOCK_MODELS = os.environ.get("DSWEB_BLOCK_MODELS", ",".join(DEFAULT_BLOCK_MODELS))


def blocked_patterns() -> list[str]:
    return [p.strip().lower() for p in BLOCK_MODELS.split(",") if p.strip()]


def is_blocked(model: str) -> bool:
    """True when this model is a GPT-series model that must not use the tools.

    An empty/unknown model slug is allowed: the plugin already errs toward
    availability for everything that is not recognisably GPT.
    """
    slug = (model or "").strip().lower()
    if not slug:
        return False
    return any(fnmatch.fnmatch(slug, pat) for pat in blocked_patterns())


DENY_TEMPLATE = (
    "{tools} belongs to the DeepSeek Web plugin and is DeepSeek-only. "
    "GPT-series (OpenAI) models must not call it, and this session is a "
    "GPT-series model, so the call is denied. Use your own built-in web search "
    "instead. If live web access through DeepSeek is wanted, the user can run "
    "`codex --profile deepseek`."
)

NOTICE_TEXT = (
    "These web tools belong to the DeepSeek Web plugin and are DeepSeek-only: "
    "`mcp__ds_web__web_search` and `mcp__ds_web__web_fetch`. "
    "GPT-series (OpenAI) models must not call them, and this session is a "
    "GPT-series model, so any call is denied and only wastes a turn. "
    "Use your own built-in web search instead. If live web access through "
    "DeepSeek is wanted, the user can run `codex --profile deepseek`."
)
