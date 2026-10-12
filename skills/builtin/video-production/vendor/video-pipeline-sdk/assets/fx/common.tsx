import React from 'react';
import { continueRender, delayRender, staticFile } from 'remotion';

const fontHandle = delayRender('fx-fonts');
const FONTS: [string, string][] = [
  ['HeiLocal', 'fonts/simhei.ttf'],
  ['MaShanLocal', 'fonts/MaShanZheng-Regular.ttf'],
];
if (typeof document !== 'undefined') {
  Promise.all(
    FONTS.map(async ([name, path]) => {
      const ff = new FontFace(name, `url(${staticFile(path)}) format('truetype')`);
      const loaded = await ff.load();
      (document as any).fonts.add(loaded);
    })
  )
    .then(() => continueRender(fontHandle))
    .catch(() => continueRender(fontHandle));
} else {
  continueRender(fontHandle);
}

export const Tag: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      position: 'absolute',
      left: 30,
      bottom: 26,
      zIndex: 120,
      padding: '10px 22px',
      borderRadius: 999,
      background: 'rgba(8,10,16,0.55)',
      border: '1px solid rgba(255,255,255,0.18)',
      backdropFilter: 'blur(12px)',
      fontFamily: 'HeiLocal, sans-serif',
      fontSize: 23,
      letterSpacing: 2,
      color: 'rgba(235,242,255,0.92)',
      whiteSpace: 'nowrap',
    }}
  >
    {text}
  </div>
);

export const Vignette: React.FC<{ z?: number }> = ({ z = 70 }) => (
  <div
    style={{
      position: 'absolute',
      inset: 0,
      zIndex: z,
      pointerEvents: 'none',
      background:
        'radial-gradient(ellipse at center, rgba(0,0,0,0) 48%, rgba(0,0,0,0.42) 100%)',
    }}
  />
);

export const Dim: React.FC<{ v: number; z?: number }> = ({ v, z = 30 }) => (
  <div
    style={{
      position: 'absolute',
      inset: 0,
      zIndex: z,
      pointerEvents: 'none',
      background: `rgba(4,6,12,${v})`,
    }}
  />
);
