---
name: skill-comment-insights
description: >-
  评论区量化分析：对一批评论做情感分析（正/中/负占比 + 代表评论）、高频词与短语提取、
  以及需求/吐槽/提问的诉求挖掘，为内容复盘和选题反哺提供数据。当用户说"评论情感分析"
  "评论区分析""用户在说什么""评论正负面比例""评论高频词""评论关键词""口碑分析""评论词云"
  "用户诉求""评论区吐槽"时使用。基于 jieba（分词）+ SnowNLP（情感）+ 社媒情感词典。
layer: attribute
---

# 评论区量化分析（comment-insights）

> 对评论做量化洞察：情感分布、高频词/短语、需求与吐槽挖掘。走
> `scripts/comment_insights.py`（jieba + SnowNLP + 社媒情感词典）。

> 和 skill-community-ops 的分工：community-ops 是"怎么回评论 + 危机应对"（运营动作）；
> 本 SKILL 是"评论区在说什么"（量化数据）。评论抓取见 skill-xhs-analyzer。

## ⚠️ 依赖

`pip install jieba snownlp`（首次 jieba 会构建词典缓存）。

## 输入

评论数据，三种格式：
- `.txt`：每行一条评论
- `.json`：字符串数组，或对象数组（`--column` 指定字段，默认 content）
- `.csv`：`--column` 指定评论列（默认首列/content）

## 输出（`outputs/主题名/`）

- 报告 JSON：情感分布/占比 + 正负代表评论 + 高频词 + 高频短语 + 需求/吐槽/提问计数与例子
- 终端可读摘要

## 执行

脚本路径（相对项目根）：`skills/openclaw/skill-comment-insights/scripts/comment_insights.py`。

```bash
python <skill>/scripts/comment_insights.py analyze -i comments.txt --top 20 \
  -o outputs/主题名/report.json
# CSV 指定列
python <skill>/scripts/comment_insights.py analyze -i comments.csv --column 评论内容
```

## 结果怎么用

1. **情感占比**：负面偏高 → 结合负面代表评论定位问题；配合 skill-community-ops 做回应/危机。
2. **高频词/短语**：用户关注点与话题；可喂 chart-visualization/infographic 出词云图。
3. **需求（demands）**：求链接/求教程/求同款 → 直接转化为下一条选题（配合 community-ops 选题反哺）。
4. **吐槽（complaints）**：产品/服务问题信号 → 复盘改进（配合 skill-content-postmortem）。

## 规则

1. 情感为 SnowNLP 基线 + 社媒词典修正的**近似值**，用于看趋势与占比，非逐条精判；
   关键决策需人工核对代表评论，或让 LLM 对存疑评论精读。
2. 高频词已做词性过滤（保留名/动/形）+ 停用词剔除，聚焦有信息量的词。
3. 数据量小（<20 条）时占比参考意义有限，如实说明样本量。
4. 只做分析不做回复；回复/危机用 skill-community-ops。

## 参考来源

沿用社媒评论分析常用组合：jieba 中文分词（#131 高频词）+ SnowNLP 情感（#130），并叠加
社媒情感词典（绝绝子/yyds/避雷/翻车等网络用语）修正 SnowNLP 在社交文本上的偏差。诉求挖掘
用规则匹配（求购/疑问/吐槽），确定可复现。
