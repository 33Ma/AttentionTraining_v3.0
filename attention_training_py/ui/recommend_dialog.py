# -*- coding: utf-8 -*-
"""个性化智能推荐对话框。

优先使用本地 ONNX 模型（LocalAnalysisEngine）基于训练历史推荐
（模式 + 难度）；本地模型不可用或本地分析被关闭时，若已配置云端
大语言模型则调用 LLM，否则回退到本地规则模板。推荐结果可通过
「用推荐开始训练」一键应用并进入训练。
"""

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.database import Database
from core.settings import DifficultyLevel, GlobalSettings
from core.user_manager import UserManager


MODE_NAMES = {
    "find_difference": "找茬模式",
    "dynamic_tracking": "动态追踪模式",
}

DIFFICULTY_NAMES = {
    "Easy": "简单",
    "Normal": "普通",
    "Hard": "困难",
}

DIFFICULTY_LEVELS = {
    "Easy": DifficultyLevel.EASY,
    "Normal": DifficultyLevel.NORMAL,
    "Hard": DifficultyLevel.HARD,
}

LLM_TIMEOUT_MS = 35000


class RecommendDialog(QDialog):
    """展示基于训练历史的个性化推荐，并支持一键开始训练。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("个性化智能推荐")
        self.setMinimumSize(440, 320)
        self.resize(480, 380)

        self._mode: Optional[str] = None
        self._difficulty: Optional[str] = None
        self._history: List[dict] = []
        self._llm_waiting = False
        self._llm_client = None

        self._setup_ui()
        self._apply_style_sheet()

        from core.llm_client import LLMClient
        self._llm_client = LLMClient()
        self._llm_client.recommendation_ready.connect(self._on_llm_recommendation)
        self._llm_client.error_occurred.connect(self._on_llm_error)

        QTimer.singleShot(0, self._compute_recommendation)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def recommended_mode(self) -> Optional[str]:
        return self._mode

    def recommended_difficulty(self) -> Optional[str]:
        return self._difficulty

    def recommended_difficulty_level(self) -> Optional[DifficultyLevel]:
        if self._difficulty is None:
            return None
        return DIFFICULTY_LEVELS.get(self._difficulty)

    def accepted_recommendation(self) -> bool:
        return self._mode is not None

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("💡 个性化智能推荐")
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("recommendTitle")
        title.setStyleSheet("font-size: 22px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        self._status_label = QLabel("正在分析训练记录，请稍候…")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("font-size: 14px; padding: 6px;")
        layout.addWidget(self._status_label)

        self._result_label = QLabel("")
        self._result_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._result_label.setWordWrap(True)
        self._result_label.setStyleSheet("font-size: 15px; padding: 10px; line-height: 1.6;")
        layout.addWidget(self._result_label, 1)

        hint = QLabel("💡 推荐依据为最近 10 条训练记录；模型不可用时自动回退规则。")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("font-size: 12px; color: #888888; padding: 4px;")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)

        self._start_btn = QPushButton("🎮 用推荐开始训练")
        self._start_btn.setEnabled(False)
        self._start_btn.setStyleSheet("font-size: 15px; font-weight: bold; padding: 10px 18px;")
        self._start_btn.clicked.connect(self.accept)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet("font-size: 14px; padding: 10px 24px;")
        close_btn.clicked.connect(self.reject)

        buttons.addStretch()
        buttons.addWidget(self._start_btn)
        buttons.addWidget(close_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

    def _apply_style_sheet(self):
        settings = GlobalSettings()
        bg = settings.background_color().name()
        text = settings.text_color().name()

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text}; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 8px; padding: 10px; }}
            QPushButton:hover {{ background-color: #45a049; }}
            QPushButton:disabled {{ background-color: #9e9e9e; }}
        """)

    # ------------------------------------------------------------------
    # 推荐逻辑
    # ------------------------------------------------------------------
    def _compute_recommendation(self):
        try:
            settings = GlobalSettings()
            username = UserManager().current_username()
            if username:
                try:
                    self._history = Database().fetch_training_records(username)
                except Exception as exc:
                    print(f"RecommendDialog: 获取训练记录失败: {exc}")
                    self._history = []

            use_local = settings.local_analysis_enabled()
            use_llm = settings.ai_enabled() and bool(settings.api_key())
            print('[AI][recommend] use_local=' + str(use_local) + ' use_llm=' + str(use_llm))

            if use_local or not use_llm:
                from ai.local_analysis import LocalAnalysisEngine
                engine = LocalAnalysisEngine.instance()
                mode, difficulty = engine.recommend_mode(
                    self._history, use_model=use_local,
                )
                source = "本地 ONNX 模型" if (use_local and engine.available()) else "本地规则分析"
                self._show_result(mode, difficulty, source)
            else:
                self._status_label.setText("正在调用大语言模型分析训练记录，请稍候…")
                self._llm_waiting = True
                self._llm_client.recommend_training_mode(self._history)
                QTimer.singleShot(LLM_TIMEOUT_MS, self._on_llm_timeout)
        except Exception as exc:
            print(f"RecommendDialog: 推荐失败: {exc}")
            self._status_label.setText("推荐失败，请稍后重试。")

    def _show_result(self, mode: str, difficulty: str, source: str):
        self._llm_waiting = False
        print('[AI][recommend] show result source=' + str(source) + ' mode=' + str(mode) + ' diff=' + str(difficulty))
        self._mode = mode
        self._difficulty = difficulty

        mode_name = MODE_NAMES.get(mode, mode)
        diff_name = DIFFICULTY_NAMES.get(difficulty, difficulty)

        records = [r for r in self._history if isinstance(r, dict)]
        atts = [int(r.get("avg_attention_score") or 0) for r in records]
        avg_att = round(sum(atts) / len(atts)) if atts else 0

        if records:
            basis = f"📊 依据：{len(records)} 条训练记录"
            if atts:
                basis += f"，平均注意力 {avg_att} 分"
        else:
            basis = "📊 暂无训练记录，推荐从基础组合开始"

        lines = [
            f"🎯 推荐模式：{mode_name}",
            f"📶 推荐难度：{diff_name}",
            "",
            basis,
            f"🧠 分析来源：{source}",
            "",
            "点击「用推荐开始训练」将按推荐模式与难度进入训练。",
        ]
        self._status_label.setText("✨ 推荐完成")
        self._result_label.setText("\n".join(lines))
        self._start_btn.setEnabled(True)
        # 推荐文案填充后布局最小尺寸可能变大，立即扩展到能容纳内容的高度，
        # 避免第一次拖动窗口时才被动变大。
        min_size = self.layout().minimumSize()
        if self.width() < min_size.width() or self.height() < min_size.height():
            self.resize(
                max(self.width(), min_size.width()),
                max(self.height(), min_size.height()),
            )

    def _on_llm_recommendation(self, mode: str, difficulty: str):
        if not self._llm_waiting:
            return
        print('[AI][recommend] cloud ok')
        self._show_result(mode, difficulty, "云端大语言模型")

    def _on_llm_error(self, _message: str):
        print('[AI][recommend] llm error: ' + str(_message))
        if self._llm_waiting:
            self._fallback_to_rules()

    def _on_llm_timeout(self):
        print('[AI][recommend] llm timeout')
        if self._llm_waiting:
            self._fallback_to_rules()

    def _fallback_to_rules(self):
        print('[AI][recommend] fallback to rules')
        try:
            from ai.local_analysis import LocalAnalysisEngine
            mode, difficulty = LocalAnalysisEngine.instance().recommend_mode(
                self._history, use_model=False,
            )
            self._show_result(mode, difficulty, "本地规则分析")
        except Exception as exc:
            print(f"RecommendDialog: 规则回退失败: {exc}")
            self._status_label.setText("推荐失败，请稍后重试。")
            self._llm_waiting = False
