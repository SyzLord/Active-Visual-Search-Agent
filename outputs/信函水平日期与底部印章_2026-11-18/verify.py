"""Verify the locks, complete paired case matrix and deterministic repeat."""
import argparse
import json
from pathlib import Path

from evaluate import check_lock, DEV, HERE


def matrix(report_path, protocol_path):
    report = json.loads(report_path.read_text())
    protocol = json.loads(protocol_path.read_text())
    expected = {(item["id"], group, policy) for item in protocol["cases"] for group in protocol["collections"]
                for policy in ("heading-first", "horizontal-footer")}
    actual = {}
    for row in report["rows"]:
        key = row["case"], row["collection"], row["policy"]
        assert key not in actual
        trace = row["trace"]
        preview = sum(item["size"][0] * item["size"][1] for item in trace["preview_observations"])
        spent = 0
        for step in trace["steps"]:
            assert len(step["raw_normalized"]) == step["ocr_lines"]
            spent += step["size"][0] * step["size"][1]
            assert step["spent"] == spent
        assert spent == trace["spent"] and preview == trace["preview_pixels"]
        assert spent + preview == trace["total_pixels"] <= protocol["budget"]
        assert row["strict"] == (all(field["strict"] for field in row["fields"])
                                 and trace["answer"] == {"result": "both_located"})
        actual[key] = row
    assert set(actual) == expected
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, default=HERE / "dev.json")
    parser.add_argument("--heldout", type=Path, default=HERE / "heldout-results.json")
    parser.add_argument("--repeat", type=Path, default=HERE / "repeat.json")
    args = parser.parse_args()
    check_lock(HERE / "policy.sha256")
    check_lock(HERE / "holdout.sha256")
    development = matrix(args.development, DEV / "protocol.json")
    previous = json.loads((DEV / "results.json").read_text())
    def original_results(report):
        return {(row["case"], row["collection"]): (row["fields"], row["strict"], row["trace"]["evidence"],
                                                  row["trace"]["total_pixels"])
                for row in report["rows"] if row["policy"] == "heading-first"}
    assert original_results(development) == original_results(previous)
    first = matrix(args.heldout, HERE / "holdout.json")
    repeat = matrix(args.repeat, HERE / "holdout.json")
    published = matrix(HERE / "heldout-results.json", HERE / "holdout.json")
    for report in (first, repeat, published):
        for row in report["rows"]:
            row.pop("wall_ms")
    assert first == repeat == published
    print(f"Development {len(development['rows'])} rows; original control reproduced. "
          f"Held-out {len(first['rows'])} rows x 2; all fields, OCR words, steps and pixel ledgers identical.")
