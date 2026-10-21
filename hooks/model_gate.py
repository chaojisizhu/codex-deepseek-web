#!/usr/bin/env python3
"""PreToolUse guard: keep the DeepSeek web tools usable only by DeepSeek models.

Codex passes the active model slug (and the tool name) on stdin for every
PreToolUse event. If the call targets one of this plugin's MCP tools and the
model is not on the allow list, the call is denied with a reason the model can
read, so GPT-family models stop reaching for tools they cannot use.

Fails open: any unexpected input shape lets the call through, because a broken
guard must never block normal work.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys

# Tool prefix this guard owns. Override with DSWEB_TOOL_PREFIX.
TOOL_PREFIX = os.environ.get("DSWEB_TOOL_PREFIX", "mcp__ds_web")
# Comma-separated glob patterns of model slugs allowed to use the tools.
ALLOW_MODELS = os.environ.get(
    "DSWEB_ALLOW_MODELS", "deepseek*,*deepseek*"
)
# "deny" blocks the call; "warn" only injects a note and lets it run.
MODE = os.environ.get("DSWEB_GATE_MODE", "deny").strip().lower()


def allow_patterns() -> list[str]:
    return [p.strip().lower() for p in ALLOW_MODELS.split(",") if p.strip()]


def model_allowed(model: str) -> bool:
    slug = (model or "").strip().lower()
    if not slug:
        return True  # unknown model: fail open
    return any(fnmatch.fnmatch(slug, pat) for pat in allow_patterns())


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0

    tool_name = str(data.get("tool_name") or "")
    if not tool_name.startswith(TOOL_PREFIX):
        return 0

    model = str(data.get("model") or "")
    if model_allowed(model):
        return 0

    reason = (
        f"The {tool_name} tool is DeepSeek-only and this session is running "
        f"'{model or 'an unknown model'}'. Do not call it again. Use your own "
        "built-in web search or ask the user to switch to a DeepSeek model "
        "(e.g. `codex --profile deepseek`) if live web access is required."
    )

    if MODE == "warn":
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": reason,
                }
            }
        )
        return 0

    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
