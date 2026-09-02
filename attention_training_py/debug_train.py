# debug_train.py
import sys
from PySide6.QtWidgets import QApplication
from ui.training_window import TrainingWindow
import traceback

def main():
    app = QApplication(sys.argv)

    try:
        print("Creating training window...")
        window = TrainingWindow(1, "dynamic_tracking")  # 1分钟，追踪模式
        print("Training window created successfully")
        window.show()
        print("Window shown")
        sys.exit(app.exec())
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()