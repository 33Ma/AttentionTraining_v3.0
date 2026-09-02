# -*- coding: utf-8 -*-
"""AI 教练请求取消行为测试（需要 PySide6 与本地 HTTP 服务）。"""

import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from ai.ai_coach import AICoachWorker, _RequestCancelled


class _SlowHandler(BaseHTTPRequestHandler):
    """服务端延迟 5 秒响应，模拟慢速/挂起的 API。"""

    def do_POST(self):
        time.sleep(5)
        body = b'{"choices":[{"message":{"content":"ok"}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class CancellationTests(unittest.TestCase):
    def test_cancel_returns_promptly(self):
        server = HTTPServer(("127.0.0.1", 0), _SlowHandler)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            worker = AICoachWorker()
            result = {}

            def run():
                try:
                    worker._call_api(
                        "你好", None, [], [],
                        "sk-test", f"http://127.0.0.1:{port}/chat/completions", "test-model",
                    )
                    result["ok"] = True
                except Exception as exc:
                    result["exc"] = exc

            call_thread = threading.Thread(target=run, daemon=True)
            start = time.monotonic()
            call_thread.start()
            time.sleep(0.3)
            worker.cancel()
            call_thread.join(timeout=3)
            elapsed = time.monotonic() - start

            self.assertFalse(call_thread.is_alive(), "取消后 _call_api 应尽快返回")
            self.assertIsInstance(result.get("exc"), _RequestCancelled)
            self.assertLess(elapsed, 2.5, "取消后应快速返回，而不是等待网络超时")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
