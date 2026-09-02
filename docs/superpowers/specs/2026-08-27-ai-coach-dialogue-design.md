# AI 教练对话（学生端）设计

日期：2026-08-27
状态：设计已与用户确认，实施中

## 背景与目标

AttentionTraining_v3.0 是 PySide6 注意力训练桌面应用。现有的"AI 分析"只在训练
结束后做一次性报告（`ui/training_window.py` → `ai/ai_analysis_manager.py` →
`ai/ai_thread_worker.py`，云端 LLM 或本地 ONNX 二选一），没有多轮对话能力。

目标：新增"AI 教练对话"——学生可以与 AI 教练进行多轮对话，教练能引用用户最近
的训练记录给出个性化建议；无 API Key 或断网时回退到本地 ONNX 分析模型生成回复。

已确认的决策：

1. 以 `ai/` 包作为底座，不依赖 `core/llm_client.py` 的既有调用链；
2. 将 `core/llm_client.py` 中已定义但未使用的 `advice_ready`、`report_ready`
   等信号并入 `ai/` 包并真正投入使用；
3. 先开放学生端：主窗口（主菜单）加入口；
4. 训练结束的分析报告对话框提供"继续咨询教练"快捷入口，携带刚结束的训练数据；
5. 可调用 API，也可调用本地 ONNX 分析模型（`LocalAnalysisEngine`）。

## 架构

```text
ui/main_window.py ──► ui/ai_coach_dialog.py（学生端入口）
ui/training_window.py ──► ui/ai_coach_dialog.py（报告页快捷入口 + 本次训练上下文）
                                 │
                                 ▼
                    ai/ai_coach.py（AICoachManager 单例 + AICoachWorker 线程）
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
      ai/coach_logic.py（纯逻辑：       云端 LLM API（OpenAI 兼容）
      提示词构建/历史裁剪/本地回复）            │
                    │                   超时/失败
                    ▼                         ▼
      core/database.py（coach_messages）  本地回退：LocalAnalysisEngine
      core/settings.py（复用 ai/* 配置）   （ONNX 模型，无模型走规则模板）
```

## 组件与接口

### `ai/coach_logic.py`（纯逻辑，不依赖 Qt，可单测）

- `build_system_prompt(session_context, recent_records, max_records=5)`：AI 教练
  人设 + 本次训练数据（如有）+ 最近训练记录摘要。
- `trim_history(messages, max_turns=20)`：保留最近 N 轮对话，防止上下文超长。
- `local_coach_reply(text, session_context, recent_records, analyzer=None)`
  返回 `(reply, kind)`：有数据时用 `LocalAnalysisEngine.analyze_session` 生成
  结构化报告（kind="report"）；无数据时返回规则化问候/建议（kind="advice"）。

### `ai/ai_coach.py`（Qt 服务层，镜像 AIAnalysisManager 的线程/队列模式）

- `AICoachWorker`：`process_message(username, text, session_context, history,
  recent_records, api_key, api_url, model)`；有 Key 时调 OpenAI 兼容 API，
  否则 `local_coach_reply`。信号：`message_ready(str)`、`message_error(str)`、
  `finished()`，以及并入的 `advice_ready(str)` / `report_ready(str)`。
- `AICoachManager` 单例：信号 `message_ready(int, str)`、`message_error(int, str)`、
  `advice_ready(str)`、`report_ready(str)`、`error_occurred(str)`、
  `request_finished(int)`；`submit_message(username, text, session_context=None)`、
  `cancel_request`、`clear_history(username)`、`load_history(username, limit)`、
  `cleanup()`。用户消息在提交时落库，助手回复在完成时落库。

### `core/database.py`

新增 `coach_messages` 表（`username, role, content, create_time`）与
`fetch_coach_messages / add_coach_message / clear_coach_messages`，沿用现有
`Database` 单例与 `_ensure_column` 迁移机制。

### `ui/ai_coach_dialog.py`

`AICoachDialog(QDialog)`：只读聊天区（QTextEdit）+ 输入框（QLineEdit）+
发送/清空按钮；打开时按当前用户加载历史；可接收 `session_context`（训练数据
字典）并自动发起首条咨询；请求期间禁用发送并显示"教练正在思考…"。

### 入口接线

- `ui/main_window.py`：`_add_role_specific_buttons` 中为学生角色新增
  "🤖 AI教练" 按钮。
- `ui/training_window.py`：训练分析报告对话框新增"🤖 继续咨询教练"按钮
  （学生可见），把本次训练指标作为 `session_context` 传给教练对话框。
- `main.py`：退出清理中追加 `AICoachManager.instance().cleanup()`。

## 数据流

1. 学生点击"AI教练"或报告页"继续咨询教练"，打开 `AICoachDialog`；
2. 对话框加载该用户最近对话历史并展示；
3. 发送消息 → `AICoachManager.submit_message`：用户消息先落库，携带历史 +
   最近 5 条训练记录入队；
4. `AICoachWorker` 在线程中执行：有 API Key → 多轮 messages 调 LLM；否则
   `local_coach_reply` 用最近数据走 ONNX/规则生成回复；
5. 回复经 `message_ready` 返回，助手回复落库，界面追加显示；
6. 失败/超时 → `message_error`，界面提示，不影响已保存的历史。

## 错误处理与回退

- API 超时（20s）/网络错误/非 200：给出中文错误提示，不落库；
- 无 API Key 或 `ai_enabled` 关闭：自动走本地 ONNX（`local_analysis_enabled`
  决定是否启用模型，模型缺失自动回退规则模板）；
- 无任何训练数据时：本地模式返回引导性问候与建议，避免空报告。

## 测试

- `tests/test_coach_logic.py`：提示词包含人设/上下文/历史；历史裁剪保留最近 N
  轮；本地回复在有数据时返回报告类文本、无数据时返回建议类文本。
- `tests/test_coach_db.py`：`coach_messages` 写入/读取/清空、顺序正确（临时 DB，
  不碰真实数据）。
- 冒烟：`QT_QPA_PLATFORM=offscreen` 下导入 `ai.ai_coach`、`ui.ai_coach_dialog`、
  `ui.main_window`、`ui.training_window`。

## 打包

- `pyproject.toml` `files` 与 `AttentionTrainingApp.spec` `hiddenimports` 增加
  `ai.ai_coach`、`ai.coach_logic`、`ui.ai_coach_dialog`（`dynamic_build.py` 会
  动态收集，静态清单同步更新）。
