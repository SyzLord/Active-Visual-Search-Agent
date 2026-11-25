from base64 import b64encode
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase

import pypdfium2
from PIL import Image, ImageDraw

from search_agent.core import ViewSpec
from search_agent.corpus import font
from search_agent.documents import ROOT, load_files, page_range, pdf_pages
from search_agent.evaluation import box_ok, check
from search_agent.reader import OCR, ReaderRuntime, project
from search_agent.scheduler import Ledger, run
from search_agent.task import field_matches, numeric, parse_task
from search_agent.webapp import process


def task(op, *fields):
    return parse_task({"op": op, "fields": list(fields)})


def mock_page(key, hints=None):
    return SimpleNamespace(key=key, name=key, size=(1200, 1600), text_hints=hints or {})


def line(spec, words, x=150, y=100):
    rows = [{"text": word, "box": [x + j * 60, y, x + j * 60 + 55, y + 20]}
            for j, word in enumerate(words)]
    return {"text": " ".join(words), "box": [x, y, rows[-1]["box"][2], y + 20],
            "confidence": .91, "raw_words": rows}


def observation(spec, lines=()):
    return {"box": list(spec.box), "size": list(spec.size), "lines": list(lines)}


class ParsingTests(TestCase):
    def test_decimal_token_forms(self):
        for token, expected in (("1,234.50", "1234.50"), ("−0.3", "-0.3"), ("26%.", "26"),
                                ("$1.08", "1.08"), ("120°F", "120"), ("-6kW", "-6")):
            with self.subTest(token=token):
                self.assertEqual(numeric(token), Decimal(expected))
        for bad in ("12,34", "NaN", "1e3", "4-5", "Infinity", "12abc"):
            self.assertIsNone(numeric(bad))

    def test_exact_anchor_and_numeric_ordinal(self):
        query = task("extract", {"anchor": "Hubble is", "ordinal": 2, "window": 6})
        seen = line(None, ("Hubble", "is", "43.5", "feet", "long", "and", "14", "feet"))
        hit, = field_matches([seen], query.fields[0], "p2", "zoom")
        self.assertEqual(hit["value"], "14")
        self.assertEqual(hit["value_box"], seen["raw_words"][6]["box"])
        fuzzy = line(None, ("HubbIe", "is", "43.5", "feet", "long", "and", "14"))
        self.assertEqual(list(field_matches([fuzzy], query.fields[0], "p2", "zoom")), [])

    def test_reject_unusable_task(self):
        for invalid in ({"op": "verify", "fields": [{"anchor": "one"}]},
                        {"op": "extract", "fields": [{"anchor": "A", "window": True}]},
                        {"op": "extract", "fields": [{"anchor": "A", "ordinal": 6, "window": 3}]}):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                parse_task(invalid)

    def test_geometry_and_page_selection(self):
        self.assertEqual(project([.1, .2, .3, .6], [100, 20, 300, 120]), [120, 40, 160, 80])
        self.assertEqual(page_range("2,5-8"), (2, 5, 6, 7, 8))
        self.assertTrue(box_ok([101, 11, 128, 19], [100, 10, 130, 20]))
        for invalid in ("8-5", "1,1", "1-25", "0"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                page_range(invalid)


class RoutingTests(TestCase):
    def test_ledger_rejects_duplicate_and_overspend(self):
        ledger = Ledger(120)
        page = mock_page("p1")
        first = ViewSpec("one", -1, "whole", (0, 0, 100, 100), (10, 10))
        ledger.buy(page, first, lambda _, spec: observation(spec), "first")
        with self.assertRaises(ValueError):
            ledger.buy(page, first, lambda _, spec: observation(spec), "again")
        other = ViewSpec("two", -1, "whole", (0, 0, 99, 99), (5, 5))
        with self.assertRaises(ValueError):
            ledger.buy(page, other, lambda _, spec: observation(spec), "over")
        self.assertEqual(ledger.spent, 100)

    def test_untrusted_index_cannot_supply_text(self):
        q = task("extract", {"anchor": "relay output"})
        page = mock_page("p1", {q.fields[0].query: [(150, 100, 265, 120)]})
        result = run(q, [page], 100_000, lambda _, spec: observation(spec), "hybrid")
        self.assertEqual(result["pdf_candidates"], {"A": 1})
        self.assertEqual(result["status"], "unresolved")
        self.assertIsNone(result["answer"])
        self.assertIn("pdf-line", {s["mode"] for s in result["steps"]})
        self.assertLessEqual(result["spent"], result["budget"])

    def test_shared_crop_is_only_charged_once(self):
        q = task("extract", {"anchor": "relay output"})
        pair = task("compare", {"anchor": "relay output"}, {"anchor": "relay output", "ordinal": 2})
        page = mock_page("p1", {q.fields[0].query: [(150, 100, 265, 120)]})

        def read(_, spec):
            return observation(spec, [line(spec, ("relay", "output", "100", "200"))])

        result = run(pair, [page], 200_000, read, "hybrid")
        self.assertEqual(result["answer"]["larger"], "B")
        self.assertEqual(result["ocr_calls"], 1)
        self.assertEqual({e["view"] for e in result["evidence"]}, {result["steps"][0]["view"]})

    def test_image_only_fallback_and_refusal(self):
        q = task("verify", {"anchor": "relay output"}, {"anchor": "reserve power"})
        pages = [mock_page("p1"), mock_page("p2")]
        result = run(q, pages, 800_000,
                     lambda p, s: observation(s, [line(s, ("relay", "output"))] if p.key == "p1" else []))
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["pdf_candidates"], {"A": 0, "B": 0})
        self.assertEqual([e["page"] for e in result["evidence"]], ["p1"])
        self.assertEqual(sum(s["pixels"] for s in result["steps"]), result["spent"])

    def test_strict_scoring_rejects_right_value_on_wrong_page(self):
        q = task("extract", {"anchor": "relay output"})
        raw = line(None, ("relay", "output", "100"))
        hit, = field_matches([raw], q.fields[0], "p1", "view")
        case = SimpleNamespace(gold={"A": {**hit, "page": "p2"}})
        score = check(case, q, {"answer": {"value": "100", "unit": ""}, "evidence": [hit]})
        self.assertTrue(score["answer_ok"])
        self.assertFalse(score["strict"])


class IntegrationTests(TestCase):
    def test_pdf_coordinates_and_two_page_values(self):
        from search_agent.corpus import example
        pages, raw = example("hubble-distance", index=True)
        q = parse_task(raw)
        self.assertEqual([p.key for p in pages], ["nasa-p01", "nasa-p02"])
        self.assertIn(q.fields[0].query, pages[0].text_hints)
        with OCR(ReaderRuntime()) as engine:
            result = run(q, pages, 2_600_000, lambda page, spec: page.observe(spec, engine))
        self.assertEqual(result["answer"]["difference"], "-114")
        self.assertEqual([e["page"] for e in result["evidence"]], ["nasa-p01", "nasa-p02"])
        self.assertLess(result["spent"], 150_000)
        self.assertTrue(all(s["mode"] == "pdf-line" for s in result["steps"]))

    def test_image_only_pdf_falls_back(self):
        pixels = Image.new("RGB", (650, 900), "white")
        ImageDraw.Draw(pixels).text((60, 300), "Cedar relay output 137", font=font(41, "Bold"), fill="black")
        bitmap = pypdfium2.PdfBitmap.from_pil(pixels)
        doc = pypdfium2.PdfDocument.new()
        page = doc.new_page(260, 360)
        obj = pypdfium2.PdfImage.new(doc)
        try:
            obj.set_bitmap(bitmap)
            obj.set_matrix(pypdfium2.PdfMatrix().scale(260, 360))
            page.insert_obj(obj)
            page.gen_content()
            payload = BytesIO()
            doc.save(payload)
        finally:
            page.close()
            bitmap.close()
            doc.close()
        q = task("extract", {"anchor": "Cedar relay output", "window": 2})
        pages = pdf_pages(payload.getvalue(), fields=q.fields)
        self.assertEqual(pages[0].text_hints, {})
        with OCR(ReaderRuntime()) as engine:
            result = run(q, pages, 800_000, lambda p, s: p.observe(s, engine))
        self.assertEqual(result["pdf_candidates"], {"A": 0})
        self.assertEqual(result["steps"][0]["view"], "survey")
        self.assertEqual(result["answer"]["value"], "137")

    def test_workbench_accepts_local_pdf_and_returns_actual_rasters(self):
        source = (ROOT / "data/external/pdf/nasa.pdf").read_bytes()
        raw = {"op": "difference", "fields": [{"anchor": "from a distance of", "window": 2},
                                               {"anchor": "dime", "window": 2}], "unit": "mi"}
        result = process({"task": raw, "files": [{"name": "nasa.pdf", "data": b64encode(source).decode()}],
                          "pages": "1-2"}, ReaderRuntime(), None)
        self.assertEqual(result["result"]["answer"]["difference"], "-114")
        self.assertEqual(len(result["views"]), result["result"]["ocr_calls"])
        self.assertTrue(all(img.startswith("data:image/jpeg;base64,") for img in result["views"]))
        self.assertEqual([p["id"] for p in result["result"]["pages"]], ["d01-p01", "d01-p02"])
        with self.assertRaises(ValueError):
            load_files([("1.jpg", b"invalid")], (1,))
