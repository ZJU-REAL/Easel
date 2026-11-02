# 执行与数据契约

用户只需提供 arXiv 链接/编号、可下载 PDF 地址或本地 PDF。Agent 执行脚本并完成阅读、写作、选图和审核；这不是一个脱离模型就能自动写作的命令行服务。

## 命令

`SKILL` 为 Skill 安装目录，`PY` 为装有 requirements.txt 依赖的 Python。`OUT` 为 `outputs/<论文简称>`，`WORK` 为`outputs/<论文简称>/assets/paper-promotion` 子目录；也兼容位于 outputs 内的独立工作目录，但禁止把 OUT 放进 WORK、两者相同或把 WORK 放在 OUT 的其他位置。每篇论文使用新 WORK；同一篇改稿复用工作资料。

```bash
"$PY" "$SKILL/scripts/promotion.py" prepare 'https://arxiv.org/abs/2610.12402' --work "$WORK"
# 同一命令也接受 https://某站/论文.pdf、本地路径、arXiv: abs/pdf 链接或裸编号
"$PY" "$SKILL/scripts/promotion.py" check-text "$OUT/post.md"
"$PY" "$SKILL/scripts/promotion.py" render --work "$WORK" --out "$OUT"
"$PY" "$SKILL/scripts/promotion.py" hashes --work "$WORK" --out "$OUT"
"$PY" "$SKILL/scripts/promotion.py" validate --work "$WORK" --out "$OUT"
```

先 prepare，再由 Agent 写 evidence、post、manifest，之后 render、视觉检查、hashes、填写 review、validate。scripts 不会从空 manifest 猜测图框或生成文章。实际执行时用真实路径替换变量，示例 arXiv 不是要求处理的论文。

下载支持 HTTP(S)、重定向及 arXiv 新旧编号/版本号，校验 PDF 内容并记录来源和 SHA-256；遇到登录页、访问失败或扫描版，不伪装成功。可使用可用浏览工具获取论文并以本地 PDF 继续，不绕过访问控制。自动下载上限 200 MiB。prepare 输出 source.json、paper.pdf、text.txt、pages.json 和 pages/ 预览。扫描版的 caption/事实通过 OCR 辅助提取、视觉核对，原始截图不改变。

## 证据文件

`evidence.json` 是非空数组。为所有定量结果、核心方法、主要结论建立记录；资源、接收状态的证据也记录。正文定稿后 post_quote 必须仍是原文子串。

```json
[
  {
    "post_quote": "正文中实际出现的完整主张",
    "page": 4,
    "source_excerpt": "论文原文摘录，包含必要条件",
    "conditions": "模型、数据集、评测设置、比较对象与指标单位",
    "source_url": "仅工作资料可保存真实链接"
  }
]
```

这是 schema 示意，字段值必须用当前论文证据替换，不可直接交付。

## 截图计划

`manifest.json`：

```json
{
  "pdf_sha256": "source.json 中的 pdf_sha256",
  "images": [
    {"file": "01-first-page.png", "page": 1, "kind": "first-page", "bbox": null},
    {
      "file": "02-method.png",
      "page": 3,
      "kind": "method",
      "bbox": [40, 70, 555, 330],
      "caption_bbox": [40, 290, 555, 330],
      "source_label": "Figure 2",
      "caption": "PDF 中对应原始 caption 的准确文本",
      "text_quote": "正文中唯一出现的原句或连续片段",
      "reason": "具体解释截图怎样支持正文，以及包含哪些子图",
      "dpi": 180
    }
  ]
}
```

页码从1开始；坐标单位是 PDF point，使用 PyMuPDF `page.rect` 对应的显示页面坐标，原点在左上方。`pages.json` 的文本块坐标在旋转页上是未旋转坐标，需乘 `page.rotation_matrix` 转换；预览坐标则按其与 page.rect 尺寸比例转换。不要把图片像素直接当 PDF point。

bbox 是包含图表与原 caption 的**单一矩形**；caption_bbox 是其中 caption 的完整区域。默认180 dpi，后续图允许144–300 dpi。首页必须使用整页可见页面（PDF 的原始 CropBox），不改页边距、旋转、内容或添加标题。校验会从同一 PDF 重新渲染并逐像素比对。

组合图仅讨论部分时，保留对应子图及必要标签/图例和与之对应的原 caption。若单个矩形必然带入未讨论子图或大段邻栏，换图或略去；不能把不相邻区域拼到一起。原始 caption 中用于定义的上下文可以保留，但不能借 caption 携带额外无关分析。caption 跨页而不能原样完整裁剪时选择其他图，或明确说明该图未纳入；不要交付半截 caption。

多图对应同一段时允许同位置，依该段叙述顺序；跨段时按首次引用位置递增。图片数量取决于正文，无固定下限（除首页）或凑数目标。正文确实讨论且图表可安全提取时，应提取相应主图/表，不能为省事只输出首页。

## 语义与视觉审核

Agent 必须打开每张实际截图，并对照 PDF 原页与证据审核；程序检查 caption 的记录/区域，不能判断 caption 内容正确、图表完整、语义支持或事实真实性。核对标题不过度承诺、百分比与百分点、数据集/模型条件、结论范围、资源来源、所有非首页图的相关性。全图中的子图、图例、脚注、数值和 caption 均应清楚可读。

`hashes` 命令输出当前 PDF、正文、manifest、evidence 的摘要。审查后将其放入 review.json 的 hashes；其余结构如下。notes 记录当前论文的具体核对依据，不可机械填写“已检查”。

```json
{
  "hashes": {"pdf": "摘要", "post": "摘要", "manifest": "摘要", "evidence": "摘要"},
  "facts": {"passed": true, "notes": "逐项核对的页码、结果与实验条件"},
  "grounding": {"passed": true, "notes": "各图和正文对应关系、未选图的原因"},
  "visual": {"passed": true, "notes": "逐图检查标签、caption、边界与可读性结果"},
  "style": {"passed": true, "notes": "选读案例与本篇借鉴之处，避免生硬套用"}
}
```

validate 验证限长、禁链接、图像顺序、有效坐标、caption 区域、图像像素忠实度、陈旧审核和多余交付文件。它不把人/模型的语义审核记录当成数学证明。任何改稿须重新核对证据、映射和语义审核；任何截图改动须重新打开检查。OUT 只允许 `post.md`、`images/`、工作资料 `assets/` 和 Easel 的 `.easel.json`；仅前两项是宣传成品。

计数口径：移除标题行开头的 `# ` 和标题后的一个空白分隔行，正文其余字符全部计入（包括文件末尾换行）。Unicode 码点与 UTF-16 单元都不超限，后者对 emoji 更保守；不宣称等同小红书未公开的实时计数算法。无需压到上限。
