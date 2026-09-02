# ui/achievement_dialog.py - 简化版本（不使用信号自动刷新）

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QProgressBar, QWidget

from core.achievement_manager import AchievementManager
from core.settings import GlobalSettings


class AchievementDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("成就")
        self.setMinimumSize(600, 600)
        self.resize(700, 650)

        self._loading = False

        self._setup_ui()

        # 连接成就解锁信号（仅在成就解锁时刷新）
        am = AchievementManager()
        am.achievement_unlocked.connect(self._on_achievement_unlocked)

        settings = GlobalSettings()
        settings.settings_changed.connect(self._apply_style_sheet)

        self._apply_style_sheet()
        # 打开时至少容纳布局所需高度，避免底部内容（列表/关闭按钮）被裁剪。
        min_h = self.layout().minimumSize().height()
        if min_h > self.height():
            self.resize(self.width(), min_h)

        # 延迟加载
        QTimer.singleShot(50, self._load_achievements)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
        super().keyPressEvent(event)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        title = QLabel("🏆 成就系统")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: bold; margin: 15px;")
        layout.addWidget(title)

        self._summary_label = QLabel()
        self._summary_label.setAlignment(Qt.AlignCenter)
        self._summary_label.setStyleSheet("font-size: 16px; margin: 10px;")
        layout.addWidget(self._summary_label)

        self._list_widget = QListWidget()
        self._list_widget.setMinimumHeight(450)
        self._list_widget.setSpacing(8)
        layout.addWidget(self._list_widget)

        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(120, 45)
        close_btn.setStyleSheet("font-size: 16px;")
        close_btn.clicked.connect(self.accept)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _load_achievements(self):
        """加载成就列表"""
        if self._loading:
            return

        self._loading = True

        try:
            self._list_widget.clear()

            am = AchievementManager()
            # 确保数据已加载
            am.load_current_user_data()

            groups = am.achievement_groups()
            achievements = am.get_all_achievements()
            unlocked_count = am.get_unlocked_count()
            total_count = am.get_total_count()

            settings = GlobalSettings()
            night_mode = settings.night_mode()
            text_color = settings.text_color().name()
            bg_color = settings.background_color().name()

            locked_color = "#888888" if night_mode else "#999999"
            border_color = "#555555" if night_mode else "#cccccc"

            self._summary_label.setText(f"已解锁 {unlocked_count} / {total_count} 项成就")
            self._summary_label.setStyleSheet(f"font-size: 16px; margin: 10px; color: {text_color};")

            # 使用临时列表构建，然后一次性添加到界面；按两大板块分组展示
            items = []

            for group_name, group_achievements in groups:
                header_item = QListWidgetItem(self._list_widget)
                header_item.setText(group_name)
                header_item.setFlags(Qt.ItemIsEnabled)
                header_item.setSizeHint(header_item.sizeHint())
                header_item.setForeground(QColor(76, 175, 80))
                header_item.setTextAlignment(Qt.AlignCenter)
                items.append((header_item, None))
                for ach in group_achievements:
                    item_widget = QWidget()
                    item_widget.setStyleSheet(f"background-color: {bg_color}; border-radius: 8px;")

                    item_layout = QHBoxLayout(item_widget)
                    item_layout.setContentsMargins(12, 10, 12, 10)

                    text_widget = QWidget()
                    text_layout = QVBoxLayout(text_widget)
                    text_layout.setSpacing(5)

                    icon = self._get_achievement_icon(ach.unlocked, ach.name)
                    name_color = text_color if ach.unlocked else locked_color

                    name_label = QLabel(f"{icon} {ach.name}")
                    name_label.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {name_color}; background: transparent;")
                    text_layout.addWidget(name_label)

                    desc_label = QLabel(ach.description)
                    desc_label.setStyleSheet(f"font-size: 12px; color: {locked_color}; background: transparent;")
                    desc_label.setWordWrap(True)
                    text_layout.addWidget(desc_label)

                    item_layout.addWidget(text_widget, 2)

                    status_widget = QWidget()
                    status_layout = QVBoxLayout(status_widget)
                    status_layout.setSpacing(5)

                    if ach.unlocked:
                        unlock_label = QLabel("✓ 已解锁")
                        unlock_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 13px; background: transparent;")
                        unlock_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        status_layout.addWidget(unlock_label)

                        time_label = QLabel(ach.unlock_time.toString("MM-dd hh:mm") if ach.unlock_time else "")
                        time_label.setStyleSheet(f"color: {locked_color}; font-size: 11px; background: transparent;")
                        time_label.setAlignment(Qt.AlignRight)
                        status_layout.addWidget(time_label)
                    else:
                        progress_bar = QProgressBar()
                        progress_bar.setRange(0, 100)
                        progress_bar.setValue(ach.progress)
                        progress_bar.setTextVisible(False)
                        progress_bar.setFixedHeight(10)
                        progress_bar.setStyleSheet(
                            f"QProgressBar {{ border: none; background-color: #3a3a3a; border-radius: 5px; }}"
                            f"QProgressBar::chunk {{ background-color: #4CAF50; border-radius: 5px; }}"
                        )
                        status_layout.addWidget(progress_bar)

                        progress_label = QLabel(ach.progress_text)
                        progress_label.setStyleSheet(f"color: {locked_color}; font-size: 12px; background: transparent;")
                        progress_label.setAlignment(Qt.AlignRight)
                        status_layout.addWidget(progress_label)

                    item_layout.addWidget(status_widget, 1)

                    list_item = QListWidgetItem(self._list_widget)
                    list_item.setSizeHint(item_widget.sizeHint())
                    items.append((list_item, item_widget))

            # 批量添加（板块标题不设置控件）
            for list_item, item_widget in items:
                self._list_widget.addItem(list_item)
                if item_widget is not None:
                    self._list_widget.setItemWidget(list_item, item_widget)

            self._list_widget.setStyleSheet(
                f"QListWidget {{ background-color: {bg_color}; border: none; outline: none; }}"
                f"QListWidget::item {{ background-color: transparent; border-bottom: 1px solid {border_color}; }}"
            )

            # 强制处理事件
            QTimer.singleShot(10, self._list_widget.repaint)

        except Exception as e:
            print(f"AchievementDialog: Error loading achievements: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._loading = False

    def _get_achievement_icon(self, unlocked: bool, name: str) -> str:
        if not unlocked:
            return "🔒"

        icons = {
            "找茬新手": "🔍",
            "火眼金睛": "👁️",
            "连击新星": "⚡",
            "完美连击": "⚡",
            "高分突破": "🏆",
            "找茬大师": "👑",
            "完美游戏": "💎",
            "追踪新手": "🎯",
            "弹无虚发": "🎯",
            "反应神速": "⚡",
            "精准路径": "🧭",
            "追踪突破": "🏆",
            "追踪大师": "👑",
            "完美追踪": "💎",
            "专注达人": "🧠",
            "坚持之星": "🕒",
            "高频训练": "🔥"
        }

        for key, icon in icons.items():
            if key in name:
                return icon
        return "🏆"

    def _on_achievement_unlocked(self, name: str):
        """成就解锁时刷新列表"""
        QTimer.singleShot(100, self._load_achievements)

    def _apply_style_sheet(self):
        """应用样式"""
        settings = GlobalSettings()
        bg = settings.background_color().name()
        text = settings.text_color().name()
        night_mode = settings.night_mode()
        border_color = "#555555" if night_mode else "#cccccc"

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text}; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 8px; padding: 8px 20px; font-size: 16px; }}
            QPushButton:hover {{ background-color: #45a049; }}
        """)

    def showEvent(self, event):
        """对话框显示时刷新数据"""
        super().showEvent(event)
        # 每次显示时刷新
        if not self._loading:
            QTimer.singleShot(50, self._load_achievements)