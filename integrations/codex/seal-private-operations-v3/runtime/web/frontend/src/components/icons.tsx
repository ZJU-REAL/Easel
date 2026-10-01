// 轻量线性图标（Lucide 风格，MIT 路径），stroke=currentColor，自适应色。
// 用来替换廉价的 emoji 图标，参考 ChatGPT / Stepfun 的简洁线性风格。
interface P { size?: number; className?: string; strokeWidth?: number; }

const svg = (size = 18, sw = 1.8) => ({
  width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: sw,
  strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
});

export const IconChat = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);
export const IconSkills = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="m12 3-1.6 4.9a2 2 0 0 1-1.3 1.3L4.2 10.8l4.9 1.6a2 2 0 0 1 1.3 1.3L12 18.6l1.6-4.9a2 2 0 0 1 1.3-1.3l4.9-1.6-4.9-1.6a2 2 0 0 1-1.3-1.3z" />
  </svg>
);
export const IconOutputs = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" />
  </svg>
);
export const IconAccounts = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <circle cx="7.5" cy="15.5" r="4.5" />
    <path d="m10.7 12.3 9.3-9.3" /><path d="m17 5 3 3" /><path d="m15 7 3 3" />
  </svg>
);
export const IconProfile = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
  </svg>
);
export const IconNewChat = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4Z" />
  </svg>
);
export const IconArrowUp = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}><path d="M12 19V5" /><path d="m5 12 7-7 7 7" /></svg>
);
export const IconStop = ({ size, className }: P) => (
  <svg {...svg(size)} className={className} fill="currentColor" stroke="none">
    <rect x="6" y="6" width="12" height="12" rx="2.5" />
  </svg>
);
export const IconCopy = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect x="9" y="9" width="13" height="13" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
);
export const IconCheck = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}><path d="M20 6 9 17l-5-5" /></svg>
);
export const IconEdit = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
  </svg>
);
export const IconRetry = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M8 16H3v5" />
  </svg>
);
export const IconArchive = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect x="2" y="3" width="20" height="5" rx="1" />
    <path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" /><path d="M10 12h4" />
  </svg>
);
export const IconUnarchive = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect x="2" y="3" width="20" height="5" rx="1" />
    <path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" /><path d="M12 18v-6" /><path d="m9 15 3-3 3 3" />
  </svg>
);
export const IconTrash = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M3 6h18" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
    <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
);
export const IconPlus = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}><path d="M5 12h14" /><path d="M12 5v14" /></svg>
);
export const IconChevron = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}><path d="m9 18 6-6-6-6" /></svg>
);

// ---- 分类图标（SKILL 卡 / Outputs 文件）----
export const IconVideo = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect x="2" y="4" width="20" height="16" rx="2.5" /><path d="M2 9h20M7 4v5M17 4v5" />
    <path d="m10.5 12.5 3.5 2-3.5 2z" fill="currentColor" stroke="none" />
  </svg>
);
export const IconImage = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect x="3" y="3" width="18" height="18" rx="2.5" /><circle cx="9" cy="9" r="1.8" />
    <path d="m21 15-3.6-3.6a2 2 0 0 0-2.8 0L6 20" />
  </svg>
);
export const IconMusic = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" />
  </svg>
);
export const IconMic = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect x="9" y="2" width="6" height="12" rx="3" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><path d="M12 19v3" />
  </svg>
);
export const IconText = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M4 7V5h16v2" /><path d="M9 20h6" /><path d="M12 5v15" />
  </svg>
);
export const IconChart = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M3 3v18h18" /><path d="M18 17V9" /><path d="M13 17V5" /><path d="M8 17v-3" />
  </svg>
);
export const IconSend = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" />
  </svg>
);
export const IconSearch = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
  </svg>
);
export const IconCompass = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <circle cx="12" cy="12" r="10" /><path d="m16.2 7.8-2.1 6.4-6.4 2.1 2.1-6.4z" />
  </svg>
);
export const IconLayout = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect x="3" y="3" width="18" height="18" rx="2.5" /><path d="M3 9h18M9 21V9" />
  </svg>
);
export const IconLayers = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="m12 2 9 5-9 5-9-5z" /><path d="m3 12 9 5 9-5" /><path d="m3 17 9 5 9-5" />
  </svg>
);
export const IconFile = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v5h5" />
  </svg>
);
export const IconRefresh = IconRetry;

export const IconFolder = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M4 20a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2Z" />
  </svg>
);

export const IconDashboard = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" />
  </svg>
);
export const IconFire = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" />
  </svg>
);
export const IconCalendar = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <rect x="3" y="4" width="18" height="18" rx="2" /><path d="M3 10h18M8 2v4M16 2v4" />
  </svg>
);
export const IconIdea = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="M9 18h6" /><path d="M10 22h4" />
    <path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5.76.76 1.23 1.52 1.41 2.5" />
  </svg>
);
export const IconBookmark = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
  </svg>
);
export const IconPublish = ({ size, className, strokeWidth }: P) => (
  <svg {...svg(size, strokeWidth)} className={className}>
    <path d="m3 11 18-5v12L3 14v-3z" /><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
  </svg>
);
