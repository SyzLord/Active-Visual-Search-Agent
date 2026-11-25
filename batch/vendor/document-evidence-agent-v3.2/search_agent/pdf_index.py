"""Find PDF text-layer regions, retaining coordinates and no candidate values."""

from collections import defaultdict
import re

import pypdfium2
from pypdfium2 import raw

from .core import area, union_box

MAX_CHARS = 24_000
MAX_MATCHES = 6
WORD = re.compile(r"[A-Za-z0-9]")


def glyph_box(text, convert, index, size):
    left, bottom, right, top = text.get_charbox(index)
    points = [convert.to_bitmap(x, y) for x in (left, right) for y in (bottom, top)]
    x, y = zip(*points)
    return [max(0, min(x)), max(0, min(y)), min(size[0], max(x)), min(size[1], max(y))]


def candidate_boxes(text, convert, size, anchor, content, plain, compact):
    query = "".join(anchor)
    boxes = []
    start = compact.find(query)
    while start >= 0 and len(boxes) <= MAX_MATCHES:
        first, last = plain[start][1], plain[start + len(query) - 1][1]
        context = content[first:last + 1]
        # One horizontal line is required, including when the text layer dropped spaces.
        bounded = (first == 0 or not WORD.fullmatch(content[first - 1])) and (
            last + 1 == len(content) or not WORD.fullmatch(content[last + 1]))
        if bounded and "\n" not in context and "\r" not in context:
            idx = [raw.FPDFText_GetCharIndexFromTextIndex(text, plain[pos][1])
                   for pos in range(start, start + len(query))]
            glyphs = [glyph_box(text, convert, i, size) for i in idx if i >= 0]
            if len(glyphs) == len(query) and all(area(box) > 0 for box in glyphs):
                box = union_box(glyphs)
                h = sorted(g[3] - g[1] for g in glyphs)[len(glyphs) // 2]
                if box[3] - box[1] <= max(2.8 * h, 14) and box[2] - box[0] <= (len(query) + 5) * 2.2 * h:
                    boxes.append(tuple(box))
        start = compact.find(query, start + 1)
    return boxes


def index_page(page, bitmap, fields):
    if not fields:
        return {}
    text = None
    try:
        text = page.get_textpage()
        if not 0 < text.count_chars() <= MAX_CHARS:
            return {}
        convert = bitmap.get_posconv(page)
        size = bitmap.width, bitmap.height
        content = text.get_text_range()
        # PDFium text indices count UTF-16 code units.
        content = re.sub(r"[\U00010000-\U0010ffff]", "\ufffd\ufffd", content)
        plain = [(char.lower(), index) for index, char in enumerate(content) if WORD.fullmatch(char)]
        compact = "".join(char for char, _ in plain)
        output = defaultdict(list)
        for anchor in dict.fromkeys(field.query for field in fields):
            output[anchor].extend(candidate_boxes(text, convert, size, anchor, content, plain, compact))
        return dict(output)
    except pypdfium2.PdfiumError:
        return {}
    finally:
        if text is not None:
            text.close()
