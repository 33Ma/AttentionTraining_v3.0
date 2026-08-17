# ui/training_record_dialog.py
from PySide6.QtCore import Qt, QDateTime
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QWidget, QComboBox, QMessageBox, QHeaderView,
    QScrollArea
)
from PySide6.QtCharts import QChartView, QLineSeries, QChart, QValueAxis

from core.settings import GlobalSettings, DifficultyLevel, TrainingRecord
from core.user_manager import UserManager, UserRole
from core.user_session import UserSession


class TrainingRecordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("训练记录与数据分析")
        self.setMinimumSize(900, 650)
        self.resize(1000, 700)

        self._attention_series = None
        self._score_series = None
        self._blink_series = None
        self._student_selector = None
        self._selected_student_username = ""
        self._table = None  # 初始化
        self._tab_widget = None
        self._chart_page = None
        self._attention_chart_view = None
        self._score_chart_view = None
        self._blink_chart_view = None
        self._improvement_label = None
        self._trend_label = None

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
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "训练时间", "时长", "游戏模式", "难度",
            "平均注意力", "眨眼次数", "游戏得分"
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

        # 创建系列
        self._attention_series = QLineSeries()
        self._attention_series.setName("注意力分数")
        self._attention_series.setColor(QColor(76, 175, 80))
        self._attention_series.setPointsVisible(True)

        self._score_series = QLineSeries()
        self._score_series.setName("游戏得分")
        self._score_series.setColor(QColor(33, 150, 243))
        self._score_series.setPointsVisible(True)

        self._blink_series = QLineSeries()
        self._blink_series.setName("眨眼次数")
        self._blink_series.setColor(QColor(255, 152, 0))
        self._blink_series.setPointsVisible(True)

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

        # 游戏得分图表
        score_chart = QChart()
        score_chart.addSeries(self._score_series)
        score_chart.setTitle("游戏得分趋势")
        score_chart.setAnimationOptions(QChart.NoAnimation)
        score_chart.setBackgroundVisible(False)

        self._score_chart_view = QChartView(score_chart)
        self._score_chart_view.setRenderHint(QPainter.Antialiasing)
        self._score_chart_view.setMinimumHeight(250)
        scroll_layout.addWidget(self._score_chart_view)

        # 眨眼次数图表
        blink_chart = QChart()
        blink_chart.addSeries(self._blink_series)
        blink_chart.setTitle("眨眼次数趋势")
        blink_chart.setAnimationOptions(QChart.NoAnimation)
        blink_chart.setBackgroundVisible(False)

        self._blink_chart_view = QChartView(blink_chart)
        self._blink_chart_view.setRenderHint(QPainter.Antialiasing)
        self._blink_chart_view.setMinimumHeight(250)
        scroll_layout.addWidget(self._blink_chart_view)

        info_label = QLabel(
            "💡 提示：\n"
            "• 图表从左到右显示最早到最近的训练记录\n"
            "• 注意力分数越高表示专注度越好\n"
            "• 眨眼次数越少通常表示更专注"
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
            self._table.setSpan(0, 0, 1, 7)
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
            self._table.setItem(i, 6, QTableWidgetItem(str(record.game_score)))

    def _update_charts(self, records: list):
        if not self._attention_series:
            return

        # 计算进步
        improvement = self._calculate_improvement(records)
        if improvement > 0:
            self._improvement_label.setText(f"📈 +{int(improvement)}%")
            self._improvement_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #4CAF50;")
        elif improvement < 0:
            self._improvement_label.setText(f"📉 {int(improvement)}%")
            self._improvement_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #F44336;")
        else:
            self._improvement_label.setText("➡️ 0%")
            self._improvement_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #FF9800;")

        self._trend_label.setText(self._get_trend_text(records))

        # 清除系列数据
        self._attention_series.clear()
        self._score_series.clear()
        self._blink_series.clear()

        if not records:
            return

        # 反转数据（最早到最近）
        chart_records = records[::-1]

        for i, record in enumerate(chart_records):
            x = i + 1
            self._attention_series.append(x, record.avg_attention_score)
            self._score_series.append(x, record.game_score)
            self._blink_series.append(x, record.total_blinks)

        self._setup_chart_axes(len(chart_records))

    def _setup_chart_axes(self, point_count: int):
        if point_count == 0:
            return

        charts = [
            (self._attention_chart_view, self._attention_series, "注意力分数", 0, 100),
            (self._score_chart_view, self._score_series, "游戏得分", 0, 1500),
            (self._blink_chart_view, self._blink_series, "眨眼次数", 0, 30)
        ]

        for chart_view, series, title, min_val, max_val in charts:
            if chart_view and chart_view.chart():
                chart = chart_view.chart()

                # 移除旧轴
                for axis in chart.axes():
                    chart.removeAxis(axis)

                axis_x = QValueAxis()
                axis_x.setTitleText("训练次数（最早 → 最近）")
                axis_x.setRange(0.5, point_count + 0.5)
                axis_x.setTickCount(min(6, point_count + 1))

                axis_y = QValueAxis()
                axis_y.setTitleText(title)
                axis_y.setRange(min_val, max_val)

                chart.addAxis(axis_x, Qt.AlignBottom)
                chart.addAxis(axis_y, Qt.AlignLeft)
                series.attachAxis(axis_x)
                series.attachAxis(axis_y)

    def _calculate_improvement(self, records: list) -> float:
        if len(records) < 2:
            return 0.0

        compare_count = 1
        if len(records) >= 6:
            compare_count = 3
        elif len(records) >= 4:
            compare_count = 2

        recent_sum = sum(r.avg_attention_score for r in records[:compare_count])
        early_sum = sum(r.avg_attention_score for r in records[-compare_count:])

        recent_avg = recent_sum // compare_count
        early_avg = early_sum // compare_count

        if early_avg == 0:
            return 100.0 if recent_avg > 0 else 0.0

        return max(-100.0, min(100.0, ((recent_avg - early_avg) / early_avg) * 100.0))

    def _get_trend_text(self, records: list) -> str:
        if len(records) < 2:
            return "完成更多训练后\n将显示进步趋势"

        improvement = self._calculate_improvement(records)

        compare_count = 1
        if len(records) >= 6:
            compare_count = 3
        elif len(records) >= 4:
            compare_count = 2

        recent_avg = sum(r.avg_attention_score for r in records[:compare_count]) // compare_count
        early_avg = sum(r.avg_attention_score for r in records[-compare_count:]) // compare_count

        if improvement > 20:
            return f"🚀 进步显著！\n注意力从{early_avg}提升到{recent_avg}\n提升了{int(improvement)}%"
        elif improvement > 10:
            return f"📈 持续进步！\n注意力从{early_avg}提升到{recent_avg}\n提升了{int(improvement)}%"
        elif improvement > 5:
            return f"✨ 稳步提升\n注意力从{early_avg}提升到{recent_avg}\n提升了{int(improvement)}%"
        elif improvement > 0:
            return f"🌱 略有进步\n注意力从{early_avg}到{recent_avg}\n提升{int(improvement)}%"
        elif improvement > -5:
            return f"⚖️ 保持稳定\n注意力从{early_avg}到{recent_avg}\n基本持平"
        elif improvement > -10:
            return f"📉 有所下降\n注意力从{early_avg}降至{recent_avg}\n下降{int(-improvement)}%"
        else:
            return f"⚠️ 需要加油\n注意力从{early_avg}降至{recent_avg}\n下降{int(-improvement)}%"

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
            records = GlobalSettings().training_records()
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