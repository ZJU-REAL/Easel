# meta.json Schema

`meta.json` 是每篇文章目录下的核心元数据文件。不同平台共用下面的基础字段，平台特有字段附加在各自扩展里。

## 基础字段（所有平台）

```json
{
  "title": "文章标题",
  "summary": "一句话摘要",
  "author": "",
  "platform": "公众号 | 小红书 | 头条号 | 通用",
  "created_at": "ISO 8601 时间（Asia/Shanghai）",
  "tags": ["标签1", "标签2"],
  "word_count": 0,
  "cover_image": "封面图文件名（可选）",
  "images": ["images/下的相对路径列表"],
  "references": {
    "search_queries": ["使用的搜索关键词"],
    "source_count": 0,
    "summary_file": "reference/summary.md"
  }
}
```

## 公众号扩展字段

```json
{
  "platform": "公众号",
  "theme": "橙心",
  "cover_image_prompt": "英文生图 prompt（可选）",
  "cover_image_url": "封面图上传后的 URL（可选，发布阶段写入）",
  "wechat": {
    "draft_media_id": "",
    "published_url": ""
  }
}
```

## 小红书扩展字段

```json
{
  "platform": "小红书",
  "post_format": "image | video",
  "caption": "100-300 字发布文案",
  "hashtags": ["#话题1", "#话题2"],
  "poster_style": "card-design 风格名（如 瑞士极简 / 杂志编辑 / 手账贴纸 / 奶油温柔 …见 card-design/references/styles.md）",

  "card_count": 7,
  "cards": [
    {
      "page": 1,
      "type": "cover | content | ending",
      "title": "卡片小标题（cover/content）",
      "content": "卡片正文（≤80 字中文）",
      "synthesis_strategy": "html_card | text_on_photo | collage",
      "material_refs": ["m001", "m002"],
      "image_prompt": "图片生成 prompt（可选）",
      "image_url": "卡片图片 URL（可选）"
    }
  ],

  "shots": [
    {
      "index": 1,
      "duration_sec": 3.0,
      "narration": "口播 ≤30 字",
      "on_screen_text": "屏幕字 ≤15 字",
      "visual": "画面描述",
      "material_ref": "m002"
    }
  ],

  "materials": [
    {
      "id": "m001",
      "path": "reference/<相对路径或原始绝对路径>",
      "kind": "text | image | video | audio",
      "caption": "画面描述",
      "usage": "cover | content-N | ending | reference-only | discard",
      "strategy": "html_card | text_on_photo | collage | use_original"
    }
  ]
}
```

字段使用规则：

- `post_format` = `image` 时，`cards[]` 必填、`shots[]` 省略
- `post_format` = `video` 时，`shots[]` 必填；`cards[]` 只需一张 `cover` 作为封面
- `materials[]` 仅在用户提供了素材时出现；详细工作流见 `material-intake.md`
- `synthesis_strategy` 为每张卡选择合成路径；`material_refs` 指向 `materials[].id`

## 字段规则

- **title**：≤30 字，公众号 ≤64 字符会被微信截断；小红书建议 10-20 字带 emoji
- **summary**：公众号 ≤20 字（微信摘要字段 ≤120 字符）；小红书无 summary，用 caption
- **created_at**：ISO 8601 带时区，例 `"2026-04-24T15:00:00+08:00"`
- **word_count**：正文字数（不含标题、摘要、caption）
- **images**：只列 `images/` 下的相对路径，不含外链
- **references.source_count**：去重后的来源数

## 完整示例

### 公众号

```json
{
  "title": "AI 冲击就业？Anthropic 最新研究揭示劳动力市场的真相",
  "summary": "失业率在下降，新岗位在增加。数据比标题党更有说服力。",
  "author": "",
  "platform": "公众号",
  "created_at": "2026-04-24T15:00:00+08:00",
  "theme": "橙心",
  "tags": ["AI", "就业", "劳动力市场"],
  "word_count": 3040,
  "cover_image": "cover.jpg",
  "cover_image_prompt": "A professional workspace, clean desk, soft natural light",
  "images": ["images/img_001.jpg", "images/img_002.jpg"],
  "references": {
    "search_queries": ["AI 失业 2026", "Anthropic economic index"],
    "source_count": 6,
    "summary_file": "reference/summary.md"
  }
}
```

### 小红书

```json
{
  "title": "💼 AI 失业危机？数据告诉你真实情况",
  "platform": "小红书",
  "created_at": "2026-04-24T15:00:00+08:00",
  "caption": "媒体说危机，数据说增长。Anthropic 调研 5000 人，83% 说 AI 提高效率而非取代……",
  "hashtags": ["#AI对工作的影响", "#失业危机是假的"],
  "poster_style": "杂志编辑",
  "card_count": 7,
  "cards": [
    {
      "page": 1,
      "type": "cover",
      "title": "💼 AI 失业危机？",
      "content": "媒体说危机，数据说增长\n美国失业率：4.2%→3.8%"
    }
  ],
  "images": [],
  "references": {
    "search_queries": ["AI 就业影响 2026"],
    "source_count": 4,
    "summary_file": "reference/summary.md"
  }
}
```
