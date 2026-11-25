# 印章日期匹配复验 · 2026-11-18

在上一轮冻结的马歇尔计划扫描、任务和像素预算上更新日期匹配器。允许月份加日与四位年份之间出现 OCR 连字符。若结果分成相邻两条 OCR 行，先要求整行分别是月日片段和纯四位年份，再检查两个框沿字行轴相邻、横向重合足够、间距和字高相称。最终检查日历日期，输出实际参与匹配的词框并集。跨行只在同一次识别、同一个窗口内进行。旧轨迹和冻结代码继续保留，复跑入口给原窗口调度器注入新匹配器。

| 条件 | 每题预算 | 正文优先 | 两窗口 | 四窗口 |
| --- | ---: | ---: | ---: | ---: |
| 单页 | 100 万 | 1/3→1/3 | 1/3→2/3 | 1/3→2/3 |
| 单页 | 160 万 | 1/3→1/3 | 1/3→2/3 | 1/3→2/3 |
| 加两张干扰页 | 100 万 | 0/3→0/3 | 0/3→1/3 | 0/3→1/3 |
| 加两张干扰页 | 160 万 | 1/3→1/3 | 1/3→2/3 | 0/3→1/3 |

36 条主试验轨迹中，窗口组的日期定位 **0/8→8/8**。命中均来自左印章的 `apR3- 1948`，原页框 IoU 0.564。联合题也找到了日期，但仍未定位另一个正文锚点，因此联合题仍未通过。正文题判定逐项一致。窗口组找到日期后减少后续 OCR，所有轨迹均校验预算账本。8 个条件共享同一印章页。

另跑 36 条仅打开连字符修复的轨迹，命中结果与主试验逐项一致。为单独验证跨行，将上一轮原策略已选的右窗口用原尺寸和旋转角重新识别一次。两行分别读出 `APR3` 和 `1948`，旧规则与仅连字符规则都无匹配，跨行规则取得日期框，IoU **0.870**。主试验先从左窗找到答案，提前停止，所以右窗结果是单独的组件验证。负例包含同一窗口内相距过远、错列、跨非相邻行和带其他词的年份行。

旧扫描 66 条 OCR 轨迹也重新执行，三个策略、两个预算的逐题判定与冻结归档一致。窗口版在 100 万和 160 万下分别通过 3/11、5/11。新增四项日期测试及原有三项均通过。 [旧扫描复验](original-comparison.txt)

[主试验轨迹](marshall.json) · [逐组对照](comparison.txt) · [仅连字符轨迹](hyphen-only.json) · [右窗实测](right-probe.json)

## 复跑

在此目录执行。OCR 使用上轮环境。每个实跑写入独立临时文件。

~~~sh
py=../../../../2026-11-13/multimodal-adaptive-reasoning/work/mlx/.venv/bin/python
before=../印章独立页评测_2026-11-18
prior=../印章定位放大评测_2026-11-17
out="$(mktemp -d)"
(cd "$before" && shasum -a 256 -c frozen.sha256)
(cd "$prior" && shasum -a 256 -c frozen.sha256)
shasum -a 256 -c frozen.sha256
"$py" -B test_dates.py
"$py" -B "$prior/check_dates.py"
"$py" -B run.py marshall "$out/marshall.json"
"$py" -B run.py marshall "$out/hyphen-only.json" --hyphen-only
"$py" -B probe_right.py "$out/right-probe.json"
"$py" -B compare.py "$before/results.json" "$out/marshall.json"
"$py" -B compare.py "$out/hyphen-only.json" "$out/marshall.json"
"$py" -B run.py original "$out/original.json"
"$py" -B compare.py "$prior/results.json" "$out/original.json"
~~~
