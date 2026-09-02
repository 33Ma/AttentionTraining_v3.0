# -*- coding: utf-8 -*-
"""便携式训练数据导出/导入（方案1：离线文件同步）。

学生端把本人训练记录与成就导出为 JSON 文件，教师端导入并合并到本地库。
设计约束：
- 按用户名合并，绝不覆盖其他学生的已有记录（不做"先删后写"）。
- "默认用户"（及空用户名）在导出与导入两端都被拦截，禁止再次出现。
- 纯逻辑不依赖 Qt，可独立单测；数据库操作通过 core.database.Database。
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple


FORMAT_NAME = "attention-training-portable"
FORMAT_VERSION = 1

#: 禁止导出/导入的用户名（历史遗留的"默认用户"以及空用户名）
FORBIDDEN_USERNAMES = ("默认用户", "")

#: 训练记录入库所需的必填字段（与 Database.insert_training_record 一致）
_REQUIRED_RECORD_FIELDS = (
    "date_time",
    "duration_minutes",
    "game_mode",
    "difficulty",
    "avg_attention_score",
    "total_blinks",
    "game_score",
    "avg_ear",
)

_INT_FIELDS = (
    "duration_minutes",
    "avg_attention_score",
    "total_blinks",
    "game_score",
    "avg_gaze_score",
    "max_consecutive_hits",
    "face_detected",
    "composite_score",
)

_FLOAT_FIELDS = (
    "avg_ear",
    "avg_gaze_distance",
    "hit_rate",
    "avg_response_time",
    "path_efficiency",
)

_RECORD_OPTIONAL_DEFAULTS = {
    "avg_gaze_score": 0,
    "avg_gaze_distance": 0.0,
    "max_consecutive_hits": 0,
    "face_detected": -1,
    "hit_rate": 0.0,
    "avg_response_time": 0.0,
    "path_efficiency": 0.0,
    "composite_score": -1,
}

_ACHIEVEMENT_TOTAL_KEYS = (
    "total_minutes_find",
    "total_minutes_tracking",
    "total_sessions_find",
    "total_sessions_tracking",
    "total_find_points",
    "total_training_minutes",
)


def is_forbidden_username(username: Any) -> bool:
    """"默认用户"与空用户名视为禁止项。"""
    name = str(username or "").strip()
    return name in FORBIDDEN_USERNAMES


def build_export_payload(
    username: str,
    display_name: str,
    role: str,
    teacher_id: str,
    records: List[Dict[str, Any]],
    achievements: Dict[str, Any],
) -> Dict[str, Any]:
    """构造可导出的训练数据载荷。

    Raises:
        ValueError: 用户名为"默认用户"或空时拒绝导出。
    """
    if is_forbidden_username(username):
        raise ValueError("不允许导出默认用户/空用户名的数据")

    exported_records = []
    for record in records or []:
        item = dict(record or {})
        item.setdefault("username", username)
        exported_records.append(item)

    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": {
            "username": username,
            "display_name": display_name or username,
            "role": role or "student",
            "teacher_id": teacher_id or "",
        },
        "records": exported_records,
        "achievements": achievements or {},
    }


def serialize_payload(payload: Dict[str, Any]) -> str:
    """序列化为 JSON 文本（UTF-8，保留中文）。"""
    return json.dumps(payload, ensure_ascii=False, indent=2)


def deserialize_payload(text: str) -> Dict[str, Any]:
    """从 JSON 文本解析载荷。"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("文件不是有效的 JSON 数据") from exc
    if not isinstance(data, dict):
        raise ValueError("文件内容不是有效的训练数据 JSON")
    return data


def parse_import_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """校验导入载荷的结构与版本。

    Raises:
        ValueError: 格式/版本不匹配、缺少用户信息，或文件来自"默认用户"。
    """
    if not isinstance(data, dict):
        raise ValueError("文件内容不是有效的训练数据 JSON")
    if data.get("format") != FORMAT_NAME:
        raise ValueError("不是本软件的训练数据文件（格式标识不匹配）")
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"不支持的训练数据文件版本: {data.get('format_version')}")

    user = data.get("user")
    if not isinstance(user, dict):
        raise ValueError("文件缺少用户信息")
    if is_forbidden_username(user.get("username")):
        raise ValueError("文件包含默认用户/空用户名的数据，禁止导入")
    if not isinstance(data.get("records"), list):
        raise ValueError("文件缺少训练记录列表")
    return data


def _normalize_record(
    record: Any, target_username: str
) -> Dict[str, Any] | None:
    """规整单条记录为入库结构；记录不属于目标用户或缺少必填字段时返回 None。"""
    if not isinstance(record, dict):
        return None

    record_username = record.get("username")
    if record_username is not None and str(record_username).strip():
        if str(record_username).strip() != target_username:
            return None

    for field in _REQUIRED_RECORD_FIELDS:
        if field not in record or record[field] is None:
            return None

    norm = dict(record)
    norm["username"] = target_username
    norm["difficulty"] = str(norm.get("difficulty") or "normal")
    for key, default in _RECORD_OPTIONAL_DEFAULTS.items():
        norm.setdefault(key, default)

    try:
        for key in _INT_FIELDS:
            norm[key] = int(norm[key])
        for key in _FLOAT_FIELDS:
            norm[key] = float(norm[key])
    except (TypeError, ValueError):
        return None
    return norm


def split_incoming_records(
    records: List[Dict[str, Any]], target_username: str
) -> Tuple[List[Dict[str, Any]], int]:
    """把待导入记录分为可接受列表与被忽略数量。

    忽略规则：用户名为"默认用户"/空、记录属于其他用户、或缺少必填字段。
    """
    accepted: List[Dict[str, Any]] = []
    ignored = 0
    for record in records or []:
        if is_forbidden_username((record or {}).get("username")):
            ignored += 1
            continue
        norm = _normalize_record(record, target_username)
        if norm is None:
            ignored += 1
        else:
            accepted.append(norm)
    return accepted, ignored


def _record_identity(record: Dict[str, Any]) -> Tuple[Any, ...]:
    """记录去重标识（与 GlobalSettings 既有去重键一致）。"""
    return (
        record.get("date_time"),
        record.get("game_mode"),
        record.get("avg_attention_score"),
        record.get("game_score"),
        record.get("total_blinks"),
    )


def merge_records(
    existing_records: List[Dict[str, Any]],
    incoming_records: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """合并训练记录：返回 (新增列表, 重复跳过数)，不修改 existing_records。"""
    existing_ids = {_record_identity(r) for r in existing_records or []}
    added: List[Dict[str, Any]] = []
    seen_ids = set()
    skipped = 0
    for record in incoming_records or []:
        identity = _record_identity(record)
        if identity in existing_ids or identity in seen_ids:
            skipped += 1
            continue
        seen_ids.add(identity)
        added.append(record)
    return added, skipped


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def merge_achievements(
    existing: Dict[str, Any], incoming: Dict[str, Any]
) -> Dict[str, Any]:
    """合并成就数据：单条成就保留"已解锁"或更高进度，累计值取两者较大。"""
    merged = dict(existing or {})
    inc = incoming or {}

    for key in _ACHIEVEMENT_TOTAL_KEYS:
        if key in inc:
            merged[key] = max(_safe_int(merged.get(key)), _safe_int(inc[key]))

    by_type: Dict[Any, Dict[str, Any]] = {}
    for ach in (existing or {}).get("achievements", []) or []:
        if isinstance(ach, dict) and ach.get("type") is not None:
            by_type.setdefault(ach["type"], dict(ach))
    for ach in inc.get("achievements", []) or []:
        if not isinstance(ach, dict) or ach.get("type") is None:
            continue
        ach_type = ach["type"]
        current = by_type.get(ach_type)
        if current is None:
            by_type[ach_type] = dict(ach)
            continue
        if bool(current.get("unlocked")):
            continue
        if bool(ach.get("unlocked")) or _safe_int(ach.get("progress")) > _safe_int(
            current.get("progress")
        ):
            by_type[ach_type] = dict(ach)

    merged["achievements"] = list(by_type.values())
    return merged


def load_achievements_file(path: str) -> Dict[str, Any]:
    """读取成就文件；文件不存在或损坏时返回空字典。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_achievements_file(path: str, data: Dict[str, Any]) -> None:
    """写入成就文件（自动创建用户目录）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data or {}, handle, ensure_ascii=False, indent=2)


def _upsert_student_user(
    db: Any, username: str, display_name: str, teacher_id: str
) -> bool:
    """创建或更新学生账号（导入专用，无密码、不可登录）。返回是否新建。"""
    existing = db.query_one("SELECT username FROM users WHERE username = ?", (username,))
    if existing:
        db.execute(
            "UPDATE users SET display_name = ?, role = 'student', teacher_id = ? "
            "WHERE username = ?",
            (display_name, teacher_id, username),
        )
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO users (username, display_name, role, password_hash, teacher_id, "
        "create_time, last_login_time) VALUES (?, ?, 'student', '', ?, ?, ?)",
        (username, display_name, teacher_id, now, now),
    )
    os.makedirs(os.path.join(db.app_dir, "users", username), exist_ok=True)
    return True


@dataclass
class ImportSummary:
    """一次导入的结果统计。"""

    user_created: bool = False
    records_added: int = 0
    records_skipped: int = 0
    records_ignored: int = 0


def apply_import(
    db: Any, payload: Dict[str, Any], *, teacher_id: str = ""
) -> ImportSummary:
    """把已解析的载荷应用到本地库（合并，不覆盖其他用户）。

    teacher_id 传当前教师用户名时强制绑定该教师；传空时仅在载荷自带教师
    存在的情况下沿用。
    """
    data = parse_import_payload(payload)
    user = data["user"]
    username = user["username"]

    resolved_teacher = (teacher_id or "").strip()
    if not resolved_teacher:
        candidate = str(user.get("teacher_id") or "").strip()
        if candidate and db.query_one(
            "SELECT username FROM users WHERE username = ?", (candidate,)
        ):
            resolved_teacher = candidate

    user_created = _upsert_student_user(
        db,
        username,
        str(user.get("display_name") or username),
        resolved_teacher,
    )

    existing = db.fetch_training_records(username)
    accepted, ignored = split_incoming_records(data["records"], username)
    added, skipped = merge_records(existing, accepted)
    for record in added:
        db.insert_training_record(username, record)

    return ImportSummary(
        user_created=user_created,
        records_added=len(added),
        records_skipped=skipped,
        records_ignored=ignored,
    )
