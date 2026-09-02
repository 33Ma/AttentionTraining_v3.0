# -*- coding: utf-8 -*-
"""AI 教练对话对话框（学生端）。"""

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

from ai.ai_coach import AICoachManager
from core.settings import GlobalSettings
from core.user_manager import UserManager


class AICoachDialog(QDialog):
    """与 AI 教练多轮对话的聊天窗口。

    session_context：从训练报告页跳转时携带的本次训练数据（字典），
    首次消息会自动带上并发送一条咨询。
    """

    def __init__(
        self,
        parent=None,
        session_context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent)
        self._session_context = session_context or None
        self._pending_request_id = 0
        self._last_question = ""

        self.setWindowTitle("🤖 AI教练")
        self.setMinimumSize(560, 640)
        self.resize(620, 720)

        self._setup_ui()
        self._apply_style_sheet()

        self._manager = AICoachManager.instance()
        self._connect_signals()
        self._load_history()

        if self._session_context and UserManager().is_logged_in():
            self._auto_ask()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("🤖 AI教练 · 你的注意力训练伙伴")
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
        self._input_edit.setPlaceholderText("输入你想咨询教练的问题，回车发送…")
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

    # ------------------------------------------------------------------
    # 信号与历史
    # ------------------------------------------------------------------
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
        rows = self._manager.load_history(username, limit=100)
        for row in rows:
            self._append_chat(row["role"], row["content"])

    def _auto_ask(self):
        """从训练报告页进入时，自动发起一次带上下文的咨询。"""
        self._append_chat("system", "📎 已携带你刚才的训练数据，教练会结合数据回答。")
        self._send_message("请结合我刚刚完成的这次训练，给我一些反馈和建议。")

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_send_clicked(self):
        text = self._input_edit.text().strip()
        if not text:
            return
        self._input_edit.clear()
        self._send_message(text)

    def _send_message(self, text: str):
        username = UserManager().current_username()
        if not username:
            QMessageBox.warning(self, "未登录", "请先登录后再与教练对话。")
            return
        if self._pending_request_id:
            return

        self._last_question = text
        request_id = self._manager.submit_message(
            username,
            text,
            session_context=self._session_context,
        )
        if not request_id:
            QMessageBox.warning(self, "提示", "当前无法发送，请稍后再试。")
            return

        self._pending_request_id = request_id
        self._session_context = None  # 上下文只在首次消息使用
        self._append_chat("user", text)
        self._set_busy(True)

    def _on_clear_clicked(self):
        username = UserManager().current_username()
        if not username:
            return
        ret = QMessageBox.question(
            self,
            "清空对话",
            "确定要清空与 AI 教练的全部对话记录吗？",
        )
        if ret == QMessageBox.Yes:
            self._manager.clear_history(username)
            self._chat_view.clear()

    def _on_cancel_clicked(self):
        """取消正在进行的请求，立即恢复输入。"""
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
        self._status_label.setText("教练正在思考…" if busy else "")

    def _append_chat(self, role: str, text: str):
        text = str(text).strip()
        if not text:
            return
        if role == "user":
            block = f"你：\n{text}"
        elif role == "assistant":
            block = f"🤖 教练：\n{text}"
        else:
            block = text
        self._chat_view.append(block)
        self._chat_view.append("")

    # ------------------------------------------------------------------
    # 槽函数
    # ------------------------------------------------------------------
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
        """本地模型无法回答时，提示用户是否改用云端大语言模型。"""
        if request_id != self._pending_request_id:
            return
        self._pending_request_id = 0
        self._set_busy(False)
        self._append_chat("assistant", content)

        ret = QMessageBox.question(
            self,
            "AI教练",
            "这个问题还在学习中，是否使用云端大语言模型来回答？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self._send_cloud_fallback()

    def _send_cloud_fallback(self):
        """以强制云端方式重发当前问题。"""
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
                "尚未配置云端大语言模型。请到「设置 → AI智能助手」勾选“启用AI智能分析”并填写 API 密钥后重试。",
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
