# 训练数据本地智能分析（ONNX Runtime）设计

日期：2026-08-26
状态：已获用户批准（方案 A），已实施

## 背景与目标

AttentionTraining_v3.0 是 PySide6 注意力训练桌面应用。训练结束后的"AI 分析"目前
依赖云端 OpenAI 兼容 API（API Key + 网络），未配置或断网时退回手写规则模板
（`ui/training_window.py` 的 `_generate_local_analysis`）。

目标：利用 onnxruntime 在本机完成训练数据智能分析——专注等级、疲劳等级、表现
等级，以及训练模式/难度推荐。模型不可用或运行时可导入失败时自动回退到规则模板，
保证现有 UI 与信号流不变。

## 方案选择

- 方案 A（采纳）：规则蒸馏小模型 → ONNX。用现有评分规则生成带标签合成数据，
  纯 numpy 训练微型 MLP，导出为 ONNX；推理走 onnxruntime。
- 方案 B（暂缓）：直接使用现有 23 条真实记录训练——样本太少、标签单一，待数据
  积累后可用同一训练脚本接入真实数据重训。
- 方案 C（不采用）：接入开源图像类 ONNX 模型——与结构化训练数据不匹配。

## 架构

```text
ui/training_window.py ──► ai/local_analysis.py（LocalAnalysisEngine 单例）
                              │
                              ├─ onnxruntime ─► models/session_analysis.onnx
                              │                      （专注5类/疲劳3类/表现5类）
                              ├─ onnxruntime ─► models/mode_recommend.onnx
                              │                      （模式2类/难度3类）
                              └─ 规则回退（模型缺失时，分级与推荐逻辑）
ai/ai_thread_worker.py ──► LocalAnalysisEngine（无 API Key 时本地分析）
core/llm_client.py ──► LocalAnalysisEngine.recommend_mode（AI 禁用时）
```

## 组件与接口

### `ai/local_analysis.py`

- `LocalAnalysisEngine`：线程安全单例；懒加载 onnxruntime 与模型 session 并缓存。
- `predict_session(...) -> Optional[Dict]`：模型推理，输出 attention_level（0-4）、
  fatigue（0-2）、performance（0-4）；模型不可用时返回 None。
- `analyze_session(...) -> str`：生成中文报告，与原有模板结构一致（数据概览、
  分析建议、综合评分、下次训练建议/目标），首行标注分析来源（ONNX 模型/规则）。
- `predict_recommend(history) -> Optional[Tuple[str, str]]`：模式+难度推荐。
- `recommend_mode(history) -> Tuple[str, str]`：推荐，模型不可用时回退规则。

输入特征（归一化到 0-1）：attention/100、眨眼频率/45、连击/30、得分率（按模式
满分 500/800）、时长/30、注视分/100、注视距离。

### 模型

- `models/session_analysis.onnx`：输入 7 维，隐藏 24，输出 3 个 Softmax 头
  （5/3/5），约 1.3KB 权重。
- `models/mode_recommend.onnx`：输入 6 维，隐藏 24，输出 2 个 Softmax 头（2/3）。
- 由 `tools/train_local_models.py` 从规则蒸馏生成（30k 合成样本，Adam，验证集
  准确率约 94% / 92.5%），可复现、可重训。

### 模型文件位置

`core/paths.py` 新增 `models_dir()`：开发时 `attention_training_py/models/`；
PyInstaller 打包后位于可执行文件旁的 `models/`（与用户数据目录约定一致）。
onnxruntime 依赖装于用户指定环境 `C:\Users\lenovo\AppData\Local\Programs\Python\Python311`。

## 集成点

1. `ui/training_window.py`：`_generate_local_analysis` 三处回退统一委托给
   `LocalAnalysisEngine.analyze_session`（未配置 Key / 请求失败 / 10 秒超时）。
2. `ai/ai_thread_worker.py`：无 API Key 分支由报错改为本地 ONNX 分析。
3. `core/llm_client.py`：`recommend_training_mode` 在 AI 禁用时改用本地引擎推荐。
4. `requirements.txt` 增加 `onnxruntime>=1.19`；`onnx` 仅训练脚本需要。
5. `AttentionTrainingApp.spec`：`models/` 作为 datas 打包，补充
   `ai.local_analysis`、`onnxruntime` hiddenimports。

## 验证

- 三个典型输入（高专注/明显疲劳/一般表现）：模型预测合理、输出确定。
- 现有 23 条真实训练记录全量推理，报告生成无异常。
- 模式推荐（真实/空历史）返回合法组合。
- 模型缺失时规则回退正常（`tools/verify_local_analysis.py` 覆盖以上用例）。

## 后续可扩展

- 数据积累后，用真实标注数据替换 `generate_*_samples` 重训（脚本与导出链路不变）。
- 可增加"趋势预测"序列模型（LSTM/TCN）与异常检测输出。

## 训练设置开关（2026-08-26 增补）

「训练设置 → 🤖 AI智能助手」新增复选框「启动本地模型分析」
（core/settings.py 持久化 i/local_analysis_enabled，默认开启）：

- 开启：训练报告优先走本地 ONNX 模型（无模型时回退规则），模式推荐同样本地化；
- 关闭：恢复原有流程——配置了云端 AI（启用 + API 密钥）时走 LLM API，
  否则使用规则模板（nalyze_session(use_model=False) / ecommend_mode(use_model=False)）。

## 摄像头实时检测增强（阶段1+2，2026-08-26 增补）

### 模型与驱动
- 人脸检测：YuNet（opencv_zoo face_detection_yunet_2023mar.onnx，约 232KB），
  经 cv2.FaceDetectorYN 驱动（OpenCV 5 DNN 的 ONNX Runtime 引擎，官方同款驱动）；
- 眨眼检测：OCEC ocec_s.onnx（约 494KB，F1≈0.994），onnxruntime Python API 直推，
  输入 24×40 单眼 RGB 裁剪，输出 prob_open；
- 模型位置：ttention_training_py/models/vision/，由
  	ools/download_vision_models.py 下载（GitHub 源，HuggingFace 不可达）。

### 架构
- camera/onnx_vision.py：ONNXVisionEngine 单例（懒加载 session、YuNet 检测、
  OCEC 双眼分类、crop_eye 裁剪）；
- camera/camera_worker.py：人脸判定可选 YuNet（无人脸时照旧扣分），眨眼可选
  OCEC（眼部裁剪来自 MediaPipe 眼轮廓中心，裁剪宽=瞳距×0.75、高=宽×0.6，
  开眼概率经滞回状态机计数眨眼，并映射为等效 EAR 参与注意力评分）；
- 任一模型缺失或加载失败自动回退 MediaPipe/EAR 既有逻辑，UI 信号不变。

### 训练设置开关
「训练设置 → 训练设置 → ONNX使用设置」新增：
- 人脸检测模型（YuNet）→ onnx/face_detection_enabled（默认 False）
- 眨眼检测模型（OCEC）→ onnx/blink_detection_enabled（默认 False）
状态标签实时显示模型文件是否就绪。

### 验证
- lena.jpg：YuNet 检测 box(208,183,146×207) score=0.909、5 关键点；
  OCEC 双眼开眼概率 1.000/0.940；
- CameraWorker 管线：ONNX 全开 attention=76，MediaPipe 回退 56，无脸 50；
- 	ools/verify_onnx_vision.py 可随时重跑。

## 摄像头实时检测增强（阶段3+4，2026-08-26 增补）

### 模型与驱动
- 头部姿态：6DRepNet（yakhyo/head-pose-estimation resnet18.onnx，约 44.7MB），
  onnxruntime 直推，输入 224×224 人脸裁剪（ImageNet 归一化），输出 3×3 旋转矩阵
  再转欧拉角（pitch/yaw/roll，度）；
- 视线估计：L2CS（yakhyo/gaze-estimation resnet18_gaze.onnx，约 45MB），
  onnxruntime 直推，输入 448×448 人脸裁剪，90 分箱 softmax 解码为 yaw/pitch（弧度）；
- 模型位置：ttention_training_py/models/vision/，由
  	ools/download_vision_models.py 下载（GitHub Releases 源）。

### 管线集成
- 重模型隔帧计算（每 3 帧一次，其余帧复用缓存），避免拖垮 30fps；
- 头部姿态：|yaw|*0.6 + |pitch|*0.4 折算惩罚分（上限 35），从注意力分数中扣除；
- 视线：由 (tan(yaw), tan(pitch)) 合成注视偏离距离，替换 MediaPipe 虹膜启发式；
- 任一模型缺失/失败自动回退原有虹膜视线/无惩罚，UI 信号不变。

### 训练设置开关（已移至「训练设置」主页）
「训练设置 → 训练设置 → ONNX使用设置」新增（4 个开关，默认关闭）：
- 人脸检测模型（YuNet）→ onnx/face_detection_enabled
- 眨眼检测模型（OCEC）→ onnx/blink_detection_enabled
- 头部姿态模型（6DRepNet）→ onnx/head_pose_enabled
- 视线估计模型（L2CS）→ onnx/gaze_enabled
状态标签实时显示 4 个模型是否就绪。

### 验证
- lena.jpg：头部姿态 yaw=-27.6°/pitch=-17.0°/roll=7.4°（符合图内转头角度）；
  视线 yaw=-13.9°/pitch=-2.1°；
- CameraWorker 全开：attention=54（含头部姿态惩罚），MediaPipe 回退 56，无脸 50；
- 	ools/verify_onnx_vision.py 覆盖四阶段全链路。
