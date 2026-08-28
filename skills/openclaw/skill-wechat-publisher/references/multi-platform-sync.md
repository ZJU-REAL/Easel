# 阶段七:多平台同步细节

把发到微信草稿箱的同一篇文章,一键同步到知乎、掘金、CSDN、头条等平台(各平台也存为草稿)。**默认不启用**,只有显式传参才触发。

#### 前置一次性安装

底层基于 [Wechatsync](https://github.com/wechatsync/Wechatsync),复用 Chrome 扩展里各平台已登录的 Cookie,不经过任何第三方服务器。

1. 装 Chrome 扩展「Wechatsync」,并分别登录知乎 / 掘金 / CSDN 等目标平台
2. 扩展设置里打开「MCP 连接」,生成一个 Token 拷出来
3. 装 CLI:
   ```bash
   npm install -g @wechatsync/cli
   ```
4. 在 `wechat-publisher.yaml` 里配置:
   ```
   integrations:
     wechatsync_mcp_token: "<第二步拷出的 Token>"
   ```
5. 自检:
   ```bash
   python3 skills/openclaw/skill-wechat-publisher/scripts/multi_publish.py --check
   ```
   两项都打 `✓` 说明就绪。

#### 触发方式

**方式 A:命令行显式指定平台(最常用)**
```bash
python3 skills/openclaw/skill-wechat-publisher/scripts/publish.py --account main \
  --input outputs/主题名/article.md \
  --cover outputs/主题名/cover.jpg \
  --sync zhihu,juejin,csdn --exec
```

**方式 B:从账号配置读默认平台列表**

先在 `wechat-publisher.yaml` 对应账号下加:
```yaml
accounts:
  main:
    ...
    sync_platforms: [zhihu, juejin]
```
然后发布时加 `--sync-from-config`:
```bash
python3 skills/openclaw/skill-wechat-publisher/scripts/publish.py --account main --input x.md --cover x.jpg --sync-from-config --exec
```

**方式 C:独立跑(不发微信,只同步)**
```bash
python3 skills/openclaw/skill-wechat-publisher/scripts/multi_publish.py --input x.md --platforms zhihu,juejin --exec
```

#### 图片注意事项

微信 CDN(`mmbiz.qpic.cn`)有严格防盗链,其他平台加载时会显示「此图片来自微信公众平台」占位图。
因此同步走的是**原始 markdown**(`article.md`),不是已处理过的版本。

- 外部 URL 图片(HTTPS):wechatsync 自动转存到各平台,通常没问题
- 本地路径图片（比如 `outputs/主题名/assets/fig1.png`）：wechatsync 的文档未明确是否支持
  - `multi_publish.py` 会扫出并提示有多少张本地图
  - 如果目标平台发现图加载不出来,需要把本地图先传到公开图床(或任何无防盗链的 CDN)、改成 URL 后再跑同步

#### 失败处理

- 同步失败**不回滚**微信草稿(微信草稿已在阶段六成功创建)
- 告知用户:微信草稿 OK,但某平台同步失败 → 可以登录 Chrome 扩展手动重试
- 各平台同步后都是「草稿」状态,**不会**直接公开发布,需要用户登录各平台二次确认
