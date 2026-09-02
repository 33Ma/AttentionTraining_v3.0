# -*- coding: utf-8 -*-
"""综合评分（连续加权版）。

动态追踪模式（dynamic_tracking）改用新的游戏分数：游戏内不再累计原始得分，
而是按“命中率 / 平均响应时间 / 追踪路径效率”三项相对分（各 0-100）加权得到
0-100 的新游戏分数。因此动态追踪的综合评分中：
  - 注意力 45%
  - 游戏表现（即新游戏分）55%

找茬模式（find_difference）仍使用旧方案：
  - 注意力 35%、最高连击 30%、游戏得分比例 35%。

共有的设计约束：
- 连续化：各组件按连续比例计分，消除分档边界处的悬空跳变；
- 去正交：注意力指标已包含注视成分，综合分不再单独叠加注视项；
- 归一化：游戏得分按“模式 × 难度”参考基准归一；
- 缺失处理：未启用摄像头/未检测到人脸时剔除注意力项，并按已测组件权重重新归一；
- 历史兼容：旧记录没有 face_detected 字段时，按注意力/注视数据是否非零推断。
"""


ATTENTION_WEIGHT = 35
COMBO_WEIGHT = 30
RATIO_WEIGHT = 35
DT_ATTENTION_WEIGHT = 45
DT_GAME_WEIGHT = 55
COMBO_FULL_MARKS = 25  # 最高档要求连击 25 次以上
# 连击档位：(达到连击数, 得分)。最高档 25 次以上 → 满分 30。
COMBO_TIERS = (
    (3, 5),
    (5, 9),
    (8, 13),
    (12, 17),
    (16, 21),
    (20, 25),
    (25, 30),
)

# 找茬模式游戏得分参考基准（动态追踪已不使用，见 score_ratio）。
# 基准按 1 分钟标定，score_ratio 会按训练时长线性放大（5 分钟 ×5、10 分钟 ×10）。
RATIO_REFERENCE = {
    # 简单（路线 B）：点更大、生存期 1.2s，同水平原始分最高，基准相应最高。
    ("find_difference", "easy"): 950,
    # 找茬普通难度（路线 B）：1.5s 节奏、每波 2 点错峰 0.65s，1 分钟约 80 点，
    # 原始分上限明显高于旧版（旧基准 580），上调到 900 避免 0-100 归一化在高分段被截断。
    ("find_difference", "normal"): 900,
    ("find_difference", "hard"): 560,
    ("find_difference", "custom"): 570,
}

_INT_DIFFICULTY = {0: "easy", 1: "normal", 2: "hard", 3: "custom"}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize_difficulty(difficulty) -> str:
    if hasattr(difficulty, "value"):
        difficulty = difficulty.value
    if isinstance(difficulty, int):
        difficulty = _INT_DIFFICULTY.get(difficulty, "normal")
    if difficulty not in ("easy", "normal", "hard", "custom"):
        return "normal"
    return difficulty


def _normalize_mode(game_mode: str) -> str:
    return game_mode if game_mode in ("find_difference", "dynamic_tracking") else "find_difference"


def score_ratio(game_score: int, game_mode: str, difficulty="normal",
                duration_minutes: int = 1) -> float:
    """游戏得分归一化到 [0,1]。

    动态追踪的新游戏分本身就是 0-100 的相对分，直接除以 100；
    找茬模式按“模式 × 难度”参考基准归一，满分基准随训练时长线性放大
    （1 分钟为基准值，5 分钟 ×5、10 分钟 ×10）。
    """
    mode = _normalize_mode(game_mode)
    if mode == "dynamic_tracking":
        return clamp01(game_score / 100.0)
    reference = RATIO_REFERENCE.get((mode, _normalize_difficulty(difficulty)))
    if not reference:
        return 0.0
    minutes = max(1, int(duration_minutes or 1))
    return clamp01(game_score / (reference * minutes))


def _get_field(record, name, default=None):
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def camera_measured(avg_attention: int, avg_gaze_score: int, face_detected=None) -> bool:
    """判断摄像头数据是否有效。

    新记录由 face_detected 显式标记（0/1）；旧记录无该字段时为 None，
    按注意力/注视分数是否非零推断（旧版本完全无数据时两者均为 0）。
    """
    if face_detected is not None:
        return bool(face_detected)
    return (avg_attention or 0) > 0 or (avg_gaze_score or 0) > 0


def composite_score(
    avg_attention: int = 0,
    max_consecutive_hits: int = 0,
    game_score: int = 0,
    game_mode: str = "find_difference",
    difficulty="normal",
    avg_gaze_score: int = 0,
    face_detected=None,
    duration_minutes: int = 1,
) -> int:
    """连续加权综合评分（0-100 整数）。摄像头数据无效时剔除注意力项并按剩余权重归一。"""
    total, _ = composite_details(
        avg_attention=avg_attention,
        max_consecutive_hits=max_consecutive_hits,
        game_score=game_score,
        game_mode=game_mode,
        difficulty=difficulty,
        avg_gaze_score=avg_gaze_score,
        face_detected=face_detected,
        duration_minutes=duration_minutes,
    )
    return total


def composite_details(
    avg_attention: int = 0,
    max_consecutive_hits: int = 0,
    game_score: int = 0,
    game_mode: str = "find_difference",
    difficulty="normal",
    avg_gaze_score: int = 0,
    face_detected=None,
    duration_minutes: int = 1,
):
    """计算综合评分及其分量分解。

    返回 (总分, [(分量名, 得分, 满分), ...])；
    摄像头数据无效时不包含注意力分量。
    """
    parts = []
    weights = []
    mode = _normalize_mode(game_mode)

    if mode == "dynamic_tracking":
        if camera_measured(avg_attention, avg_gaze_score, face_detected):
            w = DT_ATTENTION_WEIGHT
            parts.append(("注意力", w * clamp01(avg_attention / 100.0), w))
            weights.append(w)
        w = DT_GAME_WEIGHT
        parts.append(("游戏表现", w * clamp01(game_score / 100.0), w))
        weights.append(w)
    else:
        if camera_measured(avg_attention, avg_gaze_score, face_detected):
            w = ATTENTION_WEIGHT
            parts.append(("注意力", w * clamp01(avg_attention / 100.0), w))
            weights.append(w)

        combo = max(int(max_consecutive_hits or 0), 0)
        w = COMBO_WEIGHT
        combo_points = 0
        for threshold, points in COMBO_TIERS:
            if combo >= threshold:
                combo_points = points
            else:
                break
        parts.append(("最高连击", combo_points, w))
        weights.append(w)

        w = RATIO_WEIGHT
        parts.append(("游戏表现", w * score_ratio(game_score, game_mode, difficulty, duration_minutes), w))
        weights.append(w)

    if not weights:
        return 0, []
    total = int(round(sum(p for _, p, _ in parts) / sum(weights) * 100.0))
    return total, parts


def record_composite_score(record) -> int:
    """从训练记录取综合分；未落库（<0 或缺失）时按字段实时重算。"""
    stored = _get_field(record, "composite_score", -1)
    if stored is not None and int(stored) >= 0:
        return int(stored)
    return composite_score(
        avg_attention=int(_get_field(record, "avg_attention_score", 0) or 0),
        max_consecutive_hits=int(_get_field(record, "max_consecutive_hits", 0) or 0),
        game_score=int(_get_field(record, "game_score", 0) or 0),
        game_mode=_get_field(record, "game_mode", "find_difference") or "find_difference",
        difficulty=_get_field(record, "difficulty", "normal") or "normal",
        avg_gaze_score=int(_get_field(record, "avg_gaze_score", 0) or 0),
        face_detected=_get_field(record, "face_detected"),
        duration_minutes=int(_get_field(record, "duration_minutes", 1) or 1),
    )


def score_band_label(score: int) -> str:
    """综合分档位文案（与报告阈值一致）。"""
    if score >= 80:
        return "卓越表现"
    if score >= 65:
        return "表现优秀"
    if score >= 50:
        return "表现良好"
    if score >= 35:
        return "表现一般"
    return "需要更多练习"
