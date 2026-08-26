# -*- coding: utf-8 -*-
"""ONNX 摄像头视觉引擎（4 个模型全部通过 onnxruntime 推理；默认纯 CPU）。
- YuNet：onnxruntime 直接推理（固定 640x640 输入），自实现 OpenCV 同款
  解码 + NMS，输出 [x,y,w,h] + 5 关键点 + 置信度。
- OCEC：onnxruntime 直接推理，输入 24x40 单眼 RGB 裁剪，输出 prob_open。
- 头部姿态 6DRepNet / 视线 L2CS：onnxruntime 直接推理。
默认使用 CPUExecutionProvider（模型推理均为毫秒级）；如需 CUDA，
设置环境变量 ATTENTION_TRAINING_USE_GPU=1（需要 onnxruntime-gpu 且
CUDA/cuBLAS/cuDNN 版本匹配），CUDA 不可用时自动回退 CPU。
模型缺失或加载失败时返回 None/中性值，由调用方回退 MediaPipe 既有逻辑。"""

import math
import os
import threading
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from core.paths import models_dir


YUNET_MODEL_FILE = "yunet.onnx"
OCEC_MODEL_FILE = "ocec_s.onnx"

OCEC_INPUT_H = 24
OCEC_INPUT_W = 40
HEAD_POSE_MODEL_FILE = "headpose_resnet18.onnx"
GAZE_MODEL_FILE = "gaze_resnet18.onnx"

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
YUNET_INPUT_W = 640
YUNET_INPUT_H = 640
YUNET_STRIDES = (8, 16, 32)
YUNET_OUTPUT_NAMES = (
    "cls_8", "cls_16", "cls_32",
    "obj_8", "obj_16", "obj_32",
    "bbox_8", "bbox_16", "bbox_32",
    "kps_8", "kps_16", "kps_32",
)
YUNET_SCORE_THRESHOLD = 0.7
YUNET_NMS_THRESHOLD = 0.3
YUNET_TOP_K = 5000



def vision_models_dir() -> str:
    return os.path.join(models_dir(), "vision")


def face_model_path() -> str:
    return os.path.join(vision_models_dir(), YUNET_MODEL_FILE)


def blink_model_path() -> str:
    return os.path.join(vision_models_dir(), OCEC_MODEL_FILE)


def face_model_available() -> bool:
    return os.path.exists(face_model_path())


def blink_model_available() -> bool:
    return os.path.exists(blink_model_path())


def head_pose_model_path() -> str:
    return os.path.join(vision_models_dir(), HEAD_POSE_MODEL_FILE)


def gaze_model_path() -> str:
    return os.path.join(vision_models_dir(), GAZE_MODEL_FILE)


def head_pose_model_available() -> bool:
    return os.path.exists(head_pose_model_path())


def gaze_model_available() -> bool:
    return os.path.exists(gaze_model_path())


class ONNXVisionEngine:
    """ONNX 视觉引擎（线程安全单例，懒加载）。"""

    _instance: Optional["ONNXVisionEngine"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> "ONNXVisionEngine":
        return cls()

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._lock = threading.Lock()
        self._ort = None
        self._sessions: Dict[str, object] = {}
        self._cpu_sessions: Dict[str, object] = {}
        # 运行时 CUDA 推理失败（如缺少 cuDNN）后标记为仅 CPU 的模型
        self._cpu_only: Dict[str, bool] = {}
        self._yunet = None
        self._cuda_preloaded = False

    # ------------------------------------------------------------------
    # 运行时与模型加载
    # ------------------------------------------------------------------
    def _load_ort(self) -> bool:
        if self._ort is not None:
            return True
        with self._lock:
            if self._ort is not None:
                return True
            try:
                import onnxruntime as ort
                self._ort = ort
            except Exception as exc:
                print(f"ONNXVisionEngine: onnxruntime 不可用: {exc}")
                self._ort = None
            return self._ort is not None

    def _preload_ort_dlls(self):
        """在创建会话前预加载 CUDA/cuDNN/MSVC DLL（onnxruntime-gpu>=1.21 官方 API）。
        directory="" 表示从 NVIDIA site-packages 自动查找（兼容 CUDA 12 / CUDA 13 布局）。"""
        preload = getattr(self._ort, "preload_dlls", None)
        if preload is None:
            return
        try:
            preload(cuda=True, cudnn=True, msvc=True, directory="")
        except Exception as exc:
            print(f"ONNXVisionEngine: preload_dlls 警告: {exc}")

    @staticmethod
    def _gpu_enabled() -> bool:
        """CUDA 仅当显式开启时才启用：设置中勾选“允许调用GPU”，或设置环境变量
        ATTENTION_TRAINING_USE_GPU=1/true/yes/on 时也会强制启用。"""
        env = os.environ.get("ATTENTION_TRAINING_USE_GPU", "").strip().lower()
        if env in ("1", "true", "yes", "on"):
            return True
        try:
            from core.settings import GlobalSettings
            return GlobalSettings().onnx_gpu_enabled()
        except Exception:
            return False

    def _session(self, path: str, prefer_gpu: bool = True):
        if not self._load_ort():
            return None
        if not os.path.exists(path):
            return None
        force_cpu = bool(self._cpu_only.get(path))
        cache = self._cpu_sessions if force_cpu else self._sessions
        if path not in cache:
            with self._lock:
                if path not in cache:
                    opts = self._ort.SessionOptions()
                    opts.intra_op_num_threads = 2
                    opts.inter_op_num_threads = 1
                    opts.graph_optimization_level = (
                        self._ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                    )
                    # 默认纯 CPU 推理（YuNet/OCEC/头部姿态/视线耗时均为毫秒级）。
                    # 仅当显式设置 ATTENTION_TRAINING_USE_GPU=1 时才尝试 CUDA，
                    # 避免加载不匹配的 cuBLAS/cuDNN 触发 Windows “找不到入口”弹窗。
                    use_cuda = False
                    if not force_cpu and prefer_gpu and self._gpu_enabled():
                        available = self._ort.get_available_providers()
                        if "CUDAExecutionProvider" in available:
                            use_cuda = True
                            if not self._cuda_preloaded:
                                self._preload_ort_dlls()
                                self._cuda_preloaded = True
                    providers = (
                        ["CUDAExecutionProvider", "CPUExecutionProvider"]
                        if use_cuda else ["CPUExecutionProvider"]
                    )
                    try:
                        cache[path] = self._ort.InferenceSession(
                            path, sess_options=opts, providers=providers
                        )
                    except Exception as exc:
                        if use_cuda:
                            print(
                                f"ONNXVisionEngine: CUDA 不可用，"
                                f"{os.path.basename(path)} 回退 CPU: {exc}"
                            )
                            try:
                                cache[path] = self._ort.InferenceSession(
                                    path,
                                    sess_options=opts,
                                    providers=["CPUExecutionProvider"],
                                )
                            except Exception as exc2:
                                print(f"ONNXVisionEngine: 模型加载失败 {path}: {exc2}")
                                return None
                        else:
                            print(f"ONNXVisionEngine: 模型加载失败 {path}: {exc}")
                            return None
                    print(
                        f"ONNXVisionEngine: {os.path.basename(path)} "
                        f"providers={cache[path].get_providers()}"
                    )
        return cache[path]

    def _run(self, path: str, feed: Dict[str, object], output_names=None):
        """执行一次推理；CUDA 会话在运行时失败（例如缺少 cuDNN 的
        NOT_IMPLEMENTED）时自动标记该模型仅用 CPU 并重试。"""
        sess = self._session(path, prefer_gpu=True)
        if sess is None:
            return None
        try:
            return sess.run(output_names, feed)
        except Exception as exc:
            if "CUDAExecutionProvider" in sess.get_providers() and not self._cpu_only.get(path):
                print(
                    f"ONNXVisionEngine: {os.path.basename(path)} CUDA 推理失败: {exc}"
                )
                print(
                    f"ONNXVisionEngine: {os.path.basename(path)} 回退 CPU 推理"
                )
                self._cpu_only[path] = True
                cpu_sess = self._session(path, prefer_gpu=False)
                if cpu_sess is None:
                    return None
                return cpu_sess.run(output_names, feed)
            raise

    def _init_yunet(self):
        if self._yunet is not None:
            return self._yunet
        if not face_model_available():
            return None
        # _session 内部已用 self._lock 做双重检查，这里不能再持锁调用，
        # 否则非重入锁会死锁（首次初始化即卡死，导致 ONNX 永远不可用）。
        self._yunet = self._session(face_model_path())
        return self._yunet

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def face_detection_available(self) -> bool:
        return self._init_yunet() is not None

    def blink_detection_available(self) -> bool:
        return self._session(blink_model_path()) is not None

    def head_pose_detection_available(self) -> bool:
        return self._session(head_pose_model_path()) is not None

    def gaze_detection_available(self) -> bool:
        return self._session(gaze_model_path()) is not None

    def provider_report(self) -> Dict[str, str]:
        """返回各模型实际使用的 ONNX Runtime 执行后端（验证是否走 GPU）。"""
        report: Dict[str, str] = {}
        entries = (
            ("YuNet", face_model_path(), face_model_available()),
            ("OCEC", blink_model_path(), blink_model_available()),
            ("head_pose", head_pose_model_path(), head_pose_model_available()),
            ("gaze", gaze_model_path(), gaze_model_available()),
        )
        for label, path, available in entries:
            if not available:
                report[label] = "model missing"
                continue
            sess = self._session(path)
            report[label] = (
                ", ".join(sess.get_providers()) if sess is not None else "load failed"
            )
        return report


    def detect_face(self, frame_bgr: np.ndarray) -> Optional[Dict[str, object]]:
        """检测最大人脸，返回 {box:(x,y,w,h), landmarks:[(x,y)x5], score} 或 None。"""
        sess = self._init_yunet()
        if sess is None or frame_bgr is None or frame_bgr.size == 0:
            return None
        h, w = frame_bgr.shape[:2]
        try:
            blob = self._preprocess_yunet(frame_bgr)
            inp_name = sess.get_inputs()[0].name
            outs = self._run(face_model_path(), {inp_name: blob}, list(YUNET_OUTPUT_NAMES))
            if outs is None:
                return None
            faces = self._decode_yunet(outs)
        except Exception as exc:
            print(f"ONNXVisionEngine: YuNet 推理失败: {exc}")
            return None
        if faces is None or len(faces) == 0:
            return None
        best = faces[np.argmax(faces[:, 14])]
        sx = w / YUNET_INPUT_W
        sy = h / YUNET_INPUT_H
        x, y = float(best[0] * sx), float(best[1] * sy)
        fw, fh = float(best[2] * sx), float(best[3] * sy)
        landmarks = [
            (float(best[4 + i * 2] * sx), float(best[4 + i * 2 + 1] * sy))
            for i in range(5)
        ]
        return {
            "box": (x, y, fw, fh),
            "landmarks": landmarks,
            "score": float(best[14]),
        }


    def classify_eyes(
        self, left_eye_bgr: np.ndarray, right_eye_bgr: np.ndarray
    ) -> Tuple[float, float]:
        """对左右眼裁剪图分类，返回 (左眼开眼概率, 右眼开眼概率)。"""
        sess = self._session(blink_model_path())
        if sess is None:
            return 0.5, 0.5
        batch = []
        for crop in (left_eye_bgr, right_eye_bgr):
            if crop is None or crop.size == 0:
                batch.append(
                    np.full((OCEC_INPUT_H, OCEC_INPUT_W, 3), 128, np.uint8)
                )
                continue
            img = cv2.resize(crop, (OCEC_INPUT_W, OCEC_INPUT_H))
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = img.astype(np.float32) / 255.0
            img = img.transpose(2, 0, 1)
            batch.append(img)
        blob = np.asarray(batch, dtype=np.float32)
        try:
            inp_name = sess.get_inputs()[0].name
            out = self._run(blink_model_path(), {inp_name: blob})
            if out is None:
                return 0.5, 0.5
            out = out[0]
            probs = np.asarray(out, dtype=np.float32).reshape(-1)
            if len(probs) < 2:
                return float(probs[0]), float(probs[0])
            return float(probs[0]), float(probs[1])
        except Exception as exc:
            print(f"ONNXVisionEngine: OCEC 推理失败: {exc}")
            return 0.5, 0.5

    @staticmethod
    def crop_eye(
        frame_bgr: np.ndarray, center: Tuple[float, float], ref_width: float
    ) -> np.ndarray:
        """以眼睛中心裁剪近似 40x24 比例的局部图（尺寸按参考宽度自适应）。"""
        h, w = frame_bgr.shape[:2]
        cx, cy = float(center[0]), float(center[1])
        eye_w = max(24, int(ref_width * 0.75))
        eye_h = max(12, int(eye_w * 0.6))
        x0 = int(cx - eye_w / 2.0)
        y0 = int(cy - eye_h / 2.0)
        x0 = max(0, min(x0, w - 1))
        y0 = max(0, min(y0, h - 1))
        x1 = min(w, x0 + eye_w)
        y1 = min(h, y0 + eye_h)
        return frame_bgr[y0:y1, x0:x1]

    @staticmethod
    def _preprocess_yunet(frame_bgr: np.ndarray) -> np.ndarray:
        """YuNet 预处理：BGR 直接缩放至 640x640，不归一化（与 OpenCV FaceDetectorYN 一致）。"""
        img = cv2.resize(frame_bgr, (YUNET_INPUT_W, YUNET_INPUT_H))
        return np.asarray(img, dtype=np.float32).transpose(2, 0, 1)[None]

    @staticmethod
    def _decode_yunet(outs) -> Optional[np.ndarray]:
        """将 YuNet 12 个输出解码为 Nx15（640 坐标空间），再做阈值过滤与 NMS。

        每行: [x, y, w, h, re_x, re_y, le_x, le_y, nt_x, nt_y, rcm_x, rcm_y,
               lcm_x, lcm_y, score]；公式与 OpenCV face_detect.cpp postProcess 一致。
        """
        all_faces = []
        for i, stride in enumerate(YUNET_STRIDES):
            n = YUNET_INPUT_W // stride
            num = n * n
            cls = np.clip(np.asarray(outs[i], dtype=np.float32).reshape(num), 0.0, 1.0)
            obj = np.clip(
                np.asarray(outs[i + 3], dtype=np.float32).reshape(num), 0.0, 1.0
            )
            bbox = np.asarray(outs[i + 6], dtype=np.float32).reshape(num, 4)
            kps = np.asarray(outs[i + 9], dtype=np.float32).reshape(num, 10)

            c = np.tile(np.arange(n, dtype=np.float32), n)
            r = np.repeat(np.arange(n, dtype=np.float32), n)

            score = np.sqrt(cls * obj)
            cx = (c + bbox[:, 0]) * stride
            cy = (r + bbox[:, 1]) * stride
            w = np.exp(bbox[:, 2]) * stride
            h = np.exp(bbox[:, 3]) * stride
            kx = (kps[:, 0::2] + c[:, None]) * stride
            ky = (kps[:, 1::2] + r[:, None]) * stride
            # OpenCV layout: interleaved x,y (re, le, nt, rcm, lcm)
            kpts = np.stack([kx, ky], axis=2).reshape(num, 10)

            all_faces.append(
                np.concatenate(
                    [
                        (cx - w / 2.0)[:, None],
                        (cy - h / 2.0)[:, None],
                        w[:, None],
                        h[:, None],
                        kpts,
                        score[:, None],
                    ],
                    axis=1,
                )
            )
        if not all_faces:
            return None
        faces = np.concatenate(all_faces, axis=0)
        faces = faces[faces[:, 14] >= YUNET_SCORE_THRESHOLD]
        if len(faces) == 0:
            return None
        keep = ONNXVisionEngine._nms(
            faces[:, :4], faces[:, 14], YUNET_NMS_THRESHOLD, YUNET_TOP_K
        )
        if len(keep) == 0:
            return None
        return faces[keep]

    @staticmethod
    def _nms(
        boxes: np.ndarray, scores: np.ndarray, nms_threshold: float, top_k: int
    ) -> np.ndarray:
        """贪心 NMS（与 OpenCV dnn::NMSBoxes 行为一致）。boxes: Nx4 (x,y,w,h)。"""
        if len(boxes) == 0:
            return np.empty(0, dtype=np.int64)
        order = scores.argsort()[::-1][:top_k]
        keep = []
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 0] + boxes[:, 2]
        y2 = boxes[:, 1] + boxes[:, 3]
        areas = boxes[:, 2] * boxes[:, 3]
        while order.size > 0:
            i = order[0]
            keep.append(i)
            if order.size == 1:
                break
            rest = order[1:]
            xx1 = np.maximum(x1[i], x1[rest])
            yy1 = np.maximum(y1[i], y1[rest])
            xx2 = np.minimum(x2[i], x2[rest])
            yy2 = np.minimum(y2[i], y2[rest])
            inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
            union = areas[i] + areas[rest] - inter
            iou = inter / np.maximum(union, 1e-9)
            order = rest[iou <= nms_threshold]
        return np.asarray(keep, dtype=np.int64)


    @staticmethod
    def _preprocess_face(image_bgr, size_w: int, size_h: int) -> np.ndarray:
        """人脸裁剪预处理：RGB + resize + ImageNet 归一化。"""
        img = cv2.resize(image_bgr, (size_w, size_h))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img = (img - IMAGENET_MEAN) / IMAGENET_STD
        img = img.transpose(2, 0, 1)[None]
        return img.astype(np.float32)

    @staticmethod
    def _rotation_matrix_to_euler(rotation_matrix) -> Tuple[float, float, float]:
        """3x3 旋转矩阵转欧拉角（pitch, yaw, roll，单位度）。"""
        R = np.asarray(rotation_matrix, dtype=np.float32).reshape(3, 3)
        sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
        if sy < 1e-6:
            x = math.atan2(-R[1, 2], R[1, 1])
            y = math.atan2(-R[2, 0], sy)
            z = 0.0
        else:
            x = math.atan2(R[2, 1], R[2, 2])
            y = math.atan2(-R[2, 0], sy)
            z = math.atan2(R[1, 0], R[0, 0])
        return float(math.degrees(x)), float(math.degrees(y)), float(math.degrees(z))

    @staticmethod
    def _softmax(x: np.ndarray) -> np.ndarray:
        e = np.exp(x - x.max())
        return e / e.sum()

    def estimate_head_pose(self, face_bgr: np.ndarray) -> Optional[Tuple[float, float, float]]:
        """6DRepNet 头部姿态：返回 (pitch, yaw, roll) 度。"""
        sess = self._session(head_pose_model_path())
        if sess is None or face_bgr is None or face_bgr.size == 0:
            return None
        try:
            inp = sess.get_inputs()[0]
            blob = self._preprocess_face(face_bgr, int(inp.shape[3]), int(inp.shape[2]))
            out = self._run(head_pose_model_path(), {inp.name: blob})
            if out is None:
                return None
            return self._rotation_matrix_to_euler(out[0])
        except Exception as exc:
            print(f"ONNXVisionEngine: 头部姿态推理失败: {exc}")
            return None

    def estimate_gaze(self, face_bgr: np.ndarray) -> Optional[Tuple[float, float]]:
        """L2CS 视线估计：返回 (yaw, pitch) 弧度。"""
        sess = self._session(gaze_model_path())
        if sess is None or face_bgr is None or face_bgr.size == 0:
            return None
        try:
            inp = sess.get_inputs()[0]
            blob = self._preprocess_face(face_bgr, int(inp.shape[3]), int(inp.shape[2]))
            outs = self._run(gaze_model_path(), {inp.name: blob})
            if outs is None:
                return None
            yaw_logits = np.asarray(outs[0], dtype=np.float32).reshape(-1)
            pitch_logits = np.asarray(outs[1], dtype=np.float32).reshape(-1)
            idx = np.arange(90, dtype=np.float32)
            yaw_deg = float(np.sum(self._softmax(yaw_logits) * idx) * 4.0 - 180.0)
            pitch_deg = float(np.sum(self._softmax(pitch_logits) * idx) * 4.0 - 180.0)
            return float(math.radians(yaw_deg)), float(math.radians(pitch_deg))
        except Exception as exc:
            print(f"ONNXVisionEngine: 视线推理失败: {exc}")
            return None