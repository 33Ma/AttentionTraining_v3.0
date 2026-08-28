# -*- coding: utf-8 -*-
"""班级报告评判与进步逻辑测试：以综合分为主，游戏得分归一为 0-100。"""

import unittest

from core.settings import TrainingRecord, DifficultyLevel
from ui.teacher_report_dialog import TeacherReportDialog
from ai.teacher_report_logic import (
    composite_improvement,
    compute_class_stats,
    compute_class_summaries,
    compute_student_summary,
    filter_records,
    format_duration,
    normalized_game_score,
)


def _record(mode: str, score: int, difficulty: str, composite: int,
            attention: int = 80) -> TrainingRecord:
    r = TrainingRecord()
    r.game_mode = mode
    r.game_score = score
    r.difficulty = DifficultyLevel(difficulty)
    r.composite_score = composite
    r.avg_attention_score = attention
    return r


class TeacherReportLogicTests(unittest.TestCase):
    def test_normalized_game_score_maps_find_to_0_100(self):
        norm = TeacherReportDialog._normalized_game_score
        # 找茬：实际得分 / 难度基准（普通 580）
        self.assertAlmostEqual(norm(_record("find_difference", 290, "normal", 70)), 50.0)
        self.assertAlmostEqual(norm(_record("find_difference", 580, "normal", 90)), 100.0)
        self.assertAlmostEqual(norm(_record("find_difference", 600, "easy", 90)), 100.0)
        # 动态追踪：本身就是 0-100，超限截断
        self.assertAlmostEqual(norm(_record("dynamic_tracking", 80, "hard", 65)), 80.0)
        self.assertAlmostEqual(norm(_record("dynamic_tracking", 150, "hard", 65)), 100.0)

    def test_composite_improvement_uses_composite_score(self):
        imp = TeacherReportDialog._composite_improvement
        records = [
            _record("find_difference", 300, "normal", 70),   # 最近
            _record("find_difference", 200, "normal", 30),   # 最早
        ]
        # (70-30)/30 = 133% -> 截断到 100
        self.assertAlmostEqual(imp(records), 100.0)

        records = [
            _record("find_difference", 200, "normal", 30),
            _record("find_difference", 300, "normal", 70),
        ]
        self.assertAlmostEqual(imp(records), (30 - 70) / 70 * 100.0)

    def test_composite_improvement_requires_two_records(self):
        self.assertEqual(
            TeacherReportDialog._composite_improvement([
                _record("find_difference", 300, "normal", 70),
            ]),
            0.0,
        )


def _dict_record(dt: str, attention: int = 80, score: int = 290,
                 mode: str = "find_difference", difficulty: str = "normal",
                 composite: int = 70, minutes: int = 10) -> dict:
    return {
        "date_time": dt, "duration_minutes": minutes, "game_mode": mode,
        "difficulty": difficulty, "avg_attention_score": attention,
        "total_blinks": 100, "game_score": score, "avg_ear": 0.3,
        "avg_gaze_score": 80, "avg_gaze_distance": 0.1,
        "max_consecutive_hits": 10, "face_detected": 1,
        "hit_rate": 0.8, "avg_response_time": 0.4, "path_efficiency": 0.7,
        "composite_score": composite,
    }


class TeacherReportModuleTests(unittest.TestCase):
    def test_module_normalized_score_matches_dialog(self):
        r = _record("find_difference", 290, "normal", 70)
        self.assertAlmostEqual(
            normalized_game_score(r), TeacherReportDialog._normalized_game_score(r)
        )

    def test_filter_records_last_7_days(self):
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        old = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
        records = [_dict_record(today), _dict_record(old)]
        kept = filter_records(records, filter_days=7)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["date_time"], today)

    def test_filter_records_current_month(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        first_this = now.replace(day=1).strftime("%Y-%m-%d 08:00:00")
        last_month = (
            now.replace(day=1) - timedelta(days=1)
        ).replace(day=15).strftime("%Y-%m-%d 08:00:00")
        records = [_dict_record(first_this), _dict_record(last_month)]
        self.assertEqual(len(filter_records(records, filter_days=-1)), 1)

    def test_compute_student_summary_aggregates(self):
        records = [
            _dict_record("2026-08-26 10:30:00", attention=90, score=580,
                         composite=88, minutes=12),
            _dict_record("2026-08-20 09:00:00", attention=70, score=290,
                         composite=60, minutes=8),
        ]
        s = compute_student_summary("stu1", "小明", records, achievements=2)
        self.assertEqual(s["total_trainings"], 2)
        self.assertEqual(s["total_minutes"], 20)
        self.assertEqual(s["avg_attention"], 80)
        self.assertEqual(s["max_attention"], 90)
        self.assertEqual(s["achievements"], 2)
        self.assertEqual(s["last_training"], "08-26 10:30")
        self.assertGreater(s["improvement"], 0)

    def test_compute_class_summaries_caps_students(self):
        students = [{"username": f"s{i}", "display_name": f"学生{i}"} for i in range(45)]
        summaries, stats = compute_class_summaries(students, {})
        self.assertEqual(len(summaries), 40)
        self.assertEqual(stats["total_students"], 40)

    def test_compute_class_stats_improving_declining(self):
        summaries = [
            {"display_name": "A", "avg_composite": 80, "improvement": 10.0,
             "total_trainings": 5, "total_minutes": 50, "avg_attention": 80},
            {"display_name": "B", "avg_composite": 30, "improvement": -20.0,
             "total_trainings": 5, "total_minutes": 50, "avg_attention": 40},
            {"display_name": "C", "avg_composite": 50, "improvement": 0.0,
             "total_trainings": 0, "total_minutes": 0, "avg_attention": 0},
        ]
        stats = compute_class_stats(summaries)
        self.assertEqual(stats["improving"], 1)
        self.assertEqual(stats["declining"], 1)
        self.assertEqual(stats["stable"], 1)
        self.assertEqual(stats["valid_students"], 2)
        self.assertEqual(stats["best"]["display_name"], "A")
        self.assertEqual(stats["worst"]["display_name"], "B")

    def test_format_duration(self):
        self.assertEqual(format_duration(45), "45分钟")
        self.assertEqual(format_duration(60), "1小时")
        self.assertEqual(format_duration(75), "1小时15分钟")


if __name__ == "__main__":
    unittest.main()
