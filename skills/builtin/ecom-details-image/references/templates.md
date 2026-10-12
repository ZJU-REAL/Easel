# 场景模板系统

`references/templates/` 目录包含 25 个场景模板（JSON），每个模板提供 `prompt_template`、`variants`（风格变体）、`category_tips`（品类建议）、`examples` 和 `anti_ai_tips`。

## 模板匹配表

| 触发词 | 模板文件 |
|---|---|
| 白底图, 主图, hero image, packshot | `01-hero-image.json` |
| 场景图, 生活图, lifestyle | `02-lifestyle-scene.json` |
| 平铺图, flat lay, 俯拍 | `03-flat-lay.json` |
| 细节图, 微距, macro, 特写 | `04-detail-macro.json` |
| 海报, poster, banner, 促销 | `05-poster-banner.json` |
| 社交媒体, 小红书, Instagram, TikTok | `06-social-media.json` |
| UGC, 买家秀, GRWM | `07-ugc-style.json` |
| 模特, model, 人物展示 | `08-model-showcase.json` |
| 对比, before after, 前后 | `09-before-after.json` |
| 包装, packaging, 礼盒 | `10-packaging.json` |
| 信息图, A+, 详情页 | `11-infographic.json` |
| 创意, 概念, creative | `12-creative-concept.json` |
| 尺寸, 规格, 使用步骤 | `13-size-spec.json` |
| 套装, 组合, bundle | `14-multi-product.json` |
| 直播, livestream | `15-livestream.json` |
| 试穿, 融入, try on | `16-try-on-virtual.json` |
| 拆解图, 爆炸图, exploded view | `17-exploded-view.json` |
| 隐形模特, ghost mannequin, 3D服装 | `18-ghost-mannequin.json` |
| 多角度, 网格, grid, 多色展示 | `19-multi-angle-grid.json` |
| 杂志, 封面, editorial, magazine | `20-magazine-editorial.json` |
| 季节, 四季, campaign, 春夏秋冬 | `21-seasonal-campaign.json` |
| 奢华, 氛围, 烟雾, luxury, atmospheric | `22-luxury-atmospherics.json` |
| 设备模型, 界面, mockup, SaaS, APP | `23-device-mockup.json` |
| 店铺, 门面, 空间, storefront, 实体店 | `24-storefront.json` |
| 运动, 健身, sports, fitness | `25-sports-campaign.json` |

无匹配 → 默认 `01-hero-image.json`。**只读取匹配到的模板文件**，不要一次性加载全部。

## 模板使用方式

1. 取 `prompt_template` 作为 Prompt 基础结构。
2. 用用户产品信息替换 `{variables}`。
3. 用户指定风格变体 → 应用 `variants.<name>.overrides`。
4. 已知产品品类 → 应用 `category_tips.<category>`。
5. 简化：只保留有值的字段，输出简洁的自然语言 Prompt。

## 风格变体速查

每个模板通常包含 3-4 个风格变体，常用变体类型：

- **luxury** — 高端奢华（Rembrandt 光线、金色点缀、深色渐变）
- **minimal** — 极简现代（纯白/浅色、干净线条、大留白）
- **fresh** — 清新自然（明亮自然光、柔和粉彩、通透感）
- **tech** — 科技感（戏剧性侧光、深色背景、金属质感）
