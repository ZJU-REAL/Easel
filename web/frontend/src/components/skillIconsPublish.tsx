import type { ComponentType } from 'react';

type Icon = ComponentType<{ size?: number }>;
const props = (size = 18) => ({ width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const });

const Bilibili = ({size}: {size?: number}) => <svg {...props(size)}><rect x="3" y="6" width="18" height="14" rx="3"/><path d="m8 3 2 3m6-3-2 3M8 11v2m8-2v2m-6 3h4"/></svg>;
const Channels = ({size}: {size?: number}) => <svg {...props(size)}><rect x="4" y="3" width="16" height="18" rx="3"/><path d="m10 8 5 4-5 4z"/></svg>;
const Community = ({size}: {size?: number}) => <svg {...props(size)}><path d="M4 5h16v11H9l-5 4zM8 9h8M8 12h5"/></svg>;
const Repurpose = ({size}: {size?: number}) => <svg {...props(size)}><path d="M5 4h8l4 4v4H5zM13 4v4h4M9 16h10m-3-3 3 3-3 3"/></svg>;
const CrossPublish = ({size}: {size?: number}) => <svg {...props(size)}><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="12" r="2"/><circle cx="19" cy="19" r="2"/><path d="m7 11 10-5M7 12h10M7 13l10 5"/></svg>;
const Douyin = ({size}: {size?: number}) => <svg {...props(size)}><path d="M14 3v11a4 4 0 1 1-3-3.9M14 3c.5 3 2 4.5 5 5"/></svg>;
const Kuaishou = ({size}: {size?: number}) => <svg {...props(size)}><rect x="3" y="8" width="13" height="11" rx="3"/><circle cx="7" cy="5" r="2"/><circle cx="12" cy="5" r="2"/><path d="m16 11 5-2v9l-5-2z"/></svg>;
const Persona = ({size}: {size?: number}) => <svg {...props(size)}><circle cx="9" cy="8" r="3"/><path d="M3 19c0-3 2-5 6-5 1 0 2 .1 3 .5m2 2 2 2 4-5"/></svg>;
const Checklist = ({size}: {size?: number}) => <svg {...props(size)}><rect x="5" y="3" width="14" height="18" rx="2"/><path d="m8 8 1 1 2-2m2 1h3m-8 5 1 1 2-2m2 1h3m-8 5h8"/></svg>;
const Notify = ({size}: {size?: number}) => <svg {...props(size)}><path d="M6 17h12l-2-3V9a4 4 0 0 0-8 0v5zm4 3h4M12 3v2"/><path d="M19 7h2M3 7h2"/></svg>;
const Scheduler = ({size}: {size?: number}) => <svg {...props(size)}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18m-9 2v4l3 2"/></svg>;
const Quality = ({size}: {size?: number}) => <svg {...props(size)}><path d="m12 3 8 3v5c0 5-3 8-8 10-5-2-8-5-8-10V6z"/><path d="m8 12 3 3 5-6"/></svg>;
const Risk = ({size}: {size?: number}) => <svg {...props(size)}><circle cx="10" cy="10" r="6"/><path d="m14.5 14.5 5 5M10 7v4m0 2h.01"/></svg>;
const Seo = ({size}: {size?: number}) => <svg {...props(size)}><circle cx="10" cy="10" r="6"/><path d="m14 14 5 5M7 12l2-2 2 1 2-3"/></svg>;
const Link = ({size}: {size?: number}) => <svg {...props(size)}><path d="m9 15-1 1a4 4 0 0 1-6-6l3-3a4 4 0 0 1 6 0m4 2 1-1a4 4 0 0 1 6 6l-3 3a4 4 0 0 1-6 0M8 12h8"/></svg>;
const Toutiao = ({size}: {size?: number}) => <svg {...props(size)}><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 10h8M8 13h5M8 17h8"/></svg>;
const Wechat = ({size}: {size?: number}) => <svg {...props(size)}><path d="M14 16c-1 .4-2 .5-3 .5l-4 2 .5-2.5C4.8 15 3 13 3 10.5 3 7 6.5 4 11 4s8 3 8 6.5c0 .6-.1 1.2-.3 1.7"/><path d="M15 15h6v4h-2l-2 2v-2h-2zM8 10h.01M14 10h.01"/></svg>;
const XhsReply = ({size}: {size?: number}) => <svg {...props(size)}><path d="M4 5h16v11H9l-5 4zM8 10h8m-5-3-3 3 3 3"/></svg>;
const Xhs = ({size}: {size?: number}) => <svg {...props(size)}><rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 7h8M8 11h8M8 15h5m2 3 2-2"/></svg>;
const ZhihuAnswer = ({size}: {size?: number}) => <svg {...props(size)}><path d="M4 4h16v13H9l-5 3zM9 9a3 3 0 0 1 6 0c0 2-3 2-3 4m0 2h.01"/></svg>;
const ZhihuArticle = ({size}: {size?: number}) => <svg {...props(size)}><path d="M5 3h14v18H5zM8 7h8M8 11h8M8 15h5m2 4 3-3"/></svg>;

export const publishSkillIcons: Record<string, Icon> = {
  'skill-bilibili-upload': Bilibili, 'skill-channels-upload': Channels,
  'skill-community-ops': Community, 'skill-content-repurposing': Repurpose,
  'skill-cross-platform-publish': CrossPublish, 'skill-douyin-upload': Douyin,
  'skill-kuaishou-upload': Kuaishou, 'skill-persona-check': Persona,
  'skill-publish-checklist': Checklist, 'skill-publish-notify': Notify,
  'skill-publish-scheduler': Scheduler, 'skill-quality-gate': Quality,
  'skill-risk-scanner': Risk, 'skill-seo-quality': Seo, 'skill-short-link': Link,
  'skill-toutiao-publisher': Toutiao, 'skill-wechat-publisher': Wechat,
  'skill-xhs-comment-reply': XhsReply, 'skill-xhs-publisher': Xhs,
  'skill-zhihu-answer': ZhihuAnswer, 'skill-zhihu-publisher': ZhihuArticle,
};
