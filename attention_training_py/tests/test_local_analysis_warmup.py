# -*- coding: utf-8 -*-
"""LocalAnalysisEngine 预热：模型齐全时缓存 session 并完成一次推理；模型缺失时安全返回 False。"""

import os
import unittest

from ai.local_analysis import (
    LocalAnalysisEngine,
    RECOMMEND_MODEL_FILE,
    SESSION_MODEL_FILE,
)


class LocalAnalysisWarmupTests(unittest.TestCase):
    def test_warmup_caches_sessions_and_runs(self):
        engine = LocalAnalysisEngine()
        ok = engine.warmup()
        self.assertIsInstance(ok, bool)
        if ok:
            self.assertIn(SESSION_MODEL_FILE, engine._sessions)
            self.assertIn(RECOMMEND_MODEL_FILE, engine._sessions)

    def test_warmup_returns_false_when_models_missing(self):
        engine = LocalAnalysisEngine()
        original = engine._model_path
        try:
            engine._model_path = lambda name: os.path.join("__missing__", name)
            self.assertFalse(engine.warmup())
        finally:
            engine._model_path = original


if __name__ == "__main__":
    unittest.main()
