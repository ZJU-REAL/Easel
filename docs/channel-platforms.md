# 渠道平台接入指南（推特 X / 掘金 为参考实现）

> 本文记录向 Easel 接入一个新内容平台需要改哪些地方、有哪些通用坑。
> 以 **推特 X**（窗口登录 + DOM 采集）与 **掘金**（扫码登录 + API 采集）为双参考实现。

## 一、接入清单（按改动顺序）

| # | 位置 | 要做的事 | 参考实现 |
|---|---|---|---|
| 1 | `skills/shared/scripts/web_publisher.py` → `PLATFORMS` | 加平台配置（登录页/发布页/选择器/步骤 DSL） | `twitter-x`、`juejin` |
| 2 | 同文件 `_authenticated_account()` | 有账号接口的平台加一条判定分支（比 DOM 可靠） | 掘金 `user/get` |
| 3 | 同文件 `cmd_selftest()` | 加配置/步骤断言（离线可跑） | `PLATFORMS["juejin"]` 段 |
| 4 | `web/app.py` → `LOGIN_RUNNERS` | 注册平台（`backend`/`wp`/`profile`/`login_window`） | `twitter-x`、`juejin` |
| 5 | `web/app.py` → `MEDIA_REQUIRED` / `VIDEO_ONLY_PUBLISH` | 按平台媒体要求归类 | 掘金均不加（文章可纯文字） |
| 6 | `web/app.py` → `api_publish()` | 特殊发布器才加分支，否则落 `web_publisher` 通用分支 | 两者都落通用分支 |
| 7 | `web/frontend/src/components/PublishPage.tsx` → `PLATFORMS` / `PUBLISHABLE` | 发布中心加卡片（标题/正文字数限制、hint） | `juejin`、`twitter-x` |
| 8 | `skills/shared/scripts/<platform>_stats.py` | 创作数据采集（有 API 优先走 API） | `juejin_stats.py`、`x_stats.py` |
| 9 | `web/app.py` → `ANALYTICS_PLATFORMS` + `_fetch_analytics()` | 接入数据采集 | 两者都已接入 |
| 10 | `tests/` | 配置契约 + 登录/发布/采集行为测试 | `test_twitter_juejin.py`、`test_channel_regressions.py` |

## 二、登录方式三种，选对应配置

```python
# ① 扫码登录（掘金）：登录弹窗里直接有二维码
"login_prep": [{"click": ".login-button"}, {"wait": 2500}],
"login_qr_selector": "img.qrcode-img, [class*=qrcode] img",
"strict_login_qr": True,

# ② 窗口登录（X）：无扫码入口，弹有头浏览器让用户手动登录
"login_mode": "window",
# web 层对应 LOGIN_RUNNERS 里加 "login_window": True → cmd_login_qr 自动加 --headed

# ③ 凭证/API 授权：见 wechat-oa（AppID）或已移除的 youtube-api 历史实现
```

## 三、必须避开的坑（真机踩过）

### 1. headless UA 会触发风控，导致会话被服务端作废

```
现象：窗口登录成功 → 账号页自动校验一次 → 显示「未登录」
根因：headless Chromium UA 含 HeadlessChrome，平台识别为自动化客户端后作废会话
修复：needs_proxy 平台在 headless 时用 _HEADLESS_SAFE_UA（正常 Chrome UA）；headed 不伪装
```

> 任何"登录后会被 headless 校验"的平台都要评估这条。

### 2. 发布前预检不能只看 DOM

```
现象：whoami 已登录，一键发布报「未登录：被重定向到登录页」
根因：编辑器/发布页往往没有 .avatar 这类登录标志元素，login_strict 下即判未登录
修复：预检叠加 _authenticated_account() 权威判定 → API 说已登录就放行
```

### 3. 假成功：服务端拒绝但报成功

```
现象：接口返回 ok:true，内容根本没上线
根因：成功判定只看 URL 变化；拒绝原因只在页面 console（如「摘要不满足最低50字」）
修复：① gone_selector（弹窗必须关闭）② 捕获 console error 并在失败时回显真实原因
```

### 4. Playwright 通用步骤的重 SPA 盲区

| 问题 | 正确写法 |
|---|---|
| `goto` 等 `load` 会超时 | 引擎已统一 `wait_until="domcontentloaded"` + 60s |
| `waitfor` 等 visible 等不到隐藏元素 | 步骤加 `"att": True` → `state="attached"` |
| 自定义 UI 组件标准 click 无效 | 用 `{"action": "js_click"}` |
| 首次进入有引导遮罩 | 加 `"optional": True` 的关闭步骤 |
| Trusted Types CSP 禁止 `innerHTML` | 用全选 + Delete 键，别赋值 innerHTML |

### 5. 平台特定约束（掘金）

- **摘要必填且 ≥50 字** → `_make_summary()` 自动拼接补足（实现取 60 字，上限 100）
- **分类必选**，但 `.category-list .item` 是 `div` 不是 `button`
- **标签输入框被 placeholder 遮挡** → 必须点 `.byte-select__placeholder` 展开下拉
- 标签选完后下拉不收起会盖住确认按钮 → 补 `Escape` + 点击标题收起

## 四、数据采集：优先找平台 JSON 接口

| 平台 | 路径 | 是否需要登录 | 稳定性 |
|---|---|---|---|
| 掘金 | `user_api/v1/user/get`（账号概览，含 `follower_count`） | 需 cookie | 高 |
| 掘金 | `content_api/v1/article/query_list`（文章级阅读/赞/评/藏） | **免登录** | 高 |
| X | 个人主页 DOM（关注者/帖子数/推文级赞转评看） | 需登录 | 中（官方 API 免费层已取消） |

**读登录 cookie 的正确姿势**：Chromium 的 cookie 是加密的，手工读 SQLite 只能拿到空值。
用 Playwright 的 `context.request` 让 Chromium 自己解密并带上 cookie：

```python
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(profile, headless=True, **launch_kwargs)
    resp = ctx.request.get("https://api.example.com/me")   # 自动带登录 cookie
```

## 五、国际站（需代理）额外配置

```python
"needs_proxy": True,                      # 走代理而非直连
"login_navigation_timeout_ms": 30000,     # 代理冷启动 + 重 SPA，默认 10s 不够
```

代理读取链（从高到低）：
`EASEL_PROXY` → `<PLATFORM>_PROXY` → `.env` 的 `EASEL_PROXY` → `https_proxy` → `all_proxy`

**用户侧配置**：设置页 → 更多设置 → 网络代理，填 `http://127.0.0.1:7890` 即可，保存即生效。

> 国内平台（知乎/掘金/快手等）不受影响：Chromium 层强制 `--no-proxy-server` 直连。

## 六、验收要点

1. `python skills/shared/scripts/web_publisher.py selftest` 全绿
2. `python skills/shared/scripts/web_publisher.py plan --platform <pf> --title T --desc D` 步骤正确
3. 账号页点「登录」→ 状态从 `starting` → `qr_ready`/`window_login` → `success`
4. 发布中心发一条测试内容 → **用平台侧证据核实**（文章列表/帖子数变化），不要只信接口返回
5. `curl /api/analytics/<pf>` 输出字段完整
6. 跑 `pytest tests/test_twitter_juejin.py tests/test_channel_regressions.py`

## 七、移除一个平台时的清理清单

（YouTube 移除时用到的完整步骤，供参考）

- [ ] `web_publisher.PLATFORMS` 配置块 + `cmd_selftest` 断言
- [ ] `web/app.py`：`LOGIN_RUNNERS`、`_account_logged_in`、`_start_login`、`_check_account_whoami`、
      `api_publish` 分支、`MEDIA_REQUIRED`/`VIDEO_ONLY_PUBLISH`/`ANALYTICS_PLATFORMS`、`ANALYTICS` 分发
- [ ] 前端：`PublishPage` 平台卡与集合、`AccountsPage` 注释、`api.ts` 类型
- [ ] 独立脚本文件
- [ ] `.env` 相关凭据
- [ ] 运行时数据：`~/.easel-browser-profiles/<Pf>Profile`、`outputs/_login/<pf>.*`
- [ ] 测试文件与 README 平台列表
- [ ] 重启服务确认 `/api/accounts`、`/api/analytics/platforms` 不再包含
