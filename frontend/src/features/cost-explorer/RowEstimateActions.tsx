// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RowEstimateActions - the reprice entry point for a BOQ / estimate row.
//
// Additive and back-compatible: it renders NOTHING (today's behaviour, no new
// chrome) unless the row carries a cost-database code AND more than one base
// is loaded. When a second base exists it shows a compact "Reprice from base"
// control that opens the SubstitutePanel drawer, where the estimator can
// re-apply the same code's rate from another loaded base or save the
// composition as a cross-base assembly.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeftRight } from 'lucide-react';
import clsx from 'clsx';

import { apiGet } from '@/shared/lib/api';
import { SubstitutePanel, type RepricePosition } from './SubstitutePanel';

// Re-export so a consumer can pull the entry-point component and the position
// shape it needs from one module.
export type { RepricePosition };

export interface RowEstimateActionsProps {
  /** The row / position to reprice. */
  position: RepricePosition;
  /** Refetch hook fired after a successful reprice or assembly save. */
  onRepriced?: () => void;
  /** Icon-only rendering for dense grids (hides the text label). */
  compact?: boolean;
  className?: string;
}

/**
 * Compact reprice control that self-hides when repricing is not applicable.
 * Every instance shares one cached ``/v1/costs/regions/`` query (React Query
 * dedupes by key), so it is safe to render once per grid row.
 */
export function RowEstimateActions({
  position,
  onRepriced,
  compact = false,
  className,
}: RowEstimateActionsProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const { data: loadedRegions = [] } = useQuery({
    queryKey: ['costs', 'regions'],
    queryFn: () => apiGet<string[]>('/v1/costs/regions/'),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const hasCode = Boolean(position.code && position.code.trim());
  const otherBases = loadedRegions.filter((r) => r && r !== (position.region ?? ''));

  // Self-hide: no code, or a single (or zero) base loaded -> no new chrome.
  if (!hasCode || otherBases.length < 1) return null;

  const label = t('costs.reprice.action', { defaultValue: 'Reprice from base' });

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={label}
        aria-label={label}
        className={clsx(
          'inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1',
          'text-xs font-medium text-content-secondary',
          'hover:border-oe-blue/40 hover:bg-oe-blue-subtle hover:text-oe-blue-text',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/30',
          'transition-colors',
          className,
        )}
      >
        <ArrowLeftRight size={13} />
        {!compact && <span>{label}</span>}
      </button>
      <SubstitutePanel
        open={open}
        onClose={() => setOpen(false)}
        position={position}
        onRepriced={onRepriced}
      />
    </>
  );
}
