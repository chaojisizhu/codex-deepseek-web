# ds-web — DeepSeek web search & fetch for Codex

A [Codex](https://github.com/openai/codex) plugin that gives DeepSeek models real web access.

DeepSeek's models are strong at coding but, unlike OpenAI's, they have no built-in web
search inside Codex. This plugin adds two MCP tools backed by
[DeepSeek's official Search / Fetch API](https://api-docs.deepseek.com/guides/search), and keeps
them **visible only to DeepSeek models** — GPT-family models in the same Codex install never see
or reach them.

```text
you: 请查一下 DeepSeek V4 的发布时间
model (deepseek-v4-flash) → mcp__ds_web__web_search("DeepSeek V4 发布时间")
                          → 8 ranked results with summaries
                          → mcp__ds_web__web_fetch("https://…") when it needs the full page
```

## What it provides

| Tool | Purpose |
|---|---|
| `web_search` | Ranked web results: title, URL, publish date, `rerank_score`, `authority`, 600–800 char summary. Supports `site:`, `-site:`, `"exact phrase"`, `-word`, `lang:zh,en`, `after:2025`, `before:2026-01-01`. |
| `web_fetch` | Fetch one URL and return its readable content as Markdown. |

Both are read-only, use your existing DeepSeek API key, and are billed by DeepSeek per
successful request (¥5 / 1,000 requests each at the time of writing).

## How model isolation works

Three layers, cheapest first. Any one of them alone is enough; together they are belt-and-braces.

1. **Profile-scoped on/off switch.** Codex profiles (`~/.codex/<name>.config.toml`) can override
   `[plugins."ds-web@personal".mcp_servers.ds_web] enabled`. Default and GPT profiles keep it
   `false`, so the MCP server is never started and the tools are absent from the tool list.
2. **Session-start instruction.** If a GPT model starts a session while the plugin is on anyway,
   a `SessionStart` hook injects one developer-context paragraph naming the two tools and telling
   the model not to call them. The model reads this before it plans, so it never picks the tool
   and never burns a turn on a denial.
3. **`PreToolUse` model gate.** Codex passes the active model slug on every hook event. If a
   non-DeepSeek model calls `mcp__ds_web__*` regardless, the hook denies the call with a reason
   the model can read.

Verified in real sessions (`codex-cli 0.163.0`):

```text
# gpt-6-luna, plugin disabled → model sees no MCP tools
NONE

# gpt-6-luna, plugin force-enabled → told up front, and denied if it tries anyway
hook: SessionStart Completed
NO. "The ds_web MCP server … is for DeepSeek models only. This session runs 'gpt-6-luna',
so do not call those tools …"
Tool call blocked by PreToolUse hook: The mcp__ds_web__web_search tool is DeepSeek-only … (if forced)

# deepseek-v4-flash → notice stays silent, real search works
mcp: ds_web/web_search started
mcp: ds_web/web_search (completed)
10
```

## Requirements

- Codex CLI **0.144.0+** (tested on 0.163.0) — CLI, the ChatGPT desktop app, and the IDE
  extension all read the same `config.toml`, so one setup covers all three
- Python **3.9+** on `PATH` (stdlib only — no `pip install` needed)
- A DeepSeek API key from <https://platform.deepseek.com>

## Platform support

| Platform | Status | Notes |
|---|---|---|
| Linux | Works | `install.sh`. Verified on Debian 12 / codex-cli 0.163.0. |
| macOS | Works | `install.sh`. Same POSIX paths as Linux. |
| Windows (native) | Works, with `install.ps1` | `install.ps1` picks `python`/`py` instead of `python3` — Windows has no `python3`, and Codex's plugin MCP block has **no** per-platform command override (only hook handlers accept `commandWindows`), so the interpreter is pinned into `mcp.json` at install time. |
| Windows + WSL2 | Works | Codex inside WSL is a normal Linux install; use `install.sh` there. Windows-side `%USERPROFILE%\.codex` and WSL `~/.codex` are separate — set `CODEX_HOME` if you want them shared. |

Windows specifics worth knowing: native Codex on Windows runs MCP stdio servers from the app
process, so a shell shim such as `npx.cmd` or `corepack` can fail at handshake. This plugin dodges
that class of bug entirely — it launches a real `python.exe`/`py.exe` with a relative script path,
no `.cmd` shim involved. If you hit a launch problem anyway, the fix is the same one that works for
every MCP client on Windows: point `command` at the absolute interpreter and keep the script path.

## Install

**Linux / macOS**
```bash
git clone https://github.com/chaojisizhu/codex-deepseek-web.git
cd codex-deepseek-web
./install.sh
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/chaojisizhu/codex-deepseek-web.git
cd codex-deepseek-web
.\install.ps1
```

Either script copies the payload to `~/plugins/ds-web` (`%USERPROFILE%\plugins\ds-web` on
Windows), registers it in the personal marketplace (`.agents/plugins/marketplace.json`), pins a
Python interpreter, and runs `codex plugin add ds-web@personal`.

Then give Codex your key — the MCP server inherits it from Codex's environment:

```bash
export DEEPSEEK_API_KEY=sk-...          # Linux / macOS
```
```powershell
setx DEEPSEEK_API_KEY "sk-..."          # Windows (new shells pick it up)
```

## Configure

### 1. DeepSeek as a provider

Model metadata (context window, reasoning levels) matters for Codex. The easiest path is
DeepSeek's own setup script, which writes `~/.codex/models.json` and the provider block:

```bash
bash <(curl -fsSL https://cdn.deepseek.com/api-docs/codex-deepseek-setup-en.sh)
```

Or write it by hand — see
[DeepSeek's Codex integration guide](https://api-docs.deepseek.com/quick_start/agent_integrations/codex):

```toml
# ~/.codex/config.toml
[model_providers.deepseek]
name = "deepseek"
base_url = "https://api.deepseek.com/"
wire_api = "responses"
env_key = "DEEPSEEK_API_KEY"
```

### 2. Keep the tools off by default

```toml
# ~/.codex/config.toml
[plugins."ds-web@personal".mcp_servers.ds_web]
enabled = false
```

### 3. Turn them on for DeepSeek only

```toml
# ~/.codex/deepseek.config.toml
model = "deepseek-v4-flash"
model_provider = "deepseek"
model_reasoning_effort = "high"

[plugins."ds-web@personal".mcp_servers.ds_web]
enabled = true
```

### 4. Run it

```bash
codex --profile deepseek
```

The first run asks you to trust the plugin's hooks — they are the model gate and the session
notice, so review them and approve. For unattended runs (CI, scripts) you can pass
`--dangerously-bypass-hook-trust`, which skips the review — only do that where you already vet
hook sources.

## Verification

```bash
# No MCP tools should be listed in a GPT/default session
codex exec "List every tool name starting with mcp__. If none, reply NONE"

# DeepSeek profile should have them, and a real search should return results
codex --profile deepseek exec "Search the web for 'deepseek v4' and reply with the result count"

# Which servers are on, per profile
codex mcp list --json
codex --profile deepseek mcp list --json
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `mcp: ds_web/web_search (failed)` + `401` | `DEEPSEEK_API_KEY` not in Codex's environment. Export it in the shell that launches Codex (`setx` on Windows, then a new shell). |
| `DEEPSEEK_API_KEY is not set in this MCP server's environment` | You overrode `[mcp_servers.ds_web]` in `config.toml` and dropped the `env_vars` line; re-add `env_vars = ["DEEPSEEK_API_KEY"]`. |
| No `mcp__ds_web__*` tools at all | Plugin disabled for this profile. Check `codex mcp list --json` and the `enabled` line. |
| Hook never fires (`hook:` lines absent) | Hook not trusted yet (approve it on first TUI run) or `features.hooks` disabled. |
| `No marketplace plugins found` | The `[marketplaces.personal]` table got wiped from `config.toml`. Re-run the installer. |
| Plugin tools never appear, MCP fails to handshake | Wrong interpreter name for the host (`python3` on Windows). Re-run the installer, which pins a working one. |
| `402` from DeepSeek | Account balance empty for the Search/Fetch endpoints. Top up. |

## Uninstall

```bash
./install.sh --uninstall        # Linux / macOS
```
```powershell
.\install.ps1 -Uninstall        # Windows
```

Then delete the `[plugins."ds-web@personal"]` and `[marketplaces.personal]` tables from
`config.toml` if you no longer want them.

## Repo layout

```text
.codex-plugin/plugin.json   Codex manifest (declares mcpServers + hooks)
mcp.json                    MCP server definition (interpreter pinned at install time)
server/ds_web_mcp.py        stdio MCP server → DeepSeek Search/Fetch (stdlib only)
hooks/model_gate.py         PreToolUse gate: deny the tools to non-DeepSeek models
hooks/session_notice.py     SessionStart notice: tell non-DeepSeek models up front
hooks/hooks.json            Hook registration (both hooks, with Windows commands)
scripts/select_python_command.py   Picks python3 / python / py for this host
install.sh / install.ps1    Installers (POSIX / Windows)
```

### Notes for anyone editing the plugin

- Codex resolves `${PLUGIN_ROOT}` in `mcp.json` **only** for the Agent Plugins format (root
  `plugin.json` with `$schema` + `type: "stdio"` per server). This repo uses the `.codex-plugin/`
  compatibility manifest, where `${PLUGIN_ROOT}` in `args` is **not** expanded — so the server is
  launched with `cwd: "./"` and a relative `server/ds_web_mcp.py` path instead.
- `"${DEEPSEEK_API_KEY}"` inside `env` is likewise not expanded. Use `env_vars` to pass the
  variable through from Codex's own environment.
- Hook handlers accept `command` + `commandWindows`; **MCP servers do not**. Anything that must
  differ per platform has to be written into `mcp.json` at install time, which is what
  `scripts/select_python_command.py` is for.
- Hook handler timeout key is `timeout` (seconds; `timeoutSec` is rejected).
- `plugin_hooks` is a *removed* feature flag in 0.163.0; the stable `hooks` flag governs hook
  loading, and plugin-bundled hooks load with it.
- A `matcher` that names a whole server (`mcp__ds_web`) matches nothing — hook tool names are
  `mcp__<server>__<tool>`, so use a regex like `mcp__ds_web.*`.

## License

MIT — see [LICENSE](LICENSE).
