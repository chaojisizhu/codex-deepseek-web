#!/usr/bin/env python3
"""SessionStart notice: tell GPT-series models up front not to use ds-web.

The PreToolUse gate only speaks when a model actually reaches for the tool.
This hook injects the same rule into the session context at startup, so a
GPT-series model is told once, before it plans, that these tools are not for
it — instead of discovering that by being denied mid-turn.

Only GPT-series models are told anything (see model_policy.py); DeepSeek and
every other model family start a session with no extra context.

Fails open: any surprise on stdin means no context is injected.
"""

from __future__ import annotations

import json
import sys

from model_policy import NOTICE_TEXT, is_blocked


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0

    model = str(data.get("model") or "")
    if not is_blocked(model):
        return 0

    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": NOTICE_TEXT,
        }
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
