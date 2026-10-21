"""Rewrite the bundled mcp.json to launch the server with a working Python.

Codex's plugin MCP transport has no per-platform `command` override (only hook
handlers accept `commandWindows`), and Windows installs Python as `python.exe`
or via the `py` launcher rather than `python3`. This rewrites the plugin's
`mcp.json` at install time so the server starts on the host it was installed on.

Usage: python3 scripts/select_python_command.py <plugin-dir>
Prints the interpreter it chose (for install logs).
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys

# Candidates in preference order. `python3` is the Linux/macOS norm; Windows
# ships `python` / `py`, and a Microsoft-Store stub named `python3` may exist
# but does nothing useful, so on Windows we try `python` and `py` first.
POSIX_CANDIDATES = ["python3", "python"]
WINDOWS_CANDIDATES = ["python", "py", "python3"]


def choose() -> str:
    candidates = WINDOWS_CANDIDATES if sys.platform.startswith("win") else POSIX_CANDIDATES
    for name in candidates:
        path = shutil.which(name)
        if not path:
            continue
        # Reject the Windows Store alias stubs, which resolve but fail on run.
        if path.lower().endswith("windowssystem32\\python3.exe") or "windowsapps" in path.lower():
            continue
        return name
    raise SystemExit(
        "error: could not find a Python 3 interpreter (tried: "
        + ", ".join(candidates)
        + "). Install Python 3.9+ and make sure it is on PATH."
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: select_python_command.py <plugin-dir>")
    plugin_dir = pathlib.Path(sys.argv[1])
    mcp_path = plugin_dir / "mcp.json"
    config = json.loads(mcp_path.read_text())
    server = config["mcpServers"]["ds_web"]

    interpreter = choose()
    server["command"] = interpreter

    args = server.get("args") or []
    # Keep the relative script path; cwd is the plugin root.
    if not args:
        server["args"] = ["server/ds_web_mcp.py"]

    mcp_path.write_text(json.dumps(config, indent=2) + "\n")
    print(interpreter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
