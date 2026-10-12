# 商品图与详情页序列模板

## 商品和营销转化流程

商品主图、电商图片、广告图和 PDP 视觉不要从固定模板开始，要先判断转化驱动力。选择一个主要驱动力：

### A. 视觉驱动型

适用于购买决策依赖外观、风格匹配、光洁度、质感、前后对比或礼品属性的产品。重点：

- 一眼抓住产品吸引力。
- 质感、细节、工艺和质量信号。
- 使用场景和视觉层级。
- 简短利益点。

### B. 痛点驱动型

适用于买家有明确摩擦、风险、时间损失、不适或反复烦恼的产品。强制顺序：

1. 痛点挖掘 / 风险触发。
2. 利益 / 解决方案。
3. 信任和证明。
4. 优惠 + CTA。

重点是具体问题、缓解机制、证据和风险逆转。

### C. 情感价值驱动型

适用于购买和身份、信心、归属、地位、关怀、快乐、新奇或冲动相关的产品。重点：

- 情绪钩子。
- 身份或向往。
- 产品作为实现方式。
- 社交证明和低摩擦行动。

## 商品图序列模板

当用户提到"详情页、PDP、Amazon A+、Shopify 商品页、主图堆栈、整套商品图、商品详情图片"时，不要只停留在 5 张主图。必须追加详情页图片序列，并把每一屏都写成可单独生图的 Prompt。

### 视觉驱动主图序列

1. 一眼可懂的视觉主张。
2. 核心功能或质感特写。
3. 使用场景匹配。
4. 普通方案 vs 升级方案对比。
5. 优惠、物流、保障或 CTA 画面。

### 痛点驱动主图序列

1. 问题快照。
2. 解决机制。
3. 利益证明。
4. 信任画面。
5. 优惠 + 紧迫 CTA。

### 情感价值主图序列

1. 情绪场景钩子。
2. 身份 / 价值表达。
3. 产品作为实现方式。
4. 归属、地位或社交信号。
5. 带情绪强化的优惠 + CTA。

## 详情页图片序列模板

详情页图片用于移动端纵向浏览，默认每张图独立成屏，尺寸优先使用 `2:3` 或平台指定竖版比例。除非用户明确只要文案，否则每个模块都要输出对应图片 Prompt。

### 通用 PDP 详情页图片序列

1. 首屏承接：延续主图卖点，说明产品为谁解决什么问题。
2. 痛点放大：展示用户当前的不便、损失、风险或反复烦恼。
3. 机制解释：用视觉化结构说明产品如何发挥作用，避免虚构无法证明的数据。
4. 核心利益：把 2-4 个主要利益做成易扫读的信息图。
5. 使用步骤：用 3-4 步说明怎么用，降低理解成本。
6. 场景覆盖：展示典型使用场景、适用对象或使用前后状态。
7. 对比选择：普通方案 vs 本产品，突出可观察差异和体验差异。
8. 信任背书：展示材料、包装、质检、保障、真实评价等已有证据；没有证据就写"proof placeholder"，不要编造认证。
9. FAQ / 风险逆转 / CTA：处理残留、适用范围、售后、组合优惠等临门疑虑。

### 驱动力适配

- 视觉驱动型：增加质感细节、尺寸比例、使用场景和礼品感。
- 痛点驱动型：严格按"问题严重性 → 解决机制 → 利益证明 → 信任 → CTA"推进。
- 情感价值驱动型：增加生活方式、身份表达、社交场景和情绪回报。

### 图片内文字规则

- 详情页图片可以有短文案，但必须短、清楚、适合移动端。
- 每屏主标题建议 3-7 个英文词或 6-12 个中文字。
- 说明性文字用 2-4 个短标签，不要生成大段小字。
- 每一区文字量严格控制：标题 + 副标题 + 小标注不超过 50 个字。
- 中文字用「」中文引号包裹，如「修护屏障」「72h 深层锁水」，渲染准确率更高。
- 指定字体大小：标题 28-48pt，副标题 16-20pt，标注 10-14pt。
- 颜色用 hex 码：深灰标题 `#2D2D2D`，浅灰标注 `#888888`，金色强调 `#D4AF37`。
- 如果模型容易生成乱码，Prompt 中明确要求 "clean layout with short readable headline placeholders, no dense body text"。
- 出图后必须放大 200% 逐字核对中文笔画，复杂字换简单同义字。

### 视觉节奏规则（多图任务）

连续多张图的背景色不能完全一样，否则消费者视觉疲劳。多图任务必须交替使用 2-3 种背景色：

- 白底主图 / 卖点副图：`#FFFFFF`
- 成分解析 / 质地展示：`#F5F1E8`（浅米色）
- 品牌主视觉 / 促销图：品牌深色（如 `#1A3A2E`）

### 多角度镜头规则（多图任务）

**全套图片绝不能全部使用同一个拍摄角度。** AI 生图默认倾向生成正面 3/4 角度，如果不显式指定镜头角度，整套图会看起来千篇一律。多图任务必须在 Prompt 中为每张图分配不同的镜头角度和景别。

#### 角度清单（按用途选择 4-6 种组合）

| 角度 | Prompt 写法 | 适用场景 |
|---|---|---|
| 正面 3/4 | `at a slight 3/4 angle showing full front facade` | 主图、首图 |
| 正上方俯视 | `photographed directly from above at a 90-degree overhead angle` | 展示布局、内部结构、平铺 |
| 侧面 90° | `photographed from a clean 90-degree side profile` | 展示深度、层次、侧面细节 |
| 后侧 45° | `photographed from behind at a 45-degree rear angle` | 展示背面细节、码头、尾部构造 |
| 仰视低角度 | `photographed from a very low angle looking upward` | 英雄镜头、气势感、儿童视角 |
| 高角度俯视 | `photographed from a high 45-degree angle looking down` | 展示顶部、整体规模、桌面视角 |

#### 景别清单（按用途选择 2-3 种组合）

| 景别 | Prompt 写法 | 适用场景 |
|---|---|---|
| 全景 | `full product visible, product occupies 35-40%` | 主图、场景图 |
| 中景 | `showing the [section name] area, product occupies 45-50%` | 功能展示、结构说明 |
| 特写 | `tight zoom on [specific detail], product detail occupies 55-60%` | 材质纹理、工艺细节、按钮/接口 |
| 微距 | `extreme close-up macro shot, shallow depth of field` | 面料编织、接缝工艺、表面纹理 |
| 局部 | `close-up detail shot focusing on [specific part]` | 灯塔信标、大炮、拉链、标签 |

#### 多角度分配原则

1. **主图序列（5 张）**：至少使用 3 种不同角度，其中 1 张必须是特写或微距。
2. **详情页序列（7-9 张）**：至少使用 4 种不同角度，其中 2 张必须是特写/微距。
3. **不能连续 3 张图使用相同角度**，否则消费者视觉疲劳。
4. **全景图不超过整套的 40%**，必须穿插中景、特写和微距增加节奏感。
5. **仰视和俯视各至少 1 张**，打破平视拍摄的单一感。
6. 每张 Prompt 必须显式写明角度关键词（如 `side profile`、`from above`、`low angle`），不要假设模型会自动变换角度。

#### 角度 Prompt 模板

在每张图片 Prompt 的「构图、镜头和取景」段落中，直接嵌入角度描述：

```text
# 俯视图
Bird's eye top-down view. The [product] photographed directly from above at a 90-degree overhead angle, showing the full layout [specific details visible from above]. Deep even lighting from directly above minimizing shadows.

# 侧视图
Side profile view. The [product] photographed from a clean 90-degree side profile, showing [what's visible from side]. Strong side lighting from the left creating dramatic depth.

# 仰视图
Dramatic low-angle hero shot. The [product] photographed from a very low angle looking upward, making [tower/building] appear tall and imposing. Strong upward lighting creating heroic dramatic shadows.

# 微距特写
Extreme close-up macro shot. Tight zoom on the [specific detail], showing [texture/mechanism/individual elements]. Shallow depth of field with the foreground in sharp focus and background slightly blurred. Warm directional side lighting highlighting surface texture.

# 后侧角度
Rear angled view. The [product] photographed from behind at a 45-degree rear angle, revealing [back details not visible from front]. This angle shows construction details not visible from the front.
```

### 详情页信息图结构规则（关键！）

**详情页图片 ≠ 多角度产品照片。** 详情页图片必须是电商信息图格式，包含卖点文案、图标、标签、对比、步骤、信任徽章等信息图元素，产品在不同信息图中展示不同角度。多角度是为信息图服务的展示手段，不是目的。

#### 错误做法（只换角度，没有信息图结构）

```
# 错误：这只是"同一产品换个角度拍"，缺少电商转化元素
Prompt: Side profile view of the product on white background. Product occupies 38%. Whitespace 50%+.
```

#### 正确做法（电商信息图 + 多角度产品展示）

```
# 正确：有标题、卖点图标、标签、信息图布局，产品在其中展示特定角度
E-commerce infographic benefits screen on #FAF7F2 background.
Top headline in #2D2D2D at 28pt reading 「Core Benefits」.
Left side: the product shown from an elevated overhead angle.
Right side: four benefit rows stacked vertically with thin-line icons:
  (1) icon + 「Feature One」 in #7A9E7E
  (2) icon + 「Feature Two」 in #8B6F47
  (3) icon + 「Feature Three」 in #7A9E7E
  (4) icon + 「Feature Four」 in #8B6F47
Clean two-column layout. Product occupies 35%. Whitespace 48%+.
```

#### 详情页每屏必须包含的信息图元素

| 屏幕 | 电商结构 | 信息图元素 | 产品角度建议 |
|---|---|---|---|
| 首屏承接 | 标题 + 产品 + 4个特色图标 + 副标题 | 图标+标签环绕产品 | Front 3/4 |
| 痛点对比 | 3个痛点图标 → 3个解决方案 + 产品 | 上下对比布局 | Side profile |
| 核心特色 | 多栏并列展示 + 每栏标签和描述 | 网格/三栏布局 | 各元素独立特写 |
| 核心利益 | 左产品 + 右利益列表（图标+短文案） | 双栏信息图 | Elevated overhead |
| 使用步骤 | 4步时间线/编号圆 + 最终成品展示 | 步骤流程图 | Low-angle (最终效果) |
| 场景覆盖 | 3个场景照片 + 场景标签 | 三行场景卡 | 不同使用环境 |
| 信任/工艺 | 微距细节图 + 标注圆 + 信任徽章 | 细节标注图 | Macro特写 |
| CTA/礼品 | 标题 + 产品 + 卖点徽章 + CTA按钮 | 转化闭合布局 | Front 3/4 |

#### 信息图 Prompt 必须包含的要素

1. **布局关键词**：`e-commerce infographic`, `structured grid layout`, `two-column layout`, `three-row layout`, `timeline`, `comparison layout`
2. **标题和文案**：`headline in #2D2D2D at 28pt reading 「...」`, `label in #7A9E7E at 14pt reading 「...」`
3. **信息图元素**：`feature callout icons`, `thin connecting lines`, `numbered circles`, `trust badges`, `CTA button placeholder`
4. **产品角度**：每张信息图中产品从不同角度展示，但角度是为信息图内容服务的
5. **电商 Prompt 开头**：每张详情页 Prompt 必须以 `E-commerce infographic [screen type]` 开头，而不是 `Close-up shot` 或 `Side view`

### 字体搭配规则

- 主标题用衬线体（如 Didot），副标题和正文用无衬线体（如 SF Pro Display）。
- 这是奢侈品画册的标准组合，高级感强。
- 整套图只能用这 2 种字体，禁止混用第三种。

## 多图生成执行规则

当用户要求直接生成整套电商图片：

1. 先建立 Campaign Style Lock，并写入图片包计划。
2. 再为每张图建立编号、用途、画幅、图片内短文案和独立 Prompt。
3. 主图默认 `1:1`（2K）；详情页图片默认 `2:3`（2K）。
4. 每张图使用独立 Prompt 文件，避免一次 Prompt 生成多屏拼图。
5. 每张独立 Prompt 必须以同一段 Campaign Style Lock 开头。
6. 输出目录用产品英文 slug，例如 `generated-images/laundry-detergent-pods-pdp/`。
7. 如果 API 或模型不支持某个尺寸，改用最接近的支持尺寸，并在结果中说明。
8. 如果缺少 `.env` 或生图配置，只输出完整 Prompt 包，不调用脚本。
9. 不要虚构认证、实验数据、评分、销量、真实评价或品牌授权。
