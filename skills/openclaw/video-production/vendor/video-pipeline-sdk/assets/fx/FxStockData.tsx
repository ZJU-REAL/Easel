// FX-14 数据卡·素材版 —— 剪辑房实拍当底 + 玻璃数据卡
// 素材：Mixkit（boy-editing-a-video-on-a-computer, id 44071）
import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from 'remotion';
import { Tag, Vignette, Dim } from './common';

const ACCENTS = ['#4dc9f6', '#a78bfa', '#f472b6', '#34d399'];
const DATA = [
  { label: '脚本', value: 35 },
  { label: '剪辑', value: 58 },
  { label: '封面', value: 72 },
  { label: '分发', value: 92 },
];
const TRACK_W = 720;
const FPS = 30;

export const FxStockData: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 150], [1.03, 1]);
  const panelIn = interpolate(frame, [0, 22], [0, 1], { extrapolateRight: 'clamp' });
  const panelY = (1 - panelIn) * 60;

  return (
    <AbsoluteFill style={{ backgroundColor: '#020308' }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile('stock/stock_editor.mp4')} startFrom={3 * FPS} />
      </AbsoluteFill>
      <Dim v={0.3} />

      <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', zIndex: 50 }}>
        <div
          style={{
            width: 1240,
            padding: '50px 62px 56px',
            borderRadius: 26,
            background: 'linear-gradient(165deg, rgba(24,30,46,0.8), rgba(10,14,24,0.7))',
            border: '1px solid rgba(255,255,255,0.2)',
            backdropFilter: 'blur(16px) saturate(140%)',
            boxShadow: '0 40px 80px -26px rgba(0,0,0,0.7)',
            opacity: panelIn,
            transform: `translateY(${panelY}px)`,
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              height: 3,
              background: 'linear-gradient(90deg, rgba(77,201,246,0), #4dc9f6, rgba(77,201,246,0))',
            }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 42 }}>
            <div style={{ fontFamily: 'HeiLocal, sans-serif', fontSize: 40, fontWeight: 900, letterSpacing: 6, color: '#f4f8ff' }}>
              数据卡演示
            </div>
            <div style={{ fontFamily: 'HeiLocal, sans-serif', fontSize: 22, letterSpacing: 4, color: 'rgba(240,246,255,0.5)' }}>
              DEMO DATA · 非真实数据
            </div>
          </div>
          {DATA.map((d, i) => {
            const start = 18 + i * 9;
            const prog = interpolate(frame, [start, start + 42], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
            const eased = 1 - Math.pow(1 - prog, 3);
            const w = eased * (d.value / 100) * TRACK_W;
            const num = Math.round(eased * d.value);
            const ac = ACCENTS[i % ACCENTS.length];
            return (
              <div key={d.label} style={{ display: 'flex', alignItems: 'center', marginBottom: 30 }}>
                <div
                  style={{
                    width: 110,
                    fontFamily: 'HeiLocal, sans-serif',
                    fontSize: 30,
                    letterSpacing: 4,
                    color: 'rgba(240,246,255,0.88)',
                  }}
                >
                  {d.label}
                </div>
                <div
                  style={{
                    width: TRACK_W,
                    height: 26,
                    borderRadius: 999,
                    background: 'rgba(255,255,255,0.09)',
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: w,
                      height: '100%',
                      borderRadius: 999,
                      background: `linear-gradient(90deg, ${ac}88, ${ac})`,
                      boxShadow: `0 0 24px ${ac}66`,
                    }}
                  />
                </div>
                <div
                  style={{
                    width: 150,
                    textAlign: 'right',
                    fontFamily: 'HeiLocal, sans-serif',
                    fontSize: 38,
                    fontWeight: 900,
                    color: ac,
                    fontVariantNumeric: 'tabular-nums',
                    textShadow: `0 0 22px ${ac}77`,
                  }}
                >
                  {num}%
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>

      <Vignette />
      <Tag text="FX-14 · 数据卡·素材版 · 素材：Mixkit" />
    </AbsoluteFill>
  );
};
