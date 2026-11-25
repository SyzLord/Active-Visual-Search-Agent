"""Global pixel ledger and field-aware page routing."""

from dataclasses import dataclass
from functools import lru_cache
from math import sqrt
from time import perf_counter

from .core import ViewSpec, area, fit_area, fit_edge, overlap, union_box
from .task import Task, answer, field_matches, lexical

IMAGE_STRATEGIES = ("uniform", "sequential", "route-whole", "greedy", "learned", "adaptive")
STRATEGIES = (*IMAGE_STRATEGIES, "hybrid", "audited", "scan-audit")
DEFAULT_STRATEGY = "audited"
ROUTE_EDGE = 540
ROUTE_CAP = 240_000
MIN_DETAIL = 150_000
MAX_DETAIL = 1_020_000
WHOLE_TIERS = (180_000, 300_000, 450_000, 650_000, 850_000, MAX_DETAIL)
FEATURES = ("phrase_similarity", "exact_prefix", "text_density", "localization", "hint_confidence",
            "query_words", "query_digits", "page_ink", "probe_pixels", "number_field", "focus",
            "action_pixels", "action_coverage", "text_scale")


@dataclass(frozen=True)
class Hint:
    score: float
    exact: float
    confidence: float
    box: tuple
    text: str


@lru_cache(maxsize=18000)
def affinity(left, right):
    if left == right:
        return 1.
    if min(len(left), len(right)) < 3:
        return 0.
    # Character overlap is cheap and resilient to one OCR substitution.
    a = {left[i:i + 2] for i in range(len(left) - 1)}
    b = {right[i:i + 2] for i in range(len(right) - 1)}
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.


def best_hint(lines, field):
    best = None
    query = field.query
    for line in lines:
        raw = line.get("raw_words", line.get("words", []))
        lex = lexical(raw)
        for i in range(len(lex)):
            segment = lex[i:i + len(query)]
            if len(segment) < max(1, len(query) - 1):
                continue
            text = tuple(word for word, _ in segment)
            variants = (query,) if len(text) == len(query) else tuple(
                query[:j] + query[j+1:] for j in range(len(query))
            )
            for variant in variants:
                score = sum(affinity(a, b) for a, b in zip(variant, text)) / len(query)
                exact = sum(a == b for a, b in zip(variant, text)) / len(query)
                if not score:
                    continue
                item = Hint(score, exact, float(line["confidence"]),
                            tuple(union_box([raw[j]["box"] for _, j in segment])), " ".join(text))
                if best is None or (item.score, item.exact, item.confidence) > (best.score, best.exact, best.confidence):
                    best = item
    return best


def route_spec(size):
    box = (0, 0, *size)
    edge = min(ROUTE_EDGE, max(size))
    width, height = fit_edge(box, edge)
    if width * height > ROUTE_CAP:
        width, height = fit_area(box, ROUTE_CAP)
    return ViewSpec("route", -1, "route", box, (width, height))


def whole_spec(size, pixels, key="whole"):
    box = (0, 0, *size)
    return ViewSpec(key, -1, "whole", box, fit_area(box, pixels))


def focus_region(hint, size, field):
    x0, y0, x1, y1 = hint.box
    width, height = size
    h = max(y1 - y0, height * .01)
    margin = max(3 * h, (x1 - x0) * .24)
    left = margin + (min(18, field.window * 2.5) * h if field.kind == "number" and field.direction == "before" else 0)
    right = margin + (min(18, field.window * 2.5) * h if field.kind == "number" and field.direction == "after" else 0)
    up = max(3.2 * h, .026 * height)
    return (max(0, int(x0 - left)), max(0, int(y0 - up)),
            min(width, int(x1 + right + 1)), min(height, int(y1 + up + 1)))


def focus_spec(size, hint, field, pixels):
    box = focus_region(hint, size, field)
    if area(box) < 2 or area(box) > .72 * area((0, 0, *size)):
        return None
    return ViewSpec(f"focus:{field.id}", -1, "focus", box, fit_area(box, pixels))


def features(observation, field, hint, size, spec):
    lines = observation["lines"]
    page_area = size[0] * size[1]
    ink = sum(area(line["box"]) for line in lines)
    scale = hint.box[3] - hint.box[1] if hint else 0
    scale *= spec.size[1] / (spec.box[3] - spec.box[1])
    return (
        hint.score if hint else 0., hint.exact if hint else 0.,
        min(1., len(lines) / 35.), 1 - min(1., area(hint.box) / page_area * 8) if hint else 0.,
        hint.confidence if hint else 0., len(field.query) / 8,
        float(any(char.isdigit() for char in field.anchor)),
        min(1., ink / page_area), observation["size"][0] * observation["size"][1] / ROUTE_CAP,
        float(field.kind == "number"), float(spec.scale == "focus"), spec.pixels / MAX_DETAIL,
        area(spec.box) / page_area, min(2., scale / 20),
    )


class Ledger:
    def __init__(self, limit):
        self.limit = limit
        self.spent = 0
        self.seen = {}
        self.steps = []

    @property
    def remaining(self):
        return self.limit - self.spent

    def buy(self, page, spec, reader, reason, target=None):
        key = page.key, spec.box, spec.size
        if spec.pixels > self.remaining or key in self.seen:
            raise ValueError("重复动作或像素预算不足")
        observation = reader(page, spec)
        if list(spec.size) != observation["size"] or list(spec.box) != observation["box"]:
            raise ValueError("读图返回的范围或分辨率不一致")
        self.seen[key] = spec, observation
        self.spent += spec.pixels
        self.steps.append({"step": len(self.steps) + 1, "page": page.key, "view": spec.key,
                           "mode": spec.scale, "size": list(spec.size), "box": list(spec.box),
                           "pixels": spec.pixels, "spent": self.spent,
                           "reason": reason, "target": target, "ocr_lines": len(observation["lines"])})
        return observation


def read_hits(page, spec, observation, fields, hits, min_number_height=0, min_span_height=0):
    for field in fields:
        if field.id in hits:
            continue
        candidates = list(field_matches(observation["lines"], field, page.key, spec.key))
        if not candidates:
            continue
        hit = max(candidates, key=lambda row: row["confidence"])
        h = (hit["box"][3] - hit["box"][1]) * spec.size[1] / max(1, spec.box[3] - spec.box[1])
        if h >= (min_number_height if field.kind == "number" else min_span_height):
            hits[field.id] = hit


def probe_caps(pages, limit):
    specs = [route_spec(page.size) for page in pages]
    desired = sum(spec.pixels for spec in specs)
    if desired <= .52 * limit:
        return specs
    per_page = max(1, int(.52 * limit / len(pages)))
    return [ViewSpec(s.key, s.tile, s.scale, s.box, fit_area(s.box, per_page)) for s in specs]


def uniform_run(task, pages, ledger, reader, sequential):
    hits = {}
    per_page = ledger.limit // len(pages)
    for page in pages:
        if not ledger.remaining or len(hits) == len(task.fields):
            break
        pixels = min(ledger.remaining, 650_000) if sequential else per_page
        if pixels < 1:
            break
        spec = whole_spec(page.size, pixels, "uniform" if not sequential else "sequential")
        row = ledger.buy(page, spec, reader, "按页顺序读取" if sequential else "各页均摊像素")
        read_hits(page, spec, row, task.fields, hits)
    return hits


def score_options(task, pages, probes, hits, ledger, strategy, ranker, attempted, min_hint):
    options = []
    for page in pages:
        observation, hints = probes[page.key]
        for field in task.fields:
            if field.id in hits:
                continue
            hint = hints[field.id]
            specs = []
            if (strategy != "route-whole" and hint and hint.score >= min_hint
                    and (page.key, field.id, "focus") not in attempted):
                spec = focus_spec(page.size, hint, field, min(ledger.remaining, 215_000))
                if spec and spec.pixels >= 10_000:
                    specs.append(spec)
            if (page.key, "*", "whole") not in attempted:
                budget = min(ledger.remaining, MAX_DETAIL)
                if len(task.fields) - len(hits) > 1:
                    budget = min(budget, max(320_000, int(ledger.remaining * .57)))
                tier = max((tier for tier in WHOLE_TIERS if tier <= budget), default=0)
                old_pixels = observation["size"][0] * observation["size"][1]
                if tier:
                    spec = whole_spec(page.size, tier)
                if tier and spec.pixels >= MIN_DETAIL and spec.pixels >= 1.6 * old_pixels:
                    specs.append(spec)
            for spec in specs:
                vector = features(observation, field, hint, page.size, spec)
                if strategy == "learned":
                    p = ranker.score(vector)
                else:
                    p = .05 + .83 * vector[0] + .07 * vector[1] + .05 * vector[2]
                    if spec.scale == "whole":
                        p *= .78
                options.append((p / sqrt(spec.pixels / MIN_DETAIL), page, spec, field, hint))
    return options


def routed_run(task, pages, ledger, reader, strategy, ranker, min_hint):
    probes, hits = {}, {}
    for page, spec in zip(pages, probe_caps(pages, ledger.limit)):
        if spec.pixels > ledger.remaining:
            break
        observation = ledger.buy(page, spec, reader, "低成本检索页")
        hints = {field.id: best_hint(observation["lines"], field) for field in task.fields}
        probes[page.key] = observation, hints
        read_hits(page, spec, observation, task.fields, hits, min_number_height=16, min_span_height=11)
        if len(hits) == len(task.fields):
            return hits
    attempted = set()
    while ledger.remaining >= 10_000:
        options = score_options(task, pages[:len(probes)], probes, hits, ledger, strategy,
                                ranker, attempted, min_hint)
        if not options:
            break
        score, page, spec, field, hint = max(options, key=lambda item: item[0])
        marker = (page.key, field.id if spec.scale == "focus" else "*", spec.scale)
        attempted.add(marker)
        key = page.key, spec.box, spec.size
        if key in ledger.seen:
            continue
        clue = hint.text if hint else "当前候选无局部线索"
        reason = f"补读 {field.id} · {clue} · 优先分 {score:.3f}"
        observation = ledger.buy(page, spec, reader, reason, field.id)
        read_hits(page, spec, observation, task.fields, hits)
        if len(hits) == len(task.fields):
            break
    return hits


def confirmation_spec(page, hit, budget, field):
    """Re-read the exact anchor and its tentative number at a higher scale."""
    x0, y0, x1, y1 = hit["box"]
    h = y1 - y0
    # Keep enough context for a corrected minus sign, and don't include the next row.
    box = (max(0, int(x0 - 2 * h)), max(0, int(y0 - 1.35 * h)),
           min(page.size[0], int(x1 + 2 * h + 1)), min(page.size[1], int(y1 + 1.35 * h + 1)))
    if area(box) < 2:
        return None
    return ViewSpec(f"confirm:{field.id}", -1, "confirm", box, fit_area(box, min(budget, 150_000)))


def matching_evidence(page, spec, observation, field, tentative):
    candidates = list(field_matches(observation["lines"], field, page.key, spec.key))
    if tentative is not None:
        candidates = [hit for hit in candidates if overlap(hit["anchor_box"], tentative["anchor_box"]) > 0]
    return max(candidates, key=lambda row: row["confidence"], default=None)


def survey_run(task, pages, ledger, reader, limit, inset=False):
    # Keep a shared reserve while giving every candidate page a usable first read.
    per_page = min(425_000, int(.70 * limit / len(pages)))
    probes, tentative, hits = {}, {}, {}
    for page in pages:
        spec = whole_spec(page.size, per_page, "survey")
        if inset:
            width, height = page.size
            x, y = round(.08 * width), round(.06 * height)
            box = (x, y, width - x, height - y)
            spec = ViewSpec("survey-body", -1, "survey", box, fit_area(box, per_page))
        existing = ledger.seen.get((page.key, spec.box, spec.size))
        if existing is None:
            observation = ledger.buy(page, spec, reader, "均匀扫描候选页，保留局部核验预算")
        else:
            spec, observation = existing
        hints = {}
        for field in task.fields:
            if field.id in hits:
                continue
            hit = matching_evidence(page, spec, observation, field, None)
            if hit and field.kind == "span":
                hits[field.id] = hit
            elif hit:
                tentative[page.key, field.id] = hit
            hints[field.id] = best_hint(observation["lines"], field)
        probes[page.key] = spec, observation, hints
        if len(hits) == len(task.fields):
            break
    return hits, probes, tentative


def reserve_options(task, pages, ledger, hits, probes, tentative, attempted):
    options = []
    remaining_fields = [field for field in task.fields if field.id not in hits]
    for page in pages:
        survey, observation, hints = probes[page.key]
        for field in remaining_fields:
            candidate = tentative.get((page.key, field.id))
            hint = hints.get(field.id)
            if candidate and (page.key, field.id, "confirm") not in attempted:
                spec = confirmation_spec(page, candidate, ledger.remaining, field)
                if spec is not None and spec.pixels >= 5_000:
                    p = 1.5 + candidate["confidence"] * .25
                    options.append((p / sqrt(spec.pixels / 150_000), page, spec, field, candidate, "核验数字"))
            if hint and hint.score >= .56 and (page.key, field.id, "focus") not in attempted:
                spec = focus_spec(page.size, hint, field, min(ledger.remaining, 175_000))
                if spec is not None and spec.pixels >= 10_000:
                    p = (.12 + .65 * hint.score + .23 * hint.exact) ** 2
                    options.append((p / sqrt(spec.pixels / 150_000), page, spec, field, candidate, "放大线索"))
            if (page.key, "*", "whole") in attempted:
                continue
            maximum = min(ledger.remaining, 650_000)
            if len(remaining_fields) > 1:
                maximum = min(maximum, max(300_000, int(ledger.remaining * .62)))
            tier = max((n for n in WHOLE_TIERS if n <= maximum), default=0)
            if tier:
                spec = whole_spec(page.size, tier, "reserve")
                if spec.pixels >= max(150_000, survey.pixels * 1.30):
                    p = .22 + .78 * hint.score if hint else .22
                    options.append((p / sqrt(spec.pixels / 150_000), page, spec, field, None, "整页补读"))
    return options


def adaptive_run(task, pages, ledger, reader, hits=None, inset=False):
    hits = {} if hits is None else hits
    pending = tuple(field for field in task.fields if field.id not in hits)
    if not pending or ledger.remaining < 10_000:
        return hits
    missing = Task(task.op, pending, task.unit)
    surveyed, probes, tentative = survey_run(missing, pages, ledger, reader, ledger.remaining, inset)
    hits.update(surveyed)
    attempted = set()
    while ledger.remaining >= 5_000 and len(hits) < len(task.fields):
        options = reserve_options(task, pages, ledger, hits, probes, tentative, attempted)
        if not options:
            break
        score, page, spec, field, candidate, label = max(options, key=lambda option: option[0])
        marker = (page.key, "*" if spec.scale == "whole" else field.id, spec.scale)
        attempted.add(marker)
        if (page.key, spec.box, spec.size) in ledger.seen:
            continue
        observation = ledger.buy(page, spec, reader, f"{label} {field.id} · 优先分 {score:.3f}", field.id)
        verified = matching_evidence(page, spec, observation, field, candidate)
        if verified:
            if candidate and candidate["value"] != verified["value"]:
                verified["revised_from"] = candidate["value"]
            hits[field.id] = verified
        # A whole-page read can independently supply another unresolved field.
        if spec.scale == "whole":
            read_hits(page, spec, observation, task.fields, hits, min_number_height=14)
    return hits


def line_spec(page, box, field, budget, variant):
    x0, y0, x1, y1 = box
    h = y1 - y0
    # Bound the crop to this line. The asymmetric margin exposes the requested numeral.
    number_margin = (3.0 * min(8, field.window) + 2) * h if field.kind == "number" else 0
    left = (1.0 + .65 * variant) * h + (number_margin if field.direction == "before" else 0)
    right = (1.0 + .65 * variant) * h + (number_margin if field.direction == "after" else 0)
    vertical = (.48 + .28 * variant) * h
    region = (max(0, int(x0 - left)), max(0, int(y0 - vertical)),
              min(page.size[0], int(x1 + right + 1)), min(page.size[1], int(y1 + vertical + 1)))
    return ViewSpec(f"pdf-line:{field.id}", -1, "pdf-line", region, fit_area(region, min(budget, 140_000)))


def hybrid_run(task, pages, ledger, reader):
    candidates = {field.id: [(page, box) for page in pages for box in page.text_hints.get(field.query, ())]
                  for field in task.fields}
    hits = {}
    cap = min(1_000_000, ledger.limit // 2)
    considered = set()
    # Keep candidate ordering independent of OCR and spend at most half the budget here.
    # Give each field its first candidate before visiting its later occurrences.
    for variant in (0, 1):
        for index in range(max(map(len, candidates.values()), default=0)):
            for field in task.fields:
                left = cap - ledger.spent
                options = candidates[field.id]
                if field.id in hits or index >= len(options) or left < 5_000:
                    continue
                page, box = options[index]
                considered.add((page.key, field.id, box))
                spec = line_spec(page, box, field, left, variant)
                spec = ViewSpec(f"{spec.key}:{index + 1}.{variant + 1}", spec.tile, spec.scale, spec.box, spec.size)
                existing = ledger.seen.get((page.key, spec.box, spec.size))
                if existing is None:
                    observed = ledger.buy(page, spec, reader, f"PDF 候选 {field.id} · 像素复核", field.id)
                else:
                    spec, observed = existing
                expected = {"anchor_box": box}
                hit = matching_evidence(page, spec, observed, field, expected)
                if hit:
                    hits[field.id] = hit
            if len(hits) == len(task.fields):
                return hits, candidates, considered
    return adaptive_run(task, pages, ledger, reader, hits), candidates, considered


def run(task, pages, budget, reader, strategy=DEFAULT_STRATEGY, ranker=None, min_hint=.52):
    if strategy not in STRATEGIES or strategy == "learned" and ranker is None:
        raise ValueError("需要有效的检索策略和权重")
    if type(budget) is not int or not 100_000 <= budget <= 16_000_000:
        raise ValueError("请输入 100,000 到 16,000,000 之间的像素预算")
    if not pages:
        raise ValueError("至少提供一页")
    if len({page.key for page in pages}) != len(pages):
        raise ValueError("页面 ID 必须唯一")
    known = {page.key for page in pages}
    if any(set(field.pages) - known for field in task.fields):
        raise ValueError("字段 pages 包含不在输入中的页面 ID")
    ledger = Ledger(budget)
    start = perf_counter()
    candidate_count = None
    possible_ambiguities = []
    assessments = {}
    if strategy in ("uniform", "sequential"):
        hits = uniform_run(task, pages, ledger, reader, strategy == "sequential")
    elif strategy in ("audited", "scan-audit"):
        from .audit import adjudicate
        hits, assessments = adjudicate(task, pages, ledger, reader, inset=strategy == "scan-audit")
        candidate_count = {field: item["candidate_count"] for field, item in assessments.items()}
        possible_ambiguities = [field for field, item in assessments.items()
                               if item["status"] in ("conflict", "needs_review")]
    elif strategy == "hybrid":
        hits, candidates, considered = hybrid_run(task, pages, ledger, reader)
        candidate_count = {field: len(items) for field, items in candidates.items()}
        for field in task.fields:
            hit = hits.get(field.id)
            options = candidates[field.id]
            if hit and field.kind == "number" and any(
                (page.key, field.id, box) not in considered for page, box in options
            ):
                possible_ambiguities.append(field.id)
    elif strategy == "adaptive":
        hits = adaptive_run(task, pages, ledger, reader)
    else:
        hits = routed_run(task, pages, ledger, reader, strategy, ranker, min_hint)
    evidence = [hits[field.id] for field in task.fields if field.id in hits]
    result = answer(task, evidence)
    status = "answered" if result is not None else ("partial" if evidence else "unresolved")
    if any(item["status"] == "conflict" for item in assessments.values()):
        status = "conflict"
    elif possible_ambiguities and assessments:
        status = "needs_review"
    return {
        "op": task.op, "strategy": strategy, "budget": budget, "spent": ledger.spent,
        "status": status,
        "answer": result, "evidence": evidence, "steps": ledger.steps,
        "pages": [{"id": p.key, "name": p.name, "size": list(p.size)} for p in pages],
        "ocr_calls": len(ledger.steps), "elapsed_ms": round((perf_counter() - start) * 1000, 2),
        "pdf_candidates": candidate_count,
        "possible_ambiguities": possible_ambiguities,
        "field_assessments": assessments,
    }
