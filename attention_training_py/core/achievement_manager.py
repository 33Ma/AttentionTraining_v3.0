# core/achievement_manager.py
import os
import json
from enum import Enum, auto
from datetime import datetime
from typing import List, Dict, Optional
from PySide6.QtCore import QObject, Signal, QDateTime, QMutex, QMutexLocker
from .settings import GlobalSettings


class AchievementType(Enum):
    ATTENTION_MASTER = auto()
    EAGLE_EYE = auto()
    STEADY_FOCUS = auto()
    BLINK_CONTROLLER = auto()
    PERFECT_STREAK = auto()
    MARATHONER = auto()
    FINDER_NEWBIE = auto()
    TRACKER_PRO = auto()
    PERFECT_GAME = auto()
    ALL_ROUNDER = auto()
    GAZE_MASTER = auto()
    STEADY_GAZE = auto()
    FOCUS_CHAMPION = auto()


class Achievement:
    def __init__(self):
        self.type: AchievementType = AchievementType.ATTENTION_MASTER
        self.name: str = ""
        self.description: str = ""
        self.unlocked: bool = False
        self.unlock_time: Optional[QDateTime] = None
        self.progress: int = 0
        self.target: int = 1
        self.progress_text: str = ""

    def to_dict(self) -> dict:
        return {
            'type': self.type.value,
            'name': self.name,
            'description': self.description,
            'unlocked': self.unlocked,
            'unlock_time': self.unlock_time.toString("yyyy-MM-dd HH:mm:ss") if self.unlock_time else "",
            'progress': self.progress,
            'target': self.target,
            'progress_text': self.progress_text
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Achievement':
        ach = cls()
        ach.type = AchievementType(data.get('type', 1))
        ach.name = data.get('name', '')
        ach.description = data.get('description', '')
        ach.unlocked = data.get('unlocked', False)
        if data.get('unlock_time'):
            ach.unlock_time = QDateTime.fromString(data['unlock_time'], "yyyy-MM-dd HH:mm:ss")
        ach.progress = data.get('progress', 0)
        ach.target = data.get('target', 1)
        ach.progress_text = data.get('progress_text', '')
        return ach


class AchievementManager(QObject):
    achievement_unlocked = Signal(str)
    achievement_progress_updated = Signal(str, int)
    user_achievements_loaded = Signal(str)

    _instance = None
    _loading_lock = QMutex()  # 类级别的加载锁

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
        self._achievements: Dict[AchievementType, Achievement] = {}
        self._total_training_minutes = 0
        self._current_user = ""
        self.MAX_PROGRESS = 100

        self._mutex = QMutex()
        self._is_loading = False  # 防止重入

        self._total_focused_time = 0
        self._best_gaze_score = 0
        self._consecutive_focused_frames = 0
        self._max_consecutive_focused_frames = 0

        self._init_achievements()
        print("AchievementManager initialized (waiting for user load)")

    def _get_other_achievements_count(self) -> int:
        return sum(1 for ach_type in self._achievements.keys()
                   if ach_type != AchievementType.ALL_ROUNDER)

    def _init_achievements(self):
        achievements_data = [
            (AchievementType.ATTENTION_MASTER, "🧠 注意力大师", "单次训练平均注意力分数达到80分以上", 80),
            (AchievementType.EAGLE_EYE, "👁️ 火眼金睛", "在找茬模式中发现100个差异点", 100),
            (AchievementType.STEADY_FOCUS, "🎯 稳如泰山", "连续30秒保持注意力分数70分以上", 30),
            (AchievementType.BLINK_CONTROLLER, "😎 眨眼控制师", "单次训练眨眼次数少于10次", 10),
            (AchievementType.PERFECT_STREAK, "⚡ 完美连击", "达成20连击", 20),
            (AchievementType.MARATHONER, "🏃 马拉松选手", "累计训练时长达到60分钟", 60),
            (AchievementType.FINDER_NEWBIE, "🔍 找茬新手", "完成第一次找茬模式训练", 1),
            (AchievementType.TRACKER_PRO, "🎯 追踪专家", "完成第一次动态追踪模式训练", 1),
            (AchievementType.PERFECT_GAME, "💎 完美游戏", "单次训练中同时达成：注意力80+、游戏得分500+、连击10+", 100),
            (AchievementType.ALL_ROUNDER, "👑 全能选手", "解锁所有其他成就", 0),
            (AchievementType.GAZE_MASTER, "👀 注视大师", "单次训练中注视专注度达到90分以上", 90),
            (AchievementType.STEADY_GAZE, "🎯 稳定注视", "单次训练中连续60秒注视偏离距离小于0.15", 60),
            (AchievementType.FOCUS_CHAMPION, "⭐ 专注冠军", "累计专注时间达到30分钟（注视距离<0.2）", 1800),
        ]

        self._achievements.clear()
        for ach_type, name, desc, target in achievements_data:
            ach = Achievement()
            ach.type = ach_type
            ach.name = name
            ach.description = desc
            ach.target = target
            if ach_type == AchievementType.ALL_ROUNDER:
                other_count = self._get_other_achievements_count()
                ach.progress_text = f"0/{other_count}"
            else:
                ach.progress_text = f"0/{target}" if target > 0 else "0/0"
            self._achievements[ach_type] = ach

    def _get_user_achievement_path(self, username: str = None) -> str:
        if username is None:
            if self._current_user:
                username = self._current_user
            else:
                settings = GlobalSettings()
                username = settings.current_user()

        if not username:
            username = "默认用户"

        user_dir = os.path.join(self.app_dir, "users", username)
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, "achievements.json")

    def load_current_user_data(self):
        """加载当前用户数据（公共接口）"""
        self._load_current_user_data()

    def _load_current_user_data(self):
        """加载当前用户数据 - 修复死锁版本"""
        # 防止重入
        if self._is_loading:
            print("AchievementManager: Already loading, skipping")
            return

        # 使用类级别锁防止并发加载
        if not AchievementManager._loading_lock.tryLock():
            print("AchievementManager: Another load in progress, skipping")
            return

        try:
            self._is_loading = True
            print(f"AchievementManager: Loading data for user: {self._current_user}")

            settings = GlobalSettings()
            user = settings.current_user()

            if self._current_user:
                user = self._current_user

            if not user:
                user = "默认用户"

            # 重置成就数据
            for ach in self._achievements.values():
                ach.unlocked = False
                ach.progress = 0
                ach.unlock_time = None
                if ach.type == AchievementType.ALL_ROUNDER:
                    other_count = self._get_other_achievements_count()
                    ach.progress_text = f"0/{other_count}"
                else:
                    ach.progress_text = f"0/{ach.target}" if ach.target > 0 else "0/0"

            self._total_training_minutes = 0
            self._total_focused_time = 0
            self._best_gaze_score = 0
            self._consecutive_focused_frames = 0
            self._max_consecutive_focused_frames = 0

            self._current_user = user

            # 尝试加载用户数据
            path = self._get_user_achievement_path(user)
            if os.path.exists(path):
                self._load_from_file_unsafe(path)
                print(f"AchievementManager: Loaded data from {path}")
            else:
                print(f"AchievementManager: No achievement file found for user {user}, creating defaults")
                self._save_to_file_unsafe()

            self.user_achievements_loaded.emit(user)

        except Exception as e:
            print(f"AchievementManager: Error loading user data: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._is_loading = False
            AchievementManager._loading_lock.unlock()

    def _load_from_file_unsafe(self, path: str):
        """从文件加载数据（不加锁，内部调用）"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            achievements_data = data.get('achievements', [])
            self._total_training_minutes = data.get('total_training_minutes', 0)
            self._total_focused_time = data.get('total_focused_time', 0)
            self._best_gaze_score = data.get('best_gaze_score', 0)
            self._consecutive_focused_frames = data.get('consecutive_focused_frames', 0)
            self._max_consecutive_focused_frames = data.get('max_consecutive_focused_frames', 0)

            for ach_data in achievements_data:
                ach_type = AchievementType(ach_data.get('type', 1))
                if ach_type in self._achievements:
                    saved_ach = Achievement.from_dict(ach_data)
                    self._achievements[ach_type] = saved_ach

            allrounder = self._achievements.get(AchievementType.ALL_ROUNDER)
            if allrounder and allrounder.unlocked:
                other_count = self._get_other_achievements_count()
                allrounder.progress_text = f"{other_count}/{other_count}"

        except Exception as e:
            print(f"AchievementManager: Error loading from file {path}: {e}")

    def _save_to_file_unsafe(self):
        """保存数据到文件（不加锁，内部调用）"""
        if not self._current_user:
            print("AchievementManager: No current user, skipping save")
            return

        try:
            path = self._get_user_achievement_path(self._current_user)

            data = {
                'achievements': [ach.to_dict() for ach in self._achievements.values()],
                'total_training_minutes': self._total_training_minutes,
                'total_focused_time': self._total_focused_time,
                'best_gaze_score': self._best_gaze_score,
                'consecutive_focused_frames': self._consecutive_focused_frames,
                'max_consecutive_focused_frames': self._max_consecutive_focused_frames
            }

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"AchievementManager: Saved data to {path}")

        except Exception as e:
            print(f"AchievementManager: Error saving achievements: {e}")

    def switch_user(self, username: str):
        """切换用户 - 修复防重入版本"""
        if not username:
            username = "默认用户"

        if self._current_user == username:
            print(f"AchievementManager.switch_user: Already on {username}, skipping")
            return

        print(f"AchievementManager.switch_user: Switching to {username}")

        # 使用锁保护整个切换过程
        locker = QMutexLocker(self._mutex)
        try:
            self._current_user = username
            self._load_current_user_data()
            self.user_achievements_loaded.emit(username)
            print(f"AchievementManager.switch_user: Switched to {username}")
        except Exception as e:
            print(f"AchievementManager.switch_user: Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            locker.unlock()

    def get_all_achievements(self) -> List[Achievement]:
        return list(self._achievements.values())

    def get_unlocked_count(self) -> int:
        return sum(1 for ach in self._achievements.values() if ach.unlocked)

    def get_total_count(self) -> int:
        return len(self._achievements)

    def get_achievement(self, ach_type: AchievementType) -> Optional[Achievement]:
        return self._achievements.get(ach_type)

    def add_training_minutes(self, minutes: int):
        if minutes <= 0:
            return
        self._total_training_minutes += minutes
        self._check_training_duration_achievement(self._total_training_minutes)
        self._save_to_file_unsafe()

    def check_attention_achievement(self, attention_score: int):
        ach = self._achievements[AchievementType.ATTENTION_MASTER]
        if not ach.unlocked and attention_score >= ach.target:
            self._unlock_achievement(AchievementType.ATTENTION_MASTER)
        elif not ach.unlocked:
            progress = min(self.MAX_PROGRESS, (attention_score * self.MAX_PROGRESS) // ach.target)
            self._update_progress(AchievementType.ATTENTION_MASTER, progress)

    def check_blink_achievement(self, blink_count: int):
        ach = self._achievements[AchievementType.BLINK_CONTROLLER]
        if not ach.unlocked and blink_count <= ach.target and blink_count > 0:
            self._unlock_achievement(AchievementType.BLINK_CONTROLLER)
        elif not ach.unlocked and blink_count > 0:
            progress = min(self.MAX_PROGRESS,
                          max(0, int((1.0 - (blink_count - ach.target) / 50.0) * self.MAX_PROGRESS)))
            self._update_progress(AchievementType.BLINK_CONTROLLER, progress)

    def check_game_score_achievement(self, game_score: int, game_mode: str):
        if game_mode == "find_difference":
            ach = self._achievements[AchievementType.EAGLE_EYE]
            if not ach.unlocked:
                progress = min(self.MAX_PROGRESS, (game_score // 10 * self.MAX_PROGRESS) // ach.target)
                self._update_progress(AchievementType.EAGLE_EYE, progress)
                if game_score // 10 >= ach.target:
                    self._unlock_achievement(AchievementType.EAGLE_EYE)

            finder_ach = self._achievements[AchievementType.FINDER_NEWBIE]
            if not finder_ach.unlocked and game_score > 0:
                self._unlock_achievement(AchievementType.FINDER_NEWBIE)
        elif game_mode == "dynamic_tracking":
            tracker_ach = self._achievements[AchievementType.TRACKER_PRO]
            if not tracker_ach.unlocked and game_score > 0:
                self._unlock_achievement(AchievementType.TRACKER_PRO)

    def check_consecutive_hit_achievement(self, consecutive_hits: int):
        ach = self._achievements[AchievementType.PERFECT_STREAK]
        if not ach.unlocked:
            progress = min(self.MAX_PROGRESS, (consecutive_hits * self.MAX_PROGRESS) // ach.target)
            self._update_progress(AchievementType.PERFECT_STREAK, progress)
            if consecutive_hits >= ach.target:
                self._unlock_achievement(AchievementType.PERFECT_STREAK)

    def check_training_duration_achievement(self, total_minutes: int):
        ach = self._achievements[AchievementType.MARATHONER]
        if not ach.unlocked:
            progress = min(self.MAX_PROGRESS, (total_minutes * self.MAX_PROGRESS) // ach.target)
            self._update_progress(AchievementType.MARATHONER, progress)
            if total_minutes >= ach.target:
                self._unlock_achievement(AchievementType.MARATHONER)

    def check_perfect_game_achievement(self, attention_score: int, game_score: int, consecutive_hits: int):
        ach = self._achievements[AchievementType.PERFECT_GAME]
        if not ach.unlocked:
            perfect = attention_score >= 80 and game_score >= 500 and consecutive_hits >= 10
            if perfect:
                self._unlock_achievement(AchievementType.PERFECT_GAME)
            else:
                ach.progress_text = f"注意{attention_score}/80 得分{game_score}/500 连击{consecutive_hits}/10"
                self.achievement_progress_updated.emit(ach.name, -1)

    def check_steady_focus_achievement(self, attention_score: int, duration_seconds: int):
        ach = self._achievements[AchievementType.STEADY_FOCUS]
        if not ach.unlocked and attention_score >= 70 and duration_seconds >= ach.target:
            self._unlock_achievement(AchievementType.STEADY_FOCUS)
        elif not ach.unlocked and duration_seconds > 0:
            progress = min(self.MAX_PROGRESS, (duration_seconds * self.MAX_PROGRESS) // ach.target)
            self._update_progress(AchievementType.STEADY_FOCUS, progress)

    def update_gaze_data(self, gaze_score: int, gaze_distance: float, duration_seconds: int = 1):
        if gaze_score > self._best_gaze_score:
            self._best_gaze_score = gaze_score

        self._check_gaze_master_achievement(gaze_score)

        if gaze_distance < 0.15:
            self._consecutive_focused_frames += duration_seconds
            self._max_consecutive_focused_frames = max(
                self._max_consecutive_focused_frames,
                self._consecutive_focused_frames
            )
            self._check_steady_gaze_achievement(self._consecutive_focused_frames)
        else:
            self._consecutive_focused_frames = 0

        if gaze_distance < 0.2:
            self._total_focused_time += duration_seconds
            self._check_focus_champion_achievement(self._total_focused_time)

        self._save_to_file_unsafe()

    def _check_gaze_master_achievement(self, gaze_score: int):
        ach = self._achievements[AchievementType.GAZE_MASTER]
        if not ach.unlocked:
            progress = min(self.MAX_PROGRESS, (gaze_score * self.MAX_PROGRESS) // ach.target)
            self._update_progress(AchievementType.GAZE_MASTER, progress)
            if gaze_score >= ach.target:
                self._unlock_achievement(AchievementType.GAZE_MASTER)

    def _check_steady_gaze_achievement(self, consecutive_seconds: int):
        ach = self._achievements[AchievementType.STEADY_GAZE]
        if not ach.unlocked:
            progress = min(self.MAX_PROGRESS, (consecutive_seconds * self.MAX_PROGRESS) // ach.target)
            self._update_progress(AchievementType.STEADY_GAZE, progress)
            if consecutive_seconds >= ach.target:
                self._unlock_achievement(AchievementType.STEADY_GAZE)

    def _check_focus_champion_achievement(self, total_seconds: int):
        ach = self._achievements[AchievementType.FOCUS_CHAMPION]
        if not ach.unlocked:
            progress = min(self.MAX_PROGRESS, (total_seconds * self.MAX_PROGRESS) // ach.target)
            self._update_progress(AchievementType.FOCUS_CHAMPION, progress)
            if total_seconds >= ach.target:
                self._unlock_achievement(AchievementType.FOCUS_CHAMPION)

    def _unlock_achievement(self, ach_type: AchievementType):
        ach = self._achievements[ach_type]
        if ach.unlocked:
            return

        ach.unlocked = True
        ach.unlock_time = QDateTime.currentDateTime()
        ach.progress = self.MAX_PROGRESS
        if ach_type != AchievementType.ALL_ROUNDER:
            ach.progress_text = f"{ach.target}/{ach.target}"
        else:
            other_count = self._get_other_achievements_count()
            ach.progress_text = f"{other_count}/{other_count}"

        self.achievement_unlocked.emit(ach.name)
        self._save_to_file_unsafe()

        other_count = self._get_other_achievements_count()
        unlocked_others = sum(1 for a in self._achievements.values()
                              if a.unlocked and a.type != AchievementType.ALL_ROUNDER)

        if unlocked_others >= other_count:
            allrounder = self._achievements[AchievementType.ALL_ROUNDER]
            if not allrounder.unlocked:
                self._unlock_achievement(AchievementType.ALL_ROUNDER)
        else:
            allrounder = self._achievements[AchievementType.ALL_ROUNDER]
            if not allrounder.unlocked:
                progress = (unlocked_others * self.MAX_PROGRESS) // other_count
                self._update_progress(AchievementType.ALL_ROUNDER, progress)

    def _update_progress(self, ach_type: AchievementType, progress: int):
        ach = self._achievements[ach_type]
        if ach.unlocked:
            return

        new_progress = max(0, min(self.MAX_PROGRESS, progress))
        if new_progress != ach.progress:
            ach.progress = new_progress

            if ach_type == AchievementType.MARATHONER:
                current_minutes = (new_progress * ach.target) // self.MAX_PROGRESS
                ach.progress_text = f"{current_minutes}/{ach.target}分钟"
            elif ach_type == AchievementType.ALL_ROUNDER:
                other_count = self._get_other_achievements_count()
                unlocked_others = (new_progress * other_count) // self.MAX_PROGRESS
                unlocked_others = min(unlocked_others, other_count)
                ach.progress_text = f"{unlocked_others}/{other_count}"
            elif ach_type == AchievementType.GAZE_MASTER:
                current_score = (new_progress * ach.target) // self.MAX_PROGRESS
                ach.progress_text = f"{current_score}/{ach.target}分"
            elif ach_type == AchievementType.STEADY_GAZE:
                current_seconds = (new_progress * ach.target) // self.MAX_PROGRESS
                ach.progress_text = f"{current_seconds}/{ach.target}秒"
            elif ach_type == AchievementType.FOCUS_CHAMPION:
                current_seconds = (new_progress * ach.target) // self.MAX_PROGRESS
                minutes = current_seconds // 60
                target_minutes = ach.target // 60
                ach.progress_text = f"{minutes}/{target_minutes}分钟"
            else:
                current_value = (new_progress * ach.target) // self.MAX_PROGRESS
                ach.progress_text = f"{current_value}/{ach.target}"

            self.achievement_progress_updated.emit(ach.name, new_progress)

    def reset_achievements(self):
        for ach in self._achievements.values():
            ach.unlocked = False
            ach.progress = 0
            ach.unlock_time = None
            if ach.type != AchievementType.ALL_ROUNDER:
                ach.progress_text = f"0/{ach.target}"
            else:
                other_count = self._get_other_achievements_count()
                ach.progress_text = f"0/{other_count}"
        self._total_training_minutes = 0
        self._total_focused_time = 0
        self._best_gaze_score = 0
        self._consecutive_focused_frames = 0
        self._max_consecutive_focused_frames = 0
        self._save_to_file_unsafe()

    def save_to_file(self):
        """公共保存接口 - 加锁版本"""
        locker = QMutexLocker(self._mutex)
        try:
            self._save_to_file_unsafe()
        finally:
            locker.unlock()

    def load_from_file(self):
        """公共加载接口"""
        self.load_current_user_data()