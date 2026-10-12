// FX-16 人物蒙版分层 —— 背后的元素被人物"真遮挡"（文字穿人 / 粒子绕背 / 扫描线穿人 的底座件）
// 结构（自下而上）：原片(z10) → 背后元素群(z15) → 同源片 + 逐帧蒙版(z16) → 叠加层
// 蒙版集生成链：tools/rvm_matte.py（RVM 抠像 → RGBA 序列）→ tools/make_masks.py（→ 交付蒙版 pa_0000.png…）
// 生产验证：口播片《管线自检》(2026-09) 实跑；蒙版集缺位时该层 = 全帧不透明（预览可用，遮挡失效）——交付前先出蒙版。
// 要点：多视频层必须显式定位（position:'absolute', inset:0）——否则第二个 OffthreadVideo 会走文档流掉出画布。
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, spring } from 'remotion';
import { Tag, Vignette } from './common';

const ITEMS = [
  { ch: 'ᛗ', x: 560, y: 280, s: 96 },
  { ch: '⚙', x: 720, y: 220, s: 110 },
  { ch: '?', x: 900, y: 200, s: 130 },
  { ch: '!!', x: 1080, y: 210, s: 120 },
  { ch: '</>', x: 1250, y: 280, s: 92 },
  { ch: '◼', x: 640, y: 420, s: 70 },
  { ch: '✦', x: 820, y: 470, s: 84 },
  { ch: '{}', x: 1000, y: 460, s: 96 },
  { ch: '⟲', x: 1180, y: 430, s: 104 },
  { ch: '※', x: 1360, y: 340, s: 78 },
];
const COLORS = ['#ffb347', '#4dc9f6', '#cfe3ff'];

export const FxBehindMask: React.FC<{ maskDir?: string; count?: number; t0?: number }> = ({ maskDir = 'masks', count = 300, t0 = 20 }) => {
  const frame = useCurrentFrame();
  const idx = Math.min(Math.max(0, frame), count - 1);
  const mask = `url(${staticFile(`${maskDir}/pa_${String(idx).padStart(4, '0')}.png`)})`;
  const endA = frame > count - 40 ? Math.min(1, (frame - (count - 40)) / 30) : 0;

  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <OffthreadVideo src={staticFile('proxy.mp4')} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', zIndex: 10 }} />

      {/* 背后元素群：逐项 stagger ≤4 帧/项（成组入场节奏规范） */}
      <div style={{ position: 'absolute', inset: 0, zIndex: 15 }}>
        {ITEMS.map((it, i) => {
          const g = frame - (t0 + i * 4);
          if (g < 0) return null;
          const k = spring({ frame: g, fps: 30, config: { damping: 12, stiffness: 100, mass: 0.8 }, durationInFrames: 22 });
          const yy = it.y + Math.sin(g * 0.03 + i) * 10;
          const col = COLORS[i % 3];
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: it.x,
                top: yy,
                transform: `translate(-50%,-50%) scale(${0.5 + 0.5 * k}) rotate(${(1 - k) * 8 * (i % 2 ? 1 : -1)}deg)`,
                fontFamily: 'HeiLocal, sans-serif',
                fontSize: it.s,
                color: col,
                opacity: Math.min(1, k * 1.15) * (1 - endA),
                textShadow: `0 0 26px ${col}`,
                whiteSpace: 'nowrap',
              }}
            >
              {it.ch}
            </div>
          );
        })}
      </div>

      {/* 人像层：同源片 + 逐帧蒙版（把背后元素切在人身后面） */}
      <OffthreadVideo
        src={staticFile('proxy.mp4')}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', zIndex: 16, WebkitMaskImage: mask, maskImage: mask }}
      />

      <Vignette />
      <Tag text="FX-16 人物蒙版分层" />
    </AbsoluteFill>
  );
};
