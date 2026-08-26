# -*- coding: utf-8 -*-
"""Runtime path helpers shared by the app and the packaging scripts.

When the program is frozen by PyInstaller, user data (SQLite database, users,
settings, wallpapers, achievements) is stored next to the executable so the
application stays portable and a version upgrade never wipes user data.
In development the data stays at the project root, which preserves the
original behaviour.
"""

import os
import sys


def app_data_dir() -> str:
    """Return the directory where runtime/user data is stored."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # core/paths.py -> core/ -> project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def users_dir() -> str:
    """Return (creating if needed) the per-user data directory."""
    path = os.path.join(app_data_dir(), "users")
    os.makedirs(path, exist_ok=True)
    return path


def database_path() -> str:
    """Return the absolute path of the SQLite database file."""
    return os.path.join(app_data_dir(), "attention_data.db")


def models_dir() -> str:
    """Return the directory where bundled ONNX models live."""
    return os.path.join(app_data_dir(), "models")

