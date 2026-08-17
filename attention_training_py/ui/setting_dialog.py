# ui/setting_dialog.py
import os
from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QDoubleSpinBox,
    QSlider, QRadioButton, QPushButton, QGroupBox, QListWidget, QStackedWidget,
    QCheckBox, QLineEdit, QMessageBox, QFileDialog, QWidget, QScrollArea,
    QListWidgetItem, QComboBox,QSpinBox
)

from core.settings import GlobalSettings, DifficultyLevel, CustomDifficulty
from core.user_manager import UserManager
from core.llm_client import LLMClient
from utils.wallpaper_manager import WallpaperManager


class SettingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("训练设置")
        self.setFixedSize(1100, 900)

        self._setup_ui()
        self._load_settings()
        self._apply_style_sheet()

        settings = GlobalSettings()
        settings.settings_changed.connect(self._apply_style_sheet)

    def _setup_ui(self):
        dialog_layout = QHBoxLayout(self)

        # 左侧导航
        self._nav_list = QListWidget()
        self._nav_list.setFixedWidth(150)
        self._nav_list.addItem("训练设置")
        self._nav_list.addItem("难度选择")
        self._nav_list.addItem("壁纸设置")
        self._nav_list.setCurrentRow(0)
        dialog_layout.addWidget(self._nav_list)

        # 右侧分页
        self._stacked_widget = QStackedWidget()
        dialog_layout.addWidget(self._stacked_widget, 1)

        self._setup_main_page()
        self._setup_difficulty_page()
        self._setup_wallpaper_page()

        self._stacked_widget.addWidget(self._main_page)
        self._stacked_widget.addWidget(self._difficulty_page)
        self._stacked_widget.addWidget(self._wallpaper_page)

        self._nav_list.currentRowChanged.connect(self._stacked_widget.setCurrentIndex)

    def _setup_main_page(self):
        self._main_page = QWidget()
        main_layout = QVBoxLayout(self._main_page)

        # EAR阈值
        ear_group = QGroupBox("闭眼检测阈值 (EAR)")
        ear_layout = QHBoxLayout(ear_group)
        ear_label = QLabel("阈值:")
        self._ear_spin = QDoubleSpinBox()
        self._ear_spin.setRange(0.1, 0.4)
        self._ear_spin.setSingleStep(0.01)
        self._ear_spin.setDecimals(2)
        ear_layout.addWidget(ear_label)
        ear_layout.addWidget(self._ear_spin)
        ear_layout.addStretch()
        main_layout.addWidget(ear_group)

        # 灵敏度
        sens_group = QGroupBox("眨眼灵敏度")
        sens_layout = QHBoxLayout(sens_group)
        sens_label = QLabel("低")
        self._sensitivity_slider = QSlider(Qt.Horizontal)
        self._sensitivity_slider.setRange(1, 10)
        sens_high = QLabel("高")
        sens_layout.addWidget(sens_label)
        sens_layout.addWidget(self._sensitivity_slider)
        sens_layout.addWidget(sens_high)
        main_layout.addWidget(sens_group)

        # 界面模式
        mode_group = QGroupBox("界面模式")
        mode_layout = QVBoxLayout(mode_group)
        self._day_mode_radio = QRadioButton("白天模式")
        self._night_mode_radio = QRadioButton("夜间模式")
        self._day_mode_radio.setChecked(True)
        mode_layout.addWidget(self._day_mode_radio)
        mode_layout.addWidget(self._night_mode_radio)
        main_layout.addWidget(mode_group)

        # AI设置
        ai_group = QGroupBox("🤖 AI智能助手")
        ai_layout = QVBoxLayout(ai_group)

        self._ai_enable_check = QCheckBox("启用AI智能分析")

        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(QLabel("API密钥:"))
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)
        self._api_key_edit.setPlaceholderText("请输入API密钥 (sk-...)")
        api_key_layout.addWidget(self._api_key_edit)

        api_url_layout = QHBoxLayout()
        api_url_layout.addWidget(QLabel("API地址:"))
        self._api_url_edit = QLineEdit()
        self._api_url_edit.setPlaceholderText("https://api.openai.com/v1/chat/completions")
        api_url_layout.addWidget(self._api_url_edit)

        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("模型名称:"))
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("gpt-3.5-turbo")
        model_layout.addWidget(self._model_edit)

        ai_layout.addWidget(self._ai_enable_check)
        ai_layout.addLayout(api_key_layout)
        ai_layout.addLayout(api_url_layout)
        ai_layout.addLayout(model_layout)
        main_layout.addWidget(ai_group)

        # 按钮
        btn_layout = QHBoxLayout()
        apply_btn = QPushButton("应用")
        cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(apply_btn)
        btn_layout.addWidget(cancel_btn)
        main_layout.addStretch()
        main_layout.addLayout(btn_layout)

        apply_btn.clicked.connect(self._apply_settings)
        cancel_btn.clicked.connect(self.reject)

    def _setup_difficulty_page(self):
        self._difficulty_page = QWidget()
        layout = QVBoxLayout(self._difficulty_page)

        preset_group = QGroupBox("难度预设")
        preset_layout = QVBoxLayout(preset_group)
        self._easy_radio = QRadioButton("简单（速度较慢，目标较大）")
        self._normal_radio = QRadioButton("普通")
        self._hard_radio = QRadioButton("困难（速度快，时间间隔随机）")
        self._custom_radio = QRadioButton("自定义难度")
        self._normal_radio.setChecked(True)

        preset_layout.addWidget(self._easy_radio)
        preset_layout.addWidget(self._normal_radio)
        preset_layout.addWidget(self._hard_radio)
        preset_layout.addWidget(self._custom_radio)
        layout.addWidget(preset_group)

        self._custom_group = QWidget()
        custom_layout = QVBoxLayout(self._custom_group)

        # 找茬模式参数
        spot_group = QGroupBox("找茬模式参数")
        spot_grid = QGridLayout(spot_group)
        spot_grid.addWidget(QLabel("点出现间隔(ms):"), 0, 0)
        self._spot_speed_spin = QSpinBox()
        self._spot_speed_spin.setRange(300, 5000)
        self._spot_speed_spin.setSingleStep(100)
        self._spot_speed_spin.setValue(1500)
        spot_grid.addWidget(self._spot_speed_spin, 0, 1)
        spot_grid.addWidget(QLabel("点的大小(像素):"), 1, 0)
        self._spot_size_spin = QSpinBox()
        self._spot_size_spin.setRange(10, 80)
        self._spot_size_spin.setValue(30)
        spot_grid.addWidget(self._spot_size_spin, 1, 1)
        self._spot_random_check = QCheckBox("时间间隔随机")
        spot_grid.addWidget(self._spot_random_check, 2, 0, 1, 2)
        custom_layout.addWidget(spot_group)

        # 动态追踪参数
        track_group = QGroupBox("动态追踪模式参数")
        track_grid = QGridLayout(track_group)
        track_grid.addWidget(QLabel("目标移动间隔(ms):"), 0, 0)
        self._track_speed_spin = QSpinBox()
        self._track_speed_spin.setRange(300, 5000)
        self._track_speed_spin.setSingleStep(100)
        self._track_speed_spin.setValue(1500)
        track_grid.addWidget(self._track_speed_spin, 0, 1)
        track_grid.addWidget(QLabel("目标大小(半径像素):"), 1, 0)
        self._track_size_spin = QSpinBox()
        self._track_size_spin.setRange(5, 50)
        self._track_size_spin.setValue(20)
        track_grid.addWidget(self._track_size_spin, 1, 1)
        self._track_random_check = QCheckBox("时间间隔随机")
        track_grid.addWidget(self._track_random_check, 2, 0, 1, 2)
        custom_layout.addWidget(track_group)

        layout.addWidget(self._custom_group)
        self._custom_group.setEnabled(False)

        self._custom_radio.toggled.connect(self._custom_group.setEnabled)

        # 按钮
        btn_layout = QHBoxLayout()
        apply_btn = QPushButton("应用")
        cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(apply_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addStretch()
        layout.addLayout(btn_layout)

        apply_btn.clicked.connect(self._apply_settings)
        cancel_btn.clicked.connect(self.reject)

    def _setup_wallpaper_page(self):
        self._wallpaper_page = QWidget()
        main_layout = QVBoxLayout(self._wallpaper_page)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 说明
        info_label = QLabel(
            "📷 静态壁纸设置\n\n"
            "支持格式: PNG, JPG, JPEG, BMP, GIF (静态)\n"
            "建议使用16:9比例图片以获得最佳显示效果"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 13px; color: #888888; padding: 12px; background-color: rgba(76,175,80,0.1); border-radius: 8px;")
        main_layout.addWidget(info_label)

        # 启用壁纸
        self._wallpaper_enable_check = QCheckBox("启用自定义壁纸")
        self._wallpaper_enable_check.setStyleSheet("font-size: 15px; font-weight: bold; padding: 5px;")
        main_layout.addWidget(self._wallpaper_enable_check)

        # 预览
        preview_group = QGroupBox("壁纸预览")
        preview_layout = QVBoxLayout(preview_group)

        scroll_area = QScrollArea()
        scroll_area.setFixedHeight(400)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self._wallpaper_preview_label = QLabel()
        self._wallpaper_preview_label.setAlignment(Qt.AlignCenter)
        self._wallpaper_preview_label.setMinimumSize(350, 280)
        self._wallpaper_preview_label.setStyleSheet(
            "border: 3px dashed #4CAF50; border-radius: 12px; "
            "background-color: rgba(76,175,80,0.08); padding: 15px; "
            "font-size: 14px; color: #888888;"
        )
        self._wallpaper_preview_label.setText("暂无壁纸\n\n点击下方「选择图片」按钮\n选择一张图片作为壁纸")

        scroll_area.setWidget(self._wallpaper_preview_label)
        preview_layout.addWidget(scroll_area)
        main_layout.addWidget(preview_group)

        # 路径显示
        path_group = QGroupBox("当前壁纸")
        path_layout = QHBoxLayout(path_group)
        self._wallpaper_path_label = QLabel("未选择")
        self._wallpaper_path_label.setWordWrap(True)
        self._wallpaper_path_label.setStyleSheet("font-size: 12px; color: #666666; padding: 5px; background-color: rgba(0,0,0,0.05); border-radius: 5px;")
        path_layout.addWidget(self._wallpaper_path_label, 1)
        main_layout.addWidget(path_group)

        # 按钮
        btn_layout = QHBoxLayout()
        self._select_wallpaper_btn = QPushButton("📁 选择图片")
        self._clear_wallpaper_btn = QPushButton("🗑️ 清除壁纸")
        self._preview_wallpaper_btn = QPushButton("👁️ 全屏预览")

        for btn in [self._select_wallpaper_btn, self._clear_wallpaper_btn, self._preview_wallpaper_btn]:
            btn.setFixedHeight(40)
            btn.setStyleSheet("font-size: 14px; font-weight: bold;")

        btn_layout.addStretch()
        btn_layout.addWidget(self._select_wallpaper_btn)
        btn_layout.addWidget(self._clear_wallpaper_btn)
        btn_layout.addWidget(self._preview_wallpaper_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # 训练设置
        training_group = QGroupBox("训练设置")
        training_layout = QVBoxLayout(training_group)
        self._force_standard_check = QCheckBox("训练时强制使用标准背景")
        self._force_standard_check.setToolTip("开启后，训练过程中将使用简洁的纯色背景，避免分散注意力")
        training_layout.addWidget(self._force_standard_check)

        hint_label = QLabel("💡 启用此选项后，训练时会自动切换到纯色背景，训练结束后恢复壁纸显示")
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("font-size: 11px; color: #888888; padding-left: 25px;")
        training_layout.addWidget(hint_label)
        main_layout.addWidget(training_group)

        # 底部按钮
        action_layout = QHBoxLayout()
        apply_btn = QPushButton("应用设置")
        cancel_btn = QPushButton("取消")
        apply_btn.setFixedSize(120, 45)
        cancel_btn.setFixedSize(100, 45)
        action_layout.addStretch()
        action_layout.addWidget(apply_btn)
        action_layout.addWidget(cancel_btn)
        action_layout.addStretch()
        main_layout.addLayout(action_layout)

        main_layout.addStretch()

        # 连接信号
        self._select_wallpaper_btn.clicked.connect(self._on_select_wallpaper)
        self._clear_wallpaper_btn.clicked.connect(self._on_clear_wallpaper)
        self._preview_wallpaper_btn.clicked.connect(self._on_wallpaper_preview)
        apply_btn.clicked.connect(self._apply_wallpaper_settings)
        cancel_btn.clicked.connect(self.reject)
        self._wallpaper_enable_check.toggled.connect(
            lambda checked: (
                self._select_wallpaper_btn.setEnabled(checked),
                self._clear_wallpaper_btn.setEnabled(checked),
                self._preview_wallpaper_btn.setEnabled(checked and bool(WallpaperManager().current_path()))
            )
        )

    def _load_settings(self):
        settings = GlobalSettings()

        self._ear_spin.setValue(settings.ear_threshold())
        self._sensitivity_slider.setValue(settings.sensitivity())
        self._night_mode_radio.setChecked(settings.night_mode())
        self._day_mode_radio.setChecked(not settings.night_mode())

        diff = settings.difficulty_level()
        if diff == DifficultyLevel.EASY:
            self._easy_radio.setChecked(True)
        elif diff == DifficultyLevel.NORMAL:
            self._normal_radio.setChecked(True)
        elif diff == DifficultyLevel.HARD:
            self._hard_radio.setChecked(True)
        elif diff == DifficultyLevel.CUSTOM:
            self._custom_radio.setChecked(True)

        cd = settings.custom_difficulty()
        self._spot_speed_spin.setValue(cd.spot_speed)
        self._spot_size_spin.setValue(cd.spot_size)
        self._spot_random_check.setChecked(cd.spot_random_interval)
        self._track_speed_spin.setValue(cd.track_speed)
        self._track_size_spin.setValue(cd.track_size)
        self._track_random_check.setChecked(cd.track_random_interval)

        self._ai_enable_check.setChecked(settings.ai_enabled())
        self._api_key_edit.setText(settings.api_key())
        self._api_url_edit.setText(settings.api_url())
        self._model_edit.setText(settings.ai_model())

        # 壁纸
        self._wallpaper_enable_check.setChecked(settings.wallpaper_enabled())
        self._force_standard_check.setChecked(settings.force_standard_bg_in_training())

        current_path = WallpaperManager().current_path()
        if current_path:
            self._wallpaper_path_label.setText(current_path)
            self._update_wallpaper_preview(current_path)
            self._preview_wallpaper_btn.setEnabled(True)
        else:
            self._wallpaper_path_label.setText("未选择")
            self._wallpaper_preview_label.setText("暂无壁纸\n\n点击下方「选择图片」按钮\n选择一张图片作为壁纸")
            self._preview_wallpaper_btn.setEnabled(False)

        self._select_wallpaper_btn.setEnabled(settings.wallpaper_enabled())
        self._clear_wallpaper_btn.setEnabled(settings.wallpaper_enabled())

    def _apply_settings(self):
        settings = GlobalSettings()

        settings.set_ear_threshold(self._ear_spin.value())
        settings.set_sensitivity(self._sensitivity_slider.value())
        settings.set_night_mode(self._night_mode_radio.isChecked())

        if self._easy_radio.isChecked():
            settings.set_difficulty_level(DifficultyLevel.EASY)
        elif self._normal_radio.isChecked():
            settings.set_difficulty_level(DifficultyLevel.NORMAL)
        elif self._hard_radio.isChecked():
            settings.set_difficulty_level(DifficultyLevel.HARD)
        elif self._custom_radio.isChecked():
            settings.set_difficulty_level(DifficultyLevel.CUSTOM)
            cd = CustomDifficulty()
            cd.spot_speed = self._spot_speed_spin.value()
            cd.spot_size = self._spot_size_spin.value()
            cd.spot_random_interval = self._spot_random_check.isChecked()
            cd.track_speed = self._track_speed_spin.value()
            cd.track_size = self._track_size_spin.value()
            cd.track_random_interval = self._track_random_check.isChecked()
            settings.set_custom_difficulty(cd)

        settings.set_ai_enabled(self._ai_enable_check.isChecked())
        settings.set_api_key(self._api_key_edit.text())
        settings.set_api_url(self._api_url_edit.text())
        settings.set_ai_model(self._model_edit.text())

        self.accept()

    def _apply_wallpaper_settings(self):
        settings = GlobalSettings()
        settings.set_wallpaper_enabled(self._wallpaper_enable_check.isChecked())
        settings.set_force_standard_bg_in_training(self._force_standard_check.isChecked())

        if self._wallpaper_enable_check.isChecked() and not WallpaperManager().current_path():
            settings.set_wallpaper_enabled(False)
            QMessageBox.information(self, "提示", "请先选择一张图片作为壁纸。")

        self.accept()

    def _on_select_wallpaper(self):
        filters = "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;PNG文件 (*.png);;JPEG文件 (*.jpg *.jpeg);;所有文件 (*.*)"
        path = QFileDialog.getOpenFileName(self, "选择壁纸图片", "", filters)[0]

        if path:
            # 复制到用户目录
            settings = GlobalSettings()
            user_dir = os.path.join(QCoreApplication.applicationDirPath(), "users", settings.current_user(), "wallpaper")
            os.makedirs(user_dir, exist_ok=True)

            ext = os.path.splitext(path)[1]
            new_path = os.path.join(user_dir, f"wallpaper{ext}")

            import shutil
            if os.path.exists(new_path):
                os.remove(new_path)
            shutil.copy2(path, new_path)

            if WallpaperManager().load_wallpaper(new_path):
                self._wallpaper_path_label.setText(new_path)
                self._update_wallpaper_preview(new_path)
                self._preview_wallpaper_btn.setEnabled(True)
                settings.settings_changed.emit()
            else:
                QMessageBox.warning(self, "加载失败", "无法加载所选图片，请检查文件格式是否正确。")

    def _on_clear_wallpaper(self):
        WallpaperManager().clear_wallpaper()
        self._wallpaper_path_label.setText("未选择")
        self._wallpaper_preview_label.setText("暂无壁纸\n\n点击下方「选择图片」按钮\n选择一张图片作为壁纸")
        self._wallpaper_preview_label.setFixedSize(400, 280)
        self._wallpaper_preview_label.setPixmap(QPixmap())
        self._preview_wallpaper_btn.setEnabled(False)

    def _update_wallpaper_preview(self, path: str):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._wallpaper_preview_label.setText("图片加载失败\n请选择其他格式的图片")
            return

        max_width = 500
        max_height = 350
        scaled = pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._wallpaper_preview_label.setFixedSize(scaled.size())
        self._wallpaper_preview_label.setPixmap(scaled)

    def _on_wallpaper_preview(self):
        path = WallpaperManager().current_path()
        if not path:
            return

        class PreviewWidget(QWidget):
            def __init__(self, path, parent=None):
                super().__init__(parent)
                self._path = path

            def paintEvent(self, event):
                painter = QPainter(self)
                pixmap = QPixmap(self._path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    pos = ((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2)
                    painter.fillRect(self.rect(), Qt.black)
                    painter.drawPixmap(pos[0], pos[1], scaled)

        dialog = QDialog(self)
        dialog.setWindowTitle("壁纸预览")
        dialog.resize(800, 600)

        layout = QVBoxLayout(dialog)
        preview = PreviewWidget(path, dialog)
        preview.setMinimumHeight(400)
        layout.addWidget(preview)

        btn_layout = QHBoxLayout()
        close_btn = QPushButton("关闭")
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        close_btn.clicked.connect(dialog.accept)
        dialog.exec()

    def _apply_style_sheet(self):
        settings = GlobalSettings()
        bg = settings.background_color().name()
        text = settings.text_color().name()
        night_mode = settings.night_mode()

        preview_bg = "rgba(76,175,80,0.08)" if night_mode else "rgba(76,175,80,0.05)"
        border_color = "#666666" if night_mode else "#4CAF50"

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text}; }}
            QGroupBox {{ color: {text}; border: 2px solid {border_color}; border-radius: 8px; margin-top: 12px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 8px; }}
            QRadioButton, QCheckBox {{ color: {text}; }}
            QListWidget {{ background-color: {bg}; color: {text}; border: 1px solid {border_color}; border-radius: 5px; }}
            QListWidget::item {{ padding: 10px; }}
            QListWidget::item:selected {{ background-color: #4CAF50; color: white; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none; border-radius: 8px; padding: 8px 20px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QPushButton:disabled {{ background-color: #999999; }}
            QDoubleSpinBox, QSpinBox, QSlider, QLineEdit {{ background-color: {bg}; color: {text};
                border: 1px solid {border_color}; border-radius: 5px; padding: 5px; }}
            QScrollArea {{ background-color: transparent; border: none; }}
        """)