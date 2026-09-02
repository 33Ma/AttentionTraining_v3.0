# games/spot_difference_game.py
import random
from typing import List, Tuple
from PySide6.QtCore import QTimer, QRectF, QPointF, Qt, QElapsedTimer
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Signal

from .game_interface import GameInterface
from .scoring import (
    combo_bonus_percent,
    penalty_percent,
    points_for_hit,
    RECOVERY_COMBO,
    MAX_PENALTY_MISSES,
)
from core.settings import GlobalSettings, DifficultyLevel


# ---- 找茬难度预设：点生存期与刷新节奏 ----
# 简单/普通走路线 B（1.5s 一波、每波 2 点）；困难为 1.5s 单点 + 1000ms 生存期。
EASY_SPOT_LIFETIME_MS = 1200      # 简单：点存活时长，超时未点则直接消失（不扣分）
NORMAL_SPOT_LIFETIME_MS = 850     # 普通：点存活时长，超时未点则直接消失（不扣分）
HARD_SPOT_LIFETIME_MS = 1150       # 困难：点存活时长，超时未点则直接消失（不扣分）
NORMAL_WAVE_INTERVAL_MS = 1500    # 波次节奏/单点刷新间隔（简单/普通/困难共用）
NORMAL_WAVE_SIZE = 2              # 每波点数（仅简单/普通使用）
EASY_WAVE_STAGGER_MS = 750        # 简单：波内两个点的错峰间隔
NORMAL_WAVE_STAGGER_MS = 650      # 普通：波内两个点的错峰间隔
NORMAL_PUMP_MS = 50               # 出点/过期清理的轮询间隔
MAX_UNFOUND_SPOTS = 8             # 场上未点上限（沿用原逻辑）

class SpotDifferenceGame(GameInterface):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)

        self._differences: List[QRectF] = []
        self._found: List[bool] = []
        self._found_count = 0
        self._score = 0.0
        self._consecutive_hits = 0
        self._misses = 0
        self._attention_score = 50
        self._running = False
        self._feedback_message = ""
        self._feedback_color = QColor(0, 255, 0)

        settings = GlobalSettings()
        self._difficulty_level = settings.effective_difficulty_level()
        self._spot_size = settings.get_spot_size()
        self._base_interval = settings.get_spot_interval()
        self._position_randomness = settings.get_spot_position_randomness()

        # 预设档均启用“点过期消失”：简单/普通每 1.5s 一波错峰出 2 点，困难每 1.5s 单点
        self._expiry_enabled = self._difficulty_level in (
            DifficultyLevel.EASY,
            DifficultyLevel.NORMAL,
            DifficultyLevel.HARD,
        )
        self._wave_mode = self._difficulty_level in (
            DifficultyLevel.EASY,
            DifficultyLevel.NORMAL,
        )
        self._lifetime_ms = {
            DifficultyLevel.EASY: EASY_SPOT_LIFETIME_MS,
            DifficultyLevel.NORMAL: NORMAL_SPOT_LIFETIME_MS,
            DifficultyLevel.HARD: HARD_SPOT_LIFETIME_MS,
        }.get(self._difficulty_level, 0)
        self._wave_size = NORMAL_WAVE_SIZE if self._wave_mode else 1
        self._wave_stagger_ms = {
            DifficultyLevel.EASY: EASY_WAVE_STAGGER_MS,
            DifficultyLevel.NORMAL: NORMAL_WAVE_STAGGER_MS,
        }.get(self._difficulty_level, 0)
        self._wave_interval_ms = NORMAL_WAVE_INTERVAL_MS
        self._spawn_times = []       # 与 _differences/_found 对齐的出生时刻(ms)
        self._elapsed = QElapsedTimer()
        self._next_wave_ms = 0
        self._next_spawn_ms = 0
        self._wave_points_done = 0

        self._spawn_timer = QTimer(self)
        self._spawn_timer.timeout.connect(self._add_new_difference)

        self._pump_timer = QTimer(self)
        self._pump_timer.setInterval(NORMAL_PUMP_MS)
        self._pump_timer.timeout.connect(self._pump)

        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._hide_feedback)

        settings.settings_changed.connect(self.update)

    def start_game(self):
        self._running = True
        self._found_count = 0
        self._score = 0.0
        self._consecutive_hits = 0
        self._misses = 0
        self._feedback_message = ""
        self._differences.clear()
        self._found.clear()
        self._spawn_times.clear()
        if self._expiry_enabled:
            # 从 0ms 开始出点：简单/普通按波次错峰，困难按 1.5s 单点节奏
            self._elapsed.start()
            self._next_wave_ms = 0
            self._next_spawn_ms = 0
            self._wave_points_done = 0
            self._pump_timer.start()
        else:
            self._generate_differences()
            self._spawn_timer.start(self._get_next_interval())
        self.update()

    def stop_game(self):
        self._running = False
        self._spawn_timer.stop()
        self._pump_timer.stop()
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
        score_text = (f"已找到: {self._found_count} | 剩余: {unfound} | "
                      f"得分: {int(round(self._score))} | 连击: {self._consecutive_hits}")
        bonus = combo_bonus_percent(self._consecutive_hits)
        if bonus:
            score_text += f" (+{bonus}%)"
        penalty = penalty_percent(self._misses)
        if penalty:
            score_text += f" (-{penalty}%)"
        painter.drawText(15, self.height() - 15, score_text)

        # 反馈信息
        if self._feedback_message:
            feedback_font = QFont("Arial", 24, QFont.Bold)
            painter.setFont(feedback_font)
            painter.setPen(self._feedback_color)
            painter.drawText(self.width() // 2 - 80, self.height() // 2, self._feedback_message)

    def mousePressEvent(self, event):
        if not self._running:
            return

        if self._expiry_enabled:
            self._purge_expired()

        pos = event.position()
        hit = False

        for i, diff in enumerate(self._differences):
            if i < len(self._found) and not self._found[i] and diff.contains(pos):
                self._found[i] = True
                self._found_count += 1
                hit = True
                self._consecutive_hits += 1
                if self._consecutive_hits >= RECOVERY_COMBO:
                    self._misses = 0
                self._score += points_for_hit(self._consecutive_hits, self._misses)
                self.consecutive_hits_changed.emit(self._consecutive_hits)

                if self._consecutive_hits % 25 == 0:
                    self._show_feedback("PERFECT!", QColor(255, 215, 0))
                elif self._consecutive_hits % 15 == 0:
                    self._show_feedback("EXCELLENT!", QColor(255, 0, 0))
                elif self._consecutive_hits % 5 == 0:
                    self._show_feedback("GOOD!", QColor(0, 255, 0))

                self.game_score_changed.emit(int(round(self._score)))
                self.update()
                break

        if not hit:
            self._register_miss()

    def _register_miss(self):
        """点空白误点逻辑：断连击并累加未命中惩罚（点过期消失不扣分）。"""
        if self._consecutive_hits > 0:
            self._consecutive_hits = 0
            self.consecutive_hits_changed.emit(0)
        self._misses = min(self._misses + 1, MAX_PENALTY_MISSES)
        self.update()

    def _purge_expired(self):
        """移除超过生存期仍未点中的差异点：直接消失，不扣分、不断连击。"""
        if not self._expiry_enabled or not self._spawn_times:
            return
        now = self._elapsed.elapsed()
        alive_diffs = []
        alive_found = []
        alive_times = []
        expired = 0
        for i, diff in enumerate(self._differences):
            found = self._found[i]
            if found or now < self._spawn_times[i] + self._lifetime_ms:
                alive_diffs.append(diff)
                alive_found.append(found)
                alive_times.append(self._spawn_times[i])
            else:
                expired += 1
        if expired:
            self._differences = alive_diffs
            self._found = alive_found
            self._spawn_times = alive_times
            self.update()

    def _pump(self):
        """出点/过期轮询：简单/普通按波次错峰出 2 点，困难按 1.5s 单点节奏。"""
        if not self._running:
            return
        self._purge_expired()
        now = self._elapsed.elapsed()
        if now < self._next_spawn_ms:
            return
        unfound = sum(1 for f in self._found if not f)
        if unfound < MAX_UNFOUND_SPOTS:
            x, y = self._random_position()
            self._differences.append(QRectF(x, y, self._spot_size, self._spot_size))
            self._found.append(False)
            self._spawn_times.append(now)
            self.update()
        if self._wave_mode:
            self._wave_points_done += 1
            if self._wave_points_done < self._wave_size:
                self._next_spawn_ms = (
                    self._next_wave_ms + self._wave_points_done * self._wave_stagger_ms
                )
            else:
                self._next_wave_ms += self._wave_interval_ms
                self._wave_points_done = 0
                self._next_spawn_ms = self._next_wave_ms
        else:
            # 困难：单点节奏，每 1.5s 一个点
            self._next_spawn_ms = now + self._wave_interval_ms

    def _get_next_interval(self) -> int:
        return self._base_interval

    def _random_position(self) -> Tuple[float, float]:
        """按当前难度的位置随机性生成点出现位置：值越小越靠近区域中心。"""
        w = self.width() // 2 - 10
        h = self.height() - 20
        right_start_x = w + 20

        range_x = max(1, w - self._spot_size - 20)
        range_y = max(1, h - self._spot_size - 20)
        center_x = right_start_x + 10 + range_x / 2.0
        center_y = 20 + range_y / 2.0
        half_x = range_x / 2.0 * self._position_randomness
        half_y = range_y / 2.0 * self._position_randomness

        x = random.uniform(center_x - half_x, center_x + half_x)
        y = random.uniform(center_y - half_y, center_y + half_y)
        return x, y

    def _add_new_difference(self):
        if not self._running:
            return

        unfound_count = sum(1 for f in self._found if not f)
        if unfound_count >= 8:
            return

        x, y = self._random_position()

        self._differences.append(QRectF(x, y, self._spot_size, self._spot_size))
        self._found.append(False)

        self.update()

    def _generate_differences(self):
        self._differences.clear()
        self._found.clear()

        for _ in range(3):
            x, y = self._random_position()
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