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
