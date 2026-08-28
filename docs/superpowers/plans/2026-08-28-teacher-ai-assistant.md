# 教师端 AI 助教（AI 教学助手）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为学生端 AI 教练对应的教师端新增"AI 助教"多轮对话能力，可分析班级学生数据（班级整体 + 单学生下钻）并给出教学建议，云端 LLM 与本地规则双通道。

**Architecture:** 镜像学生端 `ai/ai_coach.py` 的服务层模式，新增四个模块：`ai/teacher_report_logic.py`（从 `TeacherReportDialog` 抽取的班级汇总纯函数）、`ai/teacher_coach_logic.py`（提示词 + 本地规则回复）、`ai/teacher_coach.py`（Manager/Worker 线程队列）、`ui/teacher_coach_dialog.py`（聊天窗）。历史复用 `coach_messages` 表，云端配置复用 `GlobalSettings`，入口接在主窗口与班级报告窗口。

**Tech Stack:** Python 3.9-3.11、PySide6 6.x、SQLite（复用 `core/database.py`）、requests（OpenAI 兼容 API）、unittest（项目无 pytest）。

**Spec:** [docs/superpowers/specs/2026-08-28-teacher-ai-assistant-design.md](../specs/2026-08-28-teacher-ai-assistant-design.md)

## Global Constraints

- 项目解释器：`C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe`（3.11.9，PySide6 6.11.1，无 pytest）。在 Codex 沙箱中运行该解释器需要批准/提权。
- 所有测试命令在 `attention_training_py` 目录下执行，且带 `$env:QT_QPA_PLATFORM='offscreen'`（涉及 Qt 导入）。示例：
  ```powershell
  cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
  $env:QT_QPA_PLATFORM='offscreen'
  & "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_report_logic -v
  ```
- 工作区有大量未提交的在制改动（学生端 AI 教练等）。**禁止 `git add -A` / `git add .` / 批量暂存**；每个提交只 `git add` 本任务明确列出的文件。
- 不修改 `ai/ai_coach.py`、`ai/coach_logic.py` 的业务逻辑（`teacher_coach.py` 只 import 其纯函数 `trim_history`、`normalize_chat_completions_url`）。
- 不新增数据库表、不新增 ONNX 模型；本地回退一律用统计规则模板。
- 新文件与修改保持 UTF-8 无 BOM。若 `apply_patch` 的 Update 失效（已知沙箱问题），用 PowerShell 精确文本替换并显式写 UTF-8 无 BOM。
- 中文 UI 文案，助教人设文案与消息样式沿用学生端风格（emoji 前缀、`🤖 助教：` 块）。
- 上下文上限：`MAX_STUDENTS = 40`，每名学生 `MAX_RECORDS_PER_STUDENT = 10`。

## File Structure

| 文件 | 责任 | 操作 |
|---|---|---|
| `ai/teacher_report_logic.py` | 班级汇总纯函数（归一游戏分、进步、时长、单学生摘要、班级统计） | 新建 |
| `ai/teacher_coach_logic.py` | 助教人设提示词、班级上下文格式化、本地规则回复 | 新建 |
| `ai/teacher_coach.py` | `TeacherCoachManager` 单例 + `TeacherCoachWorker` 线程队列 | 新建 |
| `ui/teacher_coach_dialog.py` | 助教聊天对话框 | 新建 |
| `ui/teacher_report_dialog.py` | 改用汇总纯函数；新增"咨询AI助教"按钮 | 修改 |
| `ui/main_window.py` | 教师/管理员主窗口"🤖 AI助教"按钮 | 修改 |
| `main.py` | 退出清理接入 `TeacherCoachManager` | 修改 |
| `pyproject.toml`、`AttentionTrainingApp.spec` | 打包清单补 4 个新模块 | 修改 |
| `tests/test_teacher_report_logic.py` | 新增模块级汇总用例 | 修改 |
| `tests/test_teacher_coach_logic.py` | 提示词与本地回复用例 | 新建 |
| `tests/test_teacher_coach.py` | 服务层单例/信号/取消用例 | 新建 |
| `tests/test_teacher_coach_smoke.py` | 导入冒烟 | 新建 |

`dynamic_build.py` 会自动收集 `ai/`、`ui/` 下非 `_` 前缀的模块，无需改动。

---

### Task 1: 班级汇总纯逻辑模块 `ai/teacher_report_logic.py`

**Files:**
- Create: `attention_training_py/ai/teacher_report_logic.py`
- Test: `attention_training_py/tests/test_teacher_report_logic.py`（追加用例）

**Interfaces:**
- Consumes: `ai/composite_scoring.record_composite_score(record) -> int`、`ai/composite_scoring.score_ratio(game_score, game_mode, difficulty) -> float`；记录 dict 键与 `core.database.Database.fetch_training_records` 输出一致（`date_time` 为 `"YYYY-MM-DD HH:MM:SS"` 字符串，新→旧）。
- Produces:
  - `normalized_game_score(record) -> float`
  - `composite_improvement(records) -> float`（±100 截断）
  - `format_duration(minutes: int) -> str`
  - `filter_records(records, filter_days: int = 0) -> list`
  - `compute_student_summary(username, display_name, records, filter_days=0, achievements=0) -> Dict`
  - `compute_class_stats(summaries) -> Dict`
  - `compute_class_summaries(students, records_map, filter_days=0, achievements_map=None) -> Tuple[List[Dict], Dict]`
  - 常量 `MAX_STUDENTS = 40`、`MAX_RECORDS_PER_STUDENT = 10`

- [ ] **Step 1: 写失败测试** — 在 `tests/test_teacher_report_logic.py` 头部追加 import，并追加新测试类：

```python
from ai.teacher_report_logic import (
    compute_class_stats,
    compute_class_summaries,
    compute_student_summary,
    filter_records,
    format_duration,
)


def _dict_record(dt: str, attention: int = 80, score: int = 290,
                 mode: str = "find_difference", difficulty: str = "normal",
                 composite: int = 70, minutes: int = 10) -> dict:
    return {
        "date_time": dt, "duration_minutes": minutes, "game_mode": mode,
        "difficulty": difficulty, "avg_attention_score": attention,
        "total_blinks": 100, "game_score": score, "avg_ear": 0.3,
        "avg_gaze_score": 80, "avg_gaze_distance": 0.1,
        "max_consecutive_hits": 10, "face_detected": 1,
        "hit_rate": 0.8, "avg_response_time": 0.4, "path_efficiency": 0.7,
        "composite_score": composite,
    }


class TeacherReportModuleTests(unittest.TestCase):
    def test_module_normalized_score_matches_dialog(self):
        r = _record("find_difference", 290, "normal", 70)
        self.assertAlmostEqual(
            normalized_game_score(r), TeacherReportDialog._normalized_game_score(r)
        )

    def test_filter_records_last_7_days(self):
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        old = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
        records = [_dict_record(today), _dict_record(old)]
        kept = filter_records(records, filter_days=7)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["date_time"], today)

    def test_filter_records_current_month(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        first_this = now.replace(day=1).strftime("%Y-%m-%d 08:00:00")
        last_month = (
            now.replace(day=1) - timedelta(days=1)
        ).replace(day=15).strftime("%Y-%m-%d 08:00:00")
        records = [_dict_record(first_this), _dict_record(last_month)]
        self.assertEqual(len(filter_records(records, filter_days=-1)), 1)

    def test_compute_student_summary_aggregates(self):
        records = [
            _dict_record("2026-08-26 10:30:00", attention=90, score=580,
                         composite=88, minutes=12),
            _dict_record("2026-08-20 09:00:00", attention=70, score=290,
                         composite=60, minutes=8),
        ]
        s = compute_student_summary("stu1", "小明", records, achievements=2)
        self.assertEqual(s["total_trainings"], 2)
        self.assertEqual(s["total_minutes"], 20)
        self.assertEqual(s["avg_attention"], 80)
        self.assertEqual(s["max_attention"], 90)
        self.assertEqual(s["achievements"], 2)
        self.assertEqual(s["last_training"], "08-26 10:30")
        self.assertGreater(s["improvement"], 0)

    def test_compute_class_summaries_caps_students(self):
        students = [{"username": f"s{i}", "display_name": f"学生{i}"} for i in range(45)]
        summaries, stats = compute_class_summaries(students, {})
        self.assertEqual(len(summaries), 40)
        self.assertEqual(stats["total_students"], 40)

    def test_compute_class_stats_improving_declining(self):
        summaries = [
            {"display_name": "A", "avg_composite": 80, "improvement": 10.0,
             "total_trainings": 5, "total_minutes": 50, "avg_attention": 80},
            {"display_name": "B", "avg_composite": 30, "improvement": -20.0,
             "total_trainings": 5, "total_minutes": 50, "avg_attention": 40},
            {"display_name": "C", "avg_composite": 50, "improvement": 0.0,
             "total_trainings": 0, "total_minutes": 0, "avg_attention": 0},
        ]
        stats = compute_class_stats(summaries)
        self.assertEqual(stats["improving"], 1)
        self.assertEqual(stats["declining"], 1)
        self.assertEqual(stats["stable"], 1)
        self.assertEqual(stats["valid_students"], 2)
        self.assertEqual(stats["best"]["display_name"], "A")
        self.assertEqual(stats["worst"]["display_name"], "B")

    def test_format_duration(self):
        self.assertEqual(format_duration(45), "45分钟")
        self.assertEqual(format_duration(60), "1小时")
        self.assertEqual(format_duration(75), "1小时15分钟")
```

同时把顶部 import 补上 `normalized_game_score` 与 `composite_improvement`（`from ai.teacher_report_logic import (...)` 列表中加入）。注意 `_record`/`TeacherReportDialog` 已在原文件定义，新增用例直接复用。

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_report_logic -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'ai.teacher_report_logic'`）。

- [ ] **Step 3: 实现模块** — 新建 `ai/teacher_report_logic.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_report_logic -v
```

Expected: 原有用例 + 新增用例全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add attention_training_py/ai/teacher_report_logic.py attention_training_py/tests/test_teacher_report_logic.py
git commit -m "feat(teacher): 抽取班级报告汇总纯逻辑模块"
```

---

### Task 2: 班级报告窗口改用汇总纯逻辑

**Files:**
- Modify: `attention_training_py/ui/teacher_report_dialog.py`
- Test: `attention_training_py/tests/test_teacher_report_logic.py`（不改，作为回归）

**Interfaces:**
- Consumes: Task 1 的 `compute_class_summaries`、`format_duration`、`normalized_game_score`、`composite_improvement`。
- Produces: `_load_student_list` 行为与旧版一致（表格/下拉/统计卡片数值不变）；`_count_achievements(username) -> int` 静态方法；静态包装 `_normalized_game_score`、`_composite_improvement`、`_format_duration` 保持签名不变（现有测试依赖）。

- [ ] **Step 1: 写失败测试（行为回归）** — 现有 `tests/test_teacher_report_logic.py` 的三个用例已经覆盖静态包装方法；无需新测试。本步改为：运行现有测试确认基线通过。

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_report_logic -v
```

Expected: PASS。

- [ ] **Step 2: 修改 `ui/teacher_report_dialog.py`** — 共 4 处修改：

1) import 区：把
`from ai.composite_scoring import record_composite_score, score_ratio`
删除（归一/进步逻辑已移入纯逻辑模块），并在原位置新增：
```python
from ai.teacher_report_logic import (
    composite_improvement,
    compute_class_summaries,
    format_duration,
    normalized_game_score,
)
```

2) 用下面的实现整体替换 `_load_student_list` 方法（从 `def _load_student_list(self):` 到 `self._top_student_label.setText("暂无数据")` 的整个方法体）：

```python
    def _load_student_list(self):
        user_manager = UserManager()
        students = []

        if user_manager.current_user_role() == UserRole.ADMIN:
            students = user_manager.get_students()
        elif user_manager.current_user_role() == UserRole.TEACHER:
            students = user_manager.get_students_by_teacher(user_manager.current_username())

        records_map = {}
        achievements_map = {}
        session = UserSession()
        for student in students:
            username = student.username
            try:
                records_map[username] = [
                    r.to_dict()
                    for r in session.get_user_training_records(username)
                ]
            except Exception:
                records_map[username] = []
            achievements_map[username] = self._count_achievements(username)

        filter_days = self._date_range_combo.currentData()
        summaries, stats = compute_class_summaries(
            students, records_map,
            filter_days=filter_days,
            achievements_map=achievements_map,
        )
        self._summaries = summaries
        self._student_combo.clear()

        if not summaries:
            self._student_table.setRowCount(0)
            self._detail_table.setRowCount(0)
            self._update_comparison_chart()
            self._class_avg_label.setText("0")
            self._total_trainings_label.setText("0次")
            self._total_hours_label.setText("0分钟")
            self._top_student_label.setText("暂无数据")
            return

        self._student_table.setRowCount(len(summaries))

        for i, summary in enumerate(summaries):
            self._student_combo.addItem(summary['display_name'], summary['name'])
            self._student_table.setItem(i, 0, QTableWidgetItem(summary['display_name']))
            self._student_table.setItem(i, 1, QTableWidgetItem(str(summary['total_trainings'])))
            self._student_table.setItem(i, 2, QTableWidgetItem(format_duration(summary['total_minutes'])))
            self._student_table.setItem(i, 3, QTableWidgetItem(str(summary['avg_attention'])))
            self._student_table.setItem(i, 4, QTableWidgetItem(str(summary['max_attention'])))
            self._student_table.setItem(i, 5, QTableWidgetItem(str(summary['avg_game_score'])))
            self._student_table.setItem(i, 6, QTableWidgetItem(str(summary['achievements'])))

            trend_text = "➡️ 0%"
            if summary['improvement'] > 0:
                trend_text = f"📈 +{int(summary['improvement'])}%"
            elif summary['improvement'] < 0:
                trend_text = f"📉 {int(summary['improvement'])}%"
            trend_item = QTableWidgetItem(trend_text)
            if summary['improvement'] > 0:
                trend_item.setForeground(QColor(76, 175, 80))
            elif summary['improvement'] < 0:
                trend_item.setForeground(QColor(244, 67, 54))
            self._student_table.setItem(i, 7, trend_item)
            self._student_table.setItem(i, 8, QTableWidgetItem(summary['last_training']))

            composite_item = QTableWidgetItem(str(summary['avg_composite']))
            if summary['avg_composite'] >= 80:
                composite_item.setForeground(QColor(76, 175, 80))
            elif summary['avg_composite'] >= 50:
                composite_item.setForeground(QColor(255, 152, 0))
            else:
                composite_item.setForeground(QColor(244, 67, 54))
            self._student_table.setItem(i, 9, composite_item)

        self._class_avg_label.setText(str(stats['class_avg_attention']))
        self._total_trainings_label.setText(f"{stats['total_trainings']}次")
        self._total_hours_label.setText(format_duration(stats['total_minutes']))
        top = stats['top_improvement_student']
        if top:
            self._top_student_label.setText(f"{top['display_name']} (+{int(top['improvement'])}%)")
        else:
            self._top_student_label.setText("暂无数据")
```

3) 把 `_count_achievements` 静态方法加到 `_load_student_list` 之后、`_on_student_combo_changed` 之前：

```python
    @staticmethod
    def _count_achievements(username: str) -> int:
        try:
            import json
            path = os.path.join(
                app_data_dir(), "users", username, "achievements.json"
            )
            if not os.path.exists(path):
                return 0
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return sum(
                1 for a in data.get('achievements', []) if a.get('unlocked', False)
            )
        except Exception:
            return 0
```

4) 三个静态方法改为薄包装（保留原签名，供 `_update_student_detail` 与现有测试使用）：

```python
    @staticmethod
    def _normalized_game_score(record) -> float:
        return normalized_game_score(record)

    @staticmethod
    def _composite_improvement(records) -> float:
        return composite_improvement(records)

    @staticmethod
    def _format_duration(minutes: int) -> str:
        return format_duration(minutes)
```

（若 apply_patch 的 Update 失效，用 PowerShell 精确替换：按上述文本块逐段替换，最后用 `New-Object System.Text.UTF8Encoding($false)` 写回。）

- [ ] **Step 3: 运行回归测试**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_report_logic -v
```

Expected: PASS（3 个原有用例）。

- [ ] **Step 4: 冒烟导入**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -c "import ui.teacher_report_dialog; print('ok')"
```

Expected: `ok`。

- [ ] **Step 5: 提交**

```bash
git add attention_training_py/ui/teacher_report_dialog.py
git commit -m "refactor(teacher): 班级报告窗口改用汇总纯逻辑"
```

---

### Task 3: AI 助教提示词与本地规则回复 `ai/teacher_coach_logic.py`

**Files:**
- Create: `attention_training_py/ai/teacher_coach_logic.py`
- Create: `attention_training_py/tests/test_teacher_coach_logic.py`

**Interfaces:**
- Consumes: Task 1 的 `format_duration`；`summaries`/`stats` 字典结构（键见 Task 1）。
- Produces:
  - `build_teacher_system_prompt(class_context: Optional[str] = None) -> str`
  - `format_class_context(summaries: List[Dict], stats: Dict) -> str`
  - `local_teacher_reply(text: str, class_context: Optional[Dict] = None) -> Tuple[str, str]`
  - `local_teacher_reply_detailed(text: str, class_context: Optional[Dict] = None) -> Tuple[str, str, bool]`

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_teacher_coach_logic.py`：

```python
# -*- coding: utf-8 -*-
"""教师端 AI 助教纯逻辑测试（不依赖 Qt）。"""

import unittest

from ai.teacher_coach_logic import (
    build_teacher_system_prompt,
    format_class_context,
    local_teacher_reply_detailed,
)


def _context():
    summary = {
        "name": "student", "display_name": "小明", "total_trainings": 4,
        "total_minutes": 45, "avg_attention": 72, "max_attention": 85,
        "avg_game_score": 60, "avg_composite": 65, "achievements": 2,
        "improvement": 8.0, "last_training": "08-26 10:30",
    }
    stats = {
        "total_students": 1, "valid_students": 1, "total_trainings": 4,
        "total_minutes": 45, "class_avg_attention": 72,
        "class_avg_composite": 65, "improving": 1, "declining": 0,
        "stable": 0, "best": summary, "worst": summary,
        "top_improvement_student": summary,
    }
    return {"summaries": [summary], "stats": stats}


class TeacherCoachPromptTests(unittest.TestCase):
    def test_system_prompt_contains_persona(self):
        prompt = build_teacher_system_prompt()
        self.assertIn("AI助教", prompt)
        self.assertIn("中文", prompt)
        self.assertIn("直接回答", prompt)

    def test_prompt_includes_class_context(self):
        ctx = _context()
        prompt = build_teacher_system_prompt(
            format_class_context(ctx["summaries"], ctx["stats"])
        )
        self.assertIn("小明", prompt)
        self.assertIn("综合分", prompt)
        self.assertIn("学生明细", prompt)


class TeacherCoachLocalReplyTests(unittest.TestCase):
    def test_class_analysis_returns_report(self):
        reply, kind, needs_cloud = local_teacher_reply_detailed(
            "帮我分析一下班级整体表现", _context()
        )
        self.assertEqual(kind, "report")
        self.assertFalse(needs_cloud)
        self.assertIn("班级训练情况分析", reply)

    def test_student_name_match(self):
        reply, kind, _ = local_teacher_reply_detailed("小明最近怎么样", _context())
        self.assertEqual(kind, "advice")
        self.assertIn("小明", reply)

    def test_risk_query_returns_report(self):
        reply, kind, _ = local_teacher_reply_detailed(
            "哪些学生需要重点关注", _context()
        )
        self.assertEqual(kind, "report")
        self.assertIn("重点关注", reply)

    def test_advice_query(self):
        reply, kind, _ = local_teacher_reply_detailed("给一些教学建议", _context())
        self.assertEqual(kind, "advice")
        self.assertIn("教学建议", reply)

    def test_knowledge_question(self):
        reply, kind, _ = local_teacher_reply_detailed(
            "每周应该训练几次", _context()
        )
        self.assertEqual(kind, "advice")
        self.assertIn("3-4", reply)

    def test_no_data_returns_guidance(self):
        reply, kind, needs_cloud = local_teacher_reply_detailed(
            "帮我分析班级表现", None
        )
        self.assertEqual(kind, "advice")
        self.assertFalse(needs_cloud)
        self.assertIn("还没有", reply)

    def test_fallback_needs_cloud(self):
        reply, kind, needs_cloud = local_teacher_reply_detailed(
            "今天天气怎么样", _context()
        )
        self.assertEqual(kind, "advice")
        self.assertTrue(needs_cloud)
        self.assertIn("还不确定", reply)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_coach_logic -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'ai.teacher_coach_logic'`）。

- [ ] **Step 3: 实现模块** — 新建 `ai/teacher_coach_logic.py`：

```python
# -*- coding: utf-8 -*-
"""教师端 AI 助教纯逻辑（不依赖 Qt，可单测）。

负责：助教人设提示词构建、班级上下文格式化，以及无云端时的本地规则回复。
"""

from typing import Any, Dict, List, Optional, Tuple

from .teacher_report_logic import format_duration

TEACHER_SYSTEM_PROMPT = (
    "你是\"游戏化注意力训练系统\"的班级教学助手（AI助教），服务的对象是班级教师。"
    "你的风格专业、具体、可操作，始终使用中文回复，可适当使用emoji。"
    "你可以基于班级学生的注意力训练数据（训练次数、平均注意力、综合分、进步幅度等）"
    "分析班级整体情况、单个学生表现和需要重点关注的学生，并给出可执行的教学建议。\n"
    "请注意区分教师意图：\n"
    "1. 如果教师只是在问常识性问题（如训练频率、如何帮助注意力差的学生、两种模式的区别等），"
    "直接回答，不要强行输出数据分析；\n"
    "2. 只有教师要求分析班级/学生数据时，才结合班级上下文输出结构化分析。"
)


def format_class_context(
    summaries: List[Dict[str, Any]],
    stats: Dict[str, Any],
) -> str:
    """把学生摘要与班级统计格式化为提示词上下文块。"""
    lines = ["【班级整体情况】"]
    lines.append(
        f"- 学生 {stats.get('total_students', 0)} 人，"
        f"其中有训练记录 {stats.get('valid_students', 0)} 人"
    )
    lines.append(
        f"- 总训练 {stats.get('total_trainings', 0)} 次，"
        f"总时长 {format_duration(stats.get('total_minutes', 0))}"
    )
    lines.append(
        f"- 班级平均注意力 {stats.get('class_avg_attention', 0)}，"
        f"平均综合分 {stats.get('class_avg_composite', 0)}"
    )
    lines.append(
        f"- 进步 {stats.get('improving', 0)} 人，"
        f"退步 {stats.get('declining', 0)} 人，"
        f"稳定 {stats.get('stable', 0)} 人"
    )

    best = stats.get("best")
    worst = stats.get("worst")
    if best:
        lines.append(
            f"- 最佳表现：{best['display_name']}（综合分 {best['avg_composite']}）"
        )
    if worst:
        lines.append(
            f"- 需关注：{worst['display_name']}（综合分 {worst['avg_composite']}）"
        )

    lines.append("【学生明细】")
    for s in summaries:
        lines.append(
            f"- {s['display_name']}：训练{s['total_trainings']}次，"
            f"平均注意力{s['avg_attention']}，综合分{s['avg_composite']}，"
            f"进步{s['improvement']:+.0f}%，最近训练{s['last_training']}"
        )
    return "\n".join(lines)


def build_teacher_system_prompt(class_context: Optional[str] = None) -> str:
    """构建助教 system 提示词：人设 + 班级上下文块（如有）。"""
    sections = [TEACHER_SYSTEM_PROMPT]
    if class_context:
        sections.append(class_context)
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# 本地规则回复
# ---------------------------------------------------------------------------

_CLASS_MARKERS = ("班级", "整体", "全班", "总体", "所有学生", "同学们")
_DATA_MARKERS = (
    "分析", "报告", "总结", "表现", "数据", "情况", "怎么样",
    "点评", "评价", "反馈", "如何",
)
_RISK_MARKERS = (
    "需要关注", "退步", "风险", "落后", "较差", "低分", "下滑", "下降", "薄弱", "担心",
)
_ADVICE_MARKERS = ("建议", "教学", "干预", "怎么帮", "如何提高", "训练计划", "提升", "改善")
_GREETING_MARKERS = ("你好", "您好", "嗨", "哈喽", "hello", "hi", "在吗", "在不在")
_THANKS_MARKERS = ("谢谢", "感谢", "辛苦", "thank")

_KNOWLEDGE_RULES = (
    (
        ("频率", "多久", "一周", "几次", "每天", "安排", "计划", "怎么训练", "训练多少"),
        "建议每周训练 3-4 次，每次 10-15 分钟，循序渐进。规律比单次时长更重要。",
    ),
    (
        ("注意力差", "不集中", "分心", "走神", "专注力", "怎么帮", "帮助"),
        "对注意力较弱的学生：1) 从简单难度开始，先建立成功体验；"
        "2) 固定训练时间形成习惯；3) 训练前做深呼吸、清空杂念；"
        "4) 观察疲劳信号，及时休息。",
    ),
    (
        ("找茬", "追踪", "区别", "哪个", "推荐", "适合"),
        "找茬模式锻炼视觉搜索与持续注意，适合入门；"
        "动态追踪锻炼反应与手眼协调，适合进阶。新手建议先从找茬开始。",
    ),
)


def _wants_class_analysis(text: str) -> bool:
    return any(m in text for m in _CLASS_MARKERS) and any(m in text for m in _DATA_MARKERS)


def _match_student(
    text: str,
    summaries: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    for s in summaries:
        name = s.get("display_name") or ""
        if name and name in text:
            return s
    return None


def _class_report(summaries, stats) -> str:
    total_students = stats.get("total_students", 0)
    total_trainings = stats.get("total_trainings", 0)
    total_minutes = stats.get("total_minutes", 0)
    class_avg = stats.get("class_avg_attention", 0)
    class_composite = stats.get("class_avg_composite", 0)
    improving = stats.get("improving", 0)
    declining = stats.get("declining", 0)
    best = stats.get("best")
    worst = stats.get("worst")

    lines = [
        "🤖 班级训练情况分析：",
        f"📊 学生 {total_students} 人，共训练 {total_trainings} 次，"
        f"总时长 {format_duration(total_minutes)}；",
        f"📈 班级平均注意力 {class_avg} 分，平均综合分 {class_composite} 分；",
        f"✅ 进步学生 {improving} 人，⚠️ 退步学生 {declining} 人，"
        f"稳定 {stats.get('stable', 0)} 人。",
    ]
    if best:
        lines.append(f"🏆 最佳表现：{best['display_name']}（综合分 {best['avg_composite']}）")
    if worst:
        lines.append(f"📌 需关注：{worst['display_name']}（综合分 {worst['avg_composite']}）")

    lines.append("")
    lines.append("💡 教学建议：")
    if class_composite < 50:
        lines.append("• 班级整体水平偏低：建议增加基础训练频率，每周至少 3-4 次、每次 10-15 分钟。")
    elif class_composite < 70:
        lines.append("• 班级整体水平中等：可通过游戏化元素和奖励机制提高参与度。")
    else:
        lines.append("• 班级整体水平优秀：可以尝试更高难度的训练模式，保持挑战性。")
    if total_trainings < total_students * 3:
        lines.append("• 训练频率偏低：建议保证每位学生每周至少完成 3-4 次训练。")
    if declining > total_students // 3:
        lines.append("• 退步学生较多：建议单独了解原因，适当调整训练计划并加强鼓励。")
    return "\n".join(lines)


def _student_reply(student: Dict[str, Any]) -> str:
    composite = student.get("avg_composite", 0)
    imp = student.get("improvement", 0.0)
    lines = [
        f"🤖 {student.get('display_name', '该学生')} 的情况：",
        f"• 训练 {student.get('total_trainings', 0)} 次，"
        f"总时长 {format_duration(student.get('total_minutes', 0))}",
        f"• 平均注意力 {student.get('avg_attention', 0)}，综合分 {composite}",
        f"• 进步幅度 {imp:+.0f}%，最近训练 {student.get('last_training', '无')}",
    ]
    if composite >= 80:
        lines.append("✅ 表现突出，可以尝试更高难度训练保持挑战。")
    elif composite >= 50:
        lines.append("📈 表现良好，建议保持训练频率，重点巩固薄弱环节。")
    else:
        lines.append("⚠️ 综合分偏低，建议增加训练频率并配合教师/家长陪伴练习。")
    if imp < -5:
        lines.append("📉 近期有所退步，建议关注其训练状态和作息，适当降低难度重建信心。")
    elif imp > 5:
        lines.append("🌟 近期进步明显，继续保持！")
    return "\n".join(lines)


def _risk_reply(summaries, stats) -> str:
    flagged = [
        s for s in summaries
        if s.get("total_trainings", 0) > 0
        and (s.get("improvement", 0.0) < -5 or s.get("avg_composite", 0) < 50)
    ]
    if not flagged:
        return "🤖 目前没有发现需要重点关注的学生，班级整体状态良好。"
    lines = ["🤖 以下学生建议重点关注："]
    for s in flagged:
        lines.append(
            f"• {s['display_name']}：综合分 {s.get('avg_composite', 0)}，"
            f"进步 {s.get('improvement', 0.0):+.0f}%，训练 {s.get('total_trainings', 0)} 次"
        )
    lines.append("建议：了解原因（训练频率/作息/兴趣），降低难度重建信心，必要时单独沟通鼓励。")
    return "\n".join(lines)


def _advice_reply(stats) -> str:
    total = stats.get("total_students", 0)
    lines = ["🤖 教学建议："]
    if stats.get("total_trainings", 0) < total * 3:
        lines.append("• 训练频率偏低，建议每周至少 3-4 次、每次 10-15 分钟。")
    if stats.get("declining", 0) > total // 3:
        lines.append("• 退步学生较多，建议分析原因并调整训练计划。")
    if stats.get("class_avg_composite", 0) < 50:
        lines.append("• 班级整体水平偏低，先夯实基础训练。")
    elif stats.get("class_avg_composite", 0) >= 70:
        lines.append("• 班级整体不错，可适度提高难度、保持挑战。")
    lines.append("• 训练贵在坚持，规律比单次时长更重要；关注学生疲劳信号，注意休息。")
    return "\n".join(lines)


def _knowledge_reply(text: str) -> Optional[str]:
    for markers, answer in _KNOWLEDGE_RULES:
        if any(m in text for m in markers):
            return answer
    return None


def _no_data_reply() -> str:
    return (
        "你好！我是班级 AI 助教 🤖\n"
        "我暂时还没有看到你名下学生的训练记录。建议先让学生完成至少一次注意力训练，"
        "之后我就能结合班级数据给出分析和教学建议了。\n"
        "你也可以现在问我，比如：\n"
        "• 每周应该训练几次？\n"
        "• 找茬模式和动态追踪模式有什么区别？\n"
        "• 怎么帮助注意力不集中的学生？"
    )


_FALLBACK_ANSWER = (
    "这个问题我暂时还不太确定怎么回答 🙈 不过我可以帮你：\n"
    "• 分析班级整体情况（比如：\"帮我分析一下班级表现\"）\n"
    "• 查看某个学生（比如：\"小明最近怎么样\"）\n"
    "• 找出需要关注的学生（比如：\"哪些学生需要重点关注\"）\n"
    "• 给出教学建议（比如：\"给一些教学建议\"）"
)


def local_teacher_reply(
    text: str,
    class_context: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    reply, kind, _ = local_teacher_reply_detailed(text, class_context)
    return reply, kind


def local_teacher_reply_detailed(
    text: str,
    class_context: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, bool]:
    """本地规则回复，返回 (reply, kind, needs_cloud)。"""
    text = (text or "").strip()
    summaries = (class_context or {}).get("summaries") or []
    stats = (class_context or {}).get("stats") or {}

    if not summaries or not stats.get("total_students"):
        return _no_data_reply(), "advice", False

    t = text.lower()
    if _wants_class_analysis(t):
        return _class_report(summaries, stats), "report", False
    student = _match_student(t, summaries)
    if student is not None:
        return _student_reply(student), "advice", False
    if any(m in t for m in _RISK_MARKERS):
        return _risk_reply(summaries, stats), "report", False
    if any(m in t for m in _ADVICE_MARKERS):
        return _advice_reply(stats), "advice", False
    kb = _knowledge_reply(t)
    if kb is not None:
        return kb, "advice", False
    if any(m in t for m in _GREETING_MARKERS):
        return (
            "你好！我是班级 AI 助教 🤖 "
            "你可以让我分析班级整体情况、查看某个学生的表现，或给出教学建议。",
            "advice",
            False,
        )
    if any(m in t for m in _THANKS_MARKERS):
        return "不客气～ 需要我帮你分析班级数据，随时告诉我！", "advice", False
    return _FALLBACK_ANSWER, "advice", True
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_coach_logic -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add attention_training_py/ai/teacher_coach_logic.py attention_training_py/tests/test_teacher_coach_logic.py
git commit -m "feat(teacher): 新增AI助教提示词与本地规则回复"
```

---

### Task 4: AI 助教对话服务层 `ai/teacher_coach.py`

**Files:**
- Create: `attention_training_py/ai/teacher_coach.py`
- Create: `attention_training_py/tests/test_teacher_coach.py`

**Interfaces:**
- Consumes: Task 3 的 `build_teacher_system_prompt`、`format_class_context`、`local_teacher_reply_detailed`；`ai/coach_logic.trim_history`、`normalize_chat_completions_url`；`core.database.Database`；`core.settings.GlobalSettings`；`core.user_manager.UserManager/UserRole`。
- Produces:
  - `TeacherCoachWorker(QObject)`：`set_request(username, text, class_context, history, api_key, api_url, model)`、`process_message(...)`、`_call_api(text, class_context, history, api_key, api_url, model) -> str`、`cancel()`；信号 `message_ready(str)`、`message_error(str)`、`local_fallback_ready(str)`、`advice_ready(str)`、`report_ready(str)`、`finished()`。
  - `TeacherCoachManager(QObject)` 单例：`submit_message(username, text, class_context=None, force_cloud=False, save_user_message=True) -> int`、`cancel_request(request_id)`、`cancel_all_requests()`、`load_history(username, limit=50)`、`clear_history(username)`、`shutdown()`、`cleanup()`；信号同学生端（`message_ready(int, str)` 等）；内部 `_build_class_context(username) -> Optional[Dict]`。

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_teacher_coach.py`（镜像 `test_ai_coach_cancel.py` / `test_ai_coach_fallback.py` 风格）：

```python
# -*- coding: utf-8 -*-
"""教师端 AI 助教服务层测试（需要 PySide6；本地 HTTP 服务测试取消行为）。"""

import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from ai.teacher_coach import TeacherCoachManager, TeacherCoachWorker, _RequestCancelled


def _context():
    summary = {
        "name": "student", "display_name": "小明", "total_trainings": 4,
        "total_minutes": 45, "avg_attention": 72, "max_attention": 85,
        "avg_game_score": 60, "avg_composite": 65, "achievements": 2,
        "improvement": 8.0, "last_training": "08-26 10:30",
    }
    stats = {
        "total_students": 1, "valid_students": 1, "total_trainings": 4,
        "total_minutes": 45, "class_avg_attention": 72,
        "class_avg_composite": 65, "improving": 1, "declining": 0,
        "stable": 0, "best": summary, "worst": summary,
        "top_improvement_student": summary,
    }
    return {"summaries": [summary], "stats": stats}


class TeacherCoachManagerTests(unittest.TestCase):
    def test_singleton(self):
        self.assertIs(TeacherCoachManager.instance(), TeacherCoachManager.instance())

    def test_submit_message_rejects_empty(self):
        mgr = TeacherCoachManager.instance()
        self.assertEqual(mgr.submit_message("t", "   "), 0)
        self.assertEqual(mgr.submit_message("", "hi"), 0)


class TeacherCoachWorkerTests(unittest.TestCase):
    def test_local_class_analysis_emits_report(self):
        worker = TeacherCoachWorker()
        ready = []
        report = []
        worker.message_ready.connect(ready.append)
        worker.report_ready.connect(report.append)
        worker.process_message(
            "teacher", "帮我分析一下班级整体表现", _context(), [],
            "", "", "",
        )
        self.assertEqual(len(ready), 1)
        self.assertEqual(len(report), 1)
        self.assertIn("班级训练情况分析", ready[0])

    def test_local_unknown_question_emits_local_fallback(self):
        worker = TeacherCoachWorker()
        fallback = []
        ready = []
        worker.local_fallback_ready.connect(fallback.append)
        worker.message_ready.connect(ready.append)
        worker.process_message(
            "teacher", "今天天气怎么样", _context(), [],
            "", "", "",
        )
        self.assertEqual(len(fallback), 1)
        self.assertEqual(len(ready), 0)
        self.assertIn("还不确定", fallback[0])


class _SlowHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        time.sleep(5)
        body = b'{"choices":[{"message":{"content":"ok"}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TeacherCoachCancellationTests(unittest.TestCase):
    def test_cancel_returns_promptly(self):
        server = HTTPServer(("127.0.0.1", 0), _SlowHandler)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            worker = TeacherCoachWorker()
            result = {}

            def run():
                try:
                    worker._call_api(
                        "你好", None, [],
                        "sk-test", f"http://127.0.0.1:{port}/chat/completions", "test-model",
                    )
                    result["ok"] = True
                except Exception as exc:
                    result["exc"] = exc

            call_thread = threading.Thread(target=run, daemon=True)
            start = time.monotonic()
            call_thread.start()
            time.sleep(0.3)
            worker.cancel()
            call_thread.join(timeout=3)
            elapsed = time.monotonic() - start

            self.assertFalse(call_thread.is_alive(), "取消后 _call_api 应尽快返回")
            self.assertIsInstance(result.get("exc"), _RequestCancelled)
            self.assertLess(elapsed, 2.5, "取消后应快速返回，而不是等待网络超时")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_coach -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'ai.teacher_coach'`）。

- [ ] **Step 3: 实现模块** — 新建 `ai/teacher_coach.py`（镜像 `ai/ai_coach.py` 的线程/队列/取消/落库模式）：

```python
# -*- coding: utf-8 -*-
"""教师端 AI 助教对话服务（以 ai/ 包为底座，镜像 ai/ai_coach.py 模式）。

- TeacherCoachManager：单例，消息队列 + QThread 工作线程，对话历史复用
  coach_messages 表（按教师 username 区分）；
- TeacherCoachWorker：在线程内执行，优先调用 OpenAI 兼容 API（复用
  GlobalSettings 配置），未配置或失败时回退到本地规则分析
  （ai/teacher_coach_logic.local_teacher_reply_detailed）。
"""

from typing import Any, Dict, List, Optional

import requests
import threading
from PySide6.QtCore import QObject, QMutex, QMutexLocker, QThread, QTimer, Signal, Slot

from .coach_logic import normalize_chat_completions_url, trim_history
from .teacher_coach_logic import (
    build_teacher_system_prompt,
    format_class_context,
    local_teacher_reply_detailed,
)
from .teacher_report_logic import (
    MAX_RECORDS_PER_STUDENT,
    MAX_STUDENTS,
    compute_class_summaries,
)
from core.database import Database
from core.settings import GlobalSettings
from core.user_manager import UserManager, UserRole


HISTORY_LIMIT = 20
REQUEST_TIMEOUT = (10, 20)  # (连接超时, 读取超时) 秒


class _RequestCancelled(Exception):
    """请求被用户取消。"""


class TeacherCoachWorker(QObject):
    """在线程中处理一条助教对话消息。"""

    message_ready = Signal(str)
    message_error = Signal(str)
    local_fallback_ready = Signal(str)
    advice_ready = Signal(str)
    report_ready = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False
        self._mutex = QMutex()
        self._finished = False
        self._pending = None

    def set_request(
        self,
        username: str,
        text: str,
        class_context: Optional[Dict[str, Any]],
        history: List[Dict[str, Any]],
        api_key: str,
        api_url: str,
        model: str,
    ):
        self._pending = (
            username, text, class_context, history, api_key, api_url, model,
        )

    @Slot()
    def run_current(self):
        if self._pending is None:
            return
        args, self._pending = self._pending, None
        self.process_message(*args)

    def process_message(
        self,
        username: str,
        text: str,
        class_context: Optional[Dict[str, Any]],
        history: List[Dict[str, Any]],
        api_key: str,
        api_url: str,
        model: str,
    ):
        if self._finished:
            return
        self._cancelled = False
        self._finished = False

        try:
            if api_key:
                reply = self._call_api(text, class_context, history, api_key, api_url, model)
                kind = "advice"
                needs_cloud = False
            else:
                reply, kind, needs_cloud = local_teacher_reply_detailed(text, class_context)

            if self._is_cancelled():
                self.finished.emit()
                self._finished = True
                return

            if needs_cloud:
                self.local_fallback_ready.emit(reply)
            else:
                self.message_ready.emit(reply)
                if kind == "report":
                    self.report_ready.emit(reply)
                else:
                    self.advice_ready.emit(reply)
        except requests.exceptions.Timeout:
            self.message_error.emit("助教回复超时，请检查网络连接后重试。")
        except requests.exceptions.ConnectionError:
            self.message_error.emit("网络连接错误，暂时无法连接 AI 服务。")
        except _RequestCancelled:
            self.message_error.emit("请求已取消。")
        except Exception as exc:
            self.message_error.emit(f"助教回复失败：{exc}")
        finally:
            self.finished.emit()
            self._finished = True

    def _call_api(
        self,
        text: str,
        class_context: Optional[Dict[str, Any]],
        history: List[Dict[str, Any]],
        api_key: str,
        api_url: str,
        model: str,
    ) -> str:
        context_text = ""
        if class_context:
            context_text = format_class_context(
                class_context.get("summaries") or [],
                class_context.get("stats") or {},
            )
        system = build_teacher_system_prompt(context_text or None)
        messages = [{"role": "system", "content": system}]
        messages.extend(trim_history(history, HISTORY_LIMIT))
        messages.append({"role": "user", "content": text})

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        data = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1000,
        }
        api_url = normalize_chat_completions_url(api_url)

        result_box: Dict[str, Any] = {}

        def _post():
            try:
                result_box["response"] = requests.post(
                    api_url, headers=headers, json=data, timeout=REQUEST_TIMEOUT,
                )
            except Exception as exc:
                result_box["exception"] = exc

        post_thread = threading.Thread(target=_post, daemon=True)
        post_thread.start()
        while post_thread.is_alive():
            if self._is_cancelled():
                raise _RequestCancelled("请求已取消")
            post_thread.join(0.2)

        if "exception" in result_box:
            raise result_box["exception"]
        response = result_box["response"]
        if response.status_code != 200:
            error_msg = f"API 错误：{response.status_code}"
            try:
                error_data = response.json()
                if "error" in error_data:
                    error_msg = error_data["error"].get("message", error_msg)
            except Exception:
                pass
            raise RuntimeError(error_msg)

        try:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError(f"API 响应格式错误：{exc}") from exc

    def _is_cancelled(self) -> bool:
        locker = QMutexLocker(self._mutex)
        return self._cancelled

    def cancel(self):
        locker = QMutexLocker(self._mutex)
        self._cancelled = True


class TeacherCoachManager(QObject):
    """AI 助教对话管理单例：队列 + 单工作线程，历史持久化。"""

    message_ready = Signal(int, str)
    message_error = Signal(int, str)
    local_fallback_ready = Signal(int, str)
    advice_ready = Signal(str)
    report_ready = Signal(str)
    error_occurred = Signal(str)
    request_finished = Signal(int)

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        super().__init__()
        self._initialized = True

        self._next_request_id = 1
        self._shutting_down = False
        self._active_worker = None
        self._active_thread = None
        self._current_request_id = 0
        self._request_queue = []
        self._request_usernames = {}
        self._mutex = QMutex()
        self._active_workers = []

    @classmethod
    def instance(cls):
        return cls()

    def submit_message(
        self,
        username: str,
        text: str,
        class_context: Optional[Dict[str, Any]] = None,
        force_cloud: bool = False,
        save_user_message: bool = True,
    ) -> int:
        """提交一条用户消息，返回请求 ID；0 表示未受理。"""
        if self._shutting_down:
            return 0
        if not username or not text or not text.strip():
            return 0
        if force_cloud:
            try:
                if not GlobalSettings().api_key():
                    return 0
            except Exception:
                return 0

        text = text.strip()
        history = self._fetch_history(username)
        if class_context is None:
            class_context = self._build_class_context(username)

        if save_user_message:
            try:
                Database().add_coach_message(username, "user", text)
            except Exception as exc:
                print(f"TeacherCoachManager: 保存用户消息失败: {exc}")

        request_id = self._next_request_id
        self._next_request_id += 1

        request = {
            "request_id": request_id,
            "username": username,
            "text": text,
            "class_context": class_context,
            "history": history,
            "api_key": "",
            "api_url": "",
            "model": "",
            "force_cloud": force_cloud,
        }

        locker = QMutexLocker(self._mutex)
        self._request_queue.append(request)
        self._request_usernames[request_id] = username
        locker.unlock()

        QTimer.singleShot(10, self._process_queue)
        return request_id

    def cancel_request(self, request_id: int):
        locker = QMutexLocker(self._mutex)
        self._request_queue = [
            r for r in self._request_queue if r["request_id"] != request_id
        ]
        locker.unlock()

        if self._current_request_id == request_id and self._active_worker:
            self._active_worker.cancel()

    def cancel_all_requests(self):
        locker = QMutexLocker(self._mutex)
        self._request_queue.clear()
        locker.unlock()

        for thread, worker in self._active_workers:
            if worker:
                worker.cancel()
                worker.disconnect(self)

        self._cleanup_worker()

    def load_history(self, username: str, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            return Database().fetch_coach_messages(username, limit=limit)
        except Exception as exc:
            print(f"TeacherCoachManager: 加载历史失败: {exc}")
            return []

    def clear_history(self, username: str) -> None:
        try:
            Database().clear_coach_messages(username)
        except Exception as exc:
            print(f"TeacherCoachManager: 清空历史失败: {exc}")

    def shutdown(self):
        self._shutting_down = True
        self.cancel_all_requests()

    def cleanup(self):
        """应用退出时清理。"""
        print("TeacherCoachManager: Starting cleanup...")
        for thread, worker in self._active_workers:
            if worker:
                try:
                    worker.cancel()
                    worker.disconnect(self)
                except Exception as exc:
                    print(f"TeacherCoachManager: cleanup worker error: {exc}")
        self._active_workers.clear()

        locker = QMutexLocker(self._mutex)
        self._request_queue.clear()
        self._request_usernames.clear()
        locker.unlock()

        self._cleanup_worker()
        self._shutting_down = True
        self._current_request_id = 0
        self._next_request_id = 1
        print("TeacherCoachManager: Cleanup completed")

    def _build_class_context(self, username: str) -> Optional[Dict[str, Any]]:
        """按当前角色汇总班级数据：TEACHER 看自己的学生，ADMIN 看全部。"""
        try:
            user_manager = UserManager()
            role = user_manager.current_user_role()
            if role == UserRole.ADMIN:
                students = user_manager.get_students()
            elif role == UserRole.TEACHER:
                students = user_manager.get_students_by_teacher(username)
            else:
                return None
            students = (students or [])[:MAX_STUDENTS]
            if not students:
                return None
            records_map: Dict[str, List[Dict[str, Any]]] = {}
            for student in students:
                sname = getattr(student, "username", "")
                try:
                    records_map[sname] = (
                        Database().fetch_training_records(sname)
                        [:MAX_RECORDS_PER_STUDENT]
                    )
                except Exception:
                    records_map[sname] = []
            summaries, stats = compute_class_summaries(students, records_map)
            if not summaries:
                return None
            return {"summaries": summaries, "stats": stats}
        except Exception as exc:
            print(f"TeacherCoachManager: 构建班级上下文失败: {exc}")
            return None

    def _fetch_history(
        self,
        username: str,
        max_turns: int = HISTORY_LIMIT,
    ) -> List[Dict[str, Any]]:
        try:
            rows = Database().fetch_coach_messages(username, limit=max_turns * 2)
            return [
                {"role": row["role"], "content": row["content"]}
                for row in rows
                if row["role"] in ("user", "assistant")
            ]
        except Exception as exc:
            print(f"TeacherCoachManager: 获取对话历史失败: {exc}")
            return []

    def _resolve_config(self, request: Dict[str, Any]):
        settings = GlobalSettings()
        key = settings.api_key()
        if key and (settings.ai_enabled() or request.get("force_cloud")):
            request["api_key"] = key
            request["api_url"] = settings.api_url()
            request["model"] = settings.ai_model()

    @Slot()
    def _process_queue(self):
        if self._shutting_down:
            return
        if self._active_worker and self._active_thread and self._active_thread.isRunning():
            return

        self._cleanup_worker()

        locker = QMutexLocker(self._mutex)
        if not self._request_queue:
            return
        request = self._request_queue.pop(0)
        self._current_request_id = request["request_id"]
        locker.unlock()

        self._resolve_config(request)

        self._active_thread = QThread()
        self._active_worker = TeacherCoachWorker()
        self._active_worker.moveToThread(self._active_thread)

        self._active_worker.set_request(
            request["username"],
            request["text"],
            request["class_context"],
            request["history"],
            request["api_key"],
            request["api_url"],
            request["model"],
        )
        self._active_thread.started.connect(self._active_worker.run_current)

        self._active_worker.message_ready.connect(self._on_worker_ready)
        self._active_worker.message_error.connect(self._on_worker_error)
        self._active_worker.local_fallback_ready.connect(self._on_worker_local_fallback)
        self._active_worker.finished.connect(self._on_worker_finished)
        self._active_worker.advice_ready.connect(self.advice_ready)
        self._active_worker.report_ready.connect(self.report_ready)

        self._active_thread.finished.connect(self._on_thread_finished)

        locker = QMutexLocker(self._mutex)
        self._active_workers.append((self._active_thread, self._active_worker))
        locker.unlock()

        self._active_thread.start()

    def _on_worker_ready(self, content: str):
        self._persist_assistant_reply(content)
        self.message_ready.emit(self._current_request_id, content)

    def _on_worker_local_fallback(self, content: str):
        self._persist_assistant_reply(content)
        self.local_fallback_ready.emit(self._current_request_id, content)

    def _persist_assistant_reply(self, content: str):
        username = self._request_usernames.get(self._current_request_id)
        if username:
            try:
                Database().add_coach_message(username, "assistant", content)
            except Exception as exc:
                print(f"TeacherCoachManager: 保存助教回复失败: {exc}")

    def _on_worker_error(self, error: str):
        self.message_error.emit(self._current_request_id, error)
        self.error_occurred.emit(error)

    def _on_worker_finished(self):
        self.request_finished.emit(self._current_request_id)
        if self._active_thread and self._active_thread.isRunning():
            self._active_thread.quit()

    def _on_thread_finished(self):
        if self._active_thread:
            locker = QMutexLocker(self._mutex)
            for i, (thread, worker) in enumerate(self._active_workers):
                if thread == self._active_thread:
                    self._active_workers.pop(i)
                    break
            locker.unlock()
        if self._active_worker:
            self._active_worker.deleteLater()
            self._active_worker = None
        self._active_thread = None
        self._current_request_id = 0
        QTimer.singleShot(10, self._process_queue)

    def _cleanup_worker(self):
        """安全清理：线程仍在运行时不清除，交由 _on_thread_finished。"""
        if self._active_thread and self._active_thread.isRunning():
            return

        if self._active_thread:
            self._active_thread = None
        if self._active_worker:
            self._active_worker.deleteLater()
            self._active_worker = None
        self._current_request_id = 0
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_coach -v
```

Expected: 全部 PASS（含取消测试，约 2-3 秒）。

- [ ] **Step 5: 提交**

```bash
git add attention_training_py/ai/teacher_coach.py attention_training_py/tests/test_teacher_coach.py
git commit -m "feat(teacher): 新增AI助教对话服务层"
```

---

### Task 5: AI 助教对话窗口 `ui/teacher_coach_dialog.py`

**Files:**
- Create: `attention_training_py/ui/teacher_coach_dialog.py`
- Create: `attention_training_py/tests/test_teacher_coach_smoke.py`

**Interfaces:**
- Consumes: Task 4 的 `TeacherCoachManager`；`core.user_manager.UserManager`；`core.settings.GlobalSettings`。
- Produces: `TeacherCoachDialog(QDialog)`，构造参数 `parent=None, class_context: Optional[Dict] = None`。

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_teacher_coach_smoke.py`（导入冒烟，需 offscreen）：

```python
# -*- coding: utf-8 -*-
"""教师端 AI 助教模块导入冒烟测试（需 QT_QPA_PLATFORM=offscreen）。"""

import unittest


class TeacherCoachImportSmokeTests(unittest.TestCase):
    def test_imports_ok(self):
        import ai.teacher_coach
        import ai.teacher_coach_logic
        import ai.teacher_report_logic
        import ui.teacher_coach_dialog
        self.assertTrue(ai.teacher_coach.TeacherCoachManager)
        self.assertTrue(ui.teacher_coach_dialog.TeacherCoachDialog)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_coach_smoke -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'ui.teacher_coach_dialog'`）。

- [ ] **Step 3: 实现对话框** — 新建 `ui/teacher_coach_dialog.py`（镜像 `ui/ai_coach_dialog.py`）：

```python
# -*- coding: utf-8 -*-
"""教师端 AI 助教对话对话框（镜像 ui/ai_coach_dialog.py）。"""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ai.teacher_coach import TeacherCoachManager
from core.settings import GlobalSettings
from core.user_manager import UserManager


class TeacherCoachDialog(QDialog):
    """与班级 AI 助教多轮对话的聊天窗口。

    class_context：从班级报告窗口跳转时携带的班级汇总（summaries + stats），
    首次消息自动带上并发送一条咨询。
    """

    def __init__(
        self,
        parent=None,
        class_context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent)
        self._class_context = class_context or None
        self._pending_request_id = 0
        self._last_question = ""

        self.setWindowTitle("🤖 AI助教")
        self.setMinimumSize(560, 640)
        self.resize(620, 720)

        self._setup_ui()
        self._apply_style_sheet()

        self._manager = TeacherCoachManager.instance()
        self._connect_signals()
        self._load_history()

        if self._class_context and UserManager().is_logged_in():
            self._auto_ask()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("🤖 AI助教 · 班级数据分析助手")
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("coachTitle")
        layout.addWidget(title)

        self._chat_view = QTextEdit()
        self._chat_view.setReadOnly(True)
        layout.addWidget(self._chat_view, 1)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._status_label)

        input_row = QHBoxLayout()
        self._input_edit = QLineEdit()
        self._input_edit.setPlaceholderText("输入你想咨询助教的问题，回车发送")
        self._send_btn = QPushButton("发送")
        input_row.addWidget(self._input_edit, 1)
        input_row.addWidget(self._send_btn)
        layout.addLayout(input_row)

        bottom_row = QHBoxLayout()
        self._cancel_btn = QPushButton("取消请求")
        self._cancel_btn.setEnabled(False)
        self._clear_btn = QPushButton("清空对话")
        bottom_row.addWidget(self._cancel_btn)
        bottom_row.addStretch()
        bottom_row.addWidget(self._clear_btn)
        layout.addLayout(bottom_row)

        self._input_edit.returnPressed.connect(self._on_send_clicked)
        self._send_btn.clicked.connect(self._on_send_clicked)
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)

    def _apply_style_sheet(self):
        settings = GlobalSettings()
        text_color = settings.text_color().name()
        night = settings.night_mode()
        bg = "#2d2d2d" if night else "#f5f5f5"
        chat_bg = "#3a3a3a" if night else "#ffffff"
        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text_color}; }}
            QLabel#coachTitle {{ font-size: 22px; font-weight: bold; padding: 8px; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 6px; padding: 8px 18px; font-size: 14px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QPushButton:disabled {{ background-color: #9e9e9e; }}
            QTextEdit {{ background-color: {chat_bg}; color: {text_color};
                border: 2px solid #4CAF50; border-radius: 8px;
                font-size: 14px; padding: 10px; }}
            QLineEdit {{ background-color: {chat_bg}; color: {text_color};
                border: 2px solid #4CAF50; border-radius: 6px;
                font-size: 14px; padding: 8px; }}
        """)

    def _connect_signals(self):
        self._manager.message_ready.connect(self._on_message_ready)
        self._manager.message_error.connect(self._on_message_error)
        self._manager.local_fallback_ready.connect(self._on_local_fallback_ready)

    def _disconnect_signals(self):
        try:
            self._manager.message_ready.disconnect(self._on_message_ready)
            self._manager.message_error.disconnect(self._on_message_error)
            self._manager.local_fallback_ready.disconnect(self._on_local_fallback_ready)
        except Exception:
            pass

    def _load_history(self):
        username = UserManager().current_username()
        if not username:
            return
        for row in self._manager.load_history(username, limit=100):
            self._append_chat(row["role"], row["content"])

    def _auto_ask(self):
        self._append_chat("system", "📊 已携带班级数据，助教会结合数据回答。")
        self._send_message("请结合班级数据，分析整体情况并给出教学建议。")

    def _on_send_clicked(self):
        text = self._input_edit.text().strip()
        if not text:
            return
        self._input_edit.clear()
        self._send_message(text)

    def _send_message(self, text: str):
        username = UserManager().current_username()
        if not username:
            QMessageBox.warning(self, "未登录", "请先登录后再与助教对话。")
            return
        if self._pending_request_id:
            return

        self._last_question = text
        request_id = self._manager.submit_message(
            username,
            text,
            class_context=self._class_context,
        )
        if not request_id:
            QMessageBox.warning(self, "提示", "当前无法发送，请稍后再试。")
            return

        self._pending_request_id = request_id
        self._class_context = None  # 上下文只在首次消息使用
        self._append_chat("user", text)
        self._set_busy(True)

    def _on_clear_clicked(self):
        username = UserManager().current_username()
        if not username:
            return
        ret = QMessageBox.question(
            self,
            "清空对话",
            "确定要清空与 AI 助教的全部对话记录吗？",
        )
        if ret == QMessageBox.Yes:
            self._manager.clear_history(username)
            self._chat_view.clear()

    def _on_cancel_clicked(self):
        if not self._pending_request_id:
            return
        request_id = self._pending_request_id
        self._pending_request_id = 0
        self._manager.cancel_request(request_id)
        self._set_busy(False)
        self._append_chat("system", "已取消本次请求。")

    def _set_busy(self, busy: bool):
        self._send_btn.setEnabled(not busy)
        self._input_edit.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)
        self._status_label.setText("助教正在思考…" if busy else "")

    def _append_chat(self, role: str, text: str):
        text = str(text).strip()
        if not text:
            return
        if role == "user":
            block = f"你：\n{text}"
        elif role == "assistant":
            block = f"🤖 助教：\n{text}"
        else:
            block = text
        self._chat_view.append(block)
        self._chat_view.append("")

    def _on_message_ready(self, request_id: int, content: str):
        if request_id != self._pending_request_id:
            return
        self._pending_request_id = 0
        self._append_chat("assistant", content)
        self._set_busy(False)

    def _on_message_error(self, request_id: int, error: str):
        if request_id != self._pending_request_id:
            return
        self._pending_request_id = 0
        self._set_busy(False)
        self._append_chat("system", f"⚠️ {error}")

    def _on_local_fallback_ready(self, request_id: int, content: str):
        if request_id != self._pending_request_id:
            return
        self._pending_request_id = 0
        self._set_busy(False)
        self._append_chat("assistant", content)

        ret = QMessageBox.question(
            self,
            "AI助教",
            "这个问题还在学习中，是否使用云端大语言模型来回答？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self._send_cloud_fallback()

    def _send_cloud_fallback(self):
        username = UserManager().current_username()
        if not username or not self._last_question:
            return
        request_id = self._manager.submit_message(
            username,
            self._last_question,
            force_cloud=True,
            save_user_message=False,
        )
        if not request_id:
            QMessageBox.information(
                self,
                "提示",
                "尚未配置云端大语言模型。请到「设置 → AI智能助手」勾选"
                "「启用AI智能分析」并填写 API 密钥后重试。",
            )
            return
        self._pending_request_id = request_id
        self._set_busy(True)

    def closeEvent(self, event):
        if self._pending_request_id:
            self._manager.cancel_request(self._pending_request_id)
            self._pending_request_id = 0
        self._disconnect_signals()
        super().closeEvent(event)
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_coach_smoke -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add attention_training_py/ui/teacher_coach_dialog.py attention_training_py/tests/test_teacher_coach_smoke.py
git commit -m "feat(teacher): 新增AI助教对话窗口"
```

---

### Task 6: 入口接线、退出清理与打包清单

**Files:**
- Modify: `attention_training_py/ui/main_window.py`
- Modify: `attention_training_py/ui/teacher_report_dialog.py`
- Modify: `attention_training_py/main.py`
- Modify: `attention_training_py/pyproject.toml`
- Modify: `attention_training_py/AttentionTrainingApp.spec`
- Test: `attention_training_py/tests/test_teacher_coach_smoke.py`（追加 `ui.main_window` 导入）

**Interfaces:**
- Consumes: Task 5 的 `TeacherCoachDialog`；Task 1 的 `compute_class_stats`。
- Produces: 主窗口 `_on_teacher_coach()` 处理器；班级报告窗口 `_on_ask_coach()` 处理器与"🤖 咨询AI助教"按钮。

- [ ] **Step 1: 写失败测试** — 在 `tests/test_teacher_coach_smoke.py` 的 `test_imports_ok` 中追加：

```python
        import ui.main_window
        import ui.teacher_report_dialog
```

（`ui.main_window` 目前未导入 `TeacherCoachDialog`，但 import 不会失败；本测试的实际价值在 Step 3 完成后验证接线不破坏导入链。）

- [ ] **Step 2: 运行测试确认当前通过**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_coach_smoke -v
```

Expected: PASS（接线前导入链已可工作）。

- [ ] **Step 3: 接线**

1) `ui/main_window.py`：
- import 区在 `from ui.ai_coach_dialog import AICoachDialog` 后新增：
```python
from ui.teacher_coach_dialog import TeacherCoachDialog
```
- `_add_role_specific_buttons` 中 `if role in (UserRole.TEACHER, UserRole.ADMIN):` 块内、`self._role_specific_buttons.append(teacher_btn)` 之后追加：
```python
            coach_btn = QPushButton("🤖 AI助教")
            coach_btn.setFixedSize(btn_width, btn_height - 5)
            coach_btn.setStyleSheet(btn_style + "background-color: #9C27B0;")
            coach_btn.clicked.connect(self._on_teacher_coach)

            h_layout = QHBoxLayout()
            h_layout.addStretch()
            h_layout.addWidget(coach_btn)
            h_layout.addStretch()

            self._main_layout.addLayout(h_layout)
            self._role_specific_buttons.append(coach_btn)
```
- 在 `_on_teacher_report` 方法后新增处理器：
```python
    def _on_teacher_coach(self):
        """AI助教对话"""
        try:
            dlg = TeacherCoachDialog(self)
            dlg.exec()
        except Exception as e:
            print(f"On teacher coach error: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"无法打开AI助教:\n{str(e)}")
```

2) `ui/teacher_report_dialog.py`：
- import 区 `from ai.teacher_report_logic import (...)` 列表中加入 `compute_class_stats`；新增 `from ui.teacher_coach_dialog import TeacherCoachDialog`。
- `_setup_ui` 控制栏中，在 `self._class_report_btn` 创建之后、`control_layout.addWidget(self._class_report_btn)` 之前追加：
```python
        self._coach_btn = QPushButton("🤖 咨询AI助教")
        self._coach_btn.setFixedSize(140, 38)
        self._coach_btn.clicked.connect(self._on_ask_coach)
```
  并在控制栏布局中加入：`control_layout.addWidget(self._coach_btn)`（放在 `addWidget(self._class_report_btn)` 之后）。
- 新增处理器：
```python
    def _on_ask_coach(self):
        """携带当前班级汇总打开 AI 助教。"""
        if not self._summaries:
            QMessageBox.information(self, "提示", "暂无学生数据，无法咨询助教。")
            return
        stats = compute_class_stats(self._summaries)
        dlg = TeacherCoachDialog(
            self,
            class_context={"summaries": self._summaries, "stats": stats},
        )
        dlg.exec()
```

3) `main.py` 的 `cleanup_resources()` 中，在 `AICoachManager.instance().cleanup()` 的 try 块之后追加：
```python
    try:
        from ai.teacher_coach import TeacherCoachManager
        TeacherCoachManager.instance().cleanup()
    except Exception as e:
        print(f"Cleanup teacher coach manager error: {e}")
```

注意：`main.py` 当前已含未提交改动（学生端 AI 教练的清理代码）。本任务的提交会连同这些既有改动一起进入 `main.py` 的 diff；如不希望混入，把 `main.py` 留到用户自行提交（其余文件仍按本任务提交）。

4) `pyproject.toml` `files` 列表：
- 在 `"ai/local_analysis.py"` 后插入 `"ai/teacher_coach.py", "ai/teacher_coach_logic.py", "ai/teacher_report_logic.py"`；
- 在 `"ui/ai_coach_dialog.py"` 后插入 `"ui/teacher_coach_dialog.py"`。

5) `AttentionTrainingApp.spec` `hiddenimports` 列表：
- 在 `'ai.local_analysis'` 后插入 `'ai.teacher_coach', 'ai.teacher_coach_logic', 'ai.teacher_report_logic'`；
- 在 `'ui.ai_coach_dialog'` 后插入 `'ui.teacher_coach_dialog'`。

`dynamic_build.py` 无需改动（自动收集）。

- [ ] **Step 4: 运行测试**

```powershell
cd D:\code\AttentionTrainingPacks\AttentionTraining_v3.0\attention_training_py
$env:QT_QPA_PLATFORM='offscreen'
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_coach_smoke -v
```

Expected: PASS。随后跑全部相关回归：

```powershell
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest tests.test_teacher_report_logic tests.test_teacher_coach_logic tests.test_teacher_coach tests.test_teacher_coach_smoke tests.test_coach_logic tests.test_coach_db -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 全量测试（可选基线）**

```powershell
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\python.exe" -m unittest discover -s tests -v
```

Expected: 若出现与本功能无关的既有失败，记录并汇报，不擅自修复。

- [ ] **Step 6: 提交**

```bash
git add attention_training_py/ui/main_window.py attention_training_py/ui/teacher_report_dialog.py attention_training_py/pyproject.toml attention_training_py/AttentionTrainingApp.spec attention_training_py/tests/test_teacher_coach_smoke.py
git commit -m "feat(teacher): 接入AI助教入口并更新打包清单"
git add attention_training_py/main.py
git commit -m "chore(main): 退出清理接入AI助教"
```

---

## Self-Review 记录

**Spec 覆盖：** 每个规格要点都有对应任务——班级汇总抽取（Task 1-2）、提示词/本地回复（Task 3）、服务层（Task 4）、聊天窗（Task 5）、两处入口 + 清理 + 打包（Task 6）、测试（各任务内建）、无新表/无新模型（Global Constraints）、上下文上限（Task 1/4）。

**占位符检查：** 无 TBD/TODO；所有代码步骤都含完整实现。

**类型一致性：** `compute_class_summaries -> (summaries, stats)`、`class_context = {"summaries": [...], "stats": {...}}` 在 Task 1/3/4/5/6 中一致；`TeacherCoachWorker.process_message` 参数顺序在 Task 4 的测试与实现中一致；`_call_api(text, class_context, history, api_key, api_url, model)` 在实现与取消测试中一致。
