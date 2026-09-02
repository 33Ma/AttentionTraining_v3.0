# -*- coding: utf-8 -*-
"""综合分“可视化”相关辅助函数测试：记录取值/重算、分量分解、档位文案。"""

import importlib.util
import pathlib
import unittest
from types import SimpleNamespace


_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MODULE_PATH = _PROJECT_ROOT / "ai" / "composite_scoring.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("composite_scoring", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


composite_scoring = _load_module()
composite_score = composite_scoring.composite_score
record_composite_score = composite_scoring.record_composite_score
composite_details = composite_scoring.composite_details
score_band_label = composite_scoring.score_band_label


class _DifficultyEnumLike:
    def __init__(self, value: str):
        self.value = value


class RecordCompositeTests(unittest.TestCase):
    def test_stored_value_returned(self):
        rec = {"composite_score": 72, "avg_attention_score": 88}
        self.assertEqual(record_composite_score(rec), 72)

    def test_legacy_dict_recomputed_from_fields(self):
        rec = {
            "composite_score": -1,
            "avg_attention_score": 88,
            "max_consecutive_hits": 18,
            "game_score": 420,
            "game_mode": "find_difference",
            "difficulty": "normal",
            "avg_gaze_score": 90,
            "face_detected": 1,
        }
        expected = composite_score(88, 18, 420, "find_difference", "normal", 90, 1)
        self.assertEqual(record_composite_score(rec), expected)

    def test_object_record_recomputed_with_enum_difficulty(self):
        rec = SimpleNamespace(
            composite_score=-1,
            avg_attention_score=80,
            max_consecutive_hits=10,
            game_score=300,
            game_mode="find_difference",
            difficulty=_DifficultyEnumLike("hard"),
            avg_gaze_score=85,
            face_detected=1,
        )
        expected = composite_score(80, 10, 300, "find_difference", "hard", 85, 1)
        self.assertEqual(record_composite_score(rec), expected)

    def test_missing_camera_and_no_game_score_scores_zero(self):
        rec = SimpleNamespace(
            composite_score=-1, avg_attention_score=0, game_score=0,
            avg_gaze_score=0, face_detected=0,
        )
        self.assertEqual(record_composite_score(rec), 0)


class CompositeDetailsTests(unittest.TestCase):
    def test_details_total_matches_score_and_weights_sum_to_100(self):
        total, parts = composite_details(
            88, 18, 420, "find_difference", "normal", 90, face_detected=1
        )
        self.assertEqual(total, composite_score(88, 18, 420, "find_difference", "normal", 90, 1))
        self.assertEqual(len(parts), 3)
        self.assertAlmostEqual(sum(full for _, _, full in parts), 100.0)
        names = [name for name, _, _ in parts]
        self.assertIn("注意力", names)
        self.assertIn("最高连击", names)
        self.assertIn("游戏表现", names)

    def test_details_marks_missing_camera_component(self):
        total, parts = composite_details(
            50, 10, 300, "find_difference", "normal", 90, face_detected=0
        )
        self.assertEqual(len(parts), 2)
        self.assertLessEqual(sum(score for _, score, _ in parts), 65.0)


class BandLabelTests(unittest.TestCase):
    def test_band_labels_follow_report_thresholds(self):
        self.assertEqual(score_band_label(95), "卓越表现")
        self.assertEqual(score_band_label(72), "表现优秀")
        self.assertEqual(score_band_label(58), "表现良好")
        self.assertEqual(score_band_label(42), "表现一般")
        self.assertEqual(score_band_label(20), "需要更多练习")


if __name__ == "__main__":
    unittest.main()
