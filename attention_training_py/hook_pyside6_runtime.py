# -*- coding: utf-8 -*-
import os
import sys

def setup_qt_environment():
    """设置 Qt 环境变量"""
    if getattr(sys, 'frozen', False):
        # 打包后的环境
        bundle_dir = sys._MEIPASS

        # 添加 PySide6 路径
        pyside6_path = os.path.join(bundle_dir, 'PySide6')
        if os.path.exists(pyside6_path):
            os.environ['PATH'] = pyside6_path + os.pathsep + os.environ.get('PATH', '')

        # 添加 plugins 路径
        plugins_path = os.path.join(bundle_dir, 'PySide6', 'plugins')
        if os.path.exists(plugins_path):
            os.environ['PATH'] = plugins_path + os.pathsep + os.environ.get('PATH', '')

        # 设置 Qt 插件路径
        os.environ['QT_PLUGIN_PATH'] = plugins_path

        # 禁用沙箱（如果使用 WebEngine）
        os.environ['QTWEBENGINE_DISABLE_SANDBOX'] = '1'

        print(f"[Runtime Hook] Bundle dir: {bundle_dir}")
        print(f"[Runtime Hook] PySide6 path exists: {os.path.exists(pyside6_path)}")
        print(f"[Runtime Hook] Plugins path exists: {os.path.exists(plugins_path)}")
        print(f"[Runtime Hook] QT_PLUGIN_PATH: {os.environ.get('QT_PLUGIN_PATH', 'Not set')}")

# 在导入 Qt 之前执行
setup_qt_environment()
