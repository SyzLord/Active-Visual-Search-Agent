from datetime import date
from types import SimpleNamespace
import unittest

import evaluate
from dates import dates_in, find_dates, NAMES, requested_date
from search_agent.task import Field


class CalendarEvidenceTests(unittest.TestCase):
    def test_spellings_share_a_calendar_value(self):
        for number, name in enumerate(NAMES, 1):
            for text in (f"17 {name}, 1935", f"{name} 17, 1935", f"{name[:3]}. 17 1935"):
                with self.subTest(text=text):
                    self.assertEqual(requested_date(text), date(1935, number, 17))
        self.assertEqual(requested_date("MAY -1 1918"), date(1918, 5, 1))
        self.assertEqual(requested_date("1948-04-03"), date(1948, 4, 3))
        self.assertEqual(requested_date("February 29, 2000"), date(2000, 2, 29))

    def test_incomplete_and_impossible_dates(self):
        for text in ("February 29, 1900", "June 31, 1948", "way 1 1918", "1 1918", "1 May",
                     "April 26 19", "notApril 26, 1918", "April 26, 19180", "May 12-14, 1958"):
            with self.subTest(text=text):
                self.assertEqual(list(dates_in(text)), [])

    def test_only_observed_matching_date_words_contribute_to_box(self):
        words = [{"text": token, "box": [offset*10, 10, offset*10+9, 20]}
                 for offset, token in enumerate(("Boston,", "October", "7,", "1947", "signed"))]
        line = {"text": "Boston, October 7, 1947 signed", "words": words, "confidence": .9}
        fields = (Field("A", "OCT 7 1947"), Field("B", "OCT 8 1947"), Field("C", "October 7, 1947", pages=("other",)))
        hits = {}
        find_dates(SimpleNamespace(key="letter"), SimpleNamespace(key="header"), [line], fields, hits)
        self.assertEqual(set(hits), {"A"})
        self.assertEqual(hits["A"]["matched_text"], "October 7, 1947")
        self.assertEqual(hits["A"]["anchor_box"], [10, 10, 39, 20])


if __name__ == "__main__":
    unittest.main()
