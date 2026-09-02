# -*- coding: utf-8 -*-
"""回归测试：CameraWorker.__init__ 必须完整执行 ONNX/摄像头初始化语句，
face_seen 属性必须位于 __init__ 之后且不能吞并初始化语句。

此测试仅用 ast 解析源码，不导入 PySide6/cv2/mediapipe，可独立运行。
"""

import ast
import pathlib
import unittest


_SRC_PATH = pathlib.Path(__file__).resolve().parent.parent / "camera" / "camera_worker.py"


def _camera_class():
    source = _SRC_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "CameraWorker"
    )


class CameraWorkerStructureTests(unittest.TestCase):
    def setUp(self):
        self.source = _SRC_PATH.read_text(encoding="utf-8")
        cls = _camera_class()
        self.init = next(
            node for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        self.face_seen = next(
            node for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "face_seen"
        )

    def _segment(self, node) -> str:
        return ast.get_source_segment(self.source, node) or ""

    def test_init_contains_onnx_lock_and_ready_print(self):
        init_src = self._segment(self.init)
        self.assertIn("self._onnx_lock = threading.Lock()", init_src)
        self.assertIn('print("CameraWorker initialized")', init_src)

    def test_face_seen_does_not_swallow_init_statements(self):
        face_src = self._segment(self.face_seen)
        self.assertNotIn("self._onnx_lock", face_src)
        self.assertNotIn("self._onnx_engine", face_src)
        self.assertNotIn("CameraWorker initialized", face_src)

    def test_face_seen_is_class_method_after_init(self):
        self.assertGreater(self.face_seen.lineno, self.init.end_lineno)


if __name__ == "__main__":
    unittest.main()
