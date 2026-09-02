# ui/heatmap_widget.py
"""专注度热力图控件：行为指标、列为训练次数，颜色表示相对表现。"""

import math
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget


COLOR_LOW = QColor(255, 255, 255)   # 表现差：白色
COLOR_HIGH = QColor(230, 126, 34)   # 表现好：橙色

RowData = Tuple[str, Sequence[float], bool]


def _gradient_color(value: float) -> QColor:
    """把 0-100 的归一化分数线性映射为 白->橙 渐变颜色（表现差为白，表现好为橙）。"""
    value = max(0.0, min(100.0, value))
    t = value / 100.0
    r = COLOR_LOW.red() + (COLOR_HIGH.red() - COLOR_LOW.red()) * t
    g = COLOR_LOW.green() + (COLOR_HIGH.green() - COLOR_LOW.green()) * t
    b = COLOR_LOW.blue() + (COLOR_HIGH.blue() - COLOR_LOW.blue()) * t
    return QColor(int(round(r)), int(round(g)), int(round(b)))


def _format_value(value: float) -> str:
    """根据数值类型给出紧凑的单元格文本。"""
    if float(value).is_integer():
        return str(int(round(value)))
    return f"{value:.3f}"


class HeatmapWidget(QWidget):
    """自适应专注度热力图控件。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rows: List[RowData] = []
        self._col_labels: List[str] = []
        self._night_mode = False
        self._text_color = QColor(60, 60, 60)
        self._hover_col = -1
        self._hover_row = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(300)
        self.setMinimumWidth(420)

    def set_data(self, rows: List[RowData], column_labels: Sequence[str]):
        """设置热力图数据。"""
        self._rows = list(rows)
        self._col_labels = list(column_labels)
        self._hover_col = -1
        self._hover_row = -1
        self.update()

    def set_theme(self, night_mode: bool, text_color: QColor):
        self._night_mode = night_mode
        self._text_color = QColor(text_color)
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        col, row = self._cell_at(pos)
        if (col, row) != (self._hover_col, self._hover_row):
            self._hover_col, self._hover_row = col, row
            self.update()
            if col >= 0 and row >= 0:
                QToolTip.showText(event.globalPosition().toPoint(), self._tooltip_text(col, row))
            else:
                QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_col = -1
        self._hover_row = -1
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def _layout(self):
        margin = 12
        legend_w = 28
        x_label_h = 22
        label_font = QFont(self.font())
        label_font.setPixelSize(11)
        fm = QFontMetrics(label_font)
        label_w = max([fm.horizontalAdvance(name) for name, _, _ in self._rows] or [0]) + 18
        width = max(self.width() - 2 * margin - label_w - legend_w, 10)
        height = max(self.height() - 2 * margin - x_label_h, 10)
        grid_rect = QRect(margin + label_w, margin, width, height)
        return grid_rect, label_w, x_label_h

    def _cell_rect(self, col, row, grid_rect, cols, rows) -> QRect:
        gap = 2
        cell_w = (grid_rect.width() - gap * (cols - 1)) / cols
        cell_h = (grid_rect.height() - gap * (rows - 1)) / rows
        x = grid_rect.left() + int(round(col * (cell_w + gap)))
        y = grid_rect.top() + int(round(row * (cell_h + gap)))
        return QRect(x, y, max(int(round(cell_w)), 1), max(int(round(cell_h)), 1))

    def _cell_at(self, pos: QPoint):
        grid_rect, _, _ = self._layout()
        rows = len(self._rows)
        cols = len(self._col_labels)
        if rows == 0 or cols == 0 or not grid_rect.contains(pos):
            return -1, -1
        gap = 2
        cell_w = (grid_rect.width() - gap * (cols - 1)) / cols
        cell_h = (grid_rect.height() - gap * (rows - 1)) / rows
        col = int((pos.x() - grid_rect.left()) // (cell_w + gap))
        row = int((pos.y() - grid_rect.top()) // (cell_h + gap))
        if 0 <= col < cols and 0 <= row < rows:
            return col, row
        return -1, -1

    def _tooltip_text(self, col: int, row: int) -> str:
        lines = [f"第 {col + 1} 次训练 · {self._col_labels[col]}"]
        for i, (name, values, _) in enumerate(self._rows):
            if row == i and 0 <= col < len(values):
                lines.append(f"{name}: {_format_value(values[col])}")
        return "\n".join(lines)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if not self._rows or not self._col_labels:
            painter.setPen(self._text_color)
            hint = QFont(self.font())
            hint.setPixelSize(13)
            painter.setFont(hint)
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无训练记录\n完成训练后将在这里显示专注度热力图")
            painter.end()
            return

        grid_rect, label_w, x_label_h = self._layout()
        rows = len(self._rows)
        cols = len(self._col_labels)

        label_font = QFont(self.font())
        label_font.setPixelSize(11)
        cell_font = QFont(self.font())
        cell_font.setPixelSize(10)

        painter.setFont(label_font)
        painter.setPen(self._text_color)
        for i, (name, _, _) in enumerate(self._rows):
            cell_rect = self._cell_rect(0, i, grid_rect, cols, rows)
            text_rect = QRect(
                self.rect().left() + 4,
                cell_rect.center().y() - 10,
                label_w - 14,
                20,
            )
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, name)

        normalized = self._normalize_rows()
        for j in range(cols):
            for i, (_, values, _) in enumerate(self._rows):
                if j >= len(values):
                    continue
                raw = values[j]
                level = normalized[i][j]
                color = _gradient_color(level)
                rect = self._cell_rect(j, i, grid_rect, cols, rows)

                path = QPainterPath()
                path.addRoundedRect(rect, 3, 3)
                painter.fillPath(path, color)

                if self._night_mode:
                    border = QColor(255, 255, 255, 28)
                else:
                    border = QColor(0, 0, 0, 18)
                painter.setPen(QPen(border, 1))
                painter.drawPath(path)

                if rect.width() >= 28 and rect.height() >= 20:
                    painter.setFont(cell_font)
                    text = _format_value(raw)
                    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
                    painter.setPen(QColor(255, 255, 255) if luminance < 150 else QColor(40, 40, 40))
                    painter.drawText(rect.adjusted(1, 1, -1, -1), Qt.AlignCenter, text)

        if 0 <= self._hover_col < cols and 0 <= self._hover_row < rows:
            rect = self._cell_rect(self._hover_col, self._hover_row, grid_rect, cols, rows)
            painter.setPen(QPen(QColor(255, 255, 255, 230), 2))
            path = QPainterPath()
            path.addRoundedRect(rect.adjusted(-1, -1, 1, 1), 4, 4)
            painter.drawPath(path)

        label_step = max(1, math.ceil(cols / 12))
        painter.setFont(label_font)
        painter.setPen(self._text_color)
        for j in range(cols):
            if j % label_step != 0 and j != cols - 1:
                continue
            rect = self._cell_rect(j, 0, grid_rect, cols, rows)
            label_rect = QRect(rect.left(), grid_rect.bottom() + 2, rect.width(), x_label_h)
            painter.drawText(label_rect, Qt.AlignCenter, self._col_labels[j])

        self._draw_legend(painter, grid_rect)
        painter.end()

    def _draw_legend(self, painter: QPainter, grid_rect: QRect):
        bar_w = 12
        bar_rect = QRect(grid_rect.right() + 10, grid_rect.top(), bar_w, grid_rect.height())
        gradient = QLinearGradient(bar_rect.topLeft(), bar_rect.bottomLeft())
        gradient.setColorAt(0.0, COLOR_HIGH)
        gradient.setColorAt(1.0, COLOR_LOW)
        painter.fillRect(bar_rect, gradient)
        painter.setPen(self._text_color)
        font = QFont(self.font())
        font.setPixelSize(10)
        painter.setFont(font)
        painter.drawText(QRect(bar_rect.left() - 4, grid_rect.top() - 4, bar_w + 8, 16), Qt.AlignCenter, "强")
        painter.drawText(QRect(bar_rect.left() - 4, grid_rect.bottom() - 12, bar_w + 8, 16), Qt.AlignCenter, "弱")

    def _normalize_rows(self) -> List[List[float]]:
        """每行独立做 0-100 归一化；越小越好的指标取反。"""
        result: List[List[float]] = []
        for _, values, higher_is_better in self._rows:
            data = [float(v) for v in values]
            lo = min(data)
            hi = max(data)
            if hi > lo:
                levels = [(v - lo) / (hi - lo) * 100.0 for v in data]
            elif not higher_is_better:
                levels = [100.0 if v == 0 else 50.0 for v in data]
            else:
                levels = [100.0 if v > 0 else 50.0 for v in data]
            if not higher_is_better:
                levels = [100.0 - level for level in levels]
            result.append(levels)
        return result
