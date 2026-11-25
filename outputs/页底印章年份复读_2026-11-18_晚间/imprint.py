"""Identify month/day and a four-digit year on the same physical stamp line."""
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
import re

import runtime
from dates import NUMBERS
from search_agent.core import union_box


MONTH = "(?P<month>" + "|".join(sorted(NUMBERS, key=len, reverse=True)) + ")"
DAY = r"(?P<day>[0-9](?:[ \t]*[0-9])?)"
GAP = r"[ \t.\-‐‑–—]*"
PREFIX = [re.compile(r"(?<!\w)" + pattern + r"(?:(?!\w)|(?=[12][0-9]{3}(?!\w)))", re.I) for pattern in (
    MONTH + GAP + DAY, DAY + r"[ \t\-.]+" + MONTH + r"\.?"
)]
FOUR_DIGITS = re.compile(r"^[^A-Za-z0-9]*([0-9]{4})[^A-Za-z0-9]*$")


@dataclass(frozen=True)
class Prefix:
    month: int
    day: int
    text: str
    page: str
    view: str
    box: tuple
    last_box: tuple
    slope: float


def prefixes(line, page_key, view):
    words = line.get("raw_words") or line["words"]
    text = " ".join(word["text"] for word in words)
    spans, start = [], 0
    for word in words:
        end = start + len(word["text"])
        spans.append((start, end, word["box"]))
        start = end + 1
    for pattern in PREFIX:
        for match in pattern.finditer(text):
            boxes = []
            for left, right, box in spans:
                if left < match.end() and right > match.start():
                    x0, y0, x1, y1 = box
                    end_fraction = min(1, (match.end() - left) / (right - left))
                    boxes.append((x0, y0, x0 + (x1 - x0) * end_fraction, y1))
            first, last = boxes[0], boxes[-1]
            dx = (last[0] + last[2] - first[0] - first[2]) / 2
            dy = (last[1] + last[3] - first[1] - first[3]) / 2
            height = max(first[3]-first[1], last[3]-last[1], 1)
            if len(boxes) > 1 and (dx <= 0 or abs(dy) > .85*height or
                                   any(b[0]-a[2] > 3*height for a,b in zip(boxes,boxes[1:]))):
                continue
            slope = dy / dx if dx >= 1.5 * height else 0.
            yield Prefix(NUMBERS[match["month"].lower()], int("".join(match["day"].split())), match[0], page_key, view,
                         tuple(union_box(boxes)), tuple(last), max(-.22, min(.22, slope)))


def observed_years(line):
    for word in line.get("raw_words") or line["words"]:
        match = FOUR_DIGITS.fullmatch(word["text"])
        if match:
            yield match[1], word["text"], tuple(word["box"])


def damaged_prefixes(line, page_key, view, month_name, day):
    words = line.get("raw_words") or line["words"]
    for first, last in zip(words, words[1:]):
        letters = re.sub("[^a-z]", "", first["text"].lower())
        digits = re.sub(r"^[^0-9]+|[^0-9]+$", "", last["text"])
        if digits != str(day) or SequenceMatcher(None, month_name[:3], letters).ratio() < .60:
            continue
        a, b = first["box"], last["box"]
        height = max(a[3]-a[1], b[3]-b[1], 1)
        dx = (b[0]+b[2]-a[0]-a[2])/2
        dy = (b[1]+b[3]-a[1]-a[3])/2
        if dx <= 0 or abs(dy) > .85*height or b[0]-a[2] > 3*height:
            continue
        yield Prefix(0, int(digits), first["text"]+" "+last["text"], page_key, view,
                     tuple(union_box([a,b])),tuple(b),max(-.22,min(.22,dy/dx)))


def attached(prefix, box):
    left, top, right, bottom = prefix.last_box
    year_left, year_top, year_right, year_bottom = box
    height = bottom - top
    year_height = year_bottom - year_top
    if min(height, year_height) <= 0 or not .40 <= year_height/height <= 2.3:
        return False
    gap = year_left - right
    offset = ((year_left + year_right) - (left + right)) / 2
    expected_y = (top + bottom)/2 + prefix.slope * offset
    return (-.35 * height <= gap <= 3.5 * height and offset > 0
            and abs((year_top+year_bottom)/2 - expected_y) <= .73 * max(height, year_height))


def combine(prefix, raw_year, raw_word, box, page_key, view, line):
    if page_key != prefix.page or not attached(prefix, box):
        return None
    try:
        value = date(int(raw_year), prefix.month, prefix.day)
    except ValueError:
        return None
    return dict(canonical_date=value.isoformat(), page=page_key, prefix_view=prefix.view,
                prefix_text=prefix.text, prefix_box=list(prefix.box), last_prefix_box=list(prefix.last_box),
                year_view=view, year_raw=raw_word, year=raw_year, year_box=list(box),
                year_line=line["text"], confidence=line["confidence"],
                anchor_box=union_box([prefix.box, box]))
