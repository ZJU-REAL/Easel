// FX-11 穿字隧道·素材版 —— 银河实拍当底 + AI 词条纵深飞过
// 素材：Mixkit（milky-way-seen-at-night, id 4148）；机制同 FX-05，换对得上的背景
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from 'remotion';
import { Particles, Spawner, Behavior, StaggeredMotion, resolvePoint, useViewportRect } from 'remotion-bits';
import { Tag, Vignette } from './common';

const FPS = 30;
const WORDS = ['Claude', 'DeepSeek', 'Qwen', 'GPT', 'Kimi', '开源', '大模型', 'AGI', 'MiniMax', '技术平权'];
const COLORS = ['#eaf2f7', '#9fd0ff', '#7fe7ff', '#c9b8ff', '#ffd98a'];

export const FxStockWords: React.FC = () => {
  const rect = useViewportRect();
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 150], [1, 1.05]);
  return (
    <AbsoluteFill style={{ backgroundColor: '#020308' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('stock/stock_milkyway.mp4')} startFrom={2 * FPS} />
      </AbsoluteFill>

      <Particles style={{ position: 'absolute', inset: 0, zIndex: 50, perspective: 4200 }}>
        <Spawner
          rate={0.3}
          max={90}
          area={{ width: rect.width, height: rect.height, depth: -rect.vmin * 55 }}
          position={resolvePoint(rect, { x: 'center', y: 'center' })}
          lifespan={105}
          velocity={{ x: 0, y: 0, z: rect.vmin * 9, varianceZ: rect.vmin * 9 }}
        >
          {WORDS.map((word, i) => (
            <StaggeredMotion
              key={i}
              style={{
                fontFamily: 'HeiLocal, sans-serif',
                fontSize: rect.vmin * 10,
                fontWeight: 900,
                letterSpacing: 4,
                whiteSpace: 'nowrap',
                color: COLORS[i % COLORS.length],
                textShadow: '0 0 38px rgba(140,190,255,0.65), 0 0 10px rgba(0,0,0,0.6)',
                textAlign: 'center',
              }}
              transition={{ opacity: [0, 1, 0.55, 0.12, 0] }}
            >
              {word}
            </StaggeredMotion>
          ))}
        </Spawner>
        <Behavior />
      </Particles>

      <Vignette />
      <Tag text="FX-11 · 穿字隧道·素材版 · 素材：Mixkit" />
    </AbsoluteFill>
  );
};
