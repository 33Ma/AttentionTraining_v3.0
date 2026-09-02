# ai/ai_thread_worker.py
import json
import requests
import threading
from typing import Optional
from PySide6.QtCore import QObject, Signal, QMutex, QMutexLocker, QThread, Slot
from .coach_logic import normalize_chat_completions_url


class AIThreadWorker(QObject):
    analysis_ready = Signal(str)
    analysis_error = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False
        self._mutex = QMutex()
        self._finished = False
        self._pending = None

    def set_request(self, request: dict):
        """保存待处理请求参数（线程启动前调用）。"""
        self._pending = request

    @Slot()
    def run_current(self):
        """由线程 started 信号调用，确保在工作线程内执行。"""
        if self._pending is None:
            return
        req, self._pending = self._pending, None
        self.process_training_analysis(
            req["avg_attention"], req["total_blinks"],
            req["max_consecutive_hits"], req["game_score"],
            req["game_mode"], req["duration_minutes"],
            req["api_key"], req["api_url"], req["model"],
            req["avg_gaze_score"], req["avg_gaze_distance"],
            req.get("difficulty", "normal"), req.get("face_detected"),
        )

    def process_training_analysis(self, avg_attention: int, total_blinks: int,
                                   max_consecutive_hits: int, game_score: int,
                                   game_mode: str, duration_minutes: int,
                                   api_key: str, api_url: str, model: str,
                                   avg_gaze_score: int = 0, avg_gaze_distance: float = 0.0,
                                   difficulty: str = "normal", face_detected: Optional[bool] = None):
        """处理训练分析"""
        if self._finished:
            return

        self._cancelled = False
        self._finished = False

        if not api_key:
            try:
                from ai.local_analysis import LocalAnalysisEngine
                from core.settings import GlobalSettings
                local_analysis = LocalAnalysisEngine.instance().analyze_session(
                    avg_attention, total_blinks, max_consecutive_hits,
                    game_score, game_mode, duration_minutes,
                    avg_gaze_score, avg_gaze_distance,
                    difficulty=difficulty,
                    face_detected=face_detected,
                    use_model=GlobalSettings().local_analysis_enabled(),
                )
                self.analysis_ready.emit(local_analysis)
            except Exception as e:
                self.analysis_error.emit(f"本地分析失败: {str(e)}")
            self.finished.emit()
            self._finished = True
            return

        # 构建提示词
        prompt = self._build_prompt(avg_attention, total_blinks, max_consecutive_hits,
                                    game_score, game_mode, duration_minutes,
                                    avg_gaze_score, avg_gaze_distance)

        # 发送请求
        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            }

            data = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': '你是注意力训练系统的AI教练，擅长分析训练数据并提供改进建议。请用中文回答，语气积极鼓励。'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.5,
                'max_tokens': 400
            }

            api_url = normalize_chat_completions_url(api_url)

            # 请求放到守护线程执行，工作线程轮询取消标记，保证取消能立即返回
            result_box = {}

            def _post():
                try:
                    result_box["response"] = requests.post(
                        api_url, headers=headers, json=data, timeout=30,
                    )
                except Exception as exc:
                    result_box["exception"] = exc

            post_thread = threading.Thread(target=_post, daemon=True)
            post_thread.start()
            print('[AI] worker posting url=' + str(api_url))
            while post_thread.is_alive():
                if self._cancelled or self._finished:
                    self.finished.emit()
                    self._finished = True
                    return
                post_thread.join(0.2)

            if "exception" in result_box:
                raise result_box["exception"]
            response = result_box["response"]
            print('[AI] worker http status=' + str(response.status_code))

            locker = QMutexLocker(self._mutex)
            try:
                if self._cancelled or self._finished:
                    self.finished.emit()
                    self._finished = True
                    return
            finally:
                locker.unlock()

            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                print('[AI] worker content len=' + str(len(content)))
                self.analysis_ready.emit(content)
            else:
                error_msg = f"API错误: {response.status_code}"
                try:
                    error_data = response.json()
                    if 'error' in error_data:
                        error_msg = error_data['error'].get('message', error_msg)
                except:
                    pass
                self.analysis_error.emit(error_msg)

        except requests.exceptions.Timeout:
            self.analysis_error.emit("请求超时，请检查网络连接")
        except requests.exceptions.ConnectionError:
            self.analysis_error.emit("网络连接错误")
        except Exception as e:
            self.analysis_error.emit(f"分析失败: {str(e)}")

        self.finished.emit()
        self._finished = True

    def cancel(self):
        """取消当前请求"""
        locker = QMutexLocker(self._mutex)
        self._cancelled = True
        locker.unlock()

    def _build_prompt(self, avg_attention: int, total_blinks: int,
                              max_consecutive_hits: int, game_score: int,
                              game_mode: str, duration_minutes: int,
                              avg_gaze_score: int = 0, avg_gaze_distance: float = 0.0) -> str:
                """构建提示词 - 增强版，包含注视数据"""
                mode_name = "找茬模式" if game_mode == "find_difference" else "动态追踪模式"

                # 评估等级
                if avg_attention >= 80:
                    attention_level = "非常专注"
                elif avg_attention >= 65:
                    attention_level = "比较专注"
                elif avg_attention >= 50:
                    attention_level = "专注度一般"
                elif avg_attention >= 35:
                    attention_level = "容易分心"
                else:
                    attention_level = "非常容易分心"

                # 眨眼评估
                blink_rate = total_blinks // duration_minutes if duration_minutes > 0 else total_blinks
                if blink_rate <= 12:
                    blink_assessment = "眨眼频率偏低，可能过于紧张或盯着屏幕太久"
                elif blink_rate <= 20:
                    blink_assessment = "眨眼频率正常，状态良好"
                elif blink_rate <= 30:
                    blink_assessment = "眨眼频率偏高，可能有些疲劳"
                else:
                    blink_assessment = "眨眼频率过高，明显疲劳，建议休息"

                # 连击评估
                if max_consecutive_hits >= 20:
                    combo_assessment = "惊人的连续命中能力！"
                elif max_consecutive_hits >= 15:
                    combo_assessment = "优秀的连击表现！"
                elif max_consecutive_hits >= 10:
                    combo_assessment = "不错的连击记录"
                elif max_consecutive_hits >= 5:
                    combo_assessment = "有一定连击基础"
                else:
                    combo_assessment = "连击较少，需要提高点击精准度"

                # 得分评估（满分基准按分钟线性放大：找茬 1 分钟 500，5 分钟 2500，10 分钟 5000）
                minutes = max(1, int(duration_minutes or 1))
                max_possible = (500 if game_mode == "find_difference" else 100) * minutes
                score_ratio = game_score / max_possible if max_possible > 0 else 0
                if score_ratio >= 0.8:
                    score_assessment = "游戏得分非常出色！"
                elif score_ratio >= 0.6:
                    score_assessment = "游戏得分良好"
                elif score_ratio >= 0.4:
                    score_assessment = "游戏得分中等，有提升空间"
                elif score_ratio >= 0.2:
                    score_assessment = "游戏得分偏低"
                else:
                    score_assessment = "游戏得分很低，可能需要调整策略"

                # 注视专注度评估
                if avg_gaze_score >= 90:
                    gaze_level = "🌟 非常专注"
                    gaze_suggestion = "你的视线非常稳定，这是极佳专注力的表现！继续保持！"
                elif avg_gaze_score >= 75:
                    gaze_level = "✨ 专注良好"
                    gaze_suggestion = "视线基本集中在屏幕中心，专注度不错！"
                elif avg_gaze_score >= 55:
                    gaze_level = "📈 专注一般"
                    gaze_suggestion = "视线偶尔会偏离屏幕中心，建议训练时保持视线在屏幕中心位置。"
                else:
                    gaze_level = "🎯 需要改进"
                    gaze_suggestion = "视线偏离较多，建议休息一下再继续训练，或调整坐姿保持正对屏幕。"

                gaze_distance_desc = ""
                if avg_gaze_distance < 0.1:
                    gaze_distance_desc = "（非常集中）"
                elif avg_gaze_distance < 0.2:
                    gaze_distance_desc = "（基本集中）"
                elif avg_gaze_distance < 0.3:
                    gaze_distance_desc = "（轻微偏移）"
                else:
                    gaze_distance_desc = "（偏移较多）"

                return f"""你是注意力训练教练。请根据以下训练数据，用温暖、鼓励的语气给出简短反馈。
                数据：平均注意力 {avg_attention}/100（{attention_level}）；眨眼 {total_blinks}次（{blink_assessment}）；最高连击 {max_consecutive_hits}次（{combo_assessment}）；游戏得分 {game_score}分（{score_assessment}）；模式 {mode_name}；时长 {duration_minutes}分钟；注视专注度 {avg_gaze_score}/100（{gaze_level}{gaze_distance_desc}）。
                
                请直接输出三部分，每部分1-2句话，全文不超过180字：
                ✨ 亮点：
                💡 建议：
                🌟 鼓励："""
    def generate_local_analysis(self, avg_attention: int, total_blinks: int,
                                    max_consecutive_hits: int, game_score: int,
                                    game_mode: str, duration_minutes: int,
                                    avg_gaze_score: int = 0, avg_gaze_distance: float = 0.0) -> str:
            """生成本地分析报告（当API不可用时）- 增强版包含注视数据"""
            mode_name = "找茬模式" if game_mode == "find_difference" else "动态追踪模式"

            # 注视相关评估
            if avg_gaze_score >= 90:
                gaze_level = "🌟 非常专注"
                gaze_suggestion = "视线非常稳定，展现了极佳的专注力！继续这样保持！"
            elif avg_gaze_score >= 75:
                gaze_level = "✨ 专注良好"
                gaze_suggestion = "视线基本集中在屏幕中心，专注度不错！"
            elif avg_gaze_score >= 55:
                gaze_level = "📈 专注一般"
                gaze_suggestion = "视线有轻微偏移，建议训练时尽量保持视线在屏幕中心。"
            else:
                gaze_level = "🎯 需要改进"
                gaze_suggestion = "视线偏离较多，建议休息一下再继续训练，保持正对屏幕的姿势。"

            gaze_distance_desc = ""
            if avg_gaze_distance < 0.1:
                gaze_distance_desc = "（非常集中，视线几乎未离开屏幕中心）"
            elif avg_gaze_distance < 0.2:
                gaze_distance_desc = "（良好，视线基本保持在屏幕中心附近）"
            elif avg_gaze_distance < 0.3:
                gaze_distance_desc = "（一般，有轻微视线偏移）"
            else:
                gaze_distance_desc = "（需要改善，视线经常离开屏幕中心）"

            analysis = "📊 训练数据概览\n"
            analysis += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            analysis += f"• 🧠 平均注意力分数：{avg_attention}/100\n"
            blink_rate = total_blinks / duration_minutes if duration_minutes > 0 else 0
            analysis += f"• 👁️ 每分钟眨眼次数：{int(round(blink_rate))}次（共{total_blinks}次）\n"
            analysis += f"• ⚡ 最高连击：{max_consecutive_hits}次\n"
            analysis += f"• 🎮 游戏得分：{game_score}分\n"
            analysis += f"• 🎲 游戏模式：{mode_name}\n"
            analysis += f"• ⏱️ 训练时长：{duration_minutes}分钟\n"
            analysis += f"• 👀 注视专注度：{avg_gaze_score}/100（{gaze_level}）{gaze_distance_desc}\n\n"

            analysis += "💡 分析建议\n"
            analysis += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

            if avg_attention >= 70:
                analysis += "✨ 注意力表现优秀！继续保持！\n"
            elif avg_attention >= 50:
                analysis += "📈 注意力表现良好，有提升空间\n"
            else:
                analysis += "🎯 注意力需要加强，建议在安静环境中训练\n"

            if max_consecutive_hits >= 15:
                analysis += "⚡ 连击能力很强！反应速度优秀！\n"
            elif max_consecutive_hits >= 8:
                analysis += "🎯 连击表现不错，继续练习会更好\n"
            else:
                analysis += "🎯 连击有待提高，建议先注重准确率再追求速度\n"

            # 注视相关建议
            analysis += f"\n👀 注视专注度分析：\n"
            analysis += f"   {gaze_suggestion}\n"

            if avg_gaze_distance >= 0.25:
                analysis += "   💡 建议：调整坐姿，确保正对屏幕，眼睛与屏幕保持适当距离。\n"
            elif avg_gaze_distance >= 0.15:
                analysis += "   💡 建议：尝试在训练中时刻提醒自己关注屏幕中心区域。\n"
            else:
                analysis += "   💡 建议：继续保持良好的注视习惯！\n"

            analysis += "\n🌟 下次训练建议\n"
            analysis += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            analysis += "• 保持规律的训练频率，每周3-4次\n"
            analysis += "• 训练前做5分钟深呼吸，帮助集中注意力\n"
            analysis += "• 每次训练后适当休息，避免眼部疲劳\n"
            analysis += "• 训练时保持正对屏幕，视线集中在屏幕中心区域\n"
            analysis += "• 如果感到疲劳，适当休息后再继续训练\n"

            return analysis