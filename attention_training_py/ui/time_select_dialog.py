# ui/time_select_dialog.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel

from core.settings import GlobalSettings


class TimeSelectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择训练时长")
        self.setMinimumSize(300, 250)
        self.resize(350, 280)

        self._minutes = 1

        self._setup_ui()
        self._apply_style_sheet()

        settings = GlobalSettings()
        settings.settings_changed.connect(self._apply_style_sheet)

    def selected_minutes(self) -> int:
        return self._minutes

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        label = QLabel("请选择训练时长：")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        btn_style = "font-size: 16px; padding: 12px;"

        btn1 = QPushButton("1 分钟")
        btn1.setStyleSheet(btn_style)
        btn1.clicked.connect(lambda: self._on_button_clicked(1))

        btn5 = QPushButton("5 分钟")
        btn5.setStyleSheet(btn_style)
        btn5.clicked.connect(lambda: self._on_button_clicked(5))

        btn10 = QPushButton("10 分钟")
        btn10.setStyleSheet(btn_style)
        btn10.clicked.connect(lambda: self._on_button_clicked(10))

        layout.addWidget(btn1)
        layout.addWidget(btn5)
        layout.addWidget(btn10)

        layout.addStretch()

    def _on_button_clicked(self, minutes: int):
        self._minutes = minutes
        self.accept()

    def _apply_style_sheet(self):
        settings = GlobalSettings()
        bg = settings.background_color().name()
        text = settings.text_color().name()

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text}; font-size: 14px; }}
            QPushButton {{ background-color: #4CAF50; color: white; border: none;
                border-radius: 8px; padding: 12px; font-size: 16px; }}
            QPushButton:hover {{ background-color: #45a049; }}
        """)