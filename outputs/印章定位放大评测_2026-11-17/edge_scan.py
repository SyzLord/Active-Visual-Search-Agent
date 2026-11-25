"""Image-only strip probes for exact span localization and verification."""
from dataclasses import replace
from io import BytesIO

from PIL import Image, ImageOps

from search_agent.core import ViewSpec, fit_area, union_box
from search_agent.reader import project
from search_agent.scheduler import Ledger, read_hits, run
from search_agent.task import answer, valid_box
from date_match import anchor_date, matches


def source_box(box, crop, angle):
    x0, y0, x1, y1 = box
    if angle == 90:
        box = (1 - y1, x0, 1 - y0, x1)
    elif angle == -90:
        box = (y0, 1 - x1, y1, 1 - x0)
    return project(box, crop)


def probes(size, quota, rotate):
    width, height = size
    x, y = round(.12 * width), round(.10 * height)
    for name, box, direction in (
        ("top", (0, 0, width, y), 0),
        ("right", (width - x, 0, width, height), 90),
        ("left", (0, 0, x, height), -90),
        ("bottom", (0, height - y, width, height), 0),
    ):
        angle = direction if rotate else 0
        image_size = fit_area(box, quota)
        if angle:
            image_size = image_size[::-1]
        yield ViewSpec("edge:" + name, -1, "edge", box, image_size), angle


def observe_edge(page, spec, angle, engine, contrast=False):
    raster = page.image.crop(spec.box)
    if angle:
        transpose = Image.Transpose.ROTATE_90 if angle == 90 else Image.Transpose.ROTATE_270
        raster = raster.transpose(transpose)
    raster = raster.resize(spec.size, Image.Resampling.LANCZOS)
    if contrast:
        raster = ImageOps.autocontrast(raster.convert("L"), cutoff=1)
    encoded = BytesIO()
    raster.save(encoded, "JPEG", quality=91)
    lines = engine.recognize(encoded.getvalue(), raster.size, "page")
    for line in lines:
        line["box"] = source_box(line["box"], spec.box, angle)
        for word in line["words"] + line.get("raw_words", []):
            word["box"] = source_box(word["box"], spec.box, angle)
    return {"box": list(spec.box), "size": list(raster.size), "lines": lines}


def date_hits(page, spec, lines, fields, hits):
    for field in fields:
        expected = anchor_date(field.anchor)
        if expected is None or field.id in hits or (field.pages and page.key not in field.pages):
            continue
        for line in lines:
            words = line.get("raw_words", line["words"])
            offset = 0
            spans = []
            for word in words:
                end = offset + len(word["text"])
                spans.append((offset, end, word["box"]))
                offset = end + 1
            text = " ".join(word["text"] for word in words)
            for match, value in matches(text):
                if value != expected:
                    continue
                boxes = [box for start, end, box in spans
                         if start < match.end() and end > match.start()]
                if not boxes:
                    continue
                box = union_box(boxes)
                if valid_box(box):
                    hits[field.id] = {"field": field.id, "anchor": field.anchor, "page": page.key,
                                      "view": spec.key, "anchor_box": box, "box": box, "value": None,
                                      "value_box": None, "line": line["text"], "confidence": line["confidence"],
                                      "match_type": "normalized_date", "matched_text": match[0],
                                      "canonical_date": value.isoformat()}
                    break
            if field.id in hits:
                break


def run_edges(task, pages, budget, engine, strategy):
    normalize = strategy in ("edge-date", "edge-date-contrast")
    contrast_top = strategy == "edge-date-contrast"
    rotate = strategy != "edge-crop"
    if any(field.kind != "span" for field in task.fields):
        raise ValueError("Strip evaluation supports exact spans only")
    ledger = Ledger(budget)
    hits = {}
    details = []
    quota = budget * 40 // (100 * 4 * len(pages))
    # Use the same page order for both strip strategies.
    for page in pages:
        for spec, angle in probes(page.size, quota, rotate):
            contrast = contrast_top and spec.key == "edge:top"
            observation = ledger.buy(page, spec, lambda p, s: observe_edge(p, s, angle, engine, contrast),
                                     "geometric strip")
            ledger.steps[-1]["rotation_deg_ccw"] = angle
            ledger.steps[-1]["contrast"] = contrast
            details.append({"page": page.key, "view": spec.key, "lines": observation["lines"]})
            read_hits(page, spec, observation, task.fields, hits)
            if normalize:
                date_hits(page, spec, observation["lines"], task.fields, hits)
    pending = tuple(field for field in task.fields if field.id not in hits)
    if pending:
        # The fallback only needs to retrieve the pending fields.
        partial = run(replace(task, fields=pending), pages, ledger.remaining,
                      lambda page, spec: page.observe(spec, engine), "scan-audit")
        hits.update((hit["field"], hit) for hit in partial["evidence"])
        for step in partial["steps"]:
            step["step"] += len(details)
            step["spent"] += ledger.spent
        steps = ledger.steps + partial["steps"]
        spent = ledger.spent + partial["spent"]
    else:
        steps, spent = ledger.steps, ledger.spent
    evidence = [hits[field.id] for field in task.fields if field.id in hits]
    result = answer(task, evidence)
    status = "answered" if result is not None else ("partial" if evidence else "unresolved")
    return {"strategy": strategy,
            "budget": budget, "spent": spent, "status": status, "answer": result,
            "evidence": evidence, "ocr_calls": len(steps), "steps": steps, "edge_ocr": details}
