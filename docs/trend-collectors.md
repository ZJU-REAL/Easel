# 热点数据源接入

Easel 的“看热点 / 热点雷达”通过标准协议支持用户自定义来源，不依赖不断增加内置平台。现有六个平台迁移到相同机制，没有增加新的默认内置平台。支持三种数据源：按需执行的 Python 脚本、已经运行的 HTTP 服务，以及直接订阅的 RSS/Atom Feed。Python 与 HTTP 返回同一份 v1 JSON，RSS/Atom 由 Easel 转换为同一结构。自定义网站、数据库或浏览器的采集逻辑由采集器自行实现；Easel 负责调用、校验、去重、缓存和展示，并支持收藏到选题库和继续创作。

六个内置平台（微博、抖音、知乎、B站、百度、头条）同样通过 Python 子进程协议运行，不再在 Web 后端里直接抓取。它们共用 `easel/trends/builtin.py`，通过平台参数区分，上游字段适配和主备源切换保留在采集器中。

## 1. 通过页面选择或编写 Python 脚本

热点雷达右上角点击“数据源”，选择“Python 脚本”。代码区自动填入包含 `collect()` 入口、`main()` 出口、v1 JSON 返回、stderr 日志和退出码约定的完整示例。可以直接改写示例，也可以点“选择 .py 文件”导入本地 UTF-8 脚本后编辑；不需要先登记文件。

点击“保存并启用”会先在受限工作进程中校验语法，校验期间不执行代码。通过后保存到配置目录旁的私有 `trend-collectors/`，使用服务端生成的文件名并注册来源。浏览器不决定写入路径、解释器或命令。首次热点查询按配置运行脚本；选择文件本身不会执行。脚本最多 64 KiB。删除该来源只清理平台保存的副本，不删除用户原始文件；保存失败会清理未注册副本。

脚本仍以当前服务账号运行，保存并启用代表本机操作者授权执行。资源限制不是完整安全沙箱；未知恶意脚本应部署到隔离服务后通过 HTTP 接入。

页面保存的是脚本副本，不会自动上传同目录的数据文件、依赖包或虚拟环境。额外依赖需由服务端环境提供；多文件采集器可使用已有 HTTP 服务，或按下文手工指定本地脚本路径。上传副本的工作目录是服务端副本所在目录，不是浏览器原始文件目录。

也可以手工配置：

在项目根目录执行（使用启动 Easel 的 Python，虚拟环境下可替换为 `.venv/Scripts/python.exe`）：

```powershell
python -X utf8 examples/trends/python_collector.py
Copy-Item config/trend-sources.example.json config/trend-sources.json
```

Linux/macOS 的复制命令为：

```bash
cp config/trend-sources.example.json config/trend-sources.json
```

打开热点雷达，或点“刷新”，会出现“我的 Python 热点”。该例只生成一条**演示数据**，没有访问真实平台。将示例中的 `collect()` 换成自己的采集逻辑即可。示例不依赖 Easel 包，也不需要额外安装依赖。

本地配置 `config/trend-sources.json` 已被 Git 忽略。配置文件每次查询时重新读取，修改后刷新页面即可，无须重启。修改 `.env` 中的数据源变量后也会在下一次请求时读取；通过操作系统设置环境变量则需要重启服务以继承变量。

也可以在项目 `.env` 中指定其他配置文件：

```dotenv
EASEL_TREND_SOURCES_CONFIG=config/trend-sources.json
```

这个路径相对 Easel 项目根目录解析，也支持绝对路径。显式指定但文件不存在时会报错，避免悄悄退回内置源。

## 2. Python 数据源配置

```json
{
  "version": 1,
  "include_builtin": true,
  "sources": [
    {
      "id": "my-news",
      "label": "我的行业资讯",
      "type": "python",
      "script": "../collectors/news.py",
      "python": "../collectors/.venv/Scripts/python.exe",
      "args": ["--category", "technology"],
      "env": {"NEWS_API_KEY": "${MY_NEWS_TOKEN}"},
      "default": true,
      "timeout_seconds": 20,
      "refresh_seconds": 300,
      "max_stale_seconds": 86400
    }
  ]
}
```

规则：

- `script` 和带路径分隔符的 `python` **相对配置文件所在目录**解析，支持绝对路径；`python` 也可以是 PATH 中的解释器名称。省略 `python` 时使用启动 Easel 的解释器。Linux/macOS 的虚拟环境通常为 `.venv/bin/python`。
- 每个数据源可以使用独立虚拟环境。请自行安装依赖，Easel 不会在查询时执行 pip 或修改自身依赖。
- 脚本工作目录为脚本所在目录。执行形式为 `python -X utf8 script.py ...args`，不经过 shell，不接受 shell 命令串。
- 脚本默认只继承运行、代理和证书相关变量，不再继承整个后端环境。用 `env` 显式传入需要的变量；`${NAME}` 可引用后端环境或项目 `.env` 中的值，未设置会返回 `missing_environment`。不会执行变量值中的命令，也不递归展开变量。聊天 API Key 等无关凭据不会自动传给脚本。
- Easel 注入 `EASEL_TREND_SOURCE_ID`，脚本可以读取当前数据源 ID。查询条数不会作为脚本参数注入：采集结果先缓存，展示时再截取。
- stdout 必须只有一份完整 UTF-8 JSON；日志写 stderr。退出码 0 表示成功，非零表示失败。**真实采集失败应抛异常或非零退出，不要伪装成 `items: []`**。
- 脚本按需启动，输出后退出。HTTP 查询不会等待常驻脚本提供接口；需要长期保持登录态或复用浏览器时，使用下节的 HTTP 服务。

## 3. HTTP 数据源配置

运行可直接测试的本地示例（保持此终端运行）：

```powershell
python -X utf8 examples/trends/http_service.py --port 8766
```

将 `config/trend-sources.json` 中 `my-http` 的 `enabled` 改成 `true`，刷新热点雷达即可。Easel 只请求服务，不负责启动或守护 HTTP 服务。

已有采集服务可按下面方式接入：

```json
{
  "id": "team-news",
  "label": "团队行业热点",
  "type": "http",
  "url": "https://collector.example.com/trends",
  "method": "POST",
  "headers": {"Authorization": "Bearer ${TEAM_TREND_TOKEN}"},
  "body": {"category": "technology", "limit": 100},
  "default": true,
  "timeout_seconds": 10,
  "refresh_seconds": 600,
  "max_stale_seconds": 86400
}
```

- 将这个对象放入配置的 `sources` 数组。支持 GET（默认）和 POST；POST 的 `body` 按 JSON 编码，GET 不允许带 body。
- 响应需为 HTTP 200 类成功状态，响应体是下节的 v1 JSON，不再额外包装 `data`。`http` 类型不接收 HTML 或 XML；RSS/Atom 请使用 `rss` 类型。
- URL 仅允许 HTTP(S)，不能包含 `user:password@host`。鉴权使用 `headers`，凭据建议保存在 `.env` 或环境变量，通过 `${NAME}` 引用。
- HTTP 3xx 重定向视为失败，不会跟随跳转或把鉴权头转发到其他地址；配置最终服务地址。
- 支持内网和 localhost；默认绕过 localhost 代理。请求遵循 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`，没有对应代理时使用 `EASEL_PROXY`。HTTP 源也可通过自己的 `env` 设置覆盖代理变量。
- 本地示例可用 `DEMO_TREND_TOKEN` 开启 Bearer 鉴权；随后配置 `Authorization: Bearer ${DEMO_TREND_TOKEN}`。示例仅用于开发验证，生产服务的部署与访问控制由服务维护者负责。

### 直接订阅 RSS / Atom

无需写脚本或部署转换服务，在 `sources` 数组中增加：

```json
{
  "id": "industry-feed",
  "label": "行业订阅",
  "type": "rss",
  "url": "https://your-site.example/feed.xml",
  "headers": {},
  "default": true,
  "timeout_seconds": 10,
  "refresh_seconds": 900,
  "max_stale_seconds": 86400
}
```

- 支持 RSS 2.0、RSS 1.0（RDF）和 Atom 1.0；使用 GET 请求，和 HTTP 数据源共用鉴权头、环境变量、代理、超时和响应大小限制。示例配置里的 `my-rss` 默认禁用，请替换真实订阅地址后启用。
- RSS `guid` / Atom `id` 转为稳定 ID，标题转为 `title`，文章链接转为 `url`，RSS `pubDate` / Dublin Core `date` / Atom `published`（无值时 `updated`）转为 `published_at`。
- 相对链接与 Atom `xml:base` 会解析成绝对地址；无文章链接但 RSS guid 是永久 HTTP(S) 地址时可作为链接。非 HTTP(S) 链接不会成为可点击地址。
- 发布时间缺失、无时区或无法识别时保留为 null；没有标题的条目跳过。没有热度的订阅保持空热度，不人为生成排名分数。保留 Feed 原有顺序，最多接收前 500 条有效条目。
- `fetched_at` 是 Easel 本次成功读取订阅的时间，文章本身的新旧看 `published_at`。Feed 空列表属于采集成功，无法解析的 XML 属于失败，会按缓存规则回退。
- 不执行 Feed 中的 HTML，也不加载 DTD 或外部实体；没有额外安装依赖。与 HTTP 源相同，不自动跟随重定向，请填写最终订阅地址。

仓库也提供了 [演示 Feed](../examples/trends/feed.xml)，可以完全在本地验证：

```powershell
python -m http.server 8767 --bind 127.0.0.1 --directory examples/trends
```

将示例配置 `my-rss` 的 `url` 改为 `http://127.0.0.1:8767/feed.xml`，并设置 `enabled: true`。刷新热点雷达即可看到一条演示订阅。演示文章的发布时间是固定值，采集时间是本次读取时间。

## 4. 统一数据协议 v1

Python stdout 与 HTTP 响应体完全一致：

```json
{
  "version": 1,
  "fetched_at": "2026-10-29T10:00:00+08:00",
  "items": [
    {
      "id": "topic-123",
      "title": "热点标题",
      "url": "https://example.com/topics/123",
      "published_at": "2026-10-29T09:00:00+08:00",
      "heat": {"value": 123456, "text": "12.3万", "unit": "阅读"}
    }
  ]
}
```

| 字段 | 规则 |
|---|---|
| `version` | 必填，整数 `1` |
| `fetched_at` | 必填，带时区的 ISO 8601 采集时间；上游有缓存时填写真实采集时间，不能用接口请求时间冒充；比当前时间超前 5 分钟以上会被拒绝 |
| `items` | 必填数组，允许为空，最多 500 条；输出顺序就是榜单顺序 |
| `items[].id` | 可省略；建议提供数据源内稳定 ID。省略时按 URL（无 URL 则标题）生成稳定哈希；同一数据源内重复 ID 保留第一条，不跨源去重 |
| `title` | 必填非空字符串，最长 1000 字符 |
| `url` | 可省略、空字符串或 null；有值时必须是无内嵌凭据的 HTTP(S) 链接 |
| `published_at` | 可省略或 null；有值时必须为带时区的 ISO 8601 时间 |
| `heat` | 可省略；对象中 `value` 是有限数值或 null，`text` / `unit` 为字符串，均可省略 |

`heat.text` 用于展示；缺失时展示 `heat.value`。不同平台的 `value` 和 `unit` 含义可能不同，Easel 不做跨平台热度排名。额外字段会被忽略；已定义字段类型错误时整批拒绝，避免错误结果污染缓存。

最小合法输出：

```json
{"version": 1, "fetched_at": "2026-10-29T02:00:00Z", "items": [{"title": "我的热点"}]}
```

此处时间仅为格式示例，运行时请生成真实时间。完整实现见 [Python 示例](../examples/trends/python_collector.py) 和 [HTTP 示例](../examples/trends/http_service.py)。

## 5. 数据源管理与缓存

| 配置项 | 默认值 / 说明 |
|---|---|
| `version` | 配置根对象必填，整数 `1` |
| `include_builtin` | 默认 `true`；设为 `false` 只使用自定义源 |
| `id` | 小写字母、数字、下划线、连字符，1–64 字符，首字符须为字母或数字 |
| `label` | 展示名称，必填，最多 80 字符 |
| `enabled` | 默认 `true`；设为 `false` 禁用源，只需提供 `id` 和 `enabled` |
| `default` | 自定义源默认 `true`；决定首页和热点雷达初次打开时是否选中 |
| `timeout_seconds` | 默认 20，范围 0.1–120 秒；采集工作进程有额外 2 秒启动/清理预算，超时终止 |
| `memory_mb` | 默认 256，范围 64–512 MiB；Windows 为整个采集进程树的提交内存上限，Linux 同时限制地址空间和进程组 RSS，macOS 使用进程组 RSS 看门狗（不依赖不可靠的 RLIMIT_AS） |
| `refresh_seconds` | 默认 300，范围 1–86400 秒；按需查询的缓存间隔，不是后台定时任务 |
| `max_stale_seconds` | 默认 86400，不能小于刷新间隔，最多 604800；按 `fetched_at` 计算结果可保留多久 |

`sources` 最多 64 项，不允许重复 ID。自定义项与内置同 ID 时**完整替换**该项配置；内置 ID 为 `weibo`、`douyin`、`zhihu`、`bilibili`、`baidu`、`toutiao`。例如：

```json
{
  "version": 1,
  "include_builtin": true,
  "sources": [{"id": "weibo", "enabled": false}]
}
```

内置源默认选中微博、抖音、知乎。前端动态读取列表，无需为新增来源改 React 代码。配置改动、脚本文件改动、环境变量改动会使对应缓存失效。缓存仅存在当前后端进程内，重启会清空；多个服务进程各自缓存。

同一源并发请求复用采集，整个后端同时最多执行 4 个采集器。超额请求短暂等待后返回 `busy`，页面稍后自动重试，不会无界排队。普通失败最多等待 30 秒重试（刷新间隔更短则遵循刷新间隔）；忙状态 1 秒后可重试。stdout、stderr 和 HTTP 响应各限制为 2 MiB，超限拒绝。不要输出大量日志。配置文件最多 128 KiB，内存缓存按 16 MiB 序列化预算和最多 96 项限制淘汰。

接口状态：

- `fresh`：成功且数据未过期；空数组也属于成功。
- `stale`：数据超过刷新间隔，或本次采集失败，暂时使用仍在最大保留时间内的旧结果。返回真实 `fetched_at`，页面标明过期缓存。
- `error`：没有可用结果或已超过最大保留时间；返回空列表和明确的错误码。

Easel 不把脚本 stderr、HTTP 响应错误正文或原始异常透传给浏览器，避免泄露鉴权信息。排错时可用同一解释器、参数、环境在本地直接运行脚本。

## 6. 前端查询接口与边界

```text
GET /api/trends/sources
GET /api/trends
GET /api/trends?platforms=my-news,team-news&limit=15
```

源发现接口只返回 `id`、`label`、`type`、`default`、`refresh_seconds`；不返回脚本路径、命令、请求头或密钥。查询接口保留 `platforms` 参数兼容原有调用，省略时使用默认源，空字符串表示不选择源；未知 ID 会被忽略，重复 ID 只查询一次。`limit` 限制在 1–30。

结果保留原有 `platform`、`label`、`items`、`ok`、顶层 `updated` 字段，条目保留展示用 `hot`。新增顶层 `version`、分组 `status`、`stale`、`fetched_at`、`last_attempt_at`、`error`，条目新增 `id`、`heat`、`published_at`。`ok` 表示存在未超最大保留时间的成功结果，成功空数组也是 true；`updated` 仅表示本次查询时间。

单条来源配置无效会被跳过并提示，不影响其余来源；整个配置无法读取时返回空列表与 `warnings`，不执行无法确认的配置。单个采集器失败不影响其他源，错误在对应分组中返回。数据源管理保存失败会返回 400/409，原文件保留。

本机制用于由部署者管理配置的本地/私有部署。所有网络响应解析和 Python 采集都在短生命周期工作进程中完成。Windows 在工作进程执行前绑定 Job Object，限制整个进程树的内存、CPU 时间与最多 8 个活动进程，并在结束时回收子孙进程；建立限制失败时拒绝执行，不无保护降级。Linux/macOS 使用进程组清理、CPU/文件输出限制和进程组 RSS/进程数监测。Linux 额外设置地址空间上限；macOS 不调用兼容性不稳定的 RLIMIT_AS。已有更严格的系统硬限制会被保留。POSIX 进程组不等同于 cgroup 或容器，不能保证恶意主动脱离会话的程序被完整约束。

这些措施隔离异常并限制资源，**不是文件系统、网络或系统调用沙箱**。脚本仍以 Easel 服务账号运行；无法据此保证任意恶意代码不能读取该账号的文件或攻击同账号进程。未知或多租户脚本应在容器/独立低权限账号中运行，再通过 HTTP 接入。

### 页面上的轻量管理入口

热点雷达右上角“数据源”可添加 RSS/Atom 订阅和 HTTP 接口、选择本地 .py 文件或编辑内置示例，以及启停来源、删除自定义来源。保存后立即更新列表，新增来源会自动选中。展示名称不追加 Python、HTTP、RSS、Atom 后缀；旧配置中这些技术后缀也会在展示时移除。

管理接口为 `GET/POST /api/trends/manage`，同时检查真实连接对端必须为回环地址，以及浏览器 Origin；远端即使伪造 Origin 也不能管理。写入请求最多 256 KiB，Python 代码本身最多 64 KiB，采用线程锁、跨进程文件锁与临时文件原子替换，避免并发覆盖。接口不返回已有请求头、密钥、解释器或脚本命令。

页面可以选择文件或编辑代码，但不接受任意解释器、命令或服务器写入路径。原有直接编辑 `trend-sources.json` 的高级配置仍可用；历史 `script_id` 与 `trend-scripts.json` 登记方式也保持兼容，页面新流程不依赖它。私有脚本副本与配置均被 Git 忽略。

协议解析会拒绝过深 JSON/XML、重复 JSON 字段、非有限数值、异常 Unicode、超长字段及不安全链接；页面再次校验响应形状，异常条目不会传给 React 渲染。浏览器热点接口设置超时和 4 MiB 响应上限，热点页面另设错误边界，异常时可以局部重载。网络、格式、保存或收藏失败均提供明确反馈；“做内容”链路遇到浏览器会话存储失败时保留当前内存状态并提示，不从 React 状态更新中抛异常。

这里配置的是 Web 热点雷达的数据源。Agent 内 `skill-trending-topics` 等技能的独立工具调用与参考文档没有自动改为读取此注册表，不能据此认定所有 Agent 抓取都已接入本协议。

## 7. 使用真实公开数据验证

[真实数据配置](../config/trend-sources.live.example.json) 包含四条接入路径，仍保留全部内置平台：

| 接入路径 | 数据来源 | 示例 |
|---|---|---|
| Python 子进程 | Hacker News 首页榜单，Algolia 官方 HN Search API | `live_collector.py --provider hackernews --limit 20` |
| HTTP JSON v1 | 本地 HTTP 适配服务每次实时请求 GitHub CLI 公开 Releases API | `live_http_service.py --provider github --limit 10` |
| RSS 2.0 | BBC News 官方订阅 | `https://feeds.bbci.co.uk/news/rss.xml` |
| Atom 1.0 | GitHub CLI Releases 官方 Atom | `https://github.com/cli/cli/releases.atom` |

Python 与 HTTP 两个脚本都在 `examples/trends/`，只有标准库依赖，成功结果均由本次上游请求生成，没有内置固定新闻或读取离线快照。HTTP 适配器不是一个现成的第三方 v1 服务：它的作用是把 GitHub 的原始 Releases JSON 转成 Easel v1，验证“外部服务自行采集、平台只消费结构化数据”的完整路径。

先在独立终端启动 HTTP 服务，并保持运行：

```powershell
python -X utf8 examples/trends/live_http_service.py --provider github --limit 10 --port 8766
```

上游请求使用该终端的 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` 环境变量；它是独立服务，不自动读取 Easel 的 `.env`。如果网络需要代理，请在这个终端按实际情况设置标准代理变量。Easel 启动的 Python 子进程则会继承平台传入的环境设置。

没有现有配置时，复制真实数据配置并刷新页面：

```powershell
Copy-Item config/trend-sources.live.example.json config/trend-sources.json
```

若已有自定义配置，请把四项合并进现有 `sources` 数组，保留原有设置。接入条目无需填 API Key；匿名公开 API 仍可能受上游限流或网络影响。此配置用于复现接入验证，不代表平台承诺这些公开服务永久可用。

验证时建议先重启后端清空内存缓存，再逐个请求 `/api/trends?platforms=<id>&limit=30`。只有 `status: fresh`、`stale: false`、`error: null` 且含真实条目，才记作本次采集通过；不要把旧缓存回退记作上游正常。

自动测试只调用本地回环服务与合成样本，不请求真实模型或平台。手工真实来源验证与自动回归分开执行；公开示例不自动启用。跨平台回归覆盖 Windows、Linux、macOS 及 Python 3.10 / 3.12。
