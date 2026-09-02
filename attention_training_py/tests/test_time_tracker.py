# -*- coding: utf-8 -*-
"""回归测试：TimeTracker 将模型推理耗时写入 time_consumed.db。

会破坏这些测试的变更：不建表、不落库、列名/列值写错、
计时失败时向外抛异常导致推理中断。
"""

import os
import sqlite3
import tempfile
import unittest

from core.time_tracker import DB_FILENAME, TimeTracker


class TimeTrackerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, DB_FILENAME)
        self.tracker = TimeTracker(db_path=self.db_path)

    def tearDown(self):
        self.tracker.close()
        self._tmp.cleanup()

    def _rows(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "SELECT run_id, ts, model, frame, duration_ms, ok, width, height, config "
                "FROM model_timing ORDER BY id"
            )
            return cur.fetchall()
        finally:
            conn.close()

    def test_record_writes_row_with_model_frame_duration_and_config(self):
        self.tracker.set_config(["blink", "face"])
        self.tracker.record("yunet", 13, 12.5, True, width=640, height=480)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        run_id, ts, model, frame, duration, ok, width, height, config = rows[0]
        self.assertEqual(model, "yunet")
        self.assertEqual(frame, 13)
        self.assertAlmostEqual(duration, 12.5, places=4)
        self.assertEqual(ok, 1)
        self.assertEqual((width, height), (640, 480))
        self.assertEqual(config, "blink,face")
        self.assertTrue(run_id)
        self.assertTrue(ts)

    def test_record_marks_failed_inference_with_ok_zero(self):
        self.tracker.record("ocec", 2, 3.0, False)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][5], 0)

    def test_config_empty_when_not_set(self):
        self.tracker.record("head_pose", 1, 1.0, True)
        self.assertEqual(self._rows()[0][8], "")

    def test_records_share_same_run_id(self):
        self.tracker.record("head_pose", 1, 1.0, True)
        self.tracker.record("gaze", 2, 2.0, True)
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], rows[1][0])
        self.assertTrue(rows[0][0])

    def test_record_failure_is_silent(self):
        bad_tracker = TimeTracker(db_path=self._tmp.name)  # 目录路径无法作为 SQLite 文件
        try:
            bad_tracker.record("yunet", 1, 1.0, True)  # 不应抛出
        finally:
            bad_tracker.close()


if __name__ == "__main__":
    unittest.main()
