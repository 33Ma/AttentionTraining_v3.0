# -*- coding: utf-8 -*-
"""动态追踪模式刷点与指标计数的回归测试。"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QElapsedTimer, QPointF, QEvent, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from games.tracking_game import TrackingGame


def _pump(ms: int):
    """运行事件循环 ms 毫秒。"""
    timer = QElapsedTimer()
    timer.start()
    app = QApplication.instance()
    while timer.elapsed() < ms:
        app.processEvents()


class TrackingGameSpawningTests(unittest.TestCase):
    """回归：注意力以 10Hz 推送时，刷点定时器不能被饿死。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.game = TrackingGame()
        self.game.resize(800, 600)

    def tearDown(self):
        self.game.stop_game()

    def test_points_keep_spawning_under_frequent_attention_updates(self):
        game = self.game
        game.start_game()
        start_total = game._total_points

        attention_timer = QTimer(game)
        attention_timer.timeout.connect(lambda: game.update_with_attention(50))
        attention_timer.start(100)  # 模拟摄像头 ~10Hz 注意力推送
        try:
            _pump(1700)
        finally:
            attention_timer.stop()

        self.assertGreater(
            game._total_points, start_total,
            "注意力更新不应阻止新目标点生成",
        )

    def test_click_registers_hit_and_metrics(self):
        game = self.game
        game.start_game()
        now = game._elapsed.elapsed()
        game._points = [{"pos": QPointF(600, 200), "spawn_ms": now}]
        game._total_points = 1

        event = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(600, 200),
            QPointF(600, 200),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.app.sendEvent(game, event)

        self.assertEqual(game._hits, 1)
        self.assertEqual(len(game._response_times), 1)
        self.assertGreater(game._theoretical_path, 0.0)
        self.assertGreater(game.hit_rate(), 0.0)



    def test_hover_over_point_counts_as_hit(self):
        game = self.game
        game.start_game()
        now = game._elapsed.elapsed()
        game._points = [{"pos": QPointF(600, 200), "spawn_ms": now}]
        game._total_points = 1

        move = QMouseEvent(
            QEvent.MouseMove,
            QPointF(600, 200),
            QPointF(600, 200),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.app.sendEvent(game, move)

        self.assertEqual(game._hits, 1)
        self.assertEqual(game._points, [])
        self.assertGreater(game.hit_rate(), 0.0)


if __name__ == "__main__":
    unittest.main()
