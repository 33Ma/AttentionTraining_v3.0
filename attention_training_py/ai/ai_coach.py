# -*- coding: utf-8 -*-
"""AI 教练对话服务（以 ai/ 包为底座）。

- AICoachManager：单例，消息队列 + QThread 工作线程，负责对话历史落库与信号分发；
- AICoachWorker：在线程内执行，优先调用 OpenAI 兼容 API，未配置或失败时回退到
  本地 ONNX 分析（LocalAnalysisEngine，模型缺失自动走规则模板）。

已并入 core/llm_client.py 中定义但未使用的 advice_ready / report_ready 信号：
本模块按回复类型（建议/报告）真正发出，LLMClient 保持兼容不动。
"""

from typing import Any, Dict, List, Optional

import requests
import threading
from PySide6.QtCore import QObject, QMutex, QMutexLocker, QThread, QTimer, Signal, Slot

from .coach_logic import (build_system_prompt, local_coach_reply_detailed, normalize_chat_completions_url, trim_history)
from core.database import Database
from core.settings import GlobalSettings


HISTORY_LIMIT = 20          # 保留最近多少轮对话
RECENT_RECORDS_LIMIT = 5    # 上下文里带最近几条训练记录
REQUEST_TIMEOUT = (10, 20)   # (连接超时, 读取超时) 秒


class _RequestCancelled(Exception):
    """请求被用户取消。"""


class AICoachWorker(QObject):
    """在线程中处理一条教练对话消息。"""

    message_ready = Signal(str)
    message_error = Signal(str)
    local_fallback_ready = Signal(str)
    finished = Signal()
    # 并入 llm_client 的未用信号：按回复类型分派
    advice_ready = Signal(str)
    report_ready = Signal(str)

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
        session_context: Optional[Dict[str, Any]],
        history: List[Dict[str, Any]],
        recent_records: List[Dict[str, Any]],
        api_key: str,
        api_url: str,
        model: str,
        use_local_model: bool,
    ):
        """保存待处理请求参数（线程启动前调用）。"""
        self._pending = (
            username, text, session_context, history, recent_records,
            api_key, api_url, model, use_local_model,
        )

    @Slot()
    def run_current(self):
        """由线程 started 信号调用，确保在工作线程内执行。"""
        if self._pending is None:
            return
        args, self._pending = self._pending, None
        self.process_message(*args)

    def process_message(
        self,
        username: str,
        text: str,
        session_context: Optional[Dict[str, Any]],
        history: List[Dict[str, Any]],
        recent_records: List[Dict[str, Any]],
        api_key: str,
        api_url: str,
        model: str,
        use_local_model: bool,
    ):
        """处理一条用户消息：优先 API，否则本地分析。"""
        if self._finished:
            return
        self._cancelled = False
        self._finished = False

        try:
            if api_key:
                reply = self._call_api(
                    text, session_context, history, recent_records,
                    api_key, api_url, model,
                )
                kind = "advice"
                needs_cloud = False
            else:
                reply, kind, needs_cloud = local_coach_reply_detailed(
                    text,
                    session_context=session_context,
                    recent_records=recent_records,
                    use_model=use_local_model,
                )

            if self._is_cancelled():
                self.finished.emit()
                self._finished = True
                return

            if needs_cloud:
                # 本地无法回答：单独发信号，由界面提示是否转云端
                self.local_fallback_ready.emit(reply)
            else:
                self.message_ready.emit(reply)
                if kind == "report":
                    self.report_ready.emit(reply)
                else:
                    self.advice_ready.emit(reply)
        except requests.exceptions.Timeout:
            self.message_error.emit("教练回复超时，请检查网络连接后重试。")
        except requests.exceptions.ConnectionError:
            self.message_error.emit("网络连接错误，暂时无法连接 AI 服务。")
        except _RequestCancelled:
            self.message_error.emit("请求已取消。")
        except Exception as exc:
            self.message_error.emit(f"教练回复失败：{exc}")
        finally:
            self.finished.emit()
            self._finished = True

    def _call_api(
        self,
        text: str,
        session_context: Optional[Dict[str, Any]],
        history: List[Dict[str, Any]],
        recent_records: List[Dict[str, Any]],
        api_key: str,
        api_url: str,
        model: str,
    ) -> str:
        """调用 OpenAI 兼容 chat completions 接口，返回回复文本。"""
        system = build_system_prompt(session_context, recent_records, RECENT_RECORDS_LIMIT)
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
            "max_tokens": 800,
        }

        api_url = normalize_chat_completions_url(api_url)

        # 请求放到守护线程执行，工作线程轮询取消标记，保证取消能立即返回
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


class AICoachManager(QObject):
    """AI 教练对话管理单例：队列 + 单工作线程，历史持久化。"""

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

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def submit_message(
        self,
        username: str,
        text: str,
        session_context: Optional[Dict[str, Any]] = None,
        force_cloud: bool = False,
        save_user_message: bool = True,
    ) -> int:
        """提交一条用户消息，返回请求 ID（0 表示未受理）。

        force_cloud=True 时，即使未勾选“启用AI智能分析”，只要已保存 API 密钥
        就强制走云端；未配置密钥时返回 0。
        save_user_message=False 用于云端兜底重试，避免重复落库。
        """
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
        recent_records = self._fetch_recent_records(username)

        # 用户消息先落库（会话历史从数据库恢复）
        if save_user_message:
            try:
                Database().add_coach_message(username, "user", text)
            except Exception as exc:
                print(f"AICoachManager: 保存用户消息失败: {exc}")

        request_id = self._next_request_id
        self._next_request_id += 1

        request = {
            "request_id": request_id,
            "username": username,
            "text": text,
            "session_context": session_context or None,
            "history": history,
            "recent_records": recent_records,
            "api_key": "",
            "api_url": "",
            "model": "",
            "force_cloud": force_cloud,
            "use_local_model": True,
        }

        locker = QMutexLocker(self._mutex)
        self._request_queue.append(request)
        self._request_usernames[request_id] = username
        locker.unlock()

        QTimer.singleShot(10, self._process_queue)
        return request_id

    def cancel_request(self, request_id: int):
        """取消指定请求（队列中或进行中）。"""
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
        """返回用户最近的对话记录（正序），供界面展示。"""
        try:
            return Database().fetch_coach_messages(username, limit=limit)
        except Exception as exc:
            print(f"AICoachManager: 加载历史失败: {exc}")
            return []

    def clear_history(self, username: str) -> None:
        """清空指定用户的对话记录。"""
        try:
            Database().clear_coach_messages(username)
        except Exception as exc:
            print(f"AICoachManager: 清空历史失败: {exc}")

    def shutdown(self):
        self._shutting_down = True
        self.cancel_all_requests()

    def cleanup(self):
        """应用退出时清理。"""
        print("AICoachManager: Starting cleanup...")
        for thread, worker in self._active_workers:
            if worker:
                try:
                    worker.cancel()
                    worker.disconnect(self)
                except Exception as exc:
                    print(f"AICoachManager: cleanup worker error: {exc}")
        self._active_workers.clear()

        locker = QMutexLocker(self._mutex)
        self._request_queue.clear()
        self._request_usernames.clear()
        locker.unlock()

        self._cleanup_worker()
        self._shutting_down = True
        self._current_request_id = 0
        self._next_request_id = 1
        print("AICoachManager: Cleanup completed")

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _fetch_history(self, username: str, max_turns: int = HISTORY_LIMIT) -> List[Dict[str, Any]]:
        try:
            rows = Database().fetch_coach_messages(username, limit=max_turns * 2)
            return [
                {"role": row["role"], "content": row["content"]}
                for row in rows
                if row["role"] in ("user", "assistant")
            ]
        except Exception as exc:
            print(f"AICoachManager: 获取对话历史失败: {exc}")
            return []

    def _fetch_recent_records(self, username: str, limit: int = RECENT_RECORDS_LIMIT) -> List[Dict[str, Any]]:
        try:
            return Database().fetch_training_records(username)[:limit]
        except Exception as exc:
            print(f"AICoachManager: 获取训练记录失败: {exc}")
            return []

    def _resolve_config(self, request: Dict[str, Any]):
        """从 GlobalSettings 读取 AI 配置（API 优先，否则本地）。"""
        settings = GlobalSettings()
        key = settings.api_key()
        if key and (settings.ai_enabled() or request.get("force_cloud")):
            request["api_key"] = key
            request["api_url"] = settings.api_url()
            request["model"] = settings.ai_model()
        request["use_local_model"] = settings.local_analysis_enabled()

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
        self._active_worker = AICoachWorker()
        self._active_worker.moveToThread(self._active_thread)

        self._active_worker.set_request(
            request["username"],
            request["text"],
            request["session_context"],
            request["history"],
            request["recent_records"],
            request["api_key"],
            request["api_url"],
            request["model"],
            request["use_local_model"],
        )
        # 直接连接 QObject 槽方法，确保 process_message 在工作线程内执行
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
        request_id = self._current_request_id
        username = self._request_usernames.get(request_id)
        if username:
            try:
                Database().add_coach_message(username, "assistant", content)
            except Exception as exc:
                print(f"AICoachManager: 保存教练回复失败: {exc}")

    def _on_worker_error(self, error: str):
        self.message_error.emit(self._current_request_id, error)
        self.error_occurred.emit(error)

    def _on_worker_finished(self):
        self.request_finished.emit(self._current_request_id)
        # 只请求线程退出事件循环，不在主线程阻塞等待或销毁仍可能运行的线程
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
        """安全清理：线程仍在运行时不阻塞、不销毁，交由 _on_thread_finished。"""
        if self._active_thread and self._active_thread.isRunning():
            return

        if self._active_thread:
            self._active_thread = None
        if self._active_worker:
            self._active_worker.deleteLater()
            self._active_worker = None
        self._current_request_id = 0
