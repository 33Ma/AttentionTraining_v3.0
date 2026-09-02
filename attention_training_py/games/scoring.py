# games/scoring.py
"""连击加分规则：每命中一个点得 10 分，连击达到 5/10/15/20/25 次后
每次命中的得分按 6%/12%/18%/24%/30% 递增，25 连击及以上封顶 30%。

未命中惩罚规则：每次未命中使单次命中得分降低 5%（最多累计降低 25%），
连击达到 5 次及以上时恢复为 10 分基准下的正常加分状态。"""

BASE_POINTS_PER_HIT = 10
MAX_COMBO_BONUS_PERCENT = 30

PENALTY_PERCENT_PER_MISS = 5
MAX_PENALTY_PERCENT = 25
RECOVERY_COMBO = 5
MAX_PENALTY_MISSES = MAX_PENALTY_PERCENT // PENALTY_PERCENT_PER_MISS

# (连击阈值, 加分百分比)，达到阈值后该次命中即按对应百分比计分
COMBO_BONUS_TIERS = (
    (5, 6),
    (10, 12),
    (15, 18),
    (20, 24),
    (25, MAX_COMBO_BONUS_PERCENT),
)


def combo_bonus_percent(combo: int) -> int:
    """根据当前连击次数返回加分百分比（0-30）。"""
    bonus = 0
    for threshold, percent in COMBO_BONUS_TIERS:
        if combo >= threshold:
            bonus = percent
        else:
            break
    return bonus


def penalty_percent(misses: int) -> int:
    """返回当前未命中惩罚百分比（0-25），每次未命中累加 5%。"""
    return min(misses * PENALTY_PERCENT_PER_MISS, MAX_PENALTY_PERCENT)


def points_for_hit(combo: int, misses: int = 0) -> float:
    """返回连击达到 combo 次时，单次命中获得的分数。"""
    return (
        BASE_POINTS_PER_HIT
        * (1 + combo_bonus_percent(combo) / 100.0)
        * (1 - penalty_percent(misses) / 100.0)
    )
