# -*- coding: utf-8 -*-
"""个性化推荐：最近记录切片与推荐结果合法性测试（无需 Qt）。"""

import unittest

from ai.local_analysis import LocalAnalysisEngine


def _record(attention=60, mode="find_difference", score=200):
    return {
        "game_mode": mode,
        "avg_attention_score": attention,
        "game_score": score,
    }


class RecommendFeaturesTests(unittest.TestCase):
    def test_uses_most_recent_records(self):
        # history 约定为“新→旧”，应取前 10 条；旧记录（注意力 10 分）不得进入特征
        history = [_record(attention=90) for _ in range(10)]
        history += [_record(attention=10), _record(attention=10)]
        engine = LocalAnalysisEngine()
        features = engine._recommend_features(history)
        self.assertIsNotNone(features)
        self.assertAlmostEqual(features[0], 0.9, places=6)

    def test_empty_history_returns_none(self):
        engine = LocalAnalysisEngine()
        self.assertIsNone(engine._recommend_features([]))

    def test_recommend_mode_returns_valid_combination(self):
        history = [_record(attention=70, score=300) for _ in range(5)]
        mode, difficulty = LocalAnalysisEngine.instance().recommend_mode(history)
        self.assertIn(mode, ("find_difference", "dynamic_tracking"))
        self.assertIn(difficulty, ("Easy", "Normal", "Hard"))

    def test_empty_history_recommend_rule_fallback(self):
        mode, difficulty = LocalAnalysisEngine.instance().recommend_mode([])
        self.assertEqual((mode, difficulty), ("find_difference", "Normal"))


if __name__ == "__main__":
    unittest.main()
