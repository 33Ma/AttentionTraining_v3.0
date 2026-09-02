# -*- coding: utf-8 -*-
"""回归测试：ONNX 模型按采样节拍（帧）运行。

会破坏这些测试的变更：把节拍改回旧值（YuNet 每4帧、OCEC 每帧、
姿态/视线每6帧）、或把错帧逻辑改错导致两个重模型同帧运行。
"""

import unittest

from camera.onnx_pipeline import onnx_models_for_frame


class OnnxScheduleTest(unittest.TestCase):
    def test_face_every_six_frames(self):
        frames = [f for f in range(1, 25) if "face" in onnx_models_for_frame(f)]
        self.assertEqual(frames, [1, 7, 13, 19])

    def test_blink_every_two_frames(self):
        frames = [f for f in range(1, 25) if "blink" in onnx_models_for_frame(f)]
        self.assertEqual(frames, [2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24])

    def test_head_pose_every_eight_frames(self):
        frames = [f for f in range(1, 25) if "head_pose" in onnx_models_for_frame(f)]
        self.assertEqual(frames, [1, 9, 17])

    def test_gaze_every_eight_frames_staggered_from_head_pose(self):
        frames = [f for f in range(1, 25) if "gaze" in onnx_models_for_frame(f)]
        self.assertEqual(frames, [5, 13, 21])

    def test_frame_13_runs_face_and_gaze(self):
        self.assertEqual(onnx_models_for_frame(13), {"face", "gaze"})

    def test_blink_runs_alone_on_even_frame(self):
        self.assertEqual(onnx_models_for_frame(2), {"blink"})


if __name__ == "__main__":
    unittest.main()
