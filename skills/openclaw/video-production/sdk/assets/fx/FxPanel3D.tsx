// FX-15 真透视 3D 卡 —— 有空间感的斜面板"立"进现实（真 CSS 3D，不是贴图斜切）
// 生产验证：口播片《管线自检》(2026-09) 实跑。要点——
//   ① perspective 必须带单位（'1400px'）；数字写法静默失效（面板退化成 2D 斜贴）
//   ② 厚度 = 背板层 translateZ(-20px)；投影 / 扫光各独立一层
//   ③ 全部帧驱动：入场弹簧 + 视差浮动 + 扫光缓移；入场后加入呼吸级浮沉
// 依赖：react / remotion；字体走 common.tsx（HeiLocal）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, spring, interpolate } from 'remotion';
import { Tag, Vignette } from './common';

const ACCENT = '#4dc9f6';

export const FxPanel3D: React.FC = () => {
  const frame = useCurrentFrame();
  const k = spring({ frame: Math.max(0, frame - 14), fps: 30, config: { damping: 11, stiffness: 120, mass: 0.8 }, durationInFrames: 26 });
  const bob = Math.sin(frame * 0.03) * 8;
  const ry = 22 + Math.sin(frame * 0.02) * 1.5;
  const rx = -4 + Math.sin(frame * 0.026) * 0.8;
  const W = 620;
  const H = 360;
  const px = 1430 + (1 - k) * 190;
  const py = 470 + bob;
  const sweep = interpolate(frame, [30, 100], [-420, 900], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <AbsoluteFill style={{ transform: 'scale(1.03)' }}>
        <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={9 * 30} />
      </AbsoluteFill>
      <Vignette />

      <AbsoluteFill style={{ perspective: '1400px', perspectiveOrigin: '58% 40%', zIndex: 10 }}>
        {/* 投影层 */}
        <div
          style={{
            position: 'absolute',
            left: px - W / 2 + 48,
            top: py - H / 2 + 56,
            width: W,
            height: H,
            borderRadius: 24,
            background: 'radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 75%)',
            opacity: k,
          }}
        />
        {/* 厚度背板 */}
        <div
          style={{
            position: 'absolute',
            left: px - W / 2,
            top: py - H / 2,
            width: W,
            height: H,
            borderRadius: 22,
            background: 'rgba(10,18,34,0.6)',
            border: '1px solid rgba(77,201,246,0.4)',
            transform: `rotateY(${ry}deg) rotateX(${rx}deg) translateZ(-20px)`,
          }}
        />
        {/* 卡面 */}
        <div
          style={{
            position: 'absolute',
            left: px - W / 2,
            top: py - H / 2,
            width: W,
            height: H,
            borderRadius: 22,
            overflow: 'hidden',
            border: '1px solid rgba(207,227,255,0.55)',
            background: 'linear-gradient(155deg, rgba(36,60,96,0.55) 0%, rgba(16,28,48,0.72) 100%)',
            boxShadow: '0 30px 80px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.35)',
            transform: `rotateY(${ry}deg) rotateX(${rx}deg)`,
            opacity: Math.min(1, k * 1.2),
          }}
        >
          {/* 扫光 */}
          <div
            style={{
              position: 'absolute',
              top: -80,
              bottom: -80,
              left: sweep,
              width: 140,
              background: 'linear-gradient(100deg, rgba(255,255,255,0) 0%, rgba(220,240,255,0.2) 50%, rgba(255,255,255,0) 100%)',
              transform: 'rotate(13deg)',
            }}
          />
          <div style={{ position: 'absolute', inset: 0, padding: '26px 32px', fontFamily: 'HeiLocal, sans-serif', color: '#eaf3ff' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <span style={{ fontSize: 30, color: '#ffb347' }}>◳</span>
              <span style={{ fontSize: 28, letterSpacing: 4 }}>3D CARD</span>
              <span style={{ marginLeft: 'auto', fontSize: 18, padding: '4px 14px', borderRadius: 999, border: '1px solid rgba(255,179,71,0.6)', color: '#ffb347' }}>v0.2</span>
            </div>
            <div style={{ height: 1, background: 'linear-gradient(90deg, rgba(77,201,246,0.8), rgba(77,201,246,0))', margin: '16px 0 18px' }} />
            {[['PERSPECTIVE', '✓'], ['THICKNESS', '✓'], ['SHADOW', '✓']].map((r, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  gap: 16,
                  marginBottom: 12,
                  opacity: interpolate(frame, [30 + i * 8, 42 + i * 8], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }),
                }}
              >
                <span style={{ fontSize: 22, letterSpacing: 3, color: 'rgba(190,215,245,0.66)' }}>{r[0]}</span>
                <span style={{ marginLeft: 'auto', fontSize: 24, color: '#5be37d' }}>{r[1]}</span>
              </div>
            ))}
            <div style={{ marginTop: 16, fontSize: 20, color: ACCENT, letterSpacing: 2 }}>真透视 · 非贴图</div>
          </div>
        </div>
      </AbsoluteFill>

      <Tag text="FX-15 真透视 3D 卡" />
    </AbsoluteFill>
  );
};
