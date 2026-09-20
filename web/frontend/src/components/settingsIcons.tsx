// 设置面板图标（Lucide 风格线性图标，MIT 路径），写法与 icons.tsx 一致。
// 环境卡 / 导航 / 通道用；来源：lucide 官方 SVG。
interface P { size?: number; className?: string; strokeWidth?: number; }

const svg = (size = 18, sw = 1.8) => ({
  width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: sw,
  strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
});

export const IconGear = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

export const IconHexagon = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
  </svg>
);

export const IconFilm = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect width="18" height="18" x="3" y="3" rx="2" />
  <path d="M7 3v18" />
  <path d="M3 7.5h4" />
  <path d="M3 12h18" />
  <path d="M3 16.5h4" />
  <path d="M17 3v18" />
  <path d="M17 7.5h4" />
  <path d="M17 16.5h4" />
  </svg>
);

export const IconFileCode = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M10 12.5 8 15l2 2.5" />
  <path d="m14 12.5 2 2.5-2 2.5" />
  <path d="M14 2v4a2 2 0 0 0 2 2h4" />
  <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" />
  </svg>
);

export const IconAudioWaveform = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M2 13a2 2 0 0 0 2-2V7a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0V4a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0v-4a2 2 0 0 1 2-2" />
  </svg>
);

export const IconDatabase = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <ellipse cx="12" cy="5" rx="9" ry="3" />
  <path d="M3 5V19A9 3 0 0 0 21 19V5" />
  <path d="M3 12A9 3 0 0 0 21 12" />
  </svg>
);

export const IconPackage = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z" />
  <path d="M12 22V12" />
  <path d="m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7" />
  <path d="m7.5 4.27 9 5.15" />
  </svg>
);

export const IconMonitor = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect width="20" height="14" x="2" y="3" rx="2" />
  <line x1="8" x2="16" y1="21" y2="21" />
  <line x1="12" x2="12" y1="17" y2="21" />
  </svg>
);

export const IconTv = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect width="20" height="15" x="2" y="7" rx="2" ry="2" />
  <polyline points="17 2 12 7 7 2" />
  </svg>
);

export const IconGlobe = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <circle cx="12" cy="12" r="10" />
  <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
  <path d="M2 12h20" />
  </svg>
);

export const IconCompass = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z" />
  <circle cx="12" cy="12" r="10" />
  </svg>
);

export const IconLibrary = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="m16 6 4 14" />
  <path d="M12 6v14" />
  <path d="M8 8v12" />
  <path d="M4 4v16" />
  </svg>
);

export const IconSlidersHorizontal = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <line x1="21" x2="14" y1="4" y2="4" />
  <line x1="10" x2="3" y1="4" y2="4" />
  <line x1="21" x2="12" y1="12" y2="12" />
  <line x1="8" x2="3" y1="12" y2="12" />
  <line x1="21" x2="16" y1="20" y2="20" />
  <line x1="12" x2="3" y1="20" y2="20" />
  <line x1="14" x2="14" y1="2" y2="6" />
  <line x1="8" x2="8" y1="10" y2="14" />
  <line x1="16" x2="16" y1="18" y2="22" />
  </svg>
);

export const IconEllipsis = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <circle cx="12" cy="12" r="1" />
  <circle cx="19" cy="12" r="1" />
  <circle cx="5" cy="12" r="1" />
  </svg>
);
