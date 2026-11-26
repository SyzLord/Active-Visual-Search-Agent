# Windows 安装与测试

在 Windows 11 或支持 WSL 2 的 Windows 10 上，通过 **WSL 2 + Ubuntu 24.04** 运行批量取证。下面的示例从仓库自带的两张真实扫描中核验收件章与正文，依赖安装完成后可离线执行。批量任务使用 Linux 文件锁，PowerShell 用于安装 WSL，后续项目命令在 Ubuntu 终端执行。[微软 WSL 安装说明](https://learn.microsoft.com/zh-cn/windows/wsl/install)

## 1. 在 PowerShell 安装 Ubuntu

以管理员身份打开 PowerShell，执行第一条命令。按提示重启，从开始菜单打开 Ubuntu 24.04，并按提示创建 Linux 用户。已经安装 Ubuntu 24.04 的读者可以直接检查版本。

```powershell
wsl --install -d Ubuntu-24.04
wsl --list --verbose
```

列表里 Ubuntu 24.04 的 `VERSION` 应为 `2`。若显示 `1`，在 PowerShell 执行 `wsl --set-version Ubuntu-24.04 2`。

## 2. 在 Ubuntu 终端安装并进入项目

从这一步开始，将命令粘贴到 **Ubuntu** 终端。将项目克隆到 Linux 家目录，SQLite 进度和文件锁都留在同一套 Linux 文件系统。已有仓库时进入其 `batch` 目录即可。

```bash
sudo apt update
sudo apt install -y git python3 python3-venv nodejs npm
cd ~
git clone https://github.com/SyzLord/Active-Visual-Search-Agent.git
cd Active-Visual-Search-Agent/batch
python3 -m venv .venv
.venv/bin/python -m pip install -r vendor/document-evidence-agent-v3.2/requirements.txt
npm --prefix vendor/document-evidence-agent-v3.2 install
.venv/bin/python -c "import sqlite3; print('SQLite', sqlite3.sqlite_version)"
node --version
```

所需版本为 Python 3.11 以上、Node.js 18 以上、SQLite 3.35 以上。已有 `visual-search-batch.zip` 时，也可以把解压后的 `visual-search-batch` 目录复制到 Ubuntu 家目录，进入该目录执行从创建 `.venv` 开始的命令。批量示例的扫描与英文 OCR 权重随仓库提供。

## 3. 运行一个真实工单

在每次新开的 Ubuntu 终端进入 `batch` 目录，再执行下面的命令。对于移植包，进入 `visual-search-batch` 目录。

```bash
export VISUAL_SEARCH_PYTHON="$PWD/.venv/bin/python"
mkdir -p local-run
sh batch.sh validate examples/quickstart.json
sh batch.sh run examples/quickstart.json --state local-run/quickstart.sqlite
sh batch.sh status --state local-run/quickstart.sqlite
sh batch.sh show griffith-stamp --state local-run/quickstart.sqlite > local-run/griffith.json
```

看最后的状态表。验收参考为 **完成 1、失败 0**，`griffith-stamp` 的结论为 `verified`。在 Mac 的源仓库实测中，该工单在第二页找到两条证据，花费 938,863 像素。当前的强制中断与续跑验收也在 Mac 完成，Windows/WSL 还需要实机核验。

- **测试续跑**：再次执行相同的 `run` 命令，已完成的任务会显示 `skipped`。执行中按 Ctrl+C，再次运行同一清单和进度文件，程序会从头重试未提交的任务。
- **换自己的扫描**：在 Ubuntu 执行 `explorer.exe .` 打开当前目录，把文件复制到 `examples/data/`。复制并修改 [单任务清单](examples/quickstart.json)，`files` 相对于清单目录，使用 `data/你的扫描.png` 这种路径。新清单配一个新的 `.sqlite`。
- **测试失败隔离**：用 `examples/jobs.json` 和一个新的进度文件运行完整批次。参考结果为完成 3、失败 2，两个失败分别检验缺文件和超预算。该批次返回退出码 1。

命令找不到 `batch.sh` 时，用 `pwd` 和 `ls` 核对当前目录。若提示缺少 Tesseract.js，确认已在 Ubuntu 终端执行 `npm --prefix vendor/document-evidence-agent-v3.2 install`。若出现依赖摘要变化，优先在 Ubuntu 家目录重新克隆，以保留仓库里的原始字节。[完整清单与证据字段说明](README.md)
