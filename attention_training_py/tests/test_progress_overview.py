# -*- coding: utf-8 -*-
"""进步概览考核参数测试：应基于综合分数而非注意力分数。"""

import unittest

from core.settings import TrainingRecord, DifficultyLevel
from PySide6.QtCharts import QLineSeries
from ui.training_record_dialog import TrainingRecordDialog


def _record(composite: int, attention: int) -> TrainingRecord:
    record = TrainingRecord()
    record.composite_score = composite
    record.avg_attention_score = attention
    return record


class ProgressOverviewTests(unittest.TestCase):
    def _dialog(self) -> TrainingRecordDialog:
        # 只调用纯计算方法，不初始化 Qt 控件
        return TrainingRecordDialog.__new__(TrainingRecordDialog)

    def test_improvement_uses_composite_not_attention(self):
        # 早期注意力高但综合分低；近期注意力低但综合分高
        records = [
            _record(composite=70, attention=40),  # 最近
            _record(composite=65, attention=45),
            _record(composite=30, attention=90),  # 最早
            _record(composite=35, attention=88),
        ]
        improvement = self._dialog()._calculate_improvement(records)
        self.assertGreater(improvement, 80)  # 按综合分：(67.5-32.5)/32.5 ≈ +107%

    def test_trend_text_mentions_composite_score(self):
        records = [
            _record(composite=70, attention=40),
            _record(composite=30, attention=90),
        ]
        text = self._dialog()._get_trend_text(records)
        self.assertIn("综合分数", text)
        self.assertNotIn("注意力", text)



    def test_score_and_composite_charts_split_by_mode(self):
        """图表按游戏模式拆分：找茬与动态追踪各占一条曲线。"""
        dlg = TrainingRecordDialog.__new__(TrainingRecordDialog)
        dlg._attention_series = QLineSeries()
        dlg._composite_series = QLineSeries()
        dlg._composite_tracking_series = QLineSeries()
        dlg._score_series = QLineSeries()
        dlg._score_tracking_series = QLineSeries()
        dlg._blink_series = QLineSeries()
        dlg._gaze_score_series = QLineSeries()
        dlg._gaze_distance_series = QLineSeries()
        dlg._improvement_label = type(
            "Stub", (), {
                "setText": lambda self, t: None,
                "setStyleSheet": lambda self, s: None,
            }
        )()
        dlg._trend_label = type(
            "Stub", (), {"setText": lambda self, t: None}
        )()
        dlg._heatmap_widget = None
        dlg._setup_chart_axes = lambda point_count: None

        def record(mode: str, score: int, difficulty: str, composite: int):
            r = TrainingRecord()
            r.game_mode = mode
            r.game_score = score
            r.difficulty = DifficultyLevel(difficulty)
            r.composite_score = composite
            r.avg_attention_score = 80
            r.total_blinks = 10
            r.avg_gaze_score = 80
            r.avg_gaze_distance = 0.1
            return r

        records = [
            record("find_difference", 450, "normal", 70),    # 最近
            record("dynamic_tracking", 80, "hard", 65),      # 最早
        ]
        dlg._update_charts(records)

        # 找茬游戏得分按比例规则归一：450/900*100 = 50；动态追踪直接 80
        self.assertEqual([p.y() for p in dlg._score_series.points()], [50.0])
        self.assertEqual([p.y() for p in dlg._score_tracking_series.points()], [80.0])
        # 综合评分按模式拆分
        self.assertEqual([p.y() for p in dlg._composite_series.points()], [70.0])
        self.assertEqual([p.y() for p in dlg._composite_tracking_series.points()], [65.0])



    def test_heatmap_game_score_row_normalized_to_0_100(self):
        """热力图游戏得分行按训练期间比例规则归一为 0-100。"""
        class HeatmapStub:
            def __init__(self):
                self.rows = None
                self.labels = None

            def set_data(self, rows, labels):
                self.rows = rows
                self.labels = labels

        dlg = TrainingRecordDialog.__new__(TrainingRecordDialog)
        heatmap = HeatmapStub()
        dlg._heatmap_widget = heatmap

        def record(mode: str, score: int, difficulty: str, composite: int):
            r = TrainingRecord()
            r.game_mode = mode
            r.game_score = score
            r.difficulty = DifficultyLevel(difficulty)
            r.composite_score = composite
            return r

        chart_records = [
            record("find_difference", 450, "normal", 70),   # 450/900*100 = 50
            record("dynamic_tracking", 80, "hard", 65),     # 80/100*100 = 80
        ]
        dlg._update_heatmap(chart_records)

        rows = {name: values for name, values, _ in heatmap.rows}
        self.assertEqual(rows["游戏得分（0-100）"], [50.0, 80.0])


if __name__ == "__main__":
    unittest.main()
