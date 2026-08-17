# utils/wallpaper_manager.py
from PySide6.QtCore import QObject, Signal, QSize, Qt
from PySide6.QtGui import QPixmap, QImage, QPainter
from PySide6.QtCore import QRect

class WallpaperManager(QObject):
    wallpaper_changed = Signal(str)
    wallpaper_cleared = Signal()

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

        self._current_path = ""
        self._pixmap = QPixmap()
        self._original_size = QSize()
        self._cached_scaled = QPixmap()
        self._cached_size = QSize(-1, -1)

    def load_wallpaper(self, path: str) -> bool:
        if not path:
            self.clear_wallpaper()
            return False

        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False

        self._current_path = path
        self._pixmap = pixmap
        self._original_size = pixmap.size()
        self._cached_scaled = QPixmap()
        self._cached_size = QSize(-1, -1)

        self.wallpaper_changed.emit(path)
        return True

    def paint_wallpaper(self, painter: QPainter, rect: QRect):
        if painter is None or self._pixmap.isNull():
            return

        if self._cached_size != rect.size():
            self._cached_scaled = self._pixmap.scaled(
                rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            self._cached_size = rect.size()

        if not self._cached_scaled.isNull():
            draw_pos = rect.topLeft()
            if self._cached_scaled.width() > rect.width():
                draw_pos.setX(rect.left() - (self._cached_scaled.width() - rect.width()) // 2)
            if self._cached_scaled.height() > rect.height():
                draw_pos.setY(rect.top() - (self._cached_scaled.height() - rect.height()) // 2)
            painter.drawPixmap(draw_pos, self._cached_scaled)

    def get_wallpaper_pixmap(self, target_size: QSize = None) -> QPixmap:
        if self._pixmap.isNull():
            return QPixmap()

        if target_size is None or target_size.isEmpty() or target_size == self._original_size:
            return self._pixmap

        return self._pixmap.scaled(target_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

    def get_wallpaper_image(self, target_size: QSize = None) -> QImage:
        return self.get_wallpaper_pixmap(target_size).toImage()

    def clear_wallpaper(self):
        self._current_path = ""
        self._pixmap = QPixmap()
        self._original_size = QSize()
        self._cached_scaled = QPixmap()
        self._cached_size = QSize(-1, -1)
        self.wallpaper_cleared.emit()

    def current_path(self) -> str:
        return self._current_path

    def is_valid(self) -> bool:
        return bool(self._current_path) and not self._pixmap.isNull()

    @staticmethod
    def supported_formats() -> list:
        from PySide6.QtGui import QImageReader
        formats = QImageReader.supportedImageFormats()
        return [f"*.{fmt.data().decode()}" for fmt in formats]