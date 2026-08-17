# games/__init__.py
"""
游戏模块
包含所有游戏相关的类和接口
"""

from .game_interface import GameInterface
from .spot_difference_game import SpotDifferenceGame
from .tracking_game import TrackingGame

__all__ = [
    'GameInterface',
    'SpotDifferenceGame',
    'TrackingGame',
]