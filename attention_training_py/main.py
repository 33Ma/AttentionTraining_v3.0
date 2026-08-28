# main.py - 程序入口

import sys
import signal
import traceback
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


def main():
    # 设置异常钩子
    sys.excepthook = exception_hook

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