# ui/mode_select_dialog.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel, QTextEdit, QHBoxLayout, QScrollArea, QWidget

from core.settings import GlobalSettings


class ModeSelectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择游戏模式")
        self.setMinimumSize(350, 350)
        self.resize(400, 380)

        self._mode = "find_difference"

        self._setup_ui()
        self._apply_style_sheet()

        settings = GlobalSettings()
        settings.settings_changed.connect(self._apply_style_sheet)

    def selected_mode(self) -> str:
        return self._mode

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        label = QLabel("请选择游戏模式：")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        btn_style = "font-size: 16px; padding: 12px;"

        btn_find = QPushButton("🔍 找茬模式")
        btn_find.setStyleSheet(btn_style)
        btn_find.clicked.connect(lambda: self._on_button_clicked("find_difference"))

        btn_track = QPushButton("🎯 动态追踪模式")
        btn_track.setStyleSheet(btn_style)
        btn_track.clicked.connect(lambda: self._on_button_clicked("dynamic_tracking"))

        layout.addWidget(btn_find)
        layout.addWidget(btn_track)

        layout.addSpacing(10)

        # 底部按钮行
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        # 模式说明按钮
        self._info_btn = QPushButton("📖 模式说明")
        self._info_btn.setStyleSheet("font-size: 14px; padding: 10px 20px; background-color: #2196F3;")
        self._info_btn.clicked.connect(self._show_mode_info)

        bottom_layout.addStretch()
        bottom_layout.addWidget(self._info_btn)
        bottom_layout.addStretch()

        layout.addLayout(bottom_layout)

    def _on_button_clicked(self, mode: str):
        self._mode = mode
        self.accept()

    def _show_mode_info(self):
        """显示模式说明对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("📖 游戏模式说明")
        dialog.setMinimumSize(500, 450)
        dialog.resize(550, 500)
        dialog.setModal(True)

        settings = GlobalSettings()
        night_mode = settings.night_mode()
        text_color = settings.text_color().name()
        bg_color = settings.background_color().name()
        text_edit_bg = "#3a3a3a" if night_mode else "#ffffff"

        dialog.setStyleSheet(f"""
            QDialog {{ background-color: {bg_color}; }}
            QLabel {{ color: {text_color}; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 5px; padding: 8px 20px; font-size: 14px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QTextEdit {{ background-color: {text_edit_bg}; color: {text_color};
                border: 2px solid #4CAF50; border-radius: 8px;
                font-size: 14px; padding: 15px; }}
        """)

        layout = QVBoxLayout(dialog)

        title = QLabel("🎮 游戏模式说明")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: 22px; font-weight: bold; padding: 10px; color: {text_color};")
        layout.addWidget(title)

        # 使用 ScrollArea 使内容可滚动
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(20)

        # 找茬模式说明
        find_group = QLabel()
        find_group.setTextFormat(Qt.RichText)
        find_group.setText("""
            <h2 style="color: #4CAF50;">🔍 找茬模式</h2>
            <p><b>🎯 目标：</b>在右侧区域找到并点击所有隐藏的差异点。</p>
            <p><b>🎮 玩法：</b></p>
            <ul>
                <li>屏幕分为左右两个区域，左侧为参考区，右侧为游戏区</li>
                <li>右侧区域会随机出现红色/黄色的差异点</li>
                <li>用鼠标点击差异点即可消除它</li>
                <li>每找到一个差异点即可获得分数</li>
            </ul>
            <p><b>💡 技巧：</b></p>
            <ul>
                <li>保持注意力集中，快速扫描屏幕</li>
                <li>注意力分数越高，越容易发现隐藏的点</li>
                <li>连续找到差异点可获得连击奖励</li>
            </ul>
            <p><b>🏆 适合人群：</b>初学者、需要提升视觉搜索能力的人</p>
            <hr>
        """)
        find_group.setWordWrap(True)
        content_layout.addWidget(find_group)

        # 动态追踪模式说明
        track_group = QLabel()
        track_group.setTextFormat(Qt.RichText)
        track_group.setText("""
            <h2 style="color: #FF9800;">🎯 动态追踪模式</h2>
            <p><b>🎯 目标：</b>用鼠标光标追踪并命中不断移动的红色目标。</p>
            <p><b>🎮 玩法：</b></p>
            <ul>
                <li>屏幕中会有一个红色圆点目标不断移动</li>
                <li>将鼠标光标移动到目标上即可命中</li>
                <li>每次命中目标后，目标会移动到新的位置</li>
                <li>命中的速度越快，获得的分数越高</li>
            </ul>
            <p><b>💡 技巧：</b></p>
            <ul>
                <li>预测目标的移动轨迹，提前移动鼠标</li>
                <li>保持手眼协调，快速反应</li>
                <li>注意力越集中，追踪速度越快</li>
            </ul>
            <p><b>🏆 适合人群：</b>进阶玩家、需要提升反应速度和手眼协调能力的人</p>
            <hr>
        """)
        track_group.setWordWrap(True)
        content_layout.addWidget(track_group)

        # 共同说明
        common_group = QLabel()
        common_group.setTextFormat(Qt.RichText)
        common_group.setText("""
            <h2 style="color: #9C27B0;">📊 通用机制</h2>
            <p><b>🧠 注意力评分：</b></p>
            <ul>
                <li>通过摄像头实时监测您的眨眼频率和注视专注度</li>
                <li>注意力分数越高，代表您越专注</li>
                <li>注意力分数会影响游戏难度和反馈</li>
            </ul>
            <p><b>👀 注视专注度：</b></p>
            <ul>
                <li>追踪您的视线是否集中在屏幕中心区域</li>
                <li>视线越集中，注视专注度分数越高</li>
                <li>保持良好的坐姿和视线习惯</li>
            </ul>
            <p><b>🏅 成就系统：</b></p>
            <ul>
                <li>完成特定目标可解锁成就徽章</li>
                <li>成就包括：注意力大师、火眼金睛、完美连击等</li>
                <li>收集所有成就，成为真正的注意力大师！</li>
            </ul>
        """)
        common_group.setWordWrap(True)
        content_layout.addWidget(common_group)

        # 提示
        tip_label = QLabel("💡 提示：建议新手从找茬模式开始，熟悉后再尝试动态追踪模式。")
        tip_label.setWordWrap(True)
        tip_label.setStyleSheet(f"font-size: 13px; color: #888888; padding: 10px; background-color: rgba(76,175,80,0.1); border-radius: 8px;")
        content_layout.addWidget(tip_label)

        content_layout.addStretch()
        scroll.setWidget(content_widget)
        layout.addWidget(scroll)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(120)
        close_btn.clicked.connect(dialog.accept)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        dialog.exec()

    def _apply_style_sheet(self):
        settings = GlobalSettings()
        bg = settings.background_color().name()
        text = settings.text_color().name()

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text}; font-size: 14px; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 8px; padding: 12px; font-size: 16px; }}
            QPushButton:hover {{ background-color: #45a049; }}
        """)