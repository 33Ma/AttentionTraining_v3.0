# -*- coding: utf-8 -*-
"""coach_messages 表读写测试（临时数据库，不触碰真实数据）。"""

import os
import tempfile
import unittest

from core.database import Database


class CoachMessagesDbTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="coach_db_test_")
        self.db = Database.__new__(Database)
        self.db.app_dir = self._tmp
        self.db.db_path = os.path.join(self._tmp, "attention_data.db")
        self.db.initialize()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_roundtrip_keeps_order(self):
        self.db.add_coach_message("stu1", "user", "今天练什么好？")
        self.db.add_coach_message("stu1", "assistant", "建议先做找茬模式。")
        self.db.add_coach_message("stu1", "user", "好的")

        rows = self.db.fetch_coach_messages("stu1")
        self.assertEqual([r["role"] for r in rows], ["user", "assistant", "user"])
        self.assertEqual(rows[1]["content"], "建议先做找茬模式。")

    def test_fetch_limit_returns_latest_in_order(self):
        for i in range(5):
            self.db.add_coach_message("stu1", "user", f"msg{i}")

        rows = self.db.fetch_coach_messages("stu1", limit=2)
        self.assertEqual([r["content"] for r in rows], ["msg3", "msg4"])

    def test_messages_scoped_per_user(self):
        self.db.add_coach_message("stu1", "user", "A")
        self.db.add_coach_message("stu2", "user", "B")
        rows = self.db.fetch_coach_messages("stu1")
        self.assertEqual([r["content"] for r in rows], ["A"])

    def test_clear_removes_only_target_user(self):
        self.db.add_coach_message("stu1", "user", "A")
        self.db.add_coach_message("stu2", "user", "B")
        self.db.clear_coach_messages("stu1")
        self.assertEqual(self.db.fetch_coach_messages("stu1"), [])
        self.assertEqual(len(self.db.fetch_coach_messages("stu2")), 1)


if __name__ == "__main__":
    unittest.main()
