# 保住正文之后，剩余像素能救回一枚章吗？

把上轮水平搜索跑完，再对已读到的页底线索小范围复读。这个可选策略在已读 Griffith 的单页上找回了收件日，保住了旧策略已经定位的正文。新留出的 Tweed 信上，单页日期维持通过，联合题仍为 0/2。默认查询继续使用水平搜索，可用 `--policy spare-stamp` 运行新规则。[可运行入口](../run.sh) · [策略实现](refine.py)

## 哪些结果能作为独立证据

上一轮的 Griffith、Cowell 在这次都属于回归。北京时间 22:14:42 锁定触发、上限、评分、共享 OCR 与历史轨迹，然后才选择 Tweed 致 Oberdorfer 的信。22:17:34 锁定新件的两个问题条件和人工框，随后开始 OCR。在既有输出的 247 个文本资料与 193 个扫描或 PDF 中，未找到该档号、姓名或相同原件字节。Tweed 与已见 Diggs 均来自美国司法部馆藏，扫描文件和信函不同。这次新增独立原件为 **1 件**。[策略登记](design.md) · [冻结清单](policy.sha256) · [新件登记](holdout.json) · [来源查重](unseen-audit.json)

Tweed 信是原 PDF 第 25 页，取整页原始黑白扫描，2550 × 3300。签发日是 9 月 3 日，右下 Tax Division 收件戳为 **SEP 5 1963**。正文锚点是信中询问报告的五个词。与 Griffith 合并的条件把干扰页放在第一位。搜索器只接触原始图像；图片中可见的黑色扫描横纹保留。[美国司法部第 25 页](https://www.justice.gov/d9/crt/legacy/2011/06/14/003-ccr-crd-part32.pdf#page=25) · [人工框放大图](blind-labels.png)

## 同预算实测

每题总上限 1,000,000 像素，含预览和每一次 OCR。下表的箭头从原水平策略指向保留正文的余量复读。日期要求完整印章日期及同章年词都通过原图定位，正文要求精确文本与登记位置；联合加验两个字段的返回。遗漏的字段单独计分。

| 数据与页集 | 条件 | 年份 | 日期 | 正文 | 联合 | 每条件实付像素 |
|---|---:|---:|---:|---:|---:|---:|
| Diggs、Robinson、Wells 开发回归 | 6 | 3 → 3 | 2 → 2 | 2 → 2 | 2 → 2 | 平均 873,576 → 896,785 |
| Griffith，单页 | 1 | 0 → 1 | 0 → 1 | 1 → 1 | 0 → 1 | 899,956 → 935,466 |
| Griffith，加干扰页 | 1 | 0 → 0 | 0 → 0 | 1 → 1 | 0 → 0 | 892,843 → 943,763 |
| Cowell，单页 | 1 | 0 → 0 | 0 → 0 | 1 → 1 | 0 → 0 | 999,819 → 999,819 |
| Cowell，加干扰页 | 1 | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 | 904,106 → 955,026 |
| Diggs 两枚章遮年 | 1 | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 | 922,025 → 970,069 |
| **独立 Tweed，单页** | **1** | **1 → 1** | **1 → 1** | **0 → 0** | **0 → 0** | **921,054 → 921,054** |
| **独立 Tweed，加干扰页** | **1** | **0 → 0** | **0 → 0** | **0 → 0** | **0 → 0** | **910,963 → 961,883** |

13 个条件中的正文证据逐项相同，包括本来就没有正文的条件。旧策略定位准确的 5 个正文结果全部保留。上一轮优先读页底在 Griffith、Cowell 上正文只得 0/4，本次为 3/4，与水平策略一致。这四个回归条件联合从 0/4 到 1/4。Diggs 的两个日期在上轮专门读页底时均能找回，本次保正文策略均未找回。这两种预算分配各有代价。[回归逐题、像素与触发原因](regression-rows.tsv) · [新件逐题](heldout-rows.tsv)

## 一笔能追溯的成功和一笔失效的支出

**Griffith 单页。** 原水平策略的粗读框覆盖人工日期框 100%，OCR 报 `UTM 61970`。余量策略由这个粘连词提出 [994, 735, 1221, 781]。整行复读花 27,010 像素，读为 `~ AUG 261970`；年段花 8,500 像素，输出独立年词 `1970`。把完整月日和四位年词对应回原页，年份位置约为 [1145.5, 745.8, 1207.9, 774.2]。原有正文和词框没有变。已用 899,956，加 35,510，共 935,466。通过实际用户查询入口从头运行得到相同的 9 次 OCR 输入、原词、年框与开销。[真实查询导出](griffith-cli.json)

**Griffith 事后定位诊断。** 评分完成后，单独用人工框做两次 OCR，维持原识别器、行模式、缩放比例与图像处理。日期框按相同留边裁剪后依然读为 `MUG 261970`，年框读为 `1970`。自动裁剪与粗读窗口均完整覆盖人工目标。这个个案的障碍可定位到整行字符识别和分词，粗取景已包含印记。两次人工框 OCR 用 33,363 像素，连同正式查询共 968,829；人工框未进入搜索、回归或独立成绩。加干扰页时自动年段仍读出 `1970`，月份分别误为 `KUG`、`WUG`，缺少月日依据，系统没有交付完整日期。[诊断原始词、框与成本](griffith-diagnostic.json)

**Tweed 新件。** 单页水平策略已得到原始行 `SEP 5 1963 *}} /`，年框约为 [1930, 2670, 2014, 2712]。追加策略立即停止，专用于页底的总支出为 249,025。加干扰页时 Tweed 粗读把关键行读成 `f_ seps 903 4)`，更强的数字线索反而来自 Griffith。三次额外 OCR 都落在干扰页，花 50,920 像素，页底支出从 210,653 增至 261,573。两种策略在这封新信的正文都为 0/2。[新件完整原始轨迹](heldout-results.json)

## 怎样读这段代码

1. 从 `footer_clues` 开始。输入是旧搜索已经付费的 OCR 和页面尺寸，输出是最多两个候选框。查询的月、日可以触发复读，形似年份的数字后缀也可以触发。后一条不接收查询年份。已经找到正文时，候选还须在同一页。[候选生成与搜索](refine.py)
2. 在 `refine` 中找 `free`。它等于 100 万减去原策略的全部预览和 OCR，余额不足 4,000 或收件章已核实时即停止。对候选的整行、年段、月日分别扣费；识别出独立年词还需与有依据的月日通过同页、邻近词框检查。只有两类字段都存在且同页才会交付联合答案。[收件章词框规则](../imprint.py)
3. 打开 `compare`。它校验已运行的每一步、预览和正文字段与基线完全一致；再独立评分并核对实际 OCR 输入宽高、字节摘要和总像素。回归复用已存的基线原始 OCR，20 次新增复读由真实引擎执行。独立组从头实跑共 14 次原策略 OCR 加 3 次新增复读。共享的基线动作在两种策略的像素账中均按全额计入。[评测和回放代码](experiment.py)

**练习。** 在 Griffith 双页轨迹中，单独年段读对了 1970，为什么逐题表的严格年份和日期仍为 0？在 Tweed 单页中，为什么没有出现追加动作？

**参考答案。** 年份必须绑定到查询月日旁的印记；双页 Griffith 的月日裁剪误读到的字母和目标月份差异过大。年段 OCR 原词仍完整保存在轨迹中。Tweed 单页则已有来自同一个底部印章的完整日期及年词，程序命中 `already_verified`，追加像素为 0。

## 复现

在本目录运行。共用环境、模型与旧版输入的安装说明见[上一轮手册](../README.md)。数据来源、页码、PNG 和两个 SHA-256 都在 holdout.json。默认的回归运行复用已核对的旧基线，新增复读会真实执行；加 `--fresh-baseline` 可连基线一起从图片重新读取。

~~~sh
py="${VISUAL_SEARCH_PYTHON:-$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
out="$(mktemp -d)"
shasum -a 256 -c policy.sha256
shasum -a 256 -c holdout.sha256
"$py" -B prepare.py data/tweed-original.pdf "$out/tweed.png"
cmp data/tweed.png "$out/tweed.png"
"$py" -B experiment.py verify regression-results.json
"$py" -B experiment.py verify heldout-results.json

# 从原图实际执行，逐行比对包含定位得分与像素的结果
"$py" -B experiment.py run regression "$out/regression.json" --fresh-baseline
"$py" -B experiment.py run holdout "$out/holdout.json"
"$py" -B experiment.py rows "$out/regression.json" > "$out/regression.tsv"
"$py" -B experiment.py rows "$out/holdout.json" > "$out/holdout.tsv"
cmp "$out/regression.tsv" regression-rows.tsv
cmp "$out/holdout.tsv" heldout-rows.tsv
"$py" -B diagnose_griffith.py "$out/griffith-diagnostic.json"
sh ../run.sh query ../data/griffith.png --date 'AUG 26 1970' \
    --text 'Thanking you I remain' --policy spare-stamp --output "$out/griffith.json"

# 可选，从馆方重新下载并比对原件
curl -fLsS 'https://www.justice.gov/d9/crt/legacy/2011/06/14/003-ccr-crd-part32.pdf' -o "$out/tweed-original.pdf"
cmp data/tweed-original.pdf "$out/tweed-original.pdf"
~~~

回归 11 个条件重建了 104 次基线及追加动作，核验 53 个已记录的输入字节摘要；其余 51 次来自较早未逐次保存摘要的基线。新件 2 个条件重建 17 次动作，17 个输入摘要全部一致。两组的判断、几何位置、像素和评分均复算一致。[回归回放核验](regression-verification.json) · [新件回放核验](heldout-verification.json)
