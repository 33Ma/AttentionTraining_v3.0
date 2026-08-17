# core/settings.py
import os
import json
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from PySide6.QtCore import QObject, Signal, QSettings, QDateTime
from PySide6.QtGui import QColor

from .database import Database


class DifficultyLevel(Enum):
    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"
    CUSTOM = "custom"


class CustomDifficulty:
    def __init__(self):
        self.spot_speed = 1500
        self.spot_size = 30
        self.spot_random_interval = False
        self.track_speed = 1500
        self.track_size = 20
        self.track_random_interval = False

    def to_dict(self) -> dict:
        return {
            'spot_speed': self.spot_speed,
            'spot_size': self.spot_size,
            'spot_random_interval': self.spot_random_interval,
            'track_speed': self.track_speed,
            'track_size': self.track_size,
            'track_random_interval': self.track_random_interval
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CustomDifficulty':
        diff = cls()
        diff.spot_speed = data.get('spot_speed', 1500)
        diff.spot_size = data.get('spot_size', 30)
        diff.spot_random_interval = data.get('spot_random_interval', False)
        diff.track_speed = data.get('track_speed', 1500)
        diff.track_size = data.get('track_size', 20)
        diff.track_random_interval = data.get('track_random_interval', False)
        return diff


class TrainingRecord:
    def __init__(self):
        self.date_time: Optional[QDateTime] = None
        self.duration_minutes: int = 0
        self.game_mode: str = ""
        self.difficulty: DifficultyLevel = DifficultyLevel.NORMAL
        self.avg_attention_score: int = 0
        self.total_blinks: int = 0
        self.game_score: int = 0
        self.avg_ear: float = 0.0

    def to_dict(self) -> dict:
        return {
            'date_time': self.date_time.toString("yyyy-MM-dd HH:mm:ss") if self.date_time else "",
            'duration_minutes': self.duration_minutes,
            'game_mode': self.game_mode,
            'difficulty': self.difficulty.value,
            'avg_attention_score': self.avg_attention_score,
            'total_blinks': self.total_blinks,
            'game_score': self.game_score,
            'avg_ear': self.avg_ear
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TrainingRecord':
        record = cls()
        if data.get('date_time'):
            record.date_time = QDateTime.fromString(data['date_time'], "yyyy-MM-dd HH:mm:ss")
        record.duration_minutes = data.get('duration_minutes', 0)
        record.game_mode = data.get('game_mode', "")
        record.difficulty = DifficultyLevel(data.get('difficulty', 'normal'))
        record.avg_attention_score = data.get('avg_attention_score', 0)
        record.total_blinks = data.get('total_blinks', 0)
        record.game_score = data.get('game_score', 0)
        record.avg_ear = data.get('avg_ear', 0.0)
        return record


class GlobalSettings(QObject):
    settings_changed = Signal()
    training_records_changed = Signal()
    user_changed = Signal(str)

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

        self.app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._db = Database()
        self.users_dir = os.path.join(self.app_dir, "users")
        os.makedirs(self.users_dir, exist_ok=True)

        self._current_user = "默认用户"
        self._settings: Optional[QSettings] = None
        self._user_settings_cache: Dict[str, QSettings] = {}

        # 默认设置
        self._ear_threshold = 0.25
        self._sensitivity = 5
        self._night_mode = False
        self._difficulty_level = DifficultyLevel.NORMAL
        self._custom_difficulty = CustomDifficulty()
        self._training_records: List[TrainingRecord] = []
        self._api_key = ""
        self._api_url = "https://api.openai.com/v1/chat/completions"
        self._ai_model = "gpt-3.5-turbo"
        self._ai_enabled = False
        self._wallpaper_path = ""
        self._wallpaper_enabled = False
        self._force_standard_bg_in_training = True

        self._load_user_list()
        self._load_current_user_settings()

    def _get_user_config_path(self, username: str) -> str:
        user_dir = os.path.join(self.users_dir, username)
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, "settings.ini")

    def _get_user_settings(self, username: str) -> QSettings:
        if username not in self._user_settings_cache:
            path = self._get_user_config_path(username)
            self._user_settings_cache[username] = QSettings(path, QSettings.Format.IniFormat)
        return self._user_settings_cache[username]


    @staticmethod
    def _record_date_to_string(value) -> str:
        if value is None:
            return ""
        if hasattr(value, "toString"):
            return value.toString("yyyy-MM-dd HH:mm:ss")
        return str(value)

    @staticmethod
    def _normalize_difficulty(value):
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if isinstance(value, int):
            value = {0: "easy", 1: "normal", 2: "hard", 3: "custom"}.get(value, "normal")
        try:
            return DifficultyLevel(value)
        except (ValueError, TypeError):
            return DifficultyLevel.NORMAL

    def _read_training_records_array(self, settings: QSettings, group: str, legacy: bool) -> List[TrainingRecord]:
        records: List[TrainingRecord] = []
        size = settings.beginReadArray(group)
        try:
            for i in range(size):
                settings.setArrayIndex(i)
                if legacy:
                    data = {
                        'date_time': self._record_date_to_string(settings.value("dateTime")),
                        'duration_minutes': int(settings.value("durationMinutes", 0)),
                        'game_mode': settings.value("gameMode", ""),
                        'difficulty': self._normalize_difficulty(settings.value("difficulty", 1)).value,
                        'avg_attention_score': int(settings.value("avgAttentionScore", 0)),
                        'total_blinks': int(settings.value("totalBlinks", 0)),
                        'game_score': int(settings.value("gameScore", 0)),
                        'avg_ear': float(settings.value("avgEAR", 0.0))
                    }
                else:
                    data = {
                        'date_time': self._record_date_to_string(settings.value("date_time")),
                        'duration_minutes': int(settings.value("duration_minutes", 0)),
                        'game_mode': settings.value("game_mode", ""),
                        'difficulty': self._normalize_difficulty(settings.value("difficulty", "normal")).value,
                        'avg_attention_score': int(settings.value("avg_attention_score", 0)),
                        'total_blinks': int(settings.value("total_blinks", 0)),
                        'game_score': int(settings.value("game_score", 0)),
                        'avg_ear': float(settings.value("avg_ear", 0.0))
                    }

                record = TrainingRecord.from_dict(data)
                if record.date_time and record.date_time.isValid():
                    records.append(record)
        finally:
            settings.endArray()
        return records

    def _read_training_records_from(self, settings: QSettings) -> List[TrainingRecord]:
        """????? QSettings ??????????????????"""
        records: List[TrainingRecord] = []
        seen = set()

        for group, legacy in (("training_records", False), ("trainingRecords", True)):
            for record in self._read_training_records_array(settings, group, legacy):
                key = (
                    record.date_time.toString("yyyy-MM-dd HH:mm:ss"),
                    record.game_mode,
                    record.avg_attention_score,
                    record.game_score,
                    record.total_blinks
                )
                if key in seen:
                    continue
                seen.add(key)
                records.append(record)

        return records

    def _write_training_records_to(self, settings: QSettings, records: List[TrainingRecord]):
        """?????????????????????????????????"""
        for group in ("training_records", "trainingRecords"):
            settings.beginGroup(group)
            settings.remove("")
            settings.endGroup()

        settings.beginWriteArray("training_records", len(records))
        try:
            for i, record in enumerate(records):
                settings.setArrayIndex(i)
                settings.setValue("date_time", record.date_time.toString("yyyy-MM-dd HH:mm:ss") if record.date_time else "")
                settings.setValue("duration_minutes", record.duration_minutes)
                settings.setValue("game_mode", record.game_mode)
                settings.setValue("difficulty", record.difficulty.value)
                settings.setValue("avg_attention_score", record.avg_attention_score)
                settings.setValue("total_blinks", record.total_blinks)
                settings.setValue("game_score", record.game_score)
                settings.setValue("avg_ear", record.avg_ear)
        finally:
            settings.endArray()
        settings.sync()

    def _load_user_list(self):
        """加载用户列表"""
        self._users = []
        if os.path.exists(self.users_dir):
            for item in os.listdir(self.users_dir):
                if os.path.isdir(os.path.join(self.users_dir, item)):
                    self._users.append(item)
        if not self._users:
            self._users = ["默认用户"]
            os.makedirs(os.path.join(self.users_dir, "默认用户"), exist_ok=True)

    def _load_current_user_settings(self):
        """加载当前用户设置"""
        if not self._current_user:
            return

        settings = self._get_user_settings(self._current_user)

        self._ear_threshold = float(settings.value("ear_threshold", 0.25))
        self._sensitivity = int(settings.value("sensitivity", 5))
        self._night_mode = settings.value("night_mode", False, type=bool)

        diff_str = settings.value("difficulty_level", "normal")
        try:
            self._difficulty_level = DifficultyLevel(diff_str)
        except ValueError:
            self._difficulty_level = DifficultyLevel.NORMAL

        custom_data = settings.value("custom_difficulty", {})
        if isinstance(custom_data, dict):
            self._custom_difficulty = CustomDifficulty.from_dict(custom_data)

        self._api_key = settings.value("ai/api_key", "")
        self._api_url = settings.value("ai/api_url", "https://api.openai.com/v1/chat/completions")
        self._ai_enabled = settings.value("ai/ai_enabled", False, type=bool)
        self._ai_model = settings.value("ai/ai_model", "gpt-3.5-turbo")

        self._wallpaper_path = settings.value("wallpaper/path", "")
        self._wallpaper_enabled = settings.value("wallpaper/enabled", False, type=bool)
        self._force_standard_bg_in_training = settings.value("wallpaper/force_standard_in_training", True, type=bool)

        self._load_training_records()

    def _save_current_user_settings(self):
        """保存当前用户设置"""
        if not self._current_user:
            return

        settings = self._get_user_settings(self._current_user)

        settings.setValue("ear_threshold", self._ear_threshold)
        settings.setValue("sensitivity", self._sensitivity)
        settings.setValue("night_mode", self._night_mode)
        settings.setValue("difficulty_level", self._difficulty_level.value)
        settings.setValue("custom_difficulty", self._custom_difficulty.to_dict())

        settings.setValue("ai/api_key", self._api_key)
        settings.setValue("ai/api_url", self._api_url)
        settings.setValue("ai/ai_enabled", self._ai_enabled)
        settings.setValue("ai/ai_model", self._ai_model)

        settings.setValue("wallpaper/path", self._wallpaper_path)
        settings.setValue("wallpaper/enabled", self._wallpaper_enabled)
        settings.setValue("wallpaper/force_standard_in_training", self._force_standard_bg_in_training)

        self._save_training_records()
        settings.sync()

    def _load_training_records(self):
        if not self._current_user:
            self._training_records = []
            return
        rows = self._db.fetch_training_records(self._current_user)
        self._training_records = [TrainingRecord.from_dict(row) for row in rows]

    def _save_training_records(self):
        if not self._current_user:
            return
        self._db.replace_training_records(
            self._current_user,
            [record.to_dict() for record in self._training_records],
        )


    def save_to_file(self):
        """
        保存当前用户设置到文件
        用于在程序退出或需要持久化时调用
        """
        self._save_current_user_settings()

    def load_from_file(self):
        """
        从文件加载当前用户设置
        用于在程序启动或切换用户时调用
        """
        self._load_current_user_settings()

    def sync(self):
        """
        同步设置到文件系统
        确保所有设置都已写入磁盘
        """
        if self._current_user:
            settings = self._get_user_settings(self._current_user)
            settings.sync()

    def reload(self):
        """
        重新加载当前用户的所有设置
        不保存当前修改，直接重新加载
        """
        # 清除缓存
        if self._current_user in self._user_settings_cache:
            del self._user_settings_cache[self._current_user]
        self._load_current_user_settings()
        self.settings_changed.emit()

    def save_and_sync(self):
        """
        保存并同步设置到文件
        组合 save_to_file 和 sync 操作
        """
        self._save_current_user_settings()
        if self._current_user:
            settings = self._get_user_settings(self._current_user)
            settings.sync()

    def export_settings(self, filepath: str) -> bool:
        """
        导出设置到指定文件
        Args:
            filepath: 目标文件路径
        Returns:
            是否导出成功
        """
        try:
            settings = self._get_user_settings(self._current_user)
            # 复制所有设置到目标文件
            export_settings = QSettings(filepath, QSettings.Format.IniFormat)
            for key in settings.allKeys():
                export_settings.setValue(key, settings.value(key))
            export_settings.sync()
            return True
        except Exception as e:
            print(f"Export settings failed: {e}")
            return False

    def import_settings(self, filepath: str) -> bool:
        """
        从指定文件导入设置
        Args:
            filepath: 源文件路径
        Returns:
            是否导入成功
        """
        try:
            import_settings = QSettings(filepath, QSettings.Format.IniFormat)
            settings = self._get_user_settings(self._current_user)
            for key in import_settings.allKeys():
                settings.setValue(key, import_settings.value(key))
            settings.sync()
            self._load_current_user_settings()
            self.settings_changed.emit()
            return True
        except Exception as e:
            print(f"Import settings failed: {e}")
            return False

    # ========== 用户管理 ==========

    def current_user(self) -> str:
        return self._current_user

    def set_current_user(self, username: str):
        if self._current_user == username:
            return
        self._save_current_user_settings()
        self._current_user = username
        self._load_current_user_settings()
        self.user_changed.emit(username)
        self.settings_changed.emit()

    def get_all_users(self) -> List[str]:
        return self._users.copy()

    def create_user(self, username: str):
        if username not in self._users:
            self._users.append(username)
            os.makedirs(os.path.join(self.users_dir, username), exist_ok=True)
            self._save_current_user_settings()

    def delete_user(self, username: str):
        if username == "默认用户":
            return
        if username in self._users:
            self._users.remove(username)
            user_dir = os.path.join(self.users_dir, username)
            import shutil
            if os.path.exists(user_dir):
                shutil.rmtree(user_dir)
            if self._current_user == username:
                self.set_current_user("默认用户")

    # ========== Getter/Setter ==========

    def ear_threshold(self) -> float:
        return self._ear_threshold

    def set_ear_threshold(self, value: float):
        if abs(self._ear_threshold - value) > 0.001:
            self._ear_threshold = value
            self._save_current_user_settings()
            self.settings_changed.emit()

    def sensitivity(self) -> int:
        return self._sensitivity

    def set_sensitivity(self, value: int):
        if self._sensitivity != value:
            self._sensitivity = max(1, min(10, value))
            self._save_current_user_settings()
            self.settings_changed.emit()

    def night_mode(self) -> bool:
        return self._night_mode

    def set_night_mode(self, enabled: bool):
        if self._night_mode != enabled:
            self._night_mode = enabled
            self._save_current_user_settings()
            self.settings_changed.emit()

    def background_color(self) -> QColor:
        return QColor(30, 30, 30) if self._night_mode else QColor(240, 240, 240)

    def text_color(self) -> QColor:
        return QColor(255, 255, 255) if self._night_mode else QColor(0, 0, 0)

    def difficulty_level(self) -> DifficultyLevel:
        return self._difficulty_level

    def set_difficulty_level(self, level: DifficultyLevel):
        if self._difficulty_level != level:
            self._difficulty_level = level
            self._save_current_user_settings()
            self.settings_changed.emit()

    def custom_difficulty(self) -> CustomDifficulty:
        return self._custom_difficulty

    def set_custom_difficulty(self, diff: CustomDifficulty):
        self._custom_difficulty = diff
        self._save_current_user_settings()
        self.settings_changed.emit()

    def get_spot_interval(self) -> int:
        if self._difficulty_level == DifficultyLevel.EASY:
            return 2500
        elif self._difficulty_level == DifficultyLevel.HARD:
            return 800
        elif self._difficulty_level == DifficultyLevel.CUSTOM:
            return self._custom_difficulty.spot_speed
        return 1500

    def get_spot_size(self) -> int:
        if self._difficulty_level == DifficultyLevel.EASY:
            return 40
        elif self._difficulty_level == DifficultyLevel.HARD:
            return 20
        elif self._difficulty_level == DifficultyLevel.CUSTOM:
            return self._custom_difficulty.spot_size
        return 30

    def get_track_interval(self) -> int:
        if self._difficulty_level == DifficultyLevel.EASY:
            return 2500
        elif self._difficulty_level == DifficultyLevel.HARD:
            return 700
        elif self._difficulty_level == DifficultyLevel.CUSTOM:
            return self._custom_difficulty.track_speed
        return 1500

    def get_track_size(self) -> int:
        if self._difficulty_level == DifficultyLevel.EASY:
            return 30
        elif self._difficulty_level == DifficultyLevel.HARD:
            return 12
        elif self._difficulty_level == DifficultyLevel.CUSTOM:
            return self._custom_difficulty.track_size
        return 20

    def api_key(self) -> str:
        return self._api_key

    def set_api_key(self, key: str):
        if self._api_key != key:
            self._api_key = key
            self._save_current_user_settings()

    def api_url(self) -> str:
        return self._api_url

    def set_api_url(self, url: str):
        if self._api_url != url:
            self._api_url = url
            self._save_current_user_settings()

    def ai_enabled(self) -> bool:
        return self._ai_enabled

    def set_ai_enabled(self, enabled: bool):
        if self._ai_enabled != enabled:
            self._ai_enabled = enabled
            self._save_current_user_settings()
            self.settings_changed.emit()

    def ai_model(self) -> str:
        return self._ai_model

    def set_ai_model(self, model: str):
        if self._ai_model != model:
            self._ai_model = model
            self._save_current_user_settings()

    def training_records(self) -> List[TrainingRecord]:
        return self._training_records.copy()

    def add_training_record(self, record: TrainingRecord):
        self._training_records.insert(0, record)
        if len(self._training_records) > 100:
            self._training_records = self._training_records[:100]
        self._save_training_records()
        self.training_records_changed.emit()

    def clear_training_records(self):
        self._training_records.clear()
        self._db.clear_training_records(self._current_user)
        self.training_records_changed.emit()

    def training_records_for_user(self, username: str) -> List[TrainingRecord]:
        if not username:
            return []
        rows = self._db.fetch_training_records(username)
        return [TrainingRecord.from_dict(row) for row in rows]

    def add_training_record_for_user(self, username: str, record: TrainingRecord):
        if not username:
            return
        records = self.training_records_for_user(username)
        records.insert(0, record)
        if len(records) > 100:
            records = records[:100]
        self._db.replace_training_records(
            username,
            [item.to_dict() for item in records],
        )
        if username == self._current_user:
            self._training_records = records
        self.training_records_changed.emit()

    def clear_training_records_for_user(self, username: str):
        if not username:
            return
        self._db.clear_training_records(username)
        if username == self._current_user:
            self._training_records.clear()
        self.training_records_changed.emit()


    def wallpaper_path(self) -> str:
        return self._wallpaper_path

    def set_wallpaper_path(self, path: str):
        if self._wallpaper_path != path:
            self._wallpaper_path = path
            self._save_current_user_settings()
            self.settings_changed.emit()

    def wallpaper_enabled(self) -> bool:
        return self._wallpaper_enabled

    def set_wallpaper_enabled(self, enabled: bool):
        if self._wallpaper_enabled != enabled:
            self._wallpaper_enabled = enabled
            self._save_current_user_settings()
            self.settings_changed.emit()

    def force_standard_bg_in_training(self) -> bool:
        return self._force_standard_bg_in_training

    def set_force_standard_bg_in_training(self, force: bool):
        if self._force_standard_bg_in_training != force:
            self._force_standard_bg_in_training = force
            self._save_current_user_settings()
            self.settings_changed.emit()

    def get_message_box_style_sheet(self) -> str:
        bg = self.background_color().name()
        text = self.text_color().name()
        return f"""
            QMessageBox {{ background-color: {bg}; }}
            QLabel {{ color: {text}; font-size: 12px; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 5px; padding: 8px 16px; min-width: 80px; font-size: 12px; }}
            QPushButton:hover {{ background-color: #45a049; }}
        """