# -*- coding: utf-8 -*-
"""训练数据本地智能分析引擎（ONNX Runtime）。

在云端 AI（LLM API）不可用或未配置时，用本地 ONNX 小模型对训练数据做
结构化分析：专注等级、疲劳等级、表现等级，以及训练模式/难度推荐。
模型由 tools/train_local_models.py 从现有评分规则蒸馏生成，推理完全在本机完成。

模型缺失或 onnxruntime 不可用时自动回退到规则模板，保证功能不中断。
"""

import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from core.paths import models_dir


SESSION_MODEL_FILE = "session_analysis.onnx"
RECOMMEND_MODEL_FILE = "mode_recommend.onnx"

ATTENTION_LEVEL_NAMES = ("待提升", "一般", "良好", "优秀", "卓越")
FATIGUE_LEVEL_NAMES = ("正常", "轻度疲劳", "明显疲劳")
PERFORMANCE_LEVEL_NAMES = ("待提升", "一般", "良好", "优秀", "出色")

ATTENTION_LEVEL_EMOJI = ("🎯", "📊", "📈", "✨", "🌟")
FATIGUE_LEVEL_EMOJI = ("✅", "⚠️", "😴")
PERFORMANCE_LEVEL_EMOJI = ("🎯", "📈", "👍", "⭐", "🏆")

DIFFICULTY_NAMES = ("Easy", "Normal", "Hard")


class LocalAnalysisEngine:
    """ONNX 本地分析引擎（线程安全单例）。"""

    _instance: Optional["LocalAnalysisEngine"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> "LocalAnalysisEngine":
        return cls()

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._lock = threading.Lock()
        self._sessions: Dict[str, Any] = {}
        self._ort: Any = None

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def _load(self) -> bool:
        """延迟导入 onnxruntime；失败时返回 False，上层回退规则。"""
        if self._ort is not None:
            return True
        with self._lock:
            if self._ort is not None:
                return True
            try:
                import onnxruntime as ort
                self._ort = ort
            except Exception as exc:  # pragma: no cover - 环境缺少 onnxruntime
                print(f"LocalAnalysisEngine: onnxruntime 不可用: {exc}")
                self._ort = None
            return self._ort is not None

    def _model_path(self, name: str) -> str:
        return os.path.join(models_dir(), name)

    def _session(self, model_file: str):
        if not self._load():
            return None
        path = self._model_path(model_file)
        if not os.path.exists(path):
            print(f"LocalAnalysisEngine: 模型文件不存在: {path}")
            return None
        if model_file not in self._sessions:
            with self._lock:
                if model_file not in self._sessions:
                    try:
                        self._sessions[model_file] = self._ort.InferenceSession(
                            path,
                            providers=self._ort.get_available_providers(),
                        )
                    except Exception as exc:
                        print(f"LocalAnalysisEngine: 模型加载失败 {model_file}: {exc}")
                        return None
        return self._sessions[model_file]

    def available(self) -> bool:
        """本地 ONNX 分析是否可用（模型文件齐全且运行时可导入）。"""
        return (
            self._session(SESSION_MODEL_FILE) is not None
            and self._session(RECOMMEND_MODEL_FILE) is not None
        )

    # ------------------------------------------------------------------
    # 特征构造
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _score_ratio(game_score: int, game_mode: str) -> float:
        max_possible = 500 if game_mode == "find_difference" else 800
        return (game_score / max_possible) if max_possible > 0 else 0.0

    def _session_features(
        self,
        avg_attention: int,
        total_blinks: int,
        max_consecutive_hits: int,
        game_score: int,
        game_mode: str,
        duration_minutes: int,
        avg_gaze_score: int,
        avg_gaze_distance: float,
    ) -> List[float]:
        blink_rate = (total_blinks / duration_minutes) if duration_minutes > 0 else 0.0
        return [
            self._clamp01(avg_attention / 100.0),
            self._clamp01(blink_rate / 45.0),
            self._clamp01(max_consecutive_hits / 30.0),
            self._clamp01(self._score_ratio(game_score, game_mode)),
            self._clamp01(duration_minutes / 30.0),
            self._clamp01(avg_gaze_score / 100.0),
            self._clamp01(avg_gaze_distance),
        ]

    def _recommend_features(self, history: List[Dict[str, Any]]) -> Optional[List[float]]:
        records = [r for r in history if isinstance(r, dict)][-10:]
        if not records:
            return None

        def attention(r: Dict[str, Any]) -> float:
            return float(r.get("avg_attention_score") or r.get("avg_attention") or 50)

        def ratio(r: Dict[str, Any]) -> float:
            mode = r.get("game_mode") or "find_difference"
            max_possible = 500 if mode == "find_difference" else 800
            score = float(r.get("game_score") or 0)
            return self._clamp01(score / max_possible) if max_possible else 0.0

        atts = [attention(r) for r in records]
        ratios = [ratio(r) for r in records]
        mean_att = sum(atts) / len(atts)
        mean_ratio = sum(ratios) / len(ratios)
        trend_att = (atts[-1] - mean_att) / 50.0
        trend_ratio = ratios[-1] - mean_ratio
        last_mode = 1.0 if (records[-1].get("game_mode") == "dynamic_tracking") else 0.0

        return [
            self._clamp01(mean_att / 100.0),
            self._clamp01(mean_ratio),
            self._clamp01(0.5 + trend_att),
            self._clamp01(0.5 + trend_ratio),
            self._clamp01(len(records) / 20.0),
            last_mode,
        ]

    # ------------------------------------------------------------------
    # ONNX 推理
    # ------------------------------------------------------------------
    def predict_session(
        self,
        avg_attention: int,
        total_blinks: int,
        max_consecutive_hits: int,
        game_score: int,
        game_mode: str,
        duration_minutes: int,
        avg_gaze_score: int = 0,
        avg_gaze_distance: float = 0.0,
    ) -> Optional[Dict[str, int]]:
        """用 ONNX 模型预测（attention_level / fatigue / performance），模型不可用时返回 None。"""
        sess = self._session(SESSION_MODEL_FILE)
        if sess is None:
            return None
        try:
            import numpy as np

            features = self._session_features(
                avg_attention, total_blinks, max_consecutive_hits,
                game_score, game_mode, duration_minutes,
                avg_gaze_score, avg_gaze_distance,
            )
            feeds = {sess.get_inputs()[0].name: np.asarray([features], dtype=np.float32)}
            outs = sess.run(None, feeds)
            names = ("attention_level", "fatigue", "performance")
            return {
                name: int(outs[i][0].argmax())
                for i, name in enumerate(names)
            }
        except Exception as exc:
            print(f"LocalAnalysisEngine: 会话分析推理失败: {exc}")
            return None

    def predict_recommend(self, history: List[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
        """用 ONNX 模型推荐 (模式, 难度)，模型不可用或历史为空时返回 None。"""
        features = self._recommend_features(history)
        sess = self._session(RECOMMEND_MODEL_FILE)
        if sess is None or features is None:
            return None
        try:
            import numpy as np

            feeds = {sess.get_inputs()[0].name: np.asarray([features], dtype=np.float32)}
            outs = sess.run(None, feeds)
            mode_idx = int(outs[0][0].argmax())
            diff_idx = int(outs[1][0].argmax())
            mode = "dynamic_tracking" if mode_idx else "find_difference"
            return mode, DIFFICULTY_NAMES[diff_idx]
        except Exception as exc:
            print(f"LocalAnalysisEngine: 模式推荐推理失败: {exc}")
            return None

    # ------------------------------------------------------------------
    # 规则回退（模型不可用时的分级）
    # ------------------------------------------------------------------
    @staticmethod
    def _rule_attention(avg_attention: int) -> int:
        if avg_attention >= 80:
            return 4
        if avg_attention >= 65:
            return 3
        if avg_attention >= 50:
            return 2
        if avg_attention >= 35:
            return 1
        return 0

    @staticmethod
    def _rule_fatigue(blink_rate: float) -> int:
        if blink_rate < 4 or blink_rate > 30:
            return 2
        if blink_rate < 8 or blink_rate > 20:
            return 1
        return 0

    @staticmethod
    def _rule_performance(score_ratio: float) -> int:
        if score_ratio >= 0.8:
            return 4
        if score_ratio >= 0.6:
            return 3
        if score_ratio >= 0.4:
            return 2
        if score_ratio >= 0.2:
            return 1
        return 0

    def _rule_recommend(self, history: List[Dict[str, Any]]) -> Tuple[str, str]:
        features = self._recommend_features(history)
        if features is None:
            return "find_difference", "Normal"
        mean_att = features[0] * 100.0
        mean_ratio = features[1]
        trend_att = features[2] - 0.5
        if mean_att >= 75 and mean_ratio >= 0.6:
            mode, diff = "dynamic_tracking", 2
        elif mean_att >= 70:
            mode, diff = "dynamic_tracking", 1
        elif mean_att >= 50:
            mode = "dynamic_tracking" if mean_ratio >= 0.6 else "find_difference"
            diff = 1
        else:
            mode, diff = "find_difference", 0
        if trend_att > 0.1 and diff < 2:
            diff += 1
        if trend_att < -0.2 and diff > 0:
            diff -= 1
        return mode, DIFFICULTY_NAMES[diff]

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def analyze_session(
        self,
        avg_attention: int,
        total_blinks: int,
        max_consecutive_hits: int,
        game_score: int,
        game_mode: str,
        duration_minutes: int,
        avg_gaze_score: int = 0,
        avg_gaze_distance: float = 0.0,
        use_model: bool = True,
    ) -> str:
        """生成训练分析报告；优先使用 ONNX 模型，不可用时回退规则模板。"""
        blink_rate = (total_blinks / duration_minutes) if duration_minutes > 0 else 0.0
        score_ratio = self._score_ratio(game_score, game_mode)

        prediction = None
        if use_model:
            prediction = self.predict_session(
                avg_attention, total_blinks, max_consecutive_hits,
                game_score, game_mode, duration_minutes,
                avg_gaze_score, avg_gaze_distance,
            )
        if prediction is None:
            prediction = {
                "attention_level": self._rule_attention(avg_attention),
                "fatigue": self._rule_fatigue(blink_rate),
                "performance": self._rule_performance(score_ratio),
            }
            source = "规则"
        else:
            source = "ONNX 模型"

        return self._render_report(
            avg_attention=avg_attention,
            total_blinks=total_blinks,
            blink_rate=blink_rate,
            max_consecutive_hits=max_consecutive_hits,
            game_score=game_score,
            score_ratio=score_ratio,
            game_mode=game_mode,
            duration_minutes=duration_minutes,
            avg_gaze_score=avg_gaze_score,
            avg_gaze_distance=avg_gaze_distance,
            attention_idx=prediction["attention_level"],
            fatigue_idx=prediction["fatigue"],
            performance_idx=prediction["performance"],
            source=source,
        )

    def recommend_mode(self, history: List[Dict[str, Any]], use_model: bool = True) -> Tuple[str, str]:
        """根据近期训练记录推荐 (模式, 难度)；模型不可用时回退规则。"""
        prediction = self.predict_recommend(history) if use_model else None
        if prediction is not None:
            return prediction
        return self._rule_recommend(history)

    # ------------------------------------------------------------------
    # 报告渲染（与原有本地分析模板结构一致）
    # ------------------------------------------------------------------
    def _render_report(
        self,
        *,
        avg_attention: int,
        total_blinks: int,
        blink_rate: float,
        max_consecutive_hits: int,
        game_score: int,
        score_ratio: float,
        game_mode: str,
        duration_minutes: int,
        avg_gaze_score: int,
        avg_gaze_distance: float,
        attention_idx: int,
        fatigue_idx: int,
        performance_idx: int,
        source: str,
    ) -> str:
        mode_name = "找茬模式" if game_mode == "find_difference" else "动态追踪模式"

        attention_level = f"{ATTENTION_LEVEL_EMOJI[attention_idx]} {ATTENTION_LEVEL_NAMES[attention_idx]}"
        fatigue_status = f"{FATIGUE_LEVEL_EMOJI[fatigue_idx]} {FATIGUE_LEVEL_NAMES[fatigue_idx]}"
        score_status = f"{PERFORMANCE_LEVEL_EMOJI[performance_idx]} {PERFORMANCE_LEVEL_NAMES[performance_idx]}"

        # 连击评估（规则）
        if max_consecutive_hits >= 20:
            combo_status = "🏆 完美"
        elif max_consecutive_hits >= 15:
            combo_status = "⭐ 优秀"
        elif max_consecutive_hits >= 10:
            combo_status = "👍 良好"
        elif max_consecutive_hits >= 5:
            combo_status = "📈 一般"
        else:
            combo_status = "🎯 待提升"

        # 注视评估（规则）
        if avg_gaze_score >= 90:
            gaze_level = "🌟 非常专注"
            gaze_suggestion = "视线非常稳定，展现了极佳的专注力！继续这样保持！"
        elif avg_gaze_score >= 75:
            gaze_level = "✨ 专注良好"
            gaze_suggestion = "视线基本集中在屏幕中心，专注度不错！"
        elif avg_gaze_score >= 55:
            gaze_level = "📈 专注一般"
            gaze_suggestion = "视线有轻微偏移，建议训练时尽量保持视线在屏幕中心。"
        else:
            gaze_level = "🎯 需要改进"
            gaze_suggestion = "视线偏离较多，建议休息一下再继续训练，保持正对屏幕的姿势。"

        if avg_gaze_distance < 0.1:
            gaze_distance_desc = "（非常集中，视线几乎未离开屏幕中心）"
        elif avg_gaze_distance < 0.2:
            gaze_distance_desc = "（良好，视线基本保持在屏幕中心附近）"
        elif avg_gaze_distance < 0.3:
            gaze_distance_desc = "（一般，有轻微视线偏移）"
        else:
            gaze_distance_desc = "（需要改善，视线经常离开屏幕中心）"

        analysis = "🤖 本地智能分析（" + source + "）\n"
        analysis += "📊 训练数据概览\n"
        analysis += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        analysis += f"• 🧠 平均注意力分数：{avg_attention}/100（{attention_level}）\n"
        analysis += f"• 👁️ 总眨眼次数：{total_blinks}次（频率：{int(round(blink_rate))}次/分钟，状态：{fatigue_status}）\n"
        analysis += f"• ⚡ 最高连击：{max_consecutive_hits}次（{combo_status}）\n"
        analysis += f"• 🎮 游戏得分：{game_score}分（{score_status}）\n"
        analysis += f"• 🎲 游戏模式：{mode_name}\n"
        analysis += f"• ⏱️ 训练时长：{duration_minutes}分钟\n"
        analysis += f"• 👀 注视专注度：{avg_gaze_score}/100（{gaze_level}）{gaze_distance_desc}\n\n"

        analysis += "💡 分析建议\n"
        analysis += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

        attention_advice = {
            4: "✨ 注意力表现卓越！你展现了极强的专注能力，继续保持这个状态！",
            3: "✨ 注意力表现优秀！你展现了很强的专注能力，继续保持这个状态！",
            2: "📈 注意力表现良好，有不错的提升空间。继续保持训练，你会越来越好！",
            1: "📊 注意力一般，试着在安静、无干扰的环境中训练，训练前做5分钟深呼吸。",
            0: "🎯 注意力需要加强。建议在安静、无干扰的环境中进行训练，训练前做5分钟深呼吸。",
        }
        analysis += attention_advice[attention_idx] + "\n"

        if max_consecutive_hits >= 15:
            analysis += "⚡ 连击能力很强！你的反应速度和精准度都很出色，可以尝试挑战更高难度！\n"
        elif max_consecutive_hits >= 8:
            analysis += "🎯 连击表现不错，继续练习提高稳定性，目标是达到15次以上！\n"
        else:
            analysis += "🎯 连击有待提高。建议先注重准确率，再追求速度，逐步提升连击数。\n"

        fatigue_advice = {
            2: "😴 眨眼频率异常，明显疲劳。建议立即休息，避免眼部过度疲劳。",
            1: "⚠️ 眨眼频率略有波动，可能有些疲劳。建议训练中适时休息，每15分钟让眼睛放松一下。",
            0: "👁️ 眨眼频率正常，状态良好！",
        }
        analysis += fatigue_advice[fatigue_idx] + "\n"

        performance_advice = {
            4: "🏆 游戏表现非常出色，得分率很高，继续保持！",
            3: "⭐ 游戏表现优秀，得分率不错，可以尝试挑战更高难度！",
            2: "👍 游戏表现良好，继续提升准确率和稳定性！",
            1: "📈 游戏表现一般，建议先注重准确率，再追求速度。",
            0: "🎯 游戏表现有待提升，多练习会越来越好！",
        }
        analysis += performance_advice[performance_idx] + "\n"

        # 注视相关建议
        analysis += "\n👀 注视专注度分析：\n"
        analysis += f"   {gaze_suggestion}\n"
        if avg_gaze_distance >= 0.25:
            analysis += "   💡 建议：调整坐姿，确保正对屏幕，眼睛与屏幕保持适当距离。\n"
        elif avg_gaze_distance >= 0.15:
            analysis += "   💡 建议：尝试在训练中时刻提醒自己关注屏幕中心区域。\n"
        else:
            analysis += "   💡 建议：继续保持良好的注视习惯！\n"

        # 综合评分（规则）
        overall_score = 0
        if avg_attention >= 70:
            overall_score += 30
        elif avg_attention >= 50:
            overall_score += 20
        else:
            overall_score += 10

        if max_consecutive_hits >= 15:
            overall_score += 25
        elif max_consecutive_hits >= 8:
            overall_score += 15
        elif max_consecutive_hits >= 3:
            overall_score += 8

        if score_ratio >= 0.6:
            overall_score += 25
        elif score_ratio >= 0.3:
            overall_score += 15
        else:
            overall_score += 5

        if avg_gaze_score >= 75:
            overall_score += 20
        elif avg_gaze_score >= 55:
            overall_score += 12
        else:
            overall_score += 5

        analysis += f"\n🏆 综合评分：{overall_score}/100\n"
        if overall_score >= 80:
            analysis += "🌟🌟🌟🌟🌟 卓越表现！你是注意力训练大师！\n"
        elif overall_score >= 65:
            analysis += "🌟🌟🌟🌟 表现优秀，继续进步！\n"
        elif overall_score >= 50:
            analysis += "🌟🌟🌟 表现良好，坚持训练会更好！\n"
        elif overall_score >= 35:
            analysis += "🌟🌟 表现一般，继续加油！\n"
        else:
            analysis += "🌟 需要更多练习，相信自己会越来越好！\n"

        analysis += "\n🌟 下次训练建议\n"
        analysis += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        analysis += "• 保持规律的训练频率，每周3-4次效果最佳\n"
        analysis += "• 训练前做5分钟深呼吸，帮助集中注意力\n"
        analysis += "• 每次训练后适当休息，避免眼部疲劳\n"
        analysis += "• 逐步增加训练时长和难度，循序渐进\n"
        analysis += "• 训练时保持正对屏幕，视线集中在屏幕中心区域\n"

        target_attention = min(100, avg_attention + 15)
        target_combo = max_consecutive_hits + 5
        target_score = int(game_score * 1.2)
        target_gaze = min(100, avg_gaze_score + 10)

        analysis += "\n🎯 下次训练目标\n"
        analysis += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        analysis += f"• 目标注意力分数：{target_attention}分以上\n"
        analysis += f"• 目标最高连击：{target_combo}次\n"
        analysis += f"• 目标游戏得分：{target_score}分\n"
        analysis += f"• 目标注视专注度：{target_gaze}分以上\n"

        analysis += "\n💪 每一次训练都是进步的开始，期待你下次更出色的表现！加油！\n"
        return analysis
