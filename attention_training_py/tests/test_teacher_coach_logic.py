# -*- coding: utf-8 -*-
"""教师端 AI 助教纯逻辑测试（不依赖 Qt）。"""

import unittest

from ai.teacher_coach_logic import (
    build_teacher_system_prompt,
    format_class_context,
    local_teacher_reply_detailed,
)


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


class TeacherCoachPromptTests(unittest.TestCase):
    def test_system_prompt_contains_persona(self):
        prompt = build_teacher_system_prompt()
        self.assertIn("AI助教", prompt)
        self.assertIn("中文", prompt)
        self.assertIn("直接回答", prompt)

    def test_prompt_includes_class_context(self):
        ctx = _context()
        prompt = build_teacher_system_prompt(
            format_class_context(ctx["summaries"], ctx["stats"])
        )
        self.assertIn("小明", prompt)
        self.assertIn("综合分", prompt)
        self.assertIn("学生明细", prompt)


class TeacherCoachLocalReplyTests(unittest.TestCase):
    def test_class_analysis_returns_report(self):
        reply, kind, needs_cloud = local_teacher_reply_detailed(
            "帮我分析一下班级整体表现", _context()
        )
        self.assertEqual(kind, "report")
        self.assertFalse(needs_cloud)
        self.assertIn("班级训练情况分析", reply)

    def test_student_name_match(self):
        reply, kind, _ = local_teacher_reply_detailed("小明最近怎么样", _context())
        self.assertEqual(kind, "advice")
        self.assertIn("小明", reply)

    def test_risk_query_returns_report(self):
        reply, kind, _ = local_teacher_reply_detailed(
            "哪些学生需要重点关注", _context()
        )
        self.assertEqual(kind, "report")
        self.assertIn("重点关注", reply)

    def test_advice_query(self):
        reply, kind, _ = local_teacher_reply_detailed("给一些教学建议", _context())
        self.assertEqual(kind, "advice")
        self.assertIn("教学建议", reply)

    def test_knowledge_question(self):
        reply, kind, _ = local_teacher_reply_detailed(
            "每周应该训练几次", _context()
        )
        self.assertEqual(kind, "advice")
        self.assertIn("3-4", reply)

    def test_no_data_returns_guidance(self):
        reply, kind, needs_cloud = local_teacher_reply_detailed(
            "帮我分析班级表现", None
        )
        self.assertEqual(kind, "advice")
        self.assertFalse(needs_cloud)
        self.assertIn("还没有", reply)

    def test_fallback_needs_cloud(self):
        reply, kind, needs_cloud = local_teacher_reply_detailed(
            "今天天气怎么样", _context()
        )
        self.assertEqual(kind, "advice")
        self.assertTrue(needs_cloud)
        self.assertIn("还不确定", reply)


if __name__ == "__main__":
    unittest.main()
