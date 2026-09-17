---
name: remotion-pipeline
description: "Remotion 大片统一管线——口播/独白/教程视频从转录到成片。触发：做视频/大片/口播特效。"
version: 2.0.0
created_by: agent
metadata:
  hermes:
    tags: [remotion, video, pipeline, blockbuster, spoken-video]
    category: creative
    related_skills: [video-shotcraft, voice-cloning]
---

# Remotion 大片统一管线

唯一入口技能。合并自 remotion-aesthetic / video-production / remotion-production-lessons / remotion-video-mastery / remotion-spoken-video-rules（2026.8.7 合并）。**冲突时以本技能为准。**

## 0. 场景路由（先判再走）

| 场景 | 管线 | 说明 |
|------|------|------|
| 已有原片做大片（口播/独白叠加概念动画+PiP+字幕） | **本技能主流程**（下方 1-5 节） | Remotion 双层架构 |
| 从零做片（品牌片/宣传片/trailer/无原片） | **OpenMontage cinematic**（`references/openmontage-cinematic-execution.md`） | 44.5k⭐ 项目，13 管线，8 阶段链 research→proposal→script→scene_plan→assets→edit→compose→publish，proposal 批准门 |
| 产品宣传片（有产品/网页截图） | video-shotcraft | 104 镜头配方卡 + Ink Press 模板 + 149 音效 |
| 长视频切短视频 | shorts（claude-shorts） | 转录→选段→Remotion 动画字幕 |

视频类型自己判，不反问用户（2026.7.8 纠正）。

## 1. 用户硬性需求（精酿版，违反必返工）

| # | 需求 | 细则 |
|---|------|------|
| 1 | 状态 A/B | A=真人全屏出镜，动画在空位（头顶/两侧）不挡脸；B=动画大屏或素材大屏+右下PiP（边距36px）。**状态分配按内容理解定，60/40 降为参考（2026.8.8 验收方改）**：情绪重锤/核心观点/反转/收尾倾向 B，铺垫过渡倾向 A；**必须有节奏**——禁连续 4+ 场同状态，禁死板交替。**A/B 两态各自都要有完整展示画面**——不只是卡片层：整屏构图、背景形态、动效体系在 A 态和 B 态必须是两种不同形式；**动画必须完整变换**（入场→演绎→收束全链路），禁半截动效/只进不出。**A 态真人不压暗（2026.9.16 验收方立）**——A 态画面禁加减光层（Dim/暗罩一律不加，真人必须全亮）；减光只用于素材/字幕可读场景，且任何压暗上限 0.3（素材大屏渐变底部 ≤0.46）。起因：卡片样板 FX-CardA 曾给真人叠 0.3 减光，被验收方当场点名 |
| 2 | 卡片三形态 | A 场景：头顶概念动画胶囊（radius 999+微倾斜±2deg）+ 左无壳浮空大字（88px发光）+ 右无壳数据滚动（环形/柱状+count-up）。**绝不复用同一卡壳换字**；左右高度错落（左y230/右y400）；禁矩形壳 |
| 3 | 玻璃态透明卡 | A 出镜时卡=半透渐变 rgba(255,255,255,0.03-0.10)+backdropFilter blur(16px) saturate(140%)+细亮边 rgba(255,255,255,0.28)+accent光斑，放人物身边。不是深色大底卡。**卡内背景必须含动态材质**（每片按风格选 1-2 种：流光扫过/呼吸亮度/内部微粒子漂浮/液态渐变位移），禁纯静态玻璃片 |
| 4 | 卡片尺寸 | ≥560px 宽（头顶胶囊~920、B中央卡≥640）。卡=背景+动画+展示内容三件套 |
| 5 | 概念动画 | 每句独立视觉、服务台词内容（不是文字关键词卡！）。填充形+底层半透明圆模拟辉光（禁drop-shadow，headless不稳）+spring驱动。**绝不手搓几何图形**（几何=PPT=被拒）；**机制可复用、风格不复用——不同场景、不同视频各做各的风格动画**（2026.9.16 验收方重申） |
| 6 | 元素密度 | 每句 ≥3 并行元素。B=中央概念卡+**左右两张真侧卡**+底部chips(3胶囊)+角落DataFloaters；A=三形态卡本身就是3元素。**元素分三层职责**：主角元素（概念动画本体，最大最亮）+ 陪衬元素（呼应主题的次级图形）+ 氛围元素（粒子/光晕/网格环境层）——三层齐才算"丰富"，三个并列卡不算。**B 态左右侧卡铁律（2026.8.8 验收方立）**：必须是真卡片不是装饰线条；左=动画卡（呼应中央概念的次级动画），右=信息卡；**表现形式不固定**——文字动画卡（逐字弹入/滚动）/动态背景卡（卡内跑动态背景）/素材卡（原片静帧/真实图片）/数据卡（环形柱状count-up）按 kind 轮换选择，禁两场连用同一形式。**A 态（真人大屏）同样铁律（2026.8.8 验收方立）**：头顶胶囊之外，左右两侧必须真卡片（左动画/文字卡、右信息卡），形式四选轮换。**禁重复动画（全片铁律，2026.8.8 升级为绝对禁令）**：绝对禁止重复动画和画面——每场每卡画面必须唯一。侧卡动画与主概念不得重复/变体复用；同一形式变体（如 data-ring、dynbg-stars）全片只出现一次；同 kind 两场的侧卡动画也必须拆开；设计表阶段即给每卡位分配唯一 形式×变体 组合，写码前自查全片无重复 |
| 7 | 字幕 | 固定底部同一位置，**transcript 原文一个字不改**，whisper 转多少段放多少段。单行 ≤14 字，>14 降字号/换行。错字/黑话列表交用户拍板（"梁子"非"梁字"案例） |
| 8 | 转场 | **每次 A↔B 状态切换都转场**（6种轮换：纸帘/墨晕/裂痕/淡入/边收/光圈，相邻不重复，0.2-0.26s）。**半透明叠加 0.5-0.8 不黑屏**。pipSnap 冻结视频层否则全塌成放大缩小。**B→B 连续舞台内不转场只切内容**（同状态相邻场 transitionIn 留空，2026.8.8 明确） |
| 9 | 配色 | **禁铜金默认**（#c4956a/#e8c97a 反射性习惯）。彩色多 accent：冰蓝#4dc9f6/青#22d3ee/紫#a78bfa/粉#f472b6/绿#34d399/暗橙红#c95a3a。每 kind 独立 accent。用户明确说"用铜色"才用 |
| 10 | 背景氛围 | 三层缺一不可：z0常驻暖光radial-gradient（A态也可见！禁MeshGradientBg，视觉为零）+ z2 FloatParticles 18颗微尘 + z4 B态 InkBokeh+光斑。B态动态背景照抄81模板参数化（grid-pulse/starfield/matrix-rain），z3。**所有背景层必须带动态分量，禁静态死背景**：z0 常驻光做呼吸/缓慢漂移（位置或亮度 6-10s 周期），A 态微尘常动，B 态动态背景全速——画面任意时刻至少 2 层在动 |
| 11 | 声音 | **零BGM**。音效铁律（2026.9.8 用户立）：**音效只能找现成的**——从现成音效库（本机 video-shotcraft **149 枚·16 类**：`skills/creative/video-shotcraft/assets/audio/sfx/`）/网上找真实音效文件（Mixkit 音效直链可爬：`assets.mixkit.co/active_storage/sfx/<id>/<id>-preview.mp3`），**禁止自己生成/合成音效**（AI 生成的"阴间音效"被用户狠批，例：whoosh-fast/impact-cine-big 被嫌难听）。用户没说要音效=不加SFX层；要加就按他的要求找合适的（剪辑感强、不阴间），音量≤0.2（人声-25dB对比），一个B场景只留1个impact。`<Sequence from={帧}><Audio/></Sequence>` 起播，**禁 startFrom/endAt**（那是音频内部偏移，会把短音效裁空）。用户说"没必要配音/音效"=删掉SFX层；**（2026.9.16 追加）生成通道全弃**——ElevenLabs sound-effects 等"文字→音效"就是验收方点名的"自己生成雷霆音效"，违规；音效要"对得上"动作：转场刀=whoosh/sweep、强调点=hit、UI 点=click/chime；核验=ffprobe 时长+名字语义（耳朵终审=验收方） |
| 12 | 进度条 | 全片必含：顶部3-4px流动光泽+端头发光点，**标明章节名**（当前章accent高亮其余暗灰），z50 |
| 13 | 预览确认制 | **用户满意前绝不渲全片**（"我不满意就渲染等于浪费时间"）。Studio 3002 预览 → 用户点头 → 才渲染 |
| 14 | 流式连续 | 禁每句独立spring弹入弹出（=断点）。A卡 enter [start-0.18,+0.08] 右滑入 / exit [end-0.12,+0.08] 左滑出（end=next start 天然重叠）；B舞台常驻只切内容（useFlow）；A↔B交叉衔接（B收尾0.22s+ A提前0.18s）。**全局连续性三铁律**：①色彩贯穿——accent 家族设计表定死后全片不换色系，kind 间切色走渐变过渡不硬跳；②动势衔接——上一元素出场方向/速度影响下一元素入场（同向延续或对撞反转），禁每场运动方向随机；③曝光平滑——场景切换前后整体亮度/色温不突变，禁一明一暗闪观众 |
| 15 | 电影感+独立风格 | **所有视觉效果围绕电影感制作**——镜头语言/光影层次/运动曲线按电影标准，不是PPT动效。**每部片独立定风格：风格由该片表达的内容决定**，禁反射性套用上一部的配色/版式/氛围。开设计表前先定本片风格基调并写明理由（2026.8.7 定）。注：动画引擎机制可复用（第3节），视觉风格不复用。**电影感落地四手段**：①景深——前/中/后景 filter blur 分级，拉开前后层次；②方向光——accent 光从固定方向染色，元素有受光面/背光面；③运动曲线——spring/ease 带惯性回弹，禁线性匀速；④质感收尾——全片常驻噪点颗粒层（opacity ≤0.06，z55）或辉光扫层 |
| 16 | 画面单调自检 | 用户说"单调/没高级感"时按四缺诊断（2026.8.8 验证）：①缺光——纯色描边线稿=图标不是场景，要体积光锥/bloom 光晕/光染色，亮部有光渗；②缺景深层次——背景+卡片两层平面是死的，加镜头前景（缓慢飘过的大颗粒模糊光斑 blur≥20px）；③缺材质——纯色 fill/stroke 是 PPT 语言，金属要渐变、玻璃要折射亮边、发光体内亮外晕三层；④缺运动物理感——sin/cos 周期运动机械，要拖尾/惯性/加减速。术语对齐：用户说"我大屏"=A 态真人全屏，"动画大屏"=B 态 |
| 17 | 素材管线 | **缺素材是病，主动找（2026.8.8 验收方立）**：①agent 主动网络搜素材（真实图片/视频片段/产品截图，web_search+下载进 public/assets/）→ **自己先看**（vision 或像素分析确认内容/色调契合本片风格）→ 插到合适场；②找不到合适的**问用户要**，不硬凑不瞎编；③**素材播放=状态 B**——素材大屏展示（图片/视频片段铺满+右下 PiP 真人），不走 A 态侧卡；④素材大屏也要动：Ken Burns 推拉/视差层/光扫，禁静态贴图；⑤设计表素材场必须标注素材来源（URL/用户提供/原片帧）；⑥**素材必须对应台词（2026.9.16 验收方立）**——每个素材镜头必须语义对应它所在场的那句台词（观众看到镜头就懂这句在说什么）；素材清单逐条标注「对应台词」，交片前逐场核对；对不上就换素材，不硬凑；⑦**素材入场前必须抽帧核对语义（2026.9.16 验收方立）**——每个候选素材先抽 2-3 帧（或 contact sheet）亲眼核验：画面内容真的符合该句的语义情景、色调契合；只凭文件名/描述下注=违规，不合就换 |
| 18 | 完整片五件套 | **一个完整视频 = 素材＋动画＋转场＋音效＋原画面（2026.9.16 验收方立）**。交付前自检五类齐备：素材（对位核验过）/ 动画 / 转场 / 音效（现成库找、挂对位置）/ 原画面（A/B 双态）；缺项=不满配 |

## 2. 管线流程（SOP：任何 agent/模型照步执行）

九步，每步四件套：**需要→做→得到→验收**。产出不齐不进下一步，验收不过不往下走。

### Step 1 素材摸底
- **需要**：原片路径（Windows 原生 `C:/` `E:/`，`/e/` 报 No such file）
- **做**：
  1. `ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_type,codec_name,width,height,r_frame_rate -of json <源>`
  2. 抽帧：Python 逐次调 `ffmpeg -ss T -i 源 -frames:v 1 out.png`（禁链式多输入=全抽同帧），间隔覆盖全片
  3. 人脸定位：vision 403 → OpenCV（**必须 `<5`**）+ haarcascade_frontalface_default.xml → bbox → 定安全区（1080p 典型：左 x<650 / 右 x>1300 / 头顶 y<170）
  4. 转码代理：`ffmpeg -vf "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black" -c:v libx264 -crf 23 -preset fast -g 30 -keyint_min 30 -sc_threshold 0 -c:a aac -b:a 192k`
- **得到**：proxy.mp4（~原片 1/15）、frames/ 抽帧、faces.json、安全区坐标
- **验收**：抽帧覆盖全片时长；人脸 bbox 全帧检出；proxy 可秒 seek

### Step 2 转录
- **需要**：proxy.mp4
- **做**：faster-whisper large-v3 CUDA（float16, `local_files_only=True`，首次 `HF_ENDPOINT=https://hf-mirror.com`）→ word_timestamps。写 .py 后台跑，**启动后 30s 查输出文件**（stdout 缓冲不可靠），不干等
- **得到**：transcript.json（segments: start/end/text/words）
- **验收**：段数>0；抽 3 段对照原音无明显错字（可疑处记入待拍板清单）

### Step 3 素材收集（执行 #17；2026.9.7 验证版完整链路）
- **需要**：对 transcript 的内容理解——哪些句需要具象素材支撑
- **做**：
  1. 素材类型判断：AI 视频模型演示→YouTube 官方频道（yt-dlp 直下：Sora tokyo in the snow / mitten astronaut、Veo 3 off-road rally official demo、UE5 Lumen/Nanite reveal、独立游戏官方预告）；AI 失败图/逼真照→Wikimedia Commons（本机被墙时走 **wsrv.nl CDN 代理**：`https://wsrv.nl/?url=commons_upload_url&w=1920`）；程序员/生活图→Pexels/Unsplash 直连（Pexels 574071/577585/270348 已验证）
  2. **子代理并行下载**（delegate_task 3 路：视频官方演示/UE5+indie/图片），每个任务给：来源清单+本地 yt-dlp 路径+验证要求；子代理必须 ffprobe/PIL 验证并写 download_log.md（含来源 URL/时长/分辨率/编码）
  3. **统一转 h264 1080p30**：AV1/VP9 必须转（`-c:v libx264 -crf 20 -preset fast -r 30`）；素材裁剪到 8-15s（`-ss 20 -t 15`）适合 B 态单场；图片保持原尺寸
  4. **每个素材自己先看**（vision 或像素分析确认内容/色调契合本片风格）：vision 上游 500 时用像素统计降级（mean/std/saturation，全黑=<10 或全白=>230 弃用）
  5. 找到素材→插到合适场；找不到的**问用户要**，不硬凑
- **得到**：素材清单（文件+来源 URL+用途场号）
- **验收**：零未查看素材；每个素材有归属场；素材播放场=B 态（#17）

### Step 4 SCENES + 风格基调
- **需要**：transcript.json、素材清单
- **做**：
  1. 逐句原话分场（仅两段都≤8字或新段≤4字语气词才合并；合并后 >20 字拆开）；边界连续 scene[N].end=scene[N+1].start
  2. 状态分配按内容理解：情绪重锤/核心观点/反转/收尾→B，铺垫过渡→A；素材播放场=B
  3. 节奏自查：禁连续 4+ 场同状态、禁死板交替
  4. kind=有意义英文名（非 hash）；每 kind 独立 accent
  5. 定本片风格基调（#15）：风格名+理由（由内容推出）+accent 家族+背景动态方案+卡片动态材质
  6. 给每卡位分配唯一 形式×变体 组合
- **得到**：scenes 草稿（状态/kind/accent/concept/卡位分配）
- **验收**：节奏自查过；风格基调五要素齐

### Step 5 设计表 → 用户确认（铁律门，未确认不写码）
- **需要**：scenes 草稿
- **做**：出表：表头=风格基调五要素；表格=`| 时间 | 台词 | 状态 | 动画/卡片 | 转场 |`；**动画列写观众看到的具体物象**（心跳线/铁块/王冠…禁组件代号）；素材场标来源；附错字待拍板项
- **重复自查清单（出表前必过，逐条打勾）**：①概念动画 id 两两不同；②卡位 形式×变体 两两不同；③同 kind 多场动画不同；④侧卡与主概念不同；⑤素材帧各场不同
- **得到**：用户点头（或改稿后重过自查）
- **验收**：用户明确说确认

### Step 6 写码
- **需要**：确认后的设计表
- **做**：
  1. 工程：复用既有工作工程（带 node_modules）或复制 package.json+tsconfig 新建（**build 脚本必须= `remotion compositions`**，模板遗留 HelloWorld 会报错）
  2. 字体本地化 `public/fonts/`+@font-face（MaShanZheng+simhei+simkai），**禁 @remotion/google-fonts**（联网卡死）
  3. public/ 只放本片资产（源视频+fonts+sfx+frames+assets），其余移 public_backup（bundler 全拷 TEMP，2GB 必超时）
  4. SFX：`skills/creative/video-shotcraft/assets/audio/sfx/`
  5. 组件分层 zIndex 铁律：`Bg=1 → 粒子=2 → B动态背景=3 → B光斑=4 → 视频=10 → 卡片≥20 → 字幕=30 → 转场=40 → 进度条=50 → 噪点=55 → 渐黑=60`（未设 zIndex 的层被视频层盖住=B 态全黑根因）
  6. 按设计表实现，遵守硬性需求 #1-#17 全表
- **得到**：Composition 编译通过
- **验收**：`npm run build`（=remotion compositions）列出本片 id 无 error

### Step 7 验证（渲染级，无跳过）
- **需要**：编译通过
- **做**：
  1. 渲关键静帧 `npx remotion still <Comp> out/k.png --frame=N`（每 B 段中段+A 开场各 1）
  2. 像素验证（numpy/PIL 区域精确查，大步长漏检细线条）：字幕 `img[900:1030,400:1520]` 白色 `(sum>600)&(max-min<60)`>0；概念动画 accent 色像素>1000；PiP 右下 1/4 均值明显亮于背景；**B 态字幕是 accent 色不是白色——检测条件要覆盖；暗色 accent（ember 等 sum<480）必须用颜色距离检测 dist<80，禁只用亮度阈值**
  3. 脸区零侵入：A 态帧人脸 bbox 内 accent 像素≈0
- **得到**：每帧验证数据
- **验收**：三要素全过+脸区零侵入

### Step 8 Studio 预览（用户点头门）
- **需要**：Step 7 全过
- **做**：`npx remotion studio --gl=angle --port=3002`（**禁 3000** Hermes 自毁；裸命令后台跑，禁 pipe=SIGPIPE 杀进程）→ poll 日志等 `Server ready`+`Built in` → `open_preview(http://localhost:3002)`
- **预览必查动态**：截相邻 2 秒两帧 diff——背景层/卡片材质/粒子全同=静态死背景，返工（#3/#10）
- **得到**：用户点头
- **验收**：**用户满意前绝不渲全片**；用户说"看效果/做个看看"=直接渲全片，不交截图

### Step 9 全片渲染 + 交付
- **需要**：用户点头；**先杀 Studio**（内存不足 compositor 崩）；端口残留：`netstat -ano | grep :3002` 找 PID → `taskkill /F /PID`（git-bash 单斜杠）
- **做**：**必须走 .ps1**：`$env:TEMP="E:\rtmp"` + `npx remotion render <Comp> out/final.mp4 --gl=angle --concurrency=4`，`powershell -File` 执行（内联 `$env:` 被 bash 吞）；渲染前 `df -h /c` <2G 先 `npm cache clean --force`+清 `Temp/remotion-*`；渲染前后各 `Get-Process node | Stop-Process -Force`；禁 `--chromium-options`（静默挂起）；音频后处理：concat 后整段一次 `loudnorm=I=-16:TP=-1.5:LRA=11`
- **得到**：final.mp4 → 拷到交付目录 → 用宿主媒体通道贴进对话交付（Easel 用 `/api/media/` 语法；禁 `MEDIA:` 前缀）
- **验收**：成片时长=设计时长；抽 3 帧与 Studio 预览一致

## 2.5 智能粗剪（Step 0.5，用户 2026.9.8 立：粗剪先行再包装）

用户认可 AI 粗剪做法（GPT 剪辑观感）：**剪气口 + 剪口误/重复 + 钩子前置**，剪完的片再上包装，时间轴全部重新对。

- **气口**：`ffmpeg -af silencedetect=noise=-32dB:d=0.7`；>0.7s 停顿剪到保留 0.22s 呼吸；段内全部处理（句间大停也剪）。
- **钩子前置**：用 whisper 词级时间戳定位最炸句（如“饭碗赶没”段）整段剪到开头；主线跳过已覆盖段后直接接后续（“而且”类衔接词天然接前句，检查语序通顺）。
- **合成**：多段 filter_complex：**全部段引用 `[0:v]`/`[0:a]` 而非 `[i:v]`**（单输入只有 0，写 [i:v] 会报段级错误）；trim/atrim+setpts/asetpts → concat=n。re-encode libx264 crf20。
- **口误**：whisper 可疑错（如“2002年”）在句子里剪不了时诚实说，留给配音修或确认原声。
- 粗剪版时长必然变短（122s→110s），设计表/SCENES/字幕全按新轴重建。
- **声音后处理（2026.9.8 用户立：下次声音要放大去噪）**：粗剪后的音频链一次过：去噪 `afftdn=nf=-30:tn=1`（口播底噪/电流音）→ 放大标准化 `loudnorm=I=-16:TP=-1.5:LRA=11`（整段一次，禁逐句 loudnorm 会音量不一）。先 ffprobe 检音轨再处理。

## 3. 风格引擎（弹药库，非固定清单）

**风格不从这里"挑"，由内容长出来**：本节是动效机制弹药库，不是风格模板单。每部片按 #15 的风格基调，先判库内机制是否服务该片表达；不服务/不够就主动出去找（本地动效库、GitHub、设计站扒技法），找到合适的再参数化改造。**禁"库里有就直接套"——清单固定=一直土**（2026.8.7 定）。机制照抄，风格外壳每片新做。

### video-shotcraft demos（`skills/creative/video-shotcraft/demos/`）
| 引擎 | 文件 | 用途 |
|------|------|------|
| 图标场+色波 | `opening/icon-field-colorize/IconFieldColorize.tsx` | 同质化/集合/群像 |
| 机场翻牌字 | `typography/split-flap-title/SplitFlapFlip.tsx` | 高潮大字/收尾定格 |
| 贝塞尔发光飞线 | `effects/glow-flyline-moves/FlylineArc.tsx` | 复制/传输/连接 |
| 数字滚动 | `assets/lib/DigitRoll.tsx` | 数据/能力值 |
| 冲击反馈 | `effects/impact-feedback/` | 印章/落地/重击 |
| 霓虹框 | `ui-entrance/neon-frame-forerun/NeonFrameForerun.tsx` | 高光/聚焦 |

### 81 模板（模板库 `remotion-templates/templates/`，自包含 default export）
matrix-rain/grid-pulse/starfield/sound-wave/particle-explosion/bokeh-circles/liquid-wave 等。**模板无 props 接口——复制源码参数化 accent/opacity 再改**，先 read_file 看源码再改，不猜 props。

### 已验证概念动画引擎（弹药参考——机制可复用、风格不复用，2026.9.16 验收方重申）
FogCluster 散点聚拢（模糊→清晰）/ PageStack 叠页（书/学习）/ TightBox 收缩框（约束/压迫）/ CrushDots 压扁（打压）/ BurstRings 扩散（爆发/突破）/ WarmGlow 暖光（希望/收尾）/ RateBars 柱状涨高（数据）/ CrackHeart 心碎（伤害）。

## 4. 坑位速查（血证）

| 坑 | 修复 |
|----|------|
| Anim* 组件缺 `({ ac })` 解构 | 运行时 ReferenceError: ac is not defined → 必须解构 props |
| `ch={}` 传多子元素 | 必须 `<>...</>` 包裹，否则 esbuild 解析失败 |
| 转场时三重全隐 | 视频/卡片/字幕禁 opacity 条件隐藏，转场是叠层不是替换 |
| 旧转场保留 | 用户一眼认出 → 6 种全部重写公式 |
| 卡片 <560px | 用户判"禁止小卡片" |
| 默认暖铜 | 见需求 #9 |
| BOverlay >0.3 | 画面漆黑，上限 0.3 |
| 卡半透暗底叠暗背景 | 透明/脏 → 底色增韧>0.85 或亮边框/光晕 |
| 渲染 ENOSPC/EPIPE（系统盘爆） | TEMP/TMP 指向其他大盘 + 渲染前清系统盘残留 |
| OffthreadVideo seek 超时 | 源片 -g 30 关键帧 |
| ffprobe/ffmpeg 中文路径 | Python subprocess 传原生路径 |
| 模板 props 不生效 | 先 read_file 源码确认接口，不猜 |
| StaticImage 不存在 | remotion 4.x 图片组件是 `Img`（`import {Img} from 'remotion'`），StaticImage 未导出→React #130 (undefined) |
| pipAmount interpolate 报错 | `[transitionStart, sc.start]` 两值相等（transitionTime=0）→ `if (transitionTime === 0) return target;` 先短路；所有 mode 变化才插值 |
| B 态素材大屏盖住 PiP | 素材大屏 zIndex 必须 < 视频层 z10（用 z3），卡片层 z20；一个组件渲染多 zIndex 层用 Fragment 拆 |
| base.mp4 转码漏 -g 30 | OffthreadVideo 按帧 seek 500/解码失败（"Could not extract frame"）→ 转码必带 `-g 30 -keyint_min 30 -sc_threshold 0` |
| 系统盘 ENOSPC bundle | public 全拷 Temp：清 `Temp/remotion-*`（每次 90M+）；仍不够→TEMP/TMP 指向其他大盘（写进 .ps1 文件执行，内联易被 shell 吞） |
| 大改多处 replace 偏移 | execute_code 用 Python 原生 open().read() 改（hermes_tools.read_file 带行号会污染文件） |
| remotion 命令 pipe | SIGPIPE 杀进程 → 裸命令后台跑 |
| studio 默认 3000 | 显式 --port=3002 |
| 多输入 ffmpeg 抽帧同帧 | 逐次调用，不链式 |
| 渲染时 Studio 还开着 | 内存不足 compositor 崩 → 先杀 Studio 再渲 |
| 声音层组件未挂载=音轨全空 | SFXLayer/Audio 组件定义了但没写进主组件 return → render 输出 ffmpeg 混音为空的静音轨（volumedetect: -91dB mean/max），Studio 里也没有任何声音（2026.9.8 血亏：连续 3 版静音切片）。**写完声音层必须检查主组件是否渲染它**；交付前 `ffmpeg -i out.mp4 -af volumedetect -f null -` 验证 mean>-60dB |
| 调色转码 -an 无音轨 | ffmpeg 调色链常带 `-an`（视频层不需要音轨）→ Remotion 的 Audio 源**必须单独从 proxy 提取**：`ffmpeg -i proxy.mp4 -vn -c:a aac -b:a 192k public/voice.m4a`（或转 wav 保底）。先 ffprobe 源确认音轨存在，防"原片就静音"的误判 |
| 素材大屏暗罩压死素材 | B 态素材大屏整体罩 rgba(6,12,22,0.78)+重渐变=素材暗成黑底（用户"有点暗了"）→ 整体罩 ≤0.40（0.38 已验），渐变只留顶部 0.34/底部 0.46 保字幕可读 |
| 预览=Studio 网页 | 用户要「预览/打开预览」= **Remotion Studio 网页**（可拖时间轴），不是文件播放器。起法：工作目录内 `npx remotion studio --gl=angle --port=3002`（避让 3000/3001），把访问地址发给用户；静态帧照贴 |
| 像素验证亮度阈值漏检暗色 | bright>480 对 ember(#c95a3a,sum=349) 永远为 0 → 暗色 accent 必须用颜色距离检测（dist<80），禁只用亮度阈值 |
| 调色 LUT 反推复刻成品帧 | 用"成品调色帧→输入帧"逐点映射生成3D LUT时，**输入帧必须是未调色原帧且两帧同源**。若用已调色中间帧当输入，LUT 含双重变换→肤色青灰/白衬衫死白（鬼脸，2026.9.8 实测翻车）。反向 LUT 只有帧间一对一时可靠，跨光照迁移必偏色 |
| ffmpeg lut3d Windows 路径 | 滤镜参数里 `C:/` 冒号被吃（No option name）→ cwd 进目标目录用相对裸文件名：`-vf "lut3d=file='x.cube'"`；ffmpeg 8.1 lut3d 选项名是 `file` 不是 `filename`（报 Option not found）。G'MIC 导出 cube 带 DOMAIN_MIN/MAX 裸行 ffmpeg 不认，清洗成 # 注释 |

## 5. 渲染后

- 交付成片：拷到交付目录，贴进对话（Easel 用 `/api/media/` 的视频语法）
- 字幕错字被用户纠正 → 同步改 transcript.json + SCENES + 卡片文案三处
- 新踩的坑补进本技能（操作纪律优先于规范）

## Verification

- 用户点头前不渲全片（铁律）
- compositions 编译通过 + still 渲染成功 + 像素验证三要素（字幕白/动画accent/PiP亮）
- 渲染走 .ps1（TEMP=E:\rtmp），C 盘 ≥2G 才开跑
