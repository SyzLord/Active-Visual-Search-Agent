# 数据与依赖来源

`external/manifest.json` 保存公开原件的来源 URL、SHA-256、实际 PDF 页码、标注、渲染图摘要和每道题的证据坐标。原件共 5 份，纳入 20 张唯一页面和 39 道任务。混合来源组复用其中 6 页。全部来自本项目 2.0 已取得的公开资料，本轮下载新增模型和数据均为零。

| 原件 | 用途 |
| --- | --- |
| [NASA · Hubble Space Telescope – An Overview](https://assets.science.nasa.gov/content/dam/science/missions/hubble/multimedia/fact-sheets/hubble-fact-sheet-overview.pdf) | 两页技术说明、数值、跨页证据 |
| [U.S. Department of Energy · Energy Saver](https://www.energy.gov/sites/default/files/2022-08/energy-saver-guide-2022.pdf) | 双栏说明、目录、表格与照明标签 |
| [U.S. Geological Survey · Topographic Map Symbols](https://pubs.usgs.gov/gip/TopographicMapSymbols/topomapsymbols.pdf) | 图例、地图术语及数值 |
| [U.S. Census Bureau · 2020 Census sample questionnaire](https://www2.census.gov/programs-surveys/decennial/2020/technical-documentation/questionnaires-and-instructions/questionnaires/2020-informational-questionnaire-english_DI-Q1.pdf) | 高度相似的问卷页与说明 |
| [NOAA NWS · Sky Watcher Chart](https://www.weather.gov/media/bmx/skywarn/cloudchart.pdf) | 反白标题和跨来源任务 |

源文件用于复现，保留原始署名和出处。截图及评测只使用公开空白问卷或说明资料。项目中的印刷数值只作为提取测试样本。

合成集由 `search_agent/corpus.py` 生成。训练 16 组共 80 页，开发 6 组共 36 页，测试 10 组共 60 页。各组的页面、种子和目标位置固定。合成留出集替换站点前缀，加入训练时未见的框线模板。`examples/` 的巡检示例用独立种子生成。

需要核对或重建公开标注时，可另装 `pdfplumber==0.11.9`，用包含原件的本机目录运行以下命令。`pdfplumber` 仅在构建标注时使用。

~~~sh
python3 tools/build_fixtures.py --source-dir /path/to/source-pdfs
~~~

英文 OCR 数据的来源和许可见 [SOURCE.json](ocr/SOURCE.json) 与 [LICENSE.txt](ocr/LICENSE.txt)。合成文档使用 Liberation Sans，随附 [字体许可](fonts/LICENSE_LIBERATION)。
