import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from .paths import app_data_dir, database_path


DB_FILENAME = "attention_data.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    teacher_id TEXT NOT NULL DEFAULT '',
    create_time TEXT NOT NULL,
    last_login_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS training_records (
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
    face_detected INTEGER NOT NULL DEFAULT -1,
    hit_rate REAL NOT NULL DEFAULT 0.0,
    avg_response_time REAL NOT NULL DEFAULT 0.0,
    path_efficiency REAL NOT NULL DEFAULT 0.0,
    composite_score INTEGER NOT NULL DEFAULT -1
);

CREATE INDEX IF NOT EXISTS idx_training_records_username_datetime
    ON training_records(username, date_time DESC);

CREATE TABLE IF NOT EXISTS coach_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    create_time TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_coach_messages_username_id
    ON coach_messages(username, id);
"""


class Database:
    """Small SQLite access layer used by user and training data stores."""

    _instance: Optional["Database"] = None

    def __new__(cls) -> "Database":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self.app_dir = app_data_dir()
        self.db_path = database_path()
        self.initialize()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._ensure_column(
                conn, "training_records", "avg_gaze_score",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn, "training_records", "avg_gaze_distance",
                "REAL NOT NULL DEFAULT 0.0",
            )
            self._ensure_column(
                conn, "training_records", "max_consecutive_hits",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn, "training_records", "face_detected",
                "INTEGER NOT NULL DEFAULT -1",
            )
            self._ensure_column(
                conn, "training_records", "hit_rate",
                "REAL NOT NULL DEFAULT 0.0",
            )
            self._ensure_column(
                conn, "training_records", "avg_response_time",
                "REAL NOT NULL DEFAULT 0.0",
            )
            self._ensure_column(
                conn, "training_records", "path_efficiency",
                "REAL NOT NULL DEFAULT 0.0",
            )
            self._ensure_column(
                conn, "training_records", "composite_score",
                "INTEGER NOT NULL DEFAULT -1",
            )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        """Add a column to an existing table when it is missing (schema migration)."""
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def query(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            cursor = conn.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, tuple(params))

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    def fetch_users(self) -> List[Dict[str, Any]]:
        return self.query(
            """
            SELECT username, display_name, role, password_hash, teacher_id,
                   create_time, last_login_time
            FROM users
            ORDER BY username
            """
        )

    def replace_users(self, users: List[Dict[str, Any]]) -> None:
        """Atomically replace all user rows with the supplied snapshot."""
        with self.connect() as conn:
            conn.execute("DELETE FROM users")
            conn.executemany(
                """
                INSERT INTO users (
                    username, display_name, role, password_hash, teacher_id,
                    create_time, last_login_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        user["username"],
                        user["display_name"],
                        user["role"],
                        user["password_hash"],
                        user["teacher_id"],
                        user["create_time"],
                        user["last_login_time"],
                    )
                    for user in users
                ],
            )

    # ------------------------------------------------------------------
    # Training records
    # ------------------------------------------------------------------
    def fetch_training_records(self, username: str) -> List[Dict[str, Any]]:
        return self.query(
            """
            SELECT date_time, duration_minutes, game_mode, difficulty,
                   avg_attention_score, total_blinks, game_score, avg_ear,
                   avg_gaze_score, avg_gaze_distance,
                   max_consecutive_hits, face_detected,
                   hit_rate, avg_response_time, path_efficiency,
                   composite_score
            FROM training_records
            WHERE username = ?
            ORDER BY date_time DESC, id DESC
            """,
            (username,),
        )

    def replace_training_records(
        self, username: str, records: List[Dict[str, Any]]
    ) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM training_records WHERE username = ?", (username,))
            conn.executemany(
                """
                INSERT INTO training_records (
                    username, date_time, duration_minutes, game_mode, difficulty,
                    avg_attention_score, total_blinks, game_score, avg_ear,
                    avg_gaze_score, avg_gaze_distance,
                    max_consecutive_hits, face_detected,
                    hit_rate, avg_response_time, path_efficiency,
                    composite_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        username,
                        record["date_time"],
                        record["duration_minutes"],
                        record["game_mode"],
                        record["difficulty"],
                        record["avg_attention_score"],
                        record["total_blinks"],
                        record["game_score"],
                        record["avg_ear"],
                        record.get("avg_gaze_score", 0),
                        record.get("avg_gaze_distance", 0.0),
                        record.get("max_consecutive_hits", 0),
                        record.get("face_detected", -1),
                        record.get("hit_rate", 0.0),
                        record.get("avg_response_time", 0.0),
                        record.get("path_efficiency", 0.0),
                        record.get("composite_score", -1),
                    )
                    for record in records
                ],
            )

    def insert_training_record(
        self, username: str, record: Dict[str, Any]
    ) -> None:
        """Append one training record without rewriting the whole history."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO training_records (
                    username, date_time, duration_minutes, game_mode, difficulty,
                    avg_attention_score, total_blinks, game_score, avg_ear,
                    avg_gaze_score, avg_gaze_distance,
                    max_consecutive_hits, face_detected,
                    hit_rate, avg_response_time, path_efficiency,
                    composite_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    record["date_time"],
                    record["duration_minutes"],
                    record["game_mode"],
                    record["difficulty"],
                    record["avg_attention_score"],
                    record["total_blinks"],
                    record["game_score"],
                    record["avg_ear"],
                    record.get("avg_gaze_score", 0),
                    record.get("avg_gaze_distance", 0.0),
                    record.get("max_consecutive_hits", 0),
                    record.get("face_detected", -1),
                    record.get("hit_rate", 0.0),
                    record.get("avg_response_time", 0.0),
                    record.get("path_efficiency", 0.0),
                    record.get("composite_score", -1),
                ),
            )

    def clear_training_records(self, username: str) -> None:
        self.execute("DELETE FROM training_records WHERE username = ?", (username,))

    # ------------------------------------------------------------------
    # AI 教练对话
    # ------------------------------------------------------------------
    def fetch_coach_messages(self, username: str, limit: int = 50) -> List[Dict[str, Any]]:
        """返回用户最近 limit 条教练对话，按时间正序排列。"""
        if limit <= 0:
            return []
        rows = self.query(
            """
            SELECT id, username, role, content, create_time
            FROM coach_messages
            WHERE username = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (username, limit),
        )
        return list(reversed(rows))

    def add_coach_message(
        self,
        username: str,
        role: str,
        content: str,
        create_time: Optional[str] = None,
    ) -> None:
        """追加一条教练对话消息（role 为 user / assistant）。"""
        from datetime import datetime

        if create_time is None:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.execute(
            """
            INSERT INTO coach_messages (username, role, content, create_time)
            VALUES (?, ?, ?, ?)
            """,
            (username, role, content, create_time),
        )

    def clear_coach_messages(self, username: str) -> None:
        """清空指定用户的教练对话记录。"""
        self.execute("DELETE FROM coach_messages WHERE username = ?", (username,))


def get_database() -> Database:
    return Database()
