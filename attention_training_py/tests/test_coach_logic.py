# -*- coding: utf-8 -*-
"""AI 教练对话纯逻辑测试（不依赖 Qt，可独立运行）。"""

import unittest

from ai.coach_logic import (
    build_system_prompt,
    local_coach_reply,
    local_coach_reply_detailed,
    normalize_chat_completions_url,
    trim_history,
)


class StubAnalyzer:
    """替身本地分析引擎，固定返回一段报告文本。"""

    def analyze_session(self, **kwargs):
        return "📊 训练数据概览\n• 平均注意力分数：88/100\n🏆 综合评分：85/100"


class BuildSystemPromptTests(unittest.TestCase):
    def test_prompt_contains_coach_persona(self):
        prompt = build_system_prompt()
        self.assertIn("AI教练", prompt)
        self.assertIn("中文", prompt)

    def test_prompt_includes_session_context(self):
        context = {
            "avg_attention": 88,
            "total_blinks": 120,
            "max_consecutive_hits": 18,
            "game_score": 420,
            "game_mode": "find_difference",
            "duration_minutes": 10,
            "avg_gaze_score": 80,
            "avg_gaze_distance": 0.12,
        }
        prompt = build_system_prompt(session_context=context)
        self.assertIn("88", prompt)
        self.assertIn("找茬模式", prompt)

    def test_prompt_includes_recent_records(self):
        records = [
            {"date_time": "2026-08-26 12:00", "game_mode": "dynamic_tracking",
             "avg_attention_score": 90, "game_score": 700}
        ]
        prompt = build_system_prompt(recent_records=records)
        self.assertIn("2026-08-26", prompt)
        self.assertIn("动态追踪模式", prompt)

    def test_prompt_instructs_direct_answer_for_common_questions(self):
        prompt = build_system_prompt()
        self.assertIn("直接回答用户的问题", prompt)
        self.assertIn("不要强行输出数据分析", prompt)


class NormalizeUrlTests(unittest.TestCase):
    def test_full_endpoint_unchanged(self):
        url = "https://api.openai.com/v1/chat/completions"
        self.assertEqual(normalize_chat_completions_url(url), url)

    def test_base_url_appends_endpoint(self):
        self.assertEqual(
            normalize_chat_completions_url("https://api.deepseek.com"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_trailing_slash_stripped(self):
        self.assertEqual(
            normalize_chat_completions_url("https://api.deepseek.com/"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_v1_prefix_appends_endpoint(self):
        self.assertEqual(
            normalize_chat_completions_url("https://api.openai.com/v1"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_v1_chat_prefix_appends_completions(self):
        self.assertEqual(
            normalize_chat_completions_url("https://api.openai.com/v1/chat"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_whitespace_stripped(self):
        self.assertEqual(
            normalize_chat_completions_url("  https://api.deepseek.com  "),
            "https://api.deepseek.com/chat/completions",
        )

    def test_empty_unchanged(self):
        self.assertEqual(normalize_chat_completions_url(""), "")


class TrimHistoryTests(unittest.TestCase):
    def test_keeps_last_n_turns(self):
        messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)}
                    for i in range(30)]
        trimmed = trim_history(messages, max_turns=10)
        self.assertEqual(len(trimmed), 20)
        self.assertEqual(trimmed[0]["content"], "10")
        self.assertEqual(trimmed[-1]["content"], "29")

    def test_short_history_unchanged(self):
        messages = [{"role": "user", "content": "hi"}]
        self.assertEqual(trim_history(messages), messages)


def _sample_context():
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


class LocalCoachReplyTests(unittest.TestCase):
    def test_analysis_request_returns_report(self):
        reply, kind = local_coach_reply(
            "请帮我分析一下这次训练数据",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "report")
        self.assertIn("综合评分", reply)

    def test_training_summary_question_returns_report(self):
        reply, kind = local_coach_reply(
            "我的训练成绩怎么样",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "report")
        self.assertIn("综合评分", reply)

    def test_analysis_request_without_data_returns_advice(self):
        reply, kind = local_coach_reply(
            "点评我的训练", analyzer=StubAnalyzer()
        )
        self.assertEqual(kind, "advice")
        self.assertTrue(reply)

    def test_greeting_answered_directly(self):
        reply, kind = local_coach_reply(
            "你好，在吗？",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "advice")
        self.assertNotIn("综合评分", reply)
        self.assertIn("教练", reply)

    def test_improve_question_answered_directly(self):
        reply, kind = local_coach_reply(
            "怎么提高注意力？",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "advice")
        self.assertNotIn("综合评分", reply)
        self.assertIn("注意力", reply)

    def test_mode_question_answered_directly(self):
        reply, kind = local_coach_reply(
            "找茬模式和动态追踪模式有什么区别？",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "advice")
        self.assertIn("找茬", reply)
        self.assertIn("动态追踪", reply)

    def test_schedule_question_answered_directly(self):
        reply, kind = local_coach_reply(
            "每周训练几次比较好？",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "advice")
        self.assertNotIn("综合评分", reply)

    def test_unknown_question_does_not_force_report(self):
        reply, kind = local_coach_reply(
            "今天天气怎么样",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "advice")
        self.assertNotIn("综合评分", reply)


class LocalCoachReplyDetailedTests(unittest.TestCase):
    def test_unknown_question_needs_cloud(self):
        reply, kind, needs_cloud = local_coach_reply_detailed(
            "今天天气怎么样",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "advice")
        self.assertTrue(needs_cloud)
        self.assertIn("暂时还不太确定", reply)

    def test_kb_question_does_not_need_cloud(self):
        reply, kind, needs_cloud = local_coach_reply_detailed(
            "怎么提高注意力？",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "advice")
        self.assertFalse(needs_cloud)

    def test_analysis_request_does_not_need_cloud(self):
        reply, kind, needs_cloud = local_coach_reply_detailed(
            "请帮我分析一下这次训练数据",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "report")
        self.assertFalse(needs_cloud)

    def test_wrapper_keeps_two_tuple(self):
        reply, kind = local_coach_reply(
            "怎么提高注意力？",
            session_context=_sample_context(),
            analyzer=StubAnalyzer(),
        )
        self.assertEqual(kind, "advice")
        self.assertTrue(reply)


if __name__ == "__main__":
    unittest.main()
