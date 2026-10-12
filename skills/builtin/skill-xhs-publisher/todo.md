# xhs-publisher 后续可移植（参考 xiaohongshu-mcp）

当前实现（`../../shared/scripts/xhs_publish.py`）已覆盖：登录 + 图文/视频发布 + 成功校验。

参考实现里还有、我们暂未移植的能力（需要时再从 `xiaohongshu-mcp/xiaohongshu/` 移植）：

- **检索/互动**：`feeds.go`/`search.go`/`feed_detail.go`/`comment_feed.go`/`like_favorite.go`
  ——喂 xhs-analyzer / comment-insights 用。
- **发布高级项**：可见范围 / 定时发布 / 原创声明 / 商品绑定（`publish.go` 里选择器齐全）。

已移植：
- ✅ **二维码登录**（`login` 抠二维码成 PNG 供扫码，headless 可用）——但机房/代理 IP 会被小红书判
  风险拦在登录前，需干净 IP 或异地登录后拷贝登录态目录（`--profile-base`）。

