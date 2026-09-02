# -*- coding: utf-8 -*-
"""training_records 的 composite_score 落库与迁移测试（临时数据库）。"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from core.database import Database


class TrainingRecordDbTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="record_db_test_")
        self.db = Database.__new__(Database)
        self.db.app_dir = self._tmp
        self.db.db_path = os.path.join(self._tmp, "attention_data.db")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _insert(self, **overrides):
        rec = {
            "date_time": "2026-08-28 12:00:00",
            "duration_minutes": 1,
            "game_mode": "find_difference",
            "difficulty": "normal",
            "avg_attention_score": 88,
            "total_blinks": 5,
            "game_score": 420,
            "avg_ear": 0.25,
            "avg_gaze_score": 90,
            "avg_gaze_distance": 0.1,
            "max_consecutive_hits": 18,
            "face_detected": 1,
            "composite_score": 72,
        }
        rec.update(overrides)
        self.db.insert_training_record("stu1", rec)

    def test_insert_and_fetch_composite_score(self):
        self.db.initialize()
        self._insert()
        rows = self.db.fetch_training_records("stu1")
        self.assertEqual(rows[0]["composite_score"], 72)

    def test_legacy_db_migrates_composite_column_with_default_minus_one(self):
        conn = sqlite3.connect(self.db.db_path)
        conn.executescript("""
        CREATE TABLE training_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            date_time TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL DEFAULT 0,
            game_mode TEXT NOT NULL DEFAULT '',
            difficulty TEXT NOT NULL DEFAULT 'normal',
            avg_attention_score INTEGER NOT NULL DEFAULT 0,
            total_blinks INTEGER NOT NULL DEFAULT 0,
            game_score INTEGER NOT NULL DEFAULT 0,
            avg_ear REAL NOT NULL DEFAULT 0.0,
            avg_gaze_score INTEGER NOT NULL DEFAULT 0,
            avg_gaze_distance REAL NOT NULL DEFAULT 0.0,
            max_consecutive_hits INTEGER NOT NULL DEFAULT 0,
            face_detected INTEGER NOT NULL DEFAULT -1
        );""")
        conn.execute(
            "INSERT INTO training_records (username, date_time, game_mode, avg_attention_score, game_score) "
            "VALUES ('stu1', '2026-08-01 00:00:00', 'find_difference', 80, 300)"
        )
        conn.commit()
        conn.close()

        self.db.initialize()
        rows = self.db.fetch_training_records("stu1")
        self.assertEqual(rows[0]["composite_score"], -1)


if __name__ == "__main__":
    unittest.main()
