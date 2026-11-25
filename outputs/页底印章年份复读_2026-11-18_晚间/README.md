# 一百万像素内，读到的年份属于哪一枚收件章？

随后完成的可选策略在水平搜索之后只使用剩余像素，附另一份独立原件和一次人工框事后诊断。[正文保留复读实验](reserve/README.md)

同一封信上可以同时出现签发日、收件日、归档日。这个版本接收一个日期、一段英文和一组页面，查找页底收件日期与同页正文，把每次 OCR 的原始词、坐标和开销留给使用者核对。本文记录今晚第一次冻结的实验。

## 两份盲测原件

北京时间 21:44:29 锁定搜索、评分、OCR 与开发集；21:55:24 锁定新原件、题目和人工框，随后实跑。两个原件来自不同文件。先前 219 个项目资料文件中未检出其来源标识和姓名，185 个历史扫描或 PDF 中无相同字节。每份跑单页及加另一封信两个条件。四个条件共享两份物理原件。[策略锁](policy.sha256) · [选样和坐标](holdout.json) · [人工框与背面核验图](blind-labels.png) · [查重范围](unseen-audit.json)

| 原件 | 输入 | 人工核验的收件日与正文 |
|---|---|---|
| Griffith | 第 32 页，1234 × 786，正面横向打字信 | 右下黑章为 AUG 26 1970，正文为签名上方的 “Thanking you, I remain”。右侧另有一枚斜章。 [档案原件](https://www.archives.gov/files/research/rfk/releases/2025/0418/166-12c-1_section_8-part_3_of_4.pdf#page=32) |
| Cowell | 第 42 页，1282 × 1655，黄色薄纸正面 | 正面能看见斜向的透印。翻到同件第 43 页，转正可读 JUN 20 1968。正文锚点取 “editorial from Computerworld”。搜索器只收到第 42 页。正文签发日恰与收件日相同。 [档案正反面](https://www.archives.gov/files/research/rfk/releases/2025/0612/591583_lbj_whcf_subject_files_on_judicial_and_legal_matters_b33_f6.pdf#page=42) |

每题 1,000,000 像素。两种策略共用离线英文 Tesseract.js 7.0.0、同一权重和评分器。年份候选必须来自页底相邻月日旁的真实四位 OCR 词。完整日期还需确认月、日，并把年份和日期都定位到同一枚人工标注的印章。词框与人工框的交并比至少 0.30，覆盖人工框至少 48%。正文要求精确短语与正确位置。联合题要求两个字段都过关。[冻结规则](design.md) · [评分代码](audit.py)

## 两种策略的结果

箭头从上轮水平搜索（horizontal-footer）指向本轮优先复读页底（receipt-year）。页底支出含专用预览及所有页底 OCR。总支出还含其他预览、正文与全局回退。单位均为每条件平均像素，实际逐项支出见表后链接。

| 数据 | 条件 | 年份 | 完整日期 | 正文 | 联合 | 页底支出 | 全题支出 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 开发 · Diggs | 2 | 0 → 2 | 0 → 2 | 0 → 0 | 0 → 0 | 243,566 → 352,220 | 915,096 → 947,996 |
| 开发 · Robinson | 2 | 2 → 2 | 2 → 2 | 2 → 2 | 2 → 2 | 231,576 → 259,590 | 706,054 → 259,590 |
| 开发 · Wells-Barnett | 2 | 1 → 1 | 0 → 1 | 0 → 0 | 0 → 0 | 243,166 → 457,016 | 999,580 → 614,590 |
| **开发合计，3 件** | **6** | **3 → 5** | **2 → 5** | **2 → 2** | **2 → 2** | **239,436 → 356,276** | **873,576 → 607,392** |
| 独立 · Griffith | 2 | 0 → 0 | 0 → 0 | 2 → 0 | 0 → 0 | 212,296 → 569,638 | 896,400 → 935,268 |
| 独立 · Cowell（透印） | 2 | 0 → 0 | 0 → 0 | 1 → 0 | 0 → 0 | 213,678 → 569,008 | 951,962 → 935,178 |
| **独立合计，2 件** | **4** | **0 → 0** | **0 → 0** | **3 → 0** | **0 → 0** | **212,987 → 569,323** | **924,181 → 935,223** |

独立集两种策略能读对年份或联合题的物理原件各为 0/2。强制优先读页底还丢失三个已能正确回答的正文条件。查询入口默认使用水平搜索，并对其输出追加印章来源核验。分件表还列出两种策略的最大支出。[独立逐题](heldout-rows.tsv) · [独立分件](heldout-summary.tsv) · [开发逐题](development-rows.tsv) · [开发分件](development-summary.tsv)

**Diggs 的可复查收益。** 单页旧读数 `10 MAY 29 19` 缺两位。新策略的第二次 OCR 在圆戳读到 `WAY 29 1963.`，四位年词回投原图约为 [1323, 2751, 1422, 2796]。第三次 OCR 在同一位置的左边读到 `MAY 29`，两个观察才组成完整日期。该题页底支出 359,404，全题 938,592。加干扰页后也读对日期，两个条件都漏掉了指定正文。[两次观察的原始词和框](development-results.json)

**两个真实失败。** Griffith 单页的页底 OCR 在旧策略读成 `UTM 61970`，新策略读成 `MAGS o g1970`；原扫描中签名压在月份旁，数字也相邻。Cowell 单页旧策略返回了页首的相同日期，日期框纵坐标 156–198，人工收件章在 1410–1509，于是严格日期与联合均判失败。使用查询入口的来源核验，该题返回 partial 并保留正确正文。已见 Wells 信另有同名机构出现在两处，命中页下方的重复文字也不能通过信头位置的评分。[原始轨迹](heldout-results.json) · [用户查询入口](evidence.py)

## 遮盖与错误查询

Diggs 负对照只遮两枚章的年份，保留页首的 1963。旧策略用 922,025 像素，新策略用 902,355；各自页底支出为 280,803、667,985，两者均未输出年份。反向对照在 Robinson 输入请求 1959，实际 OCR 报告 1958 并保留正确正文；入口返回 partial，费用 865,676。这个故意报错年份的工单是额外功能检查。[遮盖范围](negative.json) · [遮盖逐题](negative-rows.tsv) · [遮盖轨迹](negative-results.json) · [错误查询的真实 OCR](wrong-year-query.json)

## 核验与从头复跑

在本目录运行。当前机器使用 Python 3.12.14、Pillow 13.0.0、NumPy 2.3.5、pypdfium2 5.13.0、Node 24.22.3。离线模型和共用源码位于相邻项目目录，保留 outputs 的相对目录结构。在其他环境安装 [3.2 的 Python 依赖](../document-evidence-agent-v3.2/requirements.txt) 与 [Node 依赖](../document-evidence-agent-v3.2/package.json)，可通过 VISUAL_SEARCH_PYTHON、VISUAL_SEARCH_NODE 指定解释器。

~~~sh
py="${VISUAL_SEARCH_PYTHON:-$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
out="$(mktemp -d)"
shasum -a 256 -c policy.sha256
shasum -a 256 -c development.sha256
shasum -a 256 -c negative.sha256
shasum -a 256 -c holdout.sha256
"$py" -B test_evidence.py
"$py" -B verify_frozen.py --fresh-repeat heldout-fresh-repeat.json --rebuild-dir "$out/rebuilt"
"$py" -B prepare_inputs.py data "$out"
cmp data/griffith.png "$out/griffith.png"
cmp data/cowell.png "$out/cowell.png"

# 从保存的真实 OCR 重新做所有决策、评分和像素记账
for split in development negative holdout; do
    result="$split-results.json"
    if [ "$split" = holdout ]; then result=heldout-results.json; fi
    "$py" -B replay.py "$split.json" "$result"
    "$py" -B recompute.py "$split.json" "$result" --summary
done

# 从同一批原始图像重新执行 OCR，包括旧开发基线
"$py" -B benchmark.py development "$out/development.json" --fresh-baseline
"$py" -B benchmark.py negative "$out/negative.json"
"$py" -B benchmark.py holdout "$out/holdout.json"
for split in development negative holdout; do
    "$py" -B recompute.py "$split.json" "$out/$split.json" > "$out/$split.tsv"
    expected="$split-rows.tsv"
    if [ "$split" = holdout ]; then expected=heldout-rows.tsv; fi
    cmp "$expected" "$out/$split.tsv"
done
sh run.sh inspect holdout C1
sh run.sh query data/griffith.png --date 'AUG 26 1970' --text 'Thanking you I remain' --output "$out/query.json"
~~~

两份独立 PDF 原件与 SHA-256 均在 data 与 holdout.sha256，可直接离线重建。需要从馆方重新取得原件时，在上面的变量仍有效的同一终端运行以下命令。

~~~sh
mkdir "$out/download"
curl -fLsS 'https://www.archives.gov/files/research/rfk/releases/2025/0418/166-12c-1_section_8-part_3_of_4.pdf' -o "$out/download/griffith-original.pdf"
curl -fLsS 'https://www.archives.gov/files/research/rfk/releases/2025/0612/591583_lbj_whcf_subject_files_on_judicial_and_legal_matters_b33_f6.pdf' -o "$out/download/cowell-original.pdf"
cmp data/griffith-original.pdf "$out/download/griffith-original.pdf"
cmp data/cowell-original.pdf "$out/download/cowell-original.pdf"
"$py" -B prepare_inputs.py "$out/download" "$out/download"
~~~

独立集 8 条轨迹、59 次 OCR 的输入字节摘要、动作和证据全部通过记录回放。开发集 12 条轨迹的 70 次调用和遮盖集 2 条轨迹的 19 次调用也重现了动作与词框。这两组历史轨迹未逐调用保存编码字节摘要。记录回放使用已存的原始 OCR 词，命令中的 benchmark 路径才会调用真实识别器。[独立回放](holdout-replay.json) · [开发回放](development-replay.json) · [遮盖回放](negative-replay.json)

另从原始输入重新执行独立组的 59 次本地 OCR。8 条轨迹的识别词、词框、动作、像素、返回值和严格评分均与首次实跑相同，计时单列。两份官方 PDF 重建的 PNG 与测试文件逐字节一致；遮盖图在两个登记矩形之外的变更像素为 0。[从头复跑轨迹](heldout-fresh-repeat.json) · [实跑比对](heldout-fresh-verification.json) · [遮盖与复算核验](frozen-verification.json)
