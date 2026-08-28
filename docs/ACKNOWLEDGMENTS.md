# 致谢 Acknowledgments

Easel 的 SKILL 集合在自研基础上，参考、改编或借鉴了大量优秀的开源项目与方法论。本文汇总所有来源，向原作者致谢。

> 每个 SKILL 的详细来源见其目录下的 `EASEL-META.md`。
> 标注说明：**移植改编** = 基于该项目适配重写；**参考实现** = 借鉴其设计/方法，未复制代码；商业产品/论文仅作方法论参考。
> 部分 license 字段标「待核实」，正式对外发布前建议逐一核对各原库许可证。

---

## 视觉 / 卡片 / 图表

| 项目 | 用于 SKILL | 借鉴点 |
|------|-----------|--------|
| [nexu-io/open-design](https://github.com/nexu-io/open-design) | card-quote / card-xiaohongshu | HTML 卡片模板与视觉签名 |
| [antvis/GPT-Vis](https://github.com/antvis/GPT-Vis) | chart-visualization / infographic | AntV 图表生态、gpt-vis API、@antv/infographic |
| [danpeig/product-compare-matrix-generator](https://github.com/danpeig/product-compare-matrix-generator) | comparison-card | 对比矩阵生成 |
| [dostogircse171/solvyy-comparison-table](https://github.com/dostogircse171/solvyy-comparison-table) | comparison-card | 对比表布局 |
| [codyhouse/products-comparison-table](https://github.com/codyhouse/products-comparison-table) | comparison-card | 响应式对比表 |
| [GreyCat/comparison-table-generator](https://github.com/GreyCat/comparison-table-generator) | comparison-card | 对比表生成 |
| [unopim/unopim-digital-asset-management](https://github.com/unopim/unopim-digital-asset-management) | asset-manager | 目录管理 + 元数据标签 |
| [biagiomaf/smart-comfyui-gallery](https://github.com/biagiomaf/smart-comfyui-gallery) | asset-manager | 本地优先、按 prompt 搜索、标签系统 |
| [enescingoz/awesome-n8n-templates](https://github.com/enescingoz/awesome-n8n-templates) | template-library | 模板分类 + 目录组织 |
| [danielmiessler/fabric](https://github.com/danielmiessler/fabric) | template-library | patterns 模板复用模式 |
| [liangdabiao/ecom-details-image](https://github.com/liangdabiao/ecom-details-image) | ecom-details-image | 电商详情图视觉方案（原始来源） |

## 文案 / 写作 / 风格

| 项目 | 用于 SKILL | 借鉴点 |
|------|-----------|--------|
| [langgptai/LangGPT](https://github.com/langgptai/LangGPT) | post-formatter | 结构化提示词框架 |
| [kangarooking/system-prompt-skills](https://github.com/kangarooking/system-prompt-skills) | post-formatter | 中文销售型文案框架 |
| [MrGeDiao/shuorenhua（说人话）](https://github.com/MrGeDiao/shuorenhua) | post-formatter / text-polisher | 中文去 AI 味改写规则 |
| [charlie947/social-media-skills](https://github.com/charlie947/social-media-skills) | post-formatter / voice-builder / profile-manager | 原始来源：about-me/voice 双文件结构 |
| [omeyazic/ai-voice-capture-framework](https://github.com/omeyazic/ai-voice-capture-framework) | voice-builder | 多维访谈、逼具体化 |
| [angelarose210/ghostwriter](https://github.com/angelarose210/ghostwriter) | voice-builder | 反 AI 感模式库、语气画像维度 |
| [danielrosehill/My-Tone-Of-Voice](https://github.com/danielrosehill/My-Tone-Of-Voice) | voice-builder | 跨格式样本收集 |
| [jaimeschwarz/brandvoice](https://github.com/jaimeschwarz/brandvoice) | voice-builder | 以「拒绝什么」定义声音 |
| [comp-int-hum/llm-style-transfer](https://github.com/comp-int-hum/llm-style-transfer) | style-transfer | LLM 风格迁移 |
| [fuzhenxin/Style-Transfer-in-Text](https://github.com/fuzhenxin/Style-Transfer-in-Text) | style-transfer | 文本风格迁移综述 |
| [souro/tst_llm](https://github.com/souro/tst_llm) | style-transfer | LLM 文本风格迁移 |
| [praj2408/Text-Summarizer-Project](https://github.com/praj2408/Text-Summarizer-Project) | text-condenser | 文本摘要 |
| [Huzaifa785/context-compressor](https://github.com/Huzaifa785/context-compressor) | text-condenser | 上下文压缩 |
| [neopunisher/Open-Text-Summarizer](https://github.com/neopunisher/Open-Text-Summarizer) | text-condenser | 开源文本摘要 |
| [mathsyouth/awesome-text-summarization](https://github.com/mathsyouth/awesome-text-summarization) | text-condenser | 摘要方法综述 |
| [nashsu/Viral_Writer_Skill](https://github.com/nashsu/Viral_Writer_Skill) | social-content | 公众号/小红书/抖音差异化 |
| [maomao52088/xiaohongshu-automation-skills](https://github.com/maomao52088/xiaohongshu-automation-skills) | social-content | 小红书选题/文案/复盘 |
| [op7418/guizang-social-card-skill](https://github.com/op7418/guizang-social-card-skill) | social-content | 小红书轮播 + 公众号封面规格 |
| [JuneYaooo/xhs-writer-skill](https://github.com/JuneYaooo/xhs-writer-skill) | social-content | 小红书爆款方法论、标题公式 |
| [chubbyguan/chubbyskills](https://github.com/chubbyguan/chubbyskills) | social-content | 中文全渠道平台覆盖 |
| [vivy-yi/xiaohongshu-skills](https://github.com/vivy-yi/xiaohongshu-skills) | social-content | 小红书运营技能、违禁词体系 |

## 音频 / 视频

| 项目 | 用于 SKILL | 借鉴点 |
|------|-----------|--------|
| [xiph/rnnoise](https://github.com/xiph/rnnoise) | audio-denoise | RNNoise 降噪算法 |
| [GregorR/rnnoise-models](https://github.com/GregorR/rnnoise-models) | audio-denoise | RNNoise 预训练模型 |
| [timsainb/noisereduce](https://github.com/timsainb/noisereduce) | audio-denoise | 频谱降噪 |
| [louisedesadeleer/clipify](https://github.com/louisedesadeleer/clipify) | clipify | 长视频切片（原始来源） |

## 平台发布 / 数据采集（重型件，多依赖桌面/浏览器环境）

| 项目 | 用于 SKILL | 借鉴点 |
|------|-----------|--------|
| [WJZ-P/douyin-upload-mcp-skill](https://github.com/WJZ-P/douyin-upload-mcp-skill) | skill-douyin-upload | 原始来源：抖音发布 MCP |
| [jiji262/wechat-publisher](https://github.com/jiji262/wechat-publisher) | skill-wechat-publisher | 原始来源：公众号发布 |
| [lucasygu/redbook](https://github.com/lucasygu/redbook) | skill-xhs-analyzer | 原始来源：小红书分析 CLI |
| [white0dew/XiaohongshuSkills](https://github.com/white0dew/XiaohongshuSkills) | skill-xhs-publisher | 主来源（祖先 Angiin/Post-to-xhs） |
| [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | competitor-analysis / content-gap-analysis / ugc-discovery / data-tracker / cross-platform-diff | 多平台采集字段、反爬现状、节奏参数 |
| [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS) | competitor-analysis | 小红书竞品报表维度 |
| [ReaJason/xhs](https://github.com/ReaJason/xhs) | competitor-analysis | 小红书笔记公开字段 |
| [cwjcw/xhs_douyin_content](https://github.com/cwjcw/xhs_douyin_content) | competitor-analysis | 创作者中心数据边界界定 |
| [54514382/xhs_search_comment_tool](https://github.com/54514382/xhs_search_comment_tool) | content-gap-analysis | 评论区采集字段 |
| [laiaccc/XiaohongshuAnalysis](https://github.com/laiaccc) | cross-platform-diff | 小红书分析 |

## 资讯 / RSS 聚合

| 项目 | 用于 SKILL | 借鉴点 |
|------|-----------|--------|
| [cclank/news-aggregator-skill](https://github.com/cclank/news-aggregator-skill) | news-intelligence | 原始来源：新闻聚合 |
| [RSS-Renaissance/awesome-newsCN-feeds](https://github.com/RSS-Renaissance/awesome-newsCN-feeds) | news-intelligence | 中文媒体 RSS 清单 |
| [weekend-project-space/top-rss-list](https://github.com/weekend-project-space/top-rss-list) | news-intelligence | 中文优质 RSS 源 |
| [xiangyugongzuoliu/awesome-rss-feeds](https://github.com/xiangyugongzuoliu/awesome-rss-feeds) | news-intelligence | RSS 源汇总 |
| [SuYxh/ai-news-aggregator](https://github.com/SuYxh/ai-news-aggregator) | news-intelligence | AI/科技多源聚合 |
| [jwenjian/reading-list](https://github.com/jwenjian/reading-list) | news-intelligence | 中文内容聚合形态 |

## 归因 / 策略 / 画像

| 项目 | 用于 SKILL | 借鉴点 |
|------|-----------|--------|
| [bhaskatripathi/pyviralcontent](https://github.com/bhaskatripathi/pyviralcontent) | content-postmortem | 爆款预测 |
| [prateekjain98/social-media-manager-skills](https://github.com/prateekjain98/social-media-manager-skills) | profile-manager | personas 目录结构 |
| [vanities/social-skills](https://github.com/vanities/social-skills) | profile-manager | brand.json 品牌配置 |
| [coreyhaines31/marketingskills](https://github.com/coreyhaines31) | strategy-advisor | 营销策略方法 |
| [blacktwist/social-media-skills](https://github.com/blacktwist) | strategy-advisor | 社媒策略 |
| [inovector/mixpost](https://github.com/inovector/mixpost) | publish-checklist | 发布管理 |
| [trypostit/trypost](https://github.com/trypostit/trypost) | publish-checklist | 发布流程 |

## 工具 / 算法

| 项目 | 用于 SKILL | 借鉴点 |
|------|-----------|--------|
| [isee15/Lunar-Solar-Calendar-Converter](https://github.com/isee15/Lunar-Solar-Calendar-Converter) | event-calendar | 农历↔公历换算算法 |
| [jjonline/calendar.js](https://github.com/jjonline/calendar.js) | event-calendar | lunarInfo 年表算法 |
| [yiyangcpa/Cross-Platform-Comparison](https://github.com/yiyangcpa/Cross-Platform-Comparison) | cross-platform-diff | 跨平台对比框架（Springer 2021） |

## 方法论 / 商业产品 / 论文（非代码借鉴）

- **理论**：Newsjacking（David Meerman Scott，trend-rider）、Google E-E-A-T（seo-quality）、JTBD、直播电商四段式话术、内容金字塔
- **商业产品**（分析维度参考）：Metricool、Iconosquare、SocialBee、SocialBlade、Later、Mention、Brand24、Taskade、ZBrain、新榜/飞瓜/蝉妈妈/千瓜/微播易/克劳锐、巨量/千川
- **学术**：ACL 2022 文本风格迁移、arXiv 2025 抖音 vs TikTok、WikiProject AI Cleanup

---

*若有遗漏或标注有误，欢迎指正。所有原库版权归各自作者所有。*
