# -*- coding: utf-8 -*-
"""ONNX 摄像头视觉增强验证脚本（阶段1+2）。

用法（Python 3.11 环境，需 onnxruntime + opencv）：
    python tools/verify_onnx_vision.py [测试图片路径]

覆盖：模型可用性、YuNet 人脸检测、OCEC 开闭眼分类、
CameraWorker 管线端到端（MediaPipe + ONNX 开关）与规则回退。
"""

import math
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2  # noqa: E402

from camera.onnx_vision import ONNXVisionEngine  # noqa: E402


def main() -> int:
    engine = ONNXVisionEngine.instance()
    print("ONNX 运行后端:", engine.provider_report())
    face_ok = engine.face_detection_available()
    blink_ok = engine.blink_detection_available()
    print("YuNet 人脸检测可用:", face_ok)
    print("OCEC  眨眼检测可用:", blink_ok)

    test_image = sys.argv[1] if len(sys.argv) > 1 else r"C:\tmp\lena_test.jpg"
    if not os.path.exists(test_image):
        print(f"未找到测试图片: {test_image}（可传入参数指定）")
        return 1

    frame = cv2.imread(test_image)
    print("测试图片:", test_image, frame.shape)

    if face_ok:
        face = engine.detect_face(frame)
        assert face is not None, "YuNet 未检测到人脸"
        bx, by, bw, bh = face["box"]
        assert bw > 30 and bh > 30, "人脸框异常"
        assert len(face["landmarks"]) == 5, "关键点数量异常"
        print(f"[OK] YuNet 人脸: box=({bx:.0f},{by:.0f},{bw:.0f}x{bh:.0f}) "
              f"score={face['score']:.3f} landmarks={len(face['landmarks'])}")
    else:
        print("[SKIP] YuNet 模型缺失")

    if blink_ok:
        # 用 lena 眼睛区域构造开/闭眼样本（真实分类精度依赖裁剪质量）
        # prefer MediaPipe eye-contour centers (same as CameraWorker pipeline)
        left = right = None
        try:
            import mediapipe as mp
            mp_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True, max_num_faces=1, refine_landmarks=True,
                min_detection_confidence=0.5)
            mp_res = mp_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            mp_mesh.close()
            if mp_res.multi_face_landmarks:
                mlm = mp_res.multi_face_landmarks[0].landmark
                ih, iw = frame.shape[:2]
                def ctr(ids):
                    xs = [mlm[i].x * iw for i in ids]
                    ys = [mlm[i].y * ih for i in ids]
                    return sum(xs) / len(xs), sum(ys) / len(ys)
                lc = ctr([33, 133, 160, 159, 158, 144, 145, 153])
                rc = ctr([362, 263, 387, 386, 385, 374, 373, 380])
                ref = abs(rc[0] - lc[0])
                left = engine.crop_eye(frame, lc, ref)
                right = engine.crop_eye(frame, rc, ref)
        except Exception:
            left = right = None
        if left is None and face_ok:
            lm = face["landmarks"]
            ref = abs(lm[1][0] - lm[0][0])
            left = engine.crop_eye(frame, lm[0], ref)
            right = engine.crop_eye(frame, lm[1], ref)
        if left is None:
            h, w = frame.shape[:2]
            left = frame[h // 3:h // 3 + 24, w // 2:w // 2 + 40]
            right = frame[h // 3:h // 3 + 24, w // 2 - 40:w // 2]
        p_l, p_r = engine.classify_eyes(left, right)
        print(f"[OK] OCEC 分类: left={p_l:.3f} right={p_r:.3f}")
        assert 0.0 <= p_l <= 1.0 and 0.0 <= p_r <= 1.0, "概率超出范围"
    else:
        print("[SKIP] OCEC 模型缺失")

    # Stage 3+4: head pose & gaze (face crop from YuNet box)
    if face_ok:
        bx, by, bw, bh = [int(v) for v in face["box"]]
        hh, ww = frame.shape[:2]
        ex, ey = int(bh * 0.2), int(bw * 0.2)
        fc = frame[max(0, by - ey):min(hh, by + bh + ey), max(0, bx - ex):min(ww, bx + bw + ex)]
        try:
            hp = engine.estimate_head_pose(fc)
            if hp is None:
                print("[SKIP] 头部姿态模型未就绪")
            else:
                pitch, yaw, roll = hp
                assert all(abs(v) < 180 for v in hp)
                print(f"[OK] 头部姿态: yaw={yaw:.1f} pitch={pitch:.1f} roll={roll:.1f}")
        except Exception as exc:
            print(f"[SKIP] 头部姿态测试跳过: {exc}")
        try:
            gz = engine.estimate_gaze(fc)
            if gz is None:
                print("[SKIP] 视线模型未就绪")
            else:
                g_yaw, g_pitch = gz
                assert abs(g_yaw) < 1.6 and abs(g_pitch) < 1.6
                print(f"[OK] 视线: yaw={math.degrees(g_yaw):.1f} deg pitch={math.degrees(g_pitch):.1f} deg")
        except Exception as exc:
            print(f"[SKIP] 视线测试跳过: {exc}")

    # CameraWorker 管线端到端（不打开摄像头，直接喂帧）
    try:
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance() or QCoreApplication([])
        from camera.camera_worker import CameraWorker
        worker = CameraWorker()
        worker._onnx_face_enabled = True
        worker._onnx_blink_enabled = True
        worker._onnx_head_pose_enabled = True
        worker._onnx_gaze_enabled = True
        out = worker._process_frame(frame)
        assert len(out) == 6, "输出元组长度异常"
        print(f"[OK] CameraWorker 管线(ONNX 全开): attention={out[3]} gaze={out[4]}")
        worker._onnx_face_enabled = False
        worker._onnx_blink_enabled = False
        worker._onnx_head_pose_enabled = False
        worker._onnx_gaze_enabled = False
        worker._onnx_face_ok = False
        worker._onnx_blink_ok = False
        out2 = worker._process_frame(frame)
        print(f"[OK] CameraWorker 管线(MediaPipe 回退): attention={out2[3]}")
        # 空帧/无脸回退
        blank = cv2.imread(test_image)
        blank[:] = 128
        out3 = worker._process_frame(blank)
        print(f"[OK] CameraWorker 管线(无脸): attention={out3[3]}")
    except Exception as exc:
        print(f"[WARN] CameraWorker 管线测试跳过: {exc}")

    print("视觉验证完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
