# 跨页文档取证 Agent 3.2

3.2 新增可选的正文优先读取策略，并补齐独立的纯图像对照。160 万像素下，三份未参与开发的论文栅格化页面上严格通过 16/29，3.1 为 6/29。260 万像素下为 20/29 与 21/29。复现、失败分析与学习工单见 [3.2 纯图像评测](docs/3.2纯图像评测.md)。

这一版加入重复字段核验与冲突处理。输入英文 PDF 或图像、锚点和总像素预算，输出有原文坐标的提取、比较或差值结果。当同名字段读到多个不同数值时返回 conflict，保留各处证据，答案为空。用户可以按页面 ID 限定字段，再运行任务。

当前实现适合个人文档智能工程项目。公开资料仍是参与过调试的回归集，独立来源泛化、跨行表格、单位换算和多用户吞吐需要后续实验。

## 运行

当前电脑可直接执行。其他环境需要 Python 3.11+、Node.js 18+，安装 requirements.txt 和 package.json 中依赖。OCR 权重随包提供。

~~~sh
python3 -m pip install -r requirements.txt
npm install
sh run.sh serve
~~~

浏览器打开 http://127.0.0.1:8769/ 。选择样例或自己的文档，默认策略为「候选核验与冲突判定」。点击证据可切换原文和读取图像，结果可以导出 JSON。单次最多 24 页，单文件 16 MiB，总文件 32 MiB。英文数字目前要求与锚点同行。

~~~sh
sh run.sh query --example hubble-distance
sh run.sh query --example operations-difference
sh run.sh test
~~~

## 跟着做一次冲突消解

~~~sh
sh run.sh query --files data/conflicts/register-01.pdf --task data/conflict-task.json --output local/conflict.json
sh run.sh query --files data/conflicts/register-01.pdf --task data/scoped-task.json --output local/scoped.json
~~~

第一条任务请求同名字段，系统发现两页数值不同，返回 conflict。第二条任务把字段限定到 d01-p02，得到第二页的值。两次运行的候选数量、实际像素与证据都在 JSON 中。工作台「自己的文档」中也可以填写字段页面 ID。

支持 locate、verify、extract、compare、difference 五种操作。每个字段含 anchor，可选 direction、window、ordinal、pages。pages 是精确页面 ID 列表，限制字段来源。单份上传 PDF 的第 2 页 ID 是 d01-p02，多文件按 d01、d02 递增。unit 是用户提供的单位标签。

## 评测与复现

- 12 份双页 PDF 包含 8 份不同值和 4 份相同值。默认核验策略 12/12 符合任务约定，旧的首次命中策略 4/12。显式限定到第二页后两种策略都通过 12/12。这批合成样例专门检验冲突处理。
- 260 万像素预算下，5 份公开资料 34 道正例，新策略严格通过 26/34，旧策略 28/34，整页均分 15/34。该回归显示候选核验仍有漏答。完整逐题结果在 results/audited-public.json。
- 22 项测试通过，覆盖真实 OCR、图片型 PDF、页面约束、冲突、预算、证据和进程超时。

~~~sh
python3 tools/check_conflicts.py --output local/conflicts.json
sh run.sh benchmark --split external --input pdf --strategy audited hybrid uniform --budget 2600000 --output local/public.json
~~~

默认核验会读取已索引的候选，预算不足、候选读不清或达到候选截断上限时保留需要复核的状态。纯图像回退只检查实际读到的区域，尚不能证明整份扫描件内字段唯一。

代码入口是 search_agent/audit.py、scheduler.py、task.py、reader.py。设计和学习工单见 docs/3.1设计与实验.md。docs/评测与失败分析.md 和其他旧结果记录的是 3.0 基线。数据来源见 data/README.md。
