# -*- coding: utf-8 -*-
"""回归测试：ONNX 四个模型每次实际推理都会向 time_consumed.db 写一行计时。

会破坏这些测试的变更：去掉计时、改错模型名、漏传 frame_index/frame_size、
失败推理不落库。
"""

import os
import sqlite3
import tempfile
import unittest

import numpy as np

import camera.onnx_vision as ov
from core.time_tracker import DB_FILENAME, TimeTracker


class _FakeInput:
    name = "input"
    shape = (1, 3, 224, 224)


class _FakeSession:
    def get_inputs(self):
        return [_FakeInput()]

    def get_providers(self):
        return ["CPUExecutionProvider"]


class OnnxTimingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tracker = TimeTracker(db_path=os.path.join(self._tmp.name, DB_FILENAME))
        self.engine = ov.ONNXVisionEngine()
        self._orig_get_tracker = ov.get_tracker
        ov.get_tracker = lambda: self.tracker

    def tearDown(self):
        ov.get_tracker = self._orig_get_tracker
        self.tracker.close()
        self._tmp.cleanup()

    def _rows(self):
        conn = sqlite3.connect(self.tracker._db_path)
        try:
            cur = conn.execute(
                "SELECT model, frame, duration_ms, ok, width, height "
                "FROM model_timing ORDER BY id"
            )
            return cur.fetchall()
        finally:
            conn.close()

    def _yunet_outputs(self):
        per_stride = {}
        for stride in ov.YUNET_STRIDES:
            n = ov.YUNET_INPUT_W // stride
            num = n * n
            cls = np.zeros(num, dtype=np.float32)
            obj = np.zeros(num, dtype=np.float32)
            bbox = np.zeros((num, 4), dtype=np.float32)
            kps = np.zeros((num, 10), dtype=np.float32)
            idx = 1 * n + 1
            cls[idx] = 1.0
            obj[idx] = 1.0
            bbox[idx, 2] = float(np.log(0.5 / stride))
            bbox[idx, 3] = float(np.log(0.5 / stride))
            per_stride[stride] = (cls, obj, bbox, kps)
        # YUNET_OUTPUT_NAMES order: all cls, then all obj, then bbox, then kps
        outs = []
        for stride in ov.YUNET_STRIDES:
            outs.append(per_stride[stride][0])
        for stride in ov.YUNET_STRIDES:
            outs.append(per_stride[stride][1])
        for stride in ov.YUNET_STRIDES:
            outs.append(per_stride[stride][2])
        for stride in ov.YUNET_STRIDES:
            outs.append(per_stride[stride][3])
        return outs

    def test_detect_face_records_yunet_timing(self):
        self.engine._init_yunet = lambda: _FakeSession()
        self.engine._run = lambda path, feed, output_names=None: self._yunet_outputs()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = self.engine.detect_face(frame, frame_index=7)
        self.assertIsNotNone(result)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        model, frame_no, duration, ok, width, height = rows[0]
        self.assertEqual(model, "yunet")
        self.assertEqual(frame_no, 7)
        self.assertGreaterEqual(duration, 0.0)
        self.assertEqual(ok, 1)
        self.assertEqual((width, height), (640, 480))

    def test_classify_eyes_records_ocec_timing(self):
        self.engine._session = lambda path: _FakeSession()
        self.engine._run = lambda path, feed, output_names=None: [
            np.array([0.9, 0.1], dtype=np.float32)
        ]
        crop = np.zeros((24, 40, 3), dtype=np.uint8)
        p_left, p_right = self.engine.classify_eyes(
            crop, crop, frame_index=3, frame_size=(640, 480)
        )
        self.assertAlmostEqual(p_left, 0.9, places=5)
        self.assertAlmostEqual(p_right, 0.1, places=5)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        model, frame_no, duration, ok, width, height = rows[0]
        self.assertEqual(model, "ocec")
        self.assertEqual(frame_no, 3)
        self.assertGreaterEqual(duration, 0.0)
        self.assertEqual(ok, 1)
        self.assertEqual((width, height), (640, 480))

    def test_estimate_head_pose_records_timing(self):
        self.engine._session = lambda path: _FakeSession()
        self.engine._run = lambda path, feed, output_names=None: [
            np.eye(3, dtype=np.float32)
        ]
        crop = np.zeros((224, 224, 3), dtype=np.uint8)
        pose = self.engine.estimate_head_pose(
            crop, frame_index=11, frame_size=(640, 480)
        )
        self.assertIsNotNone(pose)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        model, frame_no, duration, ok, width, height = rows[0]
        self.assertEqual(model, "head_pose")
        self.assertEqual(frame_no, 11)
        self.assertGreaterEqual(duration, 0.0)
        self.assertEqual(ok, 1)
        self.assertEqual((width, height), (640, 480))

    def test_estimate_gaze_records_timing(self):
        self.engine._session = lambda path: _FakeSession()
        zeros = np.zeros(90, dtype=np.float32)
        self.engine._run = lambda path, feed, output_names=None: [zeros.copy(), zeros.copy()]
        crop = np.zeros((224, 224, 3), dtype=np.uint8)
        gaze = self.engine.estimate_gaze(crop, frame_index=13, frame_size=(640, 480))
        self.assertIsNotNone(gaze)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        model, frame_no, duration, ok, width, height = rows[0]
        self.assertEqual(model, "gaze")
        self.assertEqual(frame_no, 13)
        self.assertGreaterEqual(duration, 0.0)
        self.assertEqual(ok, 1)
        self.assertEqual((width, height), (640, 480))

    def test_failed_yunet_inference_records_ok_zero(self):
        self.engine._init_yunet = lambda: _FakeSession()
        self.engine._run = lambda path, feed, output_names=None: None
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = self.engine.detect_face(frame, frame_index=9)
        self.assertIsNone(result)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        model, frame_no, duration, ok, width, height = rows[0]
        self.assertEqual(model, "yunet")
        self.assertEqual(frame_no, 9)
        self.assertGreaterEqual(duration, 0.0)
        self.assertEqual(ok, 0)
        self.assertEqual((width, height), (640, 480))


if __name__ == "__main__":
    unittest.main()
