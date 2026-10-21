#!/usr/bin/env python3
"""PreToolUse guard: GPT-series models must not call the DeepSeek web tools.

Codex passes the active model slug and the tool name on stdin for every
PreToolUse event. If a GPT-series model reaches for one of this plugin's MCP
tools, the call is denied with a reason the model can read.

Only GPT-series models are blocked (see model_policy.py); DeepSeek and every
other model family pass through untouched.

Fails open: any unexpected input shape lets the call through, because a broken
guard must never block normal work.
"""

from __future__ import annotations

import json
import os
import sys

from model_policy import DENY_TEMPLATE, is_blocked

# Tool prefix this guard owns. Override with DSWEB_TOOL_PREFIX.
TOOL_PREFIX = os.environ.get("DSWEB_TOOL_PREFIX", "mcp__ds_web")
# "deny" blocks the call; "warn" only injects a note and lets it run.
MODE = os.environ.get("DSWEB_GATE_MODE", "deny").strip().lower()


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
    if not is_blocked(model):
        return 0

    reason = DENY_TEMPLATE.format(tools=f"`{tool_name}`")

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
