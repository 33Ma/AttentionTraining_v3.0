# ui/main_window.py - 完整修改版

import traceback
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeyEvent, QPainter
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox

from core.settings import GlobalSettings
from core.user_manager import UserManager, UserRole
from core.user_session import UserSession
from core.achievement_manager import AchievementManager
from ui.login_dialog import LoginDialog
from ui.training_window import TrainingWindow
from ui.setting_dialog import SettingDialog
from ui.training_record_dialog import TrainingRecordDialog
from ui.achievement_dialog import AchievementDialog
from ui.teacher_report_dialog import TeacherReportDialog
from ui.user_management_dialog import UserManagementDialog
from ui.time_select_dialog import TimeSelectDialog
from ui.mode_select_dialog import ModeSelectDialog
from utils.wallpaper_manager import WallpaperManager


class MainWindow(QMainWindow):
    def __init__(self):
        try:
            super().__init__()
            self._is_full_screen = False
            self._is_training_mode = False
            self._user_info_label = None
            self._ai_loading_dialog = None
            self._train_win = None

            # 保存按钮引用以便清理
            self._role_specific_buttons = []
            self._central_widget = None
            self._main_layout = None

            self.setWindowTitle("游戏化注意力训练系统")
            self.setMinimumSize(500, 600)
            self.resize(720, 900)

            self._setup_ui()
            self._apply_style_sheet()
            self._apply_wallpaper()

            # 连接信号
            settings = GlobalSettings()
            settings.settings_changed.connect(self._apply_style_sheet)

            user_manager = UserManager()
            user_manager.user_logged_in.connect(self._on_user_changed)
            user_manager.user_logged_out.connect(self._on_user_logged_out)

            wallpaper_manager = WallpaperManager()
            wallpaper_manager.wallpaper_changed.connect(self._apply_wallpaper)
            wallpaper_manager.wallpaper_cleared.connect(self._apply_wallpaper)

            print("MainWindow initialized successfully")

        except Exception as e:
            print(f"MainWindow initialization error: {e}")
            traceback.print_exc()
            raise

    def keyPressEvent(self, event: QKeyEvent):
        try:
            if event.key() == Qt.Key_F11:
                self._toggle_full_screen()
            elif event.key() == Qt.Key_Escape and self._is_full_screen:
                self._toggle_full_screen()
            super().keyPressEvent(event)
        except Exception as e:
            print(f"Key press event error: {e}")

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            settings = GlobalSettings()

            if settings.wallpaper_enabled() and not self._is_training_mode:
                WallpaperManager().paint_wallpaper(painter, self.rect())
            else:
                painter.fillRect(self.rect(), settings.background_color())

            super().paintEvent(event)
        except Exception as e:
            print(f"Paint event error: {e}")

    def _setup_ui(self):
        """设置UI"""
        try:
            # 如果已经存在中央部件，清除它
            if self._central_widget:
                self._central_widget.deleteLater()
                self._central_widget = None

            self._central_widget = QWidget()
            self.setCentralWidget(self._central_widget)

            self._main_layout = QVBoxLayout(self._central_widget)
            self._main_layout.setAlignment(Qt.AlignCenter)
            self._main_layout.setSpacing(18)
            self._main_layout.setContentsMargins(50, 30, 50, 30)

            # 用户信息
            self._user_info_label = QLabel()
            self._user_info_label.setAlignment(Qt.AlignCenter)
            self._user_info_label.setWordWrap(True)
            self._main_layout.addWidget(self._user_info_label)

            # 标题
            title = QLabel("🎯 游戏化注意力训练")
            title.setObjectName("mainTitle")
            title.setAlignment(Qt.AlignCenter)
            title.setStyleSheet("font-size: 28px; font-weight: bold; padding: 15px 0 5px 0;")
            self._main_layout.addWidget(title)

            # 提示
            hint = QLabel("💡 按 F11 键切换全屏模式")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("font-size: 11px; color: #888888; padding: 5px;")
            self._main_layout.addWidget(hint)

            self._main_layout.addSpacing(15)

            # 按钮
            btn_width = 350
            btn_height = 65
            btn_style = "font-size: 20px; font-weight: bold; border-radius: 12px;"

            buttons = [
                ("开始训练", self._on_start_training),
                ("训练设置", self._on_training_settings),
                ("训练记录", self._on_training_records),
                ("🏆 成就", self._on_achievements)
            ]

            for text, callback in buttons:
                btn = QPushButton(text)
                btn.setFixedSize(btn_width, btn_height)
                btn.setStyleSheet(btn_style)
                btn.clicked.connect(callback)

                h_layout = QHBoxLayout()
                h_layout.addStretch()
                h_layout.addWidget(btn)
                h_layout.addStretch()
                self._main_layout.addLayout(h_layout)

            self._main_layout.addSpacing(10)

            # 角色特定按钮
            self._add_role_specific_buttons()

            self._main_layout.addSpacing(15)

            # 切换账户
            switch_btn = QPushButton("🔄 切换账户")
            switch_btn.setFixedSize(btn_width - 50, 50)
            switch_btn.setStyleSheet("font-size: 16px; font-weight: bold; background-color: #9C27B0; border-radius: 10px;")
            switch_btn.clicked.connect(self._on_switch_user)

            h_layout = QHBoxLayout()
            h_layout.addStretch()
            h_layout.addWidget(switch_btn)
            h_layout.addStretch()
            self._main_layout.addLayout(h_layout)

            self._main_layout.addSpacing(20)

            self._update_user_info()

        except Exception as e:
            print(f"Setup UI error: {e}")
            traceback.print_exc()
            raise

    def _add_role_specific_buttons(self):
        """添加角色特定按钮"""
        # 清除之前添加的角色特定按钮
        self._clear_role_specific_buttons()

        user_manager = UserManager()
        role = user_manager.current_user_role()

        btn_width = 350
        btn_height = 65
        btn_style = "font-size: 20px; font-weight: bold; border-radius: 12px;"

        if role in (UserRole.TEACHER, UserRole.ADMIN):
            teacher_btn = QPushButton("📊 班级报告")
            teacher_btn.setFixedSize(btn_width, btn_height - 5)
            teacher_btn.setStyleSheet(btn_style + "background-color: #2196F3;")
            teacher_btn.clicked.connect(self._on_teacher_report)

            h_layout = QHBoxLayout()
            h_layout.addStretch()
            h_layout.addWidget(teacher_btn)
            h_layout.addStretch()

            self._main_layout.addLayout(h_layout)
            self._role_specific_buttons.append(teacher_btn)

        if role == UserRole.ADMIN:
            user_btn = QPushButton("👥 用户管理")
            user_btn.setFixedSize(btn_width, btn_height - 5)
            user_btn.setStyleSheet(btn_style + "background-color: #FF9800;")
            user_btn.clicked.connect(self._on_user_management)

            h_layout = QHBoxLayout()
            h_layout.addStretch()
            h_layout.addWidget(user_btn)
            h_layout.addStretch()

            self._main_layout.addLayout(h_layout)
            self._role_specific_buttons.append(user_btn)

    def _clear_role_specific_buttons(self):
        """清除角色特定按钮"""
        for btn in self._role_specific_buttons:
            # 找到包含按钮的父布局并移除
            if btn.parent() and btn.parent().layout():
                parent_layout = btn.parent().layout()
                # 查找并移除包含该按钮的布局
                for i in range(parent_layout.count() - 1, -1, -1):
                    item = parent_layout.itemAt(i)
                    if item and item.layout():
                        # 检查这个布局是否包含我们的按钮
                        for j in range(item.layout().count() - 1, -1, -1):
                            widget_item = item.layout().itemAt(j)
                            if widget_item and widget_item.widget() == btn:
                                item.layout().removeWidget(btn)
                                break
            btn.deleteLater()
        self._role_specific_buttons.clear()

    def _rebuild_ui(self):
        """重建UI（切换用户后调用）"""
        try:
            print("Rebuilding UI for user change...")
            # 重新设置UI
            self._setup_ui()
            self._apply_style_sheet()
            self._apply_wallpaper()

            # 强制更新
            self.update()
            if self.centralWidget():
                self.centralWidget().update()

            print("UI rebuilt successfully")
        except Exception as e:
            print(f"Rebuild UI error: {e}")
            traceback.print_exc()

    def _apply_style_sheet(self):
        try:
            settings = GlobalSettings()
            bg = settings.background_color().name()
            text = settings.text_color().name()

            self.setStyleSheet(f"""
                QMainWindow {{ background-color: {bg}; }}
                QLabel {{ color: {text}; }}
                QPushButton {{ background-color: #4CAF50; color: white; border: none;
                    border-radius: 12px; padding: 15px; }}
                QPushButton:hover {{ background-color: #45a049; }}
            """)

            title = self.findChild(QLabel, "mainTitle")
            if title:
                title.setStyleSheet(f"font-size: 28px; font-weight: bold; padding: 15px 0 5px 0; color: {text};")

            self._update_user_info()
        except Exception as e:
            print(f"Apply style sheet error: {e}")

    def _apply_wallpaper(self):
        self.update()

    def _toggle_full_screen(self):
        try:
            if self._is_full_screen:
                self.showNormal()
            else:
                self.showFullScreen()
            self._is_full_screen = not self._is_full_screen
        except Exception as e:
            print(f"Toggle full screen error: {e}")

    def _update_user_info(self):
        try:
            if not self._user_info_label:
                return

            user_manager = UserManager()
            settings = GlobalSettings()
            text = settings.text_color().name()

            if user_manager.is_logged_in():
                user = user_manager.current_user()
                role_text = {
                    UserRole.ADMIN: "管理员",
                    UserRole.TEACHER: "教师/家长",
                    UserRole.STUDENT: "学生"
                }.get(user.role, "学生")

                self._user_info_label.setText(
                    f"👤 {user.display_name} ({role_text}) | 最后登录: {user.last_login_time.strftime('%m-%d %H:%M')}"
                )
                self._user_info_label.setStyleSheet(
                    f"font-size: 13px; padding: 8px 15px; background-color: rgba(76, 175, 80, 0.15); "
                    f"border-radius: 20px; color: {text};"
                )
            else:
                self._user_info_label.setText("👤 未登录")
                self._user_info_label.setStyleSheet(
                    f"font-size: 13px; padding: 8px 15px; background-color: rgba(76, 175, 80, 0.15); "
                    f"border-radius: 20px; color: {text};"
                )
        except Exception as e:
            print(f"Update user info error: {e}")

    # ========== 事件处理 ==========

    # ui/main_window.py - 在 _on_user_changed 中添加成就管理器切换

    def _on_user_changed(self, username: str, role):
        """用户切换事件处理"""
        try:
            print(f"User changed to: {username}, role: {role}")
            # 切换成就管理器到新用户
            am = AchievementManager()
            am.switch_user(username)
            self._rebuild_ui()
        except Exception as e:
            print(f"On user changed error: {e}")
            traceback.print_exc()

    def _on_user_logged_out(self):
        """用户登出事件处理"""
        try:
            print("User logged out")
            self._rebuild_ui()
        except Exception as e:
            print(f"On user logged out error: {e}")
            traceback.print_exc()

    # ========== 按钮点击事件 ==========

    def _on_start_training(self):
        """开始训练"""
        try:
            session = UserSession()
            if session.is_training_active():
                QMessageBox.warning(self, "训练进行中", "当前有训练正在进行中，请先完成或结束当前训练。")
                return

            self._show_mode_selection()
        except Exception as e:
            print(f"On start training error: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "启动训练失败", f"无法启动训练:\n{str(e)}")

    def _show_mode_selection(self):
        try:
            time_dlg = TimeSelectDialog(self)
            if time_dlg.exec() == TimeSelectDialog.Accepted:
                minutes = time_dlg.selected_minutes()
                mode_dlg = ModeSelectDialog(self)
                if mode_dlg.exec() == ModeSelectDialog.Accepted:
                    mode = mode_dlg.selected_mode()

                    if self._train_win is not None:
                        try:
                            self._train_win.training_finished.disconnect(self._on_training_finished)
                        except:
                            pass
                        self._train_win.close()
                        self._train_win.deleteLater()
                        self._train_win = None

                    self._train_win = TrainingWindow(minutes, mode)
                    self._train_win.training_finished.connect(self._on_training_finished)
                    self._train_win.show()

                    self.hide()
                    self._is_training_mode = True
        except Exception as e:
            print(f"Show mode selection error: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "启动训练失败", f"无法启动训练:\n{str(e)}")

    def _on_training_finished(self):
        """训练完成回调"""
        try:
            print("Training finished, showing main window")

            if self._train_win is not None:
                try:
                    self._train_win.training_finished.disconnect(self._on_training_finished)
                except:
                    pass

                win_to_delete = self._train_win
                self._train_win = None
                QTimer.singleShot(0, win_to_delete.deleteLater)

            self.show()
            self._is_training_mode = False

            self.update()
            self._apply_wallpaper()

            QTimer.singleShot(10, self._force_repaint)

        except Exception as e:
            print(f"On training finished error: {e}")
            traceback.print_exc()
            self.show()
            self._is_training_mode = False

    def _force_repaint(self):
        """强制重绘窗口"""
        try:
            self.update()
            if self.centralWidget():
                self.centralWidget().update()
            QTimer.singleShot(10, self._apply_style_sheet)
        except Exception as e:
            print(f"Force repaint error: {e}")

    def _on_training_settings(self):
        """训练设置"""
        try:
            dlg = SettingDialog(self)
            dlg.exec()
        except Exception as e:
            print(f"On training settings error: {e}")
            QMessageBox.critical(self, "错误", f"无法打开设置:\n{str(e)}")

    def _on_training_records(self):
        """训练记录"""
        try:
            dlg = TrainingRecordDialog(self)
            dlg.exec()
        except Exception as e:
            print(f"On training records error: {e}")
            QMessageBox.critical(self, "错误", f"无法打开训练记录:\n{str(e)}")

    def _on_achievements(self):
        """成就"""
        try:
            dlg = AchievementDialog(self)
            dlg.exec()
        except Exception as e:
            print(f"On achievements error: {e}")
            QMessageBox.critical(self, "错误", f"无法打开成就:\n{str(e)}")

    def _on_teacher_report(self):
        """班级报告"""
        try:
            dlg = TeacherReportDialog(self)
            dlg.exec()
        except Exception as e:
            print(f"On teacher report error: {e}")
            QMessageBox.critical(self, "错误", f"无法打开班级报告:\n{str(e)}")

    def _on_user_management(self):
        """用户管理"""
        try:
            dlg = UserManagementDialog(self)
            dlg.exec()
        except Exception as e:
            print(f"On user management error: {e}")
            QMessageBox.critical(self, "错误", f"无法打开用户管理:\n{str(e)}")

    def _on_switch_user(self):
                """切换用户"""
                try:
                    session = UserSession()
                    if session.is_training_active():
                        QMessageBox.warning(self, "无法切换", "当前有训练正在进行中，请先完成或结束当前训练。")
                        return

                    msg_box = QMessageBox(self)
                    msg_box.setWindowTitle("切换账户")
                    msg_box.setText("确定要切换账户吗？\n当前未保存的设置将会丢失。")
                    msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                    msg_box.setDefaultButton(QMessageBox.No)
                    msg_box.setStyleSheet(GlobalSettings().get_message_box_style_sheet())

                    if msg_box.exec() == QMessageBox.Yes:
                        user_manager = UserManager()
                        user_manager.logout()

                        login_dlg = LoginDialog(self)
                        if login_dlg.exec() == LoginDialog.Accepted and login_dlg.is_logged_in():
                            username = login_dlg.current_user()
                            session.switch_user(username)

                            # 确保 AchievementManager 切换到正确的用户
                            am = AchievementManager()
                            am.switch_user(username)

                            self._rebuild_ui()
                        else:
                            if not user_manager.is_logged_in():
                                self.close()
                except Exception as e:
                    print(f"On switch user error: {e}")
                    traceback.print_exc()
                    QMessageBox.critical(self, "错误", f"切换用户失败:\n{str(e)}")
