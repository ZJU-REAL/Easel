// FX-13 漏光·素材版 —— 海上落日实拍 + 双层漏光
// 素材：Mixkit（red-sunset-over-the-ocean, id 15169）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from 'remotion';
import { LightLeak } from '@remotion/light-leaks';
import { Tag, Vignette } from './common';

const FPS = 30;

export const FxStockLeak: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 150], [1.05, 1]);
  return (
    <AbsoluteFill style={{ backgroundColor: '#020308' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('stock/stock_sunset.mp4')} startFrom={10 * FPS} />
      </AbsoluteFill>
      <AbsoluteFill style={{ zIndex: 50, mixBlendMode: 'screen', opacity: 0.9 }}>
        <LightLeak seed={5} hueShift={205} width={1920} height={1080} />
      </AbsoluteFill>
      <AbsoluteFill style={{ zIndex: 52, mixBlendMode: 'screen', opacity: 0.4 }}>
        <LightLeak seed={14} hueShift={35} width={1920} height={1080} />
      </AbsoluteFill>
      <Vignette />
      <Tag text="FX-13 · 漏光·素材版 · 素材：Mixkit" />
    </AbsoluteFill>
  );
};
