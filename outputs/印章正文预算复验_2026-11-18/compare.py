"""Verify both budget ledgers and print all changed fixture outcomes."""
import argparse
import json
from pathlib import Path


def indexed(path):
    rows = json.loads(path.read_text())["rows"]
    by_key = {}
    for row in rows:
        result = row.get("trace", row)
        mode = row.get("mode", row.get("strategy"))
        if mode == "date-then-article":
            mode = "stamp-locate"
        key = (row.get("collection", ""), mode, row.get("case", row.get("id")), result["budget"])
        assert key not in by_key, key
        total = 0
        for index, step in enumerate(result["steps"], 1):
            assert step["step"] == index and step["pixels"] == step["size"][0] * step["size"][1], key
            total += step["pixels"]
            assert step["spent"] == total, key
        spent = total + result.get("preview_pixels", 0)
        assert spent == row.get("total_pixels", result.get("total_pixels", spent)) <= result["budget"], key
        by_key[key] = (row, result, spent)
    return by_key


def compare(baseline, treatment):
    before, after = indexed(baseline), indexed(treatment)
    assert before.keys() == after.keys()
    before_ok = after_ok = gains = losses = article_hits = 0
    for key, (old, base, old_pixels) in before.items():
        new, tested, new_pixels = after[key]
        before_ok += old["strict"]
        after_ok += new["strict"]
        gains += new["strict"] and not old["strict"]
        losses += old["strict"] and not new["strict"]
        if "date_pages" in tested:
            detected = set(tested["date_pages"])
            assert detected <= {hit["page"] for hit in tested["evidence"]}, key
            if key[0]:
                for _, result, _ in (before[key], after[key]):
                    date = [hit for hit in result["evidence"] if hit["field"] == "A"]
                    assert all(hit["page"] == "marsh01" and hit["canonical_date"] == "1948-04-03"
                               for hit in date), key
            article_hits += new["strict"]
        if base.get("strategy") == "date-then-article" or "date_pages" in tested or old["strict"] != new["strict"]:
            print(key, f"strict {int(old['strict'])}→{int(new['strict'])}",
                  f"pixels {old_pixels}→{new_pixels}",
                  [(h["field"], h["page"], h["view"], h.get("matched_text", h["anchor"]))
                   for h in tested["evidence"]])
    print(f"{len(before)} rows validated. Strict {before_ok}→{after_ok}. "
          f"Gained {gains}, lost {losses}. Date-then-article strict {article_hits}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("treatment", type=Path)
    args = parser.parse_args()
    compare(args.baseline, args.treatment)
