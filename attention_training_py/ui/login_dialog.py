# ui/login_dialog.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QWidget, QGroupBox, QCheckBox, QMessageBox, QComboBox

from core.user_manager import UserManager, UserRole, UserInfo
from core.settings import GlobalSettings


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("注意力训练系统 - 登录")
        self.setMinimumSize(400, 350)
        self.setModal(True)

        self._logged_in = False
        self._current_user = ""

        self._setup_ui()
        self._apply_style_sheet()
        # 固定为布局实际所需的高度：避免 Qt 在窗口显示/拖动时于固定尺寸与
        # 布局最小尺寸之间来回切换，导致窗口忽大忽小、内容被裁剪。
        self.setFixedSize(450, max(420, self.layout().minimumSize().height()))

    def is_logged_in(self) -> bool:
        return self._logged_in

    def current_user(self) -> str:
        return self._current_user

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        # 标题
        title = QLabel("🎯 游戏化注意力训练")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; padding: 15px;")
        main_layout.addWidget(title)

        # 标签页
        self._tab_widget = QTabWidget()
        self._setup_login_tab()
        self._setup_register_tab()
        main_layout.addWidget(self._tab_widget)

        # 版本信息
        version = QLabel("版本 3.0 | 支持数据库存储")
        version.setAlignment(Qt.AlignCenter)
        version.setStyleSheet("font-size: 11px; color: #888888; padding: 10px;")
        main_layout.addWidget(version)

    def _setup_login_tab(self):
        login_tab = QWidget()
        layout = QVBoxLayout(login_tab)
        layout.setSpacing(15)

        input_group = QGroupBox("登录信息")
        grid = QGridLayout(input_group)
        grid.setVerticalSpacing(12)
        grid.setHorizontalSpacing(10)

        user_label = QLabel("用户名:")
        self._login_username = QLineEdit()
        self._login_username.setPlaceholderText("请输入用户名")
        self._login_username.setMinimumHeight(32)

        pwd_label = QLabel("密码:")
        self._login_password = QLineEdit()
        self._login_password.setEchoMode(QLineEdit.Password)
        self._login_password.setPlaceholderText("请输入密码")
        self._login_password.setMinimumHeight(32)

        grid.addWidget(user_label, 0, 0)
        grid.addWidget(self._login_username, 0, 1)
        grid.addWidget(pwd_label, 1, 0)
        grid.addWidget(self._login_password, 1, 1)

        layout.addWidget(input_group)

        # 显示密码
        show_pwd = QCheckBox("显示密码")
        show_pwd.toggled.connect(lambda checked: self._login_password.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password
        ))

        check_layout = QHBoxLayout()
        check_layout.addStretch()
        check_layout.addWidget(show_pwd)
        layout.addLayout(check_layout)

        # 登录按钮
        login_btn = QPushButton("登 录")
        login_btn.setMinimumHeight(45)
        login_btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        login_btn.clicked.connect(self._on_login)
        layout.addWidget(login_btn)

        # 提示
        demo_label = QLabel(
            "💡 演示账户：\n"
            "• 学生: student / student123\n"
            "• 教师: teacher / teacher123\n"
            "• 管理员: admin / admin123"
        )
        demo_label.setWordWrap(True)
        demo_label.setStyleSheet("font-size: 11px; color: #666666; padding: 10px; background-color: #f5f5f5; border-radius: 5px;")
        layout.addWidget(demo_label)

        layout.addStretch()
        self._tab_widget.addTab(login_tab, "登录")

    def _setup_register_tab(self):
        register_tab = QWidget()
        layout = QVBoxLayout(register_tab)
        layout.setSpacing(15)

        input_group = QGroupBox("注册新账户")
        grid = QGridLayout(input_group)
        grid.setVerticalSpacing(12)
        grid.setHorizontalSpacing(10)

        user_label = QLabel("用户名:")
        self._reg_username = QLineEdit()
        self._reg_username.setPlaceholderText("4-20个字符，字母数字下划线")
        self._reg_username.setMinimumHeight(32)

        name_label = QLabel("显示名称:")
        self._reg_display_name = QLineEdit()
        self._reg_display_name.setPlaceholderText("您的称呼")
        self._reg_display_name.setMinimumHeight(32)

        pwd_label = QLabel("密码:")
        self._reg_password = QLineEdit()
        self._reg_password.setEchoMode(QLineEdit.Password)
        self._reg_password.setPlaceholderText("至少4个字符")
        self._reg_password.setMinimumHeight(32)

        confirm_label = QLabel("确认密码:")
        self._reg_confirm_password = QLineEdit()
        self._reg_confirm_password.setEchoMode(QLineEdit.Password)
        self._reg_confirm_password.setPlaceholderText("再次输入密码")
        self._reg_confirm_password.setMinimumHeight(32)

        role_label = QLabel("角色:")
        self._reg_role = QComboBox()
        self._reg_role.addItem("学生", UserRole.STUDENT.value)
        self._reg_role.addItem("教师/家长", UserRole.TEACHER.value)
        self._reg_role.setMinimumHeight(32)

        grid.addWidget(user_label, 0, 0)
        grid.addWidget(self._reg_username, 0, 1)
        grid.addWidget(name_label, 1, 0)
        grid.addWidget(self._reg_display_name, 1, 1)
        grid.addWidget(pwd_label, 2, 0)
        grid.addWidget(self._reg_password, 2, 1)
        grid.addWidget(confirm_label, 3, 0)
        grid.addWidget(self._reg_confirm_password, 3, 1)
        grid.addWidget(role_label, 4, 0)
        grid.addWidget(self._reg_role, 4, 1)

        layout.addWidget(input_group)

        # 注册按钮
        register_btn = QPushButton("注 册")
        register_btn.setMinimumHeight(45)
        register_btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        register_btn.clicked.connect(self._on_register)
        layout.addWidget(register_btn)

        layout.addStretch()
        self._tab_widget.addTab(register_tab, "注册")

        # ui/login_dialog.py - 只修改 _on_login 方法

    def _on_login(self):
            username = self._login_username.text().strip()
            password = self._login_password.text()

            if not username:
                QMessageBox.warning(self, "登录失败", "请输入用户名")
                return

            if not password:
                QMessageBox.warning(self, "登录失败", "请输入密码")
                return

            user_manager = UserManager()
            if user_manager.login(username, password):
                self._logged_in = True
                self._current_user = username

                # 确保 GlobalSettings 同步更新
                settings = GlobalSettings()
                settings.set_current_user(username)
                settings.save_and_sync()

                # 通知 AchievementManager 切换用户
                from core.achievement_manager import AchievementManager
                am = AchievementManager()
                am.switch_user(username)

                self.accept()
            else:
                QMessageBox.warning(self, "登录失败", "用户名或密码错误")
                self._login_password.clear()
                self._login_password.setFocus()

    def _on_register(self):
        username = self._reg_username.text().strip()
        display_name = self._reg_display_name.text().strip()
        password = self._reg_password.text()
        confirm = self._reg_confirm_password.text()
        role = UserRole(self._reg_role.currentData())

        if len(username) < 4 or len(username) > 20:
            QMessageBox.warning(self, "注册失败", "用户名长度应为4-20个字符")
            return

        if not display_name:
            display_name = username

        if len(password) < 4:
            QMessageBox.warning(self, "注册失败", "密码长度至少为4个字符")
            return

        if password != confirm:
            QMessageBox.warning(self, "注册失败", "两次输入的密码不一致")
            return

        user_manager = UserManager()
        if user_manager.get_user(username):
            QMessageBox.warning(self, "注册失败", "用户名已存在")
            return

        new_user = UserInfo()
        new_user.username = username
        new_user.display_name = display_name
        new_user.role = role

        if user_manager.create_user(new_user, password):
            QMessageBox.information(self, "注册成功", f"用户 \"{display_name}\" 注册成功！\n请使用您的账号登录。")

            self._reg_username.clear()
            self._reg_display_name.clear()
            self._reg_password.clear()
            self._reg_confirm_password.clear()

            self._tab_widget.setCurrentIndex(0)
            self._login_username.setText(username)
            self._login_password.setFocus()
        else:
            QMessageBox.warning(self, "注册失败", "注册失败，请稍后重试")

    def _apply_style_sheet(self):
        settings = GlobalSettings()
        bg = settings.background_color().name()
        text = settings.text_color().name()
        night_mode = settings.night_mode()

        input_bg = "#3a3a3a" if night_mode else "#ffffff"
        group_bg = "#2d2d2d" if night_mode else "#f8f8f8"

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text}; }}
            QLineEdit {{ background-color: {input_bg}; color: {text}; border: 1px solid #4CAF50;
                border-radius: 5px; padding: 5px; }}
            QLineEdit:focus {{ border: 2px solid #4CAF50; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 5px; padding: 8px 20px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QPushButton:pressed {{ background-color: #3d8b40; }}
            QComboBox {{ background-color: {input_bg}; color: {text}; border: 1px solid #4CAF50;
                border-radius: 5px; padding: 5px; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background-color: {input_bg}; color: {text}; }}
            QCheckBox {{ color: {text}; }}
            QGroupBox {{ color: {text}; border: 2px solid #4CAF50; border-radius: 8px;
                margin-top: 16px; font-weight: bold; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 10px; }}
            QTabWidget::pane {{ background-color: {bg}; border: 1px solid #4CAF50; border-radius: 5px; }}
            QTabBar::tab {{ background-color: {group_bg}; color: {text}; padding: 8px 20px;
                border-top-left-radius: 5px; border-top-right-radius: 5px; }}
            QTabBar::tab:selected {{ background-color: #4CAF50; color: white; }}
            QTabBar::tab:hover {{ background-color: #45a049; color: white; }}
        """)