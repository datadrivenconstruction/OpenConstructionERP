// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Traffic-light badge for the estimate header. Quiet by design: it never opens
 * anything by itself, and it renders nothing when the module is off, the user
 * chose "off", or the backend module is not mounted.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { useDisplayMode, useEstimateCheck, useEstimateChecksEnabled } from './hooks';
import { DOT_CLASS, GROUP_ORDER, tx, worstTone } from './labels';
import { EstimateCheckPanel } from './EstimateCheckPanel';

export interface EstimateCheckBadgeProps {
  boqId: string;
  /** Scroll the BOQ grid to a position (click-through from a finding). */
  onJumpToPosition?: (positionId: string) => void;
}

export function EstimateCheckBadge({ boqId, onJumpToPosition }: EstimateCheckBadgeProps) {
  const { t } = useTranslation();
  const moduleOn = useEstimateChecksEnabled();
  const { data: mode } = useDisplayMode(moduleOn);
  const visible = moduleOn && mode !== undefined && mode !== 'off';
  const { data, isError } = useEstimateCheck(boqId, visible);
  const [open, setOpen] = useState(false);

  if (!visible || isError || !data) return null;

  const { warning, suspect } = data.counts;
  const expanded = mode === 'all' || mode === 'issues';
  const groups = GROUP_ORDER.map((g) => ({ g, items: data.kpis.filter((k) => k.group === g) })).filter(
    (x) => x.items.length > 0,
  );

  return (
    <>
      <button
        type="button"
        data-testid="estimate-check-badge"
        onClick={() => setOpen(true)}
        title={tx(t, 'estimate_checks.badge_hint')}
        aria-label={`${tx(t, 'estimate_checks.title')}: ${tx(t, 'estimate_checks.badge_aria', { warning, suspect })}`}
        className="inline-flex h-8 items-center gap-2 rounded-lg border border-border-light px-2.5 text-xs font-medium
                   text-content-secondary hover:bg-surface-secondary"
      >
        {warning === 0 && suspect === 0 ? (
          <span className="inline-flex items-center gap-1.5">
            <span className={clsx('h-2 w-2 rounded-full', DOT_CLASS.normal)} />
            {tx(t, 'estimate_checks.badge_ok')}
          </span>
        ) : (
          <>
            {warning > 0 && (
              <span className="inline-flex items-center gap-1" data-testid="estimate-check-badge-warning">
                <span className={clsx('h-2 w-2 rounded-full', DOT_CLASS.warning)} />
                {warning}
              </span>
            )}
            {suspect > 0 && (
              <span className="inline-flex items-center gap-1" data-testid="estimate-check-badge-suspect">
                <span className={clsx('h-2 w-2 rounded-full', DOT_CLASS.suspect)} />
                {suspect}
              </span>
            )}
          </>
        )}
        {expanded && (
          <span className="ml-1 inline-flex items-center gap-1 border-l border-border-light pl-2">
            {groups.map(({ g, items }) => (
              <span
                key={g}
                title={tx(t, `estimate_checks.group.${g}`)}
                className={clsx('h-2 w-2 rounded-full', DOT_CLASS[worstTone(items)])}
              />
            ))}
          </span>
        )}
      </button>
      <EstimateCheckPanel
        open={open}
        onClose={() => setOpen(false)}
        boqId={boqId}
        data={data}
        showAllByDefault={mode === 'all'}
        onJumpToPosition={(id) => {
          setOpen(false);
          onJumpToPosition?.(id);
        }}
      />
    </>
  );
}
