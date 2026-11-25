from unittest import TestCase

from test_pipeline import line, mock_page, observation, task
from search_agent.scheduler import run
from base64 import b64encode
from search_agent.documents import ROOT
from search_agent.reader import ReaderRuntime
from search_agent.webapp import process


class AuditTests(TestCase):
    def setUp(self):
        self.query = task("extract", {"anchor": "relay output"})
        self.pages = [mock_page(key, {self.query.fields[0].query: [(150, 100, 265, 120)]})
                      for key in ("p1", "p2")]

    def read(self, page, spec):
        value = "100" if page.key == "p1" else "200"
        return observation(spec, [line(spec, ("relay", "output", value))])

    def test_conflicting_values_block_answer_and_preserve_both_citations(self):
        result = run(self.query, self.pages, 500_000, self.read)
        self.assertEqual(result["status"], "conflict")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["field_assessments"]["A"]["values"], ["100", "200"])
        self.assertEqual(len(result["field_assessments"]["A"]["evidence"]), 2)

    def test_scoping_resolves_conflict_through_normal_entry(self):
        query = task("extract", {"anchor": "relay output", "pages": ["p2"]})
        result = run(query, self.pages, 500_000, self.read)
        self.assertEqual(result["answer"]["value"], "200")
        self.assertEqual(result["evidence"][0]["page"], "p2")
        self.assertEqual(result["ocr_calls"], 1)

    def test_equal_values_can_be_accepted(self):
        result = run(self.query, self.pages, 500_000,
                     lambda p, s: observation(s, [line(s, ("relay", "output", "100"))]))
        self.assertEqual(result["answer"]["value"], "100")
        self.assertEqual(len(result["field_assessments"]["A"]["evidence"]), 2)

    def test_unreadable_candidate_requires_review(self):
        result = run(self.query, self.pages, 500_000,
                     lambda p, s: self.read(p, s) if p.key == "p1" else observation(s))
        self.assertEqual(result["status"], "needs_review")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["field_assessments"]["A"]["unreadable"], 1)

    def test_conflict_is_independent_of_page_order(self):
        forward = run(self.query, self.pages, 500_000, self.read)
        reverse = run(self.query, self.pages[::-1], 500_000, self.read)
        self.assertEqual(forward["field_assessments"]["A"]["values"],
                         reverse["field_assessments"]["A"]["values"])
        self.assertIsNone(reverse["answer"])

    def test_unknown_scope_rejected_before_reading(self):
        query = task("extract", {"anchor": "relay output", "pages": ["missing"]})
        with self.assertRaises(ValueError):
            run(query, self.pages, 500_000, self.read)

    def test_truncated_candidates_require_review(self):
        self.pages[0].text_hints[self.query.fields[0].query] *= 7
        result = run(self.query, self.pages[:1], 500_000, self.read)
        self.assertEqual(result["status"], "needs_review")
        self.assertTrue(result["field_assessments"]["A"]["candidate_limit_reached"])

    def test_invalid_scope_type(self):
        with self.assertRaises(ValueError):
            task("extract", {"anchor": "relay output", "pages": "p1"})

    def test_workbench_conflict_then_scope_with_real_pdf(self):
        data = (ROOT / "data/conflicts/register-01.pdf").read_bytes()
        request = {"files": [{"name": "register.pdf", "data": b64encode(data).decode()}],
                   "task": {"op": "extract", "fields": [{"anchor": "Reserve load", "window": 2}]}}
        conflict = process(request, ReaderRuntime(), None)["result"]
        self.assertEqual(conflict["status"], "conflict")
        self.assertIsNone(conflict["answer"])
        request["task"]["fields"][0]["pages"] = ["d01-p02"]
        resolved = process(request, ReaderRuntime(), None)["result"]
        self.assertEqual(resolved["status"], "answered")
        self.assertEqual(resolved["evidence"][0]["page"], "d01-p02")
