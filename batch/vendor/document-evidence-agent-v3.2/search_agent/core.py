"""Observation geometry, budget accounting, and evidence matching."""

from dataclasses import dataclass
from math import sqrt
import re


THUMB_EDGE = 352
PREVIEW_EDGE = 224
DETAIL_EDGE = 640
BUDGETS = (320_000, 650_000, 1_100_000)
PRIMARY_BUDGET = BUDGETS[1]
WORD = re.compile(r"[A-Za-z0-9]+")


def tokens(text):
    return tuple(word.lower() for word in WORD.findall(text))


@dataclass(frozen=True)
class ViewSpec:
    key: str
    tile: int
    scale: str
    box: tuple
    size: tuple

    @property
    def pixels(self):
        return self.size[0] * self.size[1]


def fit_edge(box, edge):
    width, height = box[2] - box[0], box[3] - box[1]
    ratio = min(1.0, edge / max(width, height))
    return max(1, int(width * ratio)), max(1, int(height * ratio))


def fit_area(box, pixels):
    if pixels < 1:
        raise ValueError("像素预算必须大于零")
    width, height = box[2] - box[0], box[3] - box[1]
    ratio = min(1.0, sqrt(pixels / (width * height)))
    out_width, out_height = max(1, int(width * ratio)), max(1, int(height * ratio))
    if out_width * out_height > pixels:
        return min(out_width, pixels), min(out_height, max(1, pixels // out_width))
    return out_width, out_height


def observation_specs(size):
    """A fixed overlapping grid. Boxes are in original image pixels."""
    width, height = size
    rows, cols = (4, 3) if height >= width else (3, 4)
    full = (0, 0, width, height)
    specs = {"thumb": ViewSpec("thumb", -1, "thumb", full, fit_edge(full, THUMB_EDGE))}
    for row in range(rows):
        for col in range(cols):
            x0 = max(0, int((col - 0.15) * width / cols))
            y0 = max(0, int((row - 0.15) * height / rows))
            x1 = min(width, max(x0 + 1, int((col + 1.15) * width / cols)))
            y1 = min(height, max(y0 + 1, int((row + 1.15) * height / rows)))
            box = (x0, y0, x1, y1)
            tile = row * cols + col
            for mode, edge in (("preview", PREVIEW_EDGE), ("detail", DETAIL_EDGE)):
                key = f"{tile}:{mode}"
                specs[key] = ViewSpec(key, tile, mode, box, fit_edge(box, edge))
    return specs


def full_spec(size, pixels):
    box = (0, 0, *size)
    return ViewSpec(f"full:{pixels}", -1, "full", box, fit_area(box, pixels))


def contains_point(box, x, y):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def overlap(a, b):
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return width * height


def area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def union_box(boxes):
    return [
        min(box[0] for box in boxes), min(box[1] for box in boxes),
        max(box[2] for box in boxes), max(box[3] for box in boxes),
    ]


def locate(observation, query):
    """Return a match only when the reader saw the exact token sequence."""
    matches = []
    count = len(query)
    for line in observation["lines"]:
        words = line["words"]
        normalized = tuple(word["text"].lower() for word in words)
        for start in range(len(words) - count + 1):
            if normalized[start:start + count] == query:
                matched = words[start:start + count]
                matches.append({
                    "text": " ".join(word["text"] for word in matched),
                    "line": line["text"],
                    "box": union_box([word["box"] for word in matched]),
                    "confidence": line["confidence"],
                })
    return max(matches, key=lambda match: match["confidence"], default=None)


def correct(match, gold):
    if match is None or gold is None:
        return False
    prediction = match["box"]
    gold_area = area(gold)
    if not gold_area:
        return False
    # Word boxes from OCR and font/PDF geometry can have different padding.
    # Require useful overlap and reject broad boxes that cover unrelated text.
    shared = overlap(prediction, gold)
    return shared / gold_area >= 0.5 and shared / max(1, area(prediction)) >= 0.25


class Budget:
    def __init__(self, limit):
        if limit < 1:
            raise ValueError("像素预算必须大于零")
        self.limit = limit
        self.spent = 0
        self.seen = {}

    @property
    def remaining(self):
        return self.limit - self.spent

    def acquire(self, spec, reader):
        if spec.key in self.seen or spec.pixels > self.remaining:
            raise ValueError(f"不可执行的观察 {spec.key}")
        observation = reader(spec)
        if observation["size"] != list(spec.size) or observation["box"] != list(spec.box):
            raise ValueError(f"读图器返回了与动作不一致的图像尺寸或坐标 {spec.key}")
        self.seen[spec.key] = observation
        self.spent += spec.pixels
        return observation


def available(specs, budget):
    return [
        spec for spec in specs.values()
        if spec.tile >= 0 and spec.key not in budget.seen
        and spec.pixels <= budget.remaining
        and not (spec.scale == "preview" and f"{spec.tile}:detail" in budget.seen)
        and not (
            spec.scale == "preview"
            and spec.size == specs[f"{spec.tile}:detail"].size
        )
    ]


def run_search(size, phrase, limit, reader, chooser, keep_ocr=False):
    query = tokens(phrase)
    if not query:
        raise ValueError("请输入至少一个英文字母或数字")
    specs = observation_specs(size)
    budget = Budget(limit)
    steps = []

    def observe(spec, reason):
        observation = budget.acquire(spec, reader)
        match = locate(observation, query)
        step = {
            "view": spec.key, "tile": spec.tile, "scale": spec.scale, "box": list(spec.box),
            "size": list(spec.size), "pixels": spec.pixels, "spent": budget.spent,
            "match": match, "reason": reason,
        }
        if keep_ocr:
            step["ocr"] = [line["text"] for line in observation["lines"]]
        steps.append(step)
        return match

    match = None
    if chooser.name == "full":
        match = observe(full_spec(size, limit), "按总预算一次读取整图")
    elif specs["thumb"].pixels <= limit:
        match = observe(specs["thumb"], "获取全图低分辨率概览")
        while match is None:
            candidates = available(specs, budget)
            if not candidates:
                break
            plan = chooser.choose(query, specs, budget, candidates)
            if not plan:
                break
            if len({spec.key for spec, _ in plan}) != len(plan) or sum(spec.pixels for spec, _ in plan) > budget.remaining:
                raise ValueError("策略生成了重复或超预算的动作")
            if any(spec not in candidates for spec, _ in plan):
                raise ValueError("策略选择了候选集合之外的动作")
            # Joint selection commits every crop in its plan before reading.
            found = []
            for spec, reason in plan:
                candidate_match = observe(spec, reason)
                if candidate_match is not None:
                    found.append(candidate_match)
            match = max(found, key=lambda entry: entry["confidence"], default=None)
            if chooser.name == "joint":
                break
    return {
        "query": phrase, "size": list(size), "policy": chooser.name, "budget": limit,
        "spent": budget.spent, "status": "found" if match else "unresolved",
        "match": match, "steps": steps,
    }
