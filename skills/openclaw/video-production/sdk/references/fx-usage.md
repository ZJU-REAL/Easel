# 弹药用法（FX-15 / FX-16 即插即用指南 + 语义强制规则）

> 2026-09-17 立。背景：真机实录发现执行者"把 FX 件复制进工程、import 了，最后当未使用删掉"——法宝在手不用，交付就成了平面拼装。
> 本文件 = 照抄级用法 + 硬规则。**内容有对应语义时，禁用平面降级。**

## 零、语义 → 必须用的件（硬规则）

| 内容语义（台词/设计中出现） | 必须使用 | 禁止的降级写法 |
|---|---|---|
| 弹出 / 立起来 / 立体 / 厚度 / 3D（卡片、面板、牌子等） | **FX-15 真透视 3D 卡**（perspective + 厚度背板 + 投影三层） | 平面卡加一点 skew/浮动（看着仍是贴纸） |
| 背后 / 身后 / 穿过 / 绕到背面（人话"从背后穿过去"） | **FX-16 人物蒙版分层**（同源片 + 逐帧蒙版把人切到最前） | 把人当贴图叠在元素上 / 直接元素压人 |
| 一般卡片、字、图形（无立体/穿越语义） | 普通层即可 | — |

自查：交付前抽帧——① 凡"3D 卡"场次，帧里必须能看到侧厚/透视收缩（正对镜头的平面玻璃卡 = 返工）；② 凡"背后"场次，抽帧必须能看到元素被人体裁切（穿帮 = 返工）。

## 一、FX-15 真透视 3D 卡（最小可用骨架）

原理：**透视容器 + 三层**（投影 / 厚度背板 translateZ(-20px) / 卡面），全部由 frame 驱动。完整参照：`assets/fx/FxPanel3D.tsx`。

```tsx
// 外层：透视容器（zIndex 按片场规则）
<div style={{ position: 'absolute', inset: 0, perspective: '1400px', perspectiveOrigin: '58% 40%', zIndex: 10 }}>
  {/* ① 投影 */} <div style={{ position:'absolute', left: px-40, top: py+40, width: W, height: H, borderRadius: 24,
      background:'radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 75%)', opacity: k }} />
  {/* ② 厚度背板 */} <div style={{ position:'absolute', left: px-W/2, top: py-H/2, width: W, height: H, borderRadius: 22,
      background:'rgba(10,18,34,0.6)', border:'1px solid rgba(77,201,246,0.4)',
      transform: `rotateY(${ry}deg) rotateX(${rx}deg) translateZ(-20px)` }} />
  {/* ③ 卡面（内容放这里；overflow hidden + 扫光层） */} <div style={{ position:'absolute', left: px-W/2, top: py-H/2, width: W, height: H,
      borderRadius: 22, overflow:'hidden', transform: `rotateY(${ry}deg) rotateX(${rx}deg)`, opacity: Math.min(1, k*1.2) }}>
      {/* 扫光：left 由 frame 插值扫过 */}
  </div>
</div>
```

参数（照 FxPanel3D.tsx 改）：
- `W/H`：620×360 起步；`px, py`：位置（入场用 `(1-k)` 施位移）。
- `ry`：常驻 `22 + sin*1.5`（侧角度决定"立体感"强弱——**15°~30° 才立得起来**，太小=看不出来）；`rx`：俯仰 `-4 ± 0.8`。
- `k`：入场弹簧（damping 11 / stiffness 120 / durationInFrames 26，帧偏移 14 起步）。
- 扫光：`interpolate(frame, [30,100], [-420, 900])`，一条 140px 宽渐变条 rotate(13deg)。

坑位：
- **`perspective` 必须带单位**（`'1400px'`）——数字写法静默失效，面板退化成 2D 斜贴（本项目 PITFALLS 收录）。
- 厚度背板用 `translateZ(-20px)`；不要用"复制一层偏移 6px"冒充厚度（侧看立刻穿帮）。
- 入场后加呼吸级浮沉（±8px、0.03 周期），静止的 3D 卡会"死"。

## 二、FX-16 人物蒙版分层（完整配方，5 步）

原理：层栈自下而上——**原片(z10) → 背后元素群(z15) → 同源片+逐帧蒙版(z16)**。蒙版把"人"从画面里切出来压在最上层，背后元素经过人体时被真裁切。

1. **抠像**：`python tools/rvm_matte.py --src public/<film>/proxy.mp4 --out <rgba_dir>`（RVM；1020 帧约 4-5 分钟 GPU）
2. **蒙版集**：`python tools/make_masks.py --in <rgba_dir> --out public/<film>/masks/`（产出 `pa_0000.png…`）
3. **层栈**（三段，全部显式 `position:'absolute', inset:0`；zIndex 10/15/16）：
   ```tsx
   <OffthreadVideo src={staticFile(`${dir}/proxy.mp4`)} style={{ position:'absolute', inset:0, width:'100%', height:'100%', zIndex:10 }} />
   <div style={{ position:'absolute', inset:0, zIndex:15 }}>{/* 背后元素群（逐项 stagger ≤4 帧） */}</div>
   <OffthreadVideo src={staticFile(`${dir}/proxy.mp4`)}
     style={{ position:'absolute', inset:0, width:'100%', height:'100%', zIndex:16,
              WebkitMaskImage: mask, maskImage: mask }} />   // mask = url(staticFile(`${dir}/masks/pa_XXXX.png`))
   ```
4. **对位**：蒙版序号与帧对齐（`idx = clamp(frame, 0, count-1)`）；`count` = 该场用到的帧数（不是全片）。
5. **验收**：抽 2-3 帧看遮挡——元素经过人身边缘时被裁切（穿帮/没切住 = 查蒙版对齐/透明度）。

坑位：
- **蒙版缺位时该层=全帧不透明**——会把人整个盖住/挡住一切（预览可用、遮挡失效）；**交付前必须先出蒙版**，抽帧验证再交付。
- 多 OffthreadVideo 必须显式定位——否则第二个视频走文档流掉出画布。
- 蒙版目录别忘进 `public/`（`staticFile` 只能取 public 内）。

## 三、和门/设计表的关系

- 设计表里写了"真透视 3D 卡 / 背后穿过"→ 交付物必须真做到（上面的自查抽帧）；做不到就改设计表措辞，**不许设计表吹、实现降级**。
- 人审包（`tools/make_review_pack.py`）逐场定格会把这两类问题直接晒出来——它是这组规则的执法现场。
