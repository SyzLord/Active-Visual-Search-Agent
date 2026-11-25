"""Conservative, locale-independent equivalence for English date anchors."""
from datetime import date
import re

MONTHS = dict(zip("jan feb mar apr may jun jul aug sep oct nov dec".split(), range(1, 13)))
MONTH = "(?:" + "|".join(MONTHS) + ")"
DAY = r"[0-9](?:[ \t]*[0-9])?"
PATTERNS = (
    re.compile(rf"(?<!\w)(?P<month>{MONTH})\.?[ \t]*(?P<day>{DAY}),?[ \t]+(?P<year>[0-9]{{4}})(?!\w)", re.I),
    re.compile(rf"(?<!\w)(?P<day>{DAY})[ \t]+(?P<month>{MONTH})\.?,?[ \t]+(?P<year>[0-9]{{4}})(?!\w)", re.I),
    re.compile(r"(?<!\w)(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})(?!\w)"),
)


def matches(text):
    for pattern in PATTERNS:
        for match in pattern.finditer(text):
            values = match.groupdict()
            month = values["month"].lower()
            try:
                canonical = date(int(values["year"]),
                                 int(month) if month.isascii() and month.isdigit() else MONTHS[month],
                                 int("".join(values["day"].split())))
            except ValueError:
                continue
            yield match, canonical


def anchor_date(text):
    return next((value for match, value in matches(text) if match.span() == (0, len(text))), None)
