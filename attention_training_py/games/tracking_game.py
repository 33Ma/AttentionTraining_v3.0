# games/tracking_game.py
import random
import math
from PySide6.QtCore import QTimer, QPointF, Qt, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget

from .game_interface import GameInterface
from core.settings import GlobalSettings

class TrackingGame(GameInterface):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(400, 300)

        self._target_pos = QPointF()
        self._cursor_pos = QPointF()
        self._score = 0
        self._consecutive_hits = 0
        self._attention_score = 50
        self._running = False
        self._feedback_message = ""
        self._feedback_color = QColor(0, 255, 0)
        self._last_hit_recorded = False

        settings = GlobalSettings()
        self._target_radius = settings.get_track_size()
        self._base_interval = settings.get_track_interval()

        self._move_timer = QTimer(self)
        self._move_timer.timeout.connect(self._update_target)

        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._hide_feedback)

        settings.settings_changed.connect(self.update)

    def start_game(self):
        self._running = True
        self._score = 0
        self._consecutive_hits = 0
        self._last_hit_recorded = False
        self._feedback_message = ""
        self._target_pos = QPointF(self.width() / 2, self.height() / 2)
        self._cursor_pos = self._target_pos
        self._move_timer.start(self._base_interval)
        self.consecutive_hits_changed.emit(0)
        self.update()

    def stop_game(self):
        self._running = False
        self._move_timer.stop()
        self._feedback_timer.stop()

    def update_with_attention(self, attention_score: int):
        self._attention_score = attention_score
        if self._running and self._move_timer:
            # 根据注意力调整速度
            adjusted = self._base_interval - int((100 - attention_score) / 100.0 * self._base_interval * 0.5)
            self._move_timer.setInterval(max(300, min(5000, adjusted)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        settings = GlobalSettings()
        bg_color = settings.background_color()
        text_color = settings.text_color()

        painter.fillRect(self.rect(), bg_color)

        # 绘制目标
        painter.setBrush(QColor(255, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(self._target_pos, self._target_radius, self._target_radius)

        # 绘制光标
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(text_color, 3))
        painter.drawLine(self._cursor_pos + QPointF(-15, 0), self._cursor_pos + QPointF(15, 0))
        painter.drawLine(self._cursor_pos + QPointF(0, -15), self._cursor_pos + QPointF(0, 15))
        painter.drawEllipse(self._cursor_pos, 20, 20)

        # 显示信息
        font = QFont("Arial", 16, QFont.Bold)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(15, 40, f"追踪得分: {self._score} | 连击: {self._consecutive_hits}")

        if self._attention_score < 40:
            painter.setPen(QColor(255, 100, 100))
            painter.drawText(15, 75, f"注意力不足！分数: {self._attention_score}")

        # 反馈信息
        if self._feedback_message:
            feedback_font = QFont("Arial", 24, QFont.Bold)
            painter.setFont(feedback_font)
            painter.setPen(self._feedback_color)
            painter.drawText(self.width() // 2 - 80, self.height() // 2, self._feedback_message)

    def mouseMoveEvent(self, event):
        if not self._running:
            return

        self._cursor_pos = event.position()
        dx = self._cursor_pos.x() - self._target_pos.x()
        dy = self._cursor_pos.y() - self._target_pos.y()
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < self._target_radius + 10:
            if not self._last_hit_recorded:
                self._last_hit_recorded = True
                self._score += 10
                self._consecutive_hits += 1
                self.consecutive_hits_changed.emit(self._consecutive_hits)

                if self._consecutive_hits % 25 == 0:
                    self._show_feedback("PERFECT!", QColor(255, 215, 0))
                elif self._consecutive_hits % 15 == 0:
                    self._show_feedback("EXCELLENT!", QColor(255, 0, 0))
                elif self._consecutive_hits % 5 == 0:
                    self._show_feedback("GOOD!", QColor(0, 255, 0))

                self.game_score_changed.emit(self._score)
                self._update_target()
        else:
            self._last_hit_recorded = False

        self.update()

    def mousePressEvent(self, event):
        if not self._running:
            return

        dx = self._cursor_pos.x() - self._target_pos.x()
        dy = self._cursor_pos.y() - self._target_pos.y()
        dist = math.sqrt(dx * dx + dy * dy)

        if dist >= self._target_radius + 10 and self._consecutive_hits > 0:
            self._consecutive_hits = 0
            self._last_hit_recorded = False
            self.consecutive_hits_changed.emit(0)
            self.update()

    def _update_target(self):
        if not self._running:
            return

        margin = self._target_radius + 30
        x = random.randint(margin, max(margin + 1, self.width() - margin))
        y = random.randint(margin, max(margin + 1, self.height() - margin))
        self._target_pos = QPointF(x, y)
        self._last_hit_recorded = False
        self.update()

    def _show_feedback(self, message: str, color: QColor):
        self._feedback_message = message
        self._feedback_color = color
        self.feedback_triggered.emit(message)
        self._feedback_timer.start(800)
        self.update()

    def _hide_feedback(self):
        self._feedback_message = ""
        self.update()