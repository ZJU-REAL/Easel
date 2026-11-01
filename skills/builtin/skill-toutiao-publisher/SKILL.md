---
name: skill-toutiao-publisher
description: >-
  今日头条（头条号）图文发布：把已成稿的文章发布到 mp.toutiao.com，支持标题、
  封面、话题标签、存草稿与直接发布，走 Playwright 浏览器自动化 + 登录态持久化。
  当用户说"发头条""发布到今日头条""头条号发文章""同步到头条""头条存草稿""头条图文发布"时使用。
  与 skill-cross-platform-publish 的区别：那个是一稿多发的编排层，本 SKILL 只管头条单平台落地发布；
  正文生产交给制作层 SKILL（copywriting / article-outline）。
layer: publish
---

# skill-toutiao-publisher（发布层 · 今日头条图文）

> 把图文内容发布到今日头条（头条号后台 mp.toutiao.com）。
> 核心脚本：`scripts/toutiao_publish.py`（CWD=项目根）。平台约束与改版应对见 `references/platform-specs.md` 与 `references/publish-flow.md`。

---

## 与其他 SKILL 的关系

| SKILL | 定位 |
|---|---|
| **skill-toutiao-publisher（本 SKILL）** | 头条**单平台图文落地发布**：登录、填编辑器、封面、话题、存草稿/发布 |
| skill-cross-platform-publish | 一稿多发的**编排层**，按平台约束改写后委派各平台 publisher（含本 SKILL） |
| skill-content-repurposing | 把一个内容改写成多平台原生形态（头条偏资讯/科普长文） |
| copywriting / article-outline | 制作层，生产头条正文；本 SKILL 只负责发出去 |

---

## 输入

- **必填**：正文文件（Markdown 或纯文本）+ 标题（≤30 字）
- **选填**：正文插图（`--images`，逗号分隔）、封面图、话题标签（≤5 个）、`--draft`（存草稿）

## 输出

- 发布结果 JSON（`platform/title/tags/steps/published/url`），并留痕到 `outputs/_publish/toutiao_<时间戳>.json`
- 真发布成功后建议再跑 `skill-publish-log` 记录、`skill-publish-notify` 通知

---

## 执行步骤

### 一、前置：登录头条号（首次或登录态失效时）

```bash
python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py --login
```

浏览器弹窗扫码，登录态持久化在 `~/.easel-browser-profiles/ToutiaoProfile`（与小红书/知乎/公众号 publisher 同款方案，后续免登录）。

### 二、准备内容

正文与标题由制作层产出，落到 `outputs/<主题>/`（用人类可读主题名，禁 `test`/`xhs` 之类泛名）。头条读者偏资讯与科普，正文按"结论先行 + 小标题分段 + 数据说话"组织，细节见 `references/platform-specs.md`。

**插图**：头条号正文是 ProseMirror 富文本，本地图片路径塞进 `<img src>` 会被清掉，必须让脚本走「工具栏图片按钮 → 本地上传」让平台自己传 CDN。因此图片要通过 `--images` 交给脚本，并在正文里用**独占一行的** `![](路径)` 决定插图位置；正文里没写占位符的图会追加到末尾（头条自动取正文首图作封面）。

```markdown
第一段文字…

![](outputs/我的主题/图1.png)

第二段文字…
```

### 三、先跑 dry-run（默认，不发布）

```bash
python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py \
  --input outputs/主题名/article.md --title "文章标题" --tags "AI,效率工具"
```

dry-run 会把标题/正文/封面/话题/插图填进头条号编辑器就停手，**不点发布**。用这一步确认编辑器定位正常、内容排版无误。

> ⚠️ 头条号**没有「存草稿」按钮，草稿是自动保存的**——所以 dry-run 也会在草稿箱留下一份
> （真机实测：草稿数 3 → 4）。测完记得去草稿箱清理。

### 四、让用户确认标题与封面

把标题、字数、话题、封面、`存草稿 or 直接发布` 展示给用户，**取得明确确认后**才加 `--exec`。

### 五、真发布

```bash
# 存草稿（推荐先存草稿，登录后台复核后再发）
# 头条号草稿自动保存：--draft = 填完就停，等平台自动存进草稿箱，不点「预览并发布」
python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py \
  --input outputs/主题名/article.md --title "文章标题" \
  --tags "AI,效率工具" --cover outputs/主题名/cover.png --exec --draft

# 带插图直接发布
python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py \
  --input outputs/主题名/article.md --title "文章标题" \
  --images outputs/主题名/图1.png,outputs/主题名/图2.png --exec

# 直接发布
python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py \
  --input outputs/主题名/article.md --title "文章标题" --exec
```

**话题**：头条图文没有独立的话题输入框——话题是在正文里打「#话题名」再从联想里选出来的。
脚本会把这几个话题追加到**正文末尾**。平台上不存在的话题选不出来，会被自动撤回（正文不留半截井号）。

### 六、留痕与通知

```bash
python skills/shared/scripts/manifest.py record --topic <主题> --layer publish \
  --skill toutiao-publisher --outputs article.md --summary "已发头条：<标题>"
```

---

## 门禁与安全

- **默认 dry-run**：没有用户对标题/封面/内容的明确确认，不得加 `--exec`。
- **出站内容安全闸门**：真发前扫描标题/正文/话题，命中密钥、内部域名、私网 IP、内部路径等 BLOCK 级内容直接**退出码 7 阻止发布**；AI 措辞等 WARN 级只提醒。dry-run 全部只告警。
- 命中拦截时改稿重发，**不得**用 `--allow-unsafe` 绕过（除非用户明确要求且内容确无敏感信息）。
- 标题超 30 字会被脚本直接拒绝，不发出去让平台截断。

---

## 常见失败

| 现象 | 原因 | 处理 |
|---|---|---|
| `未登录头条号：先跑 --login 扫码` | 登录态过期 | 重跑 `--login` |
| `编辑器定位失败（标题或正文）` | 头条号后台改版 | 按 `references/publish-flow.md` 的选择器表补/调选择器 |
| `以下图片未能插入编辑器` | 工具栏图片入口改版，或图片格式不被接受 | 按 `references/publish-flow.md` 调 `IMAGE_BUTTON_SELECTORS`；或先把图转成 jpg/png 再试 |
| `未看到草稿自动保存提示` | 页面结构变了，或保存被平台拒了 | 去草稿箱核对；必要时先 `--login` 重登 |
| `标题 N 字超过头条图文上限 30 字` | 标题过长 | 精简标题（可保留副标题进正文） |
| 退出码 7 | 内容触发安全闸门 | 删掉敏感信息后重发 |

---

## Profile 感知

有 Easel Profile 时，用 Profile 的账号定位/受众/语气决定标题风格与话题选择，并可用 `skill-persona-check` 做事后一致性检查；无 Profile 时按头条通用图文规范发布，不额外假设账号人设。
