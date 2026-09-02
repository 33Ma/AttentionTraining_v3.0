# -*- coding: utf-8 -*-
"""便携数据导出/导入核心逻辑测试（不依赖 Qt，可独立运行）。

覆盖：
- 导出载荷结构与"默认用户"拦截
- 导入解析与校验
- 记录合并去重 / 无效记录过滤
- 成就合并
- 数据库落库（幂等、不产生默认用户）
"""

import os
import shutil
import tempfile
import unittest

from core.database import Database
from core.portable_sync import (
    apply_import,
    build_export_payload,
    deserialize_payload,
    is_forbidden_username,
    load_achievements_file,
    merge_achievements,
    merge_records,
    parse_import_payload,
    save_achievements_file,
    serialize_payload,
    split_incoming_records,
)


def _record(**overrides):
    rec = {
        "username": "stu1",
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
        "hit_rate": 0.9,
        "avg_response_time": 0.3,
        "path_efficiency": 0.8,
        "composite_score": 72,
    }
    rec.update(overrides)
    return rec


def _payload(**overrides):
    payload = {
        "format": "attention-training-portable",
        "format_version": 1,
        "exported_at": "2026-08-30 10:00:00",
        "user": {
            "username": "stu1",
            "display_name": "小明",
            "role": "student",
            "teacher_id": "teacher",
        },
        "records": [_record()],
        "achievements": {
            "achievements": [
                {
                    "type": 7,
                    "name": "找茬新手",
                    "description": "",
                    "unlocked": True,
                    "unlock_time": "2026-08-28 12:00:00",
                    "progress": 100,
                    "target": 1,
                    "progress_text": "1/1",
                }
            ],
            "total_minutes_find": 10,
            "total_minutes_tracking": 0,
            "total_sessions_find": 1,
            "total_sessions_tracking": 0,
            "total_find_points": 420,
        },
    }
    payload.update(overrides)
    return payload


class ExportPayloadTests(unittest.TestCase):
    def test_build_export_payload_structure(self):
        payload = build_export_payload(
            username="stu1",
            display_name="小明",
            role="student",
            teacher_id="teacher",
            records=[_record()],
            achievements={"achievements": []},
        )
        self.assertEqual(payload["format"], "attention-training-portable")
        self.assertEqual(payload["format_version"], 1)
        self.assertEqual(payload["user"]["username"], "stu1")
        self.assertEqual(payload["user"]["display_name"], "小明")
        self.assertEqual(len(payload["records"]), 1)
        self.assertIn("achievements", payload)

    def test_build_export_payload_rejects_default_user(self):
        for bad_name in ("默认用户", "", "  "):
            with self.assertRaises(ValueError):
                build_export_payload(
                    username=bad_name,
                    display_name="默认用户",
                    role="student",
                    teacher_id="",
                    records=[],
                    achievements={},
                )

    def test_is_forbidden_username(self):
        self.assertTrue(is_forbidden_username("默认用户"))
        self.assertTrue(is_forbidden_username(""))
        self.assertTrue(is_forbidden_username("   "))
        self.assertFalse(is_forbidden_username("stu1"))


class ImportParseTests(unittest.TestCase):
    def test_parse_import_payload_accepts_valid(self):
        data = parse_import_payload(_payload())
        self.assertEqual(data["user"]["username"], "stu1")
        self.assertEqual(len(data["records"]), 1)

    def test_parse_import_payload_rejects_bad_format(self):
        with self.assertRaises(ValueError):
            parse_import_payload(_payload(format="other"))
        with self.assertRaises(ValueError):
            parse_import_payload(_payload(format_version=2))

    def test_parse_import_payload_rejects_missing_user(self):
        bad = _payload()
        del bad["user"]
        with self.assertRaises(ValueError):
            parse_import_payload(bad)

    def test_parse_import_payload_rejects_default_user(self):
        bad = _payload(
            user={
                "username": "默认用户",
                "display_name": "默认用户",
                "role": "student",
                "teacher_id": "",
            }
        )
        with self.assertRaises(ValueError):
            parse_import_payload(bad)

    def test_serialize_deserialize_round_trip(self):
        text = serialize_payload(_payload())
        loaded = deserialize_payload(text)
        self.assertEqual(loaded["user"]["username"], "stu1")
        self.assertEqual(len(loaded["records"]), 1)

    def test_deserialize_rejects_invalid_json(self):
        with self.assertRaises(ValueError):
            deserialize_payload("{not json")


class MergeLogicTests(unittest.TestCase):
    def test_merge_records_adds_new_and_skips_duplicates(self):
        existing = [_record()]
        incoming = [
            _record(),
            _record(date_time="2026-08-29 09:00:00"),
        ]
        added, skipped = merge_records(existing, incoming)
        self.assertEqual(len(added), 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(len(existing), 1)  # 原列表不被修改
        self.assertEqual(added[0]["date_time"], "2026-08-29 09:00:00")

    def test_split_incoming_records_filters_forbidden_and_malformed(self):
        records = [
            _record(),
            _record(username="默认用户", date_time="2026-08-29 09:00:00"),
            _record(username="other_user", date_time="2026-08-29 10:00:00"),
            {"date_time": "2026-08-29 11:00:00"},  # 缺少必填字段
        ]
        accepted, ignored = split_incoming_records(records, "stu1")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(ignored, 3)

    def test_merge_achievements_keeps_max_progress_and_unlocked(self):
        existing = {
            "achievements": [
                {
                    "type": 7, "unlocked": False, "progress": 30, "target": 1,
                    "name": "x", "description": "", "unlock_time": "",
                    "progress_text": "0/1",
                },
                {
                    "type": 2, "unlocked": True, "progress": 100, "target": 100,
                    "name": "y", "description": "",
                    "unlock_time": "2026-08-01 00:00:00",
                    "progress_text": "100/100",
                },
            ],
            "total_minutes_find": 5,
        }
        incoming = {
            "achievements": [
                {
                    "type": 7, "unlocked": True, "progress": 100, "target": 1,
                    "name": "x", "description": "",
                    "unlock_time": "2026-08-28 12:00:00",
                    "progress_text": "1/1",
                },
                {
                    "type": 2, "unlocked": False, "progress": 60, "target": 100,
                    "name": "y", "description": "", "unlock_time": "",
                    "progress_text": "60/100",
                },
            ],
            "total_minutes_find": 12,
            "total_sessions_find": 3,
        }
        merged = merge_achievements(existing, incoming)
        by_type = {a["type"]: a for a in merged["achievements"]}
        self.assertTrue(by_type[7]["unlocked"])
        self.assertTrue(by_type[2]["unlocked"])  # 已解锁状态保留
        self.assertEqual(merged["total_minutes_find"], 12)
        self.assertEqual(merged["total_sessions_find"], 3)

        # 空 incoming 时保留 existing
        merged2 = merge_achievements(existing, {})
        self.assertEqual(len(merged2["achievements"]), 2)
        # 空 existing 时采用 incoming
        merged3 = merge_achievements({}, incoming)
        self.assertEqual(len(merged3["achievements"]), 2)

    def test_achievements_file_helpers(self):
        path = os.path.join(self._tmp_dir, "achievements.json")
        self.assertEqual(load_achievements_file(path), {})
        save_achievements_file(path, {"achievements": [{"type": 1, "unlocked": True}]})
        data = load_achievements_file(path)
        self.assertTrue(data["achievements"][0]["unlocked"])

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="portable_sync_merge_test_")

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)


class ApplyImportDbTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="portable_sync_db_test_")
        self.db = Database.__new__(Database)
        self.db.app_dir = self._tmp
        self.db.db_path = os.path.join(self._tmp, "attention_data.db")
        self.db.initialize()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_apply_import_creates_user_and_inserts_records(self):
        summary = apply_import(self.db, _payload(), teacher_id="teacher")
        self.assertTrue(summary.user_created)
        self.assertEqual(summary.records_added, 1)
        self.assertEqual(summary.records_skipped, 0)

        stu = [r for r in self.db.fetch_users() if r["username"] == "stu1"][0]
        self.assertEqual(stu["role"], "student")
        self.assertEqual(stu["teacher_id"], "teacher")
        self.assertEqual(len(self.db.fetch_training_records("stu1")), 1)

    def test_apply_import_is_idempotent(self):
        apply_import(self.db, _payload(), teacher_id="teacher")
        summary = apply_import(self.db, _payload(), teacher_id="teacher")
        self.assertFalse(summary.user_created)
        self.assertEqual(summary.records_added, 0)
        self.assertEqual(summary.records_skipped, 1)
        self.assertEqual(len(self.db.fetch_training_records("stu1")), 1)

    def test_apply_import_rejects_default_user_before_writing(self):
        bad = _payload(
            user={
                "username": "默认用户",
                "display_name": "默认用户",
                "role": "student",
                "teacher_id": "",
            }
        )
        with self.assertRaises(ValueError):
            apply_import(self.db, bad, teacher_id="teacher")
        self.assertEqual(self.db.fetch_users(), [])  # 未写入任何用户

    def test_export_import_round_trip(self):
        payload = build_export_payload(
            username="stu1",
            display_name="小明",
            role="student",
            teacher_id="teacher",
            records=[
                _record(),
                _record(date_time="2026-08-29 09:00:00"),
            ],
            achievements={"achievements": [{"type": 7, "unlocked": True}]},
        )
        text = serialize_payload(payload)
        parsed = parse_import_payload(deserialize_payload(text))
        summary = apply_import(self.db, parsed, teacher_id="teacher")
        self.assertEqual(summary.records_added, 2)
        self.assertEqual(len(self.db.fetch_training_records("stu1")), 2)


if __name__ == "__main__":
    unittest.main()
