#!/usr/bin/env bash
# Install the ds-web Codex plugin into the personal plugin marketplace.
#
#   ./install.sh              # install / update
#   ./install.sh --uninstall  # remove
#
# Layout it creates (Codex's default personal marketplace):
#   ~/.agents/plugins/marketplace.json
#   ~/plugins/ds-web/...
#
# Env: CODEX_HOME (default ~/.codex)
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
MARKETPLACE_NAME="personal"
PLUGIN_NAME="ds-web"
MARKETPLACE_FILE="$HOME/.agents/plugins/marketplace.json"
PLUGIN_DEST="$HOME/plugins/$PLUGIN_NAME"
PLUGIN_ID="$PLUGIN_NAME@$MARKETPLACE_NAME"

if ! command -v codex >/dev/null 2>&1; then
  echo "error: codex CLI not found on PATH" >&2
  exit 1
fi

# One interpreter for every embedded Python snippet below.
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "error: python3 (or python) not found on PATH; install Python 3.9+" >&2
  exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
  CODEX_HOME="$CODEX_HOME" codex plugin remove "$PLUGIN_ID" 2>/dev/null || true
  rm -rf "${PLUGIN_DEST:?}"
  echo "removed $PLUGIN_NAME (marketplace entry in $MARKETPLACE_FILE left untouched)"
  exit 0
fi

# 1. Copy the plugin payload into ~/plugins/<name> (rsync-free for portability).
mkdir -p "$PLUGIN_DEST" "$(dirname "$MARKETPLACE_FILE")"
"$PY" - "$SRC_DIR" "$PLUGIN_DEST" <<'PY'
import pathlib, shutil, sys

src, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
skip_dirs = {".git", "__pycache__"}
dest.mkdir(parents=True, exist_ok=True)
for item in dest.iterdir():
    if item.is_dir():
        shutil.rmtree(item)
    else:
        item.unlink()
for item in src.iterdir():
    if item.name in skip_dirs or item.name.endswith(".pyc"):
        continue
    target = dest / item.name
    if item.is_dir():
        shutil.copytree(item, target, ignore=shutil.ignore_patterns(*skip_dirs, "*.pyc"))
    else:
        shutil.copy2(item, target)
print(f"plugin payload copied to {dest}")
PY

# 2. Register / refresh the marketplace entry idempotently.
"$PY" - "$MARKETPLACE_FILE" "$PLUGIN_NAME" "$MARKETPLACE_NAME" <<'PY'
import json, pathlib, sys

path, name, marketplace = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
payload = {"name": marketplace, "interface": {"displayName": "Personal"}, "plugins": []}
if path.exists():
    payload = json.loads(path.read_text())
plugins = payload.setdefault("plugins", [])
entry = {
    "name": name,
    "source": {"source": "local", "path": f"./plugins/{name}"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Research",
}
for i, existing in enumerate(plugins):
    if existing.get("name") == name:
        plugins[i] = entry
        break
else:
    plugins.append(entry)
path.write_text(json.dumps(payload, indent=2) + "\n")
print(f"marketplace entry written: {path}")
PY

# 3. Pick a Python interpreter that actually exists on this host and write it
#    into the plugin's mcp.json (Codex has no per-platform MCP command override).
INTERPRETER="$("$PY" "$PLUGIN_DEST/scripts/select_python_command.py" "$PLUGIN_DEST")"
echo "MCP server will launch with: $INTERPRETER"

# 4. Register the marketplace and install the plugin.
CODEX_HOME="$CODEX_HOME" codex plugin marketplace add "$HOME" >/dev/null
CODEX_HOME="$CODEX_HOME" codex plugin remove "$PLUGIN_ID" >/dev/null 2>&1 || true
CODEX_HOME="$CODEX_HOME" codex plugin add "$PLUGIN_ID"

cat <<EOF

Installed $PLUGIN_ID

Required config — ~/.codex/config.toml (GPT / default sessions keep it off):

  [plugins."$PLUGIN_ID".mcp_servers.ds_web]
  enabled = false

Required config — ~/.codex/deepseek.config.toml (DeepSeek sessions turn it on):

  model = "deepseek-v4-flash"
  model_provider = "deepseek"
  [plugins."$PLUGIN_ID".mcp_servers.ds_web]
  enabled = true

Run DeepSeek with:  codex --profile deepseek
The key comes from DEEPSEEK_API_KEY in Codex's own environment.
EOF
