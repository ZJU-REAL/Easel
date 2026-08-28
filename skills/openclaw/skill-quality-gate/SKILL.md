---
name: skill-quality-gate
description: >
  发布前质量关卡：合规风险检测（敏感词、绝对化用语、平台规则）
  + 产物质量审核（完整性、可读性、平台适配度）。一次检查，两道把关。
  当用户说"检查合规"、"质量检查"、"能不能发"、"有没有敏感词"、
  "审核一下"、"发布前检查"、"质量够不够"时使用。
  合并了原 skill-check-compliance 和 skill-review-deliverable 的能力。
layer: publish
---

# 发布前质量关卡

> 一个 SKILL 完成两道把关：合规风险检测 + 产物质量审核。

## 输入

用户提供待检查内容：文本、图片路径、视频路径、或混合。
可选：目标发布平台。

## 输出

```json
{
  "overall_verdict": "✅ 可发布 | ⚠️ 需修改 | ❌ 不达标",
  "platform": "平台名或 generic",
  "compliance": {
    "risk_level": "low|medium|high",
    "issues": [{ "type": "", "severity": "", "text": "", "reason": "", "suggestion": "" }],
    "passed_checks": []
  },
  "quality": {
    "score": "✅|⚠️|❌",
    "dimensions": [{ "name": "", "score": "", "note": "" }]
  },
  "top_fixes": ["修改建议1", "修改建议2", "修改建议3"]
}
```

## 执行步骤

### 第一关：合规检测

1. 读取内容（文本和/或图片）
2. 加载通用合规规则 → `references/general-rules.md`
3. 根据 Profile 或用户指定的平台加载对应规则：
   - 小红书 → `references/platform-xiaohongshu.md`
   - 抖音 → `references/platform-douyin.md`
   - B站 → `references/platform-bilibili.md`
   - 无平台 → 仅通用规则
4. 逐项检测：绝对化用语、医疗违规、违禁内容、平台特有限制
5. 汇总合规结果

### 第二关：质量审核

1. 识别产物类型（文本/图片/视频）
2. 按维度逐项检查 → `references/review-dimensions.md`
3. 给出三级结论 → `references/review-levels.md`
   - ✅ 通过：可直接发布
   - ⚠️ 有瑕疵：建议微调后发布
   - ❌ 不达标：需返工
4. 如结论为 ❌，按 `references/rework-rules.md` 给出返工指引

### 综合判定

- 合规高风险 → 整体 ❌ 不达标
- 质量审核为 ❌（返工级）→ 整体 ❌ 不达标
- 合规低风险 + 质量 ✅ → 整体 ✅ 可发布
- 其他组合 → 整体 ⚠️ 需修改
- 输出 Top 3 优先修改建议

## Profile 感知

- **有 Profile**：读取 platform 加载平台规则、检查风格适配
- **无 Profile**：仅通用合规检查 + 通用质量标准
