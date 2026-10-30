# 内置论文资产模块

`vendor/paper2assets/scripts/` 包含完整的paper2assets脚本与utils，`UPSTREAM.json` 保存来源快照和文件哈希。在 Easel 中通过 `scripts/easel_video.py assets` 调用；它已适配本skill和独立视频工程的目录结构。

## 准备环境

```bash
python <skill>/scripts/easel_video.py assets check
```

基础依赖：Python≥3.10、PyMuPDF、Pillow、NumPy、Poppler的 `pdftotext` / `pdftoppm`。arXiv源码包建议使用Python≥3.12；二维码需要qrcode；SVG Logo可用CairoSVG或Python Playwright；EPS/PS转换可用Ghostscript。check列出当前环境能力，按实际提取路径补齐依赖。

先核对PDF版本与哈希，复用匹配的资产包。`<bundle>` 位于 `outputs/<论文简称>/assets/` 内。新提取结果写入新目录；已有人工修订的项目在临时目录提取后择项合并。

## 提取完整图表

按素材情况选择路径：

| 素材情况 | 操作 |
|---|---|
| 用户提供完整原图或图表文件 | 用source导入，保持原始内容和比例 |
| arXiv源码包含完整单文件图 | 用source获取，再与PDF核对图号、标签和内容 |
| 多子图组合、TeX叠加标签或表格 | 从PDF导出完整Figure/Table区域 |
| 只有PDF | 先自动提取，再补齐检测遗漏的图表 |

```bash
python <skill>/scripts/easel_video.py assets source --images <full-figure.png> <full-table.pdf> --outdir <bundle>
# arXiv源码路径：
python <skill>/scripts/easel_video.py assets source --arxiv <id-with-version> --outdir <bundle>
# 原图已导入后，补充文本、caption及候选元数据：
python <skill>/scripts/easel_video.py assets extract <paper.pdf> --outdir <bundle> --no-figures
# 直接从PDF提取文本与图像：
python <skill>/scripts/easel_video.py assets extract <paper.pdf> --outdir <bundle>
```

将提取清单与PDF逐图对照。source成功表示至少产出一张图；多includegraphics的figure在此解析器中只取得第一张，因此组合图使用PDF完整区域导出。自动检测遗漏的图表可用PyMuPDF page clip高分辨率补齐，并记录页面、边界和尺寸。

源图的page=0按未知页码处理，核对后写入明确的PDF页序；按实际JSON读取caption字典或列表。

## 清理与记录

保留原始文件。用 `crop inspect <image>`、`crop top-check <image>` 查看边缘；需要清除页眉、邻栏正文等图外内容时，在副本上裁出完整图表，保留子图、图例、箭头和内部标签。视频白边统一由CSS添加。

核实标题、作者、机构、发表状态和实验数值。venue采用实际会议、期刊或workshop名称，待确认项留空。事实表和叙事安排见[制作流程](production.md)。

## 生成共享素材包

在 `<bundle>/assets/meta/paper_spec.md` 中组织事实与候选讲稿。YAML前言可含title、authors、institutes、venue、paper_url、code_url、title_audio_script；正文按Problem、Motivation、Contribution、Method、Dataset / Benchmark、Key Result、Ablation Study、Headline Numbers、Takeaway组织，每节使用 `**Necessary:**`、`**Additional:**` 和 `**Audio script:**`。按论文实际内容填写，再为视频选取和合并段落。

```bash
python <skill>/scripts/easel_video.py assets package <paper.pdf> --outdir <bundle> --skip-extract --paper-spec <bundle>/assets/meta/paper_spec.md
```

`--skip-extract`复用已整理的原图。生成 `manifest.json` 和 `assets/meta/{sections,narration}.json`；将narration作为配音稿输入，再依据用户选择的声音生成音轨及实际对齐时间。

## 片尾入口和Logo

片尾需要论文/代码入口时生成二维码；版式需要机构或会议标识时按已核实身份获取Logo。

```bash
python <skill>/scripts/easel_video.py assets qr --outdir <bundle> --from-metadata <bundle>/assets/meta/metadata.json
python <skill>/scripts/easel_video.py assets logos --outdir <bundle> --names '<institute names separated by semicolons>'
python <skill>/scripts/easel_video.py assets venue-logo --outdir <bundle> --venue '<verified venue>'
```

Logo缺失时采用文字名称。素材齐备后，使用 `assets/meta/{text.txt,captions.json,figures.json,metadata.json}`、完整图片与来源记录继续制作视频。打包时将机器绝对路径转换为包内相对路径，并保留源PDF哈希。
