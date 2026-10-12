// FX-06 极光光晕 —— 极光色团 + 辉光球悬浮在原片上（品牌片氛围）
// 来源：creativly.ai 组件库（AuroraBackground + GlowOrb，原样搬运）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { Tag, Vignette, Dim } from './common';

const Aurora: React.FC<{ colors?: string[]; speed?: number; opacity?: number }> = ({
  colors = ['#3b82f6', '#8b5cf6', '#f43f5e', '#10b981'],
  speed = 0.5,
  opacity = 0.3,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = (frame / fps) * speed;
  const blobs = colors.map((color, i) => {
    const angle = t + (i * Math.PI * 2) / colors.length;
    const x = 50 + Math.sin(angle) * 25 + Math.cos(angle * 0.7 + i) * 10;
    const y = 50 + Math.cos(angle * 0.8) * 20 + Math.sin(angle * 1.3 + i * 2) * 8;
    const scaleX = 1 + Math.sin(t * 0.5 + i * 1.5) * 0.3;
    const scaleY = 1 + Math.cos(t * 0.7 + i) * 0.2;
    return { color, x, y, scaleX, scaleY };
  });
  const fadeIn = interpolate(frame, [0, 30], [0, 1], { extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill style={{ opacity: opacity * fadeIn, overflow: 'hidden' }}>
      {blobs.map((blob, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: `${blob.x}%`,
            top: `${blob.y}%`,
            width: '60%',
            height: '60%',
            background: `radial-gradient(circle, ${blob.color}66 0%, ${blob.color}22 30%, transparent 70%)`,
            transform: `translate(-50%, -50%) scaleX(${blob.scaleX}) scaleY(${blob.scaleY})`,
            filter: 'blur(80px)',
          }}
        />
      ))}
    </AbsoluteFill>
  );
};

const GlowOrb: React.FC<{ x: number; y: number; size: number; color: string; delay?: number; pulseSpeed?: number }> = ({
  x,
  y,
  size,
  color,
  delay = 0,
  pulseSpeed = 0.03,
}) => {
  const frame = useCurrentFrame();
  const scale = 0.8 + 0.2 * Math.sin((frame + delay) * pulseSpeed);
  const opacity = interpolate(frame, [0, 30], [0, 0.6], { extrapolateRight: 'clamp' });
  return (
    <div
      style={{
        position: 'absolute',
        left: x - size / 2,
        top: y - size / 2,
        width: size,
        height: size,
        borderRadius: '50%',
        background: `radial-gradient(circle, ${color}40 0%, ${color}10 40%, transparent 70%)`,
        transform: `scale(${scale})`,
        opacity,
        filter: 'blur(40px)',
        pointerEvents: 'none',
      }}
    />
  );
};

export const FxAurora: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 150], [1, 1.045]);
  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={24 * 30} />
      </AbsoluteFill>
      <Dim v={0.3} />
      <AbsoluteFill style={{ zIndex: 40, mixBlendMode: 'screen' }}>
        <Aurora colors={['#2563eb', '#7c3aed', '#06b6d4']} speed={0.4} opacity={0.85} />
      </AbsoluteFill>
      <AbsoluteFill style={{ zIndex: 44 }}>
        <GlowOrb x={430} y={720} size={540} color="#22d3ee" delay={10} />
        <GlowOrb x={1520} y={330} size={470} color="#a78bfa" delay={40} />
      </AbsoluteFill>
      <Vignette />
      <Tag text="FX-06 · 极光光晕 · creativly.ai 组件库" />
    </AbsoluteFill>
  );
};
