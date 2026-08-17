# ui/user_management_dialog.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QTableWidget, QListWidget, QTabWidget,
    QGroupBox, QMessageBox, QHeaderView, QTableWidgetItem, QListWidgetItem,
    QWidget  # 添加 QWidget 导入
)

from core.user_manager import UserManager, UserRole, UserInfo
from core.settings import GlobalSettings


class UserManagementDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("用户管理")
        self.setMinimumSize(800, 600)
        self.resize(900, 650)

        self._setup_ui()
        self._refresh_user_list()

        settings = GlobalSettings()
        settings.settings_changed.connect(self._apply_style_sheet)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        title = QLabel("👥 用户管理")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; padding: 10px;")
        main_layout.addWidget(title)

        self._tab_widget = QTabWidget()
        self._setup_user_tab()
        self._setup_assignment_tab()

        main_layout.addWidget(self._tab_widget)

        btn_layout = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(100, 40)
        close_btn.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        self._apply_style_sheet()

    def _setup_user_tab(self):
        user_tab = QWidget()  # 现在 QWidget 已导入
        layout = QVBoxLayout(user_tab)

        # 搜索栏
        search_layout = QHBoxLayout()
        search_label = QLabel("搜索:")
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("输入用户名或显示名称...")
        self._search_edit.textChanged.connect(self._on_search_user)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self._search_edit)
        search_layout.addStretch()
        layout.addLayout(search_layout)

        # 用户表格
        self._user_table = QTableWidget()
        self._user_table.setColumnCount(6)
        self._user_table.setHorizontalHeaderLabels([
            "用户名", "显示名称", "角色", "关联教师", "创建时间", "最后登录"
        ])
        self._user_table.horizontalHeader().setStretchLastSection(True)
        self._user_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._user_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._user_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self._user_table)

        # 按钮栏
        btn_layout = QHBoxLayout()
        self._create_btn = QPushButton("➕ 创建用户")
        self._edit_btn = QPushButton("✏️ 编辑用户")
        self._delete_btn = QPushButton("🗑️ 删除用户")
        self._reset_pwd_btn = QPushButton("🔑 重置密码")

        self._edit_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._reset_pwd_btn.setEnabled(False)

        self._user_table.itemSelectionChanged.connect(
            lambda: (
                self._edit_btn.setEnabled(bool(self._user_table.selectedItems())),
                self._delete_btn.setEnabled(bool(self._user_table.selectedItems())),
                self._reset_pwd_btn.setEnabled(bool(self._user_table.selectedItems()))
            )
        )

        self._create_btn.clicked.connect(self._on_create_user)
        self._edit_btn.clicked.connect(self._on_edit_user)
        self._delete_btn.clicked.connect(self._on_delete_user)
        self._reset_pwd_btn.clicked.connect(self._on_reset_password)

        btn_layout.addStretch()
        btn_layout.addWidget(self._create_btn)
        btn_layout.addWidget(self._edit_btn)
        btn_layout.addWidget(self._delete_btn)
        btn_layout.addWidget(self._reset_pwd_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._tab_widget.addTab(user_tab, "👥 用户列表")

    def _setup_assignment_tab(self):
        assign_tab = QWidget()
        layout = QVBoxLayout(assign_tab)

        # 教师选择
        teacher_group = QGroupBox("选择教师")
        teacher_layout = QHBoxLayout(teacher_group)
        teacher_label = QLabel("教师:")
        self._teacher_combo = QComboBox()
        self._teacher_combo.currentIndexChanged.connect(
            lambda: self._load_students_for_assignment()
        )

        teacher_layout.addWidget(teacher_label)
        teacher_layout.addWidget(self._teacher_combo)
        teacher_layout.addStretch()
        layout.addWidget(teacher_group)

        # 学生分配
        assign_layout = QHBoxLayout()

        # 未分配学生
        available_group = QGroupBox("未分配学生")
        available_layout = QVBoxLayout(available_group)
        self._available_students_list = QListWidget()
        self._available_students_list.setSelectionMode(QListWidget.ExtendedSelection)
        available_layout.addWidget(self._available_students_list)
        assign_layout.addWidget(available_group)

        # 操作按钮
        action_layout = QVBoxLayout()
        self._assign_btn = QPushButton("→ 分配 →")
        self._remove_btn = QPushButton("← 移除 ←")
        self._assign_btn.setFixedWidth(80)
        self._remove_btn.setFixedWidth(80)

        self._assign_btn.clicked.connect(self._on_assign_student)
        self._remove_btn.clicked.connect(self._on_assign_student)

        action_layout.addStretch()
        action_layout.addWidget(self._assign_btn)
        action_layout.addWidget(self._remove_btn)
        action_layout.addStretch()
        assign_layout.addLayout(action_layout)

        # 已分配学生
        assigned_group = QGroupBox("已分配学生")
        assigned_layout = QVBoxLayout(assigned_group)
        self._assigned_students_list = QListWidget()
        self._assigned_students_list.setSelectionMode(QListWidget.ExtendedSelection)
        assigned_layout.addWidget(self._assigned_students_list)
        assign_layout.addWidget(assigned_group)

        layout.addLayout(assign_layout)

        self._tab_widget.addTab(assign_tab, "📎 学生分配")

        self._load_teachers_for_assignment()

    def _load_users_to_table(self):
        user_manager = UserManager()
        users = user_manager.get_all_users()

        self._user_table.setRowCount(len(users))

        role_names = {
            UserRole.ADMIN: "管理员",
            UserRole.TEACHER: "教师",
            UserRole.STUDENT: "学生"
        }

        for i, user in enumerate(users):
            self._user_table.setItem(i, 0, QTableWidgetItem(user.username))
            self._user_table.setItem(i, 1, QTableWidgetItem(user.display_name))
            self._user_table.setItem(i, 2, QTableWidgetItem(role_names.get(user.role, "学生")))
            self._user_table.setItem(i, 3, QTableWidgetItem(user.teacher_id))
            self._user_table.setItem(i, 4, QTableWidgetItem(user.create_time.strftime("%Y-%m-%d")))
            self._user_table.setItem(i, 5, QTableWidgetItem(user.last_login_time.strftime("%Y-%m-%d %H:%M")))

    def _load_teachers_for_assignment(self):
        user_manager = UserManager()
        teachers = user_manager.get_teachers()

        self._teacher_combo.clear()
        for teacher in teachers:
            self._teacher_combo.addItem(teacher.display_name, teacher.username)

        self._load_students_for_assignment()

    def _load_students_for_assignment(self):
        if self._teacher_combo.currentIndex() < 0:
            return

        user_manager = UserManager()
        teacher_name = self._teacher_combo.currentData()
        all_students = user_manager.get_students()

        self._available_students_list.clear()
        self._assigned_students_list.clear()

        for student in all_students:
            item = QListWidgetItem(student.display_name)
            item.setData(Qt.UserRole, student.username)

            if student.teacher_id == teacher_name:
                self._assigned_students_list.addItem(item)
            elif not student.teacher_id:
                self._available_students_list.addItem(item)

    def _refresh_user_list(self):
        self._load_users_to_table()
        self._load_teachers_for_assignment()

    def _on_create_user(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("创建用户")
        dialog.setFixedSize(400, 450)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)

        input_group = QGroupBox("用户信息")
        grid = QGridLayout(input_group)
        grid.setVerticalSpacing(12)

        user_label = QLabel("用户名:")
        username_edit = QLineEdit()
        username_edit.setPlaceholderText("4-20个字符")

        name_label = QLabel("显示名称:")
        display_name_edit = QLineEdit()
        display_name_edit.setPlaceholderText("您的称呼")

        role_label = QLabel("角色:")
        role_combo = QComboBox()
        role_combo.addItem("学生", UserRole.STUDENT.value)
        role_combo.addItem("教师/家长", UserRole.TEACHER.value)
        role_combo.addItem("管理员", UserRole.ADMIN.value)

        pwd_label = QLabel("密码:")
        password_edit = QLineEdit()
        password_edit.setEchoMode(QLineEdit.Password)
        password_edit.setPlaceholderText("至少4个字符")

        confirm_label = QLabel("确认密码:")
        confirm_edit = QLineEdit()
        confirm_edit.setEchoMode(QLineEdit.Password)
        confirm_edit.setPlaceholderText("再次输入密码")

        grid.addWidget(user_label, 0, 0)
        grid.addWidget(username_edit, 0, 1)
        grid.addWidget(name_label, 1, 0)
        grid.addWidget(display_name_edit, 1, 1)
        grid.addWidget(role_label, 2, 0)
        grid.addWidget(role_combo, 2, 1)
        grid.addWidget(pwd_label, 3, 0)
        grid.addWidget(password_edit, 3, 1)
        grid.addWidget(confirm_label, 4, 0)
        grid.addWidget(confirm_edit, 4, 1)

        layout.addWidget(input_group)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("创建")
        cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        def on_ok():
            username = username_edit.text().strip()
            display_name = display_name_edit.text().strip()
            role = UserRole(role_combo.currentData())
            password = password_edit.text()
            confirm = confirm_edit.text()

            if len(username) < 4:
                QMessageBox.warning(dialog, "错误", "用户名至少4个字符")
                return

            if not display_name:
                display_name = username

            if len(password) < 4:
                QMessageBox.warning(dialog, "错误", "密码至少4个字符")
                return

            if password != confirm:
                QMessageBox.warning(dialog, "错误", "两次输入的密码不一致")
                return

            user_manager = UserManager()
            if user_manager.get_user(username):
                QMessageBox.warning(dialog, "错误", "用户名已存在")
                return

            new_user = UserInfo()
            new_user.username = username
            new_user.display_name = display_name
            new_user.role = role

            if user_manager.create_user(new_user, password):
                QMessageBox.information(dialog, "成功", "用户创建成功")
                dialog.accept()
                self._refresh_user_list()
            else:
                QMessageBox.warning(dialog, "错误", "创建失败")

        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(dialog.reject)

        dialog.exec()

    def _on_edit_user(self):
        row = self._user_table.currentRow()
        if row < 0:
            return

        username = self._user_table.item(row, 0).text()
        user_manager = UserManager()
        user = user_manager.get_user(username)

        if not user:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("编辑用户")
        dialog.setFixedSize(400, 350)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)

        input_group = QGroupBox("用户信息")
        grid = QGridLayout(input_group)
        grid.setVerticalSpacing(12)

        user_label = QLabel("用户名:")
        username_edit = QLineEdit(username)
        username_edit.setReadOnly(True)

        name_label = QLabel("显示名称:")
        display_name_edit = QLineEdit(user.display_name)

        role_label = QLabel("角色:")
        role_combo = QComboBox()
        role_combo.addItem("学生", UserRole.STUDENT.value)
        role_combo.addItem("教师/家长", UserRole.TEACHER.value)
        role_combo.addItem("管理员", UserRole.ADMIN.value)
        role_combo.setCurrentIndex(role_combo.findData(user.role.value))

        grid.addWidget(user_label, 0, 0)
        grid.addWidget(username_edit, 0, 1)
        grid.addWidget(name_label, 1, 0)
        grid.addWidget(display_name_edit, 1, 1)
        grid.addWidget(role_label, 2, 0)
        grid.addWidget(role_combo, 2, 1)

        layout.addWidget(input_group)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        def on_ok():
            user.display_name = display_name_edit.text().strip()
            user.role = UserRole(role_combo.currentData())

            if user_manager.update_user(user):
                QMessageBox.information(dialog, "成功", "用户信息已更新")
                dialog.accept()
                self._refresh_user_list()
            else:
                QMessageBox.warning(dialog, "错误", "更新失败")

        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(dialog.reject)

        dialog.exec()

    def _on_delete_user(self):
        row = self._user_table.currentRow()
        if row < 0:
            return

        username = self._user_table.item(row, 0).text()
        display_name = self._user_table.item(row, 1).text()

        if username == "admin":
            QMessageBox.warning(self, "错误", "不能删除管理员账户")
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f'确定要删除用户 "{display_name}" 吗？\n该用户的所有训练记录和成就将被永久删除！',
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            user_manager = UserManager()
            if user_manager.delete_user(username):
                QMessageBox.information(self, "成功", "用户已删除")
                self._refresh_user_list()
            else:
                QMessageBox.warning(self, "错误", "删除失败")

    def _on_reset_password(self):
        row = self._user_table.currentRow()
        if row < 0:
            return

        username = self._user_table.item(row, 0).text()
        display_name = self._user_table.item(row, 1).text()

        dialog = QDialog(self)
        dialog.setWindowTitle("重置密码")
        dialog.setFixedSize(350, 250)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)

        info_label = QLabel(f'为用户 "{display_name}" 重置密码')
        info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(info_label)

        input_group = QGroupBox("新密码")
        input_layout = QVBoxLayout(input_group)

        password_edit = QLineEdit()
        password_edit.setEchoMode(QLineEdit.Password)
        password_edit.setPlaceholderText("新密码（至少4个字符）")

        confirm_edit = QLineEdit()
        confirm_edit.setEchoMode(QLineEdit.Password)
        confirm_edit.setPlaceholderText("确认新密码")

        input_layout.addWidget(password_edit)
        input_layout.addWidget(confirm_edit)
        layout.addWidget(input_group)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("重置")
        cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        user_manager = UserManager()

        def on_ok():
            password = password_edit.text()
            confirm = confirm_edit.text()

            if len(password) < 4:
                QMessageBox.warning(dialog, "错误", "密码至少4个字符")
                return

            if password != confirm:
                QMessageBox.warning(dialog, "错误", "两次输入的密码不一致")
                return

            if user_manager.change_password(username, password, password):
                QMessageBox.information(dialog, "成功", "密码已重置")
                dialog.accept()
            else:
                QMessageBox.warning(dialog, "错误", "重置失败")

        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(dialog.reject)

        dialog.exec()

    def _on_assign_student(self):
        sender = self.sender()
        if not sender:
            return

        user_manager = UserManager()
        teacher_name = self._teacher_combo.currentData()

        if sender == self._assign_btn:
            selected = self._available_students_list.selectedItems()
            for item in selected:
                student_name = item.data(Qt.UserRole)
                user_manager.assign_student_to_teacher(student_name, teacher_name)
        elif sender == self._remove_btn:
            selected = self._assigned_students_list.selectedItems()
            for item in selected:
                student_name = item.data(Qt.UserRole)
                user_manager.remove_student_from_teacher(student_name)

        self._load_students_for_assignment()

    def _on_search_user(self):
        search_text = self._search_edit.text().strip().lower()

        for row in range(self._user_table.rowCount()):
            match = False
            for col in range(2):
                item = self._user_table.item(row, col)
                if item and search_text in item.text().lower():
                    match = True
                    break
            self._user_table.setRowHidden(row, not match and bool(search_text))

    def _apply_style_sheet(self):
        settings = GlobalSettings()
        bg = settings.background_color().name()
        text = settings.text_color().name()
        night_mode = settings.night_mode()

        table_bg = "#2d2d2d" if night_mode else "#ffffff"
        header_bg = "#3a3a3a" if night_mode else "#f0f0f0"
        line_edit_bg = "#3a3a3a" if night_mode else "#ffffff"
        border_color = "#555555" if night_mode else "#cccccc"

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text}; }}
            QTableWidget {{ background-color: {table_bg}; color: {text}; gridline-color: {border_color}; }}
            QTableWidget::item {{ padding: 8px; }}
            QTableWidget::item:selected {{ background-color: #4CAF50; color: white; }}
            QHeaderView::section {{ background-color: {header_bg}; color: {text}; padding: 8px; font-weight: bold; border: none; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none; border-radius: 5px; padding: 8px 15px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QPushButton:disabled {{ background-color: #999999; }}
            QLineEdit {{ background-color: {line_edit_bg}; color: {text}; border: 1px solid #4CAF50; border-radius: 5px; padding: 5px; }}
            QComboBox {{ background-color: {line_edit_bg}; color: {text}; border: 1px solid #4CAF50; border-radius: 5px; padding: 5px; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background-color: {line_edit_bg}; color: {text}; }}
            QListWidget {{ background-color: {line_edit_bg}; color: {text}; border: 1px solid #4CAF50; border-radius: 5px; }}
            QListWidget::item {{ padding: 5px; }}
            QListWidget::item:selected {{ background-color: #4CAF50; color: white; }}
            QGroupBox {{ color: {text}; border: 2px solid #4CAF50; border-radius: 8px; margin-top: 16px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 10px; }}
            QTabWidget::pane {{ background-color: {bg}; border: 1px solid #4CAF50; border-radius: 5px; }}
            QTabBar::tab {{ background-color: {header_bg}; color: {text}; padding: 8px 20px; }}
            QTabBar::tab:selected {{ background-color: #4CAF50; color: white; }}
            QTabBar::tab:hover {{ background-color: #45a049; color: white; }}
        """)