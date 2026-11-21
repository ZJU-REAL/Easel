import type { Page } from './Sidebar';
import type { ComponentType } from 'react';
import { IconFire, IconIdea, IconCalendar, IconPublish, IconSkills } from './icons';

export const studioTools: { page: Page; Icon: ComponentType<{ size?: number }>; label: string; action: string }[] = [
  { page: 'trends', Icon: IconFire, label: '热点雷达', action: '查平台热榜' },
  { page: 'breakdown', Icon: IconSkills, label: '爆款拆解', action: '分析参考文案' },
  { page: 'ideas', Icon: IconIdea, label: '选题库', action: '整理待做选题' },
  { page: 'calendar', Icon: IconCalendar, label: '内容日历', action: '安排发布时间' },
  { page: 'publish', Icon: IconPublish, label: '发布中心', action: '预览并提交作品' },
];
