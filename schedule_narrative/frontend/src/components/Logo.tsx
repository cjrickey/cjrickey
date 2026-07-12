/**
 * Brand logo: the staggered Gantt-bar mark + wordmark. Bars use the theme's
 * oxide tokens (via CSS vars) so it stays correct in light and dark.
 */
export function LogoMark({ size = 38 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" className="shrink-0" aria-hidden="true">
      <rect x="14" y="24" width="44" height="13" rx="6.5" fill="var(--oxide)" />
      <rect x="30" y="43.5" width="48" height="13" rx="6.5" fill="var(--oxide-bright)" />
      <rect x="46" y="63" width="34" height="13" rx="6.5" fill="var(--oxide)" />
    </svg>
  );
}

export function Logo({ markSize = 38 }: { markSize?: number }) {
  return (
    <div className="flex items-center gap-3">
      <LogoMark size={markSize} />
      <div className="leading-none">
        <div className="text-lg font-bold tracking-tight text-ink">Schedule Narrative</div>
        <div className="mt-1 text-[10px] font-semibold tracking-[0.2em] text-oxide">GENERATOR</div>
      </div>
    </div>
  );
}
