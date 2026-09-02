# ai/ai_analysis_manager.py
from queue import Queue
from typing import Optional, Dict, Any
from PySide6.QtCore import QObject, Signal, QThread, QMutex, QMutexLocker, QMetaObject, Qt, QTimer, Slot
import json
import requests
from .ai_thread_worker import AIThreadWorker


class AIAnalysisManager(QObject):
    analysis_ready = Signal(int, str)
    analysis_error = Signal(int, str)

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        super().__init__()
        self._initialized = True

        self._next_request_id = 1
        self._shutting_down = False
        self._active_worker = None
        self._active_thread = None
        self._current_request_id = 0
        self._request_queue = []
        self._mutex = QMutex()
        self._active_workers = []

    def submit_analysis(self, avg_attention: int, total_blinks: int, max_consecutive_hits: int,
                        game_score: int, game_mode: str, duration_minutes: int,
                        api_key: str, api_url: str, model: str,
                        avg_gaze_score: int = 0, avg_gaze_distance: float = 0.0,
                        difficulty: str = "normal", face_detected: Optional[bool] = None) -> int:
        """提交分析请求"""
        if self._shutting_down:
            return 0

        request_id = self._next_request_id
        self._next_request_id += 1

        request = {
            'request_id': request_id,
            'avg_attention': avg_attention,
            'total_blinks': total_blinks,
            'max_consecutive_hits': max_consecutive_hits,
            'game_score': game_score,
            'game_mode': game_mode,
            'duration_minutes': duration_minutes,
            'api_key': api_key,
            'api_url': api_url,
            'model': model,
            'avg_gaze_score': avg_gaze_score,
            'avg_gaze_distance': avg_gaze_distance,
            'difficulty': difficulty,
            'face_detected': face_detected
        }

        locker = QMutexLocker(self._mutex)
        self._request_queue.append(request)
        locker.unlock()

        # 使用 QTimer 延迟处理，避免线程问题
        QTimer.singleShot(10, self._process_queue)

        return request_id

    def cancel_request(self, request_id: int):
        """取消请求"""
        locker = QMutexLocker(self._mutex)
        self._request_queue = [r for r in self._request_queue if r['request_id'] != request_id]
        locker.unlock()

        if self._current_request_id == request_id and self._active_worker:
            self._active_worker.cancel()

    def cancel_all_requests(self):
        """取消所有请求"""
        locker = QMutexLocker(self._mutex)
        self._request_queue.clear()
        locker.unlock()

        for thread, worker in self._active_workers:
            if worker:
                worker.cancel()
                worker.disconnect(self)

        self._cleanup_worker()

    @classmethod
    def instance(cls):
        return cls()

    def shutdown(self):
        """关闭管理器，拒绝新请求"""
        self._shutting_down = True
        self.cancel_all_requests()

    @Slot()
    def _process_queue(self):
        """处理队列中的下一个请求"""
        if self._shutting_down:
            return

        if self._active_worker and self._active_thread and self._active_thread.isRunning():
            return

        self._cleanup_worker()

        locker = QMutexLocker(self._mutex)
        if not self._request_queue:
            return

        request = self._request_queue.pop(0)
        self._current_request_id = request['request_id']
        locker.unlock()

        # 创建工作线程
        self._active_thread = QThread()
        self._active_worker = AIThreadWorker()
        self._active_worker.moveToThread(self._active_thread)

        # 先存参数，再连接 QObject 槽方法，确保在工作线程内执行
        self._active_worker.set_request(request)
        self._active_thread.started.connect(self._active_worker.run_current)

        self._active_worker.analysis_ready.connect(self._on_worker_ready)
        self._active_worker.analysis_error.connect(self._on_worker_error)
        self._active_worker.finished.connect(self._on_worker_finished)

        # 线程结束时清理
        self._active_thread.finished.connect(self._on_thread_finished)

        # 记录活跃线程
        locker = QMutexLocker(self._mutex)
        self._active_workers.append((self._active_thread, self._active_worker))
        locker.unlock()

        self._active_thread.start()

    def _on_thread_finished(self):
        """线程结束时清理"""
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

    def _on_worker_finished(self):
        # 只请求线程退出事件循环，不在主线程阻塞等待或销毁仍可能运行的线程
        if self._active_thread and self._active_thread.isRunning():
            self._active_thread.quit()

    def _on_worker_ready(self, analysis: str):
        self.analysis_ready.emit(self._current_request_id, analysis)

    def _on_worker_error(self, error: str):
        self.analysis_error.emit(self._current_request_id, error)

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

    def cleanup(self):
        """清理所有资源"""
        print("AIAnalysisManager: Starting cleanup...")

        # 取消所有活跃请求
        for thread, worker in self._active_workers:
            if worker:
                try:
                    worker.cancel()
                    worker.disconnect(self)
                except Exception as e:
                    print(f"Cleanup worker error: {e}")

        self._active_workers.clear()

        locker = QMutexLocker(self._mutex)
        self._request_queue.clear()
        locker.unlock()

        # 清理当前worker
        self._cleanup_worker()

        self._shutting_down = True
        self._current_request_id = 0
        self._next_request_id = 1

        print("AIAnalysisManager: Cleanup completed")

    def cancel_all_requests_and_wait(self):
        """取消所有请求并等待完成"""
        print("AIAnalysisManager: Cancelling all requests...")

        self.cancel_all_requests()

        # 等待所有线程结束
        for thread, worker in self._active_workers:
            if thread and thread.isRunning():
                thread.quit()
                if not thread.wait(1000):
                    print("Thread did not stop gracefully, forcing termination")
                    try:
                        thread.terminate()
                        thread.wait()
                    except:
                        pass

        self._active_workers.clear()
        self._cleanup_worker()

        print("AIAnalysisManager: All requests cancelled")