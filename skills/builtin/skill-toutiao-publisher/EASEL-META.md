# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-toutiao-publisher |
| **所属层** | publish |
| **来源类型** | 自研（工具封装） |
| **原始来源** | Easel 自研。今日头条（头条号）图文发布，走 `scripts/toutiao_publish.py`（Playwright 浏览器自动化 + ToutiaoProfile 登录态持久化）。 |
| **参考项目** | Playwright（https://playwright.dev/）— 浏览器自动化与登录态持久化；发布脚本结构对齐 `skills/shared/scripts/zhihu_answer.py`（同为"已登录 profile + dry-run 默认 + 出站闸门"的发布方法论） |
| **许可** | 随 Easel 项目许可 |

## 说明

头条号没有面向个人创作者的公开图文发布 API，因此沿用与知乎/小红书/公众号后台一致的方案：持久化浏览器 profile + 复用登录态，在 mp.toutiao.com 编辑器里填内容后发布。

头条号后台改版频繁，脚本对所有关键元素采用**多选择器回退**（标题/正文/发布按钮各 3-5 个候选），改版时的修复路径见 `references/publish-flow.md`。

> 整理时间: 2026-09-15
> 用途: 来源溯源与致谢
