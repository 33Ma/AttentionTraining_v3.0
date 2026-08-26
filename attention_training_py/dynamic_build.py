#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""注意力训练系统 - 动态封装打包脚本（PyInstaller）。

工作流程：
1. 动态扫描项目源码，自动收集全部业务模块（作为隐藏导入）；
2. 检查并自动安装缺失的构建/运行依赖；
3. 生成 PyInstaller 命令并执行打包（默认 onedir、无控制台）；
4. 打包完成后验证产物并输出关键信息。

用法示例：
    python dynamic_build.py                # 默认：onedir、无控制台
    python dynamic_build.py --onefile      # 单文件模式
    python dynamic_build.py --console      # 保留控制台（调试用）
    python dynamic_build.py --name MyApp   # 自定义程序名
    python dynamic_build.py --clean        # 打包前清理 build/dist
"""

import argparse
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_APP_NAME = "AttentionTrainingApp"
ENTRY_SCRIPT = "main.py"
ICON_FILE = "app.ico"
QT_CONF = "qt.conf"
RUNTIME_HOOK = "hook_pyside6_runtime.py"

# 动态收集模块时排除的目录
EXCLUDE_DIRS = {
    "__pycache__", ".git", ".git.bak_v2", ".idea", ".vscode", ".qtcreator",
    "build", "dist", "venv", ".venv", "env", "users", "node_modules",
    # PyInstaller 钩子目录：内部文件（如 hook-mediapipe.py）无需作为业务模块打包
    "hooks",
}

# 不参与打包的顶层脚本（入口/调试/构建工具/旧版独立文件）
EXCLUDE_FILES = {
    "main.py", "run.py", "debug_train.py", "build.py", "dynamic_build.py",
    "hook_pyside6_runtime.py", "pyproject.toml", "setup.py", "launcher.py",
    "main_window.py", "training_window.py", "camera_worker.py",
}

# 运行时需要显式引入的第三方库（部分通过动态属性访问，静态分析无法发现）
BASE_HIDDEN_IMPORTS = [
    "shiboken6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtNetwork",
    "PySide6.QtCharts",
    "cv2",
    "numpy",
    "mediapipe",
    "requests",
]

# 打包/运行所需的第三方发行包（pip 名）
RUNTIME_DEPENDENCIES = [
    "PySide6",
    "opencv-python",
    "mediapipe",
    "numpy",
    "requests",
]

# pip 发行名 -> 实际 import 名（大小写敏感检查）
IMPORT_NAMES = {
    "pyinstaller": "PyInstaller",
    "opencv-python": "cv2",
    "pillow": "PIL",
}


def collect_project_modules() -> list:
    """动态收集项目内的业务模块（相对导入名，如 core.settings）。"""
    modules = []
    for root, dirs, files in os.walk(PROJECT_DIR):
        rel_root = Path(root).relative_to(PROJECT_DIR)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        if any(part in EXCLUDE_DIRS for part in rel_root.parts):
            continue
        for name in sorted(files):
            if not name.endswith(".py") or name in EXCLUDE_FILES:
                continue
            rel_file = rel_root / name
            module = str(rel_file.with_suffix("")).replace(os.sep, ".")
            if module.startswith("."):
                module = module[1:]
            if module and not module.split(".")[-1].startswith("_"):
                modules.append(module)
    return sorted(set(modules))


def _module_available(package_name: str) -> bool:
    import_name = IMPORT_NAMES.get(package_name, package_name.replace("-", "_"))
    return importlib.util.find_spec(import_name) is not None


def ensure_dependencies() -> None:
    """检查并安装缺失的构建/运行依赖。"""
    packages = ["pyinstaller"] + RUNTIME_DEPENDENCIES
    to_install = [pkg for pkg in packages if not _module_available(pkg)]
    if not to_install:
        print("依赖检查通过：PyInstaller 与全部运行依赖均已安装。")
        return
    print("以下依赖缺失，正在安装：", ", ".join(to_install))
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install"] + to_install
    )


def clean_artifacts() -> None:
    """清理旧的构建产物。"""
    for folder in ("build", "dist"):
        path = PROJECT_DIR / folder
        if path.exists():
            print(f"清理 {path} ...")
            shutil.rmtree(path)
    for spec in PROJECT_DIR.glob("*.spec"):
        print(f"删除 {spec} ...")
        spec.unlink()


def build(args) -> bool:
    print("=" * 64)
    print(f"动态封装打包 | 项目：{PROJECT_DIR.name}")
    print(
        "Python: {} | 平台: {} {}".format(
            sys.version.split()[0], platform.system(), platform.machine()
        )
    )
    print("=" * 64)

    ensure_dependencies()

    if args.clean:
        clean_artifacts()

    modules = collect_project_modules()
    print(f"\n动态收集到 {len(modules)} 个业务模块：")
    for module in modules:
        print(f"  - {module}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level=INFO",
        "--name", args.name,
        "--onedir" if not args.onefile else "--onefile",
        "--console" if args.console else "--windowed",
        "--paths", str(PROJECT_DIR),
        str(PROJECT_DIR / ENTRY_SCRIPT),
    ]

    # 数据文件：qt.conf（Qt 插件路径）
    for data in (QT_CONF,):
        if (PROJECT_DIR / data).exists():
            cmd += ["--add-data", f"{PROJECT_DIR / data}{os.pathsep}."]

    # 图标
    if args.icon and (PROJECT_DIR / args.icon).exists():
        cmd += ["--icon", str(PROJECT_DIR / args.icon)]

    # 运行时钩子（设置 Qt 环境变量）
    if (PROJECT_DIR / RUNTIME_HOOK).exists():
        cmd += ["--runtime-hook", str(PROJECT_DIR / RUNTIME_HOOK)]

    # 隐藏导入：业务模块 + 第三方库
    # Project-specific PyInstaller hooks (lean mediapipe hook)
    hooks_dir = PROJECT_DIR / "hooks"
    if hooks_dir.exists():
        cmd += ["--additional-hooks-dir", str(hooks_dir)]

    for module in sorted(set(BASE_HIDDEN_IMPORTS + modules)):
        cmd += ["--hidden-import", module]

    # mediapipe models/data are collected by hooks/hook-mediapipe.py

    # 排除无用标准库，减小体积
    for module in ("tkinter", "idlelib", "pydoc", "lib2to3"):
        cmd += ["--exclude-module", module]

    print("\n执行 PyInstaller 打包命令：")
    print(" ".join(cmd), "\n")
    result = subprocess.run(cmd, cwd=str(PROJECT_DIR))
    if result.returncode != 0:
        print("\n打包失败，请检查上方日志。")
        return False

    if args.onefile:
        exe = PROJECT_DIR / "dist" / f"{args.name}.exe"
    else:
        exe = PROJECT_DIR / "dist" / args.name / f"{args.name}.exe"

    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 64)
        print(f"打包成功：{exe}")
        print(f"程序大小：{size_mb:.1f} MB")
        print("=" * 64)
        return True

    print(f"\n未找到预期产物：{exe}")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="注意力训练系统动态封装打包工具"
    )
    parser.add_argument(
        "--name", default=DEFAULT_APP_NAME, help="程序/输出目录名"
    )
    parser.add_argument(
        "--onefile", action="store_true", help="单文件模式（默认 onedir）"
    )
    parser.add_argument(
        "--console", action="store_true", help="保留控制台窗口（调试用）"
    )
    parser.add_argument(
        "--clean", action="store_true", help="打包前清理 build/dist"
    )
    parser.add_argument(
        "--no-icon", action="store_true", help="不使用图标"
    )
    args = parser.parse_args()
    args.icon = "" if args.no_icon else ICON_FILE

    if not build(args):
        sys.exit(1)


if __name__ == "__main__":
    main()
