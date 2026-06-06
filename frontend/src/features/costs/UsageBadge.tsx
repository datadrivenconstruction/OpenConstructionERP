// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// UsageBadge — compact, instantly readable indicator of whether a cost item
// is already used in an estimate (BOQ position), and how many times.
//
// Replaces the old bare red dot, which conflated "rate certainty" with
// "usage" and never flipped because no usage was ever recorded. Usage data
// now comes from the real usage ledger via a single batched request per
// visible page (``POST /v1/costs/usage-counts``), passed down as a prop —
// no per-row fetch.
//
// Visual language (within the design system: Apple-tight radii, oe-blue /
// success tokens):
//   * Unused  → quiet outlined dot. Unused is NORMAL, not an error, so it is
//     muted, never red.
//   * Used    → filled success-tone pill with a check glyph + the count, and
//     a plain-words tooltip ("Used in N estimate positions").

import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';
import clsx from 'clsx';

interface UsageBadgeProps {
  /** Number of estimate (BOQ) positions this cost item is used in. 0 = unused. */
  count: number;
  /** Optional extra classes for the wrapper. */
  className?: string;
}

export function UsageBadge({ count, className }: UsageBadgeProps) {
  const { t } = useTranslation();

  if (count <= 0) {
    // Quiet "not yet used" state — a small outlined dot, no alarm colour.
    const label = t('costs.usage.unused', {
      defaultValue: 'Not used in any estimate yet',
    });
    return (
      <span
        title={label}
        aria-label={label}
        data-usage="0"
        className={clsx(
          'inline-flex h-2.5 w-2.5 shrink-0 rounded-full border border-content-tertiary/40',
          className,
        )}
      />
    );
  }

  const label = t('costs.usage.used_count', {
    count,
    defaultValue: 'Used in {{count}} estimate position',
    defaultValue_other: 'Used in {{count}} estimate positions',
  });

  return (
    <span
      title={label}
      aria-label={label}
      data-usage={count}
      className={clsx(
        'inline-flex items-center gap-0.5 shrink-0 rounded-md px-1.5 py-0.5',
        'bg-semantic-success/12 text-semantic-success ring-1 ring-inset ring-semantic-success/25',
        'text-2xs font-semibold tabular-nums',
        className,
      )}
    >
      <Check size={10} strokeWidth={3} className="shrink-0" />
      {count}
    </span>
  );
}
