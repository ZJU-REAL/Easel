export default function SealLogo({ size = 40, className = '' }: { size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="Seal 标志">
      <rect x="4" y="4" width="56" height="56" rx="18" fill="#ff2442"/>
      <path d="M44 20c-3.5-2.4-7.4-3.5-11.8-3.5-7.2 0-12 3.2-12 8.2 0 5.3 4.7 7.4 11.8 8.3 7 .9 11.8 3 11.8 8.5 0 5.1-4.8 8.2-12 8.2-4.8 0-8.8-1.2-12.8-3.8" fill="none" stroke="#fff" strokeWidth="6" strokeLinecap="round"/>
      <path d="M17 16h.1M47 48h.1" stroke="#ffd1d8" strokeWidth="4" strokeLinecap="round"/>
      <path d="m48 13 1.2 2.8L52 17l-2.8 1.2L48 21l-1.2-2.8L44 17l2.8-1.2Z" fill="#fff" opacity=".9"/>
    </svg>
  );
}
