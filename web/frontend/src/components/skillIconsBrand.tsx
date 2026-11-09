import type { ComponentType, CSSProperties } from 'react';
import xhs from '../assets/platform/xiaohongshu.svg';
import zhihu from '../assets/platform/zhihu.svg';
import wechat from '../assets/platform/wechat.svg';
import bilibili from '../assets/platform/bilibili.svg';
import kuaishou from '../assets/platform/kuaishou.svg';

type Icon = ComponentType<{ size?: number }>;
type Action = 'publish' | 'analysis' | 'reply' | 'article' | 'create' | 'video';
const paths: Record<Action, string> = {
  publish: 'M3 7h10M9 3l4 4-4 4',
  analysis: 'M3 12V4M3 12h10M5 10l3-3 2 2 3-4',
  reply: 'M3 3h10v8H8l-3 2v-2H3zM6 7h4',
  article: 'M4 2h8v11H4zM6 5h4M6 8h4',
  create: 'M8 3v10M3 8h10',
  video: 'M3 3h10v10H3zM7 5l4 3-4 3z',
};
const brand = (source: string, action: Action): Icon => ({ size = 26 }) => (
  <span className="skill-brand-icon" style={{ width: size, height: size }} aria-hidden="true">
    <span className="skill-brand-mark" style={{ maskImage: `url("${source}")`, WebkitMaskImage: `url("${source}")` } as CSSProperties} />
    <svg className="skill-brand-action" viewBox="0 0 16 16"><path d={paths[action]} /></svg>
  </span>
);

export const brandSkillIcons: Record<string, Icon> = {
  'skill-xhs-publisher': brand(xhs, 'publish'),
  'skill-xhs-comment-reply': brand(xhs, 'reply'),
  'skill-xhs-analyzer': brand(xhs, 'analysis'),
  'card-xiaohongshu': brand(xhs, 'article'),
  'xhs-note-creator': brand(xhs, 'create'),
  'skill-zhihu-answer': brand(zhihu, 'reply'),
  'skill-zhihu-publisher': brand(zhihu, 'article'),
  'skill-wechat-publisher': brand(wechat, 'article'),
  'skill-channels-upload': brand(wechat, 'video'),
  'skill-bilibili-upload': brand(bilibili, 'publish'),
  'skill-kuaishou-upload': brand(kuaishou, 'publish'),
};
