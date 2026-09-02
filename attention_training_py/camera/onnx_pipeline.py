# -*- coding: utf-8 -*-
"""ONNX 后台推理管线（第三步结构性优化：推理移出摄像头采集线程）。

- onnx_models_for_frame：按帧号给出采样节拍（纯函数，与调优参数解耦）。
- models_to_run：结合启用开关与“是否检测到脸”，决定该帧实际执行哪些模型。
- LatestMailbox：单槽 latest-wins 邮箱，采集线程发布最新帧，积压帧直接丢弃。
- OnnxTaskWorker：后台线程消费邮箱，按节拍调用 runner 执行推理；
  结果由 runner 写回缓存，采集线程只读缓存，不再被模型延迟阻塞。

采样节拍（帧，2026-08-30 调优后）：YuNet 6、OCEC 2、头部姿态/视线 8，
视线相位 5 与姿态（相位 1）错开，两个重模型永不落在同一帧。
"""

import threading
import time

ONNX_YUNET_INTERVAL = 6
ONNX_BLINK_INTERVAL = 2
ONNX_HEAD_POSE_INTERVAL = 8
ONNX_GAZE_INTERVAL = 8
ONNX_GAZE_PHASE = 5

MODEL_ORDER = ("face", "head_pose", "gaze", "blink")


def onnx_models_for_frame(frame_index):
    """返回当前帧按采样节拍应推理的模型集合（不含启用开关）。"""
    models = set()
    if frame_index % ONNX_YUNET_INTERVAL == 1:
        models.add("face")
    if frame_index % ONNX_BLINK_INTERVAL == 0:
        models.add("blink")
    if frame_index % ONNX_HEAD_POSE_INTERVAL == 1:
        models.add("head_pose")
    if frame_index % ONNX_GAZE_INTERVAL == ONNX_GAZE_PHASE:
        models.add("gaze")
    return models


def models_to_run(frame_index, landmarks_present, enabled):
    """返回该帧实际要执行的模型列表（固定顺序）。

    未检测到脸时只跑人脸检测（YuNet），眨眼/姿态/视线需要面部关键点。
    """
    plan = onnx_models_for_frame(frame_index) & set(enabled)
    if not landmarks_present:
        plan.discard("blink")
        plan.discard("head_pose")
        plan.discard("gaze")
    return [model for model in MODEL_ORDER if model in plan]


class LatestMailbox:
    """单槽 latest-wins 邮箱：只保留最新任务，积压任务被覆盖丢弃。"""

    def __init__(self):
        self._cv = threading.Condition()
        self._item = None

    def publish(self, item):
        with self._cv:
            self._item = item
            self._cv.notify()

    def take(self, timeout):
        """取走最新任务；超时返回 None。"""
        with self._cv:
            deadline = time.monotonic() + timeout
            while self._item is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cv.wait(remaining)
            item = self._item
            self._item = None
            return item


class OnnxTaskWorker:
    """后台 ONNX 推理线程：latest-wins 邮箱 + 按采样节拍分派。

    runner(model, frame, landmarks, w, h, frame_index) 由调用方提供，
    负责执行具体模型推理并把结果写入缓存。
    """

    def __init__(self, enabled, mailbox, stop_event, runner):
        self._enabled = set(enabled)
        self._mailbox = mailbox
        self._stop = stop_event
        self._runner = runner

    def run(self):
        while not self._stop.is_set():
            task = self._mailbox.take(timeout=0.1)
            if task is None:
                continue
            self.run_one(task)

    def run_one(self, task):
        frame_index, frame, landmarks, w, h = task
        for model in models_to_run(frame_index, landmarks is not None, self._enabled):
            self._runner(model, frame, landmarks, w, h, frame_index)
