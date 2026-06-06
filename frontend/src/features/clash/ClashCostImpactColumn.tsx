/**
 * ClashCostImpactColumn — read-only money cell for the clash review table.
 *
 * Fetches the per-clash cost-impact payload from
 *   GET /v1/clash-cost-impact/clash/{clashId}/impact
 * and renders a right-aligned formatted-money cell with a hover tooltip
 * that surfaces the rework + labour breakdown and the confidence chip.
 *
 * When the figure is ``high`` confidence (i.e. at least one BOQ position
 * actually links to the clash's element GUIDs) the cell becomes a button
 * that opens a small popover listing each affected BOQ position. Every row
 * deep-links to the BOQ editor at ``/boq/{boq_id}?highlight={position_id}``
 * (consumed by BOQEditorPage's ``?highlight`` scroll+flash) so a quantity
 * surveyor can jump straight from the rework money to the exact lines the
 * factor was applied to - defensible numbers, not a black box.
 *
 * The endpoint is owned by the ``clash_cost_impact`` backend module —
 * this column is the unique-to-AGPL-ERP differentiator (competitors that
 * ship coordination without a BOQ side cannot wire clashes to construction
 * cost). The component fails soft: any 4xx / 5xx renders an em-dash so a
 * partial outage of the cost-impact service never breaks the clash row.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink, X } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';

/** Backend response shape — kept in lock-step with
 *  ``backend/app/modules/clash_cost_impact/schemas.py``.
 *
 *  NOTE: ``rework_subtotal`` and ``labour_subtotal`` are emitted as decimal
 *  *strings* on the wire (Pydantic ``field_serializer`` narrows Decimal to a
 *  string to avoid float-rounding drift). The other money fields are plain
 *  numbers. We type them as ``number | string`` and normalise with
 *  {@link toNum} before any arithmetic so a string never reaches
 *  ``Number.prototype.toFixed`` (which would throw and break the row). */
export interface ClashCostImpactComponents {
  rework_positions_total: number | string;
  rework_factor_pct: number | string;
  rework_subtotal: number | string;
  labour_hours: number | string;
  blended_rate: number | string;
  labour_subtotal: number | string;
}

/** Coerce a wire value (number or decimal string) to a finite number;
 *  falls back to 0 for null / undefined / unparseable input. */
function toNum(v: number | string | null | undefined): number {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

/** One BOQ position that participates in the clash's rework subtotal.
 *  ``boq_id`` is required to build the editor deep-link; older payloads
 *  that predate CONN-27 omit it, so the consumer treats a missing
 *  ``boq_id`` as "not navigable" and renders the row as plain text. */
export interface ClashAffectedPosition {
  position_id: string;
  boq_id?: string;
  ordinal: string;
  description: string;
  total: number;
}

export interface ClashCostImpactPayload {
  clash_id: string;
  currency: string;
  components: ClashCostImpactComponents;
  total_estimate: number;
  confidence: 'low' | 'medium' | 'high' | string;
  affected_positions: ClashAffectedPosition[];
}

export interface ClashCostImpactColumnProps {
  /** Clash id whose cost impact should render in this cell. */
  clashId: string;
  /** Project currency (falls back to the payload's own ``currency`` field
   *  if the prop is empty). Plumbed in by the parent so the formatter
   *  picks up project-level overrides without an extra round-trip. */
  currency?: string;
  /** Optional test-only overrides for the React Query options. */
  queryEnabled?: boolean;
}

/** Confidence pill — three-step ladder mirrored from the backend service. */
function ConfidenceChip({ confidence }: { confidence: string }) {
  const cls =
    confidence === 'high'
      ? 'bg-semantic-success-bg text-semantic-success'
      : confidence === 'medium'
        ? 'bg-semantic-warning-bg text-semantic-warning'
        : 'bg-surface-secondary text-content-tertiary';
  return (
    <span
      className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ${cls}`}
      data-testid="clash-cost-confidence"
    >
      {confidence}
    </span>
  );
}

/** Floating popover listing each affected BOQ position with a deep-link
 *  into the editor. Anchored to ``anchorRect`` (the clicked cell), rendered
 *  through a portal to ``document.body`` so the table's ``overflow-auto``
 *  body and sticky header never clip it (mirrors ElementInfoPopover). */
function AffectedPositionsPopover({
  anchorRect,
  positions,
  currency,
  onClose,
}: {
  anchorRect: DOMRect;
  positions: ClashAffectedPosition[];
  currency: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);

  // Close on Escape.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // Close on click outside.
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', handler, true);
    return () => document.removeEventListener('mousedown', handler, true);
  }, [onClose]);

  // Anchor below the cell, right-aligned to its right edge; clamp into the
  // viewport so a row near the bottom/right edge stays fully visible.
  const width = 320;
  const left = Math.max(
    8,
    Math.min(anchorRect.right - width, window.innerWidth - width - 8),
  );
  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - 16);

  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label={t('clash.cost.affected_positions', {
        defaultValue: 'Affected BOQ positions',
      })}
      data-testid="clash-cost-popover"
      className="rounded-xl border border-border-light bg-white shadow-2xl dark:border-border-dark dark:bg-surface-elevated"
      style={{ position: 'fixed', top, left, width, zIndex: 9999 }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between border-b border-border-light px-3 py-2 dark:border-border-dark">
        <span className="text-xs font-semibold text-content-primary">
          {t('clash.cost.affected_positions', {
            defaultValue: 'Affected BOQ positions',
          })}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-0.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          aria-label={t('common.close', { defaultValue: 'Close' })}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <ul className="max-h-64 divide-y divide-border-light/60 overflow-y-auto dark:divide-border-dark/60">
        {positions.map((p) => {
          const label = p.ordinal || p.position_id.slice(0, 8);
          const inner = (
            <>
              <div className="min-w-0">
                <div className="truncate text-xs font-medium text-content-primary">
                  {label}
                </div>
                {p.description && (
                  <div className="truncate text-[11px] text-content-tertiary">
                    {p.description}
                  </div>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <MoneyDisplay
                  amount={p.total}
                  currency={currency}
                  className="text-[11px] tabular-nums text-content-secondary"
                />
                {p.boq_id && (
                  <ExternalLink className="h-3 w-3 text-oe-blue" aria-hidden />
                )}
              </div>
            </>
          );
          // Only positions that carry an owning ``boq_id`` are routable;
          // a pre-CONN-27 payload (no boq_id) renders as plain text.
          return (
            <li key={p.position_id}>
              {p.boq_id ? (
                <Link
                  to={`/boq/${p.boq_id}?highlight=${encodeURIComponent(p.position_id)}`}
                  onClick={onClose}
                  data-testid="clash-cost-position-link"
                  className="flex items-center justify-between gap-2 px-3 py-2 hover:bg-surface-secondary/60 focus:bg-surface-secondary/60 focus:outline-none"
                >
                  {inner}
                </Link>
              ) : (
                <div className="flex items-center justify-between gap-2 px-3 py-2">
                  {inner}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>,
    document.body,
  );
}

export function ClashCostImpactColumn({
  clashId,
  currency,
  queryEnabled = true,
}: ClashCostImpactColumnProps) {
  const { t } = useTranslation();
  const cellRef = useRef<HTMLTableCellElement>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);

  const query = useQuery<ClashCostImpactPayload>({
    queryKey: ['clash-cost-impact', clashId],
    queryFn: () =>
      apiGet<ClashCostImpactPayload>(
        `/v1/clash-cost-impact/clash/${clashId}/impact`,
      ),
    enabled: queryEnabled && !!clashId,
    // Money rarely shifts mid-session — keep it cached for a minute so
    // scrolling the review table does not re-issue a network call per row.
    staleTime: 60_000,
    retry: false,
  });

  const openPopover = useCallback(() => {
    if (cellRef.current) {
      setAnchorRect(cellRef.current.getBoundingClientRect());
    }
  }, []);
  const closePopover = useCallback(() => setAnchorRect(null), []);

  if (query.isLoading) {
    return (
      <td
        className="px-3 py-2 text-right"
        data-testid="clash-cost-cell"
        data-state="loading"
      >
        <span
          className="ml-auto inline-block h-3 w-16 animate-pulse rounded bg-surface-tertiary"
          data-testid="clash-cost-skeleton"
        />
      </td>
    );
  }

  // Fail soft on any error / missing payload — an em-dash is preferable
  // to breaking the surrounding clash row.
  if (query.isError || !query.data) {
    return (
      <td
        className="px-3 py-2 text-right text-content-tertiary"
        data-testid="clash-cost-cell"
        data-state={query.isError ? 'error' : 'empty'}
      >
        &mdash;
      </td>
    );
  }

  const impact = query.data;
  const displayCurrency = currency || impact.currency || 'EUR';
  const c = impact.components;

  const tooltip =
    `Rework: ${toNum(c.rework_positions_total).toFixed(2)} ${displayCurrency} × ` +
    `${toNum(c.rework_factor_pct)}% = ${toNum(c.rework_subtotal).toFixed(2)} ${displayCurrency}\n` +
    `Labour: ${toNum(c.labour_hours)}h × ${toNum(c.blended_rate).toFixed(2)} ${displayCurrency} = ` +
    `${toNum(c.labour_subtotal).toFixed(2)} ${displayCurrency}\n` +
    `Confidence: ${impact.confidence}`;

  // Gate the BOQ drill-down on high confidence (the only band where a BOQ
  // position actually links to the clash; medium/low carry no positions).
  const positions = impact.affected_positions ?? [];
  const drillable = impact.confidence === 'high' && positions.length > 0;

  const moneyBlock = (
    <div className="flex items-center justify-end gap-1.5">
      <ConfidenceChip confidence={impact.confidence} />
      <MoneyDisplay
        amount={impact.total_estimate}
        currency={displayCurrency}
        className="tabular-nums text-content-primary"
      />
    </div>
  );

  return (
    <td
      ref={cellRef}
      className="px-3 py-2 text-right"
      title={tooltip}
      data-testid="clash-cost-cell"
      data-state="ready"
    >
      {drillable ? (
        <button
          type="button"
          onClick={openPopover}
          data-testid="clash-cost-trigger"
          aria-haspopup="dialog"
          aria-expanded={anchorRect !== null}
          aria-label={t('clash.cost.view_positions', {
            defaultValue: 'View {{count}} affected BOQ position(s)',
            count: positions.length,
          })}
          className="ml-auto rounded px-1 py-0.5 transition-colors hover:bg-surface-secondary/60 focus:bg-surface-secondary/60 focus:outline-none"
        >
          {moneyBlock}
        </button>
      ) : (
        moneyBlock
      )}
      {anchorRect && (
        <AffectedPositionsPopover
          anchorRect={anchorRect}
          positions={positions}
          currency={displayCurrency}
          onClose={closePopover}
        />
      )}
    </td>
  );
}

export default ClashCostImpactColumn;
