import type { Page } from './Sidebar';
import type { ComponentType } from 'react';
import { IconDashboard, IconFire, IconIdea, IconCalendar, IconPublish, IconSkills } from './icons';

interface SubNavProps {
  current: Page;
  onNavigate: (page: Page) => void;
}

const TOOLS: { page: Page; Icon: ComponentType<{ size?: number }>; label: string }[] = [
  { page: 'trends', Icon: IconFire, label: '热点雷达' },
  { page: 'ideas', Icon: IconIdea, label: '选题库' },
  { page: 'calendar', Icon: IconCalendar, label: '内容日历' },
  { page: 'publish', Icon: IconPublish, label: '发布中心' },
  { page: 'breakdown', Icon: IconSkills, label: '爆款拆解' },
];

export default function SubNav({ current, onNavigate }: SubNavProps) {
  return (
    <div className="subnav">
      <button className="subnav-back" onClick={() => onNavigate('dashboard')} title="返回工作台">
        <IconDashboard size={15} /> 工作台
      </button>
      <span className="subnav-div" />
      <div className="subnav-tabs">
        {TOOLS.map(({ page, Icon, label }) => (
          <button key={page} className={`subnav-tab ${current === page ? 'active' : ''}`}
            onClick={() => onNavigate(page)}>
            <Icon size={14} />{label}
          </button>
        ))}
      </div>
    </div>
  );
}
