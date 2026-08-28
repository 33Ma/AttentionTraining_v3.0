# ui/teacher_report_dialog.py
import os
from datetime import datetime
from typing import List, Dict
from PySide6.QtCore import Qt, QDateTime, QDate, QTime, QFile, QIODevice, QTextStream
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QHeaderView, QMessageBox, QFileDialog,
    QWidget, QSplitter, QTableWidgetItem, QGroupBox, QTextEdit, QDialogButtonBox
)
from PySide6.QtCharts import QChartView, QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis, QChart

from core.user_manager import UserManager, UserRole
from core.settings import GlobalSettings, TrainingRecord
from core.user_session import UserSession
from core.paths import app_data_dir
from ai.teacher_report_logic import (
    composite_improvement,
    compute_class_stats,
    compute_class_summaries,
    format_duration,
    normalized_game_score,
)

from ui.teacher_coach_dialog import TeacherCoachDialog


class TeacherReportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 班级训练报告")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        self._summaries = []
        self._current_student = ""
        self._class_avg_label = None
        self._top_student_label = None
        self._total_hours_label = None
        self._total_trainings_label = None

        self._setup_ui()
        self._refresh_report()

        settings = GlobalSettings()
        settings.settings_changed.connect(self._apply_style_sheet)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 标题
        title = QLabel("📊 班级训练报告")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: bold; padding: 15px;")
        main_layout.addWidget(title)

        # 控制栏
        control_layout = QHBoxLayout()
        control_layout.setSpacing(15)

        range_label = QLabel("时间范围:")
        self._date_range_combo = QComboBox()
        self._date_range_combo.addItem("全部记录", 0)
        self._date_range_combo.addItem("最近7天", 7)
        self._date_range_combo.addItem("最近30天", 30)
        self._date_range_combo.addItem("本月", -1)
        self._date_range_combo.addItem("上月", -2)
        self._date_range_combo.setFixedWidth(120)
        self._date_range_combo.currentIndexChanged.connect(self._on_date_range_changed)

        self._refresh_btn = QPushButton("🔄 刷新")
        self._refresh_btn.setFixedSize(100, 38)
        self._refresh_btn.clicked.connect(self._refresh_report)

        self._export_btn = QPushButton("📎 导出CSV")
        self._export_btn.setFixedSize(120, 38)
        self._export_btn.clicked.connect(self._export_to_csv)

        self._class_report_btn = QPushButton("📈 生成班级报告")
        self._class_report_btn.setFixedSize(140, 38)
        self._class_report_btn.clicked.connect(self._on_generate_class_report)
        self._coach_btn = QPushButton("🤖 咨询AI助教")
        self._coach_btn.setFixedSize(140, 38)
        self._coach_btn.clicked.connect(self._on_ask_coach)

        control_layout.addWidget(range_label)
        control_layout.addWidget(self._date_range_combo)
        control_layout.addStretch()
        control_layout.addWidget(self._refresh_btn)
        control_layout.addWidget(self._export_btn)
        control_layout.addWidget(self._class_report_btn)
        control_layout.addWidget(self._coach_btn)
        main_layout.addLayout(control_layout)

        # 统计卡片
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(20)

        self._class_avg_card = self._create_stat_card("📊 班级平均注意力", "0")
        self._top_student_card = self._create_stat_card("🏆 进步之星", "暂无")
        self._total_hours_card = self._create_stat_card("⏱️ 总训练时长", "0分钟")
        self._total_trainings_card = self._create_stat_card("🎯 总训练次数", "0次")

        stats_layout.addWidget(self._class_avg_card)
        stats_layout.addWidget(self._top_student_card)
        stats_layout.addWidget(self._total_hours_card)
        stats_layout.addWidget(self._total_trainings_card)
        main_layout.addLayout(stats_layout)

        # 分割器
        splitter = QSplitter(Qt.Vertical)

        # 学生列表
        student_list_widget = QWidget()
        student_list_layout = QVBoxLayout(student_list_widget)
        student_list_layout.setContentsMargins(0, 0, 0, 0)

        student_list_label = QLabel("👥 学生列表")
        student_list_label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 5px 0;")
        student_list_layout.addWidget(student_list_label)

        self._student_table = QTableWidget()
        self._student_table.setColumnCount(10)
        self._student_table.setHorizontalHeaderLabels([
            "学生姓名", "训练次数", "总时长", "平均注意力",
            "最高注意力", "平均得分(0-100)", "成就数", "进步趋势", "最近训练", "平均综合分"
        ])
        self._student_table.horizontalHeader().setStretchLastSection(True)
        self._student_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._student_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._student_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._student_table.setAlternatingRowColors(True)
        self._student_table.setMinimumHeight(200)
        self._student_table.setMaximumHeight(280)
        self._student_table.itemClicked.connect(
            lambda item: self._on_student_selected(item.row()) if item else None
        )

        student_list_layout.addWidget(self._student_table)
        splitter.addWidget(student_list_widget)

        # 详细报告
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)

        detail_header_layout = QHBoxLayout()
        detail_label = QLabel("📈 学生详细报告")
        detail_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        detail_header_layout.addWidget(detail_label)
        detail_header_layout.addStretch()

        student_select_label = QLabel("选择学生:")
        self._student_combo = QComboBox()
        self._student_combo.setFixedWidth(150)
        self._student_combo.currentIndexChanged.connect(self._on_student_combo_changed)

        detail_header_layout.addWidget(student_select_label)
        detail_header_layout.addWidget(self._student_combo)
        detail_layout.addLayout(detail_header_layout)

        self._detail_table = QTableWidget()
        self._detail_table.setColumnCount(6)
        self._detail_table.setHorizontalHeaderLabels([
            "训练时间", "时长", "游戏模式", "注意力分数", "眨眼次数", "游戏得分(0-100)"
        ])
        self._detail_table.horizontalHeader().setStretchLastSection(True)
        self._detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._detail_table.setMinimumHeight(180)
        self._detail_table.setMaximumHeight(220)
        detail_layout.addWidget(self._detail_table)

        # 图表
        chart_label = QLabel("📊 注意力分数对比")
        chart_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px 0 5px 0;")
        detail_layout.addWidget(chart_label)

        self._trend_chart = QChartView()
        self._trend_chart.setRenderHint(QPainter.Antialiasing)
        self._trend_chart.setMinimumHeight(280)
        detail_layout.addWidget(self._trend_chart)

        splitter.addWidget(detail_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)

        main_layout.addWidget(splitter, 1)

        # 关闭按钮
        btn_layout = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(120, 45)
        close_btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        close_btn.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        self._apply_style_sheet()

    def _create_stat_card(self, title: str, value: str) -> QWidget:
        card = QWidget()
        card.setStyleSheet("QWidget { border-radius: 12px; background-color: rgba(76, 175, 80, 0.1); }")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setObjectName("valueLabel")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setWordWrap(True)
        value_label.setStyleSheet("font-size: 28px; font-weight: bold;")
        layout.addWidget(value_label)

        # 存储引用以便更新
        if title == "📊 班级平均注意力":
            self._class_avg_label = value_label
        elif title == "🏆 进步之星":
            self._top_student_label = value_label
        elif title == "⏱️ 总训练时长":
            self._total_hours_label = value_label
        elif title == "🎯 总训练次数":
            self._total_trainings_label = value_label

        return card

    def _load_student_list(self):
        user_manager = UserManager()
        students = []

        if user_manager.current_user_role() == UserRole.ADMIN:
            students = user_manager.get_students()
        elif user_manager.current_user_role() == UserRole.TEACHER:
            students = user_manager.get_students_by_teacher(user_manager.current_username())

        records_map = {}
        achievements_map = {}
        session = UserSession()
        for student in students:
            username = student.username
            try:
                records_map[username] = [
                    r.to_dict()
                    for r in session.get_user_training_records(username)
                ]
            except Exception:
                records_map[username] = []
            achievements_map[username] = self._count_achievements(username)

        filter_days = self._date_range_combo.currentData()
        summaries, stats = compute_class_summaries(
            students, records_map,
            filter_days=filter_days,
            achievements_map=achievements_map,
        )
        self._summaries = summaries
        self._student_combo.clear()

        if not summaries:
            self._student_table.setRowCount(0)
            self._detail_table.setRowCount(0)
            self._update_comparison_chart()
            self._class_avg_label.setText("0")
            self._total_trainings_label.setText("0次")
            self._total_hours_label.setText("0分钟")
            self._top_student_label.setText("暂无数据")
            return

        self._student_table.setRowCount(len(summaries))

        for i, summary in enumerate(summaries):
            self._student_combo.addItem(summary['display_name'], summary['name'])
            self._student_table.setItem(i, 0, QTableWidgetItem(summary['display_name']))
            self._student_table.setItem(i, 1, QTableWidgetItem(str(summary['total_trainings'])))
            self._student_table.setItem(i, 2, QTableWidgetItem(format_duration(summary['total_minutes'])))
            self._student_table.setItem(i, 3, QTableWidgetItem(str(summary['avg_attention'])))
            self._student_table.setItem(i, 4, QTableWidgetItem(str(summary['max_attention'])))
            self._student_table.setItem(i, 5, QTableWidgetItem(str(summary['avg_game_score'])))
            self._student_table.setItem(i, 6, QTableWidgetItem(str(summary['achievements'])))

            trend_text = "➡️ 0%"
            if summary['improvement'] > 0:
                trend_text = f"📈 +{int(summary['improvement'])}%"
            elif summary['improvement'] < 0:
                trend_text = f"📉 {int(summary['improvement'])}%"
            trend_item = QTableWidgetItem(trend_text)
            if summary['improvement'] > 0:
                trend_item.setForeground(QColor(76, 175, 80))
            elif summary['improvement'] < 0:
                trend_item.setForeground(QColor(244, 67, 54))
            self._student_table.setItem(i, 7, trend_item)
            self._student_table.setItem(i, 8, QTableWidgetItem(summary['last_training']))

            composite_item = QTableWidgetItem(str(summary['avg_composite']))
            if summary['avg_composite'] >= 80:
                composite_item.setForeground(QColor(76, 175, 80))
            elif summary['avg_composite'] >= 50:
                composite_item.setForeground(QColor(255, 152, 0))
            else:
                composite_item.setForeground(QColor(244, 67, 54))
            self._student_table.setItem(i, 9, composite_item)

        self._class_avg_label.setText(str(stats['class_avg_attention']))
        self._total_trainings_label.setText(f"{stats['total_trainings']}次")
        self._total_hours_label.setText(format_duration(stats['total_minutes']))
        top = stats['top_improvement_student']
        if top:
            self._top_student_label.setText(f"{top['display_name']} (+{int(top['improvement'])}%)")
        else:
            self._top_student_label.setText("暂无数据")

    @staticmethod
    def _count_achievements(username: str) -> int:
        try:
            import json
            path = os.path.join(
                app_data_dir(), "users", username, "achievements.json"
            )
            if not os.path.exists(path):
                return 0
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return sum(
                1 for a in data.get('achievements', []) if a.get('unlocked', False)
            )
        except Exception:
            return 0

    def _on_student_combo_changed(self, index: int):
        if index < 0:
            self._clear_student_detail()
            return
        username = self._student_combo.itemData(index) or ""
        self._current_student = username
        self._update_student_detail(username)

    def _clear_student_detail(self):
        if hasattr(self, "_detail_table") and self._detail_table is not None:
            self._detail_table.setRowCount(0)
        chart = QChart()
        chart.setTitle("暂无数据")
        self._trend_chart.setChart(chart)

    def _update_student_detail(self, student_username: str):
        username = student_username or ""
        if not username:
            self._clear_student_detail()
            return

        records = UserSession().get_user_training_records(username)

        filter_days = self._date_range_combo.currentData()
        filter_date = QDateTime.currentDateTime()

        if filter_days > 0:
            filter_date = filter_date.addDays(-filter_days)
        elif filter_days == -1:
            filter_date = QDateTime(QDate.currentDate().addDays(1 - QDate.currentDate().day()), QTime(0, 0))
        elif filter_days == -2:
            last_month = QDate.currentDate().addMonths(-1)
            filter_date = QDateTime(QDate(last_month.year(), last_month.month(), 1), QTime(0, 0))

        filtered_records = [r for r in records if filter_days == 0 or r.date_time >= filter_date]

        self._detail_table.setRowCount(len(filtered_records))

        for i, record in enumerate(filtered_records):
            self._detail_table.setItem(i, 0, QTableWidgetItem(record.date_time.toString("MM-dd HH:mm")))
            self._detail_table.setItem(i, 1, QTableWidgetItem(f"{record.duration_minutes}分钟"))

            mode_str = "找茬模式" if record.game_mode == "find_difference" else "动态追踪模式"
            self._detail_table.setItem(i, 2, QTableWidgetItem(mode_str))

            att_item = QTableWidgetItem(str(record.avg_attention_score))
            if record.avg_attention_score >= 70:
                att_item.setForeground(QColor(76, 175, 80))
            elif record.avg_attention_score >= 40:
                att_item.setForeground(QColor(255, 152, 0))
            else:
                att_item.setForeground(QColor(244, 67, 54))
            self._detail_table.setItem(i, 3, att_item)

            self._detail_table.setItem(i, 4, QTableWidgetItem(str(record.total_blinks)))
            self._detail_table.setItem(
                i, 5,
                QTableWidgetItem(str(int(round(self._normalized_game_score(record))))),
            )

        if not filtered_records:
            self._detail_table.setRowCount(1)
            self._detail_table.setSpan(0, 0, 1, 6)
            empty_item = QTableWidgetItem("空")
            empty_item.setTextAlignment(Qt.AlignCenter)
            self._detail_table.setItem(0, 0, empty_item)

        self._update_comparison_chart()

    def _update_comparison_chart(self):
        if not self._summaries:
            chart = QChart()
            chart.setTitle("暂无数据")
            self._trend_chart.setChart(chart)
            return

        chart = QChart()
        settings = GlobalSettings()
        theme = QChart.ChartThemeDark if settings.night_mode() else QChart.ChartThemeLight
        chart.setTheme(theme)
        chart.setTitle("学生综合评分对比")

        # 修复：使用 QFont 对象
        title_font = QFont("Arial", 16, QFont.Bold)
        chart.setTitleFont(title_font)

        chart.setAnimationOptions(QChart.SeriesAnimations)

        series = QBarSeries()
        bar_set = QBarSet("平均综合分")
        bar_set.setColor(QColor(76, 175, 80))

        categories = []
        for summary in self._summaries:
            bar_set.append(summary['avg_composite'])
            display_name = summary['display_name']
            if len(display_name) > 10:
                display_name = display_name[:8] + ".."
            categories.append(display_name)

        series.append(bar_set)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_x.setTitleText("学生")
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(0, 100)
        axis_y.setTitleText("综合评分")
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)

        self._trend_chart.setChart(chart)

    def _refresh_report(self):
        self._load_student_list()
        if self._summaries and self._student_combo.count() > 0:
            self._update_student_detail(self._student_combo.currentData() or "")
        else:
            self._clear_student_detail()

    def _on_student_selected(self, row: int):
        if 0 <= row < len(self._summaries):
            self._current_student = self._summaries[row]['name']
            index = self._student_combo.findData(self._current_student)
            if index >= 0:
                self._student_combo.setCurrentIndex(index)

    def _on_date_range_changed(self, index: int):
        self._refresh_report()
    def _on_ask_coach(self):
        """携带当前班级汇总打开 AI 助教。"""
        if not self._summaries:
            QMessageBox.information(self, "提示", "暂无学生数据，无法咨询助教。")
            return
        stats = compute_class_stats(self._summaries)
        dlg = TeacherCoachDialog(
            self,
            class_context={"summaries": self._summaries, "stats": stats},
        )
        dlg.exec()

    def _export_to_csv(self):
        file_name = QFileDialog.getSaveFileName(
            self, "导出班级报告",
            f"班级报告_{QDate.currentDate().toString('yyyyMMdd')}.csv",
            "CSV文件 (*.csv);;所有文件 (*)"
        )[0]

        if not file_name:
            return

        file = QFile(file_name)
        if not file.open(QIODevice.WriteOnly):
            QMessageBox.warning(self, "导出失败", "无法创建文件")
            return

        stream = QTextStream(file)
        stream.setEncoding(QTextStream.Utf8)

        # 写入头部
        stream << "========== 班级训练报告 ==========\n"
        stream << f"生成时间: {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')}\n"
        stream << f"总学生数: {len(self._summaries)}人\n\n"

        # 写入数据
        stream << "学生姓名,训练次数,总时长(分钟),平均注意力,最高注意力,平均得分(0-100),成就数,进步趋势,平均综合分,最近训练时间\n"

        for summary in self._summaries:
            stream << f"{summary['display_name']},"
            stream << f"{summary['total_trainings']},"
            stream << f"{summary['total_minutes']},"
            stream << f"{summary['avg_attention']},"
            stream << f"{summary['max_attention']},"
            stream << f"{summary['avg_game_score']},"
            stream << f"{summary['achievements']},"
            stream << f"{summary['improvement']:.1f}%,"
            stream << f"{summary['avg_composite']},"
            stream << f"{summary['last_training']}\n"

        file.close()

        QMessageBox.information(self, "导出成功", f"报告已导出到:\n{file_name}")

    def _on_generate_class_report(self):
        if not self._summaries:
            QMessageBox.information(self, "提示", "暂无学生数据，无法生成班级报告。")
            return

        total_students = len(self._summaries)
        total_trainings = sum(s['total_trainings'] for s in self._summaries)
        total_minutes = sum(s['total_minutes'] for s in self._summaries)
        total_attention = sum(s['avg_attention'] for s in self._summaries)
        total_scores = sum(s['avg_game_score'] for s in self._summaries)
        total_composite = sum(s['avg_composite'] for s in self._summaries)
        total_achievements = sum(s['achievements'] for s in self._summaries)

        improving = sum(1 for s in self._summaries if s['improvement'] > 5)
        declining = sum(1 for s in self._summaries if s['improvement'] < -5)

        best = max(self._summaries, key=lambda s: s['avg_composite'])
        worst = min(self._summaries, key=lambda s: s['avg_composite'])

        class_avg = total_attention // total_students if total_students > 0 else 0
        class_composite = total_composite // total_students if total_students > 0 else 0

        report = f"""
╔════════════════════════════════════════════════════════════════╗
║                      📊 班级训练报告                            ║
╚════════════════════════════════════════════════════════════════╝

📅 生成时间: {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 班级概况
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  👥 学生总数: {total_students} 人
  🎯 总训练次数: {total_trainings} 次
  ⏱️  总训练时长: {total_minutes} 分钟 ({total_minutes / 60:.1f} 小时)
  🧠 班级平均注意力: {class_avg} 分
  🎮 班级平均游戏得分(0-100): {total_scores // total_students if total_students > 0 else 0} 分
  🎯 班级平均综合分: {total_composite // total_students if total_students > 0 else 0} 分
  🏆 总成就数: {total_achievements} 个

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 进步分析
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📈 进步学生: {improving} 人 ({improving / total_students * 100:.0f}%)
  📉 退步学生: {declining} 人 ({declining / total_students * 100:.0f}%)
  ➡️ 稳定学生: {total_students - improving - declining} 人

  🏅 最佳表现: {best['display_name']} (综合分 {best['avg_composite']})
  📝 需要关注: {worst['display_name']} (综合分 {worst['avg_composite']})

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 教学建议
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        if class_composite < 50:
            report += "  🔴 班级综合水平偏低: 建议增加基础训练频率\n"
        elif class_composite < 70:
            report += "  🟡 班级综合水平中等: 可以通过游戏化元素提高参与度\n"
        else:
            report += "  🟢 班级综合水平优秀: 可以尝试更高难度的训练模式\n"

        if total_trainings < total_students * 3:
            report += "  📊 训练频率建议: 每周至少训练3-4次\n"

        if declining > total_students // 3:
            report += "  ⚠️ 退步学生较多: 建议分析原因并调整训练计划\n"

        report += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌟 总结
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        if improving > declining:
            report += "  🎉 班级整体呈现进步趋势！继续鼓励学生保持训练热情。\n"
        elif improving < declining:
            report += "  📝 班级近期表现有所下滑，建议分析原因并调整训练计划。\n"
        else:
            report += "  ⚖️ 班级整体保持稳定，可以通过增加挑战性来激发学生潜力。\n"

        # 显示报告
        dialog = QDialog(self)
        dialog.setWindowTitle("📊 班级报告")
        dialog.setMinimumSize(650, 550)
        dialog.resize(700, 600)

        settings = GlobalSettings()
        text_color = settings.text_color().name()
        night_mode = settings.night_mode()
        bg_color = "#2d2d2d" if night_mode else "#f5f5f5"
        text_edit_bg = "#3a3a3a" if night_mode else "#ffffff"

        dialog.setStyleSheet(f"""
            QDialog {{ background-color: {bg_color}; }}
            QLabel {{ color: {text_color}; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 5px; padding: 8px 15px; font-size: 13px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QTextEdit {{ background-color: {text_edit_bg}; color: {text_color};
                border: 2px solid #4CAF50; border-radius: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px; padding: 10px; }}
        """)

        layout = QVBoxLayout(dialog)

        title_label = QLabel("📊 班级训练报告")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(f"font-size: 20px; font-weight: bold; padding: 10px; color: {text_color};")
        layout.addWidget(title_label)

        text_edit = QTextEdit()
        text_edit.setPlainText(report)
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)

        dialog.exec()

    @staticmethod
    def _normalized_game_score(record) -> float:
        return normalized_game_score(record)

    @staticmethod
    def _composite_improvement(records) -> float:
        return composite_improvement(records)

    @staticmethod
    def _format_duration(minutes: int) -> str:
        return format_duration(minutes)

    def _apply_style_sheet(self):
        settings = GlobalSettings()
        bg = settings.background_color().name()
        text = settings.text_color().name()
        night_mode = settings.night_mode()

        table_bg = "#2d2d2d" if night_mode else "#ffffff"
        header_bg = "#3a3a3a" if night_mode else "#f0f0f0"
        border_color = "#555555" if night_mode else "#cccccc"

        # 更新统计卡片
        card_bg = "rgba(76, 175, 80, 0.15)" if night_mode else "rgba(76, 175, 80, 0.08)"
        value_color = "#ffffff" if night_mode else "#333333"
        title_color = "#cccccc" if night_mode else "#666666"

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text}; }}
            QTableWidget {{ background-color: {table_bg}; color: {text}; gridline-color: {border_color}; }}
            QTableWidget::item {{ padding: 8px; }}
            QTableWidget::item:selected {{ background-color: #4CAF50; color: white; }}
            QHeaderView::section {{ background-color: {header_bg}; color: {text}; padding: 10px; font-weight: bold; border: none; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none; border-radius: 8px; padding: 8px 15px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QComboBox {{ background-color: {table_bg}; color: {text}; border: 1px solid #4CAF50; border-radius: 5px; padding: 6px; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background-color: {table_bg}; color: {text}; }}
            QSplitter::handle {{ background-color: #4CAF50; }}
        """)

        # 更新卡片样式
        for card in [self._class_avg_card, self._top_student_card,
                     self._total_hours_card, self._total_trainings_card]:
            card.setStyleSheet(f"QWidget {{ background-color: {card_bg}; border-radius: 12px; }}")

        for label in self.findChildren(QLabel):
            if label.objectName() == "valueLabel":
                label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {value_color};")
            elif label.text() in ["📊 班级平均注意力", "🏆 进步之星", "⏱️ 总训练时长", "🎯 总训练次数"]:
                label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {title_color};")