// FX-12 萤火·素材版 —— 雪夜林实拍 + 双色萤火粒子
// 素材：Mixkit（moon-in-the-sky-a-snowy-forest, id 3350）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from 'remotion';
import { Particles, Spawner, Behavior, StaggeredMotion } from 'remotion-bits';
import { Tag, Vignette } from './common';

const FPS = 30;

export const FxStockFireflies: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 150], [1, 1.05]);
  return (
    <AbsoluteFill style={{ backgroundColor: '#020308' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('stock/stock_snowforest.mp4')} startFrom={1 * FPS} />
      </AbsoluteFill>

      <Particles style={{ position: 'absolute', inset: 0, zIndex: 50 }}>
        <Spawner
          rate={0.5}
          max={240}
          area={{ width: 1920, height: 1080 }}
          position={{ x: 960, y: 540 }}
          lifespan={95}
          velocity={{ x: 0.5, y: 0.4, varianceX: 1.2, varianceY: 1.2 }}
        >
          <StaggeredMotion transition={{ opacity: [0, 1, 0] }}>
            <div
              style={{
                width: 9,
                height: 9,
                borderRadius: '50%',
                backgroundColor: '#ffd98a',
                boxShadow: '0 0 26px 11px rgba(255,205,120,0.55)',
              }}
            />
          </StaggeredMotion>
        </Spawner>
        <Behavior wiggle={{ magnitude: 2.2, frequency: 0.1 }} wiggleVariance={1} />
      </Particles>

      <Particles style={{ position: 'absolute', inset: 0, zIndex: 52 }}>
        <Spawner
          rate={0.32}
          max={160}
          area={{ width: 1920, height: 1080 }}
          position={{ x: 960, y: 540 }}
          lifespan={85}
          velocity={{ x: 0.8, y: 0.6, varianceX: 2, varianceY: 2 }}
        >
          <StaggeredMotion transition={{ opacity: [0, 1, 0] }}>
            <div
              style={{
                width: 5,
                height: 5,
                borderRadius: '50%',
                backgroundColor: '#9fd0ff',
                boxShadow: '0 0 18px 7px rgba(140,190,255,0.45)',
              }}
            />
          </StaggeredMotion>
        </Spawner>
        <Behavior wiggle={{ magnitude: 3, frequency: 0.14 }} wiggleVariance={1} />
      </Particles>

      <Vignette />
      <Tag text="FX-12 · 萤火·素材版 · 素材：Mixkit" />
    </AbsoluteFill>
  );
};
