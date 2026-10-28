// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * KpiStrip - a compact, full-width row of key figures shared by the
 * delivery and quality dashboard cards (RFI, submittals, inspections,
 * punch list, labour cost).
 *
 * Each stat renders as an equal-width cell (icon-free) with a small
 * uppercase label above a prominent number, separated by hairline
 * dividers. The strip stretches to fill its container so the cards read
 * dense and even instead of clustering their numbers on the left with an
 * empty right side.
 *
 * Colours come from theme tokens / semantic palette classes only (no
 * hardcoded hex), so light and dark both render correctly. Pass a
 * Tailwind text-colour class in ``tone`` to emphasise a value (e.g.
 * ``text-rose-600`` for an overdue count).
 */
import type { ReactNode } from 'react';
import clsx from 'clsx';

export interface KpiStat {
  /** Short uppercase label shown above the value. */
  label: string;
  /** The figure itself - number, percentage or formatted money. */
  value: ReactNode;
  /** Optional Tailwind text-colour class for the value. */
  tone?: string;
}

export function KpiStrip({ stats, className }: { stats: KpiStat[]; className?: string }) {
  if (stats.length === 0) return null;
  return (
    <div
      className={clsx(
        'grid grid-flow-col auto-cols-fr divide-x divide-border-light overflow-hidden rounded-lg border border-border-light',
        className,
      )}
    >
      {stats.map((stat, i) => (
        <div key={`${stat.label}-${i}`} className="min-w-0 px-3 py-2.5">
          <p className="truncate text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {stat.label}
          </p>
          <p
            className={clsx(
              'mt-0.5 text-lg font-semibold tabular-nums sm:text-xl',
              stat.tone ?? 'text-content-primary',
            )}
          >
            {stat.value}
          </p>
        </div>
      ))}
    </div>
  );
}

export default KpiStrip;
