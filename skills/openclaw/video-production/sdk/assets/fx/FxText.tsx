// FX-02 文字动效三连 —— 故障进场 / 模糊滑入 / 逐字浮现（原片上叠字）
// 来源：remotion-bits AnimatedText（bit-glitch-in / bit-blur-slide-word / char stagger）
import React from 'react';
import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  interpolate,
} from 'remotion';
import { AnimatedText } from 'remotion-bits';
import { Tag, Vignette, Dim } from './common';

const FPS = 30;
const DUR = 150;

const Beat: React.FC<{
  big: string;
  sub: string;
  accent: string;
  transition: Record<string, unknown>;
}> = ({ big, sub, accent, transition }) => {
  const frame = useCurrentFrame();
  const out = interpolate(frame, [42, 50], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 170,
        textAlign: 'center',
        opacity: out,
      }}
    >
      <AnimatedText
        transition={transition as any}
        style={{
          fontFamily: 'HeiLocal, sans-serif',
          fontSize: 138,
          fontWeight: 900,
          letterSpacing: 16,
          color: '#f4f8ff',
          textShadow: `0 0 46px ${accent}cc, 0 4px 22px rgba(0,0,0,0.65)`,
          display: 'inline-block',
        }}
      >
        {big}
      </AnimatedText>
      <div
        style={{
          fontFamily: 'HeiLocal, sans-serif',
          fontSize: 26,
          letterSpacing: 12,
          marginTop: 26,
          color: 'rgba(240,246,255,0.72)',
        }}
      >
        {sub}
      </div>
    </div>
  );
};

export const FxText: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, DUR], [1, 1.055]);
  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={10 * FPS} />
      </AbsoluteFill>
      <Dim v={0.3} />

      <Sequence from={0} durationInFrames={52}>
        <Beat
          big="故障进场"
          sub="GLITCH IN"
          accent="#4dc9f6"
          transition={{ glitch: [1, 0, 0.05, 0], opacity: [0, 1], duration: 40, frames: [0, 40] }}
        />
      </Sequence>
      <Sequence from={50} durationInFrames={52}>
        <Beat
          big="模糊滑入"
          sub="BLUR SLIDE"
          accent="#a78bfa"
          transition={{
            split: 'character',
            splitStagger: 2,
            y: [48, 0],
            blur: [14, 0],
            opacity: [0, 1],
            duration: 30,
            easing: 'easeOutCubic',
          }}
        />
      </Sequence>
      <Sequence from={100} durationInFrames={50}>
        <Beat
          big="逐字浮现"
          sub="CHAR STAGGER"
          accent="#34d399"
          transition={{
            split: 'character',
            splitStagger: 3,
            y: [28, 0],
            scale: [0.5, 1],
            opacity: [0, 1],
            duration: 26,
            easing: 'spring',
          }}
        />
      </Sequence>

      <Vignette />
      <Tag text="FX-02 · 文字动效 · remotion-bits" />
    </AbsoluteFill>
  );
};
