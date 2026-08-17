# games/game_interface.py
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

class GameInterface(QWidget):
    game_score_changed = Signal(int)
    feedback_triggered = Signal(str)
    consecutive_hits_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

    def start_game(self):
        raise NotImplementedError

    def stop_game(self):
        raise NotImplementedError

    def update_with_attention(self, attention_score: int):
        raise NotImplementedError