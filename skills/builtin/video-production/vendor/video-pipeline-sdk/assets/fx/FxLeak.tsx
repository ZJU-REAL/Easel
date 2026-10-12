// FX-08 漏光胶片 —— 官方漏光包扫过原片（电影感光效）
// 来源：@remotion/light-leaks（官方新包，LightLeak 组件）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from 'remotion';
import { LightLeak } from '@remotion/light-leaks';
import { Tag, Vignette, Dim } from './common';

export const FxLeak: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 150], [1.04, 1]);
  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={18 * 30} />
      </AbsoluteFill>
      <Dim v={0.3} />
      <AbsoluteFill style={{ zIndex: 50, mixBlendMode: 'screen' }}>
        <LightLeak seed={5} hueShift={205} width={1920} height={1080} />
      </AbsoluteFill>
      <AbsoluteFill style={{ zIndex: 52, mixBlendMode: 'screen', opacity: 0.4 }}>
        <LightLeak seed={14} hueShift={35} width={1920} height={1080} />
      </AbsoluteFill>
      <Vignette />
      <Tag text="FX-08 · 漏光胶片 · @remotion/light-leaks（官方包）" />
    </AbsoluteFill>
  );
};
