// FX-CardB v2 · B 态舞台示范（排版重排 2026.9.16）
// 排版依据 shot-composition：margin 104；单一焦点=中央卡（hero）；侧卡叠层入位（±2°、深 90px 藏于 hero 之后）形成深度；
//                       背景去网格竖线（减噪）；规格标签 3→1；负空间留白
// 动效依据 motion-art-direction + review-animations：分级 hero/support/texture；入场错峰 stagger；ease-out；transform/opacity only
import React from 'react';
import { AbsoluteFill, Easing, useCurrentFrame, interpolate, random } from 'remotion';
import { Tag } from './common';

const EASE_OUT = Easing.out(Easing.cubic);

const glass = (accentGlow: string): React.CSSProperties => ({
  background: 'linear-gradient(135deg, rgba(255,255,255,0.10), rgba(255,255,255,0.032))',
  backdropFilter: 'blur(16px) saturate(140%)',
  border: '1px solid rgba(255,255,255,0.28)',
  borderRadius: 24,
  boxShadow: `0 24px 70px -26px rgba(0,0,0,0.75), 0 0 46px -16px ${accentGlow}`,
  overflow: 'hidden',
});

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

const Sweep: React.FC<{ dur?: number; delay?: number; strength?: number }> = ({ dur = 150, delay = 0, strength = 0.14 }) => {
  const frame = useCurrentFrame();
  const x = interpolate((frame + delay) % dur, [0, dur], [-40, 140]);
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        background: `linear-gradient(105deg, transparent 40%, rgba(255,255,255,${strength}) ${x}%, transparent 62%)`,
      }}
    />
  );
};

const Glow: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          zIndex: 1,
          opacity: 0.72 + Math.sin(frame / 56) * 0.24,
          background:
            'radial-gradient(ellipse 52% 44% at 50% 26%, rgba(56,132,255,0.15), rgba(56,132,255,0) 70%), radial-gradient(ellipse 38% 38% at 50% 98%, rgba(124,58,237,0.11), rgba(124,58,237,0) 72%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          zIndex: 1,
          left: '50%',
          top: 228,
          width: 920,
          height: 540,
          transform: 'translateX(-50%)',
          background: 'radial-gradient(ellipse, rgba(34,211,238,0.13), rgba(34,211,238,0) 70%)',
          filter: 'blur(10px)',
        }}
      />
    </>
  );
};

const Dust: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      {Array.from({ length: 14 }).map((_, i) => {
        const x = random(`b-x${i}`) * 1920;
        const y0 = random(`b-y${i}`) * 1080;
        const sp = 0.35 + random(`b-s${i}`) * 0.7;
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
              background: 'rgba(150,220,255,0.46)',
              filter: 'blur(0.4px)',
              zIndex: 2,
            }}
          />
        );
      })}
    </>
  );
};

const GridPulse: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 3, opacity: 0.35 }}>
      {Array.from({ length: 7 }).map((_, i) => (
        <div
          key={`h${i}`}
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: 90 + i * 150,
            height: 1,
            background: 'rgba(120,200,255,0.09)',
            opacity: 0.35 + Math.sin(frame / 50 + i) * 0.3,
          }}
        />
      ))}
    </div>
  );
};

const CenterCard: React.FC = () => {
  const frame = useCurrentFrame();
  const inO = interpolate(frame, [2, 32], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const inY = interpolate(frame, [2, 32], [20, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE_OUT });
  const inS = interpolate(frame, [2, 32], [0.965, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE_OUT });
  const pulse = 1 + Math.sin(frame / 13) * 0.06;
  return (
    <div
      style={{
        position: 'absolute',
        left: 640,
        top: 252,
        width: 640,
        height: 400,
        ...glass('rgba(34,211,238,0.45)'),
        zIndex: 24,
        opacity: inO,
        transform: `translateY(${inY}px) scale(${inS})`,
      }}
    >
      <Sweep dur={150} strength={0.15} />
      <div style={{ position: 'absolute', left: '50%', top: 124, transform: 'translate(-50%,-50%)' }}>
        {[0, 1, 2].map((i) => {
          const t = (((frame - 34 + i * 36) % 108) + 108) % 108 / 108;
          const started = frame >= 34 + i * 36 || frame >= 142;
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: -96,
                top: -96,
                width: 192,
                height: 192,
                borderRadius: '50%',
                border: '2px solid rgba(34,211,238,0.8)',
                transform: `scale(${0.4 + t * 1.25})`,
                opacity: started ? (1 - t) * 0.55 : 0,
              }}
            />
          );
        })}
        <div
          style={{
            position: 'absolute',
            left: -30,
            top: -30,
            width: 60,
            height: 60,
            borderRadius: '50%',
            background: 'radial-gradient(circle, #7ef0ff, #22d3ee 55%, rgba(34,211,238,0.25))',
            transform: `scale(${pulse})`,
            boxShadow: '0 0 44px rgba(34,211,238,0.85)',
          }}
        />
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 262, textAlign: 'center', fontFamily: 'HeiLocal, sans-serif', fontSize: 34, letterSpacing: 7, color: 'rgba(240,252,255,0.96)', textShadow: '0 0 20px rgba(34,211,238,0.5)' }}>
        概念演出 · 落在舞台中央
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 316, textAlign: 'center', fontFamily: 'HeiLocal, sans-serif', fontSize: 20, letterSpacing: 4, color: 'rgba(190,225,240,0.58)' }}>
        玻璃态 + 流光 + 卡内动效（动态材质）
      </div>
    </div>
  );
};

const LeftCard: React.FC = () => {
  const frame = useCurrentFrame();
  const inO = interpolate(frame, [36, 66], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const inX = interpolate(frame, [36, 66], [-30, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE_OUT });
  return (
    <div
      style={{
        position: 'absolute',
        left: 170,
        top: 430,
        width: 560,
        height: 330,
        ...glass('rgba(167,139,250,0.4)'),
        zIndex: 22,
        opacity: inO,
        transform: `translateX(${inX}px) rotate(-2deg)`,
      }}
    >
      <Sweep dur={170} delay={50} strength={0.1} />
      <div style={{ position: 'absolute', left: 36, top: 28, fontFamily: 'HeiLocal, sans-serif', fontSize: 22, letterSpacing: 5, color: 'rgba(230,220,255,0.85)' }}>左 · 动画卡</div>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 62, height: 150, display: 'flex', justifyContent: 'center', alignItems: 'flex-end', gap: 20 }}>
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} style={{ width: 22, height: 150, display: 'flex', alignItems: 'flex-end' }}>
            <div
              style={{
                width: '100%',
                height: '100%',
                borderRadius: 6,
                background: 'linear-gradient(180deg, #a78bfa, rgba(167,139,250,0.3))',
                boxShadow: '0 0 14px rgba(167,139,250,0.5)',
                transform: `scaleY(${0.24 + (Math.sin(frame / 16 + i * 0.9) * 0.5 + 0.5) * 0.62})`,
                transformOrigin: 'bottom',
              }}
            />
          </div>
        ))}
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 24, textAlign: 'center', fontFamily: 'HeiLocal, sans-serif', fontSize: 18, letterSpacing: 3, color: 'rgba(200,185,240,0.58)' }}>
        次级动画 · 560px 真卡
      </div>
    </div>
  );
};

const RightCard: React.FC = () => {
  const frame = useCurrentFrame();
  const inO = interpolate(frame, [44, 74], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const inX = interpolate(frame, [44, 74], [30, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE_OUT });
  const rows = [
    { label: '对位核验', v: 0.98, c: '#34d399' },
    { label: '尺寸达标', v: 0.94, c: '#22d3ee' },
    { label: '动态材质', v: 0.9, c: '#a78bfa' },
  ];
  return (
    <div
      style={{
        position: 'absolute',
        left: 1190,
        top: 430,
        width: 560,
        height: 330,
        ...glass('rgba(52,211,153,0.4)'),
        zIndex: 22,
        opacity: inO,
        transform: `translateX(${inX}px) rotate(2deg)`,
      }}
    >
      <Sweep dur={160} delay={90} strength={0.1} />
      <div style={{ position: 'absolute', left: 36, top: 28, fontFamily: 'HeiLocal, sans-serif', fontSize: 22, letterSpacing: 5, color: 'rgba(220,245,235,0.85)' }}>右 · 信息卡</div>
      {rows.map((r, i) => {
        const w = r.v * 100 * interpolate(frame, [64 + i * 10, 106 + i * 10], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE_OUT });
        return (
          <div key={i} style={{ position: 'absolute', left: 36, right: 36, top: 96 + i * 72 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'HeiLocal, sans-serif', fontSize: 20, color: 'rgba(225,245,238,0.85)', letterSpacing: 2 }}>
              <span>{r.label}</span>
              <span style={{ color: r.c }}>{Math.round(w)}%</span>
            </div>
            <div style={{ height: 10, borderRadius: 6, background: 'rgba(255,255,255,0.10)', marginTop: 12, overflow: 'hidden' }}>
              <div
                style={{
                  width: '100%',
                  height: '100%',
                  borderRadius: 6,
                  background: `linear-gradient(90deg, ${r.c}, rgba(255,255,255,0.55))`,
                  boxShadow: `0 0 14px ${r.c}`,
                  transform: `scaleX(${w / 100})`,
                  transformOrigin: 'left',
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};

const Chips: React.FC = () => {
  const frame = useCurrentFrame();
  const items = ['三层职责', '动态材质', '尺寸达标'];
  const colors = ['#4dc9f6', '#a78bfa', '#34d399'];
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, top: 852, display: 'flex', justifyContent: 'center', gap: 32, zIndex: 30 }}>
      {items.map((t, i) => {
        const inO = interpolate(frame, [72 + i * 12, 96 + i * 12], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
        const inY = interpolate(frame, [72 + i * 12, 96 + i * 12], [16, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE_OUT });
        return (
          <div
            key={i}
            style={{
              opacity: inO,
              transform: `translateY(${inY + Math.sin(frame / 26 + i * 1.3) * 3.5}px)`,
              padding: '12px 30px',
              borderRadius: 999,
              background: 'linear-gradient(135deg, rgba(255,255,255,0.10), rgba(255,255,255,0.03))',
              backdropFilter: 'blur(12px) saturate(140%)',
              border: '1px solid rgba(255,255,255,0.24)',
              fontFamily: 'HeiLocal, sans-serif',
              fontSize: 21,
              letterSpacing: 3,
              color: 'rgba(235,245,255,0.9)',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: colors[i], boxShadow: `0 0 12px ${colors[i]}` }} />
            {t}
          </div>
        );
      })}
    </div>
  );
};

const Floaters: React.FC = () => {
  const frame = useCurrentFrame();
  const inO = interpolate(frame, [96, 120], [0, 0.85], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const t1 = Math.round(interpolate(frame, [96, 150], [0, 1280], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }));
  return (
    <>
      <div style={{ position: 'absolute', right: 60, top: 116, zIndex: 18, opacity: inO, fontFamily: 'HeiLocal, sans-serif', fontSize: 26, color: 'rgba(160,215,240,0.7)', letterSpacing: 2 }}>
        {t1.toLocaleString()} <span style={{ color: '#34d399', fontSize: 20 }}>▲12%</span>
      </div>
      <div style={{ position: 'absolute', left: 60, top: 920, zIndex: 18, opacity: inO, fontFamily: 'HeiLocal, sans-serif', fontSize: 24, color: 'rgba(160,215,240,0.6)', letterSpacing: 2 }}>
        +86
      </div>
    </>
  );
};

const TopBar: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 5, background: 'rgba(255,255,255,0.14)', zIndex: 50, overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: `${(frame / 150) * 100}%`, background: 'rgba(120,220,255,0.22)' }} />
        <div
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${interpolate(frame % 120, [0, 120], [-12, 100])}%`,
            width: 210,
            background: 'linear-gradient(90deg, transparent, rgba(140,230,255,0.9), transparent)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: -1,
            left: `${(frame / 150) * 100}%`,
            width: 9,
            height: 7,
            borderRadius: 4,
            background: '#8ce6ff',
            boxShadow: '0 0 12px rgba(140,230,255,0.95)',
          }}
        />
      </div>
      <div style={{ position: 'absolute', top: 16, left: 32, zIndex: 60, fontFamily: 'HeiLocal, sans-serif', fontSize: 19, letterSpacing: 4, color: 'rgba(150,210,240,0.7)' }}>演示 · B 态舞台</div>
      <div style={{ position: 'absolute', top: 16, right: 32, zIndex: 60, fontFamily: 'HeiLocal, sans-serif', fontSize: 19, letterSpacing: 4, color: 'rgba(120,180,220,0.48)' }}>章节 1/1</div>
    </>
  );
};

const Noise: React.FC = () => (
  <div
    style={{
      position: 'absolute',
      inset: 0,
      zIndex: 55,
      opacity: 0.4,
      backgroundImage: 'radial-gradient(rgba(255,255,255,0.05) 1px, transparent 1px)',
      backgroundSize: '3px 3px',
    }}
  />
);

export const FxCardB: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: '#04070f' }}>
      <Glow />
      <Dust />
      <GridPulse />
      <CenterCard />
      <LeftCard />
      <RightCard />
      <Chips />
      <Floaters />
      <TopBar />
      <Noise />
      <SpecTag text="中央 640×400（hero）· 侧卡 560 ×2 叠层 ±2° · chips ×3 · 背景三层" style={{ right: 104, bottom: 30 }} />
      <Tag text="FX-CardB · B 态舞台全系统（需求 #2/#3/#4/#6/#10/#12）" />
    </AbsoluteFill>
  );
};
