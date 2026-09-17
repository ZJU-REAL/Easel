// FX-07 排版三式 —— 遮罩上升 / 路径文字 / 描边生长（纯排版技巧）
// 来源：kinetic-typography 技能（mask reveal / text-on-path / stroke draw-on 配方）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, Sequence, staticFile, useCurrentFrame, interpolate } from 'remotion';
import { Tag, Vignette, Dim } from './common';

const easeOutExpo = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

const Caption: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      fontFamily: 'HeiLocal, sans-serif',
      fontSize: 26,
      letterSpacing: 10,
      marginTop: 40,
      color: 'rgba(240,246,255,0.66)',
      textAlign: 'center',
    }}
  >
    {text}
  </div>
);

// 第一式：遮罩上升
const MaskReveal: React.FC = () => {
  const frame = useCurrentFrame();
  const out = interpolate(frame, [50, 58], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const lines = ['把版面', '动起来'];
  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity: out }}>
      <div style={{ textAlign: 'center' }}>
        {lines.map((line, i) => {
          const p = easeOutExpo(clamp01((frame - 4 - i * 9) / 26));
          return (
            <div key={i} style={{ overflow: 'hidden', lineHeight: 1.02 }}>
              <div
                style={{
                  fontFamily: 'HeiLocal, sans-serif',
                  fontSize: 150,
                  fontWeight: 900,
                  letterSpacing: 14,
                  color: '#f4f8ff',
                  textShadow: '0 0 44px rgba(77,201,246,0.55), 0 6px 24px rgba(0,0,0,0.6)',
                  transform: `translateY(${(1 - p) * 112}%)`,
                }}
              >
                {line}
              </div>
            </div>
          );
        })}
        <Caption text="遮罩上升 MASK REVEAL" />
      </div>
    </AbsoluteFill>
  );
};

// 第二式：路径文字
const CurveText: React.FC = () => {
  const frame = useCurrentFrame();
  const out = interpolate(frame, [50, 56], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const offset = interpolate(frame, [2, 54], [-30, 85], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <svg width={1920} height={1080} viewBox="0 0 1920 1080" style={{ position: 'absolute', inset: 0 }}>
        <path id="fx-curve" d="M 120 700 Q 960 330 1800 700" fill="none" stroke="rgba(255,255,255,0.16)" strokeWidth={2} />
        <text fontFamily="HeiLocal, sans-serif" fontSize={92} fontWeight={900} letterSpacing={12} fill="#7fe7ff">
          <textPath href="#fx-curve" startOffset={`${offset}%`}>
            文字沿着弧线奔跑 · 文字沿着弧线奔跑 · 文字沿着弧线奔跑
          </textPath>
        </text>
      </svg>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 810, textAlign: 'center' }}>
        <Caption text="路径文字 TEXT ON A CURVE" />
      </div>
    </AbsoluteFill>
  );
};

// 第三式：描边生长
const DrawOn: React.FC = () => {
  const frame = useCurrentFrame();
  const p = easeOutCubic(clamp01((frame - 4) / 34));
  const p2 = easeOutCubic(clamp01((frame - 22) / 34));
  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            fontFamily: 'HeiLocal, sans-serif',
            fontSize: 176,
            fontWeight: 900,
            letterSpacing: 26,
            color: '#f4f8ff',
            textShadow: '0 0 50px rgba(255,217,138,0.5), 0 6px 26px rgba(0,0,0,0.6)',
            clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`,
            display: 'inline-block',
          }}
        >
          生长
        </div>
        <svg width={820} height={90} viewBox="0 0 820 90" style={{ display: 'block', margin: '-6px auto 0' }}>
          <path
            d="M 30 30 Q 410 90 790 30"
            fill="none"
            stroke="#ffd98a"
            strokeWidth={7}
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - p2}
          />
        </svg>
        <Caption text="描边生长 STROKE DRAW-ON" />
      </div>
    </AbsoluteFill>
  );
};

export const FxKinetic: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 160], [1.03, 1]);
  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={40 * 30} />
      </AbsoluteFill>
      <Dim v={0.3} />
      <Sequence from={0} durationInFrames={58}>
        <MaskReveal />
      </Sequence>
      <Sequence from={58} durationInFrames={56}>
        <CurveText />
      </Sequence>
      <Sequence from={114} durationInFrames={46}>
        <DrawOn />
      </Sequence>
      <Vignette />
      <Tag text="FX-07 · 排版三式 · kinetic-typography 技能" />
    </AbsoluteFill>
  );
};
