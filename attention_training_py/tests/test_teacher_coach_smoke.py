# -*- coding: utf-8 -*-
"""教师端 AI 助教模块导入冒烟测试（需 QT_QPA_PLATFORM=offscreen）。"""

import unittest


class TeacherCoachImportSmokeTests(unittest.TestCase):
    def test_imports_ok(self):
        import ai.teacher_coach
        import ai.teacher_coach_logic
        import ai.teacher_report_logic
        import ui.teacher_coach_dialog
        import ui.main_window
        import ui.teacher_report_dialog
        self.assertTrue(ai.teacher_coach.TeacherCoachManager)
        self.assertTrue(ui.teacher_coach_dialog.TeacherCoachDialog)


if __name__ == "__main__":
    unittest.main()
