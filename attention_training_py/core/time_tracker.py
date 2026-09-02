# -*- coding: utf-8 -*-
"""ONNX 模型推理耗时记录：逐模型逐帧写入 time_consumed.db（SQLite）。

每个模型每次实际推理写一行，字段包括运行批次(run_id)、时间戳、帧号、
耗时(ms)、是否成功、画面宽高、当前启用的模型组合(config)。
后续性能改进直接分析该文件：按 run_id 分次、按 config 分档（2/3/4 模型）、
按 model 看单模型耗时、按 frame 看采样节拍。

计时写入失败只打印警告，绝不影响摄像头/推理主流程。
"""

import os
import sqlite3
import threading
import time

from .paths import app_data_dir

DB_FILENAME = "time_consumed.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_timing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    model TEXT NOT NULL,
    frame INTEGER NOT NULL,
    duration_ms REAL NOT NULL,
    ok INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    config TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_model_timing_run_model
    ON model_timing (run_id, model);
"""


class TimeTracker:
    """线程安全的计时落库器。"""

    def __init__(self, db_path=None):
        self._db_path = db_path or os.path.join(app_data_dir(), DB_FILENAME)
        self._lock = threading.Lock()
        self._conn = None
        self._run_id = time.strftime("%Y%m%d-%H%M%S")
        self._config = ""

    def set_config(self, enabled_models):
        """记录当前启用的模型组合，便于按 2/3/4 模型档位分组分析。"""
        self._config = ",".join(sorted(enabled_models)) if enabled_models else ""

    def record(self, model, frame, duration_ms, ok, width=0, height=0):
        """写入一行模型推理耗时；任何失败都静默，不影响推理主流程。"""
        try:
            with self._lock:
                if self._conn is None:
                    conn = sqlite3.connect(self._db_path, timeout=5.0)
                    conn.executescript(_SCHEMA)
                    self._conn = conn
                self._conn.execute(
                    "INSERT INTO model_timing "
                    "(run_id, ts, model, frame, duration_ms, ok, width, height, config) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._run_id,
                        time.strftime("%Y-%m-%d %H:%M:%S"),
                        model,
                        int(frame),
                        float(duration_ms),
                        1 if ok else 0,
                        int(width),
                        int(height),
                        self._config,
                    ),
                )
                self._conn.commit()
        except Exception as exc:
            print(f"TimeTracker: 写入 {self._db_path} 失败: {exc}")

    def close(self):
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None


_default_tracker = None
_default_lock = threading.Lock()


def get_tracker() -> TimeTracker:
    """返回进程内共享的计时器（摄像头管线与引擎共用同一配置）。"""
    global _default_tracker
    if _default_tracker is None:
        with _default_lock:
            if _default_tracker is None:
                _default_tracker = TimeTracker()
    return _default_tracker
