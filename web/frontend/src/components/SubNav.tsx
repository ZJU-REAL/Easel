import type { Page } from './Sidebar';
import { studioTools } from './studioTools';
import { IconDashboard } from './icons';

interface SubNavProps {
  current: Page;
  onNavigate: (page: Page) => void;
}



export default function SubNav({ current, onNavigate }: SubNavProps) {
  return (
    <nav className="subnav" aria-label="工作台工具">
      <button className="subnav-back" onClick={() => onNavigate('dashboard')} title="返回工作台">
        <IconDashboard size={15} /> 工作台
      </button>
      <span className="subnav-div" />
      <div className="subnav-tabs">
        {studioTools.map(({ page, Icon, label }) => (
          <button key={page} className={`subnav-tab ${current === page ? 'active' : ''}`}
            aria-current={current === page ? 'page' : undefined} onClick={() => onNavigate(page)}>
            <Icon size={14} />{label}
          </button>
        ))}
      </div>
    </nav>
  );
}
