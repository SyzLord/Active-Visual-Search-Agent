"""Regression coverage for document OCR date matches and false joins."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "印章定位放大评测_2026-11-17"))
import run_scan
from date_repair import date_hits


def line(*pairs):
    return {"text": " ".join(text for text, _ in pairs), "confidence": .8,
            "raw_words": [{"text": text, "box": box} for text, box in pairs]}


def match(lines, anchor="APR 3 1948"):
    hits = {}
    field = SimpleNamespace(id="A", anchor=anchor, pages=())
    date_hits(SimpleNamespace(key="fixture"), SimpleNamespace(key="stamp:1"),
              lines, [field], hits)
    return hits.get("A")


class DateRepairTests(unittest.TestCase):
    def test_hyphen_and_original_words(self):
        hit = match([line(("apR3-", [121,388,145,478]), ("1948", [104,326,155,375]),
                          ("©", [108,275,133,299]))])
        self.assertEqual(hit["match_type"], "normalized_date_hyphen")
        self.assertEqual(hit["anchor_box"], [104,326,155,478])
        self.assertEqual(hit["matched_text"], "apR3- 1948")
        self.assertEqual(hit["canonical_date"], "1948-04-03")

    def test_adjacent_ocr_segments(self):
        left = line(("APR3", [1499,305,1523,377]))
        year = line(("1948", [1501,411,1524,457]))
        hit = match([left, year])
        self.assertEqual(hit["anchor_box"], [1499,305,1524,457])
        self.assertEqual(hit["match_type"], "normalized_date_adjacent_lines")

    def test_distant_unaligned_and_nonadjacent_years(self):
        first = line(("APR3", [1499,305,1523,377]))
        self.assertIsNone(match([first, line(("1948", [1501,470,1524,517]))]))
        self.assertIsNone(match([first, line(("1948", [1530,411,1553,457]))]))
        self.assertIsNone(match([first, line(("CODE", [1501,382,1524,407])),
                                 line(("1948", [1501,411,1524,457]))]))
        self.assertIsNone(match([first, line(("1948", [1501,411,1524,457]),
                                           ("copies", [1501,460,1525,520]))]))

    def test_original_match_and_invalid_dates(self):
        prior = match([line(("MAR2", [12,5,25,15]), ("3", [27,5,34,15]), ("1971", [37,5,66,15]))],
                      anchor="1971-03-23")
        self.assertEqual(prior["canonical_date"], "1971-03-23")
        self.assertEqual(prior["match_type"], "normalized_date")
        wrong = line(("1947", [1501,411,1524,457]))
        self.assertIsNone(match([line(("APR3", [1499,305,1523,377])), wrong]))
        bad = line(("APR31-", [1499,305,1523,377]), ("1948", [1501,411,1524,457]))
        self.assertIsNone(match([bad], anchor="APR 30 1948"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
