# ui/training_window.py - 修复线程清理问题

import traceback
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QDateTime, QMutex, QWaitCondition
from PySide6.QtGui import QPainter, QKeyEvent, QCloseEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox

from core.settings import GlobalSettings, TrainingRecord
from core.user_session import UserSession
from core.achievement_manager import AchievementManager
from core.sound_manager import SoundManager
from camera.camera_worker import CameraWorker
from games.spot_difference_game import SpotDifferenceGame
from games.tracking_game import TrackingGame
from utils.wallpaper_manager import WallpaperManager


class TrainingWindow(QWidget):
    training_finished = Signal()

    def __init__(self, duration_minutes: int, game_mode: str, parent=None):
        super().__init__(parent)

        print(f"TrainingWindow.__init__: {duration_minutes}min, {game_mode}")

        # 初始化成员变量
        self._duration_minutes = duration_minutes
        self._game_mode = game_mode
        self._remaining_seconds = duration_minutes * 60

        self._attention_score = 50
        self._total_blinks = 0
        self._avg_attention_sum = 0
        self._attention_sample_count = 0
        self._total_game_score = 0
        self._max_consecutive_hits = 0

        self._training_active = True
        self._training_finished = False
        self._closing = False
        self._is_full_screen = False

        # UI 元素
        self._time_label = None
        self._attention_label = None
        self._score_label = None
        self._camera_label = None
        self._game_widget = None
        self._status_label = None

        # 定时器
        self._timer = None
        self._attention_timer = None

        # 摄像头
        self._camera_thread = None
        self._camera_worker = None
        self._camera_started = False  # 添加标志

        # 设置窗口
        self.setWindowTitle("注意力训练 - 进行中")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        # 设置 UI
        self._setup_ui()

        # 应用样式
        self._apply_style_sheet()
        self._apply_background()

        # 连接信号
        settings = GlobalSettings()
        settings.settings_changed.connect(self._apply_style_sheet)

        wallpaper = WallpaperManager()
        wallpaper.wallpaper_changed.connect(self._apply_background)
        wallpaper.wallpaper_cleared.connect(self._apply_background)

        # 启动训练
        print("Calling start_training from constructor...")
        self._start_training()

        print("TrainingWindow initialized successfully")

    def _setup_ui(self):
        """设置 UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 信息栏
        info_layout = QHBoxLayout()
        self._time_label = QLabel("剩余时间: --:--", self)
        self._attention_label = QLabel("注意力: --", self)
        self._score_label = QLabel("游戏得分: 0", self)

        font = self._time_label.font()
        font.setPointSize(16)
        font.setBold(True)
        for label in [self._time_label, self._attention_label, self._score_label]:
            label.setFont(font)

        info_layout.addWidget(self._time_label)
        info_layout.addStretch()
        info_layout.addWidget(self._attention_label)
        info_layout.addStretch()
        info_layout.addWidget(self._score_label)
        main_layout.addLayout(info_layout)

        # 全屏提示
        hint = QLabel("💡 按 F11 键切换全屏模式", self)
        hint.setAlignment(Qt.AlignRight)
        hint.setStyleSheet("font-size: 12px; color: #888888; padding: 5px;")
        main_layout.addWidget(hint)

        # 摄像头预览
        self._camera_label = QLabel(self)
        self._camera_label.setMinimumHeight(300)
        self._camera_label.setAlignment(Qt.AlignCenter)
        self._camera_label.setStyleSheet(
            "border: 3px solid #4CAF50; border-radius: 12px; background-color: #333333;"
        )
        self._camera_label.setText("正在初始化摄像头...")
        main_layout.addWidget(self._camera_label)

        # 游戏
        print(f"Creating game widget: {self._game_mode}")
        if self._game_mode == "find_difference":
            self._game_widget = SpotDifferenceGame(self)
        else:
            self._game_widget = TrackingGame(self)
        main_layout.addWidget(self._game_widget, 2)

        # 控制按钮
        btn_layout = QHBoxLayout()
        stop_btn = QPushButton("结束训练", self)
        stop_btn.setFixedSize(160, 50)
        stop_btn.setStyleSheet("font-size: 18px; font-weight: bold;")
        stop_btn.clicked.connect(self._on_training_finished)

        btn_layout.addStretch()
        btn_layout.addWidget(stop_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # 状态标签（调试用）
        self._status_label = QLabel("状态: 初始化完成", self)
        self._status_label.setAlignment(Qt.AlignLeft)
        self._status_label.setStyleSheet("font-size: 12px; color: #888888; padding: 5px;")
        main_layout.addWidget(self._status_label)

    def _start_training(self):
        """开始训练"""
        print("=" * 50)
        print("STARTING TRAINING...")
        print("=" * 50)

        # 锁定训练状态
        UserSession().set_training_active(True)
        print("Training locked")

        # 更新状态
        if self._status_label:
            self._status_label.setText("状态: 训练运行中")

        # 启动计时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_timer)
        self._timer.start(1000)
        self._update_time_display()
        print("Timer started")

        # 连接游戏信号
        if self._game_widget:
            self._game_widget.game_score_changed.connect(self._on_game_score_changed)
            self._game_widget.feedback_triggered.connect(self._on_feedback_triggered)
            self._game_widget.consecutive_hits_changed.connect(self._on_consecutive_hits_changed)

            # 启动游戏
            self._game_widget.start_game()
            print("Game started")

        # 启动摄像头
        self._setup_camera()

        print("=" * 50)
        print("TRAINING STARTED SUCCESSFULLY")
        print("=" * 50)

    def _setup_camera(self):
        """设置摄像头"""
        print("Setting up camera...")
        try:
            self._camera_thread = QThread(self)
            self._camera_worker = CameraWorker()
            self._camera_worker.moveToThread(self._camera_thread)

            # 连接信号
            self._camera_thread.started.connect(self._camera_worker.start_capture)
            self._camera_worker.frame_ready.connect(self._update_camera_frame)
            self._camera_worker.eye_data_updated.connect(self._on_eye_data_updated)
            self._camera_worker.camera_error.connect(self._on_camera_error)

            # 关键修复：使用正确的线程清理方式
            self._camera_worker.finished.connect(self._camera_thread.quit)
            self._camera_thread.finished.connect(self._camera_thread.deleteLater)
            self._camera_thread.finished.connect(self._camera_worker.deleteLater)

            self._camera_thread.start()
            self._camera_started = True
            print("Camera thread started")

        except Exception as e:
            print(f"Camera setup error: {e}")
            traceback.print_exc()
            if self._camera_label:
                self._camera_label.setText(f"摄像头初始化失败:\n{str(e)}")

    def _stop_camera(self):
        """安全停止摄像头"""
        print("Stopping camera...")

        if not self._camera_started:
            print("Camera not started, skipping")
            return

        # 先停止 worker
        if self._camera_worker:
            try:
                self._camera_worker.stop_capture()
                print("Camera worker stopped")
            except Exception as e:
                print(f"Stop worker error: {e}")

        # 等待线程结束
        if self._camera_thread and self._camera_thread.isRunning():
            print("Waiting for camera thread to finish...")
            # 使用更长的超时时间
            if not self._camera_thread.wait(3000):
                print("Warning: Camera thread timeout, terminating...")
                try:
                    self._camera_thread.terminate()
                    self._camera_thread.wait()
                except Exception as e:
                    print(f"Terminate error: {e}")
            else:
                print("Camera thread finished")

        self._camera_thread = None
        self._camera_worker = None
        self._camera_started = False
        print("Camera stopped")

    def _update_timer(self):
        """更新计时器"""
        if not self._training_active:
            return

        if self._remaining_seconds > 0:
            self._remaining_seconds -= 1
            self._update_time_display()

            if self._remaining_seconds <= 0:
                print("Time's up!")
                self._on_training_finished()

    def _update_time_display(self):
        """更新时间显示"""
        if self._time_label:
            minutes = self._remaining_seconds // 60
            seconds = self._remaining_seconds % 60
            self._time_label.setText(f"剩余时间: {minutes:02d}:{seconds:02d}")

    def _update_camera_frame(self, frame):
        """更新摄像头帧"""
        if not self._camera_label or self._closing:
            return

        try:
            pixmap = frame.toPixmap()
            label_size = self._camera_label.size()
            if label_size.width() > 0 and label_size.height() > 0:
                pixmap = pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._camera_label.setPixmap(pixmap)
        except Exception as e:
            print(f"Update camera frame error: {e}")

    def _on_eye_data_updated(self, ear: float, blink_count: int, attention_score: int):
        """处理眼睛数据更新"""
        if self._closing:
            return

        self._attention_score = attention_score
        self._avg_attention_sum += attention_score
        self._attention_sample_count += 1
        self._total_blinks = max(self._total_blinks, blink_count)

        if self._game_widget:
            self._game_widget.update_with_attention(attention_score)

        # 更新注意力显示
        if self._attention_label:
            color = "#4CAF50" if attention_score >= 70 else "#FF9800" if attention_score >= 40 else "#F44336"
            self._attention_label.setStyleSheet(
                f"color: {color}; background-color: transparent; font-weight: bold;"
            )
            self._attention_label.setText(f"注意力: {attention_score}")

    def _on_game_score_changed(self, score: int):
        """游戏得分变化"""
        self._total_game_score = score
        if self._score_label:
            self._score_label.setText(f"游戏得分: {score}")

        if self._camera_worker:
            self._camera_worker.update_game_score(score)

    def _on_consecutive_hits_changed(self, hits: int):
        """连击数变化"""
        self._max_consecutive_hits = max(self._max_consecutive_hits, hits)

    def _on_feedback_triggered(self, feedback_type: str):
        """反馈触发"""
        SoundManager().play_feedback_sound()

    def _on_camera_error(self, error: str):
        """摄像头错误"""
        print(f"Camera error: {error}")
        if self._camera_label and not self._closing:
            self._camera_label.setText(f"摄像头错误:\n{error}")

    def _on_training_finished(self):
        """训练完成"""
        print("=" * 50)
        print("TRAINING FINISHED")
        print("=" * 50)

        if self._training_finished:
            print("Already finished, skipping")
            return

        self._training_finished = True
        self._training_active = False

        # 停止定时器
        if self._timer and self._timer.isActive():
            self._timer.stop()
        if self._attention_timer and self._attention_timer.isActive():
            self._attention_timer.stop()

        # 停止游戏
        if self._game_widget:
            self._game_widget.stop_game()

        # 安全停止摄像头
        self._stop_camera()

        # 计算平均注意力
        avg_attention = self._avg_attention_sum // self._attention_sample_count if self._attention_sample_count > 0 else 0
        print(f"Average attention: {avg_attention}")

        # 保存记录
        try:
            settings = GlobalSettings()
            record = TrainingRecord()
            record.date_time = QDateTime.currentDateTime()
            record.duration_minutes = self._duration_minutes
            record.game_mode = self._game_mode
            record.difficulty = settings.difficulty_level()
            record.avg_attention_score = avg_attention
            record.total_blinks = self._total_blinks
            record.game_score = self._total_game_score
            settings.add_training_record(record)
            print("Training record saved")
        except Exception as e:
            print(f"Save record error: {e}")

        # 更新成就
        try:
            am = AchievementManager()
            am.check_attention_achievement(avg_attention)
            am.check_blink_achievement(self._total_blinks)
            am.check_game_score_achievement(self._total_game_score, self._game_mode)
            am.check_consecutive_hit_achievement(self._max_consecutive_hits)
            am.check_perfect_game_achievement(avg_attention, self._total_game_score, self._max_consecutive_hits)
            am.check_steady_focus_achievement(avg_attention, self._duration_minutes * 60)
            am.add_training_minutes(self._duration_minutes)
            print("Achievements updated")
        except Exception as e:
            print(f"Achievement error: {e}")

        # 释放训练锁定
        UserSession().set_training_active(False)
        print("Training lock released")

        # 显示结果
        self._show_result(avg_attention)

    def _show_result(self, avg_attention: int):
        """显示结果"""
        if self._closing:
            return

        msg = f"""
训练完成！

📊 训练数据：
• 平均注意力：{avg_attention}/100
• 总眨眼次数：{self._total_blinks}
• 最高连击：{self._max_consecutive_hits}
• 游戏得分：{self._total_game_score}
• 训练时长：{self._duration_minutes}分钟

继续加油！保持训练！
"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("训练完成")
        msg_box.setText(msg)
        msg_box.setStyleSheet(GlobalSettings().get_message_box_style_sheet())
        msg_box.exec()

        self._finish()

    def _finish(self):
        """完成训练"""
        print("Finishing training...")
        self.training_finished.emit()
        self.close()

    def paintEvent(self, event):
        """绘制背景"""
        painter = QPainter(self)
        settings = GlobalSettings()

        if settings.force_standard_bg_in_training() or not settings.wallpaper_enabled():
            painter.fillRect(self.rect(), settings.background_color())
        else:
            WallpaperManager().paint_wallpaper(painter, self.rect())

        super().paintEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件"""
        if event.key() == Qt.Key_F11:
            if self._is_full_screen:
                self.showNormal()
                self._is_full_screen = False
            else:
                self.showFullScreen()
                self._is_full_screen = True
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        """关闭事件 - 确保线程正确清理"""
        print("=" * 50)
        print("closeEvent called")
        print("=" * 50)

        self._closing = True
        self._training_active = False

        # 停止定时器
        if self._timer and self._timer.isActive():
            self._timer.stop()
        if self._attention_timer and self._attention_timer.isActive():
            self._attention_timer.stop()

        # 停止游戏
        if self._game_widget:
            try:
                self._game_widget.stop_game()
            except Exception as e:
                print(f"Stop game error: {e}")

        # 安全停止摄像头（关键修复）
        self._stop_camera()

        # 释放训练锁定
        try:
            UserSession().set_training_active(False)
        except Exception as e:
            print(f"Release lock error: {e}")

        print("closeEvent completed")
        event.accept()

    def _apply_style_sheet(self):
        """应用样式"""
        settings = GlobalSettings()
        text = settings.text_color().name()
        night_mode = settings.night_mode()
        label_bg = "#2d2d2d" if night_mode else "#f5f5f5"

        self.setStyleSheet(f"""
            QLabel {{ color: {text}; background-color: transparent; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 10px; padding: 12px 24px; font-size: 16px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QPushButton:pressed {{ background-color: #3d8b40; }}
        """)

        if self._camera_label:
            self._camera_label.setStyleSheet(
                f"border: 3px solid #4CAF50; border-radius: 12px; background-color: {label_bg};"
            )

    def _apply_background(self):
        """应用背景"""
        self.update()