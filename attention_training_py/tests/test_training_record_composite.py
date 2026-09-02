# -*- coding: utf-8 -*-
"""TrainingRecord 对象的 composite_score 序列化往返测试。"""

import unittest

from core.settings import TrainingRecord


class TrainingRecordCompositeTests(unittest.TestCase):
    def test_default_is_minus_one_unknown(self):
        self.assertEqual(TrainingRecord().composite_score, -1)

    def test_roundtrip_preserves_composite_score(self):
        record = TrainingRecord()
        record.composite_score = 72
        restored = TrainingRecord.from_dict(record.to_dict())
        self.assertEqual(restored.composite_score, 72)


if __name__ == "__main__":
    unittest.main()
