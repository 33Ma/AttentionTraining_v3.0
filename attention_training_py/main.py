# main.py - 程序入口

import os
import sys
import signal
import traceback
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow
from ui.login_dialog import LoginDialog
from core.user_manager import UserManager
from core.settings import GlobalSettings


def exception_hook(exc_type, exc_value, exc_traceback):
    """全局异常钩子"""
    print(f"Uncaught exception: {exc_type.__name__}: {exc_value}")
    traceback.print_exc()


def cleanup_resources():
    """程序退出时清理资源"""
    print("Cleaning up resources...")
    try:
        from ai.ai_analysis_manager import AIAnalysisManager
        AIAnalysisManager.instance().cleanup()
    except Exception as e:
        print(f"Cleanup AI manager error: {e}")

    try:
        from ai.ai_coach import AICoachManager
        AICoachManager.instance().cleanup()
    except Exception as e:
        print(f"Cleanup AI coach manager error: {e}")
    try:
        from ai.teacher_coach import TeacherCoachManager
        TeacherCoachManager.instance().cleanup()
    except Exception as e:
        print(f"Cleanup teacher coach manager error: {e}")

    try:
        # 保存所有设置
        GlobalSettings().save_to_file()
    except Exception as e:
        print(f"Save settings error: {e}")

    print("Cleanup completed")


def detect_ui_scale() -> float:
    """按主屏逻辑分辨率计算全局界面缩放比例（以 1920x1080 为基准）。

    覆盖市面上常见笔记本/显示器逻辑分辨率：
      - 16 英寸 2560x1600 @125% → 2048x1280，比例 1.0（保持原设计）
      - 15.6 英寸 1920x1080 @100% → 1920x1080，比例 1.0
      - 14 英寸 1920x1080 @125% → 1536x864，约 0.80
      - 14 英寸 1920x1080 @150% → 1280x720，约 0.67
      - 14 英寸 2880x1800 @200% → 1440x900，约 0.75（宽度受限）
      - 13.3 英寸 2560x1600 @200% → 1280x800，约 0.67（宽度受限）
      - 老款 1366x768 @100% → 1366x768，约 0.71
    比例下限 0.6，避免极端小屏下界面过小无法操作；计算失败时返回 1.0。
    """
    try:
        user32 = ctypes.windll.user32

        class DEVMODE(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", ctypes.c_wchar * 32),
                ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD),
                ("dmDriverExtra", wintypes.WORD),
                ("dmFields", ctypes.c_uint),
                ("dmPosition", ctypes.c_long * 2),
                ("dmDisplayOrientation", ctypes.c_uint),
                ("dmDisplayFixedOutput", ctypes.c_uint),
                ("dmColor", ctypes.c_short),
                ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short),
                ("dmFormName", ctypes.c_wchar * 32),
                ("dmLogPixels", wintypes.WORD),
                ("dmBitsPerPel", ctypes.c_uint),
                ("dmPelsWidth", ctypes.c_uint),
                ("dmPelsHeight", ctypes.c_uint),
                ("dmDisplayFlags", ctypes.c_uint),
                ("dmDisplayFrequency", ctypes.c_uint),
                ("dmICMMethod", ctypes.c_uint),
                ("dmICMIntent", ctypes.c_uint),
                ("dmMediaType", ctypes.c_uint),
                ("dmDitherType", ctypes.c_uint),
                ("dmReserved1", ctypes.c_uint),
                ("dmReserved2", ctypes.c_uint),
                ("dmPanningWidth", ctypes.c_uint),
                ("dmPanningHeight", ctypes.c_uint),
            ]

        dm = DEVMODE()
        dm.dmSize = ctypes.sizeof(DEVMODE)
        if not user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):
            return 1.0

        physical_w = float(dm.dmPelsWidth)
        physical_h = float(dm.dmPelsHeight)
        log_pixels = float(dm.dmLogPixels or 96)
        if physical_w <= 0 or physical_h <= 0 or log_pixels <= 0:
            return 1.0

        dpr = log_pixels / 96.0
        logical_w = physical_w / dpr
        logical_h = physical_h / dpr
        scale = min(1.0, logical_w / 1920.0, logical_h / 1080.0)
        return max(0.6, scale)
    except Exception:
        return 1.0


def main():
    # 设置异常钩子
    sys.excepthook = exception_hook

    # 屏幕兼容：小屏（如 14 英寸笔记本）按主屏逻辑分辨率等比缩放整个界面，
    # 使所有窗口完整落在屏幕内、内容不被裁切；16 英寸及以上大屏不受影响。
    scale = detect_ui_scale()
    if scale < 1.0:
        os.environ["QT_SCALE_FACTOR"] = f"{scale:.4f}"
    print(f"UI scale factor: {scale:.3f}")

    app = QApplication(sys.argv)
    app.setApplicationName("游戏化注意力训练系统")

    # 设置退出时清理
    app.aboutToQuit.connect(cleanup_resources)

    # 处理信号
    def signal_handler(signum, frame):
        print("Received signal, exiting...")
        cleanup_resources()
        QApplication.quit()

    signal.signal(signal.SIGINT, signal_handler)

    try:
        # 显示登录对话框
        login_dlg = LoginDialog()
        if login_dlg.exec() == LoginDialog.Accepted and login_dlg.is_logged_in():
            # 创建主窗口
            window = MainWindow()
            window.show()

            # 运行应用
            sys.exit(app.exec())
        else:
            # 用户取消登录
            cleanup_resources()
            sys.exit(0)

    except Exception as e:
        print(f"Application error: {e}")
        traceback.print_exc()
        cleanup_resources()
        sys.exit(1)


if __name__ == "__main__":
    main()