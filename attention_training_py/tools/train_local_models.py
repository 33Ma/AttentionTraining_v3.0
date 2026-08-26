# -*- coding: utf-8 -*-
"""从现有评分规则蒸馏训练本地 ONNX 小模型。

用法（需要 onnx 与 numpy，建议使用项目 Python 3.11 环境）：
    python tools/train_local_models.py

生成：
    attention_training_py/models/session_analysis.onnx   （专注/疲劳/表现分级）
    attention_training_py/models/mode_recommend.onnx     （模式/难度推荐）

训练数据由规则自动生成（规则蒸馏），因此无需人工标注；当积累到足够真实
标注数据后，可把 generate_*_samples 换成真实数据再训练。
"""

import os
from typing import List, Sequence, Tuple

import numpy as np


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(ROOT, "models")


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


# ----------------------------------------------------------------------
# 规则（与 ai/local_analysis.py 中的回退规则保持一致）
# ----------------------------------------------------------------------
def rule_attention(att: float) -> int:
    if att >= 80:
        return 4
    if att >= 65:
        return 3
    if att >= 50:
        return 2
    if att >= 35:
        return 1
    return 0


def rule_fatigue(blink_rate: float) -> int:
    if blink_rate < 4 or blink_rate > 30:
        return 2
    if blink_rate < 8 or blink_rate > 20:
        return 1
    return 0


def rule_performance(score_ratio: float) -> int:
    if score_ratio >= 0.8:
        return 4
    if score_ratio >= 0.6:
        return 3
    if score_ratio >= 0.4:
        return 2
    if score_ratio >= 0.2:
        return 1
    return 0


# ----------------------------------------------------------------------
# 合成样本生成
# ----------------------------------------------------------------------
def generate_session_samples(n: int, rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray]:
    """生成会话分析样本：7 维输入，13 维 one-hot（专注5 + 疲劳3 + 表现5）。"""
    X = np.empty((n, 7), dtype=np.float32)
    Y = np.zeros((n, 13), dtype=np.float32)
    for i in range(n):
        attention = rng.uniform(0, 100)
        blink_rate = rng.uniform(0, 45)
        combo = rng.uniform(0, 30)
        score_ratio = rng.uniform(0, 1.05)
        duration = rng.uniform(1, 30)
        gaze_score = rng.uniform(0, 100)
        gaze_distance = rng.uniform(0, 0.6)

        X[i] = [
            clamp(attention / 100.0, 0, 1),
            clamp(blink_rate / 45.0, 0, 1),
            clamp(combo / 30.0, 0, 1),
            clamp(score_ratio, 0, 1),
            clamp(duration / 30.0, 0, 1),
            clamp(gaze_score / 100.0, 0, 1),
            clamp(gaze_distance, 0, 1),
        ]

        a = rule_attention(attention)
        f = rule_fatigue(blink_rate)
        p = rule_performance(score_ratio)
        # 少量标签噪声，让模型学到平滑边界而不是死记阈值
        if rng.random() < 0.06:
            a = int(clamp(a + int(rng.choice([-1, 1])), 0, 4))
        if rng.random() < 0.06:
            f = int(clamp(f + int(rng.choice([-1, 1])), 0, 2))
        if rng.random() < 0.06:
            p = int(clamp(p + int(rng.choice([-1, 1])), 0, 4))

        Y[i, a] = 1.0
        Y[i, 5 + f] = 1.0
        Y[i, 8 + p] = 1.0
    return X, Y


def generate_recommend_samples(n: int, rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray]:
    """生成模式/难度推荐样本：6 维输入，5 维 one-hot（模式2 + 难度3）。"""
    X = np.empty((n, 6), dtype=np.float32)
    Y = np.zeros((n, 5), dtype=np.float32)
    for i in range(n):
        mean_att = clamp(rng.normal(55, 22), 5, 100)
        mean_ratio = clamp(rng.normal(mean_att / 100.0 * 0.75, 0.2), 0, 1)
        trend_att = clamp(rng.normal(0, 8), -25, 25) / 50.0
        trend_ratio = clamp(rng.normal(0, 0.08), -0.3, 0.3)
        n_sess = rng.uniform(1, 20)
        last_mode = float(rng.choice([0.0, 1.0]))

        X[i] = [
            clamp(mean_att / 100.0, 0, 1),
            clamp(mean_ratio, 0, 1),
            clamp(0.5 + trend_att, 0, 1),
            clamp(0.5 + trend_ratio, 0, 1),
            clamp(n_sess / 20.0, 0, 1),
            last_mode,
        ]

        # 规则标签
        if mean_att >= 75 and mean_ratio >= 0.6:
            mode, diff = 1, 2
        elif mean_att >= 70:
            mode, diff = 1, 1
        elif mean_att >= 50:
            mode = 1 if mean_ratio >= 0.6 else 0
            diff = 1
        else:
            mode, diff = 0, 0

        # 趋势修正
        if trend_att > 0.1 and diff < 2:
            diff += 1
        if trend_att < -0.2 and diff > 0:
            diff -= 1

        if rng.random() < 0.05:
            mode = 1 - mode
        if rng.random() < 0.05:
            diff = int(clamp(diff + int(rng.choice([-1, 1])), 0, 2))

        Y[i, mode] = 1.0
        Y[i, 2 + diff] = 1.0
    return X, Y


# ----------------------------------------------------------------------
# 微型 MLP（纯 numpy，无 sklearn 依赖）
# ----------------------------------------------------------------------
class MLP:
    def __init__(self, d_in: int, d_hidden: int, d_out: int, rng: np.random.Generator):
        self.W1 = rng.normal(0, np.sqrt(2.0 / d_in), (d_in, d_hidden)).astype(np.float32)
        self.b1 = np.zeros(d_hidden, dtype=np.float32)
        self.W2 = rng.normal(0, np.sqrt(2.0 / d_hidden), (d_hidden, d_out)).astype(np.float32)
        self.b2 = np.zeros(d_out, dtype=np.float32)
        self.h = None

    def forward(self, X: np.ndarray) -> np.ndarray:
        self.h = np.maximum(0.0, X @ self.W1 + self.b1)
        return self.h @ self.W2 + self.b2

    def loss_and_grads(
        self, X: np.ndarray, Y: np.ndarray, head_sizes: Sequence[int]
    ) -> Tuple[float, Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
        logits = self.forward(X)
        probs = np.zeros_like(logits)
        start = 0
        for size in head_sizes:
            seg = logits[:, start:start + size]
            e = np.exp(seg - seg.max(axis=1, keepdims=True))
            probs[:, start:start + size] = e / e.sum(axis=1, keepdims=True)
            start += size

        loss = -float(np.sum(Y * np.log(probs + 1e-12))) / len(X)
        dlogits = (probs - Y) / len(X)
        dW2 = self.h.T @ dlogits
        db2 = dlogits.sum(axis=0)
        dh = dlogits @ self.W2.T
        dh[self.h <= 0] = 0.0
        dW1 = X.T @ dh
        db1 = dh.sum(axis=0)
        return loss, (dW1, db1, dW2, db2)


def train(
    X: np.ndarray,
    Y: np.ndarray,
    head_sizes: Sequence[int],
    d_hidden: int = 24,
    epochs: int = 400,
    batch: int = 512,
    lr: float = 0.005,
    seed: int = 7,
) -> Tuple[MLP, float]:
    rng = np.random.default_rng(seed)
    model = MLP(X.shape[1], d_hidden, Y.shape[1], rng)
    params = {"W1": model.W1, "b1": model.b1, "W2": model.W2, "b2": model.b2}
    m = {k: np.zeros_like(v) for k, v in params.items()}
    v = {k: np.zeros_like(v) for k, v in params.items()}
    t = 0
    n = len(X)
    last_loss = 0.0
    for _ in range(epochs):
        perm = rng.permutation(n)
        for s in range(0, n, batch):
            idx = perm[s:s + batch]
            loss, grads = model.loss_and_grads(X[idx], Y[idx], head_sizes)
            last_loss = loss
            t += 1
            for k, g in zip(params, grads):
                m[k] = 0.9 * m[k] + 0.1 * g
                v[k] = 0.999 * v[k] + 0.001 * g * g
                m_hat = m[k] / (1 - 0.9 ** t)
                v_hat = v[k] / (1 - 0.999 ** t)
                params[k] -= lr * m_hat / (np.sqrt(v_hat) + 1e-8)
    model.W1, model.b1, model.W2, model.b2 = (
        params["W1"], params["b1"], params["W2"], params["b2"],
    )
    return model, last_loss


def accuracy(model: MLP, X: np.ndarray, Y: np.ndarray, head_sizes: Sequence[int]) -> float:
    logits = model.forward(X)
    ok = 0
    total = 0
    start = 0
    for size in head_sizes:
        pred = logits[:, start:start + size].argmax(axis=1)
        true = Y[:, start:start + size].argmax(axis=1)
        ok += int((pred == true).sum())
        total += len(X)
        start += size
    return ok / total


# ----------------------------------------------------------------------
# ONNX 导出
# ----------------------------------------------------------------------
def export_onnx(
    path: str,
    model: MLP,
    head_names: Sequence[str],
    head_sizes: Sequence[int],
    input_dim: int,
) -> None:
    import onnx
    from onnx import TensorProto, helper

    def make_tensor(name: str, arr: np.ndarray):
        return helper.make_tensor(
            name, TensorProto.FLOAT, list(arr.shape), arr.flatten().tolist()
        )

    nodes = [
        helper.make_node("MatMul", ["features", "W1"], ["h"]),
        helper.make_node("Add", ["h", "b1"], ["h1"]),
        helper.make_node("Relu", ["h1"], ["h2"]),
        helper.make_node("MatMul", ["h2", "W2"], ["logits"]),
        helper.make_node("Add", ["logits", "b2"], ["logits_out"]),
    ]
    init_tensors = [
        make_tensor("W1", model.W1),
        make_tensor("b1", model.b1),
        make_tensor("W2", model.W2),
        make_tensor("b2", model.b2),
    ]
    outputs = []
    start = 0
    for name, size in zip(head_names, head_sizes):
        init_tensors += [
            helper.make_tensor(f"{name}_starts", TensorProto.INT64, [1], [start]),
            helper.make_tensor(f"{name}_ends", TensorProto.INT64, [1], [start + size]),
            helper.make_tensor(f"{name}_axes", TensorProto.INT64, [1], [1]),
            helper.make_tensor(f"{name}_steps", TensorProto.INT64, [1], [1]),
        ]
        nodes += [
            helper.make_node(
                "Slice",
                [
                    "logits_out",
                    f"{name}_starts",
                    f"{name}_ends",
                    f"{name}_axes",
                    f"{name}_steps",
                ],
                [f"{name}_raw"],
            ),
            helper.make_node("Softmax", [f"{name}_raw"], [name], axis=1),
        ]
        outputs.append(helper.make_tensor_value_info(name, TensorProto.FLOAT, [None, size]))
        start += size

    graph = helper.make_graph(
        nodes,
        "local_analysis_mlp",
        [helper.make_tensor_value_info("features", TensorProto.FLOAT, [None, input_dim])],
        outputs,
        initializer=init_tensors,
    )
    onnx_model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)]
    )
    onnx_model.ir_version = 10
    onnx.checker.check_model(onnx_model)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    onnx.save(onnx_model, path)
    print(f"已导出: {path}")


def main() -> None:
    rng = np.random.default_rng(42)
    os.makedirs(MODELS_DIR, exist_ok=True)

    print("生成会话分析样本...")
    Xs, Ys = generate_session_samples(30000, rng)
    Xv, Yv = generate_session_samples(5000, np.random.default_rng(1))
    print("训练会话分析模型...")
    model, loss = train(Xs, Ys, (5, 3, 5))
    print(
        f"  会话分析 loss={loss:.4f} "
        f"train_acc={accuracy(model, Xs, Ys, (5, 3, 5)):.4f} "
        f"valid_acc={accuracy(model, Xv, Yv, (5, 3, 5)):.4f}"
    )
    export_onnx(
        os.path.join(MODELS_DIR, "session_analysis.onnx"),
        model,
        ("attention_level", "fatigue", "performance"),
        (5, 3, 5),
        7,
    )

    print("生成模式/难度推荐样本...")
    Xr, Yr = generate_recommend_samples(30000, rng)
    Xrv, Yrv = generate_recommend_samples(5000, np.random.default_rng(2))
    print("训练模式/难度推荐模型...")
    rmodel, rloss = train(Xr, Yr, (2, 3))
    print(
        f"  推荐模型 loss={rloss:.4f} "
        f"train_acc={accuracy(rmodel, Xr, Yr, (2, 3)):.4f} "
        f"valid_acc={accuracy(rmodel, Xrv, Yrv, (2, 3)):.4f}"
    )
    export_onnx(
        os.path.join(MODELS_DIR, "mode_recommend.onnx"),
        rmodel,
        ("mode", "difficulty"),
        (2, 3),
        6,
    )

    print("完成。模型已保存到:", MODELS_DIR)


if __name__ == "__main__":
    main()
