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

Two independent gates. Either one alone is enough; together they are belt-and-braces.

1. **Profile-scoped on/off switch.** Codex profiles (`~/.codex/<name>.config.toml`) can override
   `[plugins."ds-web@personal".mcp_servers.ds_web] enabled`. Default and GPT profiles keep it
   `false`, so the MCP server is never started and the tools are absent from the tool list.
2. **`PreToolUse` model gate.** Codex passes the active model slug on every hook event. If a
   non-DeepSeek model calls `mcp__ds_web__*`, the bundled hook denies the call with a reason the
   model can read, telling it not to retry.

Verified in real sessions (`codex-cli 0.163.0`):

```text
# gpt-6-luna, plugin disabled → model sees no MCP tools
NONE

# gpt-6-luna, plugin force-enabled → hook denies
Tool call blocked by PreToolUse hook: The mcp__ds_web__web_search tool is DeepSeek-only
and this session is running 'gpt-6-luna'. …

# deepseek-v4-flash → works
mcp: ds_web/web_search started
mcp: ds_web/web_search (completed)
10
```

## Requirements

- Codex CLI **0.144.0+** (tested on 0.163.0)
- Python **3.9+** on `PATH` as `python3` (stdlib only — no `pip install` needed)
- A DeepSeek API key from <https://platform.deepseek.com>

## Install

```bash
git clone https://github.com/chaojisizhu/codex-deepseek-web.git
cd codex-deepseek-web
./install.sh
```

This copies the payload to `~/plugins/ds-web`, registers it in the personal marketplace
(`~/.agents/plugins/marketplace.json`), and runs `codex plugin add ds-web@personal`.

Then export your key so Codex can forward it to the MCP server:

```bash
export DEEPSEEK_API_KEY=sk-...
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

The first run asks you to trust the plugin's hook — that hook is the model gate, so review it
and approve. For unattended runs (CI, scripts) you can pass
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
| `mcp: ds_web/web_search (failed)` + `401` | `DEEPSEEK_API_KEY` not in Codex's environment. Export it in the shell that launches Codex. |
| No `mcp__ds_web__*` tools at all | Plugin disabled for this profile. Check `codex mcp list --json` and the `enabled` line. |
| Hook never fires (`hook:` lines absent) | Hook not trusted yet (approve it on first TUI run) or `features.hooks` disabled. |
| `No marketplace plugins found` | The `[marketplaces.personal]` table got wiped from `config.toml`. Re-run `./install.sh`. |
| `402` from DeepSeek | Account balance empty for the Search/Fetch endpoints. Top up. |

## Uninstall

```bash
./install.sh --uninstall
```

Then delete the `[plugins."ds-web@personal"]` and `[marketplaces.personal]` tables from
`~/.codex/config.toml` if you no longer want them.

## Repo layout

```text
.codex-plugin/plugin.json   Codex manifest (declares mcpServers + hooks)
mcp.json                    MCP server definition
server/ds_web_mcp.py        stdio MCP server → DeepSeek Search/Fetch (stdlib only)
hooks/model_gate.py         PreToolUse gate: DeepSeek models only
hooks/hooks.json            Gate registration
install.sh                  Installer / uninstaller
```

### Notes for anyone editing the plugin

- Codex resolves `${PLUGIN_ROOT}` in `mcp.json` **only** for the Agent Plugins format (root
  `plugin.json` with `$schema` + `type: "stdio"` per server). This repo uses the `.codex-plugin/`
  compatibility manifest, where `${PLUGIN_ROOT}` in `args` is **not** expanded — so the server is
  launched with `cwd: "./"` and a relative `server/ds_web_mcp.py` path instead.
- `"${DEEPSEEK_API_KEY}"` inside `env` is likewise not expanded. Use `env_vars` to pass the
  variable through from Codex's own environment.
- Hook handler timeout key is `timeout` (seconds).
- `plugin_hooks` is a *removed* feature flag in 0.163.0; the stable `hooks` flag governs hook
  loading, and plugin-bundled hooks load with it.

## License

MIT — see [LICENSE](LICENSE).
