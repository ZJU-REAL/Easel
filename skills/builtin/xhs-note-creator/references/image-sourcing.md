# 文章配图：搜索、版权检查与处理

配图遵循**零水印上线**原则：每张图在写入 Markdown 前必须目视检查，高风险图片必须处理后才能使用。

## 安全图源优先级（从低风险到高风险）

1. **AI 生成**（用户自备 text-to-image 服务：Nano Banana、Gemini Image、Flux、SD 等）—— 零版权风险，概念图 / 装饰图首选
2. **Unsplash**（`images.unsplash.com`）—— Unsplash License，免费商用，无需署名
3. **Pexels**（`images.pexels.com`）—— 免费商用，无需署名
4. **Pixabay**（`pixabay.com`）—— CC0，免费商用
5. **官方 OG 图 / Press Kit**（GitHub opengraph、产品官网 press kit、开源项目 banner）—— 公开素材可引用
6. **自截产品截图** —— 合理使用范围内
7. **新闻 / 博客配图** —— 必须检查水印，见下方处理流程

## 图片搜索技巧

- 用英文关键词效果更好（`"Hermes agent terminal install"` 而非 `"安装终端"`）
- 加限定词提高精准度：`photo`、`screenshot`、`diagram`、`illustration`、`site:unsplash.com`
- GitHub OG 图固定格式：`https://opengraph.githubassets.com/1/{owner}/{repo}`
- Unsplash 用 `images.unsplash.com` 直链或官方 API（旧的 `source.unsplash.com` 随机直链已于 2024 年废弃，勿再用）

下载命令：

```bash
mkdir -p output/.../images
curl -L -o "output/.../images/img_001.jpg" "https://图片URL" 2>/dev/null
```

## 版权风险检查（每张图必做）

下载后立即用**多模态 Read 工具**目视检查：

```
Read tool → 查看图片 → 判断风险等级
```

### 风险分级

| 等级 | 特征 | 处理 |
|------|------|------|
| ✅ 安全 | 无水印；Unsplash / Pexels / Pixabay；官方 OG 图；AI 生成 | 直接用 |
| ⚠️ 低风险 | 无明显水印的新闻截图；博客作者自拍无署名 | 建议替换；急用可留 |
| ❌ 高风险 | 带水印（Getty / Shutterstock / 视觉中国 / 东方 IC / 图虫）；摄影师个人署名；新闻社图（AP / Reuters / AFP / 新华社）带水印标注 | 必须处理 |

### 高风险标志识别

目视重点看：

- **四个角落**：最常见水印位置（右下角尤其注意）
- **底部横条**：视觉中国、东方 IC 常用
- **半透明文字叠加**：Getty Images 常见
- **图片内嵌文字**：摄影师名字、媒体 logo

## 高风险图片处理方法

### 方法一：裁剪去水印（适合水印在边缘的新闻图）

```bash
python3 -c "
from PIL import Image
img = Image.open('output/.../images/img_xxx.jpg')
w, h = img.size
# 根据水印位置裁剪，示例：去掉底部 40px
cropped = img.crop((0, 0, w, h - 40))
cropped.save('output/.../images/img_xxx.jpg')
print(f'裁剪完成：{w}x{h} → {w}x{h-40}')
"
```

常见水印位置裁剪参考：

- 右下角水印 → `img.crop((0, 0, w - 120, h))` 或 `img.crop((0, 0, w, h - 30))`
- 底部横条 → `img.crop((0, 0, w, h - 50))`
- 四周留白水印 → 适当裁四边

**裁剪后再次用 Read 工具目视确认水印已去除。**

### 方法二：AI 生图替换（水印无法去除时）

调用用户自备的 text-to-image 服务，提示词写作要点：

- 具体描述场景而非抽象概念
- 加风格词：`minimalist`、`clean`、`professional`、`flat design`
- 避免真实人脸（肖像权风险）
- 小红书封面卡指定 `aspect_ratio="3:4"`（竖版）

## 完整配图流程

1. 根据章节内容确定需要什么类型的图（事实图 or 概念图）
2. 按安全图源优先级选择来源
3. 用 `curl` 下载到 `images/` 目录
4. **用 Read 工具目视检查** → 判断风险等级
5. 高风险 → 裁剪或 AI 替换 → 再次确认
6. 在 Markdown 中写入相对路径引用：`![描述](images/img_001.jpg)`
7. **不允许在 .md 文件中留 `【插入图片：...】` 占位符**
