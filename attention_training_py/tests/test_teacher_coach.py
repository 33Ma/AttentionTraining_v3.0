# -*- coding: utf-8 -*-
"""教师端 AI 助教服务层测试（需要 PySide6；本地 HTTP 服务测试取消行为）。"""

import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from ai.teacher_coach import TeacherCoachManager, TeacherCoachWorker, _RequestCancelled


def _context():
    summary = {
        "name": "student", "display_name": "小明", "total_trainings": 4,
        "total_minutes": 45, "avg_attention": 72, "max_attention": 85,
        "avg_game_score": 60, "avg_composite": 65, "achievements": 2,
        "improvement": 8.0, "last_training": "08-26 10:30",
    }
    stats = {
        "total_students": 1, "valid_students": 1, "total_trainings": 4,
        "total_minutes": 45, "class_avg_attention": 72,
        "class_avg_composite": 65, "improving": 1, "declining": 0,
        "stable": 0, "best": summary, "worst": summary,
        "top_improvement_student": summary,
    }
    return {"summaries": [summary], "stats": stats}


class TeacherCoachManagerTests(unittest.TestCase):
    def test_singleton(self):
        self.assertIs(TeacherCoachManager.instance(), TeacherCoachManager.instance())

    def test_submit_message_rejects_empty(self):
        mgr = TeacherCoachManager.instance()
        self.assertEqual(mgr.submit_message("t", "   "), 0)
        self.assertEqual(mgr.submit_message("", "hi"), 0)


class TeacherCoachWorkerTests(unittest.TestCase):
    def test_local_class_analysis_emits_report(self):
        worker = TeacherCoachWorker()
        ready = []
        report = []
        worker.message_ready.connect(ready.append)
        worker.report_ready.connect(report.append)
        worker.process_message(
            "teacher", "帮我分析一下班级整体表现", _context(), [],
            "", "", "",
        )
        self.assertEqual(len(ready), 1)
        self.assertEqual(len(report), 1)
        self.assertIn("班级训练情况分析", ready[0])

    def test_local_unknown_question_emits_local_fallback(self):
        worker = TeacherCoachWorker()
        fallback = []
        ready = []
        worker.local_fallback_ready.connect(fallback.append)
        worker.message_ready.connect(ready.append)
        worker.process_message(
            "teacher", "今天天气怎么样", _context(), [],
            "", "", "",
        )
        self.assertEqual(len(fallback), 1)
        self.assertEqual(len(ready), 0)
        self.assertIn("还不确定", fallback[0])


class _SlowHandler(BaseHTTPRequestHandler):
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


class TeacherCoachCancellationTests(unittest.TestCase):
    def test_cancel_returns_promptly(self):
        server = HTTPServer(("127.0.0.1", 0), _SlowHandler)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            worker = TeacherCoachWorker()
            result = {}

            def run():
                try:
                    worker._call_api(
                        "你好", None, [],
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
