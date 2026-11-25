"""Read full English month names and postal date separators from actual OCR words."""
from dataclasses import replace
from datetime import date
import re

from date_repair import date_hits as legacy_hits, words_for
from search_agent.core import union_box
from search_agent.task import valid_box


NAMES = "January February March April May June July August September October November December".lower().split()
NUMBERS = {alias: number for number, name in enumerate(NAMES, 1) for alias in (name, name[:3])}
NUMBERS["sept"] = 9
MONTH = "(?P<month>" + "|".join(sorted(NUMBERS, key=len, reverse=True)) + ")"
DAY = r"(?P<day>[0-9](?:[ \t]*[0-9])?)"
YEAR = r"(?P<year>[0-9]{4})"
TO_YEAR = r"(?:[ \t]*[,\-‐‑–—][ \t]*|[ \t]+)"
PATTERNS = tuple(re.compile(r"(?<!\w)" + pattern + r"(?!\w)", re.I) for pattern in (
    MONTH + r"\.?[ \t]*[-‐‑–—]?[ \t]*" + DAY + TO_YEAR + YEAR,
    DAY + r"[ \t]+" + MONTH + r"\.?" + TO_YEAR + YEAR,
    YEAR + r"-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})",
))


def dates_in(text):
    for pattern in PATTERNS:
        for match in pattern.finditer(text):
            month = match["month"].lower()
            month_number = int(month) if month.isdigit() else NUMBERS[month]
            try:
                value = date(int(match["year"]), month_number, int("".join(match["day"].split())))
            except ValueError:
                continue
            yield match, value


def requested_date(anchor):
    return next((value for match, value in dates_in(anchor) if match.span() == (0, len(anchor))), None)


def find_dates(page, spec, lines, fields, hits):
    wanted = {field.id: (field, requested_date(field.anchor)) for field in fields
              if field.id not in hits and (not field.pages or page.key in field.pages)}
    if not wanted:
        return
    for line in sorted(lines, key=lambda item: item["confidence"], reverse=True):
        words = words_for(line)
        spans, cursor = [], 0
        for word in words:
            end = cursor + len(word["text"])
            spans.append((cursor, end, word["box"]))
            cursor = end + 1
        text = " ".join(word["text"] for word in words)
        for match, value in dates_in(text):
            for key, (field, target) in wanted.items():
                if key in hits or target != value:
                    continue
                box = union_box([box for start, end, box in spans if start < match.end() and end > match.start()])
                if valid_box(box):
                    hits[key] = dict(field=key, anchor=field.anchor, page=page.key, view=spec.key,
                                     box=box, anchor_box=box, value=None, value_box=None,
                                     matched_text=match[0], canonical_date=value.isoformat(), line=line["text"],
                                     confidence=line["confidence"], match_type="calendar_date")
    missing = [replace(field, anchor=target.isoformat()) for key, (field, target) in wanted.items()
               if key not in hits and target is not None]
    if missing:
        legacy_hits(page, spec, lines, missing, hits)
        for field in missing:
            if field.id in hits:
                hits[field.id]["anchor"] = wanted[field.id][0].anchor
