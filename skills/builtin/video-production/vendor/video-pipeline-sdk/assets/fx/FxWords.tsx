// FX-05 穿字隧道 —— 词条从 3D 纵深飞向镜头（AI 圈词）
// 来源：remotion-bits Particles/Spawner/Behavior（bit-flying-through-words 中文词改造）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile } from 'remotion';
import { Particles, Spawner, Behavior, StaggeredMotion, resolvePoint, useViewportRect } from 'remotion-bits';
import { Tag, Vignette, Dim } from './common';

const FPS = 30;
const WORDS = ['Claude', 'DeepSeek', 'Qwen', 'GPT', 'Kimi', '开源', '大模型', 'AGI', 'MiniMax', '技术平权'];
const COLORS = ['#eaf2f7', '#9fd0ff', '#7fe7ff', '#c9b8ff', '#ffd98a'];

export const FxWords: React.FC = () => {
  const rect = useViewportRect();
  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={60 * FPS} />
      <Dim v={0.3} />

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
                fontSize: rect.vmin * 9.5,
                fontWeight: 900,
                letterSpacing: 4,
                whiteSpace: 'nowrap',
                color: COLORS[i % COLORS.length],
                textShadow: '0 0 34px rgba(120,180,255,0.5), 0 0 10px rgba(0,0,0,0.6)',
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
      <Tag text="FX-05 · 穿字隧道 · remotion-bits" />
    </AbsoluteFill>
  );
};
