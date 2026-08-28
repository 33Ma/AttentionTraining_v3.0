# -*- coding: utf-8 -*-
"""班级训练报告汇总纯逻辑（不依赖 Qt，可单测）。

从 ui/teacher_report_dialog.py 抽取：归一游戏分、进步幅度、时长格式化、
单学生摘要与班级统计。记录统一为 dict（与 Database.fetch_training_records
输出一致，date_time 形如 "YYYY-MM-DD HH:MM:SS"，按新→旧排列）；
兼容 TrainingRecord 对象（duck typing，见 _field）。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .composite_scoring import record_composite_score, score_ratio

MAX_STUDENTS = 40
MAX_RECORDS_PER_STUDENT = 10

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _field(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def normalized_game_score(record: Any) -> float:
    """游戏得分归一 0-100：找茬按“模式×难度”基准，动态追踪按 /100。"""
    return (
        score_ratio(
            int(_field(record, "game_score", 0) or 0),
            _field(record, "game_mode", "find_difference") or "find_difference",
            _field(record, "difficulty", "normal") or "normal",
        )
        * 100.0
    )


def composite_improvement(records: List[Any]) -> float:
    """按综合分计算进步幅度（%），截断 ±100；records 按新→旧。"""
    if len(records) < 2:
        return 0.0
    compare_count = 3 if len(records) >= 6 else (2 if len(records) >= 4 else 1)
    recent_avg = (
        sum(record_composite_score(r) for r in records[:compare_count])
        // compare_count
    )
    early_avg = (
        sum(record_composite_score(r) for r in records[-compare_count:])
        // compare_count
    )
    if early_avg == 0:
        return 100.0 if recent_avg > 0 else 0.0
    return max(-100.0, min(100.0, ((recent_avg - early_avg) / early_avg) * 100.0))


def format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}分钟"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}小时"
    return f"{hours}小时{mins}分钟"


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), _DATE_FORMAT)
    except ValueError:
        return None


def filter_records(records: List[Any], filter_days: int = 0) -> List[Any]:
    """时间过滤，语义与班级报告窗口一致：
    0=全部；>0=最近 N 天（含今天）；-1=本月；-2=上月。"""
    if filter_days == 0:
        return list(records)
    now = datetime.now()
    if filter_days > 0:
        cutoff = now - timedelta(days=filter_days)
    elif filter_days == -1:
        cutoff = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif filter_days == -2:
        first_this_month = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        last_month_end = first_this_month - timedelta(days=1)
        cutoff = last_month_end.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
    else:
        cutoff = now
    result = []
    for record in records:
        dt = _parse_dt(_field(record, "date_time", ""))
        if dt is None or dt >= cutoff:
            result.append(record)
    return result


def compute_student_summary(
    username: str,
    display_name: str,
    records: List[Any],
    filter_days: int = 0,
    achievements: int = 0,
) -> Dict[str, Any]:
    """单学生摘要；improvement 用全部记录（与报告窗口一致）。"""
    filtered = filter_records(records, filter_days)
    summary: Dict[str, Any] = {
        "name": username,
        "display_name": display_name or username,
        "total_trainings": len(filtered),
        "total_minutes": 0,
        "avg_attention": 0,
        "max_attention": 0,
        "avg_game_score": 0,
        "avg_composite": 0,
        "achievements": int(achievements or 0),
        "improvement": 0.0,
        "last_training": "无",
    }
    if not filtered:
        return summary

    attention_sum = 0
    score_sum = 0
    composite_sum = 0
    for record in filtered:
        summary["total_minutes"] += int(_field(record, "duration_minutes", 0) or 0)
        attention = int(_field(record, "avg_attention_score", 0) or 0)
        attention_sum += attention
        summary["max_attention"] = max(summary["max_attention"], attention)
        score_sum += normalized_game_score(record)
        composite_sum += record_composite_score(record)

    summary["avg_attention"] = attention_sum // len(filtered)
    summary["avg_game_score"] = int(round(score_sum / len(filtered)))
    summary["avg_composite"] = composite_sum // len(filtered)

    last_dt = _parse_dt(_field(filtered[0], "date_time", ""))
    if last_dt is not None:
        summary["last_training"] = last_dt.strftime("%m-%d %H:%M")

    if len(records) >= 2:
        summary["improvement"] = composite_improvement(records)
    return summary


def compute_class_stats(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从学生摘要聚合班级统计。"""
    total_attention = 0
    total_minutes = 0
    total_trainings = 0
    valid_count = 0
    top_improvement = -101.0
    top_student = None

    for s in summaries:
        total_minutes += s["total_minutes"]
        total_trainings += s["total_trainings"]
        if s["total_trainings"] > 0:
            valid_count += 1
            total_attention += s["avg_attention"]
        if s["improvement"] > top_improvement and s["total_trainings"] >= 3:
            top_improvement = s["improvement"]
            top_student = s

    class_composite = (
        sum(s["avg_composite"] for s in summaries) // len(summaries)
        if summaries
        else 0
    )
    improving = sum(1 for s in summaries if s["improvement"] > 5)
    declining = sum(1 for s in summaries if s["improvement"] < -5)
    best = max(summaries, key=lambda s: s["avg_composite"]) if summaries else None
    worst = min(summaries, key=lambda s: s["avg_composite"]) if summaries else None

    return {
        "total_students": len(summaries),
        "valid_students": valid_count,
        "total_trainings": total_trainings,
        "total_minutes": total_minutes,
        "class_avg_attention": total_attention // valid_count if valid_count else 0,
        "class_avg_composite": class_composite,
        "improving": improving,
        "declining": declining,
        "stable": len(summaries) - improving - declining,
        "best": best,
        "worst": worst,
        "top_improvement_student": top_student,
    }


def compute_class_summaries(
    students: List[Any],
    records_map: Dict[str, List[Any]],
    filter_days: int = 0,
    achievements_map: Optional[Dict[str, int]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """按给定学生列表与记录映射输出 (summaries, stats)。"""
    achievements_map = achievements_map or {}
    summaries = []
    for student in students[:MAX_STUDENTS]:
        if isinstance(student, dict):
            username = student.get("username", "")
            display_name = student.get("display_name", "") or username
        else:
            username = getattr(student, "username", "")
            display_name = getattr(student, "display_name", "") or username
        records = records_map.get(username) or []
        summaries.append(
            compute_student_summary(
                username,
                display_name,
                records,
                filter_days=filter_days,
                achievements=achievements_map.get(username, 0),
            )
        )
    return summaries, compute_class_stats(summaries)
