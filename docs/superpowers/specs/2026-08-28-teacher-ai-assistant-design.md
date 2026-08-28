# 教师端 AI 助教（AI 教学助手）设计

日期：2026-08-28
状态：设计已与用户确认，待用户审阅书面规格后进入实现计划

## 背景与目标

AttentionTraining_v3.0 是 PySide6 注意力训练桌面应用。学生端已有"AI 教练"多轮
对话（`ui/ai_coach_dialog.py` → `ai/ai_coach.py` → `ai/coach_logic.py`，
云端 LLM 或本地规则回退二选一，历史存 `coach_messages` 表）。教师端目前只有
`ui/teacher_report_dialog.py` 的静态班级报告（表格、图表、规则生成文本报告），
不能多轮提问，也无法针对"某个学生怎么样""哪些学生需要关注"做对话式分析。

目标：新增教师端专属"AI 助教"，形式与学生端 AI 教练一致（聊天对话框 + 多轮
历史 + 云端/本地双通道），以班级学生训练数据为上下文，支持班级整体分析和单个
学生下钻，并给出可操作的教学建议。

## 已确认的决策

1. 采用方案 A：完整镜像学生端架构，新增服务层、纯逻辑层、聊天对话框三个模块，
   另抽取班级汇总纯逻辑模块，共四个新文件；
   不新训班级级 ONNX 模型（现有两个 ONNX 模型为单次训练粒度，班级级分析用
   统计规则模板即可），不改造 `ai/ai_coach.py`（学生端在制品不触碰）。
2. 分析范围：班级整体 + 单个学生下钻都支持（用户已确认）。
3. 入口：主窗口"🤖 AI 助教"按钮 + 班级报告窗口"🤖 咨询AI助教"按钮
   （用户已确认）。
4. 可用角色：TEACHER 与 ADMIN；数据范围与班级报告一致——教师看自己的学生，
   admin 看全部学生。
5. 历史复用 `coach_messages` 表（按 username 区分，教师对话与学生对话天然
   隔离），不新增表。
6. 云端调用复用 `GlobalSettings` 的 API Key/URL/模型与 `ai_enabled`；
   无 Key/断网/关闭时走本地规则分析（`local_analysis_enabled` 语义不适用
   班级级，本地始终用统计规则模板）。
7. 把 `TeacherReportDialog` 内嵌的汇总/进步/归一分逻辑抽取为可复用纯函数模块
   `ai/teacher_report_logic.py`，报告窗口与 AI 助教共用，行为保持不变。

## 范围外（不做）

- 班级级 ONNX/机器学习模型训练与推理；
- 重构 `ai/ai_coach.py` / `ai/coach_logic.py`（仅复用其纯函数）；
- 新增数据表或迁移；
- 新增导出/可视化能力（班级报告已有 CSV 与图表）。

## 架构

```text
ui/main_window.py ─────▶ ui/teacher_coach_dialog.py（教师端入口）
ui/teacher_report_dialog.py ─▶ ui/teacher_coach_dialog.py（携带班级上下文）
                                  │
                                  ▼
                     ai/teacher_coach.py（TeacherCoachManager 单例 + Worker 线程）
                                  │                │
                  ai/teacher_coach_logic.py        云端 LLM API（复用 GlobalSettings）
                  纯逻辑：班级上下文、提示词、       │
                  本地规则回复（班级/单学生/        超时/失败
                  风险学生/教学建议/知识问答）       │
                                  │               本地回退：本地规则分析
                     ai/teacher_report_logic.py（班级汇总纯函数）
                     core/database.py（coach_messages 复用）
                     core/user_manager.py（教师→学生列表）
                     ai/composite_scoring.py（综合分/归一分复用）
```

## 组件与接口

### `ai/teacher_report_logic.py`（新增，纯逻辑，无 Qt）

从 `ui/teacher_report_dialog.py` 抽取，行为保持不变：

- `normalized_game_score(record) -> float`：游戏得分归一到 0-100
  （原 `_normalized_game_score`，委托 `ai/composite_scoring.score_ratio`）。
- `composite_improvement(records) -> float`：按综合分计算进步幅度，截断到
  ±100（原 `_composite_improvement`）。
- `compute_class_summaries(students, records_map, filter_days=0)
  -> (List[Dict], Dict)`：输入为纯数据（学生信息 + 用户名→记录列表 + 时间
  过滤天数），输出每名学生摘要（姓名/训练次数/总时长/平均与最高注意力/
  平均游戏分/综合分/成就数/进步幅度/最近训练）与班级统计（学生数/总训练次数/
  总时长/平均注意力/平均综合分/进步与退步人数/最佳与需关注学生）。
- `format_duration(minutes) -> str`：时长文本化（原 `_format_duration`）。

`TeacherReportDialog` 改为调用这些函数；原有 `_normalized_game_score` 与
`_composite_improvement` 静态方法保留为薄封装，保证现有测试
（`tests/test_teacher_report_logic.py`）无需改动即可继续通过。

### `ai/teacher_coach_logic.py`（新增，纯逻辑，无 Qt，可单测）

- `build_teacher_system_prompt(class_context) -> str`：AI 助教人设 + 班级上下文
  块。人设要点：你是"注意力训练系统"的班级教学助手，风格专业、具体、可操作，
  始终中文回复；区分意图——知识性问题直接回答，只有用户要求分析数据时才输出
  结构化分析。
- `format_class_context(summaries, stats) -> str`：把摘要格式化为提示词上下文，
  单学生一行（姓名、训练次数、平均注意力、综合分、进步、最近训练），附班级统计。
- `local_teacher_reply(text, class_context) -> (reply, kind)`：无云端时的本地
  回复。意图识别顺序：
  1. 班级整体分析（"班级/整体/全班" + "分析/表现/数据/情况"等）→ 结构化班级
     报告（复用并扩展报告窗口的规则模板），kind="report"；
  2. 单学生查询（文本中匹配到班级内的学生姓名/显示名）→ 该生摘要 + 针对性建议，
     kind="advice"；
  3. 风险/需关注学生（"退步/需要关注/风险/落后"等）→ 列出退步或低综合分学生及
     建议，kind="report"；
  4. 教学建议（"建议/教学/干预/怎么帮"等）→ 基于班级统计的规则建议，
     kind="advice"；
  5. 知识问答（训练频率、如何帮注意力差的学生、两种模式区别等）→ 教师向知识
     回复，kind="advice"；
  6. 问候/感谢/兜底 → 引导性回复；无法识别且本地无数据时提示可用提问方向。
- 复用 `ai/coach_logic` 的 `trim_history`、`normalize_chat_completions_url`。
- 上下文上限：最多 40 名学生、每名学生最近 10 条记录，防止提示词超长。

### `ai/teacher_coach.py`（新增，Qt 服务层，镜像 AICoachManager 模式）

- `TeacherCoachWorker(QObject)`：`process_message(username, text, class_context,
  history, api_key, api_url, model)`。有 Key 时走 OpenAI 兼容
  `/chat/completions`（复用 `coach_logic` 的 URL 规范化与超时/取消逻辑）；
  否则 `local_teacher_reply`。信号：`message_ready(str)`、`message_error(str)`、
  `local_fallback_ready(str)`、`advice_ready(str)`、`report_ready(str)`、
  `finished()`。
- `TeacherCoachManager(QObject)` 单例：信号 `message_ready(int, str)`、
  `message_error(int, str)`、`local_fallback_ready(int, str)`、
  `advice_ready(str)`、`report_ready(str)`、`error_occurred(str)`、
  `request_finished(int)`。
  - `submit_message(username, text, class_context=None, force_cloud=False,
    save_user_message=True) -> int`：用户消息先落库，携带历史与班级上下文入队；
    无 Key 且非 force_cloud 时自动本地回退。
  - `_build_class_context(username)`：按角色取学生列表（TEACHER →
    `get_students_by_teacher`，ADMIN → `get_students`），用
    `Database().fetch_training_records` 取记录，调 `compute_class_summaries`
    生成上下文；记录不足时返回空上下文。
  - `load_history / clear_history`：委托 `Database().fetch_coach_messages /
    clear_coach_messages`（按教师用户名）。
  - `cancel_request / cancel_all_requests / cleanup`：镜像学生端实现。
- 与 `ai/ai_coach.py` 的差异仅限上下文来源与本地回复函数；不修改学生端文件。

### `ui/teacher_coach_dialog.py`（新增，镜像 AICoachDialog）

`TeacherCoachDialog(QDialog)`：只读聊天区（QTextEdit）、输入框（QLineEdit）、
发送/取消请求/清空对话按钮；打开时按当前用户名加载历史；可接收
`class_context`（班级汇总字典）并在打开时自动发起首条咨询："请结合班级数据，
分析整体情况并给出教学建议。"；请求期间禁用发送并显示"助教正在思考…"；
本地无法回答时沿用"是否改用云端大语言模型"的提示模式；样式与 AI 教练一致
（标题"🤖 AI助教 · 班级数据分析助手"）。

## 入口接线

- `ui/main_window.py`：`_add_role_specific_buttons` 中为 TEACHER/ADMIN 新增
  "🤖 AI助教"按钮（在"班级报告"下方，独立配色如 #9C27B0），点击打开
  `TeacherCoachDialog`；`_on_teacher_coach` 处理异常提示。
- `ui/teacher_report_dialog.py`：控制栏新增"🤖 咨询AI助教"按钮；点击时把当前
  时间范围下的 `summaries` 与班级统计打包为 `class_context` 传给对话框并自动
  首问。
- `main.py`：退出清理中追加 `TeacherCoachManager.instance().cleanup()`。

## 数据流

1. 教师点击"🤖 AI助教"（或报告页"咨询AI助教"），打开 `TeacherCoachDialog`，
   加载该教师的对话历史；
2. 发送消息 → `TeacherCoachManager.submit_message`：用户消息落库，按角色实时
   汇总班级上下文，连同历史入队；
3. `TeacherCoachWorker` 在线程中执行：有 API Key → 多轮 messages 调云端 LLM
   （system 含人设 + 班级上下文）；否则 `local_teacher_reply` 走规则模板；
4. 回复经 `message_ready` 返回并落库、界面追加显示；
5. 失败/超时 → `message_error`，界面提示，不影响已保存历史。

## 错误处理与回退

- API 超时（连接 10s / 读取 20s）、断网、非 200、响应格式错误：中文错误提示，
  不落库；
- 无 API Key 或 `ai_enabled` 关闭：自动本地规则回复；
- 无任何班级数据：本地返回引导性回复（建议先让学生完成训练），不输出空报告；
- 本地无法回答：沿用学生端 `local_fallback_ready` 模式，询问是否改用云端
  大语言模型（force_cloud 重发，不重复落库）。

## 测试

- `tests/test_teacher_report_logic.py`：现有用例保持不变；新增
  `compute_class_summaries` 的聚合、时间过滤、空数据、进步幅度用例（临时 DB 或
  纯 dict 数据，不碰真实数据）。
- `tests/test_teacher_coach_logic.py`（新增）：提示词包含人设与班级上下文；
  本地回复按意图分类——班级分析返回 kind="report"、单学生/风险学生/教学建议/
  知识问答返回 kind="advice"、无数据返回引导语；学生姓名匹配命中班级内学生。
- 冒烟：`QT_QPA_PLATFORM=offscreen` 下导入 `ai.teacher_coach`、
  `ai.teacher_coach_logic`、`ai.teacher_report_logic`、`ui.teacher_coach_dialog`、
  `ui.main_window`、`ui.teacher_report_dialog`。

## 打包

`pyproject.toml` `files` 与 `AttentionTrainingApp.spec` `hiddenimports` 增加：
`ai.teacher_coach`、`ai.teacher_coach_logic`、`ai.teacher_report_logic`、
`ui.teacher_coach_dialog`（`dynamic_build.py` 动态收集，静态清单同步更新）。
