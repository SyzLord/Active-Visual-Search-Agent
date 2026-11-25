"""Structured queries and evidence extraction from one paid OCR observation."""

from dataclasses import dataclass
from decimal import Decimal
import re

from .core import tokens, union_box

OPERATIONS = ("locate", "verify", "extract", "compare", "difference")
NUMBER = re.compile(r"^([+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)$")
EDGE = " \t$€£%°:;?![]{}()\"“”'’"
WORD = re.compile(r"[A-Za-z0-9]+")
SUFFIXES = ("mph", "lumens", "watts", "ft", "in", "kw", "km", "mm", "cm", "mi",
            "m", "w", "f", "c", "k", "h")


@dataclass(frozen=True)
class Field:
    id: str
    anchor: str
    kind: str = "span"
    direction: str = "after"
    window: int = 5
    ordinal: int = 1
    pages: tuple = ()

    @property
    def query(self):
        return tokens(self.anchor)


@dataclass(frozen=True)
class Task:
    op: str
    fields: tuple
    unit: str = ""


def parse_task(raw):
    if not isinstance(raw, dict) or raw.get("op") not in OPERATIONS:
        raise ValueError("操作需为 locate、verify、extract、compare 或 difference")
    op = raw["op"]
    items = raw.get("fields")
    if not isinstance(items, list):
        raise ValueError("请提供字段列表")
    count = 1 if op in ("locate", "extract") else 2
    if len(items) != count:
        raise ValueError(f"{op} 需要 {count} 个字段")
    expected = "number" if op in ("extract", "compare", "difference") else "span"
    result = []
    for index, row in enumerate(items):
        if not isinstance(row, dict):
            raise ValueError("字段应为对象")
        anchor = row.get("anchor")
        if not isinstance(anchor, str) or not 1 <= len(tokens(anchor)) <= 8 or len(anchor) > 96:
            raise ValueError("每个锚点需含 1–8 个英文字母或数字词，最多 96 字符")
        field = Field(row.get("id", chr(ord("A") + index)), anchor.strip(), row.get("kind", expected),
                      row.get("direction", "after"), row.get("window", 5), row.get("ordinal", 1),
                      tuple(row.get("pages", [])) if isinstance(row.get("pages", []), list) else None)
        if (field.pages is None or len(field.pages) > 24
                or any(not isinstance(p, str) or not 1 <= len(p) <= 100 for p in field.pages)):
            raise ValueError("pages 应为最多 24 个页面 ID 的列表")
        if (not isinstance(field.id, str) or not re.fullmatch("[A-Za-z][A-Za-z0-9_]{0,15}", field.id)
                or field.kind != expected or field.direction not in ("before", "after")
                or type(field.window) is not int or type(field.ordinal) is not int
                or not 1 <= field.ordinal <= field.window <= 8):
            raise ValueError("字段类型、方向、搜索窗口或编号无效")
        result.append(field)
    if len({f.id for f in result}) != count:
        raise ValueError("字段 ID 必须唯一")
    unit = raw.get("unit", "")
    if not isinstance(unit, str) or len(unit) > 20 or any(ord(c) < 32 for c in unit):
        raise ValueError("单位最多 20 字符")
    return Task(op, tuple(result), unit.strip())


def lexical(raw_words):
    """Preserve raw indices for numeric punctuation and anchor positions."""
    out = []
    for index, word in enumerate(raw_words):
        for match in WORD.finditer(word["text"]):
            out.append((match[0].lower(), index))
    return out


def numeric(raw):
    text = raw.strip(EDGE)
    if text.endswith(".") or text.endswith(","):
        text = text[:-1].strip(EDGE)
    # Handle attached common units while keeping punctuation in the OCR token.
    for suffix in SUFFIXES:
        if text.lower().endswith(suffix):
            text = text[:-len(suffix)].rstrip("°")
            break
    found = NUMBER.fullmatch(text)
    if not found or sum(c.isdigit() for c in text) > 18:
        return None
    return Decimal(found[1].replace(",", "").replace("−", "-"))


def scalar(value):
    return format(value.normalize(), "f") if value else "0"


def valid_box(box):
    return len(box) == 4 and box[2] > box[0] and box[3] > box[1]


def field_matches(lines, field, page, view):
    """An accepted value must be visible beside an exact anchor on the same OCR line."""
    if field.pages and page not in field.pages:
        return
    query = field.query
    for line in lines:
        raw = line.get("raw_words", line.get("words", []))
        lex = lexical(raw)
        words = [pair[0] for pair in lex]
        for start in range(len(words) - len(query) + 1):
            if tuple(words[start:start + len(query)]) != query:
                continue
            left = lex[start][1]
            right = lex[start + len(query) - 1][1]
            anchor_box = union_box([w["box"] for w in raw[left:right + 1]])
            if not valid_box(anchor_box):
                continue
            value, value_box = None, None
            if field.kind == "number":
                indices = (range(right + 1, min(len(raw), right + 1 + field.window))
                           if field.direction == "after"
                           else range(left - 1, max(-1, left - 1 - field.window), -1))
                values = [(numeric(raw[i]["text"]), raw[i]["box"]) for i in indices]
                values = [(number, box) for number, box in values if number is not None and valid_box(box)]
                if len(values) < field.ordinal:
                    continue
                number, value_box = values[field.ordinal - 1]
                value = scalar(number)
            yield {
                "field": field.id, "page": page, "view": view, "anchor": field.anchor,
                "anchor_box": anchor_box, "value": value, "value_box": value_box,
                "box": union_box([anchor_box, value_box]) if value_box else anchor_box,
                "line": line["text"], "confidence": round(float(line["confidence"]), 4),
            }


def answer(task, evidence):
    if len(evidence) != len(task.fields):
        return None
    if task.op == "locate":
        return {"page": evidence[0]["page"]}
    if task.op == "verify":
        return {"result": "both_located"}
    numbers = [Decimal(hit["value"]) for hit in evidence]
    if task.op == "extract":
        return {"value": scalar(numbers[0]), "unit": task.unit}
    if task.op == "compare":
        result = "equal" if numbers[0] == numbers[1] else task.fields[int(numbers[1] > numbers[0])].id
        return {"larger": result, "values": [scalar(v) for v in numbers], "unit": task.unit}
    return {"difference": scalar(numbers[0] - numbers[1]),
            "values": [scalar(v) for v in numbers], "unit": task.unit}
