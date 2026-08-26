# -*- coding: utf-8 -*-
"""下载 ONNX 摄像头视觉模型（阶段1+2）。

用法（需联网）：
    python tools/download_vision_models.py

下载到：
    attention_training_py/models/vision/yunet.onnx     （YuNet 人脸检测，opencv_zoo）
    attention_training_py/models/vision/ocec_s.onnx     （OCEC 眨眼分类，PINTO0309）

注意：HuggingFace 当前不可达，模型一律从 GitHub 获取。
"""

import os
import sys
import urllib.request


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIR = os.path.join(ROOT, "models", "vision")

# (文件名, 下载地址, 最小字节数)
MODELS = [
    (
        "yunet.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
        "models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        100_000,
    ),
    (
        "ocec_s.onnx",
        "https://github.com/PINTO0309/OCEC/releases/download/onnx/ocec_s.onnx",
        100_000,
    ),
    (
        "headpose_resnet18.onnx",
        "https://github.com/yakhyo/head-pose-estimation/releases/download/weights/resnet18.onnx",
        5_000_000,
    ),
    (
        "gaze_resnet18.onnx",
        "https://github.com/yakhyo/gaze-estimation/releases/download/weights/resnet18_gaze.onnx",
        5_000_000,
    ),
]



def download(url: str, target: str, min_bytes: int) -> None:
    print(f"下载 {os.path.basename(target)} ...")
    tmp = target + ".tmp"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        size = os.path.getsize(tmp)
        if size < min_bytes:
            raise RuntimeError(f"文件过小 ({size} bytes)，疑似下载不完整")
        os.replace(tmp, target)
        print(f"  OK {target} ({size} bytes)")
    except Exception as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def main() -> int:
    os.makedirs(TARGET_DIR, exist_ok=True)
    for name, url, min_bytes in MODELS:
        target = os.path.join(TARGET_DIR, name)
        if os.path.exists(target) and os.path.getsize(target) >= min_bytes:
            print(f"已存在，跳过: {target}")
            continue
        download(url, target, min_bytes)

    # 用 onnxruntime 验证可加载
    try:
        import onnxruntime as ort
    except ImportError:
        print("提示：onnxruntime 未安装，跳过加载验证（请先安装 onnxruntime）")
        return 0
    for name, _, _ in MODELS:
        path = os.path.join(TARGET_DIR, name)
        try:
            sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
            print(f"验证通过: {name} 输入={sess.get_inputs()[0].shape}")
        except Exception as exc:
            print(f"验证失败: {name}: {exc}")
            return 1
    print("全部模型就绪:", TARGET_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
