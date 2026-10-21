"""Regression checks for MCP deadlines and concurrent slow HTTP requests."""

import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch


SERVER_PATH = Path(__file__).resolve().parents[1] / "server" / "ds_web_mcp.py"
SPEC = importlib.util.spec_from_file_location("ds_web_timeout_tests", SERVER_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class SlowAPI(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body = json.dumps({"results": []}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            if data.get("query") == "slow":
                # 持续有字节到达，刻意绕过 socket 的“无数据”超时。
                for byte in body:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.04)
            else:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def tool_call(identifier, query):
    return {
        "jsonrpc": "2.0", "id": identifier, "method": "tools/call",
        "params": {"name": "web_search", "arguments": {"query": query}},
    }


class TimeoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowAPI)
        cls.api.daemon_threads = True
        cls.listener = threading.Thread(target=cls.api.serve_forever, daemon=True)
        cls.listener.start()

    @classmethod
    def tearDownClass(cls):
        cls.api.shutdown()
        cls.api.server_close()
        cls.listener.join(timeout=2)

    def run_mcp(self, messages, timeout=0.2):
        env = dict(os.environ)
        env.update({
            "DEEPSEEK_API_KEY": "local-test-only",
            "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{self.api.server_port}",
            "DEEPSEEK_TIMEOUT": str(timeout),
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_PROXY": "127.0.0.1",
        })
        # 测试走真实子进程和本地 HTTP，不读取或使用用户的认证信息。
        process = subprocess.Popen(
            [sys.executable, str(SERVER_PATH)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=env,
        )
        # 从完成握手后计时，避免 Windows 解释器启动和病毒扫描影响截止时间断言。
        process.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": "ready", "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }) + "\n")
        process.stdin.flush()
        handshake = queue.Queue()
        threading.Thread(
            target=lambda: handshake.put(process.stdout.readline()), daemon=True,
        ).start()
        try:
            self.assertEqual(json.loads(handshake.get(timeout=4))["id"], "ready")
            started = time.monotonic()
            stdout, stderr = process.communicate(
                "".join(json.dumps(message) + "\n" for message in messages), timeout=4,
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)
        self.assertEqual(process.returncode, 0, stderr)
        return (
            [json.loads(line) for line in stdout.splitlines()],
            time.monotonic() - started,
        )

    def test_slow_trickle_has_total_deadline_and_does_not_block_ping(self):
        replies, elapsed = self.run_mcp([
            tool_call(1, "slow"),
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ])
        self.assertEqual([reply["id"] for reply in replies], [2, 1])
        self.assertTrue(replies[1]["result"]["isError"])
        self.assertIn("total time limit", replies[1]["result"]["content"][0]["text"])
        self.assertLess(elapsed, 0.5)

    def test_fast_tool_completes_while_another_tool_is_slow(self):
        replies, _ = self.run_mcp([tool_call(1, "slow"), tool_call(2, "fast")])
        self.assertEqual([reply["id"] for reply in replies], [2, 1])
        self.assertFalse(replies[0]["result"]["isError"])
        self.assertTrue(replies[1]["result"]["isError"])

    def test_eof_does_not_wait_for_underlying_timed_out_worker(self):
        replies, elapsed = self.run_mcp([tool_call(1, "slow")], timeout=0.1)
        self.assertEqual(len(replies), 1)
        self.assertTrue(replies[0]["result"]["isError"])
        self.assertLess(elapsed, 0.55)

    def test_full_workers_fail_fast_without_queue_or_duplicate_timeout_reply(self):
        release = threading.Event()
        finished = threading.Event()

        def blocked(_):
            release.wait(2)
            finished.set()
            return "late success"

        output = io.StringIO()
        calls = SERVER.ToolCalls(timeout=0.04, limit=1)
        with patch.object(sys, "stdout", output):
            try:
                calls.submit(1, blocked, {})
                calls.wait()
                # 到时仍在执行的网络任务保持占用槽位，防止后台线程无限增长。
                calls.submit(2, lambda _: "must not run", {})
            finally:
                release.set()
                self.assertTrue(finished.wait(1))
                time.sleep(0.04)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([reply["id"] for reply in replies], [1, 2])
        self.assertTrue(all(reply["result"]["isError"] for reply in replies))
        self.assertIn("busy", replies[1]["result"]["content"][0]["text"])
        self.assertNotIn("late success", output.getvalue())

    def test_success_cancels_deadline_and_has_single_reply(self):
        output = io.StringIO()
        calls = SERVER.ToolCalls(timeout=0.04, limit=1)
        with patch.object(sys, "stdout", output):
            calls.submit(1, lambda _: "finished", {})
            calls.wait()
            time.sleep(0.07)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(replies), 1)
        self.assertFalse(replies[0]["result"]["isError"])

    def test_worker_start_failure_replies_and_releases_capacity(self):
        output = io.StringIO()
        calls = SERVER.ToolCalls(timeout=0.1, limit=1)
        with patch.object(sys, "stdout", output):
            with patch.object(
                threading.Timer, "start", side_effect=RuntimeError("cannot start new thread"),
            ):
                calls.submit(1, lambda _: "must not run", {})
                calls.wait()
            calls.submit(2, lambda _: "recovered", {})
            calls.wait()
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([reply["id"] for reply in replies], [1, 2])
        self.assertTrue(replies[0]["result"]["isError"])
        self.assertFalse(replies[1]["result"]["isError"])

    def test_oversized_and_nonfinite_timeouts_remain_below_client_deadline(self):
        for value in ("300", "inf", "nan"):
            with self.subTest(value=value):
                env = dict(os.environ, DEEPSEEK_TIMEOUT=value, PYTHONDONTWRITEBYTECODE="1")
                source = (
                    "import importlib.util;"
                    f"s=importlib.util.spec_from_file_location('m',{str(SERVER_PATH)!r});"
                    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                    "print(m.TIMEOUT)"
                )
                process = subprocess.run(
                    [sys.executable, "-c", source],
                    capture_output=True, text=True, env=env, timeout=3, check=True,
                )
                self.assertLessEqual(float(process.stdout), 240)


if __name__ == "__main__":
    unittest.main()
