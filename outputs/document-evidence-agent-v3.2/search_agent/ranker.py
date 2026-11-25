"""Cost-aware action scoring with a small logistic model trained on actual reads."""

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from .documents import ROOT
from .evaluation import hit_ok
from .scheduler import FEATURES, best_hint, features, focus_spec, probe_caps, whole_spec
from .task import field_matches

TRAIN_BUDGETS = (1_600_000, 2_600_000, 4_000_000)
TRAIN_TIERS = (300_000, 450_000, 650_000, 1_020_000)
WEIGHTS = ROOT / "data/ranker.json"


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -35, 35)))


@dataclass
class Ranker:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: float

    def score(self, vector):
        return float(sigmoid((np.asarray(vector) - self.mean) / self.scale @ self.weights + self.bias))

    def save(self, path, metadata):
        payload = {"features": FEATURES, "mean": self.mean.tolist(), "scale": self.scale.tolist(),
                   "weights": self.weights.tolist(), "bias": self.bias, "training": metadata}
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if tuple(data["features"]) != FEATURES:
            raise ValueError("权重特征版本不匹配")
        arrays = [np.asarray(data[name], dtype=float) for name in ("mean", "scale", "weights")]
        bias = float(data["bias"])
        if (any(a.shape != (len(FEATURES),) or not np.all(np.isfinite(a)) for a in arrays)
                or np.any(arrays[1] <= 0) or not np.isfinite(bias)):
            raise ValueError("权重内容无效")
        return cls(*arrays, bias)


def samples(packs, reader, progress=None):
    vectors, labels, modes = [], [], Counter()
    for index, pack in enumerate(packs):
        budget = TRAIN_BUDGETS[index % len(TRAIN_BUDGETS)]
        targets = {}
        for case in (pack.cases[0], pack.cases[2], pack.cases[3], pack.cases[5]):
            for field in case.task.fields:
                targets.setdefault((field.anchor, field.kind, field.direction), (field, case.gold[field.id]))
        for page, route in zip(pack.pages, probe_caps(pack.pages, budget)):
            probe = reader(page, route)
            choices = [whole_spec(page.size, tier) for tier in TRAIN_TIERS]
            whole = [(spec, reader(page, spec)) for spec in choices if spec.pixels >= 1.6 * route.pixels]
            for field, gold in targets.values():
                hint = best_hint(probe["lines"], field)
                observations = whole.copy()
                if hint and hint.score >= .52:
                    focus = focus_spec(page.size, hint, field, 215_000)
                    if focus is not None and focus.pixels >= 10_000:
                        observations.append((focus, reader(page, focus)))
                for spec, observation in observations:
                    candidates = field_matches(observation["lines"], field, page.key, spec.key)
                    chosen = max(candidates, key=lambda hit: hit["confidence"], default=None)
                    success = int(hit_ok(chosen, gold))
                    labels.append(success)
                    vectors.append(features(probe, field, hint, page.size, spec))
                    modes[f"{spec.scale}:{success}"] += 1
        if progress:
            progress(pack.key, len(labels))
    return np.asarray(vectors), np.asarray(labels), dict(modes)


def log_loss(target, pred):
    pred = np.clip(pred, 1e-7, 1 - 1e-7)
    return float(-np.mean(target * np.log(pred) + (1 - target) * np.log(1 - pred)))


def fit(train, dev):
    x, y, counts = train
    valid_x, valid_y, valid_counts = dev
    if len(set(y)) != 2 or len(set(valid_y)) != 2:
        raise ValueError("训练与开发集均需含正负动作")
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < .04] = 1
    a, b = (x - mean) / scale, (valid_x - mean) / scale
    weights = np.zeros(a.shape[1])
    rate = float(y.mean())
    bias = float(np.log(rate / (1 - rate)))
    curve = []
    best = None
    for epoch in range(1, 301):
        residual = sigmoid(a @ weights + bias) - y
        weights -= .14 * (a.T @ residual / len(y) + .012 * weights)
        bias -= .14 * residual.mean()
        if epoch % 10 == 0:
            pred = sigmoid(b @ weights + bias)
            loss = log_loss(valid_y, pred)
            curve.append({"epoch": epoch, "train_log_loss": round(log_loss(y, sigmoid(a @ weights + bias)), 6),
                          "dev_log_loss": round(loss, 6)})
            if best is None or loss < best[0]:
                best = loss, epoch, weights.copy(), bias
    loss, epoch, weights, bias = best
    metadata = {"train_actions": counts, "dev_actions": valid_counts, "train_rows": len(y),
                "dev_rows": len(valid_y), "best_epoch": epoch, "dev_log_loss": round(loss, 6), "curve": curve}
    return Ranker(mean, scale, weights, bias), metadata
