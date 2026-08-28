# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-zhihu-answer |
| **所属层** | publish |
| **来源类型** | 自研（工具封装 + 实战沉淀） |
| **原始来源** | Easel 自研。知乎问答**回答**发布，走 `skills/shared/scripts/zhihu_answer.py`（Playwright 浏览器自动化 + ZhihuProfile 登录态持久化）。2026-08-06 由 skill-workshop 从两轮共 9 条真实知乎回答发布沉淀（原提案 `skill-zhihu-answer-20260806-a4fd2d217c`，因网关插件授权不可用改为手动落库）。 |
| **参考项目** | Playwright（https://playwright.dev/）— 浏览器自动化与登录态持久化；与 skill-zhihu-publisher / channels-upload / kuaishou-upload 共用同一 ZhihuProfile 与浏览器发布方法论 |
| **许可** | 随 Easel 项目许可 |

## 实战沉淀要点（2026-08-06）

调试中发现并修复的三个核心问题（选择器经多次真实页面验证）：
1. **header 遮挡「写回答」** → dispatch_event / React 事件序列 / focus+Enter 三策略绕过 pointer 拦截。
2. **编辑器延迟出现** → 每策略后轮询 `.public-DraftEditor-content` 判定成功。
3. **「发布回答」按钮滚出视口** → JS 遍历全部 button 精确匹配「发布回答」+ scrollIntoView，避开与「发布设置」歧义。

> 整理时间: 2026-08-06
> 用途: 来源溯源与致谢
