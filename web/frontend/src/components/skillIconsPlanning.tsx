import type { ComponentType } from 'react';

type Icon = ComponentType<{ size?: number }>;
const icon = (paths: string[]): Icon => ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {paths.map((d, i) => <path key={i} d={d} />)}
  </svg>
);

export const planningSkillIcons: Record<string, Icon> = {
  'skill-account-diagnosis': icon(['M4 19v-2a4 4 0 0 1 4-4h3','M8 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6','M13 17h2l1-3 2 5 1-2h2']),
  'skill-article-outline': icon(['M5 3h11l3 3v15H5z','M15 3v4h4','M8 10h7M8 14h8M8 18h5']),
  'skill-audience-profiler': icon(['M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6','M3 20v-2a6 6 0 0 1 12 0v2z','M17 5a3 3 0 0 1 0 6M18 14a4 4 0 0 1 3 4v2']),
  'skill-brand-onboarding': icon(['M5 4h14v17H5z','M8 3v3M16 3v3','M9 11a3 3 0 1 0 6 0 3 3 0 0 0-6 0','M8 18c1-3 7-3 8 0']),
  'skill-campaign-planner': icon(['M4 10v4h4l8 4V6L8 10z','M8 14l1 5h3l-1-4M19 9l2-1M19 15l2 1']),
  'skill-carousel-planner': icon(['M5 6h14v13H5z','M2 9v7M22 9v7','M8 9h8v5H8zM8 16h5']),
  'skill-collab-proposal': icon(['M3 12l4-4 4 2 2-1 6 5-4 5-4-3-2 1-6-5z','M13 9l3-2 5 4-2 3M7 8l-2-2M18 7l2-2']),
  'skill-content-calendar': icon(['M4 5h16v16H4z','M8 3v4M16 3v4M4 10h16','M8 14h2M14 14h2M8 18h2']),
  'skill-content-matrix': icon(['M4 4h16v16H4z','M4 9h16M4 15h16M10 4v16M15 4v16']),
  'skill-content-strategy': icon(['M4 20h16M6 17V8h4v9M14 17V4h4v13','M7 4l2-2 2 2']),
  'skill-hook-generator': icon(['M8 4v8a4 4 0 0 0 8 0V9','M13 11l3-3 3 3','M6 4h4']),
  'skill-livestream': icon(['M4 7h12v10H4z','M16 10l4-2v8l-4-2','M8 4a4 4 0 0 1 5 0M9 2a6 6 0 0 1 7 1']),
  'skill-positioning-analysis': icon(['M12 3a9 9 0 1 0 9 9 9 9 0 0 0-9-9','M12 7a5 5 0 1 0 5 5','M12 12l7-7M16 5h3v3']),
  'skill-topic-evaluator': icon(['M5 3h14v18H5z','M8 7h8M8 11h5','M9 16l2 2 4-4']),
  'skill-trend-rider': icon(['M3 17l5-5 3 3 7-7','M14 8h4v4','M5 21h14']),
  'skill-voice-builder': icon(['M12 4a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V7a3 3 0 0 0-3-3','M6 11a6 6 0 0 0 12 0M12 17v3M9 20h6']),
  'roi-calculator': icon(['M5 3h14v18H5z','M8 6h8v3H8z','M8 13h1M12 13h1M16 13h1M8 17h1M12 17h1M16 17h1']),
  'skill-comment-insights': icon(['M4 5h16v11H9l-4 3v-3H4z','M8 9h8M8 12h5','M17 12l2 2']),
  'skill-content-calendar-log': icon(['M4 5h16v16H4z','M8 3v4M16 3v4M4 10h16','M8 14h8M8 17h5']),
  'skill-content-postmortem': icon(['M4 5h12v14H4z','M7 9h6M7 12h4','M15 17l5 4M17 14a3 3 0 1 0 0 6 3 3 0 0 0 0-6']),
  'skill-data-tracker': icon(['M4 19V5M4 19h16','M7 15l4-4 3 2 5-6','M16 7h3v3']),
  'skill-post-scorer': icon(['M5 4h14v16H5z','M8 8h8M8 11h4','M12 14l1 2 2 .3-1.5 1.4.4 2-1.9-1-1.9 1 .4-2L9 16.3l2-.3z']),
  'skill-publish-analytics': icon(['M4 20V4M4 20h16','M7 17v-5h3v5M12 17V8h3v9M17 17V5h3v12']),
  'skill-publish-log': icon(['M6 4h13v17H6z','M4 7h4M4 11h4M4 15h4M4 19h4','M11 8h5M11 12h5M11 16h4']),
  'skill-social-performance-review': icon(['M5 4h14v17H5z','M8 16v-3M12 16V9M16 16v-5','M8 18h8']),
  'skill-strategy-advisor': icon(['M4 18h4l4-6 3 3 5-9','M17 6h3v3','M4 21h16']),
  'skill-xhs-analyzer': icon(['M4 5h16v14H4z','M7 15l3-3 2 2 5-5','M14 9h3v3']),
  'asset-manager': icon(['M3 6h7l2 2h9v11H3z','M7 12h10M7 15h6']),
  'batch-process': icon(['M5 4h11v11H5z','M8 8h11v11H8z','M11 12h5M11 15h5']),
  'skill-my-account': icon(['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8','M5 20a7 7 0 0 1 14 0z','M18 5h3M19.5 3.5v3']),
  'skill-profile-builder': icon(['M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7','M3 20a6 6 0 0 1 12 0z','M18 8v6M15 11h6']),
  'skill-profile-manager': icon(['M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6','M3 19a5 5 0 0 1 10 0','M16 13h5M18.5 10.5v5M16 19h5']),
  'skill-record-card': icon(['M5 4h14v16H5z','M8 8h8M8 12h8M8 16h5','M16 15l2 2 3-4']),
  'template-library': icon(['M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z']),
};
