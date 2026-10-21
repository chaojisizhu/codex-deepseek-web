#!/usr/bin/env python3
"""SessionStart notice: tell non-DeepSeek models up front not to use ds-web.

The PreToolUse gate only speaks when a model actually reaches for the tool.
This hook injects the same rule into the session context at startup, so a
GPT-family model is told once, before it plans, that these tools are not for
it — instead of discovering that by being denied mid-turn.

Fails open: any surprise on stdin means no context is injected.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys

ALLOW_MODELS = os.environ.get("DSWEB_ALLOW_MODELS", "deepseek*,*deepseek*")


def model_allowed(model: str) -> bool:
    slug = (model or "").strip().lower()
    if not slug:
        return True  # unknown model: stay quiet, the deny gate still protects
    patterns = [p.strip().lower() for p in ALLOW_MODELS.split(",") if p.strip()]
    return any(fnmatch.fnmatch(slug, pat) for pat in patterns)


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0

    model = str(data.get("model") or "")
    if model_allowed(model):
        return 0

    context = (
        "The `ds_web` MCP server bundled with the DeepSeek Web plugin "
        "(tools `mcp__ds_web__web_search` and `mcp__ds_web__web_fetch`) is for "
        "DeepSeek models only. This session runs "
        f"'{model}', so do not call those tools: their calls are denied and will "
        "only waste a turn. Use your own built-in web search, or ask the user to "
        "run `codex --profile deepseek` when live web access through DeepSeek is "
        "wanted."
    )
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
