# -*- coding: utf-8 -*-
"""本地 ONNX 智能分析验证脚本。

用法（Python 3.11 环境，需 onnxruntime）：
    python tools/verify_local_analysis.py

覆盖：模型可用性、典型输入、确定性、真实训练记录全量推理、
模式推荐，以及模型缺失时的规则回退。
"""

import os
import sqlite3
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ai.local_analysis import LocalAnalysisEngine  # noqa: E402


def main() -> int:
    eng = LocalAnalysisEngine.instance()
    print("本地 ONNX 分析可用:", eng.available())
    if not eng.available():
        print("模型缺失或 onnxruntime 不可用，后续用例将验证规则回退。")

    cases = [
        ("high_focus", dict(
            avg_attention=92, total_blinks=30, max_consecutive_hits=25,
            game_score=700, game_mode="dynamic_tracking", duration_minutes=10,
            avg_gaze_score=95, avg_gaze_distance=0.04)),
        ("fatigue", dict(
            avg_attention=42, total_blinks=380, max_consecutive_hits=6,
            game_score=120, game_mode="find_difference", duration_minutes=10,
            avg_gaze_score=48, avg_gaze_distance=0.42)),
        ("average", dict(
            avg_attention=58, total_blinks=150, max_consecutive_hits=9,
            game_score=210, game_mode="find_difference", duration_minutes=15,
            avg_gaze_score=70, avg_gaze_distance=0.18)),
    ]

    for name, kw in cases:
        pred = eng.predict_session(**kw)
        r1 = eng.analyze_session(**kw)
        r2 = eng.analyze_session(**kw)
        assert r1 == r2, f"{name}: deterministic check failed"
        assert len(r1) > 200, f"{name}: report too short"
        print(f"[OK] {name}: pred={pred} len={len(r1)}")

    # 真实训练记录全量推理
    db_path = os.path.join(ROOT, "attention_data.db")
    if os.path.exists(db_path):
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT game_mode,avg_attention_score,total_blinks,game_score,"
            "duration_minutes,avg_gaze_score,avg_gaze_distance "
            "FROM training_records"
        ).fetchall()
        con.close()
        for r in rows:
            text = eng.analyze_session(
                avg_attention=r[1], total_blinks=r[2], max_consecutive_hits=0,
                game_score=r[3], game_mode=r[0], duration_minutes=r[4] or 1,
                avg_gaze_score=r[5] or 0, avg_gaze_distance=r[6] or 0.0)
            assert len(text) > 200, "real record report too short"
        print(f"[OK] 真实训练记录全量推理: {len(rows)} 条")
    else:
        print("[SKIP] 未找到 attention_data.db，跳过真实记录验证")

    # 模式推荐
    history = [
        {"game_mode": "find_difference", "avg_attention_score": 55, "game_score": 180},
        {"game_mode": "find_difference", "avg_attention_score": 60, "game_score": 220},
        {"game_mode": "dynamic_tracking", "avg_attention_score": 72, "game_score": 420},
    ]
    mode, diff = eng.recommend_mode(history)
    assert mode in ("find_difference", "dynamic_tracking")
    assert diff in ("Easy", "Normal", "Hard")
    print(f"[OK] 模式推荐: {mode} / {diff}；空历史: {eng.recommend_mode([])}")

    # 模型缺失回退
    original = eng._model_path
    try:
        eng._model_path = lambda name: os.path.join("__missing__", name)
        fallback_text = eng.analyze_session(**cases[0][1])
        assert len(fallback_text) > 200
        assert "规则" in fallback_text
        assert eng.recommend_mode(history) in (
            ("find_difference", "Easy"), ("find_difference", "Normal"),
            ("find_difference", "Hard"), ("dynamic_tracking", "Easy"),
            ("dynamic_tracking", "Normal"), ("dynamic_tracking", "Hard"),
        )
        print("[OK] 模型缺失时规则回退正常")
    finally:
        eng._model_path = original

    print("全部验证通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
