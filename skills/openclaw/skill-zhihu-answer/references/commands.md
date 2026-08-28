# skill-zhihu-answer 命令速查

脚本 CWD = **项目根**（用 `cd <项目根> &&` 前缀；见 AGENTS.md「跑脚本铁律」）。

## 0. 环境 & 登录检查

```bash
python skills/shared/scripts/zhihu_answer.py --selftest              # 脚本自测（不启浏览器）
python skills/shared/scripts/account_stats.py check                  # playwright 环境
python skills/shared/scripts/web_publisher.py whoami --platform zhihu # 知乎登录态
```

## 1. Dry-run 预检（不发布）

```bash
python skills/shared/scripts/zhihu_answer.py \
    --question "https://www.zhihu.com/question/XXXXX" \
    --content-file "outputs/<主题>/answer.md"
```

输出示例：
```
[DRY-RUN] 将回答问题：有什么惊悚的恐怖小故事吗？
[DRY-RUN] 回答字数：1284 字
{"success": true, "url": "...", "dry_run": true}
```

## 2. 正式发布

```bash
python skills/shared/scripts/zhihu_answer.py \
    --question "https://www.zhihu.com/question/XXXXX" \
    --content-file "outputs/<主题>/answer.md" \
    --exec
```

## 3. 有头模式（调试/首次校验）

```bash
python skills/shared/scripts/zhihu_answer.py \
    --question "https://www.zhihu.com/question/XXXXX" \
    --content-file "outputs/<主题>/answer.md" \
    --exec --headed
```

## 4. 检查问题可答状态（批量，临时脚本逻辑）

```python
from playwright.sync_api import sync_playwright
from pathlib import Path

PROFILE_DIR = Path.home() / ".easel-browser-profiles" / "ZhihuProfile"

def check(url):
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=True,
              args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)
        has_write = page.locator(".WriteAnswerButton").count() > 0
        already = page.evaluate(
            "() => Array.from(document.querySelectorAll('button')).some(b => b.innerText.trim()==='编辑回答')")
        ctx.close()
        return {"can_answer": has_write and not already, "already_answered": already}
```

## 5. 发布后留痕

```bash
python skills/shared/scripts/persona_gate.py record \
    --topic <主题> --profile <画像> --score <评分> --verdict pass

python skills/openclaw/skill-publish-log/scripts/log.py record \
    --platform 知乎 --title <问题标题> --profile <画像> \
    --persona-score <评分> --persona-verdict pass --skill-source zhihu-answer
```

## 6. 搜热门问题（参考脚本逻辑）

```python
import re
page.goto(url, wait_until="domcontentloaded", timeout=20000)
page.wait_for_timeout(2000)
m = re.search(r'(\d[\d,]*)\s*个回答', page.inner_text("body"))
ans_count = int(m.group(1).replace(',', '')) if m else 0
has_write = page.locator(".WriteAnswerButton").count() > 0
```

> 注：`wait_until="networkidle"` 更准但更慢；批量检查用 `domcontentloaded` + 2s wait 效率更高。
