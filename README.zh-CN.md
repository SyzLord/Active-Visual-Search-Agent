# Active-Visual-Search-Agent

[English](README.md) · **简体中文**

## 项目简介

主动视觉搜索 Agent 在固定的 OCR 像素预算内，从高分辨率文档扫描中定位并核验收件章日期和正文。它根据已读线索选择局部区域复读，保留 OCR 原词、原图坐标和逐步像素账本。批量任务支持从本地进度文件续跑。

**实测。** 每题上限 100 万像素。新版策略在 13 个已见条件中的联合核验从 3/13 提升到 4/13。在两封新信的 4 个独立条件中，新旧策略均通过 1/4。

- [Windows 快速开始](#windows-快速开始)
- [最新实验与演示](outputs/主动视觉搜索_印章候选覆盖_2026-11-25/README.md)
- [OCR 引擎与工作台](outputs/document-evidence-agent-v3.2/README.md)

## Windows 快速开始

在管理员 PowerShell 执行 `wsl --install -d Ubuntu-24.04`。按提示重启后，从开始菜单打开 Ubuntu。接下来在 Ubuntu 终端安装依赖并运行 Griffith 示例。[Windows 安装与测试手册](batch/WINDOWS.md) · [Griffith 单任务清单](batch/examples/quickstart.json)

该示例在 macOS 上的实测结果为 **完成 1、失败 0**，结论为 `verified`。Windows/WSL 实机验收待完成。

## 批量处理

批量命令接受 JSON 任务清单，从本地 PDF 或扫描图读取指定内容。程序将 OCR 观察、坐标、像素开销和结果写入 SQLite。用同一份清单和进度文件继续运行时，程序跳过已完成的任务。修复输入后可单独重试失败项。[批量命令与配置](batch/README.md)

| 已验证的工单 | 实测表现 |
| --- | --- |
| 在 OCR 工单执行中强制停止 | 已完成任务的结果摘要一致，中断的工单重新执行。 |
| 缺失输入或预算字段无效 | 当前工单记录失败，后续工单继续执行。 |
| 同时写入同一进度文件或修改任务清单 | 命令拒绝冲突的运行请求。 |
| Griffith 信件加一张干扰页 | 在同一页核验两个字段，用了 938,863 像素。 |

完整示例包含用于测试失败隔离的无效工单。首次运行可先使用上面的单任务清单。[完整任务清单](batch/examples/jobs.json) · [验收记录](batch/acceptance-results.json)

## 复现实验

安装 Python 3 和 Node.js 后，从仓库根目录运行以下命令。记录回放使用已经归档的 OCR 词和坐标，完整复现会重新调用 OCR。

```sh
python3 tools/fetch-archive-scans.py
engine=outputs/document-evidence-agent-v3.2
python3 -m pip install -r "$engine/requirements.txt"
npm --prefix "$engine" install
cd outputs/主动视觉搜索_印章候选覆盖_2026-11-25
sh run.sh replay holdout-results.json
sh reproduce.sh
```

最新版实验使用的扫描页、冻结输入和运行记录随仓库提供。下载脚本从美国国家档案馆和司法部获取两份较大的原始 PDF 并核对 SHA-256。下载中断时可再次执行脚本续传。引擎的早期外部文档集需要另行取得。
