"""Apply the same frozen field checks to either registered copy of a receipt."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

import evaluate


score_single = evaluate.grader.score


def score(fields, gold, trace, protocol):
    scores = []
    for field, expected in zip(fields, gold, strict=True):
        boxes = [expected["box"], *expected.get("alternative_boxes", [])]
        options = []
        for index, box in enumerate(boxes):
            result, = score_single([field], [dict(expected, box=box)], trace, protocol)
            options.append(dict(result, reference=index, reference_box=box))
        scores.append(max(options, key=lambda item: (item["strict"], item["iou"], item["coverage"])))
    return scores


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output path")
    assert evaluate.digest(evaluate.HERE / "policy.sha256") == json.loads(
        (evaluate.HERE / "holdout.json").read_text())["policy_lock_sha256"]
    with patch.object(evaluate.grader, "score", score):
        report = evaluate.evaluate("holdout")
    with args.output.open("x") as handle:
        json.dump(report, handle, ensure_ascii=False, separators=(",", ":"))
