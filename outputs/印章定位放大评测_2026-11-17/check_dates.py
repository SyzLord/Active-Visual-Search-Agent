from datetime import date
from types import SimpleNamespace
import unittest

from run_scan import HERE
from date_match import anchor_date, matches
from edge_scan import date_hits


class DateTests(unittest.TestCase):
    def test_equivalent_forms(self):
        expected = date(1971, 3, 23)
        for text in ("MAR2 3 1971", "23 Mar. 1971", "1971-03-23", "Mar 23, 1971"):
            self.assertEqual(anchor_date(text), expected, text)
        self.assertEqual(anchor_date("Feb 29 2000"), date(2000, 2, 29))

    def test_other_and_invalid_dates(self):
        self.assertNotEqual(anchor_date("MAR 24 1971"), date(1971, 3, 23))
        self.assertEqual(anchor_date("17 DEC 1962"), date(1962, 12, 17))
        for text in ("Feb 29 1900", "Apr 31 2024", "Mar 00 1971", "Mar 23 0000",
                     "Mar XX 1971", "SMART MARION 23 1971", "MAR 23 19711",
                     "XMAr23 1971", "MAR2 3\n1971", "1971-13-23", "03/04/1971"):
            self.assertEqual(list(matches(text)), [], text)

    def test_boxes_are_only_for_consumed_words(self):
        words = [{"text": text, "box": [i*10, 5, i*10+8, 15]}
                 for i,text in enumerate("STAMP MAR2 3 1971 RECEIVED".split())]
        line = {"text": "STAMP MAR2 3 1971 RECEIVED", "confidence": .93,
                "words": words, "raw_words": words}
        hits = {}
        field = SimpleNamespace(id="A", anchor="MAR 23 1971", pages=("right-page",))
        spec = SimpleNamespace(key="right")
        date_hits(SimpleNamespace(key="wrong-page"), spec, [line], [field], hits)
        self.assertFalse(hits)
        date_hits(SimpleNamespace(key="right-page"), spec, [line], [field], hits)
        self.assertEqual(hits["A"]["anchor_box"], [10,5,38,15])
        self.assertEqual(hits["A"]["matched_text"], "MAR2 3 1971")


if __name__ == "__main__":
    unittest.main(verbosity=2)
