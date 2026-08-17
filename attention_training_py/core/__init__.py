# core/__init__.py
"""
核心模块
包含系统核心功能和数据管理
"""

from .settings import GlobalSettings, DifficultyLevel, TrainingRecord, CustomDifficulty
from .user_manager import UserManager, UserInfo, UserRole
from .user_session import UserSession
from .achievement_manager import AchievementManager, Achievement, AchievementType
from .sound_manager import SoundManager
from .llm_client import LLMClient

__all__ = [
    'GlobalSettings',
    'DifficultyLevel',
    'TrainingRecord',
    'CustomDifficulty',
    'UserManager',
    'UserInfo',
    'UserRole',
    'UserSession',
    'AchievementManager',
    'Achievement',
    'AchievementType',
    'SoundManager',
    'LLMClient',
]