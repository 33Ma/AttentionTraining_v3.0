# core/achievement_manager.py
"""成就管理器：成就按游戏模式分为“找茬模式”与“动态追踪模式”两大专有板块，
每板块 10 个成就；动态追踪板块不设连击相关成就。

成就数据保存在 users/<用户名>/achievements.json（含各板块累计统计）。
旧版成就文件（13 个全局成就）加载时自动跳过已移除的成就类型，
仍在列表中的成就（火眼金睛/完美连击/找茬新手/追踪专家/完美游戏）保留进度。
"""

import os
import json
from enum import Enum
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, QDateTime, QMutex, QMutexLocker

from .paths import app_data_dir


class AchievementType(Enum):
    # ---- 找茬模式（10 个）----
    FINDER_NEWBIE = 7        # 完成第一次找茬训练
    EAGLE_EYE = 2            # 找茬累计找到 100 个差异点
    FINDER_COMBO_10 = 14     # 找茬单次 10 连击
    PERFECT_STREAK = 5       # 找茬单次 20 连击
    FINDER_SCORE_300 = 15    # 找茬单次游戏得分 300
    FINDER_SCORE_500 = 16    # 找茬单次游戏得分 500
    PERFECT_GAME = 9         # 找茬单次：注意力80+、得分500+、连击10+
    FINDER_ATTENTION = 17    # 找茬单次平均注意力 80+
    FINDER_MINUTES = 18      # 找茬累计训练 60 分钟
    FINDER_SESSIONS = 19     # 找茬累计训练 20 次

    # ---- 动态追踪模式（10 个，无连击）----
    TRACKER_NEWBIE = 8       # 完成第一次动态追踪训练
    TRACKER_HIT_RATE = 20    # 动态追踪单次命中率 90%
    TRACKER_RESPONSE = 21    # 动态追踪单次平均响应 <= 0.5 秒
    TRACKER_PATH = 22        # 动态追踪单次路径效率 80%
    TRACKER_SCORE_80 = 23    # 动态追踪单次游戏得分 80
    TRACKER_SCORE_90 = 24    # 动态追踪单次游戏得分 90
    TRACKER_PERFECT = 25     # 动态追踪单次：注意力80+、得分90+
    TRACKER_ATTENTION = 26   # 动态追踪单次平均注意力 80+
    TRACKER_MINUTES = 27     # 动态追踪累计训练 60 分钟
    TRACKER_SESSIONS = 28    # 动态追踪累计训练 20 次


# (类型, 名称, 描述, 目标值)
FIND_ACHIEVEMENTS = [
    (AchievementType.FINDER_NEWBIE, "🔍 找茬新手", "完成第一次找茬模式训练", 1),
    (AchievementType.EAGLE_EYE, "👁️ 火眼金睛", "找茬模式累计找到100个差异点", 100),
    (AchievementType.FINDER_COMBO_10, "⚡ 连击新星", "找茬模式单次达成10连击", 10),
    (AchievementType.PERFECT_STREAK, "⚡ 完美连击", "找茬模式单次达成20连击", 20),
    (AchievementType.FINDER_SCORE_300, "🏆 高分突破", "找茬模式单次游戏得分达到300", 300),
    (AchievementType.FINDER_SCORE_500, "👑 找茬大师", "找茬模式单次游戏得分达到500", 500),
    (AchievementType.PERFECT_GAME, "💎 完美游戏", "找茬模式单次训练：注意力80+、得分500+、连击10+", 100),
    (AchievementType.FINDER_ATTENTION, "🧠 专注达人", "找茬模式单次平均注意力达到80分", 80),
    (AchievementType.FINDER_MINUTES, "🕒 坚持之星", "找茬模式累计训练60分钟", 60),
    (AchievementType.FINDER_SESSIONS, "🔥 高频训练", "找茬模式累计训练20次", 20),
]

TRACKING_ACHIEVEMENTS = [
    (AchievementType.TRACKER_NEWBIE, "🎯 追踪新手", "完成第一次动态追踪模式训练", 1),
    (AchievementType.TRACKER_HIT_RATE, "🎯 弹无虚发", "动态追踪单次命中率达到90%", 90),
    (AchievementType.TRACKER_RESPONSE, "⚡ 反应神速", "动态追踪单次平均响应不超过0.5秒", 500),
    (AchievementType.TRACKER_PATH, "🧭 精准路径", "动态追踪单次路径效率达到80%", 80),
    (AchievementType.TRACKER_SCORE_80, "🏆 追踪突破", "动态追踪单次游戏得分达到80", 80),
    (AchievementType.TRACKER_SCORE_90, "👑 追踪大师", "动态追踪单次游戏得分达到90", 90),
    (AchievementType.TRACKER_PERFECT, "💎 完美追踪", "动态追踪单次训练：注意力80+、得分90+", 100),
    (AchievementType.TRACKER_ATTENTION, "🧠 专注达人", "动态追踪单次平均注意力达到80分", 80),
    (AchievementType.TRACKER_MINUTES, "🕒 坚持之星", "动态追踪模式累计训练60分钟", 60),
    (AchievementType.TRACKER_SESSIONS, "🔥 高频训练", "动态追踪模式累计训练20次", 20),
]

FIND_TYPES = tuple(t for t, _, _, _ in FIND_ACHIEVEMENTS)
TRACKING_TYPES = tuple(t for t, _, _, _ in TRACKING_ACHIEVEMENTS)

_PROGRESS_UNITS = {
    AchievementType.EAGLE_EYE: "个差异点",
    AchievementType.FINDER_COMBO_10: "连击",
    AchievementType.PERFECT_STREAK: "连击",
    AchievementType.FINDER_SCORE_300: "分",
    AchievementType.FINDER_SCORE_500: "分",
    AchievementType.FINDER_ATTENTION: "分",
    AchievementType.TRACKER_ATTENTION: "分",
    AchievementType.TRACKER_SCORE_80: "分",
    AchievementType.TRACKER_SCORE_90: "分",
    AchievementType.FINDER_MINUTES: "分钟",
    AchievementType.TRACKER_MINUTES: "分钟",
    AchievementType.FINDER_SESSIONS: "次",
    AchievementType.TRACKER_SESSIONS: "次",
    AchievementType.TRACKER_HIT_RATE: "%",
    AchievementType.TRACKER_PATH: "%",
}


class Achievement:
    def __init__(self):
        self.type: AchievementType = AchievementType.FINDER_NEWBIE
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

        self.app_dir = app_data_dir()
        self._achievements: Dict[AchievementType, Achievement] = {}
        self._current_user = ""
        self.MAX_PROGRESS = 100

        self._mutex = QMutex()
        self._is_loading = False  # 防止重入

        # 各板块累计统计
        self._total_minutes_find = 0
        self._total_minutes_tracking = 0
        self._total_sessions_find = 0
        self._total_sessions_tracking = 0
        self._total_find_points = 0  # 找茬累计游戏得分（火眼金睛按得分/10 近似差异点）

        self._init_achievements()

    def _init_achievements(self):
        achievements_data = FIND_ACHIEVEMENTS + TRACKING_ACHIEVEMENTS
        self._achievements.clear()
        for ach_type, name, desc, target in achievements_data:
            ach = Achievement()
            ach.type = ach_type
            ach.name = name
            ach.description = desc
            ach.target = target
            unit = _PROGRESS_UNITS.get(ach_type, "")
            ach.progress_text = f"0/{target}{unit}" if target > 0 else "0/0"
            self._achievements[ach_type] = ach

    def _get_user_achievement_path(self, username: str = None) -> str:
        if username is None:
            if self._current_user:
                username = self._current_user
            else:
                from .settings import GlobalSettings
                username = GlobalSettings().current_user()

        if not username:
            return ""

        user_dir = os.path.join(self.app_dir, "users", username)
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, "achievements.json")

    def load_current_user_data(self):
        """加载当前用户数据（公共接口）"""
        self._load_current_user_data()

    def _load_current_user_data(self):
        """加载当前用户数据 - 防重入版本"""
        if self._is_loading:
            print("AchievementManager: Already loading, skipping")
            return

        if not AchievementManager._loading_lock.tryLock():
            print("AchievementManager: Another load in progress, skipping")
            return

        try:
            self._is_loading = True
            user = self._current_user
            if not user:
                from .settings import GlobalSettings
                user = GlobalSettings().current_user()
            if not user:
                self._current_user = ""
                print("AchievementManager: No user logged in, skipping load")
                return

            # 重置成就数据与累计统计
            self._init_achievements()
            self._total_minutes_find = 0
            self._total_minutes_tracking = 0
            self._total_sessions_find = 0
            self._total_sessions_tracking = 0
            self._total_find_points = 0
            self._current_user = user

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
        """从文件加载数据（不加锁，内部调用）。旧文件里已移除的成就类型自动跳过。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            achievements_data = data.get('achievements', [])
            # 旧版全局训练时长作为两种模式累计时长的兜底
            legacy_minutes = data.get('total_training_minutes', 0)
            self._total_minutes_find = data.get('total_minutes_find', legacy_minutes)
            self._total_minutes_tracking = data.get('total_minutes_tracking', legacy_minutes)
            self._total_sessions_find = data.get('total_sessions_find', 0)
            self._total_sessions_tracking = data.get('total_sessions_tracking', 0)
            self._total_find_points = data.get('total_find_points', 0)

            for ach_data in achievements_data:
                try:
                    ach_type = AchievementType(ach_data.get('type', -1))
                except ValueError:
                    continue
                if ach_type in self._achievements:
                    saved_ach = Achievement.from_dict(ach_data)
                    self._achievements[ach_type] = saved_ach

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
                'total_minutes_find': self._total_minutes_find,
                'total_minutes_tracking': self._total_minutes_tracking,
                'total_sessions_find': self._total_sessions_find,
                'total_sessions_tracking': self._total_sessions_tracking,
                'total_find_points': self._total_find_points,
            }

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"AchievementManager: Saved data to {path}")

        except Exception as e:
            print(f"AchievementManager: Error saving achievements: {e}")

    def switch_user(self, username: str):
        """切换用户 - 防重入版本"""
        if not username:
            self._current_user = ""
            return

        if self._current_user == username:
            print(f"AchievementManager.switch_user: Already on {username}, skipping")
            return

        print(f"AchievementManager.switch_user: Switching to {username}")

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

    def achievement_groups(self) -> List[Tuple[str, List[Achievement]]]:
        """返回两大板块及其成就，供成就对话框分组展示。"""
        return [
            ("🔍 找茬模式", [self._achievements[t] for t in FIND_TYPES]),
            ("🎯 动态追踪模式", [self._achievements[t] for t in TRACKING_TYPES]),
        ]

    def get_unlocked_count(self) -> int:
        return sum(1 for ach in self._achievements.values() if ach.unlocked)

    def get_total_count(self) -> int:
        return len(self._achievements)

    def get_achievement(self, ach_type: AchievementType) -> Optional[Achievement]:
        return self._achievements.get(ach_type)

    # ------------------------------------------------------------------
    # 训练成就检查（按模式）
    # ------------------------------------------------------------------
    def check_training_achievements(
        self,
        *,
        game_mode: str,
        avg_attention: int,
        game_score: int,
        max_consecutive_hits: int = 0,
        hit_rate: float = 0.0,
        avg_response_time: float = 0.0,
        path_efficiency: float = 0.0,
        duration_minutes: int = 0,
    ):
        """训练结束后按游戏模式更新成就；动态追踪不检查任何连击成就。"""
        if game_mode == "find_difference":
            self._total_minutes_find += max(0, duration_minutes)
            self._total_sessions_find += 1
            self._total_find_points += max(0, game_score)
            self._check_find_achievements(
                avg_attention=avg_attention,
                game_score=game_score,
                max_consecutive_hits=max_consecutive_hits,
            )
        elif game_mode == "dynamic_tracking":
            self._total_minutes_tracking += max(0, duration_minutes)
            self._total_sessions_tracking += 1
            self._check_tracking_achievements(
                avg_attention=avg_attention,
                game_score=game_score,
                hit_rate=hit_rate,
                avg_response_time=avg_response_time,
                path_efficiency=path_efficiency,
            )
        else:
            return
        self._save_to_file_unsafe()

    def _check_find_achievements(self, *, avg_attention: int, game_score: int,
                                 max_consecutive_hits: int):
        self._check_cumulative(AchievementType.FINDER_NEWBIE,
                               1 if game_score > 0 else 0)
        # 火眼金睛：每个差异点基础 10 分，累计得分/10 近似累计差异点
        self._check_cumulative(AchievementType.EAGLE_EYE,
                               self._total_find_points // 10)
        self._check_cumulative(AchievementType.FINDER_COMBO_10,
                               max_consecutive_hits)
        self._check_cumulative(AchievementType.PERFECT_STREAK,
                               max_consecutive_hits)
        self._check_cumulative(AchievementType.FINDER_SCORE_300, game_score)
        self._check_cumulative(AchievementType.FINDER_SCORE_500, game_score)
        self._check_cumulative(AchievementType.FINDER_ATTENTION, avg_attention)
        self._check_cumulative(AchievementType.FINDER_MINUTES,
                               self._total_minutes_find)
        self._check_cumulative(AchievementType.FINDER_SESSIONS,
                               self._total_sessions_find)

        ach = self._achievements[AchievementType.PERFECT_GAME]
        if not ach.unlocked:
            perfect = (
                avg_attention >= 80
                and game_score >= 500
                and max_consecutive_hits >= 10
            )
            if perfect:
                self._unlock_achievement(AchievementType.PERFECT_GAME)
            else:
                ach.progress_text = (
                    f"注意{avg_attention}/80 得分{game_score}/500 "
                    f"连击{max_consecutive_hits}/10"
                )
                self.achievement_progress_updated.emit(ach.name, -1)

    def _check_tracking_achievements(self, *, avg_attention: int, game_score: int,
                                     hit_rate: float, avg_response_time: float,
                                     path_efficiency: float):
        self._check_cumulative(AchievementType.TRACKER_NEWBIE,
                               1 if game_score > 0 else 0)
        self._check_cumulative(AchievementType.TRACKER_HIT_RATE,
                               int(round(hit_rate * 100.0)))
        self._check_cumulative(AchievementType.TRACKER_PATH,
                               int(round(path_efficiency * 100.0)))
        self._check_cumulative(AchievementType.TRACKER_SCORE_80, game_score)
        self._check_cumulative(AchievementType.TRACKER_SCORE_90, game_score)
        self._check_cumulative(AchievementType.TRACKER_ATTENTION, avg_attention)
        self._check_cumulative(AchievementType.TRACKER_MINUTES,
                               self._total_minutes_tracking)
        self._check_cumulative(AchievementType.TRACKER_SESSIONS,
                               self._total_sessions_tracking)

        # 平均响应时间：<= 0.5 秒解锁（无命中时不检查）
        rt_ms = avg_response_time * 1000.0
        if rt_ms > 0:
            if rt_ms <= 500:
                self._unlock_achievement(AchievementType.TRACKER_RESPONSE)
            else:
                progress = int(
                    max(0.0, min(1.0, (800.0 - rt_ms) / 300.0)) * self.MAX_PROGRESS
                )
                self._update_progress(AchievementType.TRACKER_RESPONSE, progress)

        ach = self._achievements[AchievementType.TRACKER_PERFECT]
        if not ach.unlocked:
            perfect = avg_attention >= 80 and game_score >= 90
            if perfect:
                self._unlock_achievement(AchievementType.TRACKER_PERFECT)
            else:
                ach.progress_text = (
                    f"注意{avg_attention}/80 得分{game_score}/90"
                )
                self.achievement_progress_updated.emit(ach.name, -1)

    def _check_cumulative(self, ach_type: AchievementType, value: int):
        """按目标值推进进度，达到目标即解锁。"""
        ach = self._achievements[ach_type]
        if ach.unlocked:
            return
        value = max(0, int(value))
        if value >= ach.target:
            self._unlock_achievement(ach_type)
        else:
            progress = min(
                self.MAX_PROGRESS,
                (value * self.MAX_PROGRESS) // ach.target if ach.target > 0 else 0,
            )
            self._update_progress(ach_type, progress)

    # ------------------------------------------------------------------
    # 解锁与进度
    # ------------------------------------------------------------------
    def _unlock_achievement(self, ach_type: AchievementType):
        ach = self._achievements[ach_type]
        if ach.unlocked:
            return

        ach.unlocked = True
        ach.unlock_time = QDateTime.currentDateTime()
        ach.progress = self.MAX_PROGRESS
        unit = _PROGRESS_UNITS.get(ach_type, "")
        ach.progress_text = f"{ach.target}/{ach.target}{unit}"

        self.achievement_unlocked.emit(ach.name)
        self._save_to_file_unsafe()

    def _update_progress(self, ach_type: AchievementType, progress: int):
        ach = self._achievements[ach_type]
        if ach.unlocked:
            return

        new_progress = max(0, min(self.MAX_PROGRESS, progress))
        if new_progress != ach.progress:
            ach.progress = new_progress

            unit = _PROGRESS_UNITS.get(ach_type, "")
            if ach_type == AchievementType.TRACKER_RESPONSE:
                # 进度条越满表示响应越接近 500ms 目标
                ach.progress_text = (
                    f"{int(round(500 + (1 - new_progress / 100.0) * 300))}ms"
                )
            elif unit:
                current_value = int(round(new_progress * ach.target / self.MAX_PROGRESS))
                ach.progress_text = f"{current_value}/{ach.target}{unit}"
            else:
                current_value = int(round(new_progress * ach.target / self.MAX_PROGRESS))
                ach.progress_text = f"{current_value}/{ach.target}"

            self.achievement_progress_updated.emit(ach.name, new_progress)

    def reset_achievements(self):
        self._init_achievements()
        self._total_minutes_find = 0
        self._total_minutes_tracking = 0
        self._total_sessions_find = 0
        self._total_sessions_tracking = 0
        self._total_find_points = 0
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
