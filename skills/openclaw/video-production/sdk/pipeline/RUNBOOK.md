# 管线流程（RUNBOOK · 九步可执行版）

> 每步：**需要 → 做（命令）→ 得到 → 门（不过不往下走）**
> 工作工程目录自定（示例 `E:/remotion-test`；也可用 deps/remotion 蓝图新建）；工具在 `../tools/`，门在 `../gates/`。

### Step 1 素材摸底
- 做：ffprobe 摸底 → 抽帧 → 人脸安全区 → 转码 proxy（`-g 30` 关键帧）
- 得到：proxy.mp4 / frames / 安全区
- 门：抽帧覆盖全片；proxy 可秒 seek

### Step 2 转录
- 做：`python tools/transcribe.py --src proxy.mp4 --out transcript.json`（本地 large-v3，免下载）
- 得到：transcript.json（词级时间戳）
- 门：段数>0；抽 3 段对照（可疑处记「错字待拍板」；子词修正法见 PITFALLS §4）

### Step 3 素材收集
- 做：Mixkit 抓取（`tools/fetch_mixkit*.py` → `tools/parse_mixkit.py` → 按 id 下载）→ `tools/transcode_stock.py` 统一 1080p30 → **逐支抽帧核验**（`tools/fx5_frames.py` 模式）
- 得到：素材 + `assets/stock-ledger.json` 登记（来源/许可/时长）
- 门：**素材必须对应台词；入场前抽帧核验（不合就换）；零未查看素材**

### Step 4 SCENES + 风格基调
- 做：逐句分场；状态分配；定本片风格基调（由内容推理由）；给每卡位分配唯一 形式×变体
- 门：`python ../gates/check_dup.py --scenes scenes.json`
- 门：`python ../gates/check_timeline.py --scenes scenes.json`（重叠/长间隙/过短场——防 A/B 闪切）

### Step 5 设计表 → 用户确认（铁律门）
- 做：出设计表（含「每场概念演出清单」）；附「本片 × 参照物」对照表
- 门：**用户点头才写码**；查重自查过

### Step 6 写码
- 做：Remotion 工程（复用 deps/remotion 蓝图）；字体本地化；SFX 从 `assets/sfx/` 与现成库找（禁生成）
- 调色（如需）：`tools/grade_demo.py` 模式（降噪 → LUT blend 控强度）
- 门：`npm run build`（=remotion compositions）无 error；`python ../gates/check_layout.py`（排版网格）

### Step 7 渲染级验证
- 做：渲关键静帧 → 像素断言
- **视觉自检（执行者具备看图工具时必过）**：把关键帧交给看图工具，对照设计表核查——密度（≥3 层元素）/ 字幕可读 / 有无素场；有明确问题先改再往下。参考实现 `tools/see.py`（图片→多模态端点→文字结论）
- 门：`python ../gates/check_frames.py`（帧检+尺寸+脸区）+ `python ../gates/check_transitions.py`（转场可感知）

### Step 8 Studio 预览（用户点头门）
- 做：`npx remotion studio --gl=angle --port=3002` → 桌面预览
- 注意：Studio 播放是近似同步（起步晚 200-600ms）——审片用「拖时间轴 / 暂停再播」；**同步判定以 Step 9 实测算，不以预览观感算**
- 门：**用户满意前绝不渲全片**；预览必查动态（相邻帧 diff）

### Step 9 全片渲染 + 交付
- 渲染基建：`npx remotion bundle`（一次，产物在本地 `build/`）→ 之后 `npx remotion render build <Comp> out/final.mp4` 复用（禁每次现拷 public，防 Temp 灌爆，见 PITFALLS §2）；`TEMP/TMP` 指向大盘
- 音频后处理：`afftdn` → `loudnorm=I=-16:TP=-1.5:LRA=11`；处理链引入的约 30ms 后移用 `atrim=start_sample=N` 裁齐
- 门：`python ../gates/check_meta.py`（五件套）+ `python ../gates/check_match.py`（对位表）+ **`python ../gates/check_audio.py`**（响度：max≥-3 且 mean≥-20）＋ **`python ../tools/check_sync.py --ref ref.wav --test out/final.mp4`**（|偏移|≤15ms；AAC 固有 ~42.6ms → 裁齐重封复核到 0ms 级）＋ 人审包：`python ../tools/make_review_pack.py --run-dir <run>`（每场定格帧 + 核对表，随交付附上）
- 交付：final.mp4 + design-table.md + asset-match.md + gate-report.md + sources.json（见 INTERFACE.md）
