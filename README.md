# Active-Visual-Search-Agent
Finds and verifies evidence in high-resolution document scans under a fixed OCR pixel budget.

The agent preserves the read trace, coordinates in the original scan, and a ledger of every OCR pixel read. The latest experiment capped each query at 1,000,000 pixels. Joint stamp-date and body-text verification improved from 3/13 to 4/13 on previously seen conditions. Both strategies passed 1/4 conditions on two new letters.

- [Windows 快速开始](#windows-快速开始)
- [Latest experiment and demo](outputs/主动视觉搜索_印章候选覆盖_2026-11-25/README.md)
- [OCR engine and app](outputs/document-evidence-agent-v3.2/README.md)

## Windows 快速开始

在 Windows 的管理员 PowerShell 执行 `wsl --install -d Ubuntu-24.04`。按提示重启后，从开始菜单打开 Ubuntu，在 Ubuntu 终端操作。

[Windows 安装与测试手册](batch/WINDOWS.md)包含环境安装、样例运行、结果导出和断点续跑步骤。用仓库自带的 [Griffith 单任务清单](batch/examples/quickstart.json)开始，参考结果为 **完成 1、失败 0**，结论为 `verified`。

## Batch processing

[Batch CLI and setup](batch/README.md) accepts JSON job lists for local scans and PDFs. It records OCR reads, coordinates, pixel costs and results in SQLite. Restarting with the same manifest preserves completed jobs. A failed job can be retried separately once its inputs are repaired.

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
