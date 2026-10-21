#!/usr/bin/env python3
"""DeepSeek Web MCP server.

Exposes two MCP tools for Codex (and any MCP client):

  web_search  -> POST https://api.deepseek.com/v1/tools/search
  web_fetch   -> POST https://api.deepseek.com/v1/tools/fetch

Stdlib only, newline-delimited JSON-RPC 2.0 over stdio (MCP stdio transport).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
TIMEOUT = float(os.environ.get("DEEPSEEK_TIMEOUT", "60"))
MAX_FETCH_CHARS = int(os.environ.get("DSWEB_MAX_FETCH_CHARS", "60000"))
SERVER_NAME = "ds-web"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the live web with DeepSeek's search engine and get ranked results "
            "with title, url, publish date, authority score and a 600-800 char summary. "
            "Use this for anything that may have changed recently (news, releases, prices, "
            "docs, error messages, people, current events). "
            "Supports search operators inside `query`: site:example.com, -site:example.com, "
            '"exact phrase", -word, lang:zh,en, after:2025, before:2026-06-01.'
        ),
        "annotations": {
            "title": "Web Search (DeepSeek)",
            "readOnlyHint": True,
            "openWorldHint": True,
            "idempotentHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, 1-128 chars. Operators allowed (site:, lang:, after:, before:, quotes).",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of results, 1-50. Default 8.",
                    "minimum": 1,
                    "maximum": 50,
                },
                "need_content": {
                    "type": "boolean",
                    "description": "Also return extracted page body text for each result (much larger output). Default false; prefer web_fetch on the result you pick.",
                },
                "ori_question": {
                    "type": "string",
                    "description": "Optional original user question (<=128 chars) that triggered the search; improves intent matching.",
                },
                "localization": {
                    "type": "string",
                    "description": "Optional IP address used to localise results (e.g. 1.2.3.4). Usually omit.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch a single web page and return its readable content as Markdown. "
            "Use this after web_search to read a specific result in full, or when the user "
            "gives you a URL. Fails (with a clear error) on pages the fetch service cannot "
            "extract, paywalls and unsupported content types."
        ),
        "annotations": {
            "title": "Web Fetch (DeepSeek)",
            "readOnlyHint": True,
            "openWorldHint": True,
            "idempotentHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "HTTP/HTTPS URL to fetch (max 8192 chars, no credentials in URL).",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Truncate returned markdown to this many chars. Default from env, 60000.",
                    "minimum": 1000,
                },
            },
            "required": ["url"],
        },
    },
]


class ToolError(Exception):
    pass


def api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise ToolError(
            "DEEPSEEK_API_KEY is not set in this MCP server's environment. "
            "Add it to env_vars in the plugin's mcp.json or export it before starting Codex."
        )
    return key


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        message = body
        try:
            message = json.loads(body).get("error", {}).get("message") or body
        except Exception:
            pass
        hint = {
            401: "API key missing or invalid.",
            402: "DeepSeek account balance is insufficient.",
            403: "Fetch rejected by the provider's security policy.",
            404: "Fetch could not obtain usable page content (URL unavailable, blocked, or unsupported type).",
            429: "Rate limit hit (Search 100 QPS / Fetch 25 QPS per account). Retry after a moment.",
        }.get(exc.code, "")
        raise ToolError(f"DeepSeek API HTTP {exc.code}: {message} {hint}".strip()) from None
    except urllib.error.URLError as exc:
        raise ToolError(f"Cannot reach {API_BASE}: {exc.reason}") from None
    except TimeoutError:
        raise ToolError(f"DeepSeek API timed out after {TIMEOUT:.0f}s") from None


def do_search(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        raise ToolError("`query` is required and must not be blank.")
    count = args.get("count") or 8
    try:
        count = max(1, min(50, int(count)))
    except (TypeError, ValueError):
        count = 8
    payload = {"query": query, "count": count, "need_content": bool(args.get("need_content"))}
    if args.get("ori_question"):
        payload["ori_question"] = str(args["ori_question"])[:128]
    if args.get("localization"):
        payload["localization"] = str(args["localization"])

    data = post("/v1/tools/search", payload)
    results = data.get("results") or []
    if not results:
        return f'No results for "{query}". Try a shorter or differently worded query.'

    lines = [f'{len(results)} results for "{query}" (DeepSeek search):', ""]
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip() or "(untitled)"
        url = r.get("url") or ""
        meta = []
        if r.get("site_name"):
            meta.append(str(r["site_name"]))
        if r.get("date"):
            meta.append(str(r["date"])[:10])
        if r.get("rerank_score") is not None:
            meta.append(f"score {float(r['rerank_score']):.2f}")
        if r.get("authority") not in (None, -1):
            meta.append(f"authority {r['authority']}/4")
        lines.append(f"{i}. {title}")
        lines.append(f"   {url}")
        if meta:
            lines.append("   " + " | ".join(meta))
        body = (r.get("summary") or r.get("snippet") or "").strip()
        if body:
            lines.append("   " + body.replace("\n", " "))
        content = (r.get("content") or "").strip()
        if content:
            lines.append("   --- content ---")
            lines.append("   " + content.replace("\n", "\n   ")[:4000])
        lines.append("")
    lines.append("Fetch a result in full with web_fetch(url) when you need details.")
    return "\n".join(lines)


def do_fetch(args: dict) -> str:
    url = (args.get("url") or "").strip()
    if not url:
        raise ToolError("`url` is required.")
    limit = int(args.get("max_chars") or MAX_FETCH_CHARS)
    data = post("/v1/tools/fetch", {"url": url})
    title = (data.get("title") or "").strip()
    content = data.get("content") or ""
    if not content.strip():
        raise ToolError(f"Fetch returned no readable content for {url}")
    truncated = len(content) > limit
    body = content[:limit]
    head = f"# {title}\n\n{url}\n\n" if title else f"{url}\n\n"
    tail = f"\n\n[truncated to {limit} of {len(content)} chars]" if truncated else ""
    return head + body + tail


HANDLERS = {"web_search": do_search, "web_fetch": do_fetch}


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def ok(msg_id, result):
    send({"jsonrpc": "2.0", "id": msg_id, "result": result})


def err(msg_id, code, message):
    send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def handle(msg: dict) -> None:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        protocol = params.get("protocolVersion") or DEFAULT_PROTOCOL
        ok(
            msg_id,
            {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Live web access backed by DeepSeek's search/fetch API. "
                    "Call web_search when the answer may have changed since training; "
                    "then web_fetch the most relevant URL for full text."
                ),
            },
        )
        return
    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return
    if method == "ping":
        ok(msg_id, {})
        return
    if method == "tools/list":
        ok(msg_id, {"tools": TOOLS})
        return
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if not handler:
            err(msg_id, -32602, f"Unknown tool: {name}")
            return
        try:
            text = handler(arguments)
            ok(msg_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except ToolError as exc:
            ok(msg_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception as exc:  # noqa: BLE001 - surface anything else to the model
            ok(msg_id, {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True})
        return
    if method in ("resources/list", "prompts/list"):
        ok(msg_id, {("resources" if method.startswith("resources") else "prompts"): []})
        return
    if msg_id is not None:
        err(msg_id, -32601, f"Method not found: {method}")


def main() -> None:
    debug_log = os.environ.get("DSWEB_DEBUG_LOG", "").strip()
    if debug_log:
        try:
            with open(debug_log, "a", encoding="utf-8") as fh:
                fh.write(f"started pid={os.getpid()} argv={sys.argv} cwd={os.getcwd()}\n")
        except Exception:
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            err(None, -32700, "Parse error")
            continue
        if isinstance(msg, list):
            for item in msg:
                if isinstance(item, dict):
                    handle(item)
        elif isinstance(msg, dict):
            handle(msg)


if __name__ == "__main__":
    main()
