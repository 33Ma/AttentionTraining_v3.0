# core/user_session.py
from typing import List, Optional
from PySide6.QtCore import QObject, Signal, QMutex, QReadWriteLock, QRecursiveMutex

from .settings import GlobalSettings, TrainingRecord
from .user_manager import UserManager
from .achievement_manager import AchievementManager

class UserSession(QObject):
    user_switched = Signal(str, str)
    user_data_locked = Signal(str)
    user_data_unlocked = Signal(str)
    user_access_denied = Signal(str, str)

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

        self._current_user = ""
        self._previous_user = ""
        self._training_active = False
        self._user_locks = {}
        self._locked_users = set()
        self._lock = QReadWriteLock()  # 直接创建锁，不是传入现有锁

        # 监听用户管理器的登录/登出事件
        user_manager = UserManager()
        user_manager.user_logged_in.connect(self._on_user_logged_in)
        user_manager.user_logged_out.connect(self._on_user_logged_out)

        # 会话可能在登录完成之后才被首次实例化（例如点击“开始训练”时），
        # 此时登录信号已经错过，需同步当前已登录用户；
        # 否则训练数据会被错误地归属到未登录的空用户。
        if user_manager.is_logged_in():
            self._current_user = user_manager.current_username()

    def _on_user_logged_in(self, username: str, role):
        self.switch_user(username)

    def _on_user_logged_out(self):
        """登出：清空会话用户，不再回退到“默认用户”。"""
        old_user = self._current_user
        if not old_user:
            return
        self._previous_user = old_user
        self._current_user = ""
        try:
            GlobalSettings().set_current_user("")
        except Exception as e:
            print(f"UserSession: Failed to clear GlobalSettings user: {e}")
        self._unlock_user_data(old_user)
        self.user_switched.emit(old_user, "")

    def switch_user(self, username: str) -> bool:
        if self._training_active:
            self.user_access_denied.emit(username, "switch_user_training_active")
            return False

        if self._current_user == username:
            return True

        if not self._lock_user_data(username):
            self.user_access_denied.emit(username, "user_data_locked")
            return False

        old_user = self._current_user
        self._previous_user = old_user
        self._current_user = username

        try:
            settings = GlobalSettings()
            settings.set_current_user(username)
        except Exception as e:
            print(f"UserSession: Failed to switch GlobalSettings to {username}: {e}")
            try:
                settings.set_current_user(old_user)
            except Exception:
                pass
            self._current_user = old_user
            self._unlock_user_data(username)
            self.user_access_denied.emit(username, "switch_user_failed")
            return False

        try:
            am = AchievementManager()
            am.switch_user(username)
            print(f"UserSession: AchievementManager switched to {username}")
        except Exception as e:
            print(f"UserSession: Failed to switch AchievementManager: {e}")

        self.user_switched.emit(old_user, username)
        if old_user:
            self._unlock_user_data(old_user)
        return True

    def _lock_user_data(self, username: str, timeout_ms: int = 1000) -> bool:
        if not username:
            return False

        self._lock.lockForWrite()
        try:
            if username in self._locked_users:
                return True
            if username not in self._user_locks:
                self._user_locks[username] = QMutex()
            mutex = self._user_locks[username]
        finally:
            self._lock.unlock()

        if not mutex.tryLock(timeout_ms):
            return False

        self._lock.lockForWrite()
        try:
            self._locked_users.add(username)
        finally:
            self._lock.unlock()

        self.user_data_locked.emit(username)
        return True

    def _unlock_user_data(self, username: str):
        if not username:
            return

        self._lock.lockForWrite()
        try:
            if username not in self._locked_users:
                return
            self._locked_users.discard(username)
            mutex = self._user_locks.get(username)
        finally:
            self._lock.unlock()

        if mutex:
            mutex.unlock()
            self.user_data_unlocked.emit(username)

    def _try_lock_user_data(self, username: str, timeout_ms: int = 1000) -> bool:
        return self._lock_user_data(username, timeout_ms)

    def current_user(self) -> str:
        return self._current_user

    def previous_user(self) -> str:
        return self._previous_user

    def is_training_active(self) -> bool:
        return self._training_active

    def set_training_active(self, active: bool):
        self._training_active = active

    def get_user_training_records(self, username: str) -> List[TrainingRecord]:
        """???????????????????????????"""
        user_manager = UserManager()
        if not user_manager.can_view_student(username):
            self.user_access_denied.emit(username, "student_data_forbidden")
            return []
        return GlobalSettings().training_records_for_user(username)

    def clear_user_training_records(self, username: str) -> bool:
        """???????????????????"""
        user_manager = UserManager()
        if not user_manager.can_view_student(username):
            self.user_access_denied.emit(username, "student_data_forbidden")
            return False
        GlobalSettings().clear_training_records_for_user(username)
        return True

    def add_training_record_for_user(self, username: str, record: TrainingRecord) -> bool:
        """???????????????????"""
        user_manager = UserManager()
        if not user_manager.can_view_student(username):
            self.user_access_denied.emit(username, "student_data_forbidden")
            return False
        GlobalSettings().add_training_record_for_user(username, record)
        return True

    def settings(self) -> GlobalSettings:
        return GlobalSettings()