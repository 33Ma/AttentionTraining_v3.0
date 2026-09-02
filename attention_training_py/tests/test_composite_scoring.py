# -*- coding: utf-8 -*-
"""综合评分（连续加权版）单元测试。

设计目标对应的行为约束：
- 连续化：输入小幅变化不再产生 7-10 分的悬崖跳变；
- 正交化：注意力已内含注视成分，综合分不再单独叠加注视项；
- 归一化：游戏得分按“模式 × 难度”参考基准归一；
- 缺失处理：未启用摄像头/未检测到人脸时剔除注意力项并按已测组件重新归一；
- 历史兼容：旧记录没有 face_detected 字段时按注意力/注视数据推断。
"""

import importlib.util
import pathlib
import unittest


_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MODULE_PATH = _PROJECT_ROOT / "ai" / "composite_scoring.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("composite_scoring", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


composite_scoring = _load_module()
composite_score = composite_scoring.composite_score
score_ratio = composite_scoring.score_ratio
camera_measured = composite_scoring.camera_measured
record_composite_score = composite_scoring.record_composite_score


class CompositeScoreTests(unittest.TestCase):
    def test_attention_boundary_no_longer_jumps_ten_points(self):
        lo = composite_score(69, 0, 100, "find_difference", "normal", 90, face_detected=1)
        hi = composite_score(70, 0, 100, "find_difference", "normal", 90, face_detected=1)
        self.assertLessEqual(abs(hi - lo), 1)

    def test_score_is_monotonic_in_attention(self):
        scores = [
            composite_score(att, 10, 300, "find_difference", "normal", 90, face_detected=1)
            for att in (50, 60, 70, 80, 90)
        ]
        self.assertEqual(scores, sorted(scores))
        self.assertGreater(len(set(scores)), 1)

    def test_full_marks_gives_100(self):
        self.assertEqual(
            composite_score(100, 25, 1000, "find_difference", "normal", 100, face_detected=1),
            100,
        )

    def test_combo_restored_from_record_adds_points(self):
        base = composite_score(80, 0, 300, "find_difference", "normal", 90, face_detected=1)
        with_combo = composite_score(80, 20, 300, "find_difference", "normal", 90, face_detected=1)
        self.assertGreaterEqual(with_combo - base, 20)

    def test_difficulty_normalization_hard_not_penalized_at_equal_skill(self):
        easy = composite_score(80, 10, 450, "find_difference", "easy", 90, face_detected=1)
        hard = composite_score(80, 10, 450, "find_difference", "hard", 90, face_detected=1)
        self.assertGreaterEqual(hard, easy)

    def test_missing_camera_excludes_attention_and_renormalizes(self):
        measured = composite_score(50, 0, 0, "find_difference", "normal", 90, face_detected=1)
        missing = composite_score(50, 0, 0, "find_difference", "normal", 90, face_detected=0)
        self.assertLess(missing, measured)
        # 未启用摄像头但游戏表现出色时，综合分仍可达到满分（缺失项不惩罚）
        self.assertEqual(
            composite_score(50, 25, 1000, "find_difference", "normal", 90, face_detected=0),
            100,
        )

    def test_legacy_record_without_face_flag_infers_from_attention(self):
        self.assertTrue(camera_measured(80, 0, None))
        self.assertFalse(camera_measured(0, 0, None))
        self.assertFalse(camera_measured(50, 100, 0))

    def test_score_ratio_normalized_per_mode_and_difficulty(self):
        self.assertAlmostEqual(score_ratio(500, "find_difference", "easy"), 500 / 950)
        self.assertAlmostEqual(score_ratio(500, "find_difference", "hard"), 500 / 560)
        self.assertAlmostEqual(score_ratio(800, "dynamic_tracking", "normal"), 1.0)
        self.assertAlmostEqual(score_ratio(50, "dynamic_tracking", "normal"), 0.5)

    def test_score_ratio_maps_game_score_to_0_100_scale(self):
        # 训练记录图表使用的 0-100 归一：score_ratio * 100
        self.assertAlmostEqual(score_ratio(900, "find_difference", "normal") * 100, 100.0)
        self.assertAlmostEqual(score_ratio(450, "find_difference", "normal") * 100, 50.0)
        self.assertAlmostEqual(score_ratio(950, "find_difference", "easy") * 100, 100.0)
        self.assertAlmostEqual(score_ratio(560, "find_difference", "hard") * 100, 100.0)
        self.assertAlmostEqual(score_ratio(80, "dynamic_tracking", "normal") * 100, 80.0)
        self.assertAlmostEqual(score_ratio(120, "dynamic_tracking", "normal") * 100, 100.0)

    def test_score_ratio_tolerates_int_difficulty_and_unknown_mode(self):
        self.assertAlmostEqual(score_ratio(300, "unknown_mode", 2), 300 / 560)

    def test_score_ratio_full_marks_scales_with_duration(self):
        # 5 分钟满分基准 = 1 分钟基准 ×5，10 分钟 ×10
        self.assertAlmostEqual(
            score_ratio(900 * 5, "find_difference", "normal", 5), 1.0
        )
        self.assertAlmostEqual(
            score_ratio(900 * 10, "find_difference", "normal", 10), 1.0
        )
        self.assertAlmostEqual(
            score_ratio(900, "find_difference", "normal", 5), 0.2
        )
        self.assertAlmostEqual(
            score_ratio(450 * 10, "find_difference", "normal", 10), 0.5
        )
        # 默认按 1 分钟基准，兼容旧调用
        self.assertAlmostEqual(score_ratio(900, "find_difference", "normal"), 1.0)
        # 动态追踪本身是 0-100 相对分，不受时长影响
        self.assertAlmostEqual(
            score_ratio(50, "dynamic_tracking", "normal", 10), 0.5
        )

    def test_composite_score_scales_game_reference_with_duration(self):
        # 相同水平下，5/10 分钟达到各自满分游戏分时，综合分应与 1 分钟满分一致
        base = composite_score(80, 10, 900, "find_difference", "normal", 90,
                              face_detected=1)
        five = composite_score(80, 10, 900 * 5, "find_difference", "normal", 90,
                              face_detected=1, duration_minutes=5)
        ten = composite_score(80, 10, 900 * 10, "find_difference", "normal", 90,
                             face_detected=1, duration_minutes=10)
        self.assertEqual(five, base)
        self.assertEqual(ten, base)
        # 时长缺失或为 0 时按 1 分钟处理（旧记录兼容）
        zero = composite_score(80, 10, 900, "find_difference", "normal", 90,
                              face_detected=1, duration_minutes=0)
        self.assertEqual(zero, base)

    def test_record_composite_score_uses_record_duration(self):
        def rec(duration: int, game_score: int):
            return {
                "avg_attention_score": 80,
                "max_consecutive_hits": 10,
                "game_score": game_score,
                "game_mode": "find_difference",
                "difficulty": "normal",
                "avg_gaze_score": 90,
                "face_detected": 1,
                "composite_score": -1,
                "duration_minutes": duration,
            }

        base = record_composite_score(rec(1, 900))
        five = record_composite_score(rec(5, 900 * 5))
        ten = record_composite_score(rec(10, 900 * 10))
        self.assertEqual(five, base)
        self.assertEqual(ten, base)

    def test_score_never_exceeds_100(self):
        self.assertEqual(
            composite_score(100, 99, 99999, "dynamic_tracking", "hard", 100, face_detected=1),
            100,
        )

    def test_discrimination_improved_many_distinct_values(self):
        values = {
            composite_score(att, combo, score, mode, diff, 90, face_detected=1)
            for att in range(0, 101, 10)
            for combo in (0, 5, 10, 15, 20)
            for score in (0, 150, 300, 450, 600, 800)
            for mode, diff in (("find_difference", "normal"), ("dynamic_tracking", "hard"))
        }
        self.assertGreaterEqual(len(values), 25)


    def test_dynamic_tracking_uses_45_55_weights(self):
        # 新游戏分为 0-100 相对分；注意力 45% + 游戏表现 55%
        low = composite_score(50, 0, 40, "dynamic_tracking", "normal", 0, face_detected=1)
        high = composite_score(50, 0, 80, "dynamic_tracking", "normal", 0, face_detected=1)
        self.assertEqual(low, int(round(45 * 0.5 + 55 * 0.4)))
        self.assertEqual(high, int(round(45 * 0.5 + 55 * 0.8)))
        # 无摄像头数据时按游戏表现单独归一
        self.assertEqual(
            composite_score(50, 0, 80, "dynamic_tracking", "normal", 0, face_detected=0),
            80,
        )


class ComboTierTests(unittest.TestCase):
    """连击档位：最高档 25 次以上，档位数量多于旧版 4 档。"""

    def _combo_part(self, hits: int) -> int:
        _, parts = composite_scoring.composite_details(
            0, hits, 0, "find_difference", "normal", 0, face_detected=0
        )
        return int(round(next(p for n, p, _ in parts if n == "最高连击")))

    def test_combo_full_marks_reached_at_25(self):
        self.assertEqual(self._combo_part(24), 25)
        self.assertEqual(self._combo_part(25), 30)
        self.assertEqual(self._combo_part(40), 30)

    def test_combo_zero_scores_zero(self):
        self.assertEqual(self._combo_part(0), 0)
        self.assertEqual(self._combo_part(2), 0)

    def test_combo_has_more_tiers_than_old_four(self):
        values = {self._combo_part(h) for h in range(0, 31)}
        self.assertEqual(values, {0, 5, 9, 13, 17, 21, 25, 30})

    def test_combo_part_monotonic(self):
        prev = -1
        for hits in range(0, 31):
            value = self._combo_part(hits)
            self.assertGreaterEqual(value, prev)
            prev = value

    def test_full_marks_constant_is_25(self):
        self.assertEqual(composite_scoring.COMBO_FULL_MARKS, 25)


if __name__ == "__main__":
    unittest.main()
