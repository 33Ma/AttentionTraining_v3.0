# camera/camera_worker.py
import cv2
import numpy as np
import mediapipe as mp
from typing import Optional
from PySide6.QtCore import QObject, Signal, QThread, QMutex
from PySide6.QtGui import QImage


class CameraWorker(QObject):
    """摄像头工作线程 - 简化版"""

    frame_ready = Signal(QImage)
    eye_data_updated = Signal(float, int, int)
    camera_error = Signal(str)
    finished = Signal()

    game_score_to_update = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap = None
        self._running = False
        self._mutex = QMutex()

        # MediaPipe Face Mesh
        try:
            self._mp_face_mesh = mp.solutions.face_mesh
            self._face_mesh = self._mp_face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
        except Exception as e:
            print(f"MediaPipe initialization error: {e}")
            self._face_mesh = None

        # 眨眼检测
        self._blink_counter = 0
        self._closed_frames = 0
        self._open_frames = 0
        self._total_frames = 0

        # 注意力评估
        self._attention_score = 50
        self._closed_history = []
        self._PERCLOS_WINDOW = 90

        # 游戏得分
        self._last_game_score = 0
        self._game_score_history = []
        self._game_score_update_frame = 0
        self._game_performance_ratio = 0.5
        self._GAME_SCORE_WINDOW = 90

        # 滤波
        self._filtered_ear = 0.3
        self._peak_ear = 0.3

        # 眨眼状态
        self._blink_state = "OPEN"

        # 连接游戏得分更新信号
        self.game_score_to_update.connect(self._update_game_score_impl)

    def start_capture(self):
        """启动摄像头捕获 - 在子线程中调用"""
        try:
            self._running = True

            # 尝试打开摄像头
            for i in range(5):
                try:
                    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                    if cap.isOpened():
                        self._cap = cap
                        break
                except Exception as e:
                    print(f"Camera {i} open error: {e}")
                    continue

            if self._cap is None or not self._cap.isOpened():
                self.camera_error.emit("无法打开摄像头，请检查摄像头连接")
                self.finished.emit()
                return

            # 设置摄像头参数
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._cap.set(cv2.CAP_PROP_FPS, 30)

            # 主循环
            self._capture_loop()

        except Exception as e:
            error_msg = f"摄像头启动失败: {str(e)}"
            print(error_msg)
            self.camera_error.emit(error_msg)
            self.finished.emit()

    def stop_capture(self):
        """停止摄像头捕获"""
        try:
            self._mutex.lock()
            self._running = False
            self._mutex.unlock()
        except Exception as e:
            print(f"Stop capture error: {e}")

    def update_game_score(self, game_score: int):
        """更新游戏得分 - 线程安全"""
        try:
            self.game_score_to_update.emit(game_score)
        except Exception as e:
            print(f"Update game score error: {e}")

    def _update_game_score_impl(self, game_score: int):
        """实际更新游戏得分"""
        try:
            if game_score != self._last_game_score:
                delta = game_score - self._last_game_score
                if delta > 0:
                    self._game_score_history.append(delta)
                    if len(self._game_score_history) > self._GAME_SCORE_WINDOW:
                        self._game_score_history.pop(0)
                    self._last_game_score = game_score
                    self._game_score_update_frame = self._total_frames
        except Exception as e:
            print(f"Update game score impl error: {e}")

    def _capture_loop(self):
        """主捕获循环"""
        try:
            while self._running:
                # 检查摄像头是否可用
                self._mutex.lock()
                if not self._running or self._cap is None:
                    self._mutex.unlock()
                    break
                self._mutex.unlock()

                # 捕获帧
                try:
                    ret, frame = self._cap.read()
                    if not ret or frame is None:
                        QThread.msleep(10)
                        continue
                except Exception as e:
                    print(f"Frame capture error: {e}")
                    QThread.msleep(50)
                    continue

                # 处理帧
                try:
                    self._process_frame(frame)
                except Exception as e:
                    print(f"Frame processing error: {e}")

                # 控制帧率（约30fps）
                QThread.msleep(33)

        except Exception as e:
            print(f"Capture loop error: {e}")
        finally:
            # 清理资源
            self._cleanup()

    def _process_frame(self, frame: np.ndarray):
        """处理单帧"""
        try:
            self._total_frames += 1

            # 转换为 RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            ear = 0.0
            attention_score = 50

            # 检查 MediaPipe 是否可用
            if self._face_mesh is None:
                # 如果 MediaPipe 不可用，直接显示帧
                qimage = self._cv2_to_qimage(frame)
                self.frame_ready.emit(qimage)
                self.eye_data_updated.emit(0.0, 0, 50)
                return

            try:
                results = self._face_mesh.process(rgb_frame)

                if results.multi_face_landmarks:
                    landmarks = results.multi_face_landmarks[0]

                    # 计算 EAR
                    ear = self._calculate_ear(landmarks)

                    # 滤波
                    filtered_ear = self._filter_ear(ear)

                    # 更新眨眼检测
                    self._update_blink_detection(filtered_ear)

                    # 计算注意力分数
                    attention_score = self._calculate_attention_score()

                    # 绘制面部标记
                    h, w, _ = frame.shape
                    for landmark in landmarks.landmark:
                        x, y = int(landmark.x * w), int(landmark.y * h)
                        cv2.circle(frame, (x, y), 1, (0, 255, 0), -1)

                    # 绘制状态信息
                    cv2.putText(frame, f"EAR: {filtered_ear:.3f}", (20, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    cv2.putText(frame, f"State: {self._blink_state}", (20, 55),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
                    cv2.putText(frame, f"Attention: {attention_score}", (20, 80),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 200), 1)
                else:
                    cv2.putText(frame, "No face detected", (20, 40),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    # 未检测到人脸时，认为闭眼
                    for _ in range(5):
                        self._closed_history.append(True)
                        if len(self._closed_history) > self._PERCLOS_WINDOW:
                            self._closed_history.pop(0)
                    attention_score = self._calculate_attention_score()
            except Exception as e:
                print(f"Face processing error: {e}")
                # 发生错误时使用默认值
                attention_score = 50

            # 发送数据到主线程
            self.eye_data_updated.emit(ear, self._blink_counter, attention_score)

            # 转换并发送帧
            qimage = self._cv2_to_qimage(frame)
            self.frame_ready.emit(qimage)

        except Exception as e:
            print(f"Process frame error: {e}")

    def _calculate_ear(self, landmarks) -> float:
        """计算眼睛纵横比"""
        try:
            def get_point(idx):
                return (landmarks.landmark[idx].x, landmarks.landmark[idx].y)

            left_eye = [
                get_point(33), get_point(160), get_point(158),
                get_point(133), get_point(153), get_point(144)
            ]
            left_ear = self._ear_for_points(left_eye)

            right_eye = [
                get_point(362), get_point(385), get_point(387),
                get_point(263), get_point(373), get_point(380)
            ]
            right_ear = self._ear_for_points(right_eye)

            return (left_ear + right_ear) / 2.0
        except Exception as e:
            print(f"Calculate EAR error: {e}")
            return 0.3

    def _ear_for_points(self, points) -> float:
        """计算给定点的 EAR"""
        try:
            p1, p2, p3, p4, p5, p6 = points

            def dist(a, b):
                return np.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2)

            A = dist(p2, p6)
            B = dist(p3, p5)
            C = dist(p1, p4)

            if C == 0:
                return 0.3
            return (A + B) / (2.0 * C)
        except Exception as e:
            print(f"EAR for points error: {e}")
            return 0.3

    def _filter_ear(self, raw_ear: float) -> float:
        """指数平滑滤波"""
        try:
            alpha = 0.7
            self._filtered_ear = alpha * self._filtered_ear + (1 - alpha) * raw_ear
            return max(0.0, min(0.5, self._filtered_ear))
        except Exception as e:
            print(f"Filter EAR error: {e}")
            return 0.3

    def _update_blink_detection(self, filtered_ear: float):
        """更新眨眼检测"""
        try:
            threshold = 0.25

            if filtered_ear > self._peak_ear * 0.8:
                self._peak_ear = 0.95 * self._peak_ear + 0.05 * filtered_ear

            if self._blink_state == "OPEN":
                self._open_frames += 1
                if filtered_ear < threshold:
                    self._blink_state = "CLOSING"
                    self._closed_frames = 1

            elif self._blink_state == "CLOSING":
                self._closed_frames += 1
                if filtered_ear > threshold:
                    if self._closed_frames >= 3:
                        self._blink_counter += 1
                    self._blink_state = "OPEN"
                    self._open_frames = 0
                    self._closed_frames = 0

            elif self._blink_state == "CLOSED":
                self._closed_frames += 1
                if filtered_ear > threshold:
                    self._blink_state = "OPENING"

            elif self._blink_state == "OPENING":
                if filtered_ear > threshold:
                    if self._closed_frames >= 3:
                        self._blink_counter += 1
                    self._blink_state = "OPEN"
                    self._open_frames = 0
                    self._closed_frames = 0

            self._closed_history.append(filtered_ear < threshold)
            if len(self._closed_history) > self._PERCLOS_WINDOW:
                self._closed_history.pop(0)
        except Exception as e:
            print(f"Update blink detection error: {e}")

    def _calculate_attention_score(self) -> int:
        """计算注意力分数"""
        try:
            if not self._closed_history:
                return 50

            # PERCLOS
            closed_count = sum(1 for c in self._closed_history if c)
            perclos = closed_count / len(self._closed_history) if self._closed_history else 0
            perclos_score = max(0, int(100.0 * (1.0 - perclos * 2.5)))

            # 眨眼频率
            elapsed_minutes = self._total_frames / (30.0 * 60.0)
            blink_rate = self._blink_counter / elapsed_minutes if elapsed_minutes > 0.1 else 15.0
            blink_score = 100
            if blink_rate < 10:
                blink_score = int(blink_rate * 10)
            elif blink_rate > 30:
                blink_score = max(0, 100 - int((blink_rate - 30) * 5))

            # 当前状态
            current_state_score = 100
            if self._blink_state in ("CLOSING", "CLOSED"):
                current_state_score = max(0, 100 - self._closed_frames * 3)

            # 游戏表现
            game_score = self._calculate_game_performance_score()

            # 加权综合
            final_score = int(perclos_score * 0.25 +
                             blink_score * 0.20 +
                             current_state_score * 0.25 +
                             game_score * 0.30)

            return max(0, min(100, final_score))
        except Exception as e:
            print(f"Calculate attention score error: {e}")
            return 50

    def _calculate_game_performance_score(self) -> int:
        """计算游戏表现分数"""
        try:
            if not self._game_score_history:
                return 50

            active_frames = sum(1 for d in self._game_score_history if d > 0)
            activity_ratio = active_frames / len(self._game_score_history)

            frames_since_last = self._total_frames - self._game_score_update_frame
            stagnation_penalty = 0.0
            if frames_since_last > 90:
                stagnation_penalty = min(1.0, (frames_since_last - 90) / 150.0)

            total_delta = sum(self._game_score_history)
            avg_score_per_frame = total_delta / len(self._game_score_history) if self._game_score_history else 0.0
            rate_score = min(1.0, avg_score_per_frame / 0.3)

            game_performance = activity_ratio * 0.4 + rate_score * 0.3 + (1.0 - stagnation_penalty) * 0.3
            self._game_performance_ratio = 0.85 * self._game_performance_ratio + 0.15 * game_performance

            return int(self._game_performance_ratio * 100.0)
        except Exception as e:
            print(f"Calculate game performance score error: {e}")
            return 50

    def _cv2_to_qimage(self, frame: np.ndarray) -> QImage:
        """将 OpenCV 帧转换为 QImage"""
        try:
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        except Exception as e:
            print(f"CV2 to QImage error: {e}")
            # 返回一个空白图像
            return QImage(640, 480, QImage.Format_RGB888)

    def _cleanup(self):
        """清理资源"""
        try:
            # 释放摄像头
            if self._cap:
                try:
                    self._cap.release()
                except:
                    pass
                self._cap = None

            # 释放 MediaPipe
            if self._face_mesh:
                try:
                    self._face_mesh.close()
                except:
                    pass
                self._face_mesh = None

            # 发送完成信号
            self.finished.emit()
        except Exception as e:
            print(f"Cleanup error: {e}")