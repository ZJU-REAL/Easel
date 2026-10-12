// FX-CardA v2 · A 态三形态示范（排版重排 2026.9.16）
// 排版依据 shot-composition：1920 网格 margin 104 / 8px 基线；单一焦点=人物；三形态件落三分位；负空间留白
// 动效依据 motion-art-direction：分级 hero(人物)/support(三形态件)/texture(暖光·微尘)；入场错峰 ease-out
import React from 'react';
import { AbsoluteFill, Easing, OffthreadVideo, staticFile, useCurrentFrame, interpolate, random } from 'remotion';
import { Tag } from './common';

const FPS = 30;
const EASE_OUT = Easing.out(Easing.cubic);

const SpecTag: React.FC<{ text: string; style?: React.CSSProperties }> = ({ text, style }) => (
  <div
    style={{
      position: 'absolute',
      padding: '7px 16px',
      borderRadius: 8,
      background: 'rgba(4,8,14,0.6)',
      border: '1px solid rgba(255,255,255,0.14)',
      fontFamily: 'HeiLocal, sans-serif',
      fontSize: 17,
      letterSpacing: 2,
      color: 'rgba(200,220,240,0.72)',
      whiteSpace: 'nowrap',
      zIndex: 60,
      ...style,
    }}
  >
    {text}
  </div>
);

const WarmGlow: React.FC = () => {
  const frame = useCurrentFrame();
  const breathe = 0.72 + Math.sin(frame / 52) * 0.28;
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 15,
        opacity: breathe,
        pointerEvents: 'none',
        background:
          'radial-gradient(ellipse 44% 38% at 7% 5%, rgba(255,198,130,0.16), rgba(255,198,130,0) 70%), radial-gradient(ellipse 40% 36% at 95% 97%, rgba(120,190,255,0.12), rgba(120,190,255,0) 72%)',
      }}
    />
  );
};

const Dust: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      {Array.from({ length: 14 }).map((_, i) => {
        const x = random(`a-x${i}`) * 1920;
        const y0 = random(`a-y${i}`) * 1080;
        const sp = 0.35 + random(`a-s${i}`) * 0.7;
        const y = (((y0 - frame * sp * 5) % 1080) + 1080) % 1080;
        const sway = Math.sin(frame / 52 + i * 1.7) * 24;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x + sway,
              top: y,
              width: 4,
              height: 4,
              borderRadius: '50%',
              background: 'rgba(255,214,170,0.5)',
              filter: 'blur(0.4px)',
              zIndex: 16,
            }}
          />
        );
      })}
    </>
  );
};

const Capsule: React.FC = () => {
  const frame = useCurrentFrame();
  const inY = interpolate(frame, [4, 30], [-24, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE_OUT });
  const inO = interpolate(frame, [4, 30], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const tilt = Math.sin(frame / 52) * 1.2;
  const sweep = interpolate(frame % 150, [0, 150], [-30, 132]);
  return (
    <div
      style={{
        position: 'absolute',
        top: 64,
        left: '50%',
        transform: `translateX(-50%) translateY(${inY}px) rotate(${tilt}deg)`,
        opacity: inO,
        width: 920,
        height: 96,
        borderRadius: 999,
        overflow: 'hidden',
        background: 'linear-gradient(135deg, rgba(255,255,255,0.11), rgba(255,255,255,0.035))',
        backdropFilter: 'blur(16px) saturate(140%)',
        border: '1px solid rgba(255,255,255,0.30)',
        boxShadow: '0 18px 60px -18px rgba(77,201,246,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 26,
        zIndex: 40,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: -90,
          top: -70,
          width: 340,
          height: 240,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(77,201,246,0.5), transparent 70%)',
          filter: 'blur(28px)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `linear-gradient(105deg, transparent 40%, rgba(255,255,255,0.2) ${sweep}%, transparent 62%)`,
        }}
      />
      {Array.from({ length: 12 }).map((_, i) => {
        const v = Math.sin(frame / 9 - i * 0.55);
        return (
          <div
            key={i}
            style={{
              width: 11,
              height: 11,
              borderRadius: '50%',
              background: '#4dc9f6',
              opacity: 0.4 + v * 0.4,
              transform: `scale(${1 + v * 0.5})`,
              boxShadow: '0 0 14px rgba(77,201,246,0.9)',
            }}
          />
        );
      })}
      <span
        style={{
          fontFamily: 'HeiLocal, sans-serif',
          fontSize: 30,
          letterSpacing: 8,
          color: 'rgba(242,250,255,0.96)',
          textShadow: '0 0 18px rgba(77,201,246,0.65)',
        }}
      >
        概念动画 · 胶囊
      </span>
    </div>
  );
};

const BigWords: React.FC = () => {
  const frame = useCurrentFrame();
  const opa = interpolate(frame, [10, 40], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const rise = interpolate(frame, [10, 40], [44, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE_OUT });
  const glow = 0.5 + Math.sin(frame / 16) * 0.26;
  const shadow = `0 0 ${22 + glow * 26}px rgba(178,120,255,${Math.min(1, glow + 0.3)}), 0 0 96px rgba(150,95,240,0.6)`;
  return (
    <div
      style={{
        position: 'absolute',
        left: 104,
        top: 236,
        opacity: opa,
        transform: `translateY(${rise}px)`,
        zIndex: 40,
      }}
    >
      <div style={{ fontFamily: 'MaShanLocal, serif', fontSize: 88, lineHeight: 1.14, color: '#fff', letterSpacing: 12, textShadow: shadow }}>浮空</div>
      <div style={{ fontFamily: 'MaShanLocal, serif', fontSize: 88, lineHeight: 1.14, color: '#fff', letterSpacing: 12, textShadow: shadow }}>大字</div>
    </div>
  );
};

const DataFloat: React.FC = () => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [16, 96], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const count = Math.round(p * 12800);
  const bars = [0.92, 0.55, 0.78, 0.42, 0.64];
  return (
    <div style={{ position: 'absolute', right: 104, top: 434, width: 560, zIndex: 40 }}>
      <div
        style={{
          fontFamily: 'HeiLocal, sans-serif',
          fontSize: 78,
          fontWeight: 700,
          color: '#34d399',
          textShadow: '0 0 30px rgba(52,211,153,0.7)',
        }}
      >
        {count.toLocaleString()}
      </div>
      <div style={{ fontFamily: 'HeiLocal, sans-serif', fontSize: 23, letterSpacing: 5, color: 'rgba(215,240,230,0.75)', marginTop: 2 }}>
        数据滚动 · count-up
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 20, height: 150, marginTop: 26 }}>
        {bars.map((b, i) => {
          const t = b * interpolate(frame, [24 + i * 7, 76 + i * 7], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE_OUT });
          return (
            <div key={i} style={{ width: 48, height: 150, display: 'flex', alignItems: 'flex-end' }}>
              <div
                style={{
                  width: '100%',
                  height: '100%',
                  borderRadius: 8,
                  background: 'linear-gradient(180deg, #34d399, rgba(52,211,153,0.3))',
                  boxShadow: '0 0 18px rgba(52,211,153,0.5)',
                  transform: `scaleY(${t})`,
                  transformOrigin: 'bottom',
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
};

export const FxCardA: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: '#05070d' }}>
      <AbsoluteFill style={{ zIndex: 10 }}>
        <OffthreadVideo
          src={staticFile('assets/proxy.mp4')}
          startFrom={8 * FPS}
          muted
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </AbsoluteFill>
      <WarmGlow />
      <Dust />
      <Capsule />
      <BigWords />
      <DataFloat />
      <SpecTag text="规格 · 胶囊 920 / radius 999 · 大字 88px · 数据件 560+ · 暖光微尘常动" style={{ right: 104, bottom: 30 }} />
      <Tag text="FX-CardA · A 态三形态（需求 #2/#3/#4/#10）" />
    </AbsoluteFill>
  );
};
