# Active-Visual-Search-Agent
Finds and verifies evidence in high-resolution document scans under a fixed OCR pixel budget.

The agent preserves the read trace, coordinates in the original scan, and a ledger of every OCR pixel read. The latest experiment capped each query at 1,000,000 pixels. Joint stamp-date and body-text verification improved from 3/13 to 4/13 on previously seen conditions. Both strategies passed 1/4 conditions on two new letters.

- [Latest experiment and demo](outputs/主动视觉搜索_印章候选覆盖_2026-11-25/README.md)
- [OCR engine and app](outputs/document-evidence-agent-v3.2/README.md)

## Replay

Install Python 3 and Node.js. Install the documented OCR runtime dependencies. The offline comparison consumes archived OCR readings. The full experiment reruns the OCR engine.

```sh
python3 tools/fetch-archive-scans.py
engine=outputs/document-evidence-agent-v3.2
python3 -m pip install -r "$engine/requirements.txt"
npm --prefix "$engine" install
cd outputs/主动视觉搜索_印章候选覆盖_2026-11-25
sh run.sh replay holdout-results.json
sh reproduce.sh
```

The latest experiment includes its pinned inputs and fixtures. The engine's separate historical external-document collections are not included in this public copy.

Two large historical PDFs are fetched from the U.S. National Archives and Department of Justice and verified by SHA-256. The scanned pages, frozen inputs, and trial logs used by the current experiment are included.
