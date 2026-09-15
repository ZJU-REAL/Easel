# 参考资料搜索与采集

用 Claude 内置 `WebSearch` / `WebFetch` 从多个角度搜集参考资料，提取正文并生成结构化摘要，结果保存到 `reference/` 子目录供写作消费。

## 搜索流程

1. **分析主题**：从用户输入提炼搜索关键词
2. **多角度搜索**：中英文 + 不同关键词组合，至少 3 轮，覆盖事实、观点、数据
3. **内容提取**：对有价值的 URL 用 `WebFetch` 抓取正文
4. **交叉验证**：核心数据在 ≥2 个来源中交叉确认
5. **生成摘要**：综合生成结构化分析
6. **保存结果**：写入 `reference/` 目录

## 搜索策略

- **多语言**：英文搜一手信息源（官方博客、TechCrunch、arXiv 等），中文搜国内视角
- **多角度**：同一主题从技术细节、行业影响、用户反馈、竞品对比分别搜
- **时效性**：搜索时加入年份或日期限定词
- **关键数据**：基准分数、定价、发布时间等务必在 2 个以上来源确认
- **避免幻觉**：所有结论都要有 `WebFetch` 抓到的原文做支撑，不允许凭记忆编造来源

## 可用工具（按推荐顺序）

1. **WebSearch** — Claude 内置搜索，获取结果列表
2. **WebFetch** — 抓取具体页面正文
3. **搜索引擎 HTML 端点回退**（WebSearch 不可用时）：
   - DuckDuckGo：`https://html.duckduckgo.com/html/?q=<URL 编码>`
   - Bing：`https://www.bing.com/search?q=<URL 编码>`
4. **Bash + curl** — 特定 RSS / JSON API

## 输出到 reference/ 目录

```
reference/
├── search_results.json   # 搜索关键词 + 原始结果（URL + 标题 + 摘要）
├── summary.md            # 参考资料综合摘要
├── thinking.md           # （可选）意图识别、大纲构思、写作决策
└── articles/             # 提取的参考文章原文
    ├── ref_001_{来源标题}.md
    └── ...
```

**挂载位置**：

- 为某篇文章搜参考 → 保存到该文章目录下的 `reference/`
- 独立搜索任务 → 保存到 `output/参考资料/{YYYY-MM-DD}/{短主题}_{YYYYMMDDHHmm}/reference/`

## search_results.json 建议结构

```json
{
  "topic": "AI 对就业的影响",
  "queries": [
    "AI impact on jobs 2026",
    "AI 失业数据 2026",
    "Anthropic economic index"
  ],
  "results": [
    {
      "query": "Anthropic economic index",
      "title": "...",
      "url": "https://...",
      "source": "anthropic.com",
      "abstract": "...",
      "fetched": true,
      "local_file": "articles/ref_001_....md"
    }
  ]
}
```

## summary.md 建议结构

```markdown
# 参考资料综合摘要：{主题}

## 一、核心事实与数据
- 事实 1（来源：ref_001、ref_003）
- 事实 2（来源：ref_002）

## 二、主要观点与分歧
- 正方：...（来源：...）
- 反方：...（来源：...）

## 三、可引用的金句 / 数字
- "..." —— 来源

## 四、潜在写作角度
- 角度 A
- 角度 B
```
