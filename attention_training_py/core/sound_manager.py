# core/sound_manager.py
import os
from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from .paths import app_data_dir

class SoundManager(QObject):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        super().__init__()
        self._initialized = True

        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(0.8)

        self._initialized_ok = False
        self._init_sound()

    def _init_sound(self):
        # 尝试加载资源文件
        app_dir = app_data_dir()
        sound_path = os.path.join(app_dir, "resources", "feedback_sound.mp3")

        if os.path.exists(sound_path):
            self._player.setSource(QUrl.fromLocalFile(sound_path))
            self._initialized_ok = True
            print(f"SoundManager initialized with: {sound_path}")
        else:
            # 尝试使用 Qt 资源
            self._player.setSource(QUrl("qrc:/sounds/feedback_sound.mp3"))
            self._initialized_ok = True
            print("SoundManager initialized with resource")

    def play_feedback_sound(self):
        if self._initialized_ok and self._player:
            self._player.stop()
            self._player.play()

    def is_initialized(self) -> bool:
        return self._initialized_ok