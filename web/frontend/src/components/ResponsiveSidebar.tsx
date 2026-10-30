import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { ComponentProps, MouseEvent } from 'react';
import Sidebar from './Sidebar';

const NARROW_SCREEN = '(max-width: 760px)';
const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]';

/** Keep one mounted sidebar while changing only its narrow-screen presentation. */
export default function ResponsiveSidebar(props: ComponentProps<typeof Sidebar>) {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW_SCREEN).matches);
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const query = window.matchMedia(NARROW_SCREEN);
    const update = () => { setNarrow(query.matches); setOpen(false); };
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  // Also dismiss when navigation is initiated outside the sidebar.
  useEffect(() => { setOpen(false); }, [props.currentPage, props.activeSessionId, props.selectedPersona]);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel || !narrow) return;
    const trigger = triggerRef.current;
    if (!open) {
      if (panel.contains(document.activeElement)) trigger?.focus({ preventScroll: true });
      return;
    }
    const siblings = Array.from(panel.parentElement?.children || [])
      .filter((node): node is HTMLElement => node instanceof HTMLElement
        && node !== panel && node !== backdropRef.current);
    const previousInert = siblings.map(node => node.inert);
    siblings.forEach(node => { node.inert = true; });

    const focusable = () => Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE))
      .filter(node => node.tabIndex >= 0 && !node.matches(':disabled')
        && !node.closest('[inert]') && node.getClientRects().length > 0
        && getComputedStyle(node).visibility !== 'hidden');
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.isComposing) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
      } else if (event.key === 'Tab') {
        const items = focusable();
        const first = items[0], last = items[items.length - 1];
        if (!first) { event.preventDefault(); panel.focus(); return; }
        if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
          event.preventDefault(); first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKeyDown);
    closeRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      siblings.forEach((node, index) => { node.inert = previousInert[index]; });
      if (window.matchMedia(NARROW_SCREEN).matches) {
        trigger?.focus({ preventScroll: true });
      } else if (panel.contains(document.activeElement)
        && !(document.activeElement as HTMLElement).getClientRects().length) {
        focusable()[0]?.focus({ preventScroll: true });
      }
    };
  }, [narrow, open]);

  const dismiss = () => setOpen(false);
  const onNavigationClick = (event: MouseEvent<HTMLDivElement>) => {
    // Hosts can supply their own nav callbacks; they still use the native nav.
    if (event.target instanceof Element && event.target.closest('.sidebar-nav button, .sidebar-nav a')) dismiss();
  };

  return <>
    <div className="mobile-nav-bar">
      <button ref={triggerRef} type="button" className="sidebar-toggle" aria-label="打开导航"
        aria-expanded={narrow && open} aria-controls={panelId} onClick={() => setOpen(true)}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <span>Easel</span>
    </div>
    <div ref={backdropRef} className={`sidebar-backdrop${narrow && open ? ' is-open' : ''}`}
      aria-hidden="true" onClick={dismiss} />
    <div ref={panelRef} id={panelId} className={`sidebar-panel${narrow && open ? ' is-open' : ''}`}
      role={narrow ? 'dialog' : undefined} aria-modal={narrow && open ? true : undefined}
      aria-label={narrow ? '主导航' : undefined} aria-hidden={narrow && !open ? true : undefined}
      inert={narrow && !open} tabIndex={-1} onClickCapture={onNavigationClick}>
      <div className="sidebar-mobile-header">
        <span>导航</span>
        <button ref={closeRef} type="button" className="sidebar-close" aria-label="关闭导航" onClick={dismiss}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </div>
      <Sidebar {...props}
        onPageChange={page => { dismiss(); props.onPageChange(page); }}
        onSessionSelect={id => { dismiss(); props.onSessionSelect(id); }}
        onPersonaChange={persona => { dismiss(); props.onPersonaChange(persona); }}
        onNewProfile={() => { dismiss(); props.onNewProfile(); }}
        onNewChat={() => { dismiss(); props.onNewChat(); }}
        onOpenSettings={() => { dismiss(); props.onOpenSettings(); }} />
    </div>
  </>;
}
