"""One-off migration from the legacy Users/JSON files into SQLite.

The script reads:
  - ``attention_training_py/users.json`` for account metadata and password hashes
  - ``attention_training_py/users/<username>/settings.ini`` for training records

and writes them into the SQLite tables used by :mod:`core.database`:
  - ``users``
  - ``training_records``

The legacy Qt ``@DateTime(...)`` values are decoded directly, so this script does
not require PySide6.

Usage:
    python migrate_to_sqlite.py [--dry-run]
"""

from __future__ import annotations

import argparse
import configparser
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parent
APP_DIR = ROOT_DIR / "attention_training_py"
USERS_DIR = APP_DIR / "users"
USERS_JSON = APP_DIR / "users.json"
DATABASE_MODULE = APP_DIR / "core" / "database.py"


_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_OCT_DIGITS = frozenset("01234567")


def _load_database_module():
    """Load ``core/database.py`` without triggering PySide6 imports."""
    spec = importlib.util.spec_from_file_location("attention_training_database", DATABASE_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load database module: {DATABASE_MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _decode_qt_ini_bytes(raw: str) -> bytes:
    """Decode the escaped byte payload found inside ``@DateTime(...)``."""
    out = bytearray()
    i = 0
    n = len(raw)

    while i < n:
        ch = raw[i]
        if ch != "\\":
            out.append(ord(ch) & 0xFF)
            i += 1
            continue

        i += 1
        if i >= n:
            break

        esc = raw[i]
        if esc == "x":
            i += 1
            start = i
            while i < n and raw[i] in _HEX_DIGITS:
                i += 1
            out.append(int(raw[start:i], 16) & 0xFF if i > start else 0)
        elif esc in _OCT_DIGITS:
            start = i
            while i < n and i < start + 3 and raw[i] in _OCT_DIGITS:
                i += 1
            out.append(int(raw[start:i], 8) & 0xFF)
        else:
            replacements = {
                "0": 0,
                "a": 7,
                "b": 8,
                "f": 12,
                "n": 10,
                "r": 13,
                "t": 9,
                "v": 11,
            }
            out.append(replacements.get(esc, ord(esc)) & 0xFF)
            i += 1

    return bytes(out)


def _julian_day_to_date(jd: int) -> Optional[date]:
    """Convert Qt's Julian-day representation to a Python date."""
    if jd <= 0:
        return None
    try:
        return date(2000, 1, 1) + timedelta(days=jd - 2451545)
    except (OverflowError, ValueError):
        return None


def _parse_qt_datetime(value: str) -> str:
    """Parse a legacy ``@DateTime(...)`` QSettings value into ``YYYY-MM-DD HH:MM:SS``."""
    if not value.startswith("@DateTime(") or not value.endswith(")"):
        return ""

    raw = value[len("@DateTime(") : -1]
    payload = _decode_qt_ini_bytes(raw)

    # QVariant stream: quint32 type id, quint8 null flag, then QDateTime:
    # qint64 julian day, quint32 milliseconds since midnight, qint8 time spec.
    if len(payload) < 18:
        return ""

    type_id = int.from_bytes(payload[0:4], "big")
    if type_id != 16:  # QMetaType::QDateTime in the Qt 5 series
        return ""

    julian_day = int.from_bytes(payload[5:13], "big", signed=True)
    msecs = int.from_bytes(payload[13:17], "big")

    parsed_date = _julian_day_to_date(julian_day)
    if parsed_date is None or msecs > 86_399_999:
        return ""

    hours, remainder = divmod(msecs, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds = remainder // 1000
    time_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{parsed_date.isoformat()} {time_text}"


def _to_int(value: Optional[str], default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _normalize_difficulty(value: Optional[str]) -> str:
    if value is None:
        return "normal"
    text = str(value).strip()
    if text.isdigit():
        value = int(text)
    if isinstance(value, int):
        return {0: "easy", 1: "normal", 2: "hard", 3: "custom"}.get(value, "normal")
    if text in {"easy", "normal", "hard", "custom"}:
        return text
    return "normal"


def _read_settings(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def _parse_training_records(config: configparser.ConfigParser) -> List[Dict[str, object]]:
    """Read both new and legacy training-record groups, deduplicating by record key."""
    records: List[Dict[str, object]] = []
    seen = set()

    for section, legacy in (("training_records", False), ("trainingRecords", True)):
        if not config.has_section(section):
            continue

        size = _to_int(config.get(section, "size", fallback="0"))
        for index in range(1, size + 1):
            prefix = f"{index}\\"

            if legacy:
                raw_date = config.get(section, prefix + "dateTime", fallback="")
                date_time = _parse_qt_datetime(raw_date)
                duration = _to_int(config.get(section, prefix + "durationMinutes", fallback="0"))
                game_mode = config.get(section, prefix + "gameMode", fallback="")
                difficulty_raw = config.get(section, prefix + "difficulty", fallback="normal")
                avg_attention = _to_int(config.get(section, prefix + "avgAttentionScore", fallback="0"))
                total_blinks = _to_int(config.get(section, prefix + "totalBlinks", fallback="0"))
                game_score = _to_int(config.get(section, prefix + "gameScore", fallback="0"))
                avg_ear = _to_float(config.get(section, prefix + "avgEAR", fallback="0"))
            else:
                raw_date = config.get(section, prefix + "date_time", fallback="")
                date_time = raw_date.strip()
                duration = _to_int(config.get(section, prefix + "duration_minutes", fallback="0"))
                game_mode = config.get(section, prefix + "game_mode", fallback="")
                difficulty_raw = config.get(section, prefix + "difficulty", fallback="normal")
                avg_attention = _to_int(config.get(section, prefix + "avg_attention_score", fallback="0"))
                total_blinks = _to_int(config.get(section, prefix + "total_blinks", fallback="0"))
                game_score = _to_int(config.get(section, prefix + "game_score", fallback="0"))
                avg_ear = _to_float(config.get(section, prefix + "avg_ear", fallback="0"))

            if not date_time:
                continue

            key = (date_time, game_mode, avg_attention, game_score, total_blinks)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "date_time": date_time,
                    "duration_minutes": duration,
                    "game_mode": game_mode,
                    "difficulty": _normalize_difficulty(difficulty_raw),
                    "avg_attention_score": avg_attention,
                    "total_blinks": total_blinks,
                    "game_score": game_score,
                    "avg_ear": avg_ear,
                }
            )

    records.sort(key=lambda item: str(item["date_time"]), reverse=True)
    return records


def _load_users_json() -> Tuple[Dict[str, dict], Dict[str, str]]:
    users: Dict[str, dict] = {}
    passwords: Dict[str, str] = {}

    if not USERS_JSON.exists():
        return users, passwords

    with USERS_JSON.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    for user in data.get("users", []):
        users[user["username"]] = user
    for entry in data.get("passwords", []):
        passwords[entry["username"]] = entry.get("password_hash", "")

    return users, passwords


def _build_user_rows(
    users_by_name: Dict[str, dict], passwords: Dict[str, str], usernames: Iterable[str]
) -> List[Dict[str, object]]:
    now = datetime.now().isoformat()
    rows: List[Dict[str, object]] = []

    for username in sorted(usernames):
        old = users_by_name.get(username, {})
        rows.append(
            {
                "username": username,
                "display_name": old.get("display_name") or username,
                "role": old.get("role", "student"),
                "password_hash": passwords.get(username, ""),
                "teacher_id": old.get("teacher_id", ""),
                "create_time": old.get("create_time") or now,
                "last_login_time": old.get("last_login_time") or now,
            }
        )

    return rows


def migrate(dry_run: bool = False) -> None:
    database_module = _load_database_module()
    database = database_module.Database()

    users_by_name, passwords = _load_users_json()

    directory_names: List[str] = []
    if USERS_DIR.exists():
        directory_names = sorted(p.name for p in USERS_DIR.iterdir() if p.is_dir())

    usernames = set(users_by_name) | set(directory_names)
    user_rows = _build_user_rows(users_by_name, passwords, usernames)

    training_counts: Dict[str, int] = {}
    for username in sorted(directory_names):
        settings_path = USERS_DIR / username / "settings.ini"
        if not settings_path.exists():
            continue
        records = _parse_training_records(_read_settings(settings_path))
        if records:
            training_counts[username] = len(records)
            if not dry_run:
                database.replace_training_records(username, records)

    print(f"{'[dry-run] ' if dry_run else ''}Users to write: {len(user_rows)}")
    for row in user_rows:
        print(
            f"  - {row['username']} ({row['role']}, "
            f"display_name={row['display_name']!r}, teacher_id={row['teacher_id']!r})"
        )

    print(f"{'[dry-run] ' if dry_run else ''}Users with training records: {len(training_counts)}")
    for username, count in sorted(training_counts.items()):
        print(f"  - {username}: {count} record(s)")

    if dry_run:
        print("Dry run completed; no data was written.")
        return

    database.replace_users(user_rows)
    print("Migration completed.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy Users data into SQLite.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report only; do not write to SQLite.",
    )
    args = parser.parse_args(argv)
    migrate(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
