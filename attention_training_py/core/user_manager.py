# core/user_manager.py
import os
import hashlib
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict
from PySide6.QtCore import QObject, Signal

from .database import Database
from .paths import app_data_dir


class UserRole(Enum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class UserInfo:
    def __init__(self):
        self.username: str = ""
        self.display_name: str = ""
        self.role: UserRole = UserRole.STUDENT
        self.teacher_id: str = ""
        self.student_ids: List[str] = []
        self.create_time: datetime = datetime.now()
        self.last_login_time: datetime = datetime.now()

    def to_dict(self) -> dict:
        return {
            'username': self.username,
            'display_name': self.display_name,
            'role': self.role.value,
            'teacher_id': self.teacher_id,
            'student_ids': self.student_ids,
            'create_time': self.create_time.isoformat(),
            'last_login_time': self.last_login_time.isoformat()
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'UserInfo':
        user = cls()
        user.username = data.get('username', '')
        user.display_name = data.get('display_name', '')
        user.role = UserRole(data.get('role', 'student'))
        user.teacher_id = data.get('teacher_id', '')
        user.student_ids = data.get('student_ids', [])
        if data.get('create_time'):
            try:
                user.create_time = datetime.fromisoformat(data['create_time'])
            except:
                user.create_time = datetime.now()
        if data.get('last_login_time'):
            try:
                user.last_login_time = datetime.fromisoformat(data['last_login_time'])
            except:
                user.last_login_time = datetime.now()
        return user


class UserManager(QObject):
    user_logged_in = Signal(str, object)
    user_logged_out = Signal()
    user_list_changed = Signal()
    student_assigned = Signal(str, str)

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        super().__init__()
        self._initialized = True

        self.app_dir = app_data_dir()
        self._db = Database()
        self._users: Dict[str, UserInfo] = {}
        self._passwords: Dict[str, str] = {}
        self._current_user: Optional[UserInfo] = None

        self._load_users()

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def _create_default_users(self):
        admin = UserInfo()
        admin.username = "admin"
        admin.display_name = "系统管理员"
        admin.role = UserRole.ADMIN
        admin.create_time = datetime.now()
        self._users[admin.username] = admin
        self._passwords[admin.username] = self._hash_password("admin123")

        teacher = UserInfo()
        teacher.username = "teacher"
        teacher.display_name = "张老师"
        teacher.role = UserRole.TEACHER
        teacher.create_time = datetime.now()
        self._users[teacher.username] = teacher
        self._passwords[teacher.username] = self._hash_password("teacher123")

        student = UserInfo()
        student.username = "student"
        student.display_name = "小明"
        student.role = UserRole.STUDENT
        student.teacher_id = "teacher"
        student.create_time = datetime.now()
        self._users[student.username] = student
        self._passwords[student.username] = self._hash_password("student123")

        self._users["teacher"].student_ids.append("student")
        self._save_users()

    def _load_users(self):
        try:
            rows = self._db.fetch_users()
            for row in rows:
                user_data = {
                    'username': row['username'],
                    'display_name': row['display_name'],
                    'role': row['role'],
                    'teacher_id': row['teacher_id'],
                    'student_ids': [],
                    'create_time': row['create_time'],
                    'last_login_time': row['last_login_time']
                }
                user = UserInfo.from_dict(user_data)
                self._users[user.username] = user
                self._passwords[user.username] = row['password_hash']

            # Derive teacher.student_ids from student.teacher_id stored in SQLite.
            for user in self._users.values():
                if user.role == UserRole.STUDENT and user.teacher_id:
                    teacher = self._users.get(user.teacher_id)
                    if teacher and user.username not in teacher.student_ids:
                        teacher.student_ids.append(user.username)

            if not self._users or 'admin' not in self._users:
                self._create_default_users()

        except Exception as e:
            print(f"Error loading users: {e}")
            self._create_default_users()

    def _save_users(self):
        try:
            users_data = []
            for user in self._users.values():
                data = user.to_dict()
                data['password_hash'] = self._passwords.get(user.username, "")
                users_data.append(data)
            self._db.replace_users(users_data)
        except Exception as e:
            print(f"Error saving users: {e}")


    def reload_users(self):
        """重新从数据库加载用户列表（导入学生数据后调用）。"""
        self._load_users()
    def login(self, username: str, password: str) -> bool:
        if username not in self._users:
            return False

        if self._passwords.get(username) != self._hash_password(password):
            return False

        self._current_user = self._users[username]
        self._current_user.last_login_time = datetime.now()
        self._users[username] = self._current_user
        self._save_users()

        self.user_logged_in.emit(username, self._current_user.role)
        return True

    def logout(self):
        self._current_user = None
        self.user_logged_out.emit()

    def create_user(self, user: UserInfo, password: str) -> bool:
        if user.username in self._users:
            return False
        if len(password) < 4:
            return False

        user.create_time = datetime.now()
        self._users[user.username] = user
        self._passwords[user.username] = self._hash_password(password)

        user_dir = os.path.join(self.app_dir, "users", user.username)
        os.makedirs(user_dir, exist_ok=True)

        self._save_users()
        self.user_list_changed.emit()
        return True

    def delete_user(self, username: str) -> bool:
        if username == "admin":
            return False
        if username not in self._users:
            return False

        user = self._users[username]
        if user.role == UserRole.TEACHER:
            for student_id in user.student_ids:
                if student_id in self._users:
                    self._users[student_id].teacher_id = ""

        if user.role == UserRole.STUDENT and user.teacher_id:
            teacher = self._users.get(user.teacher_id)
            if teacher and username in teacher.student_ids:
                teacher.student_ids.remove(username)

        del self._users[username]
        if username in self._passwords:
            del self._passwords[username]
        self._db.clear_training_records(username)

        import shutil
        user_dir = os.path.join(self.app_dir, "users", username)
        if os.path.exists(user_dir):
            shutil.rmtree(user_dir)

        self._save_users()
        self.user_list_changed.emit()
        return True

    def update_user(self, user: UserInfo) -> bool:
        if user.username not in self._users:
            return False

        old_user = self._users[user.username]

        # ??????????????????????????/?????????
        if old_user.role == UserRole.TEACHER and user.role != UserRole.TEACHER:
            for student_id in old_user.student_ids:
                student = self._users.get(student_id)
                if student and student.role == UserRole.STUDENT:
                    student.teacher_id = ""
            user.student_ids = []

        if old_user.role == UserRole.STUDENT and user.role != UserRole.STUDENT:
            teacher = self._users.get(old_user.teacher_id) if old_user.teacher_id else None
            if teacher and user.username in teacher.student_ids:
                teacher.student_ids.remove(user.username)
            user.teacher_id = ""

        self._users[user.username] = user
        self._save_users()
        self.user_list_changed.emit()
        return True

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        if username not in self._users:
            return False
        if self._passwords.get(username) != self._hash_password(old_password):
            return False
        if len(new_password) < 4:
            return False
        self._passwords[username] = self._hash_password(new_password)
        self._save_users()
        return True

    def get_user(self, username: str) -> Optional[UserInfo]:
        return self._users.get(username)

    def get_all_users(self) -> List[UserInfo]:
        return list(self._users.values())

    def get_students(self) -> List[UserInfo]:
        return [u for u in self._users.values() if u.role == UserRole.STUDENT]

    def get_teachers(self) -> List[UserInfo]:
        return [u for u in self._users.values() if u.role == UserRole.TEACHER]

    def get_students_by_teacher(self, teacher_id: str) -> List[UserInfo]:
        return [u for u in self._users.values()
                if u.role == UserRole.STUDENT and u.teacher_id == teacher_id]

    def assign_student_to_teacher(self, student_name: str, teacher_name: str) -> bool:
        if student_name not in self._users or teacher_name not in self._users:
            return False

        student = self._users[student_name]
        teacher = self._users[teacher_name]

        if student.role != UserRole.STUDENT or teacher.role != UserRole.TEACHER:
            return False

        old_teacher = self._users.get(student.teacher_id) if student.teacher_id else None
        if old_teacher and student_name in old_teacher.student_ids:
            old_teacher.student_ids.remove(student_name)

        student.teacher_id = teacher_name
        if student_name not in teacher.student_ids:
            teacher.student_ids.append(student_name)

        self._save_users()
        self.student_assigned.emit(student_name, teacher_name)
        self.user_list_changed.emit()
        return True

    def remove_student_from_teacher(self, student_name: str) -> bool:
        if student_name not in self._users:
            return False

        student = self._users[student_name]
        if student.role != UserRole.STUDENT:
            return False

        old_teacher = self._users.get(student.teacher_id) if student.teacher_id else None
        if old_teacher and student_name in old_teacher.student_ids:
            old_teacher.student_ids.remove(student_name)

        student.teacher_id = ""
        self._save_users()
        self.user_list_changed.emit()
        return True

    def is_logged_in(self) -> bool:
        return self._current_user is not None

    def current_user(self) -> Optional[UserInfo]:
        return self._current_user

    def current_user_role(self) -> Optional[UserRole]:
        return self._current_user.role if self._current_user else None

    def current_username(self) -> str:
        return self._current_user.username if self._current_user else ""

    def can_view_student(self, student_name: str) -> bool:
        if not self.is_logged_in():
            return False
        if self._current_user.role == UserRole.ADMIN:
            return True
        if self._current_user.role == UserRole.TEACHER:
            student = self._users.get(student_name)
            return (
                student_name in self._current_user.student_ids
                or (student is not None
                    and student.role == UserRole.STUDENT
                    and student.teacher_id == self._current_user.username)
            )
        if self._current_user.role == UserRole.STUDENT:
            return self._current_user.username == student_name
        return False

    def can_manage_settings(self) -> bool:
        return self.is_logged_in() and self._current_user.role in (UserRole.ADMIN, UserRole.TEACHER)

    def can_manage_users(self) -> bool:
        return self.is_logged_in() and self._current_user.role == UserRole.ADMIN