# games/spot_difference_game.py
import random
from typing import List, Tuple
from PySide6.QtCore import QTimer, QRectF, QPointF, Qt
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Signal

from .game_interface import GameInterface
from core.settings import GlobalSettings

class SpotDifferenceGame(GameInterface):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)

        self._differences: List[QRectF] = []
        self._found: List[bool] = []
        self._found_count = 0
        self._consecutive_hits = 0
        self._attention_score = 50
        self._running = False
        self._feedback_message = ""
        self._feedback_color = QColor(0, 255, 0)

        settings = GlobalSettings()
        self._spot_size = settings.get_spot_size()
        self._base_interval = settings.get_spot_interval()

        self._spawn_timer = QTimer(self)
        self._spawn_timer.timeout.connect(self._add_new_difference)

        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._hide_feedback)

        settings.settings_changed.connect(self.update)

    def start_game(self):
        self._running = True
        self._found_count = 0
        self._consecutive_hits = 0
        self._feedback_message = ""
        self._differences.clear()
        self._found.clear()
        self._generate_differences()
        self._spawn_timer.start(self._get_next_interval())
        self.update()

    def stop_game(self):
        self._running = False
        self._spawn_timer.stop()
        self._feedback_timer.stop()

    def update_with_attention(self, attention_score: int):
        self._attention_score = attention_score
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        settings = GlobalSettings()
        bg_color = settings.background_color()
        text_color = settings.text_color()

        painter.fillRect(self.rect(), bg_color)

        # 绘制左右两个区域
        w = self.width() // 2 - 10
        h = self.height() - 20
        left_rect = QRectF(10, 10, w, h)
        right_rect = QRectF(w + 20, 10, w, h)

        painter.setPen(QPen(text_color, 2))
        painter.setBrush(bg_color.lighter(120))
        painter.drawRect(left_rect)
        painter.setBrush(QColor(100, 200, 100, 50))
        painter.drawRect(right_rect)

        # 绘制差异点
        for i, diff in enumerate(self._differences):
            if i < len(self._found) and self._found[i]:
                continue
            painter.setPen(Qt.NoPen)
            if self._attention_score < 40:
                painter.setBrush(QColor(255, 255, 0, 100))
            else:
                painter.setBrush(QColor(255, 100, 100, 80))
            painter.drawEllipse(diff)

        # 显示信息
        font = QFont("Arial", 16, QFont.Bold)
        painter.setFont(font)
        painter.setPen(text_color)

        unfound = sum(1 for f in self._found if not f)
        painter.drawText(15, self.height() - 15,
                        f"已找到: {self._found_count} | 剩余: {unfound} | 连击: {self._consecutive_hits}")

        # 反馈信息
        if self._feedback_message:
            feedback_font = QFont("Arial", 24, QFont.Bold)
            painter.setFont(feedback_font)
            painter.setPen(self._feedback_color)
            painter.drawText(self.width() // 2 - 80, self.height() // 2, self._feedback_message)

    def mousePressEvent(self, event):
        if not self._running:
            return

        pos = event.position()
        hit = False

        for i, diff in enumerate(self._differences):
            if i < len(self._found) and not self._found[i] and diff.contains(pos):
                self._found[i] = True
                self._found_count += 1
                hit = True
                self._consecutive_hits += 1
                self.consecutive_hits_changed.emit(self._consecutive_hits)

                if self._consecutive_hits % 25 == 0:
                    self._show_feedback("PERFECT!", QColor(255, 215, 0))
                elif self._consecutive_hits % 15 == 0:
                    self._show_feedback("EXCELLENT!", QColor(255, 0, 0))
                elif self._consecutive_hits % 5 == 0:
                    self._show_feedback("GOOD!", QColor(0, 255, 0))

                self.game_score_changed.emit(self._found_count * 10)
                self.update()
                break

        if not hit and self._consecutive_hits > 0:
            self._consecutive_hits = 0
            self.consecutive_hits_changed.emit(0)
            self.update()

    def _get_next_interval(self) -> int:
        return self._base_interval

    def _add_new_difference(self):
        if not self._running:
            return

        unfound_count = sum(1 for f in self._found if not f)
        if unfound_count >= 8:
            return

        w = self.width() // 2 - 10
        h = self.height() - 20
        right_start_x = w + 20

        x = right_start_x + 10 + random.randint(0, max(1, w - self._spot_size - 20))
        y = 20 + random.randint(0, max(1, h - self._spot_size - 20))

        self._differences.append(QRectF(x, y, self._spot_size, self._spot_size))
        self._found.append(False)

        self.update()

    def _generate_differences(self):
        self._differences.clear()
        self._found.clear()

        w = self.width() // 2 - 10
        h = self.height() - 20
        right_start_x = w + 20

        for _ in range(3):
            x = right_start_x + 10 + random.randint(0, max(1, w - self._spot_size - 20))
            y = 20 + random.randint(0, max(1, h - self._spot_size - 20))
            self._differences.append(QRectF(x, y, self._spot_size, self._spot_size))
            self._found.append(False)

    def _show_feedback(self, message: str, color: QColor):
        self._feedback_message = message
        self._feedback_color = color
        self.feedback_triggered.emit(message)
        self._feedback_timer.start(800)
        self.update()

    def _hide_feedback(self):
        self._feedback_message = ""
        self.update()