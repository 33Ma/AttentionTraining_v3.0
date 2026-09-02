# -*- coding: utf-8 -*-
"""AI 教练本地兜底信号测试（需要 PySide6）。"""

import unittest

from ai.ai_coach import AICoachWorker


def _record():
    return {
        "avg_attention": 88,
        "total_blinks": 120,
        "max_consecutive_hits": 18,
        "game_score": 420,
        "game_mode": "find_difference",
        "duration_minutes": 10,
        "avg_gaze_score": 80,
        "avg_gaze_distance": 0.12,
    }


class LocalFallbackSignalTests(unittest.TestCase):
    def test_unknown_question_emits_local_fallback(self):
        worker = AICoachWorker()
        fallback = []
        ready = []
        worker.local_fallback_ready.connect(fallback.append)
        worker.message_ready.connect(ready.append)
        worker.process_message(
            "tester", "今天天气怎么样", None, [], [_record()],
            "", "", "", True,
        )
        self.assertEqual(len(fallback), 1)
        self.assertEqual(len(ready), 0)
        self.assertIn("暂时还不太确定", fallback[0])

    def test_kb_question_emits_message_ready(self):
        worker = AICoachWorker()
        fallback = []
        ready = []
        worker.local_fallback_ready.connect(fallback.append)
        worker.message_ready.connect(ready.append)
        worker.process_message(
            "tester", "怎么提高注意力？", None, [], [_record()],
            "", "", "", True,
        )
        self.assertEqual(len(fallback), 0)
        self.assertEqual(len(ready), 1)

    def test_analysis_request_emits_message_ready(self):
        worker = AICoachWorker()
        fallback = []
        ready = []
        worker.local_fallback_ready.connect(fallback.append)
        worker.message_ready.connect(ready.append)
        worker.process_message(
            "tester", "请帮我分析一下这次训练数据", None, [], [_record()],
            "", "", "", True,
        )
        self.assertEqual(len(fallback), 0)
        self.assertEqual(len(ready), 1)


if __name__ == "__main__":
    unittest.main()
