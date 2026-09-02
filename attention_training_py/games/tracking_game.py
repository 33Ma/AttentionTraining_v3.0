# games/tracking_game.py
"""动态追踪模式（多点命中版）。

计分不再使用“单次命中固定加分”的原始得分，而是统计三个相对指标
（每项满分 100 分），加权得到新的游戏分数（0-100）：
  - 命中率：命中点数 / (出现点数 + 空点点击数)
  - 平均响应时间：目标出现到命中的平均耗时（秒）
  - 追踪路径效率：理论最短路径总长 / 鼠标实际移动路径总长
权重：命中率 40%、响应时间 25%、路径效率 35%（模块常量，可调）。

玩法：每帧同时出现 POINTS_PER_FRAME 个目标点，每个点在
POINT_LIFETIME_MS 毫秒后消失；鼠标光标扫过目标点即计一次命中
（点击同样有效），点击空白处计一次空点点击（计入分母，防止无脑扫射刷命中率）。
"""
import random
import math
from PySide6.QtCore import QTimer, QPointF, Qt, QElapsedTimer
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget

from .game_interface import GameInterface
from core.settings import GlobalSettings


# ---- 计分与玩法常量（可按需要调参） ----
POINTS_PER_FRAME = 3          # 单帧同时出现的目标点数
POINT_LIFETIME_MS = 800       # 目标点存活时长
FRAME_PUMP_MS = 100           # 刷点轮询泵间隔（固定值，实际刷帧节奏由 _frame_interval 控制）
CLICK_SLACK_PX = 6            # 点击判定在目标半径外的额外容差
HIT_RATE_WEIGHT = 0.40        # 命中率权重
RESPONSE_TIME_WEIGHT = 0.25   # 平均响应时间权重
PATH_EFFICIENCY_WEIGHT = 0.35 # 路径效率权重
RT_FULL_SCORE_MS = 400        # 平均响应 <= 该值记 100 分


class TrackingGame(GameInterface):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(400, 300)

        self._points = []          # list of dict: pos, spawn_ms
        self._cursor_pos = QPointF()
        self._score = 0
        self._attention_score = 50
        self._running = False

        settings = GlobalSettings()
        self._target_radius = settings.get_track_size()
        self._base_interval = settings.get_track_interval()
        self._position_randomness = settings.get_track_position_randomness()
        self._frame_interval = self._base_interval  # 当前刷点间隔（注意力自适应只改这里）
        self._next_frame_ms = 0                     # 下一帧刷点的目标时间（相对 _elapsed）

        # 三指标统计
        self._total_points = 0
        self._hits = 0
        self._empty_clicks = 0
        self._response_times = []      # 秒
        self._theoretical_path = 0.0   # 各次命中的理论最短路径之和
        self._actual_path = 0.0        # 鼠标实际移动路径
        self._path_anchor = QPointF()  # 路径计量起点（上一次命中位置/开局光标位）
        self._last_cursor_pos = QPointF()

        self._elapsed = QElapsedTimer()
        self._spawn_timer = QTimer(self)
        self._spawn_timer.timeout.connect(self._spawn_frame)

        settings.settings_changed.connect(self.update)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start_game(self):
        self._running = True
        self._score = 0
        self._total_points = 0
        self._hits = 0
        self._empty_clicks = 0
        self._response_times = []
        self._theoretical_path = 0.0
        self._actual_path = 0.0
        self._points = []
        self._cursor_pos = QPointF(self.width() / 2, self.height() / 2)
        self._last_cursor_pos = self._cursor_pos
        self._path_anchor = self._cursor_pos
        self._elapsed.start()
        self._frame_interval = min(
            self._base_interval, POINT_LIFETIME_MS * POINTS_PER_FRAME
        )
        self._next_frame_ms = 0
        self._spawn_frame()
        # 固定频率轮询泵：不能在 update_with_attention 里改它的间隔，
        # 否则频繁 setInterval 会反复重启活动定时器，导致刷点永远不触发。
        self._spawn_timer.start(FRAME_PUMP_MS)
        self.game_score_changed.emit(0)
        self.update()

    def stop_game(self):
        self._running = False
        self._spawn_timer.stop()

    def update_with_attention(self, attention_score: int):
        self._attention_score = attention_score
        if self._running:
            # 与旧版一致的注意力自适应：注意力越低，刷点间隔越短；
            # 帧间隔不超过“寿命 × 点数”，保证任意时刻屏幕上都有点。
            adjusted = self._base_interval - int(
                (100 - attention_score) / 100.0 * self._base_interval * 0.5
            )
            adjusted = min(adjusted, POINT_LIFETIME_MS * POINTS_PER_FRAME)
            self._frame_interval = max(300, adjusted)

    # ------------------------------------------------------------------
    # 指标接口（供训练窗口写入记录）
    # ------------------------------------------------------------------
    def hit_rate(self) -> float:
        denominator = self._total_points + self._empty_clicks
        return self._hits / denominator if denominator > 0 else 0.0

    def avg_response_time(self) -> float:
        """返回平均响应时间（秒）；无命中时为 0。"""
        if not self._response_times:
            return 0.0
        return sum(self._response_times) / len(self._response_times)

    def path_efficiency(self) -> float:
        """理论最短路径 / 实际路径，截断到 [0,1]；无命中时为 0。"""
        if self._actual_path <= 0 or self._theoretical_path <= 0:
            return 0.0
        return max(0.0, min(1.0, self._theoretical_path / self._actual_path))

    # ------------------------------------------------------------------
    # 玩法逻辑
    # ------------------------------------------------------------------
    def _random_position(self):
        margin = self._target_radius + 30
        range_x = max(1, self.width() - 2 * margin)
        range_y = max(1, self.height() - 2 * margin)
        center_x = margin + range_x / 2.0
        center_y = margin + range_y / 2.0
        half_x = range_x / 2.0 * self._position_randomness
        half_y = range_y / 2.0 * self._position_randomness
        return QPointF(
            random.uniform(center_x - half_x, center_x + half_x),
            random.uniform(center_y - half_y, center_y + half_y),
        )

    def _spawn_frame(self):
        if not self._running:
            return
        self._purge_expired()
        now = self._elapsed.elapsed()
        if now >= self._next_frame_ms:
            # 按当前生效间隔调度下一帧，并把各点出现时间错开，
            # 使前后帧的点在时间上重叠，保证任意时刻屏幕上至少有一个点。
            self._next_frame_ms = now + self._frame_interval
            step = self._frame_interval / POINTS_PER_FRAME
            for i in range(POINTS_PER_FRAME):
                self._points.append(
                    {"pos": self._random_position(), "spawn_ms": now + int(i * step)}
                )
                self._total_points += 1
        self.update()

    def _purge_expired(self):
        if not self._points:
            return
        now = self._elapsed.elapsed()
        self._points = [
            pt for pt in self._points
            if now < pt["spawn_ms"] + POINT_LIFETIME_MS
        ]

    def _compute_game_score(self) -> int:
        hit_rate = self.hit_rate()
        hit_rate_score = 100.0 * hit_rate

        lifetime_s = POINT_LIFETIME_MS / 1000.0
        rt_full_s = RT_FULL_SCORE_MS / 1000.0
        avg_rt = self.avg_response_time()
        if avg_rt > 0:
            rt_score = 100.0 * max(
                0.0, min(1.0, (lifetime_s - avg_rt) / max(lifetime_s - rt_full_s, 1e-6))
            )
        else:
            rt_score = 0.0

        eff_score = 100.0 * self.path_efficiency()
        total = (
            HIT_RATE_WEIGHT * hit_rate_score
            + RESPONSE_TIME_WEIGHT * rt_score
            + PATH_EFFICIENCY_WEIGHT * eff_score
        )
        return int(round(total))

    def _on_hit(self, point):
        now = self._elapsed.elapsed()
        self._hits += 1
        self._response_times.append((now - point["spawn_ms"]) / 1000.0)

        target = point["pos"]
        self._theoretical_path += math.hypot(
            target.x() - self._path_anchor.x(),
            target.y() - self._path_anchor.y(),
        )
        self._path_anchor = target
        self._points.remove(point)

        self._score = self._compute_game_score()
        self.game_score_changed.emit(self._score)
        self.update()

    def _on_empty_click(self):
        self._empty_clicks += 1
        self._score = self._compute_game_score()
        self.game_score_changed.emit(self._score)
        self.update()

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def mouseMoveEvent(self, event):
        if not self._running:
            return
        pos = event.position()
        self._actual_path += math.hypot(
            pos.x() - self._last_cursor_pos.x(),
            pos.y() - self._last_cursor_pos.y(),
        )
        self._last_cursor_pos = pos
        self._cursor_pos = pos

        # 光标扫到目标点即命中（无需点击）
        self._purge_expired()
        now = self._elapsed.elapsed()
        hit_radius = self._target_radius + CLICK_SLACK_PX
        for pt in list(self._points):
            if pt["spawn_ms"] > now:
                continue
            d = math.hypot(pos.x() - pt["pos"].x(), pos.y() - pt["pos"].y())
            if d <= hit_radius:
                self._on_hit(pt)

        self.update()

    def mousePressEvent(self, event):
        if not self._running:
            return
        self._purge_expired()
        now = self._elapsed.elapsed()
        pos = event.position()
        hit_radius = self._target_radius + CLICK_SLACK_PX
        best = None
        best_dist = hit_radius
        for pt in self._points:
            if pt["spawn_ms"] > now:
                continue
            d = math.hypot(pos.x() - pt["pos"].x(), pos.y() - pt["pos"].y())
            if d <= best_dist:
                best = pt
                best_dist = d
        if best is not None:
            self._on_hit(best)
        else:
            self._on_empty_click()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        settings = GlobalSettings()
        bg_color = settings.background_color()
        text_color = settings.text_color()

        painter.fillRect(self.rect(), bg_color)

        # 目标点（未到出现时间的点先不绘制）
        self._purge_expired()
        paint_now = self._elapsed.elapsed()
        for pt in self._points:
            if pt["spawn_ms"] > paint_now:
                continue
            pos = pt["pos"]
            painter.setBrush(QColor(255, 0, 0))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(pos, self._target_radius, self._target_radius)

        # 光标
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(text_color, 3))
        painter.drawLine(self._cursor_pos + QPointF(-15, 0), self._cursor_pos + QPointF(15, 0))
        painter.drawLine(self._cursor_pos + QPointF(0, -15), self._cursor_pos + QPointF(0, 15))
        painter.drawEllipse(self._cursor_pos, 20, 20)

        # 信息
        font = QFont("Arial", 16, QFont.Bold)
        painter.setFont(font)
        painter.setPen(text_color)
        hr = self.hit_rate()
        rt = self.avg_response_time()
        eff = self.path_efficiency()
        score_text = (
            f"游戏得分: {self._score} | 命中率: {int(round(hr * 100))}% | "
            f"响应: {int(round(rt * 1000))}ms | 效率: {int(round(eff * 100))}%"
        )
        painter.drawText(15, 40, score_text)

        if self._attention_score < 40:
            painter.setPen(QColor(255, 100, 100))
            painter.drawText(15, 75, f"注意力不足！分数: {self._attention_score}")
