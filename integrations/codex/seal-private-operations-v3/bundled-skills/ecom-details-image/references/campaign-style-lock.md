# 整套图片风格一致性规则（Campaign Style Lock）

当生成主图 + 详情页、PDP 图片包、广告组图、社媒组图或任何多张图片时，必须先定义一个 **Campaign Style Lock**。这是整套图的视觉合同，不是灵感描述。

## Campaign Style Lock 必填字段

1. **视觉方向**：例如 premium tech ecommerce、clean household care、warm gift editorial。
2. **固定色板**：限制为 2-3 个主色 + 1 个强调色；写清楚背景色、文字色、强调色，不要每张图重新配色。
3. **冷暖调**：明确 warm / cool / neutral，并要求全套一致。
4. **字体系统**：统一为一种字体风格，例如 modern geometric sans-serif；禁止混用衬线、手写、复古、卡通字体。
5. **背景系统**：统一背景材质、空间和深浅，例如 clean light gray studio background 或 deep navy premium tech background。
6. **光线系统**：统一光源方向、阴影强度、反光质感和氛围。
7. **布局系统**：统一留白、圆角、分栏、标签、编号和信息图组件风格。
8. **图标 / 插画系统**：如果用图标，统一线宽、形状、颜色和复杂度。
9. **产品呈现规则**：产品角度、大小比例、材质表现和是否居中必须稳定。
10. **禁止漂移项**：明确禁止 changing color palette, mixed fonts, inconsistent lighting, random backgrounds, mismatched icon styles。

## 默认 Style Lock 模板

如果用户没有给品牌规范，使用保守统一的电商视觉系统：

```text
Campaign Style Lock: consistent premium ecommerce visual system across the entire image set; fixed palette of clean off-white background, deep charcoal text, one product-matched accent color, and one soft secondary accent; neutral-cool studio lighting; modern geometric sans-serif headline placeholders only; consistent rounded rectangular info labels; consistent thin-line icon style; clean high-end product photography mixed with minimal infographic elements; stable product scale and placement; generous whitespace; no color palette changes, no mixed fonts, no random backgrounds, no inconsistent lighting, no mismatched icon styles.
```

## 多图 Prompt 强制规则

- 每张图 Prompt 的第一段必须是同一段 Campaign Style Lock，不能改写、缩短或换同义词。
- 单张图只能改变：画面目的、主体动作、局部构图和短文案。
- 单张图不能改变：色板、冷暖调、字体风格、背景系统、光线系统、图标风格和信息标签样式。
- 如果用户要求重生其中一张图，必须复用原来的 Campaign Style Lock。
- 如果已生成图片风格不一致，优先重写 Prompt 包，而不是逐张随意补描述。
