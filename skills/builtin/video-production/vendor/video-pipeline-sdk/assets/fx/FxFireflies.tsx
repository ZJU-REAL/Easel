// FX-03 萤火氛围 —— 双色萤火粒子悬浮原片上（暖金 + 冰蓝，wiggle 漫游）
// 来源：remotion-bits Particles / Spawner / Behavior（bit-fireflies 双色改造）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from 'remotion';
import { Particles, Spawner, Behavior, StaggeredMotion } from 'remotion-bits';
import { Tag, Vignette, Dim } from './common';

const FPS = 30;
const DUR = 150;

export const FxFireflies: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, DUR], [1, 1.05]);
  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={42 * FPS} />
      </AbsoluteFill>
      <Dim v={0.3} />

      {/* 暖金萤火 */}
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
                boxShadow: '0 0 26px 11px rgba(255,205,120,0.5)',
              }}
            />
          </StaggeredMotion>
        </Spawner>
        <Behavior wiggle={{ magnitude: 2.2, frequency: 0.1 }} wiggleVariance={1} />
      </Particles>

      {/* 冰蓝小微尘 */}
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
                backgroundColor: '#7fe7ff',
                boxShadow: '0 0 18px 7px rgba(110,220,255,0.42)',
              }}
            />
          </StaggeredMotion>
        </Spawner>
        <Behavior wiggle={{ magnitude: 3, frequency: 0.14 }} wiggleVariance={1} />
      </Particles>

      <Vignette />
      <Tag text="FX-03 · 萤火氛围 · remotion-bits" />
    </AbsoluteFill>
  );
};
