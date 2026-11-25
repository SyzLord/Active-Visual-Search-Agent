# 印章定位后的正文预算 · 2026-11-18

沿用冻结的马歇尔计划扫描与问题，保留单页、有两张干扰页、100 万与 160 万像素的对照，以及两窗和四窗上限。日期匹配沿用已修复的连字符与跨行实现。所有策略均重跑真实 OCR。正文和日期单字段任务沿用基线；预算调度变更只作用于同时含有日期与普通文字锚点的任务。

基线用墨迹密度挑候选边窗，尝试到窗口上限后，用余额在所有页面寻找未找到的正文。新策略限制边窗最多使用扣除预览后的 60% 像素，并在匹配所需日期后立刻转向正文。先扫描确有日期证据的页面内三条重叠横带。若其他页面尚未查找，保留剩余预算的 20% 给原有跨页调度。所有 OCR 均从原扫描重取，输出真实词框。

先试横带直读。若 OCR 命中疑似词但未能完整读出短语，再从横带池预留 16% 做最多两次原分辨率单行重读。使用原项目模糊匹配器从已有 OCR 候选中排序，支持将几何上同一行的断裂片段作为候选线索。线索只用来确定再次 OCR 的位置，最后要求重新识别并精确匹配正文短语。规则是在检查横带失败原因后增加，马歇尔页已参与开发。两项旧联合题用于检查是否有退化。各组检查回答、日期和正文定位几何要求，以及像素总账，预览图也计入。

## 实测

| 页面 | 预算 | 联合题 · 基线 | 日期后横带 | 日期后横带＋单行复核 |
| --- | ---: | ---: | ---: | ---: |
| 单页 | 100 万 | 0/2 | 0/2 | 0/2 |
| 单页 | 160 万 | 0/2 | 0/2 | 2/2 |
| 有两张干扰页 | 100 万 | 0/2 | 0/2 | 0/2 |
| 有两张干扰页 | 160 万 | 0/2 | 0/2 | 2/2 |

分母为每组的两窗、四窗策略，同一道联合题在八个条件下重复。日期均从真实左印章获得，页号正确，日期框 IoU 为 0.564。160 万像素时，横带提供了相似的正文词。重新 OCR 单行得到完整的 `FINDINGS AND DECLARATION OF POLICY`，正文框 IoU 为 0.841。100 万像素时未获取足够清晰的局部线索。新策略总通过数 16/36→20/36，日期和正文单字段的通过结果全部相同。联合题最终策略在 160 万像素预算下，单页支出 1,370,468 像素，含干扰页支出 1,123,260 像素。在同样 160 万上限内，原策略随窗口数变化支出 1,179,997–1,414,494 像素，但这些条件的联合题均失败。

[基线](baseline-marshall.json) · [仅横带](bands-only-marshall.json) · [横带与复核轨迹](reserved-marshall.json) · [冻结配对检查](marshall-comparison.txt)

### 跨页检查

只优先读印章页的版本，在旧扫描的 66 次复验中丢了一个 100 万预算联合题。该题日期在第 26 页，正文在第 13 页。补上跨页探查后，若找印章时也看过其他页的边窗，最多用此时余量的 29% 先小读这些页的正文，每页上限 235,000 像素，再查日期页。只依赖已读页列表和实际 OCR。新分支后加，旧跨页题用于开发复验。

最终跨页版重跑旧扫描 66 条，逐项通过判定与原策略一致。旧联合题两档都读回第 13 页 `A RESOLUTION` 及第 26 页日期，100 万档的实际像素由 593,329 降到 428,498，160 万档由 798,944 降到 430,286。新马歇尔页的日期由第一个边窗读到，跨页探查未触发。重跑 36 条得到相同的定位、通过值和实际像素。

[旧扫描复核](cross-probe-original-comparison.txt) · [最终旧扫描轨迹](cross-probe-original.json) · [最终马歇尔复核](cross-probe-marshall-comparison.txt) · [最终马歇尔轨迹](cross-probe-marshall.json)

## 复跑

在本目录使用先前实验的本机 Python 环境。所有输出写入一套新目录。

~~~sh
py=../../../../2026-11-13/multimodal-adaptive-reasoning/work/mlx/.venv/bin/python
out="$(mktemp -d)"
(cd ../印章独立页评测_2026-11-18 && shasum -a 256 -c frozen.sha256)
(cd ../印章定位放大评测_2026-11-17 && shasum -a 256 -c frozen.sha256)
(cd ../印章日期修复_2026-11-18 && shasum -a 256 -c frozen.sha256)
shasum -a 256 -c frozen.sha256
"$py" -B run.py baseline marshall "$out/baseline-marshall.json"
"$py" -B run.py bands marshall "$out/bands-only-marshall.json"
"$py" -B run.py reserved marshall "$out/reserved-marshall.json"
"$py" -B compare.py "$out/baseline-marshall.json" "$out/bands-only-marshall.json"
"$py" -B compare.py "$out/baseline-marshall.json" "$out/reserved-marshall.json"
"$py" -B run.py baseline original "$out/baseline-original.json"
"$py" -B run.py reserved original "$out/reserved-original.json"
"$py" -B compare.py "$out/baseline-original.json" "$out/reserved-original.json"
"$py" -B run.py cross-probe original "$out/cross-probe-original.json"
"$py" -B run.py cross-probe marshall "$out/cross-probe-marshall.json"
"$py" -B compare.py "$out/baseline-original.json" "$out/cross-probe-original.json"
"$py" -B compare.py "$out/baseline-marshall.json" "$out/cross-probe-marshall.json"
~~~
