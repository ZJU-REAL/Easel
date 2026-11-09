import type { ComponentType } from 'react';
import {
  Bilibili, Channels, Community, Repurpose, CrossPublish, Douyin, Kuaishou, Persona, Checklist, Notify, Scheduler, Quality, Risk, Seo, Link, Toutiao, Wechat, XhsReply, Xhs, ZhihuAnswer, ZhihuArticle
} from '../components/skillIconsPublish';

type Icon = ComponentType<{ size?: number }>;

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
