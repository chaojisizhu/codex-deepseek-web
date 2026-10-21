"""Regression coverage for malformed Unicode in model inputs and MCP replies."""

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


SERVER_PATH = Path(__file__).resolve().parents[1] / "server" / "ds_web_mcp.py"
SPEC = importlib.util.spec_from_file_location("ds_web_unicode_tests", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)


class UnicodeTests(unittest.TestCase):
    def run_mcp_with_encoding(self, encoding):
        # 不继承工具环境强设的 UTF-8，真实覆盖 Windows 本地代码页启动方式。
        environment = dict(os.environ)
        environment.pop("PYTHONIOENCODING", None)
        environment["PYTHONUTF8"] = "0"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if encoding is not None:
            environment["PYTHONIOENCODING"] = encoding
        program = f"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("ds_web_encoding_probe", {str(SERVER_PATH)!r})
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)
server.HANDLERS["web_search"] = lambda args: json.dumps(args, ensure_ascii=False)
server.main()
"""
        arguments = {"query": "洛天依😀", "ori_question": "搜一下洛天依"}
        message = {
            "jsonrpc": "2.0", "id": 41, "method": "tools/call",
            "params": {"name": "web_search", "arguments": arguments},
        }
        result = subprocess.run(
            [sys.executable, "-c", program],
            input=(json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"),
            capture_output=True, env=environment, timeout=10, check=True,
        )
        reply = json.loads(result.stdout.decode("utf-8", "strict"))
        self.assertFalse(reply["result"]["isError"])
        self.assertEqual(
            json.loads(reply["result"]["content"][0]["text"]),
            arguments,
        )

    def test_mcp_utf8_overrides_cp936_surrogateescape(self):
        self.run_mcp_with_encoding("cp936:surrogateescape")

    def test_mcp_utf8_without_inherited_encoding_override(self):
        self.run_mcp_with_encoding(None)

    def test_normal_unicode_is_preserved(self):
        text = "中文搜索 😀 café"
        self.assertEqual(server.normalize_json(text), text)

    def test_surrogate_pairs_are_combined(self):
        self.assertEqual(server.normalize_json("a\ud83d\ude00b"), "a😀b")

    def test_lone_high_and_low_surrogates_are_replaced(self):
        self.assertEqual(server.normalize_json("a\ud83db\ude00c"), "a\ufffdb\ufffdc")

    def test_nested_json_and_keys_are_normalized(self):
        payload = {"\ud83d": [{"value": "\ud83d\ude00"}, "\ude00"], "count": 2, "flag": True}
        self.assertEqual(
            server.normalize_json(payload),
            {"\ufffd": [{"value": "😀"}, "\ufffd"], "count": 2, "flag": True},
        )

    def test_api_request_has_only_valid_utf8_and_unicode_scalars(self):
        payload = {"query": "中文\ud83d", "extra": ["\ud83d\ude00", "\ude00"]}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), patch.object(
            server.urllib.request, "urlopen",
            return_value=io.BytesIO(b'{"results": []}'),
        ) as request:
            self.assertEqual(server.post("/v1/tools/search", payload), {"results": []})
        body = request.call_args.args[0].data.decode("utf-8", "strict")
        decoded = json.loads(body)
        self.assertEqual(decoded, {"query": "中文\ufffd", "extra": ["😀", "\ufffd"]})
        # 模拟上游严格 Unicode 校验，确认请求里没有残留代理码点。
        json.dumps(decoded, ensure_ascii=False).encode("utf-8", "strict")
        self.assertNotIn("\\ud83d", body.lower())

    def test_original_question_limit_does_not_split_surrogate_pair(self):
        question = "x" * 127 + "\ud83d\ude00" + "tail"
        with patch.object(server, "post", return_value={"results": []}) as post:
            server.do_search({"query": "test", "ori_question": question})
        actual = post.call_args.args[1]["ori_question"]
        self.assertEqual(actual, "x" * 127 + "😀")
        self.assertEqual(len(actual), 128)

    def test_mcp_response_survives_ascii_only_stdout(self):
        # Windows 的管道可能继承非 UTF-8 编码，JSON 仍须完整发送。
        raw = io.BytesIO()
        stdout = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
        message = {"result": {"text": "中文😀\ud83d\ude00\ud83d"}}
        with patch.object(server.sys, "stdout", stdout):
            server.send(message)
        encoded = raw.getvalue()
        self.assertEqual(encoded.count(b"\n"), 1)
        self.assertEqual(json.loads(encoded)["result"]["text"], "中文😀😀\ufffd")
        stdout.detach()

    def test_malformed_query_can_be_returned_in_no_results_message(self):
        with patch.object(server, "post", return_value={"results": []}):
            text = server.do_search({"query": "test\ud83d"})
        stdout = io.StringIO()
        with patch.object(server.sys, "stdout", stdout):
            server.ok(9, {"content": [{"type": "text", "text": text}], "isError": False})
        reply = json.loads(stdout.getvalue())
        self.assertIn("test\ufffd", reply["result"]["content"][0]["text"])
        self.assertEqual(reply["id"], 9)


if __name__ == "__main__":
    unittest.main()
