# 第三方素材与来源登记（ATTRIBUTIONS）

> 开源发布版（v0.2.0）。受限资产一律不入库，处理方式见下表；各 assets 子目录另有 README。

| 类别 | 内容 | 来源 | 许可状态 / 处理 |
|------|------|------|----------------|
| 效果件源码 | FxShatter 等（改造为视频版） | github: av/remotion-bits | **MIT**（已核：package.json + README）→ 保留致谢 |
| 效果件源码 | FxAurora / FxKinetic（示例改造） | github: naveen-annam / hollowenshot creativly.ai-brand-video-remotion | **MIT**（已核：仓库 license 字段）→ 保留致谢 |
| 转场 / 漏光 | `@remotion/transitions`、`@remotion/light-leaks` | Remotion 官方包 | 随依赖（Remotion License） |
| 音效 | Mixkit 现成音效 10 枚 | mixkit.co | Free License（可商用）→ **mp3 不入库**，`tools/fetch_sfx.py` 直链拉取 |
| 视频素材 | 12 支（台账 `assets/stock-ledger.json`） | mixkit.co | Free License → **不入库**（台账保留） |
| LUT | Portra160NC/VC、Fuji400H、kfinal_replica（本项目调校） | G'MIC film emulation 系 / 自产 | 再分发不明确 → **cube 不入库**，说明见 `assets/luts/README.md` |
| 字体 | MaShanZheng-Regular | Google Fonts | **SIL OFL 1.1** → 随包（含 `OFL.txt`） |
| 字体 | simhei / simkai | Windows 系统字体 | 不可再分发 → **不入库**，自备（见 `assets/fonts/README.md`） |
