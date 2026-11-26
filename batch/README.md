# 批量文档取证与断点续跑

用一份 JSON 清单批量读取本机扫描。每项查询独立使用 100 万像素，结果、OCR 原词、裁剪坐标、输入摘要与实际开销一并落盘。清单里可以同时放收件章工单和 3.2 文档查询。两条路径分别复用 11 月 25 日搜索规则与 3.2 的候选核验。

## 运行一个批次

从 GitHub 克隆后进入 `batch`，从移植包解压后进入 `visual-search-batch`。环境需要 macOS 或 Linux、本地 SQLite 3.35 以上、Python 3.11 以上和 Node.js 18 以上。Windows 用户可先配置 WSL 2。首次安装依赖时执行以下命令。[Windows 从安装到测试](WINDOWS.md)

~~~sh
python3 -m venv .venv
.venv/bin/python -m pip install -r vendor/document-evidence-agent-v3.2/requirements.txt
npm --prefix vendor/document-evidence-agent-v3.2 install
export VISUAL_SEARCH_PYTHON="$PWD/.venv/bin/python"
~~~

英文 OCR 权重随包携带。在有依赖的机器上，查询与验收在本地完成。可通过 `VISUAL_SEARCH_NODE` 指定 Node 解释器。

~~~sh
out=$(mktemp -d)
sh batch.sh validate examples/jobs.json
sh batch.sh run examples/jobs.json --state "$out/progress.sqlite"
sh batch.sh status --state "$out/progress.sqlite"
sh batch.sh show griffith-stamp --state "$out/progress.sqlite" > "$out/griffith.json"
sh batch.sh attempts --state "$out/progress.sqlite" > "$out/attempts.json"
~~~

`examples/jobs.json` 中的缺文件及错误预算会使 `validate`、`run` 分别返回 1。其余查询继续执行。首次测试也可将命令中的清单换为 [examples/quickstart.json](examples/quickstart.json)，只执行 Griffith 双页工单，预期退出码 0。状态命令可加 `--json`，运行命令为逐行 JSON 事件。退出码 0 表示命令成功且无执行错误，1 表示一项或多项校验或执行失败，2 表示清单、环境或进度文件级错误，130 表示键盘中断。

## 清单与证据

最外层为 `{"version":1,"jobs":[...]}`。每项需要唯一 `id`、任务类型 `kind` 及 `files`。文件路径相对于清单所在目录。支持 JPEG、PNG、WebP、PDF。单个 PDF 可用 `"pages":"2,5-8"` 选择页面，沿用 3.2 的单文件 16 MiB、全任务 32 MiB、最多 24 页及输入尺寸限制。

| 类型 | 需要填写 | 实际执行 |
|---|---|---|
| `stamp` | 英文日期 `date` 和正文锚点 `text`。可选 `policy` | 默认按月份重排页底候选 `month-routed-stamp`，也可选上一轮 `spare-stamp`。正文和收件章必须在同页才能核验。 |
| `document` | 3.2 的 `task` 对象 | 使用 `audited` 搜索候选，支持 locate、verify、extract、compare、difference。PDF 文字层可定位候选，裁剪 OCR 提供图像证据。 |

`pixel_budget` 可省略，或填整数 `1000000`。预览和每一次局部重读都按实际输入像素收费。核验、部分结果、未定位、冲突等结论保存在 `result.decision.status`，都可以完成一次任务。文件缺失、无效任务、OCR 超时等执行错误记为 `failed`。在 `result.trace.steps` 查每次观察的页号、坐标、宽高、累计支出、真实识别词与编码输入 SHA-256。在 `result.sources` 查实际读入的文件大小及 SHA-256。

## 中断和重试

再次传入同一份清单和同一个进度文件即可续跑。程序跳过完成项和已标记失败项，重新执行中断时正在运行的项。若缺失文件已补齐，使用 `--retry-failed` 只重试失败项，以及本来就待执行的项。修改清单内容后应使用新的进度文件。清单按 JSON 内容摘要绑定，允许调整缩进和同一对象内字段顺序。输入文件在每次实际执行时读取并记录字节摘要，已完成项复用当时的证据。

状态、结果和尝试编号用 SQLite 事务提交。进程在事务完成后才能发出完成事件。一项任务已经落盘但完成事件尚未打印时，续跑也会跳过它。中断发生在提交之前时，重新运行整项任务，像素上限按该次尝试重新计算。目前保存的是任务级断点，任务执行中途的 OCR 观察不会作为下次尝试的缓存。写入者使用同一进度文件的本地锁，另一个写入请求会被拒绝，状态仍可读。

## 从解压包复跑验收

用一个新目录存储日志和进度库。验收脚本真实运行三份已有档案任务，在 Younger 已登记开始后向批量进程及其子进程发送 SIGKILL。之后检查首次完成项的结果字节和尝试数，检查锁、预算、失败隔离、移植与启动命令，并在补齐缺失文件后验证重试。

~~~sh
python3 -B acceptance.py --bundle ./visual-search-batch.zip ./本次验收
~~~

如手头是解压后的目录，可省略 `--bundle`，脚本会复制运行文件到新位置测试。项目目录中的 `验收记录` 保存发布包的真实归档结果。

## 移植文件

- `batch.sh`、`batch.py` 是启动与命令入口，`batch_engine.py` 校验清单单项并接入原查询，`batch_state.py` 持久化执行状态。
- `vendor/` 是运行依赖，包含已有版本的最小源码、依赖声明和英语 OCR 权重。具体复制路径与摘要见 `vendor-files.txt` 和 `vendor.sha256`。
- `examples/` 包含可执行清单、输入与来源。依赖安装完成后，可将整个解压目录连同相对路径清单复制到新位置，再使用新的本地进度文件。
- `acceptance.py` 是验收，`pack.py` 按显式文件清单重建 ZIP。SQLite 进度文件可在程序退出后与同一版本及清单一并迁移。续跑会核验 Python、Node、OCR、Python 依赖和源码指纹。
