# -*- coding: utf-8 -*-
"""AI 教练对话纯逻辑（不依赖 Qt，便于单元测试）。

负责：教练人设/上下文提示词构建、多轮历史裁剪、以及无 API 时的本地回复
（优先本地 ONNX 分析，模型不可用回退规则模板）。
"""

from typing import Any, Dict, List, Optional, Tuple


MODE_NAMES = {
    "find_difference": "找茬模式",
    "dynamic_tracking": "动态追踪模式",
}

SYSTEM_PROMPT = (
    "你是\"游戏化注意力训练系统\"的AI教练。你的风格温暖、鼓励、专业，"
    "善于发现用户的进步并给出建设性建议。请始终使用中文回复，"
    "适当使用emoji，语气像朋友一样亲切。回答要具体、可操作，"
    "可以引用用户的训练数据来解释你的建议。\n"
    "请注意区分用户意图：\n"
    "1. 如果用户只是寒暄或询问常见问题（如如何提高注意力、两种模式的区别与选择、"
    "训练频率与休息建议等），请直接回答用户的问题，不要强行输出数据分析；\n"
    "2. 只有当用户要求点评/分析训练表现时，才结合训练数据输出结构化分析。"
)


def _mode_name(game_mode: str) -> str:
    return MODE_NAMES.get(game_mode, game_mode or "未知模式")


def format_training_summary(record: Dict[str, Any]) -> str:
    """把一条训练记录格式化为一行摘要。"""
    date = record.get("date_time") or record.get("date") or "未知时间"
    attention = record.get("avg_attention_score", record.get("avg_attention", 0))
    mode = _mode_name(record.get("game_mode", ""))
    return (
        f"时间：{date}，模式：{mode}，注意力：{attention}/100，"
        f"得分：{record.get('game_score', 0)}，"
        f"时长：{record.get('duration_minutes', 0)}分钟"
    )


def format_session_context(context: Dict[str, Any]) -> str:
    """把本次训练数据格式化为提示词中的上下文块。"""
    parts = [
        f"注意力 {context.get('avg_attention', 0)}/100",
        f"眨眼 {context.get('total_blinks', 0)} 次",
        f"最高连击 {context.get('max_consecutive_hits', 0)} 次",
        f"得分 {context.get('game_score', 0)}",
        f"模式 {_mode_name(context.get('game_mode', ''))}",
        f"时长 {context.get('duration_minutes', 0)} 分钟",
    ]
    if context.get("avg_gaze_score") is not None:
        parts.append(f"注视专注度 {context.get('avg_gaze_score')}/100")
    if context.get("avg_gaze_distance") is not None:
        parts.append(f"注视距离 {context.get('avg_gaze_distance'):.3f}")
    return "，".join(parts)


def build_system_prompt(
    session_context: Optional[Dict[str, Any]] = None,
    recent_records: Optional[List[Dict[str, Any]]] = None,
    max_records: int = 5,
) -> str:
    """构建教练的系统提示词：人设 + 本次训练数据 + 最近训练记录。"""
    sections = [SYSTEM_PROMPT]

    if session_context:
        sections.append(
            "【用户本次训练数据】\n" + format_session_context(session_context)
        )

    records = (recent_records or [])[-max_records:]
    if records:
        lines = [format_training_summary(r) for r in records]
        sections.append("【用户最近训练记录】\n" + "\n".join(f"- {line}" for line in lines))

    return "\n\n".join(sections)


def trim_history(
    messages: List[Dict[str, Any]],
    max_turns: int = 20,
) -> List[Dict[str, Any]]:
    """保留最近 max_turns 轮对话（每轮 = 用户+助手两条）。"""
    limit = max(1, int(max_turns)) * 2
    if len(messages) <= limit:
        return list(messages)
    return messages[-limit:]


def normalize_chat_completions_url(url: str) -> str:
    """把用户填写的 API 地址规范化为完整的 /chat/completions 端点。

    兼容常见写法：
    - 完整地址 https://host/v1/chat/completions（原样保留）
    - 根地址 https://host（补 /chat/completions）
    - 版本前缀 https://host/v1（补 /chat/completions）
    """
    text = (url or "").strip()
    if not text:
        return text
    if not (text.startswith("http://") or text.startswith("https://")):
        return text
    base = text.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if base.endswith("/v1/chat"):
        return base + "/completions"
    return base + "/chat/completions"


def _no_data_reply() -> str:
    return (
        "你好！我是你的AI教练 🤖\n"
        "我暂时还没有看到你的训练记录。建议你先完成一次注意力训练，"
        "之后我就能结合你的数据给出更具体的建议了。\n"
        "如果你想现在聊聊训练方法，也可以直接问我：\n"
        "• 训练前应该做哪些准备？\n"
        "• 怎么提高注意力分数？\n"
        "• 选找茬模式还是动态追踪模式？"
    )


_ANALYSIS_MARKERS = ("分析", "点评", "评价", "反馈", "总结", "报告")
_ANALYSIS_DATA_MARKERS = ("训练", "数据", "成绩", "表现", "这次", "刚才", "本次", "我的")
_MODE_MARKERS = ("找茬", "动态追踪", "模式")
_MODE_QUESTION_MARKERS = ("区别", "不同", "哪个", "推荐", "适合", "选择", "新手", "进阶", "开始", "怎么玩", "第一次")
_IMPROVE_MARKERS = (
    "提高注意力", "提升注意力", "注意力怎么", "注意力下降", "注意力不集中",
    "注意力不好", "注意力差", "注意力低", "注意力分数低", "容易分心", "走神", "专注力",
)
_SCHEDULE_MARKERS = ("多久", "频率", "一周", "几次", "每天", "安排", "计划", "什么时候", "训练多久", "怎么练", "怎么训练")
_FATIGUE_MARKERS = ("累", "疲劳", "休息", "眼睛", "眼干", "酸", "放松", "眨眼")
_PREP_MARKERS = ("准备", "注意事项", "训练前", "第一次", "刚开始", "新手")
_WHAT_MARKERS = ("是什么", "有什么用", "有什么好处", "好处", "作用", "这个软件", "这个系统", "注意力训练")
_GREETING_MARKERS = ("你好", "您好", "嗨", "哈喽", "hello", "hi", "早上好", "中午好", "下午好", "晚上好", "在吗", "在不在", "hey")
_THANKS_MARKERS = ("谢谢", "感谢", "thank", "辛苦")

_GREETING_ANSWER = (
    "你好呀！👋 我是你的AI教练，很高兴见到你～\n"
    "你可以问我关于注意力训练的任何问题，比如：\n"
    "• 怎么提高注意力分数\n"
    "• 找茬模式和动态追踪模式怎么选\n"
    "• 训练频率和休息建议\n"
    "• 点评我的训练数据\n"
    "今天想聊点什么？"
)

_THANKS_ANSWER = (
    "不客气～😊 能帮到你我很开心！坚持规律训练，你一定会越来越棒。有任何问题随时来找我！"
)

_IMPROVE_ANSWER = (
    "想提高注意力，可以从这几件事做起：\n"
    "1️⃣ 保持规律训练：每周3-4次，每次10-15分钟，让大脑形成习惯；\n"
    "2️⃣ 训练前做5分钟深呼吸，清空杂念；\n"
    "3️⃣ 尽量在安静、光线舒适的环境里训练，坐姿端正，视线保持在屏幕中央；\n"
    "4️⃣ 训练后看看教练的数据分析，找到自己的薄弱项（比如视线偏移或走神时段）。\n"
    "坚持两周左右，你会看到注意力分数稳步上升的！"
)

_MODE_ANSWER = (
    "两种模式各有侧重：\n"
    "🔍 找茬模式：在右侧区域快速扫描并点击隐藏的差异点，锻炼视觉搜索和持续注意力，适合新手入门；\n"
    "🎯 动态追踪模式：用鼠标追踪不断移动的目标，锻炼反应速度和手眼协调，适合进阶练习。\n"
    "建议新手先从找茬模式开始，熟悉之后再挑战动态追踪。想让我根据你的训练记录推荐，也可以告诉我～"
)

_SCHEDULE_ANSWER = (
    "建议每周训练3-4次，每次10-15分钟，循序渐进。\n"
    "训练贵在坚持，规律比单次时长更重要。如果已经适应某个模式，可以适当提高难度，或挑战动态追踪模式。"
)

_FATIGUE_ANSWER = (
    "感觉疲劳是很正常的信号，说明该休息啦～😴\n"
    "1️⃣ 训练间隙闭眼休息1-2分钟，或远眺放松；\n"
    "2️⃣ 用眼后可以做做眼保健操，多眨眼保持湿润；\n"
    "3️⃣ 训练频率保持每周3-4次，给眼睛和大脑留出恢复时间；\n"
    "4️⃣ 如果连续几次注意力分数偏低，先休息好再训练，效果会更好。"
)

_PREP_ANSWER = (
    "开始训练前可以这样做：\n"
    "1️⃣ 找一个安静、光线适宜的环境；\n"
    "2️⃣ 调整坐姿正对屏幕，眼睛与屏幕保持合适距离；\n"
    "3️⃣ 做几次深呼吸，让自己平静下来；\n"
    "4️⃣ 第一次可以从找茬模式开始，熟悉操作后再尝试动态追踪。\n"
    "准备好了就去试试吧！"
)

_WHAT_ANSWER = (
    "这个系统通过找茬和动态追踪两种游戏化模式，配合摄像头实时监测你的眨眼频率和视线专注度，"
    "帮你训练和提升注意力。\n"
    "每次训练后AI教练会结合数据给出反馈，还有成就系统记录你的进步。坚持训练，你会看到自己的变化！"
)

_FALLBACK_ANSWER = (
    "这个问题我暂时还不太确定怎么回答～😅 不过关于注意力训练，我可以帮你：\n"
    "• 点评/分析训练数据（比如：\"帮我分析一下这次训练\"）\n"
    "• 讲解怎么提高注意力分数\n"
    "• 介绍找茬模式和动态追踪模式的区别\n"
    "• 给出训练频率和休息建议\n"
    "你可以换个说法再问我一次～"
)


def _wants_data_analysis(text: str) -> bool:
    """判断用户是否明确要求基于训练数据的分析。"""
    t = (text or "").lower()
    if any(m in t for m in _ANALYSIS_MARKERS) and any(m in t for m in _ANALYSIS_DATA_MARKERS):
        return True
    # “训练/成绩/表现/数据 + 怎么样”属于询问结果评价
    if "怎么样" in t:
        idx = t.index("怎么样")
        for marker in ("训练", "成绩", "表现", "数据"):
            pos = t.rfind(marker)
            if pos != -1 and pos < idx:
                return True
    return False


def _knowledge_reply(text: str) -> Optional[str]:
    """按常见问题返回本地知识库回答；无法识别时返回 None。"""
    t = (text or "").strip().lower()

    if any(m in t for m in _MODE_MARKERS) and any(m in t for m in _MODE_QUESTION_MARKERS):
        return _MODE_ANSWER
    if any(m in t for m in _IMPROVE_MARKERS):
        return _IMPROVE_ANSWER
    if any(m in t for m in _SCHEDULE_MARKERS):
        return _SCHEDULE_ANSWER
    if any(m in t for m in _FATIGUE_MARKERS):
        return _FATIGUE_ANSWER
    if any(m in t for m in _PREP_MARKERS):
        return _PREP_ANSWER
    if any(m in t for m in _WHAT_MARKERS):
        return _WHAT_ANSWER
    if any(m in t for m in _GREETING_MARKERS):
        return _GREETING_ANSWER
    if any(m in t for m in _THANKS_MARKERS):
        return _THANKS_ANSWER
    return None


def _fallback_reply(record: Optional[Dict[str, Any]]) -> str:
    """无法识别意图时的兜底回答，避免强制输出数据分析。"""
    if record is None:
        return _FALLBACK_ANSWER
    attention = record.get("avg_attention_score", record.get("avg_attention"))
    prefix = (
        f"我注意到你最近一次训练注意力是 {attention}/100，需要我帮你分析一下吗？\n"
        if attention is not None else ""
    )
    return (
        "这个问题我暂时还不太确定怎么回答～😅\n" + prefix +
        "不过关于注意力训练，我可以帮你：\n"
        "• 点评/分析训练数据（比如：\"帮我分析一下这次训练\"）\n"
        "• 讲解怎么提高注意力分数\n"
        "• 介绍找茬模式和动态追踪模式的区别\n"
        "• 给出训练频率和休息建议\n"
        "你想先了解哪一项？"
    )


def local_coach_reply(
    text: str,
    session_context: Optional[Dict[str, Any]] = None,
    recent_records: Optional[List[Dict[str, Any]]] = None,
    analyzer: Any = None,
    use_model: Optional[bool] = None,
) -> Tuple[str, str]:
    """无 API 时的本地回复，返回 (回复文本, kind)。"""
    reply, kind, _needs_cloud = local_coach_reply_detailed(
        text,
        session_context=session_context,
        recent_records=recent_records,
        analyzer=analyzer,
        use_model=use_model,
    )
    return reply, kind


def local_coach_reply_detailed(
    text: str,
    session_context: Optional[Dict[str, Any]] = None,
    recent_records: Optional[List[Dict[str, Any]]] = None,
    analyzer: Any = None,
    use_model: Optional[bool] = None,
) -> Tuple[str, str, bool]:
    """无 API 时的本地回复，返回 (回复文本, kind, 是否需要云端兜底)。

    kind 为 "report"（基于训练数据的结构化报告）或 "advice"（引导性建议）。
    needs_cloud 为 True 表示本地无法回答该问题（知识库未命中），
    可提示用户切换到云端大语言模型。
    analyzer 可注入（测试用），默认使用 LocalAnalysisEngine 单例。
    """
    record = None
    if session_context:
        record = session_context
    elif recent_records:
        record = recent_records[-1]

    text = (text or "").strip()

    # 常见问题优先直接回答，不要强行输出数据分析
    if not _wants_data_analysis(text):
        kb_reply = _knowledge_reply(text)
        if kb_reply is not None:
            return kb_reply, "advice", False

    # 用户明确要求分析训练数据时才输出结构化报告
    if _wants_data_analysis(text) and record is not None:
        try:
            if analyzer is None:
                from ai.local_analysis import LocalAnalysisEngine
                analyzer = LocalAnalysisEngine.instance()
            if use_model is None:
                try:
                    from core.settings import GlobalSettings
                    use_model = GlobalSettings().local_analysis_enabled()
                except Exception:
                    use_model = True

            report = analyzer.analyze_session(
                avg_attention=int(record.get("avg_attention_score", record.get("avg_attention", 0))),
                total_blinks=int(record.get("total_blinks", 0)),
                max_consecutive_hits=int(record.get("max_consecutive_hits", 0)),
                game_score=int(record.get("game_score", 0)),
                game_mode=record.get("game_mode", "find_difference"),
                duration_minutes=int(record.get("duration_minutes", 0)),
                avg_gaze_score=int(record.get("avg_gaze_score", 0)),
                avg_gaze_distance=float(record.get("avg_gaze_distance", 0.0)),
                difficulty=record.get("difficulty", "normal"),
                face_detected=record.get("face_detected"),
                use_model=use_model,
            )
            reply = f"🤖 我结合你的训练数据做了分析：\n\n{report}"
            return reply, "report", False
        except Exception as exc:
            print(f"AICoach: 本地分析失败: {exc}")

    if _wants_data_analysis(text):
        return _no_data_reply(), "advice", False
    return _fallback_reply(record), "advice", True