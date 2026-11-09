import type { ReactNode } from 'react';

interface ContentPanelProps {
  className?: string;
  header: ReactNode;
  children: ReactNode;
  label: string;
}

/** Shared bounded, keyboard-scrollable content panel. */
export default function ContentPanel({ className = '', header, children, label }: ContentPanelProps) {
  return (
    <section className={`card content-panel ${className}`}>
      {header}
      <div className="content-panel-body" role="region" aria-label={label} tabIndex={0}>{children}</div>
    </section>
  );
}
