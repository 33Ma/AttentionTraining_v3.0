# camera/camera_worker.py
import cv2
import math
import numpy as np
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

        print("CameraWorker initialized")

    def start_capture(self):
        """启动摄像头"""
        print("CameraWorker.start_capture called")

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

            self.eye_data_updated.emit(ear, blink_count, attention, gaze_score, gaze_distance)

            qimage = self._cv2_to_qimage(processed_frame)
            self.frame_ready.emit(qimage)

        except Exception as e:
            print(f"Frame update error: {e}")

    def _process_frame(self, frame):
        """处理单帧"""
        display = frame.copy()
        self._total_frames += 1

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(rgb)

        ear = 0.0
        blink_count = self._blink_counter
        attention = 50
        gaze_score = 100
        gaze_distance = 1.0

        if not results.multi_face_landmarks:
            cv2.putText(display, "No face detected", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            return display, ear, blink_count, attention, gaze_score, gaze_distance

        landmarks = results.multi_face_landmarks[0].landmark
        h, w, _ = frame.shape

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
            gaze_point = self._calculate_gaze_point(
                landmarks, left_eye_pts, right_eye_pts,
                left_iris_pts, right_iris_pts,
                left_eye_corners, right_eye_corners,
                w, h
            )

            if gaze_point:
                gaze_x, gaze_y = gaze_point
                self._last_gaze_point = (gaze_x, gaze_y)

                # 绘制注视点
                cv2.circle(display, (int(gaze_x), int(gaze_y)), 10, (0, 0, 255), 2)
                cv2.circle(display, (int(gaze_x), int(gaze_y)), 4, (0, 0, 255), -1)

                # 绘制从屏幕中心到注视点的连线
                center_x, center_y = w // 2, h // 2
                cv2.line(display, (center_x, center_y), (int(gaze_x), int(gaze_y)), (255, 0, 255), 1)

                # 绘制屏幕中心参考点
                cv2.circle(display, (center_x, center_y), 6, (0, 255, 255), 1)

                # 计算注视偏离距离
                dx = (gaze_x - center_x) / (w / 2)
                dy = (gaze_y - center_y) / (h / 2)
                gaze_distance = math.sqrt(dx * dx + dy * dy)
                self._gaze_distance = gaze_distance

                # 更新注视历史
                self._gaze_history.append(gaze_distance)
                if len(self._gaze_history) > self._gaze_history_size:
                    self._gaze_history.pop(0)

                # 计算注视专注度分数
                gaze_score = self._calculate_gaze_score()
                self._gaze_score = gaze_score

                # 显示注视信息
                cv2.putText(display, f"Gaze Dist: {gaze_distance:.3f}", (10, 180),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                cv2.putText(display, f"Gaze Score: {gaze_score}", (10, 210),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

                # 根据注视状态显示提示
                if gaze_distance < 0.15:
                    cv2.putText(display, "Looking at screen", (w - 200, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                elif gaze_distance < 0.3:
                    cv2.putText(display, "Looking away slightly", (w - 230, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                else:
                    cv2.putText(display, "Looking away!", (w - 180, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            # 眨眼检测
            blink_detected = self._detect_blink(ear)
            if blink_detected:
                self._blink_counter += 1
                cv2.putText(display, "Blink Detected!", (10, 90),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # 计算注意力分数
            attention = self._calculate_attention_score(ear, gaze_score)

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

        if len(self._ear_history) < 10:
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