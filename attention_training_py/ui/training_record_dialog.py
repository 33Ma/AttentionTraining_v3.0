# ui/training_record_dialog.py
import math
import os

from PySide6.QtCore import Qt, QDateTime
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QWidget, QComboBox, QMessageBox, QFileDialog, QHeaderView,
    QScrollArea
)
from PySide6.QtCharts import QChartView, QLineSeries, QChart, QValueAxis, QCategoryAxis

from core.settings import GlobalSettings, DifficultyLevel, TrainingRecord
from core.user_manager import UserManager, UserRole
from core.user_session import UserSession
from core.paths import app_data_dir
from core.portable_sync import (
    build_export_payload,
    is_forbidden_username,
    load_achievements_file,
    serialize_payload,
)

from ui.heatmap_widget import HeatmapWidget
from ai.composite_scoring import record_composite_score, score_ratio
from ai.teacher_report_logic import (
    GAME_MODE_LABELS,
    blinks_per_minute,
    composite_improvement,
    improvement_by_mode,
)


class TrainingRecordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("训练记录与数据分析")
        self.setMinimumSize(900, 650)
        self.resize(1000, 700)

        self._attention_series = None
        self._composite_series = None
        self._composite_tracking_series = None
        self._score_series = None
        self._score_tracking_series = None
        self._blink_series = None
        self._gaze_score_series = None
        self._gaze_distance_series = None
        self._student_selector = None
        self._selected_student_username = ""
        self._table = None  # 初始化
        self._tab_widget = None
        self._chart_page = None
        self._attention_chart_view = None
        self._composite_chart_view = None
        self._score_chart_view = None
        self._blink_chart_view = None
        self._gaze_score_chart_view = None
        self._gaze_distance_chart_view = None
        self._improvement_label = None
        self._trend_label = None
        self._heatmap_widget = None

        self._setup_ui()
        self._setup_chart_page()
        self._refresh_data()

        settings = GlobalSettings()
        settings.settings_changed.connect(self._apply_style_sheet)
        settings.training_records_changed.connect(self._refresh_data)

        self._apply_style_sheet()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        title = QLabel("📊 训练记录与数据分析")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; padding: 10px;")
        main_layout.addWidget(title)

        # 学生选择器（教师/管理员可见）
        user_manager = UserManager()
        if user_manager.current_user_role() in (UserRole.TEACHER, UserRole.ADMIN):
            student_select_layout = QHBoxLayout()
            student_label = QLabel("选择学生:")
            self._student_selector = QComboBox()
            self._student_selector.setFixedWidth(150)
            self._student_selector.currentIndexChanged.connect(self._on_student_changed)

            student_select_layout.addStretch()
            student_select_layout.addWidget(student_label)
            student_select_layout.addWidget(self._student_selector)
            student_select_layout.addStretch()
            main_layout.addLayout(student_select_layout)

            self._load_student_list()

        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar::tab { padding: 10px 25px; font-size: 14px; }"
            "QTabBar::tab:selected { background-color: #4CAF50; color: white; }"
        )

        # 训练记录页面
        record_page = QWidget()
        record_layout = QVBoxLayout(record_page)
        record_layout.setContentsMargins(5, 5, 5, 5)

        self._table = QTableWidget()  # 创建 _table
        self._table.setColumnCount(11)
        self._table.setHorizontalHeaderLabels([
            "训练时间", "时长", "游戏模式", "难度",
            "平均注意力", "眨眼次数", "每分钟眨眼次数", "游戏得分",
            "注视专注度平均值", "注视偏移距离平均值",
            "综合评分"
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        record_layout.addWidget(self._table)

        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("🗑️ 清除所有记录")
        close_btn = QPushButton("关闭")

        clear_btn.setFixedSize(150, 40)
        close_btn.setFixedSize(100, 40)

        clear_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; border: none; border-radius: 5px; font-size: 14px; font-weight: bold; } QPushButton:hover { background-color: #d32f2f; }")
        close_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; border: none; border-radius: 5px; font-size: 14px; font-weight: bold; } QPushButton:hover { background-color: #45a049; }")

        btn_layout.addStretch()
        btn_layout.addWidget(clear_btn)
        export_btn = QPushButton("📤 导出训练数据")
        export_btn.setFixedSize(150, 40)
        export_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; border: none; border-radius: 5px; font-size: 14px; font-weight: bold; } QPushButton:hover { background-color: #1976D2; }")
        export_btn.clicked.connect(self._on_export_data)
        btn_layout.addWidget(export_btn)

        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        record_layout.addLayout(btn_layout)

        clear_btn.clicked.connect(self._on_clear_records)
        close_btn.clicked.connect(self.accept)

        self._tab_widget.addTab(record_page, "📋 训练记录")

        # 图表页面
        self._chart_page = QWidget()
        self._tab_widget.addTab(self._chart_page, "📈 训练分析图")

        main_layout.addWidget(self._tab_widget)

    def _setup_chart_page(self):
        layout = QVBoxLayout(self._chart_page)
        layout.setSpacing(10)
        layout.setContentsMargins(5, 5, 5, 5)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)
        scroll_layout.setContentsMargins(10, 10, 10, 10)

        # 进步概览
        summary_card = QWidget()
        summary_card.setStyleSheet("background-color: rgba(76, 175, 80, 0.1); border-radius: 12px; padding: 10px;")
        card_layout = QVBoxLayout(summary_card)

        summary_title = QLabel("🎯 进步概览")
        summary_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        summary_title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(summary_title)

        stats_layout = QHBoxLayout()
        self._improvement_label = QLabel()
        self._improvement_label.setAlignment(Qt.AlignCenter)
        self._trend_label = QLabel()
        self._trend_label.setAlignment(Qt.AlignCenter)
        self._trend_label.setWordWrap(True)

        stats_layout.addWidget(self._improvement_label)
        stats_layout.addWidget(self._trend_label)
        card_layout.addLayout(stats_layout)
        scroll_layout.addWidget(summary_card)

        # 专注度热力图
        heatmap_card = QWidget()
        heatmap_card.setStyleSheet("background-color: rgba(33, 150, 243, 0.08); border-radius: 12px; padding: 10px;")
        heatmap_layout = QVBoxLayout(heatmap_card)
        heatmap_layout.setSpacing(8)

        heatmap_title = QLabel("🔥 专注度热力图")
        heatmap_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        heatmap_title.setAlignment(Qt.AlignCenter)
        heatmap_layout.addWidget(heatmap_title)

        self._heatmap_widget = HeatmapWidget()
        self._heatmap_widget.setMinimumHeight(300)
        heatmap_layout.addWidget(self._heatmap_widget)

        heatmap_caption = QLabel(
            "💡 每一列代表一次训练（从左到右，最早 → 最近），每一行代表一项指标；"
            "颜色越绿表示该项在自己历史中的表现越好，悬停单元格可查看具体数值。"
        )
        heatmap_caption.setWordWrap(True)
        heatmap_caption.setStyleSheet("font-size: 11px; color: #888888;")
        heatmap_layout.addWidget(heatmap_caption)

        scroll_layout.addWidget(heatmap_card)

        # 创建系列
        self._attention_series = QLineSeries()
        self._attention_series.setName("注意力分数")
        self._attention_series.setColor(QColor(76, 175, 80))
        self._attention_series.setPointsVisible(True)

        self._score_series = QLineSeries()
        self._score_series.setName("游戏得分（找茬）")
        self._score_series.setColor(QColor(33, 150, 243))
        self._score_series.setPointsVisible(True)

        self._score_tracking_series = QLineSeries()
        self._score_tracking_series.setName("游戏得分（动态追踪）")
        self._score_tracking_series.setColor(QColor(255, 152, 0))
        self._score_tracking_series.setPointsVisible(True)

        self._blink_series = QLineSeries()
        self._blink_series.setName("每分钟眨眼次数")
        self._blink_series.setColor(QColor(255, 152, 0))
        self._blink_series.setPointsVisible(True)

        self._gaze_score_series = QLineSeries()
        self._gaze_score_series.setName("注视专注度平均值")
        self._gaze_score_series.setColor(QColor(156, 39, 176))
        self._gaze_score_series.setPointsVisible(True)

        self._gaze_distance_series = QLineSeries()
        self._gaze_distance_series.setName("注视偏移距离平均值")
        self._gaze_distance_series.setColor(QColor(0, 150, 136))
        self._gaze_distance_series.setPointsVisible(True)

        self._composite_series = QLineSeries()
        self._composite_series.setName("综合评分（找茬）")
        self._composite_series.setColor(QColor(255, 87, 34))
        self._composite_series.setPointsVisible(True)

        self._composite_tracking_series = QLineSeries()
        self._composite_tracking_series.setName("综合评分（动态追踪）")
        self._composite_tracking_series.setColor(QColor(156, 39, 176))
        self._composite_tracking_series.setPointsVisible(True)

        # 注意力图表
        attention_chart = QChart()
        attention_chart.addSeries(self._attention_series)
        attention_chart.setTitle("注意力分数趋势")
        attention_chart.setAnimationOptions(QChart.NoAnimation)
        attention_chart.setBackgroundVisible(False)

        self._attention_chart_view = QChartView(attention_chart)
        self._attention_chart_view.setRenderHint(QPainter.Antialiasing)
        self._attention_chart_view.setMinimumHeight(250)
        scroll_layout.addWidget(self._attention_chart_view)

        composite_chart = QChart()
        composite_chart.addSeries(self._composite_series)
        composite_chart.addSeries(self._composite_tracking_series)
        composite_chart.setTitle("综合评分趋势（按模式）")
        composite_chart.setAnimationOptions(QChart.NoAnimation)
        composite_chart.setBackgroundVisible(False)

        self._composite_chart_view = QChartView(composite_chart)
        self._composite_chart_view.setRenderHint(QPainter.Antialiasing)
        self._composite_chart_view.setMinimumHeight(250)
        scroll_layout.addWidget(self._composite_chart_view)

        # 游戏得分图表
        score_chart = QChart()
        score_chart.addSeries(self._score_series)
        score_chart.addSeries(self._score_tracking_series)
        score_chart.setTitle("游戏得分趋势（按模式·0-100）")
        score_chart.setAnimationOptions(QChart.NoAnimation)
        score_chart.setBackgroundVisible(False)

        self._score_chart_view = QChartView(score_chart)
        self._score_chart_view.setRenderHint(QPainter.Antialiasing)
        self._score_chart_view.setMinimumHeight(250)
        scroll_layout.addWidget(self._score_chart_view)

        # 每分钟眨眼次数图表
        blink_chart = QChart()
        blink_chart.addSeries(self._blink_series)
        blink_chart.setTitle("每分钟眨眼次数趋势")
        blink_chart.setAnimationOptions(QChart.NoAnimation)
        blink_chart.setBackgroundVisible(False)

        self._blink_chart_view = QChartView(blink_chart)
        self._blink_chart_view.setRenderHint(QPainter.Antialiasing)
        self._blink_chart_view.setMinimumHeight(250)
        scroll_layout.addWidget(self._blink_chart_view)

        # 注视专注度平均值图表
        gaze_score_chart = QChart()
        gaze_score_chart.addSeries(self._gaze_score_series)
        gaze_score_chart.setTitle("注视专注度平均值趋势")
        gaze_score_chart.setAnimationOptions(QChart.NoAnimation)
        gaze_score_chart.setBackgroundVisible(False)

        self._gaze_score_chart_view = QChartView(gaze_score_chart)
        self._gaze_score_chart_view.setRenderHint(QPainter.Antialiasing)
        self._gaze_score_chart_view.setMinimumHeight(250)
        scroll_layout.addWidget(self._gaze_score_chart_view)

        # 注视偏移距离平均值图表
        gaze_distance_chart = QChart()
        gaze_distance_chart.addSeries(self._gaze_distance_series)
        gaze_distance_chart.setTitle("注视偏移距离平均值趋势")
        gaze_distance_chart.setAnimationOptions(QChart.NoAnimation)
        gaze_distance_chart.setBackgroundVisible(False)

        self._gaze_distance_chart_view = QChartView(gaze_distance_chart)
        self._gaze_distance_chart_view.setRenderHint(QPainter.Antialiasing)
        self._gaze_distance_chart_view.setMinimumHeight(250)
        scroll_layout.addWidget(self._gaze_distance_chart_view)

        info_label = QLabel(
            "💡 提示：\n"
            "• 图表从左到右显示最早到最近的训练记录\n"
            "• 综合评分与游戏得分图表按模式分为找茬/动态追踪两条曲线\n"
            "• 找茬游戏得分按训练期间的比例规则归一为0-100（不含连击加成）\n"
            "• 注意力分数越高表示专注度越好\n"
            "• 每分钟眨眼次数越少通常表示更专注（正常范围约 10-20 次/分钟）\n"
            "• 注视专注度平均值越高表示视线越集中\n"
            "• 注视偏移距离平均值越小表示视线越贴近屏幕中心"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 11px; color: #888888; padding: 10px; background-color: rgba(0,0,0,0.05); border-radius: 8px;")
        scroll_layout.addWidget(info_label)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

    def _load_student_list(self):
        if not self._student_selector:
            return

        self._student_selector.clear()
        user_manager = UserManager()

        if user_manager.current_user_role() == UserRole.ADMIN:
            students = user_manager.get_students()
        else:
            students = user_manager.get_students_by_teacher(user_manager.current_username())

        for student in students:
            self._student_selector.addItem(student.display_name, student.username)

        if students:
            self._student_selector.setEnabled(True)
            self._student_selector.setCurrentIndex(0)
            self._on_student_changed(0)
        else:
            self._student_selector.addItem("暂无学生", "")
            self._student_selector.setEnabled(False)
            self._update_table([])
            self._update_charts([])

    def _load_records_for_user(self, username: str) -> list:
        """????????????????????????????"""
        return UserSession().get_user_training_records(username)

    def _on_student_changed(self, index: int):
        if not self._student_selector or index < 0:
            return

        username = self._student_selector.itemData(index)
        self._selected_student_username = username or ""

        if not username:
            self._update_table([])
            self._update_charts([])
            return

        records = self._load_records_for_user(username)
        self._update_table(records)
        self._update_charts(records)

    def _update_table(self, records: list):
        if not self._table:  # 确保 _table 存在
            return

        self._table.clearContents()
        self._table.setRowCount(0)

        if not records:
            self._table.setRowCount(1)
            self._table.setSpan(0, 0, 1, self._table.columnCount())
            empty_item = QTableWidgetItem("暂无训练记录")
            empty_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(0, 0, empty_item)
            return

        self._table.setRowCount(len(records))

        for i, record in enumerate(records):
            self._table.setItem(i, 0, QTableWidgetItem(record.date_time.toString("MM-dd HH:mm")))
            self._table.setItem(i, 1, QTableWidgetItem(f"{record.duration_minutes}分钟"))

            mode_str = "找茬模式" if record.game_mode == "find_difference" else "动态追踪"
            self._table.setItem(i, 2, QTableWidgetItem(mode_str))

            diff_strs = {
                DifficultyLevel.EASY: "简单",
                DifficultyLevel.NORMAL: "普通",
                DifficultyLevel.HARD: "困难",
                DifficultyLevel.CUSTOM: "自定义"
            }
            self._table.setItem(i, 3, QTableWidgetItem(diff_strs.get(record.difficulty, "普通")))

            att_item = QTableWidgetItem(str(record.avg_attention_score))
            if record.avg_attention_score >= 70:
                att_item.setForeground(QColor(76, 175, 80))
            elif record.avg_attention_score >= 40:
                att_item.setForeground(QColor(255, 152, 0))
            else:
                att_item.setForeground(QColor(244, 67, 54))
            self._table.setItem(i, 4, att_item)

            self._table.setItem(i, 5, QTableWidgetItem(str(record.total_blinks)))
            self._table.setItem(
                i, 6, QTableWidgetItem(str(int(round(blinks_per_minute(record)))))
            )
            # 游戏得分统一为 0-100：与图表/热力图一致，找茬按训练期间比例规则
            # （score_ratio，实际得分/难度基准）归一，不叠加连击分；动态追踪本身即为 0-100。
            normalized_score = int(round(
                score_ratio(record.game_score, record.game_mode, record.difficulty,
                            record.duration_minutes) * 100.0
            ))
            self._table.setItem(i, 7, QTableWidgetItem(str(normalized_score)))

            gaze_score_item = QTableWidgetItem(str(record.avg_gaze_score))
            if record.avg_gaze_score >= 70:
                gaze_score_item.setForeground(QColor(76, 175, 80))
            elif record.avg_gaze_score >= 40:
                gaze_score_item.setForeground(QColor(255, 152, 0))
            else:
                gaze_score_item.setForeground(QColor(244, 67, 54))
            self._table.setItem(i, 8, gaze_score_item)

            gaze_dist_item = QTableWidgetItem(f"{record.avg_gaze_distance:.3f}")
            if record.avg_gaze_distance < 0.15:
                gaze_dist_item.setForeground(QColor(76, 175, 80))
            elif record.avg_gaze_distance < 0.3:
                gaze_dist_item.setForeground(QColor(255, 152, 0))
            else:
                gaze_dist_item.setForeground(QColor(244, 67, 54))
            self._table.setItem(i, 9, gaze_dist_item)

            composite_item = QTableWidgetItem(str(record_composite_score(record)))
            cs = record_composite_score(record)
            if cs >= 80:
                composite_item.setForeground(QColor(76, 175, 80))
            elif cs >= 50:
                composite_item.setForeground(QColor(255, 152, 0))
            else:
                composite_item.setForeground(QColor(244, 67, 54))
            self._table.setItem(i, 10, composite_item)

    def _update_charts(self, records: list):
        if not self._attention_series:
            return

        # 计算进步
        # 进步：每种模式单独计算（某模式仅一次时按旧约定记为 0%）
        by_mode = improvement_by_mode(records)
        mode_parts = []
        for mode, mode_label in GAME_MODE_LABELS:
            imp = by_mode.get(mode, 0.0)
            color = "#4CAF50" if imp > 0 else "#F44336" if imp < 0 else "#FF9800"
            mode_parts.append(
                f'<span style="color:{color}; font-weight:bold;">{mode_label} {imp:+.0f}%</span>'
            )
        self._improvement_label.setText("　|　".join(mode_parts))
        self._improvement_label.setStyleSheet("font-size: 22px;")

        self._trend_label.setText(self._get_trend_text(records))

        # 清除系列数据
        self._attention_series.clear()
        self._score_series.clear()
        self._score_tracking_series.clear()
        self._blink_series.clear()
        self._gaze_score_series.clear()
        self._gaze_distance_series.clear()
        self._composite_series.clear()
        self._composite_tracking_series.clear()

        # 反转数据（最早到最近）
        chart_records = records[::-1] if records else []

        self._update_heatmap(chart_records)

        if not chart_records:
            return

        for i, record in enumerate(chart_records):
            x = i + 1
            self._attention_series.append(x, record.avg_attention_score)
            # 游戏得分统一为 0-100：找茬按训练期间的比例规则（实际得分/难度基准）归一，
            # 不叠加连击分；动态追踪本身即为 0-100。
            normalized_score = score_ratio(
                record.game_score, record.game_mode, record.difficulty,
                record.duration_minutes,
            ) * 100.0
            composite = record_composite_score(record)
            if record.game_mode == "dynamic_tracking":
                self._score_tracking_series.append(x, normalized_score)
                self._composite_tracking_series.append(x, composite)
            else:
                self._score_series.append(x, normalized_score)
                self._composite_series.append(x, composite)
            self._blink_series.append(x, blinks_per_minute(record))
            self._gaze_score_series.append(x, record.avg_gaze_score)
            self._gaze_distance_series.append(x, record.avg_gaze_distance)

        self._setup_chart_axes(len(chart_records))

    def _setup_chart_axes(self, point_count: int):
        if point_count == 0:
            return

        charts = [
            (self._attention_chart_view, [self._attention_series], "注意力分数", 0.0, 100.0, False),
            (self._composite_chart_view, [self._composite_series, self._composite_tracking_series],
             "综合评分", 0.0, 100.0, False),
            (self._score_chart_view, [self._score_series, self._score_tracking_series],
             "游戏得分（0-100）", 0.0, 100.0, False),
            (self._blink_chart_view, [self._blink_series], "每分钟眨眼次数", 0.0, None, True),
            (self._gaze_score_chart_view, [self._gaze_score_series], "注视专注度平均值", 0.0, 100.0, False),
            (self._gaze_distance_chart_view, [self._gaze_distance_series], "注视偏移距离平均值", 0.0, None, False)
        ]

        for chart_view, series_list, title, domain_min, domain_max, integer_ticks in charts:
            if not (chart_view and chart_view.chart()):
                continue
            chart = chart_view.chart()

            # 移除旧轴
            for axis in chart.axes():
                chart.removeAxis(axis)

            y_values = [
                point.y() for series in series_list
                for point in series.points()
            ]
            y_min, y_max, y_step = self._nice_axis_range(y_values, domain_min, domain_max, integer_ticks)

            axis_x = QCategoryAxis()
            axis_x.setTitleText("训练次数（最早 → 最近）")
            axis_x.setRange(0.5, point_count + 0.5)
            axis_x.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
            label_step = max(1, math.ceil(point_count / 10))
            for i in range(1, point_count + 1, label_step):
                axis_x.append(str(i), float(i))
            axis_x.setGridLineVisible(False)

            axis_y = QValueAxis()
            axis_y.setTitleText(title)
            axis_y.setRange(y_min, y_max)
            axis_y.setTickCount(int(round((y_max - y_min) / y_step)) + 1)
            if y_step >= 1:
                axis_y.setLabelFormat("%d")
            elif y_step >= 0.1:
                axis_y.setLabelFormat("%.1f")
            else:
                axis_y.setLabelFormat("%.2f")

            chart.addAxis(axis_x, Qt.AlignBottom)
            chart.addAxis(axis_y, Qt.AlignLeft)
            for series in series_list:
                series.attachAxis(axis_x)
                series.attachAxis(axis_y)

    def _update_heatmap(self, chart_records: list):
        """填充专注度热力图：行 = 指标，列 = 训练次数。"""
        if self._heatmap_widget is None:
            return

        if not chart_records:
            self._heatmap_widget.set_data([], [])
            return

        rows = [
            ("平均注意力", [r.avg_attention_score for r in chart_records], True),
            ("注视专注度", [r.avg_gaze_score for r in chart_records], True),
            # 游戏得分统一为 0-100：找茬/动态追踪均按训练期间的比例规则
            # （score_ratio，实际得分/难度基准或 /100）归一，不叠加连击分。
            ("游戏得分（0-100）", [
                score_ratio(r.game_score, r.game_mode, r.difficulty,
                            r.duration_minutes) * 100.0
                for r in chart_records
            ], True),
            ("每分钟眨眼次数", [blinks_per_minute(r) for r in chart_records], False),
            ("注视偏移距离", [r.avg_gaze_distance for r in chart_records], False),
            ("综合评分", [record_composite_score(r) for r in chart_records], True),
        ]
        labels = [
            r.date_time.toString("MM-dd") if r.date_time else f"第{i + 1}次"
            for i, r in enumerate(chart_records)
        ]
        self._heatmap_widget.set_data(rows, labels)

    @staticmethod
    def _nice_axis_range(values, domain_min=None, domain_max=None, integer_ticks=False):
        """根据数据范围计算美观的自适应坐标轴范围与刻度步长。

        刻度目标密度约为 7 档，步长按 1/2/5 x 10^n 自适应取整；
        顶部不做硬性截断：当数据贴近（或达到）100 等上限时，
        坐标轴自动向外扩展一个刻度，为曲线和刻度标签预留空间。
        """
        if not values:
            low, high = 0.0, 1.0
        else:
            data_min = float(min(values))
            data_max = float(max(values))
            span = data_max - data_min
            if span > 0:
                pad = span * 0.10
            else:
                pad = max(abs(data_min) * 0.1, 1.0)
            low = data_min - pad
            high = data_max + pad

        # 下限不越过自然定义域（百分比/次数等不能为负）
        if domain_min is not None:
            low = max(low, domain_min)
        if high <= low:
            high = low + 1.0

        raw_step = (high - low) / 7.0
        magnitude = 10 ** math.floor(math.log10(raw_step))
        step = magnitude
        for nice in (1, 2, 5, 10):
            candidate = nice * magnitude
            if raw_step <= candidate + 1e-9:
                step = candidate
                break
        if integer_ticks and step < 1:
            step = 1.0

        low = math.floor(low / step) * step
        high = math.ceil(high / step) * step

        # 数据最大值不应顶在坐标轴边界上：至少留出半个刻度的空间
        if values and float(max(values)) >= high - step * 0.5:
            high += step

        return low, high, step

    def _calculate_improvement(self, records: list) -> float:
        if len(records) < 2:
            return 0.0

        compare_count = 1
        if len(records) >= 6:
            compare_count = 3
        elif len(records) >= 4:
            compare_count = 2

        recent_sum = sum(record_composite_score(r) for r in records[:compare_count])
        early_sum = sum(record_composite_score(r) for r in records[-compare_count:])

        recent_avg = recent_sum // compare_count
        early_avg = early_sum // compare_count

        if early_avg == 0:
            return 100.0 if recent_avg > 0 else 0.0

        return max(-100.0, min(100.0, ((recent_avg - early_avg) / early_avg) * 100.0))

    @staticmethod
    def _mode_of(record) -> str:
        """未知/空模式按找茬处理（与 score_ratio 归一语义一致）。"""
        mode = getattr(record, "game_mode", "")
        return mode if mode == "dynamic_tracking" else "find_difference"

    def _get_trend_text(self, records: list) -> str:
        lines = []
        for mode, mode_label in GAME_MODE_LABELS:
            mode_records = [r for r in records if self._mode_of(r) == mode]
            if len(mode_records) < 2:
                # 仅一次：按旧约定不展示进步趋势
                lines.append(f"{mode_label}模式：完成更多训练后将显示进步趋势")
                continue

            compare_count = 1
            if len(mode_records) >= 6:
                compare_count = 3
            elif len(mode_records) >= 4:
                compare_count = 2

            recent_avg = (
                sum(record_composite_score(r) for r in mode_records[:compare_count])
                // compare_count
            )
            early_avg = (
                sum(record_composite_score(r) for r in mode_records[-compare_count:])
                // compare_count
            )
            improvement = composite_improvement(mode_records)

            if improvement > 0:
                lines.append(
                    f"{mode_label}模式：综合分数从{early_avg}提升到{recent_avg}，"
                    f"提升了{int(improvement)}%"
                )
            elif improvement < 0:
                lines.append(
                    f"{mode_label}模式：综合分数从{early_avg}降至{recent_avg}，"
                    f"下降{int(-improvement)}%"
                )
            else:
                lines.append(f"{mode_label}模式：综合分数保持{recent_avg}，基本持平")
        return "\n".join(lines)

    def _on_export_data(self):
        user_manager = UserManager()
        if self._student_selector is not None:
            username = self._selected_student_username
            user = user_manager.get_user(username) if username else None
        else:
            username = GlobalSettings().current_user()
            user = user_manager.get_user(username)

        if is_forbidden_username(username):
            QMessageBox.warning(self, "禁止导出", "默认用户/空用户名的数据不允许导出")
            return

        display_name = user.display_name if user else username
        role = user.role.value if user else "student"
        teacher_id = user.teacher_id if user else ""

        records = [
            r.to_dict()
            for r in GlobalSettings().training_records_for_user(username)
        ]
        achievements = load_achievements_file(
            os.path.join(app_data_dir(), "users", username, "achievements.json")
        )

        payload = build_export_payload(
            username=username,
            display_name=display_name,
            role=role,
            teacher_id=teacher_id,
            records=records,
            achievements=achievements,
        )

        default_name = (
            f"训练数据_{username}_"
            f"{QDateTime.currentDateTime().toString('yyyyMMdd')}.json"
        )
        file_name = QFileDialog.getSaveFileName(
            self, "导出训练数据", default_name, "训练数据文件 (*.json);;所有文件 (*)"
        )[0]
        if not file_name:
            return

        try:
            with open(file_name, "w", encoding="utf-8") as f:
                f.write(serialize_payload(payload))
        except OSError as e:
            QMessageBox.warning(self, "导出失败", f"无法写入文件:\n{e}")
            return

        QMessageBox.information(
            self,
            "导出成功",
            f"已导出 {len(records)} 条训练记录。\n"
            f"文件: {file_name}\n"
            f"请在教师端「班级报告」中点击「导入学生数据」。",
        )
    def _on_clear_records(self):
        settings = GlobalSettings()
        if self._student_selector is not None:
            target_user = self._selected_student_username
            if not target_user:
                QMessageBox.warning(self, "警告", "请先选择要清除记录的学生")
                return
        else:
            target_user = settings.current_user()

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("确认")
        msg_box.setText(f'确定要清除 "{target_user}" 的所有训练记录吗？\n\n此操作不可恢复')
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)
        msg_box.setStyleSheet(GlobalSettings().get_message_box_style_sheet())

        if msg_box.exec() == QMessageBox.Yes:
            session = UserSession()
            if session.clear_user_training_records(target_user):
                self._refresh_data()
                info_box = QMessageBox(self)
                info_box.setWindowTitle("成功")
                info_box.setText(f'已成功清除 "{target_user}" 的所有训练记录')
                info_box.setStyleSheet(GlobalSettings().get_message_box_style_sheet())
                info_box.exec()
            else:
                QMessageBox.warning(self, "错误", "清除训练记录失败，请稍后重试")

    def _refresh_data(self):
        if self._student_selector is not None:
            if self._student_selector.isEnabled() and self._student_selector.currentIndex() >= 0:
                self._on_student_changed(self._student_selector.currentIndex())
            else:
                self._update_table([])
                self._update_charts([])
        else:
            settings = GlobalSettings()
            records = settings.training_records_for_user(settings.current_user())
            self._update_table(records)
            self._update_charts(records)

    def _apply_style_sheet(self):
        settings = GlobalSettings()
        bg = settings.background_color().name()
        text = settings.text_color().name()
        night_mode = settings.night_mode()

        table_bg = "#2d2d2d" if night_mode else "#ffffff"
        header_bg = "#3a3a3a" if night_mode else "#f0f0f0"
        border_color = "#555555" if night_mode else "#cccccc"

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text}; }}
            QTableWidget {{ background-color: {table_bg}; color: {text}; gridline-color: {border_color}; }}
            QTableWidget::item {{ padding: 5px; }}
            QTableWidget::item:selected {{ background-color: #4CAF50; color: white; }}
            QHeaderView::section {{ background-color: {header_bg}; color: {text}; padding: 8px; font-weight: bold; border: none; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none; border-radius: 5px; padding: 5px 15px; font-size: 13px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QTabWidget::pane {{ background-color: {bg}; border: none; }}
            QTabBar::tab {{ background-color: {header_bg}; color: {text}; padding: 8px 20px; }}
            QTabBar::tab:selected {{ background-color: #4CAF50; color: white; }}
            QScrollArea {{ background-color: transparent; border: none; }}
            QComboBox {{ background-color: {table_bg}; color: {text}; border: 1px solid #4CAF50; border-radius: 5px; padding: 5px; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background-color: {table_bg}; color: {text}; }}
        """)

        if self._heatmap_widget is not None:
            self._heatmap_widget.set_theme(night_mode, QColor(text))
