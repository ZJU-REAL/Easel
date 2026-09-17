// FX-04 卡片叠阵 —— 8 张玻璃卡弹簧叠放入场、扇形成型（卡做足尺寸 ~880px 宽）
// 来源：remotion-bits StaggeredMotion（bit-card-stack 玻璃拟态改造）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from 'remotion';
import { StaggeredMotion } from 'remotion-bits';
import { Tag, Vignette, Dim } from './common';

const FPS = 30;
const DUR = 150;
const ACCENTS = ['#4dc9f6', '#a78bfa', '#f472b6', '#34d399'];
const LABELS = ['概念动画', '数据卡', '素材卡', '转场卡', '文字卡', '动势卡', '氛围卡', '图标卡'];

const CARD_W = 620;
const CARD_H = 620 * 0.66;

const Card: React.FC<{ i: number }> = ({ i }) => {
  const ac = ACCENTS[i % ACCENTS.length];
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        borderRadius: 24,
        background: 'linear-gradient(165deg, rgba(24,30,46,0.78), rgba(10,14,24,0.66))',
        border: '1px solid rgba(255,255,255,0.2)',
        backdropFilter: 'blur(16px) saturate(140%)',
        boxShadow: `0 34px 70px -22px rgba(0,0,0,0.65), 0 0 46px -12px ${ac}66`,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '34px 38px',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          background: `linear-gradient(90deg, ${ac}00, ${ac}, ${ac}00)`,
        }}
      />
      <div
        style={{
          fontFamily: 'HeiLocal, sans-serif',
          fontSize: 74,
          fontWeight: 900,
          color: ac,
          lineHeight: 1,
          textShadow: `0 0 26px ${ac}88`,
        }}
      >
        {String(i + 1).padStart(2, '0')}
      </div>
      <div>
        <div
          style={{
            width: 46,
            height: 2,
            background: 'rgba(255,255,255,0.35)',
            marginBottom: 16,
          }}
        />
        <div
          style={{
            fontFamily: 'HeiLocal, sans-serif',
            fontSize: 30,
            letterSpacing: 6,
            color: 'rgba(240,246,255,0.92)',
          }}
        >
          {LABELS[i % LABELS.length]}
        </div>
      </div>
    </div>
  );
};

export const FxCards: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, DUR], [1, 1.04]);
  const count = 8;

  return (
    <AbsoluteFill style={{ backgroundColor: '#04060b' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('proxy.mp4')} startFrom={55 * FPS} />
      </AbsoluteFill>
      <Dim v={0.3} />

      <AbsoluteFill
        style={{
          justifyContent: 'center',
          alignItems: 'center',
          perspective: '1400px',
          zIndex: 50,
        }}
      >
        <div
          style={{
            position: 'relative',
            width: CARD_W,
            height: CARD_H,
            transformStyle: 'preserve-3d',
            transform: 'translateX(-40px)',
          }}
        >
          <StaggeredMotion
            transition={{ y: [820, 0], opacity: [0, 1], frames: [6, 74], stagger: 4, easing: 'spring' }}
            style={{
              position: 'absolute',
              width: '100%',
              height: '100%',
              top: 0,
              left: 0,
              transformStyle: 'preserve-3d',
            }}
          >
            {Array.from({ length: count }, (_, i) => {
              const angle = (i - (count - 1) / 2) * 5.5;
              const xOffset = (i - (count - 1) / 2) * 78;
              const zOffset = i * -14;
              return (
                <div
                  key={i}
                  style={{
                    position: 'absolute',
                    width: '100%',
                    height: '100%',
                    transformStyle: 'preserve-3d',
                    zIndex: -i,
                  }}
                >
                  <div
                    style={{
                      width: '100%',
                      height: '100%',
                      transform: `translateZ(${zOffset}px) translateX(${xOffset}px) rotateZ(${angle}deg)`,
                    }}
                  >
                    <Card i={i} />
                  </div>
                </div>
              );
            })}
          </StaggeredMotion>
        </div>
      </AbsoluteFill>

      <Vignette />
      <Tag text="FX-04 · 卡片叠阵 · remotion-bits" />
    </AbsoluteFill>
  );
};
