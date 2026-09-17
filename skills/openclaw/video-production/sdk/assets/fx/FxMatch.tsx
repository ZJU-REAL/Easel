// FX-Match 台词↔素材对位测试 —— 五镜连排：每句台词配"对得上"的实拍素材
// 源片：public/assets/proxy.mp4（110s 社会现象主题）；素材：Mixkit（见各行 credit）
import React from 'react';
import { AbsoluteFill, Audio, OffthreadVideo, Sequence, staticFile, useCurrentFrame, interpolate } from 'remotion';
import { Vignette } from './common';

const FPS = 30;
const SRC = 'assets/proxy.mp4';

type Scene = {
  src: number;
  dur: number;
  clip: string;
  clipStart: number;
  sub: string;
  no: string;
  credit: string;
};

const SCENES: Scene[] = [
  { src: 10.1, dur: 4.0, clip: 'stock/stock_scrambled.mp4', clipStart: 1.0, sub: '一些人在拿一堆别人听不懂的名词', no: '①', credit: 'scrambled dots · Mixkit' },
  { src: 14.1, dur: 3.1, clip: 'stock/stock_money.mp4', clipStart: 2.0, sub: '忽悠别人，然后把客卖出高价', no: '②', credit: 'money counting machine · Mixkit' },
  { src: 56.9, dur: 3.1, clip: 'stock/stock_worldmap.mp4', clipStart: 1.5, sub: '用AI技术改变，你觉得你能够改变一些人吗', no: '③', credit: 'world map digital · Mixkit' },
  { src: 60.0, dur: 3.0, clip: 'stock/stock_bubbles.mp4', clipStart: 2.0, sub: '真的有吗？根本就没有好吧', no: '④', credit: 'bubbles drifting · Mixkit' },
  { src: 74.6, dur: 3.8, clip: 'stock/stock_graphs.mp4', clipStart: 0.3, sub: '你们到底在卖什么呀，你们到底在讲什么呀', no: '⑤', credit: 'exposing graphs · Mixkit' },
];

const Pill: React.FC<{ text: string; style?: React.CSSProperties }> = ({ text, style }) => (
  <div
    style={{
      position: 'absolute',
      padding: '10px 22px',
      borderRadius: 999,
      background: 'rgba(8,10,16,0.55)',
      border: '1px solid rgba(255,255,255,0.2)',
      backdropFilter: 'blur(10px)',
      fontFamily: 'HeiLocal, sans-serif',
      fontSize: 24,
      letterSpacing: 3,
      color: 'rgba(240,246,255,0.92)',
      whiteSpace: 'nowrap',
      ...style,
    }}
  >
    {text}
  </div>
);

const SceneComp: React.FC<{ s: Scene }> = ({ s }) => {
  const frame = useCurrentFrame();
  const total = Math.round(s.dur * FPS);
  const zoom = interpolate(frame, [0, total], [1, 1.055]);
  return (
    <AbsoluteFill>
      {/* 素材大屏（缓慢推近） */}
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile(s.clip)} startFrom={Math.round(s.clipStart * FPS)} muted />
      </AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(180deg, rgba(0,0,0,0.3) 0%, rgba(0,0,0,0) 32%, rgba(0,0,0,0) 52%, rgba(0,0,0,0.46) 100%)',
        }}
      />
      <Vignette />

      {/* 右下真人 PiP（说话的原声在这路） */}
      <div
        style={{
          position: 'absolute',
          right: 36,
          bottom: 36,
          width: 420,
          height: 236,
          borderRadius: 18,
          overflow: 'hidden',
          border: '2px solid rgba(255,255,255,0.3)',
          boxShadow: '0 18px 50px -12px rgba(0,0,0,0.75)',
          zIndex: 80,
        }}
      >
        <OffthreadVideo
          src={staticFile(SRC)}
          startFrom={Math.round(s.src * FPS)}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </div>

      {/* 台词字幕（避开 PiP 区域） */}
      <div style={{ position: 'absolute', left: 0, right: 480, bottom: 56, textAlign: 'center', zIndex: 90 }}>
        <span
          style={{
            fontFamily: 'HeiLocal, sans-serif',
            fontSize: 36,
            color: '#fff',
            letterSpacing: 3,
            textShadow: '0 2px 18px rgba(0,0,0,0.85)',
            background: 'rgba(0,0,0,0.34)',
            padding: '10px 28px',
            borderRadius: 12,
          }}
        >
          {s.sub}
        </span>
      </div>

      {/* 镜号 + 素材署名 */}
      <Pill text={`镜头 ${s.no}`} style={{ top: 44, right: 52, zIndex: 95 }} />
      <Pill text={`素材：${s.credit}`} style={{ left: 52, bottom: 36, zIndex: 95, fontSize: 20 }} />
    </AbsoluteFill>
  );
};

export const FxMatch: React.FC = () => {
  let from = 0;
  return (
    <AbsoluteFill style={{ backgroundColor: '#020308' }}>
      {SCENES.map((s, i) => {
        const durF = Math.round(s.dur * FPS);
        const el = (
          <Sequence key={i} from={from} durationInFrames={durF}>
            <SceneComp s={s} />
          </Sequence>
        );
        from += durF;
        return el;
      })}

      {/* 转场音效（现成库找的，Mixkit，音量≤0.2） */}
      <Sequence from={105}>
        <Audio src={staticFile('sfx/mk-1490-fast-whoosh-transition.mp3')} volume={0.18} />
      </Sequence>
      <Sequence from={198}>
        <Audio src={staticFile('sfx/mk-3120-technology-transition-slide.mp3')} volume={0.18} />
      </Sequence>
      <Sequence from={296}>
        <Audio src={staticFile('sfx/mk-2350-magic-sparkle-whoosh.mp3')} volume={0.15} />
      </Sequence>
      <Sequence from={386}>
        <Audio src={staticFile('sfx/mk-1474-transition-windy-swoosh.mp3')} volume={0.17} />
      </Sequence>

      <Pill text="测试 · 台词 ↔ 素材对位" style={{ top: 44, left: 52, zIndex: 100 }} />
    </AbsoluteFill>
  );
};
