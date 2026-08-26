# -*- coding: utf-8 -*-
"""
PyInstaller hook for mediapipe.

mediapipe 的 legacy Solutions API（如 mp.solutions.face_mesh）在运行时通过
``resource_util.set_resource_dir(root_path)`` 加载模型与图配置：

    root_path = os.path.dirname(mediapipe.__file__) 的上三级目录

在 PyInstaller 冻结环境中，模块 ``__file__`` 被设置为
``<bundle_dir>/mediapipe/python/solution_base.pyc``，因此 root_path 即
``sys._MEIPASS``，模型文件必须被打包到 ``mediapipe/modules/...`` 目录下。

如果不收集这些数据文件，打包后的程序会在初始化 FaceMesh 时报
``FileNotFoundError``，界面显示“摄像头初始化失败”。
"""

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# 收集 mediapipe 的模型/图数据（.tflite/.binarypb/.txt 等），保持
# mediapipe/modules/... 的相对路径，使其落到 sys._MEIPASS 下。
# 排除 .py/.pyc/.pyd/.dll，避免与纯 Python 模块和动态库重复收集。
datas = collect_data_files(
    "mediapipe",
    excludes=[
        "**/*.py",
        "**/*.pyc",
        "**/*.pyd",
        "**/*.dll",
        "**/__pycache__",
    ],
)

# _framework_bindings 的 pyd 与其依赖的 opencv_world3410.dll
binaries = collect_dynamic_libs("mediapipe")
