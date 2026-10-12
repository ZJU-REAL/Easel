// FX-10 官方转场 —— TransitionSeries：时钟擦除 + 弹性滑入（官方转场包双式）
// 来源：@remotion/transitions（clockWipe / slide，timing 配置参照 editor-pro-max presets）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile } from 'remotion';
import { TransitionSeries, linearTiming, springTiming } from '@remotion/transitions';
import { clockWipe } from '@remotion/transitions/clock-wipe';
import { slide } from '@remotion/transitions/slide';
import { Tag, Vignette } from './common';

const Segment: React.FC<{ start: number; tag: string; grade?: string; scale?: number }> = ({
  start,
  tag,
  grade,
  scale = 1,
}) => (
  <AbsoluteFill style={{ transform: `scale(${scale})` }}>
    <AbsoluteFill style={{ filter: grade }}>
      <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={Math.round(start * 30)} />
    </AbsoluteFill>
    <div
      style={{
        position: 'absolute',
        top: 44,
        right: 52,
        padding: '10px 24px',
        borderRadius: 999,
        background: 'rgba(8,10,16,0.5)',
        border: '1px solid rgba(255,255,255,0.22)',
        backdropFilter: 'blur(10px)',
        fontFamily: 'HeiLocal, sans-serif',
        fontSize: 28,
        letterSpacing: 4,
        color: 'rgba(240,246,255,0.9)',
      }}
    >
      {tag}
    </div>
  </AbsoluteFill>
);

export const FxSwitch: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={80}>
          <Segment start={6} tag="段 ①" />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={clockWipe({ width: 1920, height: 1080 })}
          timing={linearTiming({ durationInFrames: 25 })}
        />
        <TransitionSeries.Sequence durationInFrames={80}>
          <Segment start={32.7} tag="段 ②" grade="sepia(0.3) saturate(1.15)" scale={1.06} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: 'from-right' })}
          timing={springTiming({ config: { damping: 14, stiffness: 100 }, durationInFrames: 25 })}
        />
        <TransitionSeries.Sequence durationInFrames={80}>
          <Segment start={52} tag="段 ③" grade="hue-rotate(18deg) saturate(1.3)" scale={1.03} />
        </TransitionSeries.Sequence>
      </TransitionSeries>
      <Vignette />
      <Tag text="FX-10 · 官方转场包 · @remotion/transitions" />
    </AbsoluteFill>
  );
};
