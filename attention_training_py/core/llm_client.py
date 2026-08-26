# core/llm_client.py
import json
import requests
from typing import Optional, Dict, Any, List
from queue import Queue
from PySide6.QtCore import QObject, Signal, QMutex, QMutexLocker, QMetaObject, Qt, QTimer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtCore import QUrl, QByteArray, QJsonDocument

from .settings import GlobalSettings


class LLMClient(QObject):
    """LLM 客户端 - 用于与各种 AI API 通信"""

    analysis_text_ready = Signal(str)
    analysis_ready = Signal(str)
    advice_ready = Signal(str)
    recommendation_ready = Signal(str, str)
    report_ready = Signal(str)
    error_occurred = Signal(str)
    request_finished = Signal()

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

        self._network_manager = QNetworkAccessManager()
        self._api_key = ""
        self._api_url = "https://api.openai.com/v1/chat/completions"
        self._model = "gpt-3.5-turbo"
        self._enabled = False
        self._timeout_timer = QTimer()
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(30000)
        self._timeout_timer.timeout.connect(self._on_timeout)

        self._mutex = QMutex()
        self._reply_callbacks = {}
        self._reply_request_ids = {}
        self._active_replies = []
        self._current_request_id = 0

        # 从 GlobalSettings 更新配置
        self._update_config_from_global()

    def _update_config_from_global(self):
        """从 GlobalSettings 同步配置"""
        settings = GlobalSettings()
        self._api_key = settings.api_key()
        self._api_url = settings.api_url()
        self._model = settings.ai_model()
        self._enabled = settings.ai_enabled()

        print(f"LLMClient config updated: URL={self._api_url}, Model={self._model}, Enabled={self._enabled}")

    def set_api_key(self, key: str):
        locker = QMutexLocker(self._mutex)
        self._api_key = key

    def set_api_url(self, url: str):
        locker = QMutexLocker(self._mutex)
        self._api_url = url

    def set_model(self, model: str):
        locker = QMutexLocker(self._mutex)
        self._model = model

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def cancel_all_requests(self):
        """取消所有请求"""
        locker = QMutexLocker(self._mutex)
        replies_copy = self._active_replies.copy()
        for reply in replies_copy:
            if reply and not reply.isFinished():
                reply.disconnect()
                reply.abort()

        self._active_replies.clear()
        self._reply_callbacks.clear()
        self._reply_request_ids.clear()

    def cancel_all_requests_and_wait(self):
        """取消所有请求并等待完成"""
        self.cancel_all_requests()
        # 简单等待
        import time
        time.sleep(0.1)

        # core/llm_client.py - 修改 analyze_training_data 方法

    def analyze_training_data(self, avg_attention: int, total_blinks: int,
                                       max_consecutive_hits: int, game_score: int,
                                       game_mode: str, duration_minutes: int,
                                       avg_gaze_score: int = 0, avg_gaze_distance: float = 0.0):
                """分析训练数据 - 增强版提示词，包含注视数据"""
                if not self._enabled:
                    self.analysis_text_ready.emit("AI分析未启用，请在设置中配置API密钥后启用。")
                    return

                if not self._api_key:
                    self.analysis_text_ready.emit("请先在设置中配置API密钥以使用AI分析功能。")
                    return

                # 计算个性化指标
                attention_level = self._get_attention_level(avg_attention)
                blink_rate = total_blinks // duration_minutes if duration_minutes > 0 else total_blinks
                blink_status = self._get_blink_status(blink_rate)
                mode_name = "找茬模式" if game_mode == "find_difference" else "动态追踪模式"

                # 注视相关指标
                if avg_gaze_score >= 90:
                    gaze_level = "🌟 非常专注"
                    gaze_recommendation = "你的视线非常稳定，显示出了极佳的专注力！"
                elif avg_gaze_score >= 75:
                    gaze_level = "✨ 专注良好"
                    gaze_recommendation = "你的视线基本保持在屏幕中心，专注度不错！"
                elif avg_gaze_score >= 55:
                    gaze_level = "📈 专注一般"
                    gaze_recommendation = "视线有轻微偏移，建议训练时尽量保持视线在屏幕中心。"
                else:
                    gaze_level = "🎯 需要改进"
                    gaze_recommendation = "视线偏离较多，可能注意力分散或疲劳，建议适当休息。"

                gaze_distance_desc = ""
                if avg_gaze_distance < 0.1:
                    gaze_distance_desc = "（非常集中，视线几乎未离开屏幕中心）"
                elif avg_gaze_distance < 0.2:
                    gaze_distance_desc = "（良好，视线基本保持在屏幕中心附近）"
                elif avg_gaze_distance < 0.3:
                    gaze_distance_desc = "（一般，有轻微视线偏移）"
                else:
                    gaze_distance_desc = "（需要改善，视线经常离开屏幕中心）"

                # 增强版提示词
                prompt = f"""你是一位专业的注意力训练私人教练。请根据以下数据生成一份温暖、个性化的训练分析报告：

        【用户本次训练数据】
        - 注意力分数：{avg_attention}/100（等级：{attention_level}）
        - 眨眼次数：{total_blinks}次（频率：{blink_rate}次/分钟，状态：{blink_status}）
        - 最高连击：{max_consecutive_hits}次
        - 游戏得分：{game_score}分
        - 游戏模式：{mode_name}
        - 训练时长：{duration_minutes}分钟
        - 注视专注度：{avg_gaze_score}/100（{gaze_level}）
        - 视线偏离距离：{avg_gaze_distance:.3f}{gaze_distance_desc}

        【注视专注度说明】
        注视专注度是通过眼睛聚焦点到屏幕中心的距离计算得出的指标：
        - 90-100分：视线高度集中，几乎未离开屏幕中心
        - 75-89分：视线基本集中在屏幕中心区域
        - 55-74分：视线有轻微偏移，需要改善
        - 0-54分：视线偏移较多，注意力可能分散

        请用温暖鼓励的语气生成报告，包含：
        1. 一个亲切的称呼和开场白
        2. 2-3个具体的亮点肯定（要结合数据，包括注视表现）
        3. 1-2个温柔的改进建议（包括注视专注度的建议）
        4. 3个具体可执行的行动建议（包括注视训练建议）
        5. 一个充满正能量的结束语

        要求：
        - 使用"你"来称呼用户，像朋友一样交流
        - 避免负面批评，用建设性语言表达
        - 建议要具体、可操作
        - 总字数控制在300-500字
        - 适当使用emoji增加亲和力

        现在请以私人教练的身份写出这份报告："""

                self._send_request(prompt, "analysis")

    def generate_personalized_advice(self, attention_score: int, blink_count: int):
        """生成个性化建议"""
        if not self._enabled or not self._api_key:
            return

        prompt = f"注意力分数：{attention_score}/100，眨眼次数：{blink_count}次。\n给出简短鼓励或建议（30字以内）。"
        self._send_request(prompt, "advice")

    def recommend_training_mode(self, history: List[Dict[str, Any]]):
        """推荐训练模式"""
        if not self._enabled or not self._api_key:
            try:
                from ai.local_analysis import LocalAnalysisEngine
                from core.settings import GlobalSettings
                use_model = GlobalSettings().local_analysis_enabled()
                mode, difficulty = LocalAnalysisEngine.instance().recommend_mode(history, use_model=use_model)
                self.recommendation_ready.emit(mode, difficulty)
            except Exception:
                self.recommendation_ready.emit("find_difference", "Normal")
            return

        prompt = "根据以下训练历史，推荐最适合的游戏模式（find_difference或dynamic_tracking）和难度（Easy/Normal/Hard）：\n\n"
        for record in history[-5:]:  # 只取最近5条
            prompt += f"- 模式: {record.get('game_mode', 'unknown')}, "
            prompt += f"注意力: {record.get('avg_attention', 0)}, "
            prompt += f"得分: {record.get('game_score', 0)}\n"

        prompt += "\n只返回格式：模式|难度，例如：find_difference|Normal"

        self._send_request(prompt, "recommend")

    def generate_weekly_report(self, records: List[Dict[str, Any]]):
        """生成周报告"""
        if not self._enabled or not self._api_key:
            return

        prompt = "生成这周的训练总结报告，包括进步、成就和建议。\n\n"
        for record in records:
            prompt += f"- {record.get('date', '')}: 注意力{record.get('avg_attention', 0)}, "
            prompt += f"得分{record.get('game_score', 0)}\n"

        self._send_request(prompt, "report")

    def update_config_from_global(self):
        """从 GlobalSettings 更新配置"""
        self._update_config_from_global()

    def _get_attention_level(self, score: int) -> str:
        if score >= 80:
            return "卓越"
        elif score >= 65:
            return "优秀"
        elif score >= 50:
            return "良好"
        elif score >= 35:
            return "及格"
        else:
            return "待提升"

    def _get_blink_status(self, rate: int) -> str:
        if rate <= 15:
            return "正常"
        elif rate <= 25:
            return "偏高"
        else:
            return "过高"

    def _send_request(self, prompt: str, callback_type: str):
        """发送请求到 LLM API"""
        if not self._api_key:
            if callback_type == "analysis":
                self.analysis_text_ready.emit("API密钥未设置，请在设置中配置。")
            self.error_occurred.emit("API密钥未设置")
            self.request_finished.emit()
            return

        # 构建请求体
        request_data = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是热情、专业、富有同理心的注意力训练私人教练。你的风格温暖亲切，善于发现用户的进步，给出建设性建议。永远使用积极正面的语言。用中文回复。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.75,
            "max_tokens": 800
        }

        # 创建网络请求
        request = QNetworkRequest()
        request.setUrl(QUrl(self._api_url))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Authorization", f"Bearer {self._api_key}".encode())

        json_data = QJsonDocument(json.loads(json.dumps(request_data))).toJson()

        reply = self._network_manager.post(request, json_data)

        # 生成请求ID
        request_id = self._current_request_id + 1
        self._current_request_id = request_id

        locker = QMutexLocker(self._mutex)
        self._reply_callbacks[reply] = callback_type
        self._reply_request_ids[reply] = request_id
        self._active_replies.append(reply)

        self._timeout_timer.start()

        # 连接信号
        reply.finished.connect(self._on_reply_finished)

    def _on_reply_finished(self):
        """处理回复完成"""
        reply = self.sender()
        if not reply:
            return

        self._timeout_timer.stop()

        callback_type = ""
        request_id = -1

        locker = QMutexLocker(self._mutex)
        if reply in self._active_replies:
            self._active_replies.remove(reply)
        callback_type = self._reply_callbacks.pop(reply, "")
        request_id = self._reply_request_ids.pop(reply, -1)

        if reply.error() != QNetworkReply.NoError:
            error_msg = self._get_error_message(reply)
            self._emit_error(callback_type, error_msg)
            reply.deleteLater()
            return

        response_data = reply.readAll()
        reply.deleteLater()

        try:
            doc = QJsonDocument.fromJson(response_data)
            if doc.isNull():
                self._emit_error(callback_type, "无效的JSON响应")
                return

            obj = doc.object()
            if not obj.contains("choices"):
                self._emit_error(callback_type, "响应格式错误")
                return

            choices = obj["choices"].toArray()
            if choices.isEmpty():
                self._emit_error(callback_type, "没有选择结果")
                return

            content = choices[0].toObject()["message"].toObject()["content"].toString()
            self._handle_response(callback_type, content)

        except Exception as e:
            self._emit_error(callback_type, f"解析响应失败: {str(e)}")

        self.request_finished.emit()

    def _get_error_message(self, reply: QNetworkReply) -> str:
        """获取错误信息"""
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        error_string = reply.errorString()

        if status_code == 404:
            return f"API地址错误 (404)\n\n请检查API地址是否正确：\n当前使用的地址：{self._api_url}\n请在设置中修正API地址。"
        elif status_code == 401:
            return "API密钥错误 (401)\n\n请检查API密钥是否正确配置。"
        elif status_code == 429:
            return "请求过于频繁 (429)\n\nAPI调用频率超限，请稍后再试。"
        elif reply.error() == QNetworkReply.OperationCanceledError:
            return "请求已取消"
        else:
            return f"网络错误: {error_string} (状态码: {status_code})"

    def _emit_error(self, callback_type: str, error_msg: str):
        """发送错误信号"""
        if callback_type == "analysis":
            self.analysis_text_ready.emit(error_msg)
        self.error_occurred.emit(error_msg)
        self.request_finished.emit()

    def _handle_response(self, callback_type: str, content: str):
        """处理响应"""
        if callback_type == "analysis":
            self.analysis_ready.emit(content)
            self.analysis_text_ready.emit(content)
        elif callback_type == "advice":
            self.advice_ready.emit(content)
        elif callback_type == "recommend":
            self._parse_recommendation(content)
        elif callback_type == "report":
            self.report_ready.emit(content)

    def _parse_recommendation(self, content: str):
        """解析推荐结果"""
        if "find_difference" in content:
            difficulty = "Hard" if "Hard" in content else "Easy" if "Easy" in content else "Normal"
            self.recommendation_ready.emit("find_difference", difficulty)
        elif "dynamic_tracking" in content:
            difficulty = "Hard" if "Hard" in content else "Easy" if "Easy" in content else "Normal"
            self.recommendation_ready.emit("dynamic_tracking", difficulty)
        else:
            self.recommendation_ready.emit("find_difference", "Normal")

    def _on_timeout(self):
        """超时处理"""
        locker = QMutexLocker(self._mutex)
        replies_copy = self._active_replies.copy()
        for reply in replies_copy:
            if reply and not reply.isFinished():
                reply.disconnect()
                reply.abort()
                callback_type = self._reply_callbacks.pop(reply, "")
                if callback_type == "analysis":
                    self.analysis_text_ready.emit("AI分析超时，请检查网络连接后重试。")
                self.error_occurred.emit("请求超时")
                self.request_finished.emit()

        self._active_replies.clear()
        self._reply_callbacks.clear()
        self._reply_request_ids.clear()

    def generate_local_analysis(self, avg_attention: int, total_blinks: int,
                                max_consecutive_hits: int, game_score: int,
                                game_mode: str, duration_minutes: int) -> str:
        """生成本地分析报告（当API不可用时）"""
        mode_name = "找茬模式" if game_mode == "find_difference" else "动态追踪模式"

        analysis = "📊 训练数据概览\n"
        analysis += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        analysis += f"• 平均注意力分数：{avg_attention}/100\n"
        analysis += f"• 总眨眼次数：{total_blinks}次\n"
        analysis += f"• 最高连击：{max_consecutive_hits}次\n"
        analysis += f"• 游戏得分：{game_score}分\n"
        analysis += f"• 游戏模式：{mode_name}\n"
        analysis += f"• 训练时长：{duration_minutes}分钟\n\n"

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

        analysis += "\n🌟 下次训练建议\n"
        analysis += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        analysis += "• 保持规律的训练频率，每周3-4次\n"
        analysis += "• 训练前做5分钟深呼吸，帮助集中注意力\n"
        analysis += "• 每次训练后适当休息，避免眼部疲劳\n"

        return analysis