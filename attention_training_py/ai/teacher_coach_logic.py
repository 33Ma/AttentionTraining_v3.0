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
    "需要关注", "重点关注", "退步", "风险", "落后", "较差", "低分", "下滑", "下降", "薄弱", "担心",
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
    "这个问题我暂时还不确定怎么回答 🙈 不过我可以帮你：\n"
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
