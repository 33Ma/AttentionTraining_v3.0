# -*- coding: utf-8 -*-
"""成就系统测试：找茬/动态追踪两大板块各 10 个，追踪板块无连击成就。"""

import unittest

from core.achievement_manager import (
    AchievementManager,
    AchievementType,
    FIND_ACHIEVEMENTS,
    TRACKING_ACHIEVEMENTS,
    TRACKING_TYPES,
)


class AchievementStructureTests(unittest.TestCase):
    def setUp(self):
        self.am = AchievementManager()
        # 隔离测试：重置到初始状态，且不写入真实用户文件
        self.am._current_user = ""
        self.am._init_achievements()
        self.am._total_minutes_find = 0
        self.am._total_minutes_tracking = 0
        self.am._total_sessions_find = 0
        self.am._total_sessions_tracking = 0
        self.am._total_find_points = 0

    def test_two_sections_with_ten_each(self):
        self.assertEqual(len(FIND_ACHIEVEMENTS), 10)
        self.assertEqual(len(TRACKING_ACHIEVEMENTS), 10)
        self.assertEqual(self.am.get_total_count(), 20)

    def test_tracking_has_no_combo_achievements(self):
        for _, name, _, _ in TRACKING_ACHIEVEMENTS:
            self.assertNotIn("连击", name, name)
        self.assertNotIn(AchievementType.PERFECT_STREAK, TRACKING_TYPES)
        self.assertNotIn(AchievementType.FINDER_COMBO_10, TRACKING_TYPES)

    def test_find_training_unlocks_find_achievements(self):
        self.am.check_training_achievements(
            game_mode="find_difference",
            avg_attention=85,
            game_score=520,
            max_consecutive_hits=12,
            duration_minutes=30,
        )
        for t in (
            AchievementType.FINDER_NEWBIE,
            AchievementType.FINDER_SCORE_500,
            AchievementType.PERFECT_GAME,
            AchievementType.FINDER_ATTENTION,
        ):
            self.assertTrue(self.am.get_achievement(t).unlocked, t)
        # 动态追踪成就不受找茬训练影响
        self.assertFalse(
            self.am.get_achievement(AchievementType.TRACKER_NEWBIE).unlocked
        )

    def test_tracking_training_unlocks_tracking_without_combo(self):
        self.am.check_training_achievements(
            game_mode="dynamic_tracking",
            avg_attention=85,
            game_score=95,
            hit_rate=0.95,
            avg_response_time=0.4,
            path_efficiency=0.85,
            duration_minutes=30,
        )
        for t in (
            AchievementType.TRACKER_NEWBIE,
            AchievementType.TRACKER_HIT_RATE,
            AchievementType.TRACKER_RESPONSE,
            AchievementType.TRACKER_PATH,
            AchievementType.TRACKER_SCORE_90,
            AchievementType.TRACKER_PERFECT,
            AchievementType.TRACKER_ATTENTION,
        ):
            self.assertTrue(self.am.get_achievement(t).unlocked, t)
        # 连击类成就绝不能被动态追踪触发
        self.assertFalse(
            self.am.get_achievement(AchievementType.PERFECT_STREAK).unlocked
        )
        self.assertFalse(
            self.am.get_achievement(AchievementType.FINDER_COMBO_10).unlocked
        )

    def test_cumulative_progress_text(self):
        for _ in range(5):
            self.am.check_training_achievements(
                game_mode="find_difference",
                avg_attention=60,
                game_score=100,
                max_consecutive_hits=0,
                duration_minutes=10,
            )
        sessions = self.am.get_achievement(AchievementType.FINDER_SESSIONS)
        self.assertFalse(sessions.unlocked)
        self.assertIn("5/20次", sessions.progress_text)

        minutes = self.am.get_achievement(AchievementType.FINDER_MINUTES)
        self.assertIn("50/60分钟", minutes.progress_text)

        eagle = self.am.get_achievement(AchievementType.EAGLE_EYE)
        self.assertIn("50/100个差异点", eagle.progress_text)


if __name__ == "__main__":
    unittest.main()
