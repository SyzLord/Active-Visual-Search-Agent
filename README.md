# Active-Visual-Search-Agent

**English** · [简体中文](README.zh-CN.md)

## Overview

Active Visual Search Agent locates and verifies receipt stamp dates and body text in high-resolution document scans under a fixed OCR pixel budget. It uses earlier OCR observations to select regions for a closer read, and records the raw OCR text, source-image coordinates, and pixel cost of each step. Batch jobs can resume from a local progress file.

**Results.** With a cap of 1,000,000 pixels per query, the updated policy improved joint verification from 3/13 to 4/13 on previously seen conditions. Both policies passed 1/4 conditions across two held-out letters.

- [Windows quickstart](#windows-quickstart)
- [Latest experiment and demo (Chinese)](outputs/主动视觉搜索_印章候选覆盖_2026-11-25/README.md)
- [OCR engine and app (Chinese)](outputs/document-evidence-agent-v3.2/README.md)

<a name="windows-快速开始"></a>

## Windows quickstart

Run `wsl --install -d Ubuntu-24.04` in an administrator PowerShell window. Restart if prompted, then open Ubuntu from the Start menu. Run the following commands in Ubuntu:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv nodejs npm
cd ~
git clone https://github.com/SyzLord/Active-Visual-Search-Agent.git
cd Active-Visual-Search-Agent/batch
python3 -m venv .venv
.venv/bin/python -m pip install -r vendor/document-evidence-agent-v3.2/requirements.txt
npm --prefix vendor/document-evidence-agent-v3.2 install
export VISUAL_SEARCH_PYTHON="$PWD/.venv/bin/python"
mkdir -p local-run
sh batch.sh run examples/quickstart.json --state local-run/quickstart.sqlite
sh batch.sh status --state local-run/quickstart.sqlite
```

The [single-job example](batch/examples/quickstart.json) should report one completed job, zero failures, and a `verified` result. Rerun the same command with the same state file to resume. The example has been verified on macOS. End-to-end Windows/WSL testing is pending. [Detailed setup and troubleshooting (Chinese)](batch/WINDOWS.md)

## Batch processing

The batch CLI accepts JSON job lists for local scans and PDFs. It records OCR reads, coordinates, pixel costs and results in SQLite. Restarting with the same manifest preserves completed jobs. A failed job can be retried separately once its inputs are repaired. [Batch CLI reference (Chinese)](batch/README.md)

| Verified scenario | Observed behavior |
| --- | --- |
| Force-stop during an OCR job | The completed result kept its digest. Only the interrupted job was run again. |
| Missing input or invalid budget | The job was recorded as failed. Later jobs still ran. |
| Second writer or changed job list | The CLI rejected the conflicting run. |
| Griffith scan with a distractor page | Both requested fields were verified on the same page in 938,863 pixels. |

See the [job manifest](batch/examples/jobs.json) and [recorded acceptance checks](batch/acceptance-results.json). The example deliberately includes invalid jobs to exercise failure handling. No explicit resume action is required beyond rerunning the same manifest and state file.

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
Run the fetch command again to resume a partial archive download. The scans are checked before use.
