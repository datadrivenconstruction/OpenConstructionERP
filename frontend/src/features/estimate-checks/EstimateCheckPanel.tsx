// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Side panel with the estimate check: one calm row per figure, grouped, with
 * the usual range, how many past estimates it was compared with, a plain reason,
 * the positions behind it and "Accept, because ..." (the human confirms).
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { Settings2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { SideDrawer } from '@/shared/ui/SideDrawer';
import type { CheckResponse, KpiResult } from './api';
import { useAcceptFinding, useWithdrawAcceptance } from './hooks';
import { confidenceKey, DOT_CLASS, formatValue, GROUP_ORDER, toneOf, tx } from './labels';

export interface EstimateCheckPanelProps {
  open: boolean;
  onClose: () => void;
  boqId: string;
  data: CheckResponse;
  showAllByDefault: boolean;
  onJumpToPosition: (positionId: string) => void;
}

function isIssue(k: KpiResult): boolean {
  return k.status === 'suspect' || k.status === 'warning' || Boolean(k.accepted);
}

export function EstimateCheckPanel({
  open,
  onClose,
  boqId,
  data,
  showAllByDefault,
  onJumpToPosition,
}: EstimateCheckPanelProps) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(showAllByDefault);
  const visible = showAll ? data.kpis : data.kpis.filter(isIssue);

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title={tx(t, 'estimate_checks.title')}
      subtitle={tx(t, 'estimate_checks.panel_subtitle')}
      headerActions={
        <Link
          to="/estimate-checks"
          className="inline-flex items-center gap-1 text-xs text-content-secondary hover:underline"
          onClick={onClose}
        >
          <Settings2 size={14} />
          {tx(t, 'estimate_checks.open_settings')}
        </Link>
      }
    >
      <div className="flex flex-col gap-4" data-testid="estimate-check-panel">
        <div className="flex items-center justify-between gap-2 text-xs text-content-secondary">
          <span>{tx(t, `estimate_checks.compared_scope.${data.comparables_scope}`)}</span>
          <div role="group" className="inline-flex overflow-hidden rounded-lg border border-border-light">
            {[false, true].map((all) => (
              <button
                key={String(all)}
                type="button"
                aria-pressed={showAll === all}
                onClick={() => setShowAll(all)}
                className={clsx(
                  'px-2 py-1',
                  showAll === all ? 'bg-surface-secondary font-medium text-content-primary' : '',
                )}
              >
                {tx(t, all ? 'estimate_checks.filter_all' : 'estimate_checks.filter_issues')}
              </button>
            ))}
          </div>
        </div>

        {visible.length === 0 && (
          <p className="rounded-lg bg-surface-secondary px-3 py-4 text-sm text-content-secondary">
            <span className={clsx('mr-2 inline-block h-2 w-2 rounded-full', DOT_CLASS.normal)} />
            {tx(t, 'estimate_checks.all_clear')}
          </p>
        )}

        {GROUP_ORDER.map((g) => {
          const items = visible.filter((k) => k.group === g);
          if (items.length === 0) return null;
          return (
            <section key={g}>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {tx(t, `estimate_checks.group.${g}`)}
              </h3>
              <ul className="divide-y divide-border-light rounded-lg border border-border-light">
                {items.map((k) => (
                  <KpiRow
                    key={k.kpi_id}
                    k={k}
                    boqId={boqId}
                    currency={data.currency}
                    onJumpToPosition={onJumpToPosition}
                  />
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </SideDrawer>
  );
}

function KpiRow({
  k,
  boqId,
  currency,
  onJumpToPosition,
}: {
  k: KpiResult;
  boqId: string;
  currency: string;
  onJumpToPosition: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const [showPositions, setShowPositions] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [reason, setReason] = useState('');
  const accept = useAcceptFinding(boqId);
  const withdraw = useWithdrawAcceptance(boqId);
  const tone = toneOf(k);
  const locale = i18n.language || 'en';
  const fmt = (v: number | null) => formatValue(v, k.unit, locale, currency, k.unit_label);
  const reasonCount = k.unit === 'count' ? k.position_count : k.compared;
  const canAccept = (k.status === 'suspect' || k.status === 'warning') && !k.accepted;

  return (
    <li className="px-3 py-2.5" data-testid={`estimate-check-kpi-${k.kpi_id}`}>
      <div className="flex items-start gap-2">
        <span
          className={clsx('mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full', DOT_CLASS[tone])}
          aria-label={tx(t, `estimate_checks.status.${tone}`)}
          title={tx(t, `estimate_checks.status.${tone}`)}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm text-content-primary">{tx(t, `estimate_checks.kpi.${k.kpi_id}`)}</span>
            <span className="shrink-0 text-sm font-semibold tabular-nums text-content-primary">{fmt(k.value)}</span>
          </div>
          <p className="text-xs text-content-secondary">
            {tx(t, `estimate_checks.reason.${k.reason}`, { count: reasonCount })}
          </p>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {k.unit === 'count'
              ? tx(t, 'estimate_checks.expected_none')
              : k.low !== null && k.high !== null
                ? tx(t, 'estimate_checks.usual_range', { low: fmt(k.low), high: fmt(k.high) })
                : null}
            {k.status !== 'no_data' && k.unit !== 'count' && (
              <span className="ml-2">{tx(t, confidenceKey(k.confidence))}</span>
            )}
          </p>

          {k.accepted && (
            <div className="mt-1.5 flex items-start justify-between gap-2 rounded-md bg-surface-secondary px-2 py-1.5 text-xs">
              <span className="text-content-secondary">
                {tx(t, 'estimate_checks.accepted_note', { reason: k.accepted.reason })}
                {k.accepted.accepted_at && (
                  <span className="ml-1 text-content-tertiary">
                    ({new Date(k.accepted.accepted_at).toLocaleDateString(locale)})
                  </span>
                )}
              </span>
              <button
                type="button"
                className="shrink-0 text-content-secondary hover:underline"
                disabled={withdraw.isPending}
                onClick={() => withdraw.mutate(k.kpi_id)}
              >
                {tx(t, 'estimate_checks.undo_accept')}
              </button>
            </div>
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs">
            {k.positions.length > 0 && (
              <button
                type="button"
                className="text-oe-blue hover:underline"
                onClick={() => setShowPositions((v) => !v)}
              >
                {showPositions
                  ? tx(t, 'estimate_checks.hide_positions')
                  : tx(t, 'estimate_checks.show_positions', { count: k.position_count })}
              </button>
            )}
            {canAccept && !accepting && (
              <button
                type="button"
                className="text-content-secondary hover:underline"
                title={tx(t, 'estimate_checks.accept_hint')}
                onClick={() => setAccepting(true)}
              >
                {tx(t, 'estimate_checks.accept')}
              </button>
            )}
          </div>

          {showPositions && (
            <ul className="mt-1.5 max-h-48 overflow-auto rounded-md border border-border-light text-xs">
              {k.positions.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className="flex w-full gap-2 px-2 py-1 text-left hover:bg-surface-secondary"
                    onClick={() => onJumpToPosition(p.id)}
                  >
                    <span className="shrink-0 tabular-nums text-content-tertiary">{p.ordinal}</span>
                    <span className="truncate text-content-primary">{p.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {accepting && (
            <form
              className="mt-2 flex flex-col gap-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (reason.trim().length < 3) return;
                accept.mutate(
                  { kpiId: k.kpi_id, reason: reason.trim() },
                  { onSuccess: () => { setAccepting(false); setReason(''); } },
                );
              }}
            >
              <p className="text-2xs text-content-tertiary">{tx(t, 'estimate_checks.accept_hint')}</p>
              <textarea
                className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs"
                rows={2}
                maxLength={2000}
                value={reason}
                autoFocus
                placeholder={tx(t, 'estimate_checks.accept_placeholder')}
                onChange={(e) => setReason(e.target.value)}
              />
              <div className="flex gap-2">
                <Button type="submit" size="sm" disabled={reason.trim().length < 3 || accept.isPending}>
                  {tx(t, 'estimate_checks.accept_save')}
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setAccepting(false)}>
                  {tx(t, 'estimate_checks.cancel')}
                </Button>
              </div>
            </form>
          )}
        </div>
      </div>
    </li>
  );
}
