// FX-01 碎屏转场 —— 画面在切点上冻结、炸成 25 块飞向 3D 纵深，露出下一段
// 来源：remotion-bits（bit-fracture-reassemble 改成视频版）
import React from 'react';
import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  interpolate,
} from 'remotion';
import { StaggeredMotion, randomFloat } from 'remotion-bits';
import { Tag, Vignette } from './common';

const FPS = 30;
const DUR = 150;
const A_START = 32.7;
const B_START = 35.05;
const ROWS = 5;
const COLS = 5;

const Tile: React.FC<{ i: number }> = ({ i }) => {
  const row = Math.floor(i / COLS);
  const col = i % COLS;
  const tw = 1920 / COLS;
  const th = 1080 / ROWS;
  const dx = randomFloat(`sx${i}`, -1500, 1500);
  const dy = randomFloat(`sy${i}`, -1100, 1100);
  const dz = randomFloat(`sz${i}`, -900, 500);
  const rx = randomFloat(`srx${i}`, -170, 170);
  const ry = randomFloat(`sry${i}`, -170, 170);
  const rz = randomFloat(`srz${i}`, -40, 40);
  const dist = Math.abs(row - 2) + Math.abs(col - 2);

  return (
    <StaggeredMotion
      transition={{
        x: [0, 0, dx],
        y: [0, 0, dy],
        z: [0, 0, dz],
        rotateX: [0, 0, rx],
        rotateY: [0, 0, ry],
        rotateZ: [0, 0, rz],
        opacity: [1, 1, 0],
        frames: [10, 66],
        delay: dist * 2.4,
        easing: 'easeInOutCubic',
      }}
      style={{
        position: 'absolute',
        left: col * tw,
        top: row * th,
        width: tw,
        height: th,
        perspective: '900px',
        transformStyle: 'preserve-3d',
      }}
    >
      <div
        style={{
          width: '100%',
          height: '100%',
          backgroundImage: `url(${staticFile('fx/frameA.png')})`,
          backgroundSize: '1920px 1080px',
          backgroundPosition: `${-col * tw}px ${-row * th}px`,
        }}
      />
    </StaggeredMotion>
  );
};

export const FxShatter: React.FC = () => {
  const frame = useCurrentFrame();
  const aZoom = interpolate(frame, [20, 66], [1, 1.07], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const flash = interpolate(frame, [64, 68, 74], [0, 0.85, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ backgroundColor: '#05070c' }}>
      {/* 段 A：真人原片，切点前微推近 */}
      <Sequence from={0} durationInFrames={70}>
        <AbsoluteFill style={{ transform: `scale(${aZoom})` }}>
          <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={Math.round(A_START * FPS)} muted />
        </AbsoluteFill>
      </Sequence>

      {/* 段 B：下一段原片，从碎块后面露出 */}
      <Sequence from={47} durationInFrames={103}>
        <AbsoluteFill>
          <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={Math.round(B_START * FPS)} />
        </AbsoluteFill>
      </Sequence>

      {/* 冻帧碎块：25 片 */}
      <Sequence from={46} durationInFrames={100}>
        <AbsoluteFill style={{ zIndex: 40, transformStyle: 'preserve-3d' }}>
          {Array.from({ length: ROWS * COLS }, (_, i) => (
            <Tile key={i} i={i} />
          ))}
        </AbsoluteFill>
      </Sequence>

      {/* 白色闪帧 */}
      <AbsoluteFill style={{ zIndex: 55, pointerEvents: 'none', background: '#fff', opacity: flash }} />

      <Vignette />
      <Tag text="FX-01 · 碎屏转场 · remotion-bits" />
    </AbsoluteFill>
  );
};
