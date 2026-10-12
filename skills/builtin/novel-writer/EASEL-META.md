# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | novel-writer |
| **所属层** | produce |
| **来源类型** | 自研（借鉴多个开源方案的方法论） |
| **参考项目** | [NousResearch/autonovel](https://github.com/NousResearch/autonovel)（模板文件体系 world/characters/canon/voice + 双免疫系统去 AI slop）；[Deng-m1/MaliangAINovalWriter 马良](https://github.com/Deng-m1/MaliangAINovalWriter)（三级大纲、黄金三章、Next Outline 剧情推演）；[YILING0013/AI_NovelGenerator](https://github.com/YILING0013/AI_NovelGenerator)（定稿即更新状态文件 + 一致性校验，中文网文）；[GOAT-AI-lab/GOAT-Storytelling-Agent](https://github.com/GOAT-AI-lab/GOAT-Storytelling-Agent)（场景卡分解替代长上下文）；[xindoo/ai-novel-lab](https://github.com/xindoo/ai-novel-lab)（字数门禁 + 修订闭环） |
| **借鉴方式** | 仅借鉴方法论与产物结构（文件即真相 + 按需加载 + 三级大纲 + 滚动前情提要），未引入其代码/依赖。确定性状态管理自研 `scripts/novel_ops.py`（纯标准库，带 selftest） |
| **内部复用** | text-condenser（前情提要滚动压缩）、text-polisher（去 AI 感）、style-transfer（文风统一）、skill-article-outline（大纲底座）、skill-zhihu-publisher（发布）、card-xiaohongshu/xhs-note-creator（图文连载）、shared/scripts/wordcount.py（字数门禁） |
| **许可** | 随 Easel 项目许可 |

> 整理时间: 2026-08-04
> 用途: 来源溯源与致谢
