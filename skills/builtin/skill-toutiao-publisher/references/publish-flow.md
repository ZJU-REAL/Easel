# 头条号发布链路与选择器维护

> 本文件是领域知识，`scripts/toutiao_publish.py` 改动选择器时对照本表。
> **2026-10 已用真实账号真机校准**，下面标「真机」的都是实测结论，不是推导。

## 一、链路

```
mp.toutiao.com/auth/page/login          扫码登录（登录态存 ToutiaoProfile）
        ↓
mp.toutiao.com/profile_v4/graphic/publish   图文发布页
        ├── 标题输入框（textarea，placeholder「请输入文章标题（2～30个字）」）
        ├── 正文富文本编辑器（.ProseMirror）
        │     ├── 工具栏「图片」.syl-toolbar-tool.image → 图片面板 → 上传 → 点「确定」
        │     └── 话题：正文里打「#话题名」→ 联想列表 .forum-list-item-text → 点选
        ├── 封面设置（「展示封面 / 无封面」单选）
        ├── 作品声明 / 定时发布 等右侧选项
        └── 「预览并发布」→ 二次确认弹窗
```

**没有「存草稿」按钮**（真机）：页面上只有 预览 / 定时发布 / 预览并发布，草稿是**自动保存**的
（页面底部提示「草稿将自动保存」，编辑过程中显示「草稿保存中...」）。
所以「存草稿」= 填完内容就停，等平台自动保存；**dry-run 也会在草稿箱留下一份**（真机实测草稿数 3→4）。

## 二、选择器表（脚本里的常量，按顺序回退）

| 元素 | 脚本常量 | 候选选择器 | 备注 |
|---|---|---|---|
| 标题 | `TITLE_SELECTORS` | `textarea[placeholder*='标题']` / `input[placeholder*='标题']` / `.article-title textarea` / `.title-input textarea` / `textarea.byte-input__textarea` | 真机：首个选择器即命中，placeholder 是「请输入文章标题（2～30个字）」 |
| 正文 | `BODY_SELECTORS` | `.ProseMirror` / `div[contenteditable='true'][data-placeholder]` / `div.editor-content[contenteditable='true']` / `#ueditor_0` | 真机：`.ProseMirror` 命中。老版页面正文在 iframe 里，见 `BODY_IFRAME_SELECTORS` |
| 发布 | `SUBMIT_SELECTORS` | `button:has-text('预览并发布')` / `text=预览并发布` / `button:has-text('发布')` / `div.publish-btn` | 真机：只有「预览并发布」。**没有存草稿按钮** |
| 正文插图入口 | `IMAGE_BUTTON_SELECTORS` | `.syl-toolbar-tool.image` / `button:has-text('图片')` / `[aria-label*='图片']` / … | 真机：字节系工具栏的图片工具 class 就是 `image`（元素 class = `syl-toolbar-tool image static`） |
| 插图面板 | 内联 | 面板里**可见的** `input[type=file]`（可见那个在 `.upload-btn` 里，另一个是隐藏的拖拽区） | 真机：面板标签为 上传图片 / 免费正版图片 / 热点图库 / 我的素材 / 本地上传 / 扫码上传 |
| 插图确认 | `IMAGE_CONFIRM_SELECTORS` | `button:has-text('确定')` / `.byte-btn:has-text('确定')` / `text=确定` | **漏了它，图只停在面板素材区，编辑器里不会有图**（真机踩过） |
| 插图结果判定 | `EDITOR_IMG_SELECTOR` | `.ProseMirror img` / `div[contenteditable='true'] img` / `.editor-content img` | 上传后编辑器里会多出 `<div class="pgc-img"><img src="https://image-tt-private.toutiao.com/...">` |
| 话题联想项 | `UPLOADED_THUMB_SELECTORS` 之外的 `.forum-list-item-text` | 文本与话题名**完全相等**才点 | 真机：联想项 class = `forum-list-item-text`（父 `.forum-list-item`） |
| 话题结果判定 | `.ProseMirror a.tteditor-forum` | — | 真机：选中后生成 `<syl-inline><a class="tteditor-forum" data-name="代际">#代际#</a></syl-inline>` |
| 话题触发 | — | 先打「#」等约 1s，再打话题名 | 真机：**一次性插「#话题」不会唤起联想**，必须分两步（真机实测：一次性 → 无联想项；分步 → 有） |
| 草稿自动保存 | `_wait_autosave` | 页面正文含「草稿保存中」或「草稿已保存」 | 真机：平台**不显示**「已保存」，只有「草稿保存中...」；偶发短暂出现「保存失败」后重试成功 |
| 封面 | `COVER_INPUT_SELECTORS` | `[class*='cover'] input[type='file']` 等 | 页面上有多个 file input，优先挑封面区的，其次挑编辑器之外的 |
| 成功判定 | `SUCCESS_HINTS` | `发布成功` / `已发布` / `内容管理` / `草稿箱` | 点完按钮后读 `body` 全文匹配 |

## 三、三个关键交互（真机踩过的坑）

### 3.1 正文插图：点图片工具 → 塞图 → **点「确定」**

```
点 .syl-toolbar-tool.image          → 图片面板打开
给面板里可见的 input[type=file] 塞图 → 平台传自己 CDN（POST /spice/image），面板显示「已上传 N 张图片」
点面板底部「确定」                   → 图片插进编辑器当前光标处
```
少第三步，图就只停在面板的素材区（`ul.image-list`），编辑器里永远没有图——这是最早那版实现失败的原因。

### 3.2 话题：正文里打「#话题名」→ 点联想项

头条图文**没有独立的话题输入框**。话题是在正文里打「#」唤起联想（提示「敲空格可取消插入话题」），
再点联想项（文本与话题名完全一致）才会变成真话题节点。平台上没有的话题点不出来——
脚本会把刚打进去的「#话题」用退格撤掉，不在正文里留半截井号。

### 3.3 草稿：自动保存，没有按钮

因此：
- `--draft` = 填完标题/正文/插图/话题就停，等自动保存，**绝不点「预览并发布」**
- `--exec` = 填完之后点「预览并发布」→ 处理二次确认弹窗
- **dry-run 也会留草稿**（真机实测）

## 四、改版了怎么修

1. **先跑 dry-run 定位失败点**：`steps` 字段会告诉你 `title` / `body` / `images` / `tags` 哪个没填上；插图失败会在 `error` 里列出没能插入的图片路径。
   ```bash
   python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py \
     --input outputs/主题名/article.md --title "标题" --headed \
     --images outputs/主题名/图1.png
   ```
   `--headed` 能直接看到浏览器停在哪一步。
2. **在浏览器 DevTools 里取新选择器**：优先用**语义稳定**的属性（placeholder 文本、按钮可见文字），避免 `class` 哈希 / `:nth-child` 这类易变定位。
3. **加进候选列表的末尾**，保留旧选择器——头条灰度发布期间不同账号页面版本可能不同。
4. **改完跑自检 + dry-run**：
   ```bash
   python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py --selftest
   ```
   再在仓库根跑一遍契约校验：`python scripts/validate_skill_commands.py`（在仓库根执行，不在本 skill 目录下）。

## 五、登录态

- profile 目录：`~/.easel-browser-profiles/ToutiaoProfile`
- 失效表现：访问发布页被跳回 `auth/page/login`，脚本返回 `未登录头条号：先跑 --login 扫码`
- 头条登录常要求短信验证，`--login` 时留意手机；同一 profile 长期复用可显著降低二次验证概率
- 别把 profile 目录提交进仓库（`.gitignore` 已排除 `~/.easel-browser-profiles` 这类 home 目录）

## 六、发布留痕

每次发布成功都会写 `outputs/_publish/toutiao_<时间戳>.json`（系统目录，经 `skills/shared/scripts/output_paths.py` 校验）。内容库不展示该系统目录，它是给归因层和排障用的。

