# 微信公众号（WeChat OA）接入 —— 架构与使用说明

> 本文件说明把「微信公众号」作为一个发布/数据平台接进 Easel 的**账号页 / 发布中心 / 数据中心**的实现。
> 默认走「公众号后台扫码会话」，**免 AppID/AppSecret、免 IP 白名单**；官方开发者 API 作为可选回退。

---

## 0. 一句话总览

公众号能力已端到端接进 Easel，**默认走「公众号后台扫码会话」**（管理员级会话，Playwright 驱动 `mp.weixin.qq.com`）：

- **免 AppID/AppSecret、免 IP 白名单**，未认证号也能用；
- 官方开发者 API（AppID/AppSecret + 出口 IP 白名单）保留为 `--official-api` 回退，前端 UI 默认隐藏。

平台标识 `wechat-oa`，web 默认 `:7860`，OpenClaw gateway 端口由 OpenClaw 自行分配（`easel` profile → `37289`，非 `18789`），Easel 自动解析。

---

## 1. 核心引擎：`skills/shared/scripts/weixin_mp_stats.py`

用**扫码会话**操作 mp 后台。四个子命令，默认直连（`mp.weixin.qq.com` 为国内站）；受限网络可用
`--proxy`（或环境变量 `EASEL_PROXY` / `https_proxy`）指定正向代理：

- **`login`**：Playwright 打开 `mp.weixin.qq.com` 出二维码 → 管理员微信扫码 → 会话持久化到浏览器
  profile `~/.easel-browser-profiles/WeixinMpProfile`。
  - 关键实现点：`goto(wait_until="commit")`（等 `domcontentloaded` 可能超时）；二维码要等
    `img[src*='qrcode']` 真正渲染（`naturalWidth>10`）再截图，否则截出白图。
- **`stats`**：拦截页面自然发出的数据 XHR（不自己拼易变参数）：`appmsgpublish`（发表记录：
  total/publish/masssend count + 文章列表 title/link/cover）+ `get_article_stat_tendency`
  （近 30 天阅读/分享 read_uv/share_uv）。输出与 `account_stats.py` 一致的统一 dict。
- **`publish`**：`--html --cover --title [--digest --author]`。流程：打开编辑器抽 `ticket`/`user_name`
  → `filetransfer?action=upload_material`（传封面，返回 media_id）→ 正文 `<img src>` 本地图走
  `uploadimg2cdn` 传 mp CDN 并替换 → `operate_appmsg?sub=create`（建草稿）。返回 `{success, media_id}`。
- **`whoami`**：读会话是否有效。

---

## 2. 发布器：`skill-wechat-publisher/scripts/publish.py`（默认会话式）

- **默认走会话**：保留其 AI 味 gate + 多套主题排版 + 贴图模式，只把最后的「传图 + 建草稿」换成会话
  （内部调 `weixin_mp_stats.py publish`，见 `_session_publish_html()` + `session_mode` 参数，默认 `True`）。
- `--official-api` 回退到官方 HTTP API（`draft/add`，需 `app_id`/`app_secret` + 出口 IP 加白名单）。
- `--input`(Markdown) 与 `--html` 两种入口都默认会话式。

---

## 3. Web 后端 `web/app.py`（backend 类型 `wechat-oa`）

- 平台注册：`LOGIN_RUNNERS["wechat-oa"] = {"name": "微信公众号", "backend": "wechat-oa"}`。
- **登录（扫码）**：`POST /api/accounts/wechat-oa/mp-login`（起 `weixin_mp_stats.py login`，出二维码到
  `outputs/_login/wechat-oa-mp.png`，状态写 `wechat-oa-mp.json`）+ `GET .../mp-login/status`（轮询）。
- **登录态判定**：`_account_logged_in` / `whoami` 对 wechat-oa **以 mp 会话为准**
  （`wechat-oa-mp.json` state==success）；AppID 凭证仅作旧配置兜底。
- **退出**：`api_logout` 清 AppID 凭证 + 停后台登录进程 + 删 `wechat-oa-mp.json`/png/log + 删
  `WeixinMpProfile`（真正退登）。
- **发布**：`api_publish` 的 `wechat-oa` 分支 → 检查 mp 会话已登录 → 正文 MD 写临时文件 →
  `html_converter.py` 转公众号 HTML → `weixin_mp_stats.py publish`（会话）。
- **数据中心**：`api_analytics` 的 `wechat-oa` 分支 → `weixin_mp_stats.py stats`。`ANALYTICS_PLATFORMS` 含 `wechat-oa`。
- **凭证端点**（AppID，UI 默认隐藏，保留兼容）：`GET/POST /api/accounts/wechat-oa/credentials`。

代理：以上调用默认直连；若设了 `EASEL_PROXY` / `https_proxy` 则通过其转发（供受限网络使用）。

---

## 4. 前端 `web/frontend/src/`

- `components/AccountsPage.tsx`：公众号卡片与其它平台**统一**——单个「登录」按钮 → `handleMpLogin`
  （扫码，mp 会话）；成功后内存态即时翻转为已登录并刷新（`effLoggedIn` 对 wechat-oa 以后端登录态为准，
  避免浏览器缓存把已登录盖成未登录）；切回标签页会自动重新校验。AppID 表单代码保留但不在 UI 露出。
- `components/ProfilePage.tsx`：「平台运营」维度加「📊 抓取公众号数据」按钮，复用数据中心同一 stats
  接口，把粉丝量级/内容形式写进 `platforms.md`（幂等，注释围栏包裹，抓完直接落盘）。
- `lib/api.ts`：`startMpLogin` / `mpLoginStatus` / `getCredentials` / `saveCredentials`；`request()`
  统一 `cache: 'no-store'`（避免登录态等动态接口被浏览器 HTTP 缓存）。
- `components/PublishPage.tsx`：平台列表含「公众号」（正文上限 20000，需封面图，非视频）。
- `components/DashboardPage.tsx`：数据中心平台选择器含公众号；wechat-oa 在「跳过浏览器 whoami 校验」集合里。
- 改前端后需 `cd web/frontend && npm run build` 再重启 web。

---

## 5. 网络说明

| 用途 | 默认出口 |
|---|---|
| 公众号后台会话（登录/发布/取数） | **直连**（受限网络设 `EASEL_PROXY` / `https_proxy` 走正向代理） |
| 官方 API 发布（`--official-api` 回退） | 直连；若公众号开了 IP 白名单，需保证出口 IP 固定并加白（可用 `scripts/wechat-egress.sh` 起固定出口代理，见脚本注释） |

> 会话式发布**不依赖固定出口 IP**（无需白名单），是默认主路径。仅当改用官方 API 且公众号启用了
> IP 白名单时，才需要固定出口。

---

## 6. 启动 / 使用

```bash
# web（受限网络时按需 export EASEL_PROXY / https_proxy）
easel web --port 7860

# gateway
bash scripts/gateway.sh restart
```

**使用流程**：账号页「登录」扫码（管理员微信）→ 发布中心选公众号，填标题/正文/封面 → 发草稿箱 →
数据中心看发表记录/阅读。会话过期就在账号页重新扫码。

---

## 7. 注意事项 / 已知限制

- 会话为**管理员级**，会过期；文章只发**草稿箱**，不自动群发（群发需在 mp 后台确认）。
- 数据抓取依赖后台页面 XHR 结构，mp 后台改版时可能需要跟进调整选择器/接口。
- 官方 API 回退需在公众平台配置 `app_id`/`app_secret`，并把出口 IP 加进「IP 白名单」（错误码 40164）。
- 用户凭证文件 `skills/builtin/skill-wechat-publisher/wechat-publisher.yaml` 已在 `.gitignore`，
  仓库只提供 `wechat-publisher.yaml.example` 模板。

---

## 8. 关键文件清单

- `skills/shared/scripts/weixin_mp_stats.py` —— 会话引擎（login/whoami/stats/publish）
- `skills/builtin/skill-wechat-publisher/scripts/publish.py` —— 发布器（默认会话，`--official-api` 回退）
- `skills/builtin/skill-wechat-publisher/SKILL.md` —— skill 说明
- `web/app.py` —— 后端端点（mp-login / publish / analytics / logout / credentials）
- `web/frontend/src/components/{AccountsPage,ProfilePage,PublishPage,DashboardPage}.tsx`、`lib/api.ts`
- `scripts/wechat-egress.sh` —— 固定出口代理（仅官方 API + IP 白名单场景需要）
