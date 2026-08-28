# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | card-design |
| **所属层** | produce（设计系统参考，被其它 card 类 SKILL 生成前引用；也可单独调用做审美指导） |
| **来源类型** | 自研（规则再提炼自开源方案 + 去 AI 味研究，未抄任何文件） |
| **参考项目** | [op7418/guizang-social-card-skill](https://github.com/op7418/guizang-social-card-skill)（**AGPL-3.0**，仅借鉴其设计立场/锁色/「越大越细」/填满≥75%法则/4带密度自检思想，**未复制任何文件**，规则均重新表述）；[comeonzhj/Auto-Redbook-Skills](https://github.com/comeonzhj/Auto-Redbook-Skills)(MIT，主题皮肤/三层结构/自动分页)；[funboy322/avoid-ai-design](https://github.com/funboy322/avoid-ai-design) + [yetone/kill-ai-slop](https://github.com/yetone/kill-ai-slop)（去 AI 味 P0/P1/P2 清单）；[aixier/cardplanet.me](https://github.com/aixier/cardplanet.me) / [Rpeng666/Ant-Card](https://github.com/Rpeng666/Ant-Card)(MIT，风格命名与模板库思路)；配色参考莫兰迪色库(zkcoi/qtccolor) |
| **借鉴方式** | 只借鉴「设计系统 + 硬规则」的方法论，配色/字阶/法则均重新组织表述。确定性质检 `scripts/card_audit.py` 为自研（PIL+numpy 横向边缘密度分析，带 selftest） |
| **内部关系** | 被 card-xiaohongshu / card-quote / poster-hero / comparison-card / xhs-note-creator / paper-explainer(xhs分支) 在生成 HTML 前引用；渲染仍走 shared/scripts/render_card.py（HTML→PNG） |
| **对标** | 类似 Anthropic Claude 的 `dataviz` skill——生成前先读的设计系统 + 生成后校验 |
| **许可** | 随 Easel 项目许可 |

> 整理时间: 2026-08-04
> 用途: 来源溯源与致谢
