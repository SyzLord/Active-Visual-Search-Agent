"""Search upright letter dates and receipt stamps with one metered OCR budget."""
from dataclasses import replace
from io import BytesIO
from math import ceil, floor
import re

import numpy as np
from PIL import Image, ImageFilter, ImageOps

import heading
import stamp_scan
from dates import dates_in, find_dates, NAMES, requested_date
from date_repair import words_for
from search_agent.core import ViewSpec, area, fit_area, overlap
from search_agent.reader import project
from search_agent.scheduler import Ledger, read_hits, run
from search_agent.task import answer


def upright_read(page, spec, engine):
    gray = page.image.crop(spec.box).resize(spec.size, Image.Resampling.LANCZOS).convert("L")
    if spec.scale == "pdf-line":
        raster = ImageOps.autocontrast(gray, cutoff=(.4, 1))
    else:
        background = gray.filter(ImageFilter.GaussianBlur(max(3, spec.size[0] / 80)))
        ink = np.maximum(np.asarray(background, dtype=np.int16) - np.asarray(gray, dtype=np.int16), 0)
        adjusted = np.clip(250 - 3.2 * ink - .25 * (255 - np.asarray(gray)), 0, 255).astype("uint8")
        raster = Image.fromarray(adjusted)
    encoded = BytesIO()
    raster.save(encoded, format="PNG")
    mode = "line" if spec.scale == "pdf-line" else "page"
    lines = engine.recognize(encoded.getvalue(), spec.size, mode)
    for line in lines:
        line["box"] = project(line["box"], spec.box)
        for word in line["words"] + line.get("raw_words", []):
            word["box"] = project(word["box"], spec.box)
    return {"box": list(spec.box), "size": list(spec.size), "lines": lines}


def date_clues(lines, field, size):
    expected = requested_date(field.anchor)
    month, day, year = NAMES[expected.month - 1], str(expected.day), str(expected.year)
    candidates = []
    for line in lines:
        complete = {value for _, value in dates_in(line["text"])}
        if complete and expected not in complete:
            continue
        tokens = re.findall(r"[a-z]+|[0-9]+", line["text"].lower())
        month_seen = month in tokens or month[:3] in tokens
        for word in words_for(line):
            parts = re.findall(r"[a-z]+|[0-9]+", word["text"].lower())
            from_month = month in parts or month[:3] in parts
            from_year = year in parts
            from_day = parts == [day]
            if not (from_month or from_year or from_day):
                continue
            left, top, right, bottom = word["box"]
            height = bottom - top
            if height <= 0:
                continue
            pad_left = 1.2 * height if from_month else max(14 * height, .10 * size[0])
            pad_right = 1.5 * height if from_year else max(12 * height, .10 * size[0])
            if from_day and not from_year and not from_month:
                pad_left = max(pad_left, .115 * size[0])
                above, below = max(1.5 * height, .012 * size[1]), max(height, .0085 * size[1])
            else:
                above, below = .87 * height, .60 * height
            box = (max(0, floor(left - pad_left)), max(0, floor(top - above)),
                   min(size[0], ceil(right + pad_right)), min(size[1], ceil(bottom + below)))
            score = int(year in tokens) + int(month_seen) + int(day in tokens)
            candidates.append((score, from_month, box, word["text"]))
    return sorted(candidates, key=lambda item: item[:2], reverse=True)


class LetterSearch:
    def __init__(self, task, pages, budget, engine):
        self.task, self.pages, self.budget, self.engine = task, pages, budget, engine
        self.by_key = {page.key: page for page in pages}
        self.date_fields = tuple(field for field in task.fields if requested_date(field.anchor))
        self.body_fields = tuple(field for field in task.fields if field not in self.date_fields)
        self.previews, self.ranking, self.sides = stamp_scan.rank_candidates(pages)
        self.preview_pixels = sum(item["pixels"] for item in self.previews)
        self.ledger = Ledger(budget - self.preview_pixels)
        if self.ledger.limit < 1:
            raise ValueError("Preview cost exceeds the available letter-search budget")
        self.hits, self.reads, self.events = {}, [], []
        self.tried_text = {page.key: [] for page in pages}

    def done(self, fields):
        return all(field.id in self.hits for field in fields)

    def record(self, page, spec, observed, stage):
        before = set(self.hits)
        find_dates(page, spec, observed["lines"], self.date_fields, self.hits)
        read_hits(page, spec, observed, self.body_fields, self.hits)
        self.reads.append({"page": page.key, "view": spec.key, "stage": stage, "lines": observed["lines"]})
        self.events.append({"stage": stage, "view": spec.key, "page": page.key,
                            "new_fields": [field.id for field in self.task.fields
                                           if field.id in self.hits and field.id not in before]})

    def buy(self, page, box, quota, name, stage, *, angle=0, target=None, reason=None, line=False):
        cap = min(quota, self.ledger.remaining)
        if cap < 1 or not area(box):
            return []
        native = (box[2] - box[0], box[3] - box[1])
        size = fit_area((0, 0, native[0] * 2, native[1] * 2), cap) if line else fit_area(box, cap)
        if angle:
            size = size[::-1]
        if (page.key, box, size) in self.ledger.seen:
            return []
        spec = ViewSpec(name, -1, "pdf-line" if line else stage, box, size)
        reader = (lambda p, s: stamp_scan.observe_edge(p, s, angle, self.engine)) if angle else (
            lambda p, s: upright_read(p, s, self.engine))
        observed = self.ledger.buy(page, spec, reader, reason or stage, target)
        self.ledger.steps[-1].update(stage=stage, rotation_deg_ccw=angle)
        self.record(page, spec, observed, stage)
        return observed["lines"]

    def search_horizontal(self):
        for stage, top, bottom, share in (("header", .015, .42, .32), ("footer", .735, 1., .22)):
            for page in self.pages:
                if self.done(self.date_fields):
                    return
                width, height = page.size
                box = (0, floor(top * height), width, ceil(bottom * height))
                quota = int(self.ledger.limit * share / len(self.pages))
                lines = self.buy(page, box, quota, stage, stage)
                for field in self.date_fields:
                    if field.id in self.hits or (field.pages and page.key not in field.pages):
                        continue
                    tried = []
                    for _, _, clue_box, clue in date_clues(lines, field, page.size):
                        if len(tried) >= 2 or field.id in self.hits:
                            break
                        if any(overlap(clue_box, prior) > .5 * min(area(clue_box), area(prior)) for prior in tried):
                            continue
                        tried.append(clue_box)
                        self.buy(page, clue_box, min(32_000, self.ledger.limit // (20 * len(self.pages))),
                                 f"{stage}-date-line:{len(tried)}", "date-reread", target=field.id,
                                 line=True, reason=f"{stage} OCR clue: {clue}")
                if not self.done(self.body_fields):
                    self.body_reread(page.key, self.tried_text[page.key], strong_only=True)

    def search_sides(self):
        selected = self.sides[:2]
        pool = int(self.ledger.remaining * .34)
        before = self.ledger.spent
        for index, candidate in enumerate(selected):
            if self.done(self.date_fields):
                break
            quota = (pool - (self.ledger.spent - before)) // (len(selected) - index)
            self.buy(self.by_key[candidate["page"]], tuple(candidate["box"]), quota,
                     f"stamp:{candidate['rank']}", "side", angle=candidate["angle"])

    def body_reread(self, key, attempted, strong_only=False):
        pending = [field for field in self.body_fields if field.id not in self.hits]
        views = [dict(row, view=f"article-band:{index}") for index, row in enumerate(self.reads)
                 if row["page"] == key and row["stage"] in {"header", "footer", "body"}]
        suggestions = heading.line_views(views, self.by_key, pending)
        if strong_only:
            suggestions = [item for item in suggestions if item[0] >= .60][:1]
        else:
            suggestions += [item for item in heading.heading_views(views, self.by_key, pending) if item[1] >= .23]
        for score, _, _, page, box, field, clue in suggestions:
            if len(attempted) >= 3 or self.done(self.body_fields):
                break
            if field.id in self.hits or any(overlap(box, old) > .55 * min(area(box), area(old)) for old in attempted):
                continue
            attempted.append(box)
            self.buy(page, box, min(45_000, self.ledger.remaining // 3), f"text-line:{len(attempted)}",
                     "text-reread", target=field.id, line=True, reason=f"body clue {clue} ({score:.2f})")

    def search_body(self):
        keys = dict.fromkeys(self.hits[field.id]["page"] for field in self.date_fields if field.id in self.hits)
        for key in keys:
            if self.done(self.body_fields):
                return
            attempted = self.tried_text[key]
            self.body_reread(key, attempted)
            if not self.done(self.body_fields):
                page = self.by_key[key]
                width, height = page.size
                box = (round(.035 * width), round(.06 * height), round(.965 * width), round(.97 * height))
                self.buy(page, box, int(self.ledger.remaining * .70), "date-page-body", "body")
                self.body_reread(key, attempted)

    def finish(self):
        pending = tuple(field for field in self.task.fields if field.id not in self.hits)
        steps = list(self.ledger.steps)
        spent = self.ledger.spent
        if pending and self.ledger.remaining >= 100_000:
            def read(page, spec):
                observed = page.observe(spec, self.engine)
                self.record(page, spec, observed, "global")
                return observed
            partial = run(replace(self.task, fields=pending), self.pages, self.ledger.remaining, read, "scan-audit")
            for hit in partial["evidence"]:
                self.hits.setdefault(hit["field"], hit)
            steps.extend(dict(step, step=step["step"] + len(self.ledger.steps), spent=step["spent"] + spent,
                              stage="global") for step in partial["steps"])
            spent += partial["spent"]
        evidence = [self.hits[field.id] for field in self.task.fields if field.id in self.hits]
        result = answer(self.task, evidence)
        return dict(strategy="horizontal-and-footer", budget=self.budget, spent=spent,
                    preview_pixels=self.preview_pixels, total_pixels=spent + self.preview_pixels, answer=result,
                    status="answered" if result else ("partial" if evidence else "unresolved"),
                    evidence=evidence, steps=steps, ocr_calls=len(steps), preview_observations=self.previews,
                    candidates=self.ranking, events=self.events)


def run_letter(task, pages, budget, engine):
    if not (task.op == "verify" and sum(bool(requested_date(field.anchor)) for field in task.fields) == 1):
        return heading.run_reserved(task, pages, budget, engine, cross_probe=True)
    search = LetterSearch(task, pages, budget, engine)
    search.search_horizontal()
    if not search.done(search.date_fields):
        search.search_sides()
    if search.done(search.date_fields):
        search.search_body()
    return search.finish()
