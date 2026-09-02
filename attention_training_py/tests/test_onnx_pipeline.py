# -*- coding: utf-8 -*-
"""回归测试：ONNX 后台推理管线（latest-wins 邮箱 + 按采样节拍分派）。

会破坏这些测试的变更：把推理留在采集线程（没有邮箱/worker 分派）、
latest-wins 语义丢失（积压任务被逐个处理）、无脸时仍跑眨眼/姿态/视线。
"""

import queue
import threading
import time
import unittest

from camera.onnx_pipeline import (
    LatestMailbox,
    OnnxTaskWorker,
    models_to_run,
)

ALL = {"face", "blink", "head_pose", "gaze"}


class ModelsToRunTest(unittest.TestCase):
    def test_no_face_runs_only_face_detection(self):
        self.assertEqual(models_to_run(1, False, ALL), ["face"])

    def test_no_face_never_runs_blink_head_pose_or_gaze(self):
        for frame in (1, 2, 5, 9, 13, 17, 21):
            self.assertTrue(set(models_to_run(frame, False, ALL)) <= {"face"})

    def test_with_face_returns_scheduled_models_in_order(self):
        self.assertEqual(models_to_run(13, True, ALL), ["face", "gaze"])
        self.assertEqual(models_to_run(5, True, ALL), ["gaze"])
        self.assertEqual(models_to_run(2, True, ALL), ["blink"])
        self.assertEqual(models_to_run(1, True, ALL), ["face", "head_pose"])

    def test_disabled_models_are_excluded(self):
        enabled = {"face", "blink"}
        self.assertEqual(models_to_run(13, True, enabled), ["face"])


class LatestMailboxTest(unittest.TestCase):
    def test_keeps_only_latest_task(self):
        box = LatestMailbox()
        box.publish(("t1",))
        box.publish(("t2",))
        box.publish(("t3",))
        self.assertEqual(box.take(timeout=0.2), ("t3",))
        self.assertIsNone(box.take(timeout=0.05))


class OnnxTaskWorkerTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.runner = (
            lambda model, frame, landmarks, w, h, frame_index: self.calls.append(
                (model, frame_index, landmarks is not None)
            )
        )

    def test_run_one_dispatches_scheduled_models_with_frame_index(self):
        worker = OnnxTaskWorker(
            enabled=ALL,
            mailbox=LatestMailbox(),
            stop_event=threading.Event(),
            runner=self.runner,
        )
        worker.run_one((13, "frame", [object()], 640, 480))
        self.assertEqual(self.calls, [("face", 13, True), ("gaze", 13, True)])

    def test_run_one_without_face_dispatches_face_only(self):
        worker = OnnxTaskWorker(
            enabled=ALL,
            mailbox=LatestMailbox(),
            stop_event=threading.Event(),
            runner=self.runner,
        )
        worker.run_one((1, "frame", None, 640, 480))
        self.assertEqual(self.calls, [("face", 1, False)])

    def test_loop_processes_task_then_stops(self):
        done = queue.Queue()

        def runner(model, frame, landmarks, w, h, frame_index):
            done.put(model)

        stop = threading.Event()
        box = LatestMailbox()
        worker = OnnxTaskWorker(
            enabled=ALL, mailbox=box, stop_event=stop, runner=runner
        )
        thread = threading.Thread(target=worker.run, daemon=True)
        thread.start()
        try:
            box.publish((1, "frame", [object()], 640, 480))
            got = []
            deadline = time.monotonic() + 2.0
            while len(got) < 2 and time.monotonic() < deadline:
                try:
                    got.append(done.get(timeout=0.2))
                except queue.Empty:
                    pass
            self.assertEqual(got, ["face", "head_pose"])
        finally:
            stop.set()
            thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
