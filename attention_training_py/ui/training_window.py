# ui/training_window.py
import traceback
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QDateTime, QMutex, QMutexLocker, QMetaObject
from PySide6.QtGui import QPainter, QKeyEvent, QCloseEvent, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox, QDialog, QTextEdit, QProgressBar

from core.settings import GlobalSettings, TrainingRecord
from core.user_session import UserSession
from core.user_manager import UserManager, UserRole
from core.achievement_manager import AchievementManager
from core.sound_manager import SoundManager
from ai.ai_analysis_manager import AIAnalysisManager
from ai.composite_scoring import composite_details, score_band_label
from ui.ai_coach_dialog import AICoachDialog
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
        self._training_user_name = ""

        self._attention_score = 50
        self._total_blinks = 0
        self._avg_attention_sum = 0
        self._attention_sample_count = 0
        self._total_game_score = 0
        self._max_consecutive_hits = 0
        self._camera_face_seen = False

        # 注视数据
        self._gaze_scores = []
        self._gaze_distances = []
        self._avg_gaze_score = 0
        self._avg_gaze_distance = 0.0

        self._training_active = True
        self._training_finished = False
        self._closing = False
        self._is_full_screen = False
        self._training_started = False
        self._finishing = False
        self._cleanup_done = False

        # AI 相关
        self._ai_request_id = 0
        self._ai_request_pending = False
        self._ai_request_is_llm = False
        self._ai_signals_connected = False
        self._ai_loading_dialog = None
        self._ai_composite_visible = False
        self._dialog_mutex = QMutex()
        self._finish_mutex = QMutex()
        self._fallback_timer = None
        self._analysis_dialog = None

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
        self._camera_worker = None
        self._camera_started = False
        self._camera_thread = None

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
        print("Starting training...")
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
        try:
            if self._game_mode == "find_difference":
                self._game_widget = SpotDifferenceGame(self)
            else:
                self._game_widget = TrackingGame(self)
            print(f"Game widget created successfully")
        except Exception as e:
            print(f"Game widget creation error: {e}")
            traceback.print_exc()
            self._game_widget = None

        if self._game_widget:
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

        # 状态标签
        self._status_label = QLabel("状态: 初始化完成", self)
        self._status_label.setAlignment(Qt.AlignLeft)
        self._status_label.setStyleSheet("font-size: 12px; color: #888888; padding: 5px;")
        main_layout.addWidget(self._status_label)

    def _start_training(self):
        """开始训练"""
        print("=" * 50)
        print("STARTING TRAINING...")
        print("=" * 50)

        if self._training_started:
            print("Training already started, skipping")
            return
        self._training_started = True

        try:
            # 记录训练用户
            self._training_user_name = UserSession().current_user()
            print(f"Training user: {self._training_user_name}")
            if not self._training_user_name:
                print("WARNING: No user logged in, training results will not be saved")

            # 锁定训练状态
            UserSession().set_training_active(True)
            print("Training locked")

            # 更新状态
            if self._status_label:
                self._status_label.setText("状态: 正在启动...")

            # 启动计时器
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._update_timer)
            self._timer.start(1000)
            self._update_time_display()
            print("Timer started")

            # 注意力定时器
            self._attention_timer = QTimer(self)
            self._attention_timer.timeout.connect(self._update_attention_display)
            self._attention_timer.start(1000)

            # 连接游戏信号
            if self._game_widget:
                self._game_widget.game_score_changed.connect(self._on_game_score_changed)
                self._game_widget.feedback_triggered.connect(self._on_feedback_triggered)
                self._game_widget.consecutive_hits_changed.connect(self._on_consecutive_hits_changed)

                # 启动游戏
                self._game_widget.start_game()
                print("Game started")
            else:
                print("WARNING: Game widget is None, skipping game start")

            # 启动摄像头
            self._setup_camera()

            if self._status_label:
                self._status_label.setText("状态: 训练运行中")

            print("=" * 50)
            print("TRAINING STARTED SUCCESSFULLY")
            print("=" * 50)

        except Exception as e:
            print(f"ERROR in _start_training: {e}")
            traceback.print_exc()
            if self._status_label:
                self._status_label.setText(f"状态: 启动失败 - {str(e)}")
            self._on_training_finished()

    def _setup_camera(self):
        """设置摄像头"""
        print("Setting up camera...")
        try:
            self._camera_thread = QThread(self)
            self._camera_worker = CameraWorker()
            # 应用EAR阈值设置：自适应模式下使用历史记录计算值，手动模式使用手动设定值
            settings = GlobalSettings()
            self._camera_worker.set_ear_threshold(settings.effective_ear_threshold())
            self._camera_worker.set_adaptive_ear(settings.adaptive_ear())
            self._camera_worker.moveToThread(self._camera_thread)

            # 连接信号
            self._camera_worker.frame_ready.connect(self._update_camera_frame)
            self._camera_worker.eye_data_updated.connect(self._on_eye_data_updated)
            self._camera_worker.camera_error.connect(self._on_camera_error)
            self._camera_worker.finished.connect(self._on_camera_finished)

            # 线程启动时开始捕获
            self._camera_thread.started.connect(self._camera_worker.start_capture)

            self._camera_thread.start()
            self._camera_started = True
            print("Camera started successfully")

        except Exception as e:
            print(f"Camera setup error: {e}")
            traceback.print_exc()
            if self._camera_label:
                self._camera_label.setText(f"摄像头初始化失败:\n{str(e)}")

    def _on_camera_finished(self):
        """摄像头完成信号处理"""
        print("Camera worker finished")
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.quit()

    def _stop_camera(self):
        """停止摄像头"""
        print("Stopping camera...")

        if not self._camera_started:
            print("Camera not started, skipping")
            return

        try:
            if self._camera_worker:
                # 断开所有连接
                try:
                    self._camera_worker.disconnect(self)
                except:
                    pass

                # 调用停止
                self._camera_worker.stop_capture()
                print("Camera stopped")

            if self._camera_thread and self._camera_thread.isRunning():
                self._camera_thread.quit()
                if not self._camera_thread.wait(2000):
                    print("Camera thread did not stop gracefully, forcing termination")
                    self._camera_thread.terminate()
                    self._camera_thread.wait()
                self._camera_thread = None

            self._camera_worker = None
            self._camera_started = False
            print("Camera stopped safely")
        except Exception as e:
            print(f"Stop camera error: {e}")
            self._camera_started = False

    def _update_timer(self):
        """更新计时器"""
        if not self._training_active:
            return

        if self._remaining_seconds > 0:
            self._remaining_seconds -= 1
            self._update_time_display()

            if self._remaining_seconds % 10 == 0:
                print(f"Time remaining: {self._remaining_seconds} seconds")

            if self._remaining_seconds <= 0:
                print("=" * 50)
                print("TIME'S UP! Finishing training...")
                print("=" * 50)
                self._on_training_finished()

    def _update_time_display(self):
        """更新时间显示"""
        if self._time_label:
            minutes = self._remaining_seconds // 60
            seconds = self._remaining_seconds % 60
            self._time_label.setText(f"剩余时间: {minutes:02d}:{seconds:02d}")

    def _update_attention_display(self):
        """更新注意力显示"""
        if self._attention_label:
            color = "#4CAF50" if self._attention_score >= 70 else "#FF9800" if self._attention_score >= 40 else "#F44336"
            self._attention_label.setStyleSheet(
                f"color: {color}; background-color: transparent; font-weight: bold;"
            )
            self._attention_label.setText(f"注意力: {self._attention_score}")

    def _update_camera_frame(self, frame):
        """更新摄像头帧"""
        if not self._camera_label or self._closing:
            return
        try:
            pixmap = QPixmap.fromImage(frame)
            label_size = self._camera_label.size()
            if label_size.width() > 0 and label_size.height() > 0:
                pixmap = pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.FastTransformation)
            self._camera_label.setPixmap(pixmap)
        except Exception as e:
            print(f"Update camera frame error: {e}")

    def _on_eye_data_updated(self, ear: float, blink_count: int, attention_score: int,
                              gaze_score: int, gaze_distance: float):
        """处理眼睛数据更新"""
        if self._closing:
            return

        self._attention_score = attention_score
        self._avg_attention_sum += attention_score
        self._attention_sample_count += 1
        self._total_blinks = max(self._total_blinks, blink_count)

        # 记录注视数据
        self._gaze_scores.append(gaze_score)
        self._gaze_distances.append(gaze_distance)

        # 限制列表大小
        max_samples = self._duration_minutes * 60
        if len(self._gaze_scores) > max_samples:
            self._gaze_scores = self._gaze_scores[-max_samples:]
            self._gaze_distances = self._gaze_distances[-max_samples:]

        # 更新成就管理器的注视数据
        try:
            am = AchievementManager()
            if hasattr(am, 'update_gaze_data'):
                am.update_gaze_data(gaze_score, gaze_distance)
        except Exception as e:
            print(f"Update gaze achievement error: {e}")

        if self._game_widget:
            self._game_widget.update_with_attention(attention_score)

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

    # ==================== AI 相关方法 ====================

    def _show_ai_loading_dialog(self):
        """显示 AI 分析加载对话框"""
        locker = QMutexLocker(self._dialog_mutex)
        try:
            if self._closing:
                return

            if self._ai_loading_dialog:
                self._ai_loading_dialog.close()
                self._ai_loading_dialog.deleteLater()

            self._ai_loading_dialog = QDialog(self)
            self._ai_loading_dialog.setWindowTitle("AI分析中")
            self._ai_loading_dialog.setFixedSize(400, 200)
            self._ai_loading_dialog.setModal(True)
            self._ai_loading_dialog.setAttribute(Qt.WA_DeleteOnClose)

            settings = GlobalSettings()
            text_color = settings.text_color().name()
            night_mode = settings.night_mode()
            dialog_bg = "#2d2d2d" if night_mode else "#f5f5f5"

            self._ai_loading_dialog.setStyleSheet(f"""
                QDialog {{ background-color: {dialog_bg}; }}
                QLabel {{ color: {text_color}; }}
                QPushButton {{ background-color: #4CAF50; color: white; border: none;
                    border-radius: 5px; padding: 8px 16px; font-size: 14px; }}
                QPushButton:hover {{ background-color: #45a049; }}
            """)

            layout = QVBoxLayout(self._ai_loading_dialog)

            icon_label = QLabel("🤖", self._ai_loading_dialog)
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setStyleSheet("font-size: 54px;")
            layout.addWidget(icon_label)

            label = QLabel("AI正在分析您的训练数据...\n\n请稍候...", self._ai_loading_dialog)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"font-size: 16px; color: {text_color};")
            layout.addWidget(label)

            progress_hint = QLabel("⏳ 分析中", self._ai_loading_dialog)
            progress_hint.setAlignment(Qt.AlignCenter)
            progress_hint.setStyleSheet(f"font-size: 13px; color: {text_color};")
            layout.addWidget(progress_hint)

            cancel_btn = QPushButton("取消分析", self._ai_loading_dialog)
            cancel_btn.setFixedWidth(120)
            cancel_btn.clicked.connect(self._on_cancel_ai_analysis)

            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            btn_layout.addWidget(cancel_btn)
            btn_layout.addStretch()
            layout.addLayout(btn_layout)

            # 动画定时器
            animation_timer = QTimer(self._ai_loading_dialog)
            dot_count = 0

            def update_dots():
                nonlocal dot_count
                dot_count = (dot_count % 3) + 1
                dots = "." * dot_count
                progress_hint.setText(f"⏳ 分析中{dots}")

            animation_timer.timeout.connect(update_dots)
            animation_timer.start(500)
            self._ai_loading_dialog.finished.connect(animation_timer.stop)

            self._ai_loading_dialog.show()
        finally:
            locker.unlock()

    def _on_cancel_ai_analysis(self):
        """取消 AI 分析"""
        if self._ai_request_id != 0 and self._ai_request_pending:
            AIAnalysisManager.instance().cancel_request(self._ai_request_id)
            self._ai_request_pending = False

        locker = QMutexLocker(self._dialog_mutex)
        try:
            if self._ai_loading_dialog:
                self._ai_loading_dialog.close()
                self._ai_loading_dialog = None
        finally:
            locker.unlock()

        self._finish_training()

    def _submit_local_analysis(self, avg_attention: int, total_blinks: int,
                               max_consecutive_hits: int, game_score: int,
                               game_mode: str, duration_minutes: int,
                               avg_gaze_score: int = 0, avg_gaze_distance: float = 0.0) -> int:
        """把本地 ONNX 分析提交到 AIAnalysisManager 后台线程执行，返回 request_id。"""
        print('[AI] submit LOCAL analysis')
        settings = GlobalSettings()
        ai_manager = AIAnalysisManager.instance()
        self._ai_composite_visible = True
        self._ai_request_is_llm = False
        self._disconnect_ai_signals()
        ai_manager.analysis_ready.connect(self._on_ai_analysis_ready, Qt.UniqueConnection)
        ai_manager.analysis_error.connect(self._on_ai_analysis_error, Qt.UniqueConnection)
        self._ai_signals_connected = True
        return ai_manager.submit_analysis(
            avg_attention=avg_attention,
            total_blinks=total_blinks,
            max_consecutive_hits=max_consecutive_hits,
            game_score=game_score,
            game_mode=game_mode,
            duration_minutes=duration_minutes,
            api_key="",
            api_url="",
            model="",
            avg_gaze_score=avg_gaze_score,
            avg_gaze_distance=avg_gaze_distance,
            difficulty=settings.effective_difficulty_level().value,
            face_detected=self._camera_face_seen,
        )

    def _disconnect_all_signals(self):
        """断开所有信号连接"""
        try:
            # 断开游戏信号
            if self._game_widget:
                try:
                    self._game_widget.game_score_changed.disconnect(self._on_game_score_changed)
                except:
                    pass
                try:
                    self._game_widget.feedback_triggered.disconnect(self._on_feedback_triggered)
                except:
                    pass
                try:
                    self._game_widget.consecutive_hits_changed.disconnect(self._on_consecutive_hits_changed)
                except:
                    pass

            # 断开摄像头信号
            if self._camera_worker:
                try:
                    self._camera_worker.frame_ready.disconnect(self._update_camera_frame)
                except:
                    pass
                try:
                    self._camera_worker.eye_data_updated.disconnect(self._on_eye_data_updated)
                except:
                    pass
                try:
                    self._camera_worker.camera_error.disconnect(self._on_camera_error)
                except:
                    pass
                try:
                    self._camera_worker.finished.disconnect(self._on_camera_finished)
                except:
                    pass
        except Exception as e:
            print(f"Disconnect signals error: {e}")

    def _disconnect_ai_signals(self):
        """断开AI管理器信号（仅在已连接时断开，避免 PySide6 的 Failed to disconnect 告警）"""
        if not self._ai_signals_connected:
            return
        try:
            ai_manager = AIAnalysisManager.instance()
            ai_manager.analysis_ready.disconnect(self._on_ai_analysis_ready)
            ai_manager.analysis_error.disconnect(self._on_ai_analysis_error)
        except Exception as e:
            print(f"Disconnect AI signals error: {e}")
        finally:
            self._ai_signals_connected = False

    def _safe_close(self):
        """安全关闭窗口"""
        try:
            self._stop_camera()

            if self._timer and self._timer.isActive():
                self._timer.stop()
            if self._attention_timer and self._attention_timer.isActive():
                self._attention_timer.stop()

            if not self._closing:
                self._closing = True
                self.close()
        except Exception as e:
            print(f"Safe close error: {e}")
            self.hide()
            self.deleteLater()

    def _on_ai_analysis_ready(self, request_id: int, analysis: str):
        """AI 分析完成"""
        if request_id != self._ai_request_id or self._closing or not self._ai_request_pending:
            return
        print('[AI] ready req=' + str(request_id) + ' cur=' + str(self._ai_request_id) + ' llm=' + str(self._ai_request_is_llm) + ' len=' + str(len(analysis)))

        self._ai_request_pending = False
        if self._fallback_timer:
            self._fallback_timer.stop()
            self._fallback_timer.deleteLater()
            self._fallback_timer = None

        locker = QMutexLocker(self._dialog_mutex)
        try:
            if self._ai_loading_dialog:
                self._ai_loading_dialog.close()
                self._ai_loading_dialog = None
        finally:
            locker.unlock()

        composite_visible = self._ai_composite_visible
        self._ai_composite_visible = False
        QTimer.singleShot(50, lambda: self._show_analysis_dialog(analysis, composite_visible))

    def _on_ai_analysis_error(self, request_id: int, error: str):
        """AI 分析错误"""
        if request_id != self._ai_request_id or self._closing or not self._ai_request_pending:
            return

        self._ai_request_pending = False
        if self._fallback_timer:
            self._fallback_timer.stop()
            self._fallback_timer.deleteLater()
            self._fallback_timer = None
        print('[AI] error req=' + str(request_id) + ' cur=' + str(self._ai_request_id) + ' : ' + str(error))

        locker = QMutexLocker(self._dialog_mutex)
        try:
            if self._ai_loading_dialog:
                self._ai_loading_dialog.close()
                self._ai_loading_dialog = None
        finally:
            locker.unlock()

        if self._ai_request_is_llm:
            QMessageBox.warning(
                self,
                "AI分析失败",
                f"云端AI分析失败：{error}\n已改用本地规则分析。\n请检查API地址、API密钥及网络/代理设置后重试。",
            )

        avg_attention = self._avg_attention_sum // self._attention_sample_count if self._attention_sample_count > 0 else 0

        # 计算平均注视数据
        if self._gaze_scores:
            self._avg_gaze_score = sum(self._gaze_scores) // len(self._gaze_scores)
        else:
            self._avg_gaze_score = 0

        if self._gaze_distances:
            self._avg_gaze_distance = sum(self._gaze_distances) / len(self._gaze_distances)
        else:
            self._avg_gaze_distance = 0.0

        self._show_ai_loading_dialog()
        self._ai_request_id = self._submit_local_analysis(
            avg_attention,
            self._total_blinks,
            self._max_consecutive_hits,
            self._total_game_score,
            self._game_mode,
            self._duration_minutes,
            self._avg_gaze_score,
            self._avg_gaze_distance,
        )
        self._ai_request_pending = True

    def _show_analysis_dialog(self, analysis: str, composite_visible: bool = False):
        """显示分析结果对话框"""
        if self._closing or not self.isVisible():
            self._finish_training()
            return

        settings = GlobalSettings()
        text_color = settings.text_color().name()
        night_mode = settings.night_mode()

        dialog_bg = "#2d2d2d" if night_mode else "#f5f5f5"
        text_edit_bg = "#3a3a3a" if night_mode else "#ffffff"

        dialog = QDialog(self)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowTitle("🤖 训练分析报告")
        dialog.setMinimumSize(700, 600)
        dialog.setModal(False)

        dialog.setStyleSheet(f"""
            QDialog {{ background-color: {dialog_bg}; }}
            QLabel {{ color: {text_color}; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 5px; padding: 10px 20px; font-size: 14px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QTextEdit {{ background-color: {text_edit_bg}; color: {text_color};
                border: 2px solid #4CAF50; border-radius: 8px;
                font-size: 14px; padding: 15px; }}
        """)

        layout = QVBoxLayout(dialog)

        title_label = QLabel("📊 训练分析报告", dialog)
        title_label.setStyleSheet(f"font-size: 24px; font-weight: bold; padding: 15px; color: {text_color};")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        text_edit = QTextEdit(dialog)
        text_edit.setPlainText(analysis)
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)

        if composite_visible:
            composite_total, composite_parts = composite_details(
                avg_attention=self._avg_attention_sum // self._attention_sample_count if self._attention_sample_count > 0 else 0,
                max_consecutive_hits=self._max_consecutive_hits,
                game_score=self._total_game_score,
                game_mode=self._game_mode,
                difficulty=GlobalSettings().effective_difficulty_level().value,
                avg_gaze_score=self._avg_gaze_score,
                face_detected=int(self._camera_face_seen),
                duration_minutes=self._duration_minutes,
            )
            band_color = "#F44336"
            if composite_total >= 80:
                band_color = "#4CAF50"
            elif composite_total >= 65:
                band_color = "#8BC34A"
            elif composite_total >= 50:
                band_color = "#FF9800"
            elif composite_total >= 35:
                band_color = "#FF5722"

            composite_card = QWidget(dialog)
            composite_card.setStyleSheet("background-color: rgba(76, 175, 80, 0.08); border-radius: 10px; padding: 10px;")
            card_layout = QVBoxLayout(composite_card)
            card_layout.setSpacing(6)

            score_label = QLabel(f"\U0001f3c6 综合评分\uff1a{composite_total}/100\uff08{score_band_label(composite_total)}\uff09", composite_card)
            score_label.setAlignment(Qt.AlignCenter)
            score_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {band_color}; background: transparent;")
            card_layout.addWidget(score_label)

            progress_bar = QProgressBar(composite_card)
            progress_bar.setRange(0, 100)
            progress_bar.setValue(composite_total)
            progress_bar.setTextVisible(False)
            progress_bar.setFixedHeight(14)
            progress_bar.setStyleSheet(
                "QProgressBar { border: none; background-color: #3a3a3a; border-radius: 7px; }"
                f"QProgressBar::chunk {{ background-color: {band_color}; border-radius: 7px; }}"
            )
            card_layout.addWidget(progress_bar)

            breakdown_text = "  \u00b7  ".join(
                f"{name} {round(part)}/{int(full)}" for name, part, full in composite_parts
            )
            breakdown_label = QLabel(breakdown_text, composite_card)
            breakdown_label.setAlignment(Qt.AlignCenter)
            breakdown_label.setStyleSheet(f"font-size: 12px; color: {text_color}; background: transparent;")
            card_layout.addWidget(breakdown_label)

            layout.insertWidget(1, composite_card)

        avg_attention = self._avg_attention_sum // self._attention_sample_count if self._attention_sample_count > 0 else 0
        gaze_info = f"  |  注视专注度: {self._avg_gaze_score}" if self._gaze_scores else ""
        summary_label = QLabel(
            f"训练时长: {self._duration_minutes}分钟  |  平均注意力: {avg_attention}  |  游戏得分: {self._total_game_score}{gaze_info}",
            dialog
        )
        summary_label.setAlignment(Qt.AlignCenter)
        summary_label.setStyleSheet(f"font-size: 14px; color: {text_color}; padding: 10px;")
        layout.addWidget(summary_label)

        btn_layout = QHBoxLayout()
        close_btn = QPushButton("完成训练", dialog)
        copy_btn = QPushButton("📋 复制报告", dialog)
        coach_btn = None
        if UserManager().current_user_role() == UserRole.STUDENT:
            coach_btn = QPushButton("🤖 继续咨询教练", dialog)
            coach_btn.clicked.connect(self._on_continue_with_coach)

        self._analysis_dialog = dialog

        def on_close_clicked():
            dialog.close()
            self._finish_training()

        close_btn.clicked.connect(on_close_clicked)
        copy_btn.clicked.connect(lambda: self._on_copy_analysis(text_edit))
        dialog.finished.connect(self._on_analysis_dialog_finished)

        btn_layout.addWidget(copy_btn)
        if coach_btn:
            btn_layout.addWidget(coach_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        dialog.show()

    def _on_continue_with_coach(self):
        """打开 AI 教练对话框并携带本次训练数据"""
        try:
            avg_attention = self._avg_attention_sum // self._attention_sample_count if self._attention_sample_count > 0 else 0
            context = {
                "avg_attention": avg_attention,
                "total_blinks": self._total_blinks,
                "max_consecutive_hits": self._max_consecutive_hits,
                "game_score": self._total_game_score,
                "game_mode": self._game_mode,
                "duration_minutes": self._duration_minutes,
                "avg_gaze_score": self._avg_gaze_score,
                "avg_gaze_distance": self._avg_gaze_distance,
            }
            dlg = AICoachDialog(self, session_context=context)
            dlg.setAttribute(Qt.WA_DeleteOnClose)
            dlg.show()
        except Exception as e:
            print(f"Open coach dialog error: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"无法打开AI教练:\n{str(e)}")

    def _on_analysis_dialog_finished(self, result: int):
        """分析对话框结束"""
        self._analysis_dialog = None
        if not self._cleanup_done:
            self._finish_training()

    def _on_copy_analysis(self, text_edit: QTextEdit):
        """复制分析报告"""
        text_edit.selectAll()
        text_edit.copy()

    # ==================== 训练完成相关方法 ====================

    def _on_training_finished(self):
        """训练完成"""
        if not self._training_active:
            print("onTrainingFinished: Training not active, skipping")
            return

        if self._training_finished:
            print("onTrainingFinished: Already finished, skipping")
            return

        self._training_finished = True
        self._training_active = False

        print("=" * 50)
        print("TRAINING FINISHED")
        print("=" * 50)

        if self._timer and self._timer.isActive():
            self._timer.stop()
        if self._attention_timer and self._attention_timer.isActive():
            self._attention_timer.stop()

        if self._game_widget:
            try:
                self._game_widget.stop_game()
                print("Game stopped")
            except Exception as e:
                print(f"Stop game error: {e}")

        avg_attention = self._avg_attention_sum // self._attention_sample_count if self._attention_sample_count > 0 else 0
        print(f"Average attention: {avg_attention}")

        # 计算平均注视数据
        if self._gaze_scores:
            self._avg_gaze_score = sum(self._gaze_scores) // len(self._gaze_scores)
        else:
            self._avg_gaze_score = 0

        if self._gaze_distances:
            self._avg_gaze_distance = sum(self._gaze_distances) / len(self._gaze_distances)
        else:
            self._avg_gaze_distance = 0.0

        print(f"Average gaze score: {self._avg_gaze_score}")
        print(f"Average gaze distance: {self._avg_gaze_distance:.3f}")

        current_user = UserSession().current_user()
        if current_user != self._training_user_name:
            print(f"User changed during training! Original: {self._training_user_name}, Current: {current_user}")
            if UserSession().switch_user(self._training_user_name):
                print(f"Successfully switched back to original user: {self._training_user_name}")

        settings = GlobalSettings()

        try:
            record = TrainingRecord()
            record.date_time = QDateTime.currentDateTime()
            record.duration_minutes = self._duration_minutes
            record.game_mode = self._game_mode
            record.difficulty = settings.effective_difficulty_level()
            record.avg_attention_score = avg_attention
            record.total_blinks = self._total_blinks
            record.game_score = self._total_game_score
            record.avg_gaze_score = self._avg_gaze_score
            record.avg_gaze_distance = self._avg_gaze_distance
            self._camera_face_seen = bool(getattr(self._camera_worker, "face_seen", False))
            record.max_consecutive_hits = self._max_consecutive_hits
            record.face_detected = int(self._camera_face_seen)
            if self._game_mode == "dynamic_tracking" and self._game_widget is not None:
                record.hit_rate = float(getattr(self._game_widget, "hit_rate", lambda: 0.0)())
                record.avg_response_time = float(
                    getattr(self._game_widget, "avg_response_time", lambda: 0.0)()
                )
                record.path_efficiency = float(
                    getattr(self._game_widget, "path_efficiency", lambda: 0.0)()
                )
            composite_total, _ = composite_details(
                avg_attention=avg_attention,
                max_consecutive_hits=self._max_consecutive_hits,
                game_score=self._total_game_score,
                game_mode=self._game_mode,
                difficulty=record.difficulty.value,
                avg_gaze_score=self._avg_gaze_score,
                face_detected=int(self._camera_face_seen),
                duration_minutes=self._duration_minutes,
            )
            record.composite_score = composite_total
            settings.add_training_record_for_user(self._training_user_name, record)
            print("Training record saved")
        except Exception as e:
            print(f"Save record error: {e}")
            traceback.print_exc()

        # 按游戏模式更新成就（找茬/动态追踪两大板块，各 10 个）
        try:
            am = AchievementManager()
            if am._current_user != self._training_user_name:
                am.switch_user(self._training_user_name)

            hit_rate = 0.0
            avg_response_time = 0.0
            path_efficiency = 0.0
            if self._game_mode == "dynamic_tracking" and self._game_widget is not None:
                hit_rate = float(getattr(self._game_widget, "hit_rate", lambda: 0.0)())
                avg_response_time = float(
                    getattr(self._game_widget, "avg_response_time", lambda: 0.0)()
                )
                path_efficiency = float(
                    getattr(self._game_widget, "path_efficiency", lambda: 0.0)()
                )

            am.check_training_achievements(
                game_mode=self._game_mode,
                avg_attention=avg_attention,
                game_score=self._total_game_score,
                max_consecutive_hits=self._max_consecutive_hits,
                hit_rate=hit_rate,
                avg_response_time=avg_response_time,
                path_efficiency=path_efficiency,
                duration_minutes=self._duration_minutes,
            )
            am.save_to_file()
            print("Achievements updated")
        except Exception as e:
            print(f"Achievement error: {e}")
            traceback.print_exc()

        self._stop_camera()

        settings = GlobalSettings()
        if settings.ai_enabled() and settings.api_key() and not settings.local_analysis_enabled():
            print("Starting AI analysis...")

            self._show_ai_loading_dialog()

            ai_manager = AIAnalysisManager.instance()

            self._disconnect_ai_signals()

            ai_manager.analysis_ready.connect(self._on_ai_analysis_ready, Qt.UniqueConnection)
            ai_manager.analysis_error.connect(self._on_ai_analysis_error, Qt.UniqueConnection)
            self._ai_signals_connected = True

            self._ai_request_id = ai_manager.submit_analysis(
                avg_attention=avg_attention,
                total_blinks=self._total_blinks,
                max_consecutive_hits=self._max_consecutive_hits,
                game_score=self._total_game_score,
                game_mode=self._game_mode,
                duration_minutes=self._duration_minutes,
                api_key=settings.api_key(),
                api_url=settings.api_url(),
                model=settings.ai_model(),
                difficulty=settings.effective_difficulty_level().value,
                face_detected=self._camera_face_seen,
                avg_gaze_score=self._avg_gaze_score,
                avg_gaze_distance=self._avg_gaze_distance
            )
            self._ai_request_pending = True
            self._ai_request_is_llm = True
            print(f"AI request submitted: {self._ai_request_id}")

            self._fallback_timer = QTimer(self)
            self._fallback_timer.setSingleShot(True)

            def on_fallback_timeout():
                if self._ai_request_pending:
                    print("AI response slow, using local analysis...")
                    ai_manager.cancel_request(self._ai_request_id)
                    self._ai_request_id = 0
                    self._ai_request_pending = False

                    locker2 = QMutexLocker(self._dialog_mutex)
                    try:
                        if self._ai_loading_dialog:
                            self._ai_loading_dialog.close()
                            self._ai_loading_dialog = None
                    finally:
                        locker2.unlock()

                    QMessageBox.warning(
                        self,
                        "AI分析超时",
                        "云端AI分析超过30秒未响应，已改用本地规则分析。\n请检查API地址、API密钥以及网络/代理设置后重试。",
                    )

                    self._show_ai_loading_dialog()
                    self._ai_request_id = self._submit_local_analysis(
                        avg_attention,
                        self._total_blinks,
                        self._max_consecutive_hits,
                        self._total_game_score,
                        self._game_mode,
                        self._duration_minutes,
                        self._avg_gaze_score,
                        self._avg_gaze_distance,
                    )
                    self._ai_request_pending = True

            self._fallback_timer.timeout.connect(on_fallback_timeout)
            self._fallback_timer.start(30000)

        else:
            print('[AI] cloud skipped -> local analysis: ai_enabled=' + str(settings.ai_enabled()) + ' has_key=' + str(bool(settings.api_key())) + ' local_enabled=' + str(settings.local_analysis_enabled()) + ' user=' + str(self._training_user_name))
            self._show_ai_loading_dialog()
            self._ai_request_id = self._submit_local_analysis(
                avg_attention,
                self._total_blinks,
                self._max_consecutive_hits,
                self._total_game_score,
                self._game_mode,
                self._duration_minutes,
                self._avg_gaze_score,
                self._avg_gaze_distance,
            )
            self._ai_request_pending = True

    def _finish_training(self):
        """完成训练（发送信号，清理资源）"""
        locker = QMutexLocker(self._finish_mutex)
        try:
            if self._finishing or self._closing or self._cleanup_done:
                return

            self._finishing = True
            print("finishTraining: Starting cleanup")

            self._disconnect_all_signals()

            if self._fallback_timer:
                self._fallback_timer.stop()
                self._fallback_timer.deleteLater()
                self._fallback_timer = None

            if self._ai_request_pending and self._ai_request_id != 0:
                AIAnalysisManager.instance().cancel_request(self._ai_request_id)
                self._ai_request_pending = False

            locker2 = QMutexLocker(self._dialog_mutex)
            try:
                if self._ai_loading_dialog:
                    self._ai_loading_dialog.close()
                    self._ai_loading_dialog = None
            finally:
                locker2.unlock()

            self._disconnect_ai_signals()

            UserSession().set_training_active(False)

            self._cleanup_done = True

            self.training_finished.emit()

            QTimer.singleShot(100, self._safe_close)
        finally:
            locker.unlock()

    # ==================== 事件处理 ====================

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
        elif event.key() == Qt.Key_Escape and self._is_full_screen:
            self.showNormal()
            self._is_full_screen = False
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        """关闭事件"""
        print("=" * 50)
        print("closeEvent called")
        print(f"self._training_finished = {self._training_finished}")
        print(f"self._closing = {self._closing}")
        print(f"self._cleanup_done = {self._cleanup_done}")
        print("=" * 50)

        if not self._training_finished and not self._closing:
            reply = QMessageBox.question(
                self, "确认退出",
                "训练还未完成，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                print("User cancelled close")
                event.ignore()
                return

        self._closing = True
        self._training_active = False

        self._disconnect_all_signals()
        self._disconnect_ai_signals()

        if self._fallback_timer:
            self._fallback_timer.stop()
            self._fallback_timer.deleteLater()
            self._fallback_timer = None

        if self._ai_request_pending and self._ai_request_id != 0:
            AIAnalysisManager.instance().cancel_request(self._ai_request_id)
            self._ai_request_pending = False

        locker = QMutexLocker(self._dialog_mutex)
        try:
            if self._ai_loading_dialog:
                self._ai_loading_dialog.close()
                self._ai_loading_dialog = None
        finally:
            locker.unlock()

        self._stop_camera()

        if self._timer:
            self._timer.stop()
            self._timer = None
        if self._attention_timer:
            self._attention_timer.stop()
            self._attention_timer = None

        if self._game_widget:
            try:
                self._game_widget.stop_game()
                print("Game stopped")
            except Exception as e:
                print(f"Stop game error: {e}")

        try:
            UserSession().set_training_active(False)
            print("Training lock released")
        except Exception as e:
            print(f"Release lock error: {e}")

        self._cleanup_done = True

        print("closeEvent completed, accepting event")
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