import { useRef, useState } from 'react';
import type { ChatSession } from '../lib/store';
import type { ComponentType } from 'react';
import {
  IconChat, IconSkills, IconOutputs, IconAccounts, IconProfile,
  IconNewChat, IconEdit, IconArchive, IconUnarchive, IconTrash, IconChevron,
  IconDashboard,
} from './icons';
import { IconGear } from './settingsIcons';
import ThemeToggle from './ThemeToggle';

export type Page = 'dashboard' | 'chat' | 'trends' | 'ideas' | 'calendar' | 'publish' | 'breakdown' | 'skills' | 'outputs' | 'accounts' | 'profile';

interface SidebarProps {
  currentPage: Page;
  onPageChange: (page: Page) => void;
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSessionSelect: (id: string) => void;
  onSessionDelete: (id: string) => void;
  onSessionRename: (id: string, title: string) => void;
  onSessionArchive: (id: string, archived: boolean) => void;
  onNewChat: () => void;
  gatewayStatus: string;
  apiDirect: boolean;
  agentRuntime: string;
  onOpenSettings: () => void;
}

const NAV: { page: Page; Icon: ComponentType<{ size?: number }>; label: string }[] = [
  { page: 'dashboard', Icon: IconDashboard, label: '工作台' },
  { page: 'chat', Icon: IconChat, label: '对话' },
  { page: 'skills', Icon: IconSkills, label: '技能库' },
  { page: 'outputs', Icon: IconOutputs, label: '内容库' },
  { page: 'accounts', Icon: IconAccounts, label: '账号' },
  { page: 'profile', Icon: IconProfile, label: '画像' },
];

export default function Sidebar({
  currentPage,
  onPageChange,
  sessions,
  activeSessionId,
  onSessionSelect,
  onSessionDelete,
  onSessionRename,
  onSessionArchive,
  onNewChat,
  gatewayStatus,
  apiDirect,
  onOpenSettings,
}: SidebarProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [showArchived, setShowArchived] = useState(false);

  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  function navigate(action: () => void) {
    setMenuOpen(false);
    action();
  }

  const startRename = (s: ChatSession) => { setRenamingId(s.id); setRenameValue(s.title); };
  const commitRename = () => {
    if (renamingId) onSessionRename(renamingId, renameValue);
    setRenamingId(null);
  };

  const active = sessions.filter((s) => !s.archived && (s.messages.length > 0 || s.id === activeSessionId));
  const archived = sessions.filter((s) => s.archived);

  const renderItem = (s: ChatSession, isArchived: boolean) => {
    if (renamingId === s.id) {
      return (
        <div key={s.id} className="session-item">
          <input
            className="session-rename-input"
            value={renameValue}
            autoFocus
            onChange={(e) => setRenameValue(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename();
              else if (e.key === 'Escape') setRenamingId(null);
            }}
            onBlur={commitRename}
          />
        </div>
      );
    }
    return (
      <div
        key={s.id}
        className={`session-item ${s.id === activeSessionId ? 'active' : ''}`}
        onClick={() => navigate(() => onSessionSelect(s.id))}
      >
        <span className="session-item-title">{s.title === 'New Chat' && s.messages.length === 0 ? '新对话' : s.title}</span>
        <div className="session-actions">
          <button className="session-act" title="重命名"
            onClick={(e) => { e.stopPropagation(); startRename(s); }}><IconEdit size={14} /></button>
          <button className="session-act" title={isArchived ? '取消归档' : '归档'}
            onClick={(e) => { e.stopPropagation(); onSessionArchive(s.id, !isArchived); }}>
            {isArchived ? <IconUnarchive size={14} /> : <IconArchive size={14} />}
          </button>
          <button className="session-act danger" title="删除"
            onClick={(e) => { e.stopPropagation(); onSessionDelete(s.id); }}><IconTrash size={14} /></button>
        </div>
      </div>
    );
  };

  return (
    <div className={menuOpen ? 'sidebar is-open' : 'sidebar'} onKeyDown={event => {
      if (event.key === 'Escape' && menuOpen) { setMenuOpen(false); menuButton.current?.focus(); }
    }}>
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <img className="sidebar-logo-icon" src="./static/easel-icon-transparent.png" alt="" />
          <h1>Easel</h1>
          <ThemeToggle />
          <button ref={menuButton} className="mobile-menu" aria-label={menuOpen ? '收起导航' : '打开导航'}
            aria-expanded={menuOpen} aria-controls="studio-navigation" onClick={() => setMenuOpen(open => !open)}>
            <IconDashboard size={18} /><span>导航</span>
          </button>
        </div>
      </div>

      <div id="studio-navigation" className="sidebar-body">
        <nav className="sidebar-nav" aria-label="主导航">
          <div className="studio-nav-group">
            <div className="studio-nav-label">工作空间</div>
            {NAV.map(({ page, Icon, label }) => (
              <button
                key={page}
                className={`nav-item ${currentPage === page ? 'active' : ''}`}
                aria-current={currentPage === page ? 'page' : undefined}
                onClick={() => navigate(() => onPageChange(page))}
              >
                <span className="nav-icon"><Icon size={18} /></span>
                {label}
              </button>
            ))}
          </div>
        </nav>

        <div className="sidebar-section">
          <div className="sidebar-section-header">
            <span className="sidebar-section-title">对话</span>
            <button className="new-chat-btn" onClick={() => navigate(onNewChat)} title="新建对话">
              <IconNewChat size={13} /> 新对话
            </button>
          </div>
          {active.map((s) => renderItem(s, false))}

          {archived.length > 0 && (
            <>
              <div className="archived-header" onClick={() => setShowArchived((v) => !v)}>
                <span className={`archived-chevron ${showArchived ? 'open' : ''}`}><IconChevron size={12} /></span>
                已归档 · {archived.length}
              </div>
              {showArchived && archived.map((s) => renderItem(s, true))}
            </>
          )}
        </div>

        <div className="sidebar-status">
          <span className={`status-dot ${gatewayStatus === 'connected' ? '' : 'offline'}`} />
          <span className="sidebar-status-text">{gatewayStatus === 'connected'
            ? (apiDirect ? '文字对话' : '创作助手')
            : gatewayStatus === 'disconnected'
              ? '请检查设置'
              : '加载中…'}</span>
          <button className="settings-gear" onClick={() => navigate(onOpenSettings)} title="设置（模型 · 环境 · 更多）">
            <IconGear size={13} /> 设置
          </button>
        </div>
      </div>
    </div>
  );
}
