# -*- coding: utf-8 -*-
"""导出/导入 UI 接线回归测试（仅静态 AST 检查，无需 Qt）。

防止"代码使用了 os 但模块顶部没有 import os"这类 NameError 回归。
"""

import ast
import pathlib
import unittest


PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent

_UI_MODULES = (
    "ui/training_record_dialog.py",
    "ui/teacher_report_dialog.py",
)


class UiImportSanityTests(unittest.TestCase):
    def test_ui_modules_using_os_import_it(self):
        for rel in _UI_MODULES:
            src = (PROJECT_DIR / rel).read_text(encoding="utf-8-sig")
            tree = ast.parse(src, filename=rel)

            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])

            uses_os = any(
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
                for node in ast.walk(tree)
            )
            if uses_os:
                self.assertIn(
                    "os",
                    imported,
                    f"{rel} 使用了 os 但模块顶部未导入 os",
                )


if __name__ == "__main__":
    unittest.main()
