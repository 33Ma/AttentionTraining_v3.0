# camera/camera_worker.py
import cv2
import math
import time
import numpy as np
import threading
import mediapipe as mp
from PySide6.QtCore import QObject, Signal, QTimer, QMetaObject, Qt
from PySide6.QtGui import QImage

class CameraWorker(QObject):
    """摄像头工作类"""

    frame_ready = Signal(QImage)
    eye_data_updated = Signal(float, int, int, int, float)  # ear, blink_count, attention, gaze_score, gaze_distance
    camera_error = Signal(str)
    finished = Signal()

    # MediaPipe 眼部关键点
    LEFT_EYE_INDICES = [33, 133, 160, 159, 158, 144, 145, 153]
    RIGHT_EYE_INDICES = [362, 263, 387, 386, 385, 374, 373, 380]

    # 虹膜关键点
    LEFT_IRIS_INDICES = [468, 469, 470, 471, 472]
    RIGHT_IRIS_INDICES = [473, 474, 475, 476, 477]

    # 眼睛边界关键点（用于计算眼睛宽度）
    LEFT_EYE_OUTER = [33, 133]
    RIGHT_EYE_OUTER = [362, 263]

    def __init__(self, parent=None):
        super().__init__(parent)

        self._cap = None
        self._running = False
        self._timer = None

        # MediaPipe
        self._mp_face_mesh = mp.solutions.face_mesh
        self._face_mesh = self._mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self._mp_draw = mp.solutions.drawing_utils

        # 眨眼检测参数
        self.EAR_THRESHOLD = 0.22
        self._adaptive_ear_enabled = False
        self.EYE_AR_CONSEC_FRAMES = 2
        self._eye_counter = 0
        self._blink_counter = 0

        # 自适应参数
        self._ear_history = []
        self._history_size = 15
        self._blink_threshold_ratio = 0.65
        self._last_blink_time = 0
        self._min_blink_interval = 5
        self._total_frames = 0

        # 当前值
        self._current_ear = 0.0
        self._attention_score = 50

        # 注视检测相关
        self._gaze_x = 0.0
        self._gaze_y = 0.0
        self._gaze_distance = 1.0
        self._gaze_history = []
        self._gaze_history_size = 10
        self._gaze_score = 100
        self._last_gaze_point = None

        # 平滑滤波
        self._gaze_filter_x = []
        self._gaze_filter_y = []
        self._filter_size = 5

        # 注视灵敏度：将虹膜偏移放大后映射到屏幕坐标，值越大，同样的眼动产生的注视距离越大
        self._gaze_sensitivity = 3.0
        # 允许的最大归一化虹膜偏移，避免极端噪声直接打到屏幕边缘
        self._gaze_max_offset = 0.5

        # 信号发送节流（限制GUI线程负载，防止事件队列堆积）
        self.FRAME_EMIT_INTERVAL = 1.0 / 12.0    # 预览帧上限 ~12 FPS
        self.EYE_DATA_EMIT_INTERVAL = 1.0 / 10.0 # 数据更新上限 ~10 Hz
        self._last_frame_emit = -1.0
        self._last_eye_emit = -1.0

        # ONNX 视觉增强（阶段1+2：YuNet 人脸检测 + OCEC 眨眼检测）
        self._onnx_engine = None
        self._onnx_face_enabled = False
        self._onnx_blink_enabled = False
        self._onnx_face_ok = False
        self._onnx_blink_ok = False
        self._onnx_eye_state = "OPEN"
        self._onnx_open_frames = 0
        self._onnx_closed_frames = 0
        # 自适应开眼概率基线：跟踪近期开眼概率，避免固定滞回阈值与模型实际输出
        # 标定不一致时状态机卡死在 CLOSING 导致眨眼漏报；看门狗避免长时间闭眼卡死
        self._onnx_open_base = 0.9
        self._onnx_max_closed_frames = 20
        # OCEC 失效健康检查：模型输出退化时用 EAR 并行计数作为对照
        self._onnx_ear_blinks = 0
        self._onnx_warned = set()
        self._onnx_head_pose_enabled = False
        self._onnx_gaze_enabled = False
        self._onnx_head_pose_ok = False
        self._onnx_gaze_ok = False
        self._onnx_head_pose = None
        self._onnx_gaze = None
        self._onnx_last_face = None
        self._onnx_prob_open = 0.5
        self._onnx_face_infer_errors = 0
        # ONNX 后台预热：模型加载放到独立线程，避免阻塞摄像头初始化与帧循环
        self._onnx_warmup_thread = None
        self._onnx_warmup_started = False
        self._onnx_lock = threading.Lock()

        print("CameraWorker initialized")

    def set_ear_threshold(self, value: float):
        """设置EAR闭眼检测阈值"""
        self.EAR_THRESHOLD = max(0.1, min(0.4, float(value)))

    def set_adaptive_ear(self, enabled: bool):
        """开启/关闭自适应EAR：开启后阈值根据历史记录与实时数据动态调整"""
        self._adaptive_ear_enabled = bool(enabled)

    def start_capture(self):
        """启动摄像头"""
        print("CameraWorker.start_capture called")

        # 读取 ONNX 视觉设置（模型缺失时自动回退 MediaPipe）
        with self._onnx_lock:
            self._onnx_engine = None
            self._onnx_face_ok = False
            self._onnx_blink_ok = False
            self._onnx_head_pose_ok = False
            self._onnx_gaze_ok = False
            self._onnx_last_face = None
            self._onnx_prob_open = 0.5
            self._onnx_open_base = 0.9
            self._onnx_eye_state = "OPEN"
            self._onnx_open_frames = 0
            self._onnx_closed_frames = 0
            self._last_blink_time = 0
            self._onnx_ear_blinks = 0
            self._onnx_face_infer_errors = 0
            self._onnx_warmup_started = False
        self._last_frame_emit = -1.0
        self._last_eye_emit = -1.0
        try:
            from core.settings import GlobalSettings
            self._onnx_face_enabled = GlobalSettings().onnx_face_detection_enabled()
            self._onnx_blink_enabled = GlobalSettings().onnx_blink_detection_enabled()
            self._onnx_head_pose_enabled = GlobalSettings().onnx_head_pose_enabled()
            self._onnx_gaze_enabled = GlobalSettings().onnx_gaze_enabled()
        except Exception:
            self._onnx_face_enabled = False
            self._onnx_blink_enabled = False
            self._onnx_head_pose_enabled = False
            self._onnx_gaze_enabled = False
        print(f"ONNX vision: face={self._onnx_face_enabled} blink={self._onnx_blink_enabled} head_pose={self._onnx_head_pose_enabled} gaze={self._onnx_gaze_enabled}")

        # 后台预热 ONNX 引擎，摄像头立即开始出帧，模型就绪后自动切换
        self._start_onnx_warmup()

        if self._running:
            print("Camera already running")
            return

        try:
            self._cap = cv2.VideoCapture(0)
            if not self._cap.isOpened():
                self.camera_error.emit("无法打开摄像头")
                self.finished.emit()
                return

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._cap.set(cv2.CAP_PROP_FPS, 30)

            self._running = True

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._update_frame)
            self._timer.start(33)

            print("Camera started successfully")

        except Exception as e:
            print(f"Camera start error: {e}")
            self.camera_error.emit(str(e))
            self.finished.emit()

    def stop_capture(self):
        """停止摄像头"""
        print("CameraWorker.stop_capture called")

        self._running = False

        if self._timer:
            QMetaObject.invokeMethod(self._timer, "stop", Qt.QueuedConnection)
            self._timer = None

        if self._cap:
            try:
                self._cap.release()
            except:
                pass
            self._cap = None

        if self._face_mesh:
            try:
                self._face_mesh.close()
            except:
                pass
            self._face_mesh = None

        print("Camera stopped")
        self.finished.emit()

    def update_game_score(self, game_score: int):
        """更新游戏得分（用于注意力计算）"""
        pass

    def _update_frame(self):
        """更新帧"""
        if not self._running or self._cap is None:
            return

        try:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                return

            frame = cv2.flip(frame, 1)
            processed_frame, ear, blink_count, attention, gaze_score, gaze_distance = self._process_frame(frame)

            self._current_ear = ear
            self._blink_counter = blink_count
            self._attention_score = attention
            self._gaze_score = gaze_score
            self._gaze_distance = gaze_distance

            now = time.monotonic()
            if now - self._last_eye_emit >= self.EYE_DATA_EMIT_INTERVAL:
                self._last_eye_emit = now
                self.eye_data_updated.emit(ear, blink_count, attention, gaze_score, gaze_distance)

            if now - self._last_frame_emit >= self.FRAME_EMIT_INTERVAL:
                self._last_frame_emit = now
                qimage = self._cv2_to_qimage(processed_frame)
                self.frame_ready.emit(qimage)

        except Exception as e:
            print(f"Frame update error: {e}")

    def _warn_once(self, key: str, message: str):
        if key not in self._onnx_warned:
            self._onnx_warned.add(key)
            print(f"CameraWorker: {message}")

    def _start_onnx_warmup(self):
        """在后台线程初始化 ONNX 视觉引擎，不阻塞摄像头打开与帧循环。"""
        if not (self._onnx_face_enabled or self._onnx_blink_enabled
                or self._onnx_head_pose_enabled or self._onnx_gaze_enabled):
            return
        with self._onnx_lock:
            if self._onnx_warmup_started:
                return
            self._onnx_warmup_started = True
            thread = threading.Thread(
                target=self._ensure_onnx, name="onnx-vision-warmup", daemon=True
            )
        self._onnx_warmup_thread = thread
        thread.start()
        print("CameraWorker: ONNX 视觉引擎后台预热已启动")

    def _ensure_onnx(self):
        """初始化 ONNX 视觉引擎并检查模型可用性（后台线程执行，仅一次）。"""
        with self._onnx_lock:
            if self._onnx_engine is not None:
                return
            try:
                from camera.onnx_vision import ONNXVisionEngine
                engine = ONNXVisionEngine.instance()
                face_ok = False
                blink_ok = False
                head_pose_ok = False
                gaze_ok = False
                if self._onnx_face_enabled:
                    face_ok = engine.face_detection_available()
                    if not face_ok:
                        self._warn_once("face", "ONNX 人脸检测模型不可用，回退 MediaPipe")
                if self._onnx_blink_enabled:
                    blink_ok = engine.blink_detection_available()
                    if not blink_ok:
                        self._warn_once("blink", "ONNX 眨眼检测模型不可用，回退 EAR 阈值")
                if self._onnx_head_pose_enabled:
                    head_pose_ok = engine.head_pose_detection_available()
                    if not head_pose_ok:
                        self._warn_once("head_pose", "ONNX 头部姿态模型不可用，跳过")
                if self._onnx_gaze_enabled:
                    gaze_ok = engine.gaze_detection_available()
                    if not gaze_ok:
                        self._warn_once("gaze", "ONNX 视线模型不可用，回退虹膜注视")
                self._onnx_engine = engine
                self._onnx_face_ok = face_ok
                self._onnx_blink_ok = blink_ok
                self._onnx_head_pose_ok = head_pose_ok
                self._onnx_gaze_ok = gaze_ok
            except Exception as exc:
                self._onnx_engine = None
                self._onnx_face_ok = False
                self._onnx_blink_ok = False
                self._onnx_head_pose_ok = False
                self._onnx_gaze_ok = False
                self._warn_once("init", f"ONNX 视觉引擎初始化失败: {exc}")
            print(f"ONNX vision engine ready: face={self._onnx_face_ok} "
                  f"blink={self._onnx_blink_ok} head_pose={self._onnx_head_pose_ok} "
                  f"gaze={self._onnx_gaze_ok}")

    def _detect_face_onnx(self, frame):
        if not self._onnx_face_ok or self._onnx_engine is None:
            return None
        try:
            result = self._onnx_engine.detect_face(frame)
            self._onnx_face_infer_errors = 0
            return result
        except Exception as exc:
            self._onnx_face_infer_errors += 1
            self._warn_once("face_infer", f"ONNX 人脸检测失败: {exc}")
            if self._onnx_face_infer_errors >= 5:
                self._onnx_face_ok = False
                self._warn_once("face_infer_disable", "ONNX 人脸检测连续失败，回退 MediaPipe")
            return None

    def _classify_eyes_onnx(self, frame, left_eye_pts, right_eye_pts) -> float:
        """用 OCEC 分类双眼，返回平均开眼概率。"""
        if not self._onnx_blink_ok or self._onnx_engine is None:
            return 0.5
        try:
            left_cx = sum(pt[0] for pt in left_eye_pts) / len(left_eye_pts)
            left_cy = sum(pt[1] for pt in left_eye_pts) / len(left_eye_pts)
            right_cx = sum(pt[0] for pt in right_eye_pts) / len(right_eye_pts)
            right_cy = sum(pt[1] for pt in right_eye_pts) / len(right_eye_pts)
            ref = math.hypot(right_cx - left_cx, right_cy - left_cy)
            left_crop = self._onnx_engine.crop_eye(frame, (left_cx, left_cy), ref)
            right_crop = self._onnx_engine.crop_eye(frame, (right_cx, right_cy), ref)
            p_left, p_right = self._onnx_engine.classify_eyes(left_crop, right_crop)
            return (p_left + p_right) / 2.0
        except Exception as exc:
            self._warn_once("blink_infer", f"ONNX 眨眼检测失败: {exc}")
            return 0.5

    def _get_face_crop(self, frame, landmarks, w, h, onnx_face=None):
        """Face crop from YuNet box or MediaPipe landmark bbox, expanded 20%."""
        if onnx_face is not None:
            bx, by, bw, bh = [float(v) for v in onnx_face["box"]]
        else:
            xs = [lm.x * w for lm in landmarks]
            ys = [lm.y * h for lm in landmarks]
            bx, by = min(xs), min(ys)
            bw, bh = max(xs) - bx, max(ys) - by
        ex = int(bh * 0.2)
        ey = int(bw * 0.2)
        x0 = max(0, int(bx) - ex)
        y0 = max(0, int(by) - ey)
        x1 = min(w, int(bx + bw) + ex)
        y1 = min(h, int(by + bh) + ey)
        if x1 <= x0 or y1 <= y0:
            return None
        return frame[y0:y1, x0:x1]

    def _estimate_head_pose_onnx(self, face_crop):
        if not self._onnx_head_pose_ok or self._onnx_engine is None or face_crop is None:
            return None
        try:
            return self._onnx_engine.estimate_head_pose(face_crop)
        except Exception as exc:
            self._warn_once("head_pose_infer", f"ONNX \u5934\u90e8\u59ff\u6001\u63a8\u7406\u5931\u8d25: {exc}")
            return None

    def _estimate_gaze_onnx(self, face_crop):
        if not self._onnx_gaze_ok or self._onnx_engine is None or face_crop is None:
            return None
        try:
            return self._onnx_engine.estimate_gaze(face_crop)
        except Exception as exc:
            self._warn_once("gaze_infer", f"ONNX \u89c6\u7ebf\u63a8\u7406\u5931\u8d25: {exc}")
            return None

    def _process_frame(self, frame):
        """处理单帧"""
        # 未启动后台预热时（如验证脚本直接调用管线）同步初始化；
        # 生产环境由 start_capture 启动的后台线程完成，帧循环不会被阻塞。
        if not self._onnx_warmup_started and (
                self._onnx_face_enabled or self._onnx_blink_enabled
                or self._onnx_head_pose_enabled or self._onnx_gaze_enabled):
            self._ensure_onnx()

        display = frame.copy()
        self._total_frames += 1

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(rgb)

        ear = 0.0
        blink_count = self._blink_counter
        attention = 50
        gaze_score = 100
        gaze_distance = 1.0

        mp_face = bool(results.multi_face_landmarks)
        onnx_face = self._onnx_last_face
        if self._onnx_face_enabled and self._onnx_face_ok:
            # YuNet 每4帧检测一次，中间帧复用缓存的人脸框
            if self._total_frames % 4 == 1:
                self._onnx_last_face = self._detect_face_onnx(frame)
                onnx_face = self._onnx_last_face
            face_present = onnx_face is not None
        else:
            # ONNX 未就绪/不可用时回退 MediaPipe，避免训练期间误报“未检测到人脸”
            face_present = mp_face

        if not face_present:
            cv2.putText(display, "No face detected", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            return display, ear, blink_count, attention, gaze_score, gaze_distance

        if onnx_face is not None:
            bx, by, bw, bh = [int(v) for v in onnx_face["box"]]
            cv2.rectangle(display, (bx, by), (bx + bw, by + bh), (255, 165, 0), 2)
            cv2.putText(display, f"YuNet {onnx_face['score']:.2f}", (bx, by - 6),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 165, 0), 2)

        if not mp_face:
            cv2.putText(display, "Face detected (ONNX)", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            return display, ear, blink_count, attention, gaze_score, gaze_distance

        landmarks = results.multi_face_landmarks[0].landmark
        h, w, _ = frame.shape

        # Stage 3+4: 头部姿态/视线各每6帧跑一次并错开不同帧，中间帧复用缓存结果
        if self._onnx_head_pose_enabled or self._onnx_gaze_enabled:
            if self._total_frames % 6 == 1:
                if self._onnx_head_pose_enabled and self._onnx_head_pose_ok:
                    face_crop = self._get_face_crop(frame, landmarks, w, h, onnx_face)
                    self._onnx_head_pose = self._estimate_head_pose_onnx(face_crop)
            elif self._total_frames % 6 == 4:
                if self._onnx_gaze_enabled and self._onnx_gaze_ok:
                    face_crop = self._get_face_crop(frame, landmarks, w, h, onnx_face)
                    self._onnx_gaze = self._estimate_gaze_onnx(face_crop)

        # 获取眼部关键点（像素坐标）
        left_eye_pts = self._get_eye_points(landmarks, self.LEFT_EYE_INDICES, w, h, normalize=False)
        right_eye_pts = self._get_eye_points(landmarks, self.RIGHT_EYE_INDICES, w, h, normalize=False)

        # 获取虹膜关键点（归一化坐标）
        left_iris_pts = self._get_eye_points(landmarks, self.LEFT_IRIS_INDICES, w, h, normalize=True)
        right_iris_pts = self._get_eye_points(landmarks, self.RIGHT_IRIS_INDICES, w, h, normalize=True)

        # 获取眼角关键点（用于计算眼睛宽度）
        left_eye_corners = self._get_eye_points(landmarks, self.LEFT_EYE_OUTER, w, h, normalize=False)
        right_eye_corners = self._get_eye_points(landmarks, self.RIGHT_EYE_OUTER, w, h, normalize=False)

        if left_eye_pts and right_eye_pts and len(left_eye_pts) == 8 and len(right_eye_pts) == 8:
            left_ear = self._calculate_ear(left_eye_pts)
            right_ear = self._calculate_ear(right_eye_pts)
            ear = (left_ear + right_ear) / 2.0

            # 绘制眼睛轮廓
            left_eye_hull = cv2.convexHull(np.array(left_eye_pts))
            right_eye_hull = cv2.convexHull(np.array(right_eye_pts))
            cv2.polylines(display, [left_eye_hull], True, (0, 255, 0), 1)
            cv2.polylines(display, [right_eye_hull], True, (0, 255, 0), 1)

            # ========== 注视检测 ==========
            onnx_gaze_active = self._onnx_gaze_enabled and self._onnx_gaze_ok and self._onnx_gaze is not None
            if onnx_gaze_active:
                g_yaw, g_pitch = self._onnx_gaze
                gaze_distance = min(1.0, math.hypot(math.tan(g_yaw), math.tan(g_pitch)) / 0.75)
                self._gaze_distance = gaze_distance
                self._gaze_history.append(gaze_distance)
                if len(self._gaze_history) > self._gaze_history_size:
                    self._gaze_history.pop(0)
                gaze_score = self._calculate_gaze_score()
                self._gaze_score = gaze_score
                cv2.putText(display, f"Gaze Yaw: {math.degrees(g_yaw):.0f} Pitch: {math.degrees(g_pitch):.0f}", (10, 180),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                cv2.putText(display, f"Gaze Score: {gaze_score}", (10, 210),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                cv2.putText(display, "Gaze(ONNX)", (w - 200, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            else:
                gaze_point = self._calculate_gaze_point(
                    landmarks, left_eye_pts, right_eye_pts,
                    left_iris_pts, right_iris_pts,
                    left_eye_corners, right_eye_corners,
                    w, h
                )

                if gaze_point:
                    gaze_x, gaze_y = gaze_point
                    self._last_gaze_point = (gaze_x, gaze_y)
                    cv2.circle(display, (int(gaze_x), int(gaze_y)), 10, (0, 0, 255), 2)
                    cv2.circle(display, (int(gaze_x), int(gaze_y)), 4, (0, 0, 255), -1)
                    center_x, center_y = w // 2, h // 2
                    cv2.line(display, (center_x, center_y), (int(gaze_x), int(gaze_y)), (255, 0, 255), 1)
                    cv2.circle(display, (center_x, center_y), 6, (0, 255, 255), 1)
                    dx = (gaze_x - center_x) / (w / 2)
                    dy = (gaze_y - center_y) / (h / 2)
                    gaze_distance = math.sqrt(dx * dx + dy * dy)
                    self._gaze_distance = gaze_distance
                    self._gaze_history.append(gaze_distance)
                    if len(self._gaze_history) > self._gaze_history_size:
                        self._gaze_history.pop(0)
                    gaze_score = self._calculate_gaze_score()
                    self._gaze_score = gaze_score
                    cv2.putText(display, f"Gaze Dist: {gaze_distance:.3f}", (10, 180),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                    cv2.putText(display, f"Gaze Score: {gaze_score}", (10, 210),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                    if gaze_distance < 0.15:
                        cv2.putText(display, "Looking at screen", (w - 200, 30),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    elif gaze_distance < 0.3:
                        cv2.putText(display, "Looking away slightly", (w - 230, 30),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                    else:
                        cv2.putText(display, "Looking away!", (w - 180, 30),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            if self._onnx_blink_enabled and self._onnx_blink_ok:
                # OCEC 每帧分类一次，避免采样间隔漏掉快速眨眼
                self._onnx_prob_open = self._classify_eyes_onnx(frame, left_eye_pts, right_eye_pts)
                prob_open = self._onnx_prob_open
                ear_for_score = 0.12 + 0.22 * prob_open
                blink_detected = self._detect_blink_prob(prob_open)
                # 健康检查：若 OCEC 一直计不到眨眼而 EAR 能正常计数
                # （当前画面下模型输出退化，如裁剪/光照问题），
                # 自动回退 EAR，避免眨眼数恒为 0
                if self._detect_blink(ear):
                    self._onnx_ear_blinks += 1
                    if self._blink_counter == 0 and self._onnx_ear_blinks >= 3:
                        self._onnx_blink_ok = False
                        self._onnx_ear_blinks = 0
                        self._warn_once(
                            "blink_unusable",
                            "OCEC 眨眼模型输出不可用，回退 EAR 阈值眨眼检测",
                        )
                cv2.putText(display, f"OCEC: {prob_open:.2f}", (10, 240),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
            else:
                ear_for_score = ear
                blink_detected = self._detect_blink(ear)
            if blink_detected:
                self._blink_counter += 1
                cv2.putText(display, "Blink Detected!", (10, 90),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # 计算注意力分数
            attention = self._calculate_attention_score(ear_for_score, gaze_score)
            if self._onnx_head_pose_enabled and self._onnx_head_pose_ok and self._onnx_head_pose is not None:
                hp_pitch, hp_yaw, hp_roll = self._onnx_head_pose
                penalty = min(35, int(abs(hp_yaw) * 0.6 + abs(hp_pitch) * 0.4))
                attention = max(0, attention - penalty)
                cv2.putText(display, f"HP: yaw {hp_yaw:.0f} pitch {hp_pitch:.0f} roll {hp_roll:.0f}", (10, 260),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

            # 显示信息
            cv2.putText(display, f"EAR: {ear:.3f}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.putText(display, f"Blinks: {self._blink_counter}", (10, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(display, f"Attention: {attention}", (10, 120),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 200), 2)

            # 显示状态
            status = "Focused" if attention > 70 else "Distracted"
            color = (0, 255, 0) if attention > 70 else (0, 0, 255)
            cv2.putText(display, status, (10, 150),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        return display, ear, self._blink_counter, attention, gaze_score, gaze_distance

    def _calculate_gaze_point(self, landmarks, left_eye_pts, right_eye_pts,
                               left_iris_pts, right_iris_pts,
                               left_eye_corners, right_eye_corners,
                               w, h):
        """
        计算注视点
        使用虹膜相对于眼睛中心的位置来估计注视方向
        """
        try:
            if not left_iris_pts or not right_iris_pts:
                return None

            if len(left_iris_pts) < 5 or len(right_iris_pts) < 5:
                return None

            # 计算眼睛中心（像素坐标）
            left_eye_center_x = sum(pt[0] for pt in left_eye_pts) / len(left_eye_pts)
            left_eye_center_y = sum(pt[1] for pt in left_eye_pts) / len(left_eye_pts)
            right_eye_center_x = sum(pt[0] for pt in right_eye_pts) / len(right_eye_pts)
            right_eye_center_y = sum(pt[1] for pt in right_eye_pts) / len(right_eye_pts)

            # 计算虹膜中心（归一化坐标，需要转换为像素）
            left_iris_center_x = sum(pt[0] for pt in left_iris_pts) / len(left_iris_pts)
            left_iris_center_y = sum(pt[1] for pt in left_iris_pts) / len(left_iris_pts)
            right_iris_center_x = sum(pt[0] for pt in right_iris_pts) / len(right_iris_pts)
            right_iris_center_y = sum(pt[1] for pt in right_iris_pts) / len(right_iris_pts)

            # 将虹膜中心转换为像素坐标
            left_iris_px = (left_iris_center_x * w, left_iris_center_y * h)
            right_iris_px = (right_iris_center_x * w, right_iris_center_y * h)

            # 计算虹膜相对于眼睛中心的偏移（像素）
            left_offset_x = left_iris_px[0] - left_eye_center_x
            left_offset_y = left_iris_px[1] - left_eye_center_y
            right_offset_x = right_iris_px[0] - right_eye_center_x
            right_offset_y = right_iris_px[1] - right_eye_center_y

            # 计算眼睛宽度（用于归一化）
            if left_eye_corners and len(left_eye_corners) >= 2:
                left_eye_width = math.hypot(
                    left_eye_corners[0][0] - left_eye_corners[1][0],
                    left_eye_corners[0][1] - left_eye_corners[1][1]
                )
            else:
                # 备用：使用眼睛轮廓计算宽度
                left_eye_width = math.hypot(
                    left_eye_pts[0][0] - left_eye_pts[1][0],
                    left_eye_pts[0][1] - left_eye_pts[1][1]
                )

            if right_eye_corners and len(right_eye_corners) >= 2:
                right_eye_width = math.hypot(
                    right_eye_corners[0][0] - right_eye_corners[1][0],
                    right_eye_corners[0][1] - right_eye_corners[1][1]
                )
            else:
                right_eye_width = math.hypot(
                    right_eye_pts[0][0] - right_eye_pts[1][0],
                    right_eye_pts[0][1] - right_eye_pts[1][1]
                )

            avg_eye_width = (left_eye_width + right_eye_width) / 2
            if avg_eye_width < 1:
                return None

            # 归一化偏移（相对于眼睛宽度）
            norm_offset_x = ((left_offset_x / avg_eye_width) + (right_offset_x / avg_eye_width)) / 2
            norm_offset_y = ((left_offset_y / avg_eye_width) + (right_offset_y / avg_eye_width)) / 2

            # 限制偏移范围
            max_offset = self._gaze_max_offset
            norm_offset_x = max(-max_offset, min(max_offset, norm_offset_x))
            norm_offset_y = max(-max_offset, min(max_offset, norm_offset_y))

            # 屏幕中心
            center_x, center_y = w // 2, h // 2

            # 映射到屏幕坐标
            # 将归一化眼动偏移放大后，映射到以屏幕中心为原点的半屏坐标。
            # sensitivity 越大，同样的虹膜偏移对应越大的屏幕注视距离。
            gaze_x = center_x + norm_offset_x * (w / 2) * self._gaze_sensitivity
            gaze_y = center_y + norm_offset_y * (h / 2) * self._gaze_sensitivity

            # 限制在屏幕范围内
            gaze_x = max(0, min(w, gaze_x))
            gaze_y = max(0, min(h, gaze_y))

            # 平滑滤波
            self._gaze_filter_x.append(gaze_x)
            self._gaze_filter_y.append(gaze_y)
            if len(self._gaze_filter_x) > self._filter_size:
                self._gaze_filter_x.pop(0)
                self._gaze_filter_y.pop(0)

            if len(self._gaze_filter_x) >= 3:
                smooth_x = sum(self._gaze_filter_x) / len(self._gaze_filter_x)
                smooth_y = sum(self._gaze_filter_y) / len(self._gaze_filter_y)
                return (smooth_x, smooth_y)

            return (gaze_x, gaze_y)

        except Exception as e:
            print(f"Gaze calculation error: {e}")
            return None

    def _calculate_gaze_score(self):
        """计算注视专注度分数"""
        if not self._gaze_history:
            return 100

        # 计算平均注视距离
        avg_distance = sum(self._gaze_history) / len(self._gaze_history)

        # 距离分数：距离越近分数越高
        if avg_distance < 0.1:
            distance_score = 100
        elif avg_distance < 0.2:
            distance_score = 90 - (avg_distance - 0.1) * 100
        elif avg_distance < 0.35:
            distance_score = 80 - (avg_distance - 0.2) * 200
        else:
            distance_score = max(0, 50 - (avg_distance - 0.35) * 100)

        # 稳定性分数（基于标准差）
        if len(self._gaze_history) > 1:
            variance = sum((d - avg_distance) ** 2 for d in self._gaze_history) / len(self._gaze_history)
            std_dev = math.sqrt(variance)
            # 注视距离被灵敏度放大后，稳定性阈值也应按同一比例放大，
            # 避免轻微但正常的眼动噪声被误判为“不稳定”。
            stability_reference = 0.15 * self._gaze_sensitivity
            stability_score = max(0, min(100, (1 - std_dev / stability_reference) * 100))
        else:
            stability_score = 100

        # 综合评分
        gaze_score = int(0.7 * distance_score + 0.3 * stability_score)

        return max(0, min(100, gaze_score))

    def _calculate_ear(self, eye_pts):
        """计算眼睛纵横比"""
        if len(eye_pts) != 8:
            return 0.0

        v1 = math.hypot(eye_pts[2][0] - eye_pts[5][0], eye_pts[2][1] - eye_pts[5][1])
        v2 = math.hypot(eye_pts[3][0] - eye_pts[6][0], eye_pts[3][1] - eye_pts[6][1])
        v3 = math.hypot(eye_pts[4][0] - eye_pts[7][0], eye_pts[4][1] - eye_pts[7][1])
        h = math.hypot(eye_pts[0][0] - eye_pts[1][0], eye_pts[0][1] - eye_pts[1][1])

        if h == 0:
            return 0.0

        return (v1 + v2 + v3) / (3.0 * h)

    def _detect_blink(self, current_ear):
        """检测眨眼"""
        self._ear_history.append(current_ear)
        if len(self._ear_history) > self._history_size:
            self._ear_history.pop(0)

        # 手动模式下固定使用设定的阈值；自适应模式下根据实时历史动态调节
        if not self._adaptive_ear_enabled or len(self._ear_history) < 10:
            threshold = self.EAR_THRESHOLD
        else:
            sorted_history = sorted(self._ear_history)
            trim_size = int(len(sorted_history) * 0.2)
            trimmed = sorted_history[trim_size:-trim_size] if trim_size > 0 else sorted_history
            avg_ear = sum(trimmed) / len(trimmed)
            threshold = avg_ear * self._blink_threshold_ratio
            threshold = max(0.15, min(0.30, threshold))

        if current_ear < threshold:
            self._eye_counter += 1
            return False
        else:
            if self._eye_counter >= self.EYE_AR_CONSEC_FRAMES:
                current_frame = self._total_frames
                if current_frame - self._last_blink_time >= self._min_blink_interval:
                    self._last_blink_time = current_frame
                    self._eye_counter = 0
                    return True
            self._eye_counter = 0
            return False

    def _detect_blink_prob(self, prob_open: float) -> bool:
        """基于 OCEC 开眼概率的自适应眨眼状态机。

        关闭/恢复阈值跟随近期开眼概率基线自适应：当模型输出标定偏低（开眼概率
        落在固定 0.45~0.55 死区内）时，旧状态机会卡死在 CLOSING，之后所有眨眼
        都会漏报；看门狗则保证长时间闭眼/遮挡后转入 CLOSED_LONG，重新睁眼时
        复位但不计数，也不阻塞后续检测。
        """
        if self._onnx_eye_state == "OPEN":
            self._onnx_open_frames += 1
            # 仅用开眼时段的概率更新基线，眨眼时的低概率不会污染基线
            self._onnx_open_base += 0.08 * (prob_open - self._onnx_open_base)
            close_th = max(0.28, min(0.50, self._onnx_open_base * 0.6))
            if prob_open < close_th:
                self._onnx_eye_state = "CLOSING"
                self._onnx_closed_frames = 1
        elif self._onnx_eye_state == "CLOSING":
            self._onnx_closed_frames += 1
            if self._onnx_closed_frames >= self._onnx_max_closed_frames:
                # 长时间闭眼/遮挡：转入 CLOSED_LONG，睁眼时复位但不计数
                self._onnx_eye_state = "CLOSED_LONG"
                self._onnx_open_frames = 0
                self._onnx_closed_frames = 0
            else:
                reopen_th = max(0.38, min(0.60, self._onnx_open_base * 0.75))
                if prob_open > reopen_th:
                    counted = False
                    if self._onnx_closed_frames >= 2:
                        current_frame = self._total_frames
                        if current_frame - self._last_blink_time >= self._min_blink_interval:
                            self._last_blink_time = current_frame
                            counted = True
                    self._onnx_eye_state = "OPEN"
                    self._onnx_open_frames = 0
                    self._onnx_closed_frames = 0
                    return counted
        elif self._onnx_eye_state == "CLOSED_LONG":
            # 长时间闭眼/标定漂移期间仍缓慢更新基线，避免恢复阈值偏高而卡死
            self._onnx_open_base += 0.08 * (prob_open - self._onnx_open_base)
            reopen_th = max(0.38, min(0.60, self._onnx_open_base * 0.75))
            if prob_open > reopen_th:
                self._onnx_eye_state = "OPEN"
                self._onnx_open_frames = 0
                self._onnx_closed_frames = 0
        return False

    def _calculate_attention_score(self, ear, gaze_score):
        """计算注意力分数"""
        # 基于EAR的分数
        if ear < self.EAR_THRESHOLD:
            ear_score = 100.0 - (self.EAR_THRESHOLD - ear) * 200.0
        elif ear > 0.35:
            ear_score = 100.0 - (ear - 0.35) * 500.0
        else:
            ear_score = 100.0
        ear_score = max(0.0, min(100.0, ear_score))

        # 眨眼频率分数
        if self._total_frames > 0:
            blink_rate = self._blink_counter / (self._total_frames / 30.0)
        else:
            blink_rate = 0

        optimal_blink_rate = 0.3
        blink_score = 100.0 - min(50.0, abs(blink_rate - optimal_blink_rate) * 200.0)
        blink_score = max(0.0, min(100.0, blink_score))

        # 综合评分
        attention = int(0.3 * ear_score + 0.2 * blink_score + 0.5 * gaze_score)
        return max(0, min(100, attention))

    def _get_eye_points(self, landmarks, indices, w, h, normalize=False):
        """获取眼部关键点坐标"""
        pts = []
        for idx in indices:
            try:
                if idx < len(landmarks):
                    if normalize:
                        pts.append((landmarks[idx].x, landmarks[idx].y))
                    else:
                        x = int(landmarks[idx].x * w)
                        y = int(landmarks[idx].y * h)
                        pts.append((x, y))
            except IndexError:
                return []
        return pts

    def _cv2_to_qimage(self, frame):
        """OpenCV 转 QImage"""
        try:
            h, w, ch = frame.shape
            bytes_per_line = ch * w

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = QImage(rgb_frame.data.tobytes(), w, h, bytes_per_line, QImage.Format_RGB888)

            return image
        except Exception as e:
            print(f"CV2 to QImage error: {e}")
            return QImage(640, 480, QImage.Format_RGB888)