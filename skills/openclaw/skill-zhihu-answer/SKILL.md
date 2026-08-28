---
name: skill-zhihu-answer
description: >-
  知乎问答回答发布：在知乎问题下发布原创回答——搜热门问题、检查可答性、写内容、
  Playwright 发布（绕 header 遮挡 + JS 遍历发布按钮）。当用户说"回答知乎问题""在知乎问答下回答"
  "发知乎回答""知乎答题""帮我回答这个知乎问题""批量回答知乎"时使用。与 skill-zhihu-publisher
  区别：那个发**专栏文章**（zhuanlan），本 SKILL 专发**问答区的回答**；回答内容写作用制作层 SKILL
  （novel-writer / copywriting）。
layer: publish
---

# skill-zhihu-answer（发布层 · 知乎问答回答）

> 在知乎问答帖子下发布原创回答：搜索热门问题 → 检查可答性 → 调用制作层 SKILL 写内容 → Playwright 发布。
> 核心脚本：`skills/shared/scripts/zhihu_answer.py`（CWD=项目根）。命令速查见 `references/commands.md`。

---

## 与其他 SKILL 的区别

| SKILL | 定位 |
|---|---|
| **skill-zhihu-answer（本 SKILL）** | 知乎问答帖的**回答发布**：搜题 + 写内容 + 发布 |
| skill-zhihu-publisher | 知乎**专栏文章**（zhuanlan）发布，非问答回答 |
| skill-cross-platform-publish | 一稿多发，多平台分发 |
| novel-writer / copywriting | 制作层，生产回答正文；本 SKILL 调用它 |

---

## 核心流程

```
1. 搜索热门问题（可选，或用户直接给 URL）
      ↓
2. 检查可答状态（未答过 + WriteAnswerButton 存在）
      ↓
3. 制作层写内容（用 novel-writer / copywriting SKILL，或用户自备文本）
      ↓
4. 发布前人设检查（有 Profile 时）
      ↓
5. zhihu_answer.py --exec 发布
      ↓
6. 发布后留痕（persona_gate record + publish-log record）
```

---

## Step 1：搜索热门问题（可选）

用已登录的 ZhihuProfile 搜索问题，直接访问候选页取真实回答数（搜索结果元数据不准）：

```python
page.goto("https://www.zhihu.com/search?type=question&q=<关键词>", wait_until="networkidle")
# 直接访问候选问题页取真实数据
page.goto("<问题URL>", wait_until="domcontentloaded")
import re
m = re.search(r'(\d[\d,]*)\s*个回答', page.inner_text("body"))
ans_count = int(m.group(1).replace(',', '')) if m else 0
```

> `zhihu_answer.py` 目前不含搜索功能，搜索用临时脚本或用户直接给 URL（逻辑见 `references/commands.md` §6）。

---

## Step 2：检查可答状态

```python
has_write = page.locator(".WriteAnswerButton").count() > 0
already_answered = page.evaluate("""
    () => Array.from(document.querySelectorAll('button'))
               .some(b => (b.innerText||'').trim() === '编辑回答')
""")
can_answer = has_write and not already_answered
```

> ⚠️ 每个用户在同一问题只能回答一次。已答的问题显示「编辑回答」而非「写回答」。
> 对已答问题不要重复发布，否则进入编辑旧答案流程（发布按钮变为「提交修改」）。

---

## Step 3：制作层写内容

回答正文属于制作层，**用制作层 SKILL 写**（`novel-writer` 或 `copywriting`），也可用用户提供的文本。
内容存为 `outputs/主题名/answer_<问题ID>.md`。

写作要点（恐怖/悬疑题材示例）：第一人称、冷静克制、暗示>直白；短段落多换行适配手机；
开篇 500 字内建立世界观 + 第一个恐怖节点；文末加"本故事纯属虚构"。

---

## Step 4：发布前人设检查

```bash
cd <项目根> && python skills/shared/scripts/persona_gate.py check --score <评分>
# 始终退出码 0；低于 80 分时告知偏离点，但不阻断用户发布
```

---

## Step 5：发布命令

```bash
# Dry-run 预检（默认，不真正发布）
cd <项目根> && python skills/shared/scripts/zhihu_answer.py \
    --question <问题URL> --content-file <回答内容.md>

# 正式发布
cd <项目根> && python skills/shared/scripts/zhihu_answer.py \
    --question <问题URL> --content-file <回答内容.md> --exec

# 调试模式（有头浏览器，首次校验选择器时用）
cd <项目根> && python skills/shared/scripts/zhihu_answer.py \
    --question <问题URL> --content-file <回答内容.md> --exec --headed
```

---

## 核心实现：三策略点击「写回答」

> **根本原因**：知乎顶部 `<header class="AppHeader">` 覆盖「写回答」按钮，Playwright 常规
> `.click()` 因 pointer event 被拦截而 30s 超时。必须绕过覆盖层。

```
策略1: btn.dispatch_event("click")          ← 绕过 header，多数页面有效
策略2: React 完整事件序列（mousedown+mouseup+click，dispatchEvent bubbles）
策略3: btn.focus() + keyboard.press("Enter") ← 最可靠降级，焦点触发 React 事件
```

每策略后检查 `.public-DraftEditor-content` 是否出现，出现即成功，否则进入下一策略。

---

## 核心实现：点击「发布回答」按钮

> **根本原因**：内容输入后按钮可能滚出视口，`wait_for(state="visible")` 超时；且同页有
> 「发布设置」与「发布回答」两个含「发布」的按钮，需精确匹配「发布回答」。

```javascript
// JS 遍历全部 button，不依赖视口可见性
const pub = Array.from(document.querySelectorAll('button'))
    .find(b => (b.innerText || '').trim().includes('发布回答'));
if (pub) { pub.scrollIntoView({block:'center'}); pub.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window})); }
```

降级：`locator("button:has-text('发布回答')").wait_for(state="attached")` + `scroll_into_view_if_needed()` + `dispatch_event("click")`。

---

## Step 6：发布后留痕

```bash
cd <项目根> && python skills/shared/scripts/persona_gate.py record \
    --topic <主题> --profile <画像> --score <评分> --verdict <pass|warn>

cd <项目根> && python skills/openclaw/skill-publish-log/scripts/log.py record \
    --platform 知乎 --title <问题标题> --profile <画像> \
    --persona-score <评分> --persona-verdict <结论> --skill-source zhihu-answer
```

---

## 批量发布多个问题

1. 列出问题 URL + 对应内容文件；2. 批量检查可答状态；3. 制作层**写完全部内容再发布**（避免写一篇发一篇的上下文碎片化）；4. 逐题**串行**发布（同一浏览器 Profile 不并发）；5. 每题间隔约 30 秒降低风控。

---

## 已知限制与风险

| 问题 | 说明 |
|---|---|
| 同一问题只能回答一次 | 检查 `can_answer` 过滤，已答的跳过 |
| 知乎 Draft.js 编辑器 | 只支持纯文本段落，Markdown `**加粗**` 不渲染、会原样显示星号 |
| header 遮挡 | 已通过 dispatch_event 三策略绕过 |
| 发布按钮视口外 | 已通过 JS 遍历 + scrollIntoView 绕过 |
| 反爬风控 | 用 `--disable-blink-features=AutomationControlled`；发布间隔 ≥ 30s |
| 登录态 | 读 `~/.easel-browser-profiles/ZhihuProfile`；未登录时输出 `未登录知乎` 并退出 |

---

## 依赖与验证

```bash
python skills/shared/scripts/zhihu_answer.py --selftest              # 脚本自测（不启浏览器）
python skills/shared/scripts/account_stats.py check                  # playwright 环境
python skills/shared/scripts/web_publisher.py whoami --platform zhihu # 知乎登录态
```
