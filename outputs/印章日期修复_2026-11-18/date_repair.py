"""Recognize date fragments from one edge OCR observation and preserve their original boxes."""
import re

from date_match import DAY, MONTH, anchor_date, matches
from search_agent.core import union_box
from search_agent.task import valid_box

MONTH_DAY = rf"{MONTH}\.?[ \t]*{DAY}"
TRAILING_DASH = re.compile(rf"(?<!\w){MONTH_DAY}[ \t]*([-‐‑–—])(?=[ \t]*[0-9]{{4}}(?!\w))", re.I)
PREFIX = re.compile(rf"{MONTH_DAY}[ \t]*[-‐‑–—,]?", re.I)
YEAR = re.compile(r"[0-9]{4}")


def repair_separator(text):
    # Preserve character indices for the mapping back to source words.
    characters = list(text)
    for match in TRAILING_DASH.finditer(text):
        characters[match.start(1)] = " "
    return "".join(characters)


def words_for(line):
    return line.get("raw_words") or line["words"]


def date_candidates(words):
    text = " ".join(word["text"] for word in words)
    offset = 0
    segments = []
    for word in words:
        end = offset + len(word["text"])
        segments.append((offset, end, word["box"]))
        offset = end + 1
    normalized = repair_separator(text)
    for match, value in matches(normalized):
        boxes = [box for start, end, box in segments if start < match.end() and end > match.start()]
        if boxes:
            box = union_box(boxes)
            if valid_box(box):
                raw = text[match.start():match.end()]
                yield value, box, raw, raw != match[0]


def nearby_along_baseline(prefix_box, year_box):
    # The OCR view may have been rotated back into page coordinates by the caller.
    boxes = (prefix_box, year_box)
    for axis in (0, 1):
        cross = 1 - axis
        length = [box[axis+2] - box[axis] for box in boxes]
        thickness = [box[cross+2] - box[cross] for box in boxes]
        if any(width < 1.5 * height for width, height in zip(length, thickness)):
            continue
        overlap = min(box[cross+2] for box in boxes) - max(box[cross] for box in boxes)
        if overlap < .65 * min(thickness):
            continue
        first, second = sorted(boxes, key=lambda box: box[axis])
        gap = second[axis] - first[axis+2]
        if -.15 * max(thickness) <= gap <= 1.6 * max(thickness):
            return True
    return False


def cross_line_parts(prefix, year):
    left, right = words_for(prefix), words_for(year)
    if not PREFIX.fullmatch(" ".join(word["text"] for word in left)):
        return None
    if len(right) != 1 or not YEAR.fullmatch(right[0]["text"]):
        return None
    if not nearby_along_baseline(union_box([word["box"] for word in left]), right[0]["box"]):
        return None
    return left + right


def date_hits(page, spec, lines, fields, hits, *, allow_cross_line=True):
    wanted = {field.id: (field, date)
              for field in fields
              if field.id not in hits and (not field.pages or page.key in field.pages)
              and (date := anchor_date(field.anchor)) is not None}
    if not wanted:
        return
    candidates = []
    for line in lines:
        for value, box, text, changed in date_candidates(words_for(line)):
            kind = "normalized_date_hyphen" if changed else "normalized_date"
            candidates.append((kind, value, box, text, line["text"], line["confidence"]))
    if allow_cross_line:
        for prefix, year in zip(lines, lines[1:]):
            words = cross_line_parts(prefix, year)
            if words is not None:
                for value, box, text, _ in date_candidates(words):
                    raw = prefix["text"] + "\n" + year["text"]
                    confidence = min(prefix["confidence"], year["confidence"])
                    candidates.append(("normalized_date_adjacent_lines", value, box, text, raw, confidence))
    for key, (field, expected) in wanted.items():
        for kind, value, box, text, raw, confidence in candidates:
            if value == expected:
                hits[key] = {"field": key, "anchor": field.anchor, "page": page.key,
                             "view": spec.key, "anchor_box": box, "box": box, "value": None,
                             "value_box": None, "line": raw, "confidence": confidence,
                             "match_type": kind, "matched_text": text,
                             "canonical_date": value.isoformat()}
                break
