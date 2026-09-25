// DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// 6D whole-life tab: EN 15978 carbon (A-B-C-D) beside ISO 15686-5 whole-life
// cost, model coverage as a traffic light, an optional carbon price that
// monetises the whole-life carbon, and the AI-proposes / human-confirms flow:
// compute (dry-run preview then save drafts) plus an accept/reject control on
// the resulting draft operational-carbon and whole-life cost lines.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  AlertOctagon,
  Box,
  Check,
  Coins,
  Gauge,
  Leaf,
  Loader2,
  Plus,
  Recycle,
  Sparkles,
  Trash2,
} from 'lucide-react';

import {
  AITrustNote,
  Badge,
  Button,
  Card,
  ConfidenceBadge,
  ConfirmDialog,
  EmptyState,
  MoneyDisplay,
  SkeletonTable,
  WideModal,
} from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';

import {
  computeLifeCycleCost,
  computeOperationalCarbon,
  confirmLifeCycleCost,
  confirmOperationalCarbon,
  deleteLifeCycleCost,
  deleteOperationalCarbon,
  getWholeLife,
  listInventories,
  listLifeCycleCost,
  listOperationalCarbon,
  type EmbodiedSource,
  type LifeCycleCostComputeResult,
  type LifeCycleCostEntry,
  type OperationalCarbonComputeResult,
  type OperationalCarbonEntry,
  type WholeLifeCarbonBreakdown,
  type WholeLifeCostBreakdown,
  type WholeLifeCoverage,
  type WholeLifeSummary,
} from './api';
import {
  coverageTone,
  formatCarbonKg,
  isDraftStatus,
  sourceLabel,
  sourcePillVariant,
  summarizeCompute,
  toNumber,
  type CoverageTone,
} from './sixd';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

/** How long a proposal preview list can get before it is capped. */
const PROPOSAL_CAP = 60;

const TONE_COLOR: Record<CoverageTone, string> = {
  good: 'bg-semantic-success',
  partial: 'bg-amber-500',
  none: 'bg-semantic-error',
};

/* --- Panel: inventory selector + dashboard --- */

export function WholeLifePanel({ projectId, currency }: { projectId: string; currency?: string }) {
  const { t } = useTranslation();
  const [inventoryId, setInventoryId] = useState('');

  const inventoriesQ = useQuery({
    queryKey: ['carbon', 'inventories', projectId],
    queryFn: () => listInventories(projectId),
  });
  const inventories = inventoriesQ.data ?? [];
  const effectiveId = inventoryId || inventories[0]?.id || '';

  if (inventoriesQ.isLoading) {
    return (
      <Card>
        <SkeletonTable rows={4} columns={3} />
      </Card>
    );
  }
  if (inventoriesQ.isError) {
    return (
      <EmptyState
        icon={<AlertOctagon size={22} />}
        title={t('carbon.load_error', {
          defaultValue: 'Could not load carbon data',
        })}
        description={getErrorMessage(inventoriesQ.error)}
        action={{
          label: t('common.retry', { defaultValue: 'Retry' }),
          onClick: () => void inventoriesQ.refetch(),
        }}
      />
    );
  }
  if (inventories.length === 0) {
    return (
      <EmptyState
        icon={<Recycle size={22} />}
        title={t('carbon.sixd.wl_no_inventories', {
          defaultValue: 'No inventories yet',
        })}
        description={t('carbon.sixd.wl_no_inventories_desc', {
          defaultValue:
            'Create a carbon inventory first, then compute its whole-life carbon and cost here.',
        })}
      />
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-content-tertiary">
        {t('carbon.sixd.wl_intro', {
          defaultValue:
            'A 6D whole-life view: EN 15978 carbon (A-B-C-D) beside ISO 15686-5 whole-life cost, with how much of the BIM model each figure covers. AI computes the lines, you confirm them.',
        })}
      </p>
      {inventories.length > 1 && (
        <div className="max-w-xs">
          <label className={labelCls} htmlFor="wl-inventory">
            {t('carbon.sixd.wl_pick_inventory', { defaultValue: 'Inventory' })}
          </label>
          <select
            id="wl-inventory"
            value={effectiveId}
            onChange={(e) => setInventoryId(e.target.value)}
            className={inputCls}
          >
            {inventories.map((inv) => (
              <option key={inv.id} value={inv.id}>
                {inv.name}
              </option>
            ))}
          </select>
        </div>
      )}
      {effectiveId && (
        <WholeLifeDashboard
          key={effectiveId}
          inventoryId={effectiveId}
          projectId={projectId}
          currency={currency}
        />
      )}
    </div>
  );
}

/* --- Dashboard --- */

function WholeLifeDashboard({
  inventoryId,
  projectId,
  currency,
}: {
  inventoryId: string;
  projectId: string;
  currency?: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [priceInput, setPriceInput] = useState('');
  const [appliedPrice, setAppliedPrice] = useState<number | null>(null);
  const [computeModal, setComputeModal] = useState<null | 'operational' | 'lcc'>(null);

  // Debounce the carbon-price input so typing does not fire a request per key.
  useEffect(() => {
    const n = Number(priceInput);
    const next = priceInput.trim() !== '' && Number.isFinite(n) && n >= 0 ? n : null;
    const id = setTimeout(() => setAppliedPrice(next), 300);
    return () => clearTimeout(id);
  }, [priceInput]);

  const wlQ = useQuery({
    queryKey: ['carbon', 'whole-life', inventoryId, appliedPrice],
    queryFn: () => getWholeLife(inventoryId, appliedPrice),
  });
  const opQ = useQuery({
    queryKey: ['carbon', 'operational', inventoryId],
    queryFn: () => listOperationalCarbon(inventoryId).catch(() => []),
  });
  const lccQ = useQuery({
    queryKey: ['carbon', 'lcc', inventoryId],
    queryFn: () => listLifeCycleCost(inventoryId).catch(() => []),
  });

  function invalidateAll() {
    qc.invalidateQueries({ queryKey: ['carbon', 'whole-life', inventoryId] });
    qc.invalidateQueries({ queryKey: ['carbon', 'operational', inventoryId] });
    qc.invalidateQueries({ queryKey: ['carbon', 'lcc', inventoryId] });
    qc.invalidateQueries({ queryKey: ['carbon', 'totals', inventoryId] });
  }

  const wl = wlQ.data;
  const costCurrency = wl?.cost.currency || currency || 'EUR';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          size="sm"
          icon={<Sparkles size={13} />}
          onClick={() => setComputeModal('operational')}
        >
          {t('carbon.sixd.wl_compute_operational', {
            defaultValue: 'Compute operational carbon',
          })}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          icon={<Sparkles size={13} />}
          onClick={() => setComputeModal('lcc')}
        >
          {t('carbon.sixd.wl_compute_lcc', {
            defaultValue: 'Compute whole-life cost',
          })}
        </Button>
      </div>

      {wlQ.isLoading ? (
        <Card>
          <SkeletonTable rows={6} columns={2} />
        </Card>
      ) : wlQ.isError ? (
        <EmptyState
          icon={<AlertOctagon size={22} />}
          title={t('carbon.sixd.wl_load_error', {
            defaultValue: 'Could not load the whole-life summary',
          })}
          description={getErrorMessage(wlQ.error)}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void wlQ.refetch(),
          }}
        />
      ) : wl ? (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <CarbonBreakdownCard carbon={wl.carbon} />
            <CostBreakdownCard cost={wl.cost} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <CoverageCard coverage={wl.coverage} />
            <CarbonPriceCard
              priceInput={priceInput}
              onPriceChange={setPriceInput}
              summary={wl}
              currency={costCurrency}
            />
          </div>
          <DraftReviewSection
            projectId={projectId}
            operational={opQ.data ?? []}
            lcc={lccQ.data ?? []}
            currency={costCurrency}
            onChanged={invalidateAll}
          />
        </>
      ) : null}

      {computeModal === 'operational' && (
        <OperationalComputeModal
          inventoryId={inventoryId}
          projectId={projectId}
          onClose={() => setComputeModal(null)}
          onDone={invalidateAll}
        />
      )}
      {computeModal === 'lcc' && (
        <LccComputeModal
          inventoryId={inventoryId}
          projectId={projectId}
          currency={costCurrency}
          onClose={() => setComputeModal(null)}
          onDone={invalidateAll}
        />
      )}
    </div>
  );
}

/* --- Breakdown cards --- */

function BreakdownRow({
  label,
  value,
  indent,
  strong,
}: {
  label: string;
  value: React.ReactNode;
  indent?: boolean;
  strong?: boolean;
}) {
  return (
    <li className={clsx('flex items-center justify-between gap-2', indent && 'ps-3')}>
      <span className={strong ? 'font-medium text-content-primary' : 'text-content-secondary'}>
        {label}
      </span>
      <span
        className={clsx(
          'tabular-nums',
          strong ? 'font-medium text-content-primary' : 'text-content-secondary',
        )}
      >
        {value}
      </span>
    </li>
  );
}

function CarbonBreakdownCard({ carbon }: { carbon: WholeLifeCarbonBreakdown }) {
  const { t } = useTranslation();
  const a1a3 = toNumber(carbon.a1a3);
  const a4 = toNumber(carbon.a4);
  const a5 = toNumber(carbon.a5);
  const a1a5 = toNumber(carbon.a1a5);
  const bEmbodied = toNumber(carbon.b_embodied);
  const b6 = toNumber(carbon.b6_operational);
  const bTotal = toNumber(carbon.b_total);
  const c = toNumber(carbon.c_end_of_life);
  const d = toNumber(carbon.d_beyond);
  const total = toNumber(carbon.whole_life_total);
  const seg = (v: number) => (total > 0 ? Math.max(0, (v / total) * 100) : 0);

  return (
    <Card>
      <div className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        <Leaf size={13} />
        {t('carbon.sixd.wl_carbon_title', {
          defaultValue: 'Whole-life carbon (EN 15978)',
        })}
      </div>
      <p className="text-2xl font-semibold tabular-nums text-content-primary">
        {formatCarbonKg(total)}
      </p>
      <p className="text-xs text-content-tertiary">
        {t('carbon.sixd.wl_carbon_total', {
          defaultValue: 'Whole-life carbon (A-C)',
        })}
      </p>

      {total > 0 && (
        <div
          className="mt-3 flex h-3 w-full overflow-hidden rounded-full bg-surface-secondary"
          role="img"
          aria-label={t('carbon.sixd.wl_carbon_bar', {
            defaultValue: 'Whole-life carbon split across A1-A5, B and C',
          })}
        >
          <div className="bg-oe-blue" style={{ width: `${seg(a1a5)}%` }} />
          <div className="bg-emerald-500" style={{ width: `${seg(bTotal)}%` }} />
          <div className="bg-amber-500" style={{ width: `${seg(c)}%` }} />
        </div>
      )}

      <ul className="mt-3 space-y-1 text-sm">
        <BreakdownRow
          label={t('carbon.sixd.wl_stage_a1a5', {
            defaultValue: 'A1-A5 embodied',
          })}
          value={formatCarbonKg(a1a5)}
          strong
        />
        <BreakdownRow
          label={t('carbon.sixd.wl_stage_a1a3', {
            defaultValue: 'A1-A3 product',
          })}
          value={formatCarbonKg(a1a3)}
          indent
        />
        <BreakdownRow
          label={t('carbon.sixd.wl_stage_a4', { defaultValue: 'A4 transport' })}
          value={formatCarbonKg(a4)}
          indent
        />
        <BreakdownRow
          label={t('carbon.sixd.wl_stage_a5', {
            defaultValue: 'A5 construction',
          })}
          value={formatCarbonKg(a5)}
          indent
        />
        <BreakdownRow
          label={t('carbon.sixd.wl_stage_b_total', {
            defaultValue: 'B use stage',
          })}
          value={formatCarbonKg(bTotal)}
          strong
        />
        <BreakdownRow
          label={t('carbon.sixd.wl_stage_b_embodied', {
            defaultValue: 'B1-B5 maintenance',
          })}
          value={formatCarbonKg(bEmbodied)}
          indent
        />
        <BreakdownRow
          label={t('carbon.sixd.wl_stage_b6', {
            defaultValue: 'B6 operational',
          })}
          value={formatCarbonKg(b6)}
          indent
        />
        <BreakdownRow
          label={t('carbon.sixd.wl_stage_c', { defaultValue: 'C end-of-life' })}
          value={formatCarbonKg(c)}
          strong
        />
      </ul>

      <div className="mt-3 rounded-md border border-dashed border-border-light p-2">
        <div className="flex items-center justify-between text-sm">
          <span className="text-content-secondary">
            {t('carbon.sixd.wl_stage_d', { defaultValue: 'D beyond boundary' })}
          </span>
          <span className="tabular-nums font-medium">{formatCarbonKg(d)}</span>
        </div>
        <p className="mt-0.5 text-xs text-content-tertiary">
          {t('carbon.sixd.wl_stage_d_hint', {
            defaultValue: 'Reported separately, not added to the whole-life total.',
          })}
        </p>
      </div>
    </Card>
  );
}

function CostBreakdownCard({ cost }: { cost: WholeLifeCostBreakdown }) {
  const { t } = useTranslation();
  const currency = cost.currency || 'EUR';
  const entryCount = cost.entry_count ?? 0;

  return (
    <Card>
      <div className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        <Coins size={13} />
        {t('carbon.sixd.wl_cost_title', {
          defaultValue: 'Whole-life cost (ISO 15686-5)',
        })}
      </div>
      {entryCount === 0 ? (
        <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
          {t('carbon.sixd.wl_cost_none', {
            defaultValue: 'No whole-life cost computed yet.',
          })}
        </p>
      ) : (
        <>
          <p className="text-2xl font-semibold tabular-nums text-content-primary">
            <MoneyDisplay amount={cost.whole_life_cost} currency={currency} />
          </p>
          <p className="text-xs text-content-tertiary">
            {t('carbon.sixd.wl_cost_total', {
              defaultValue: 'Whole-life cost',
            })}
          </p>
          <ul className="mt-3 space-y-1 text-sm">
            <BreakdownRow
              label={t('carbon.sixd.wl_cost_capex', { defaultValue: 'Capex' })}
              value={<MoneyDisplay amount={cost.capex} currency={currency} showCode />}
            />
            <BreakdownRow
              label={t('carbon.sixd.wl_cost_opex', {
                defaultValue: 'Opex (present value)',
              })}
              value={<MoneyDisplay amount={cost.opex_pv} currency={currency} showCode />}
            />
            <BreakdownRow
              label={t('carbon.sixd.wl_cost_replacement', {
                defaultValue: 'Replacement (present value)',
              })}
              value={<MoneyDisplay amount={cost.replacement_pv} currency={currency} showCode />}
            />
            <BreakdownRow
              label={t('carbon.sixd.wl_cost_eol', {
                defaultValue: 'End-of-life (present value)',
              })}
              value={<MoneyDisplay amount={cost.eol_pv} currency={currency} showCode />}
            />
            {Number(cost.residual_value_pv) > 0 && (
              <BreakdownRow
                label={t('carbon.sixd.wl_cost_residual', {
                  defaultValue: 'Less residual value (present value)',
                })}
                value={
                  <MoneyDisplay
                    amount={`-${cost.residual_value_pv}`}
                    currency={currency}
                    showCode
                  />
                }
              />
            )}
          </ul>
          <p className="mt-2 text-xs text-content-tertiary">
            {t('carbon.sixd.wl_cost_entries', {
              defaultValue: '{{count}} cost lines',
              count: entryCount,
            })}
          </p>
        </>
      )}
    </Card>
  );
}

/* --- Coverage traffic light --- */

function CoverageRow({
  label,
  linked,
  total,
  pct,
}: {
  label: string;
  linked: number;
  total: number;
  pct: number;
}) {
  const { t } = useTranslation();
  const tone = coverageTone(pct);
  const safePct = Number.isFinite(pct) ? pct : 0;
  return (
    <li>
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="flex items-center gap-1.5">
          <span
            className={clsx('inline-block h-2 w-2 rounded-full', TONE_COLOR[tone])}
            aria-hidden="true"
          />
          <span className="text-content-secondary">{label}</span>
        </span>
        <span className="tabular-nums text-content-secondary">
          {t('carbon.sixd.wl_coverage_linked', {
            defaultValue: '{{linked}} of {{total}} elements',
            linked,
            total,
          })}{' '}
          ({fmtPercent(safePct, 0)})
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
        <div
          className={clsx('h-full rounded-full', TONE_COLOR[tone])}
          style={{ width: `${Math.max(0, Math.min(100, safePct))}%` }}
        />
      </div>
    </li>
  );
}

function CoverageCard({ coverage }: { coverage: WholeLifeCoverage }) {
  const { t } = useTranslation();
  const total = coverage.bim_element_count ?? 0;
  return (
    <Card>
      <div className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        <Gauge size={13} />
        {t('carbon.sixd.wl_coverage_title', { defaultValue: 'Model coverage' })}
      </div>
      {total === 0 ? (
        <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
          {t('carbon.sixd.wl_coverage_no_bim', {
            defaultValue:
              'No BIM elements in this project yet. Upload and convert a model to measure coverage.',
          })}
        </p>
      ) : (
        <>
          <p className="mb-2 text-xs text-content-tertiary">
            {t('carbon.sixd.wl_coverage_hint', {
              defaultValue: 'How many of the {{total}} BIM elements each figure is linked to.',
              total,
            })}
          </p>
          <ul className="space-y-2.5">
            <CoverageRow
              label={t('carbon.sixd.wl_coverage_embodied', {
                defaultValue: 'Embodied carbon',
              })}
              linked={coverage.embodied_linked_count}
              total={total}
              pct={coverage.embodied_coverage_pct}
            />
            <CoverageRow
              label={t('carbon.sixd.wl_coverage_operational', {
                defaultValue: 'Operational carbon',
              })}
              linked={coverage.operational_linked_count}
              total={total}
              pct={coverage.operational_coverage_pct}
            />
            <CoverageRow
              label={t('carbon.sixd.wl_coverage_lcc', {
                defaultValue: 'Whole-life cost',
              })}
              linked={coverage.lcc_linked_count}
              total={total}
              pct={coverage.lcc_coverage_pct}
            />
          </ul>
        </>
      )}
    </Card>
  );
}

/* --- Carbon price / monetised carbon --- */

function CarbonPriceCard({
  priceInput,
  onPriceChange,
  summary,
  currency,
}: {
  priceInput: string;
  onPriceChange: (value: string) => void;
  summary: WholeLifeSummary;
  currency: string;
}) {
  const { t } = useTranslation();
  const monetised = summary.cost_of_whole_life_carbon;
  const hasPrice = monetised !== null && monetised !== undefined;
  return (
    <Card>
      <div className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        <Coins size={13} />
        {t('carbon.sixd.wl_price_title', {
          defaultValue: 'Cost of carbon (optional)',
        })}
      </div>
      <label className={labelCls} htmlFor="wl-carbon-price">
        {t('carbon.sixd.wl_price_label', {
          defaultValue: 'Carbon price (per tonne CO2e)',
        })}
      </label>
      <input
        id="wl-carbon-price"
        type="number"
        min="0"
        step="1"
        value={priceInput}
        onChange={(e) => onPriceChange(e.target.value)}
        className={inputCls}
        placeholder={t('carbon.sixd.wl_price_placeholder', {
          defaultValue: 'e.g. 50',
        })}
      />
      <p className="mt-1 text-xs text-content-tertiary">
        {t('carbon.sixd.wl_price_hint', {
          defaultValue: 'Set a price to monetise the whole-life carbon.',
        })}
      </p>
      {hasPrice && (
        <div className="mt-3 rounded-md bg-surface-secondary/60 p-3">
          <p className="text-xs uppercase tracking-wide text-content-tertiary">
            {t('carbon.sixd.wl_price_result', {
              defaultValue: 'Monetised whole-life carbon',
            })}
          </p>
          <p className="mt-0.5 text-lg font-semibold tabular-nums text-content-primary">
            <MoneyDisplay amount={monetised} currency={currency} />
          </p>
        </div>
      )}
    </Card>
  );
}

/* --- Draft review: accept / reject the AI-proposed draft lines --- */

function Sep() {
  return (
    <span className="mx-1.5 text-content-tertiary/50" aria-hidden="true">
      |
    </span>
  );
}

function ProvenanceLine({
  source,
  confidence,
  elementRef,
}: {
  source: EmbodiedSource | string;
  confidence?: 'high' | 'medium' | 'low' | null;
  elementRef?: string | null;
}) {
  const { t } = useTranslation();
  const src = source as EmbodiedSource;
  const label = sourceLabel(src);
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1.5">
      <Badge variant={sourcePillVariant(src)} size="sm">
        {t(label.key, { defaultValue: label.defaultValue })}
      </Badge>
      {confidence && <ConfidenceBadge level={confidence} />}
      {elementRef && (
        <span
          className="inline-flex max-w-[20ch] items-center gap-1 truncate text-xs text-content-tertiary"
          title={t('carbon.sixd.from_element', {
            defaultValue: 'BIM element: {{name}}',
            name: elementRef,
          })}
        >
          <Box size={11} className="shrink-0" />
          <span className="truncate">{elementRef}</span>
        </span>
      )}
    </span>
  );
}

function AcceptReject({
  status,
  busy,
  onAccept,
  onReject,
}: {
  status: string;
  busy: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  const { t } = useTranslation();
  const rejectLabel = t('carbon.sixd.wl_reject', { defaultValue: 'Reject' });
  if (!isDraftStatus(status)) {
    return (
      <span className="flex shrink-0 items-center gap-1">
        <Badge variant="success" size="sm" dot>
          {t('carbon.sixd.wl_status_confirmed', { defaultValue: 'Confirmed' })}
        </Badge>
        <button
          type="button"
          onClick={onReject}
          disabled={busy}
          className="rounded p-1.5 text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error disabled:opacity-40"
          aria-label={rejectLabel}
          title={rejectLabel}
        >
          <Trash2 size={14} />
        </button>
      </span>
    );
  }
  return (
    <span className="flex shrink-0 items-center gap-1.5">
      <Button
        variant="secondary"
        size="sm"
        icon={<Check size={13} />}
        loading={busy}
        disabled={busy}
        onClick={onAccept}
      >
        {t('carbon.sixd.wl_accept', { defaultValue: 'Accept' })}
      </Button>
      <button
        type="button"
        onClick={onReject}
        disabled={busy}
        className="rounded p-1.5 text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error disabled:opacity-40"
        aria-label={rejectLabel}
        title={rejectLabel}
      >
        <Trash2 size={14} />
      </button>
    </span>
  );
}

function DraftReviewSection({
  projectId,
  operational,
  lcc,
  currency,
  onChanged,
}: {
  projectId: string;
  operational: OperationalCarbonEntry[];
  lcc: LifeCycleCostEntry[];
  currency: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, setLoading, ...confirmProps } = useConfirm();
  const [busyId, setBusyId] = useState<string | null>(null);

  async function accept(id: string, kind: 'op' | 'lcc') {
    setBusyId(id);
    try {
      if (kind === 'op') await confirmOperationalCarbon(id);
      else await confirmLifeCycleCost(id);
      addToast({
        type: 'success',
        title: t('carbon.sixd.wl_accepted', { defaultValue: 'Line accepted' }),
      });
      onChanged();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusyId(null);
    }
  }

  async function reject(id: string, kind: 'op' | 'lcc') {
    const ok = await confirm({
      title: t('carbon.sixd.wl_confirm_reject_title', {
        defaultValue: 'Reject this line?',
      }),
      message: t('carbon.sixd.wl_confirm_reject_msg', {
        defaultValue: 'The line will be permanently removed. You can recompute it again later.',
      }),
      confirmLabel: t('carbon.sixd.wl_reject', { defaultValue: 'Reject' }),
    });
    if (!ok) return;
    setLoading(true);
    setBusyId(id);
    try {
      if (kind === 'op') await deleteOperationalCarbon(id);
      else await deleteLifeCycleCost(id);
      addToast({
        type: 'success',
        title: t('carbon.sixd.wl_rejected', { defaultValue: 'Line rejected' }),
      });
      onChanged();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setLoading(false);
      setBusyId(null);
    }
  }

  return (
    <Card>
      <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        <Check size={13} />
        {t('carbon.sixd.wl_review_title', {
          defaultValue: 'Review draft lines',
        })}
      </div>
      <p className="mb-3 text-xs text-content-tertiary">
        {t('carbon.sixd.wl_review_hint', {
          defaultValue:
            'AI proposed these lines. Accept the ones you trust and reject the rest. Nothing counts until you accept.',
        })}
      </p>
      <AITrustNote
        surface="carbon_whole_life_review"
        projectId={projectId}
        refId={null}
        producedBy={t('carbon.sixd.wl_produced_by', {
          defaultValue:
            'AI computed these operational-carbon and whole-life cost lines from the BIM asset register. Review each one before you confirm it.',
        })}
        showFeedback={false}
      />

      <div className="mt-3 space-y-4">
        <div>
          <h4 className="mb-2 text-xs font-semibold text-content-secondary">
            {t('carbon.sixd.wl_review_operational', {
              defaultValue: 'Operational carbon (B6)',
            })}
          </h4>
          {operational.length === 0 ? (
            <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
              {t('carbon.sixd.wl_review_none_op', {
                defaultValue: 'No operational-carbon lines yet. Compute them above.',
              })}
            </p>
          ) : (
            <ul className="divide-y divide-border-light rounded border border-border-light text-sm">
              {operational.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="min-w-0">
                    <span className="block truncate text-content-primary">
                      {e.description || e.system || e.element_ref || '-'}
                    </span>
                    <span className="flex flex-wrap items-center text-xs text-content-tertiary">
                      {e.end_use}
                      <Sep />
                      {formatCarbonKg(toNumber(e.carbon_kg))}
                      <Sep />
                      {t('carbon.sixd.wl_over_years', {
                        defaultValue: 'over {{count}} yr',
                        count: e.study_period_years,
                      })}
                    </span>
                    <ProvenanceLine
                      source={e.source}
                      confidence={e.match_confidence}
                      elementRef={e.element_id ? e.element_ref : null}
                    />
                  </span>
                  <AcceptReject
                    status={e.status}
                    busy={busyId === e.id}
                    onAccept={() => void accept(e.id, 'op')}
                    onReject={() => void reject(e.id, 'op')}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h4 className="mb-2 text-xs font-semibold text-content-secondary">
            {t('carbon.sixd.wl_review_lcc', {
              defaultValue: 'Whole-life cost',
            })}
          </h4>
          {lcc.length === 0 ? (
            <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
              {t('carbon.sixd.wl_review_none_lcc', {
                defaultValue: 'No whole-life cost lines yet. Compute them above.',
              })}
            </p>
          ) : (
            <ul className="divide-y divide-border-light rounded border border-border-light text-sm">
              {lcc.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="min-w-0">
                    <span className="block truncate text-content-primary">
                      {e.description || e.category || e.element_ref || '-'}
                    </span>
                    <span className="flex flex-wrap items-center text-xs text-content-tertiary">
                      <MoneyDisplay
                        amount={e.whole_life_cost}
                        currency={e.currency || currency}
                        showCode
                        compact
                      />
                      <Sep />
                      {t('carbon.sixd.wl_replacements', {
                        defaultValue: '{{count}} replacements',
                        count: e.replacement_count,
                      })}
                      <Sep />
                      {t('carbon.sixd.wl_over_years', {
                        defaultValue: 'over {{count}} yr',
                        count: e.study_period_years,
                      })}
                    </span>
                    <ProvenanceLine
                      source={e.source}
                      confidence={e.confidence}
                      elementRef={e.element_id ? e.element_ref : null}
                    />
                  </span>
                  <AcceptReject
                    status={e.status}
                    busy={busyId === e.id}
                    onAccept={() => void accept(e.id, 'lcc')}
                    onReject={() => void reject(e.id, 'lcc')}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}

/* --- Small field helper --- */

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className={labelCls}>{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-content-tertiary">{hint}</p>}
    </div>
  );
}

/* --- Operational-carbon compute modal (dry-run preview then save) --- */

interface OpForm {
  grid_country: string;
  grid_year: number;
  grid_factor: string;
  study_period_years: number;
  end_use: string;
  gross_floor_area_m2: string;
  modelled_intensity: string;
}

function OperationalComputeModal({
  inventoryId,
  projectId,
  onClose,
  onDone,
}: {
  inventoryId: string;
  projectId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<OpForm>({
    grid_country: '',
    grid_year: 2023,
    grid_factor: '',
    study_period_years: 60,
    end_use: 'regulated',
    gross_floor_area_m2: '',
    modelled_intensity: '',
  });
  const [preview, setPreview] = useState<OperationalCarbonComputeResult | null>(null);

  function update<K extends keyof OpForm>(key: K, value: OpForm[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setPreview(null);
  }

  function buildBody() {
    return {
      grid_country: form.grid_country || undefined,
      grid_year: form.grid_year,
      grid_factor_kg_co2e_per_kwh:
        form.grid_factor.trim() !== '' ? Number(form.grid_factor) : undefined,
      study_period_years: form.study_period_years,
      end_use: form.end_use,
      gross_floor_area_m2:
        form.gross_floor_area_m2.trim() !== '' ? Number(form.gross_floor_area_m2) : undefined,
      modelled_intensity_kwh_per_m2_year:
        form.modelled_intensity.trim() !== '' ? Number(form.modelled_intensity) : undefined,
    };
  }

  const previewMut = useMutation({
    mutationFn: () => computeOperationalCarbon(inventoryId, buildBody(), true),
    onSuccess: (res) => setPreview(res),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const confirmMut = useMutation({
    mutationFn: () => computeOperationalCarbon(inventoryId, buildBody(), false),
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('carbon.sixd.wl_saved_op', {
          defaultValue: 'Saved {{count}} operational-carbon draft lines',
          count: res.created,
        }),
      });
      onDone();
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const summary = preview ? summarizeCompute(preview) : null;
  const busy = previewMut.isPending || confirmMut.isPending;

  return (
    <WideModal
      open
      onClose={onClose}
      size="lg"
      busy={busy}
      title={t('carbon.sixd.wl_op_title', {
        defaultValue: 'Compute operational carbon (B6)',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {summary && summary.hasProposals ? (
            <Button
              variant="primary"
              icon={<Check size={14} />}
              loading={confirmMut.isPending}
              disabled={busy}
              onClick={() => confirmMut.mutate()}
            >
              {t('carbon.sixd.wl_op_save', {
                defaultValue: 'Save {{count}} draft lines',
                count: summary.created,
              })}
            </Button>
          ) : (
            <Button
              variant="primary"
              icon={<Sparkles size={14} />}
              loading={previewMut.isPending}
              disabled={busy}
              onClick={() => previewMut.mutate()}
            >
              {t('carbon.sixd.wl_preview', { defaultValue: 'Preview' })}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-xs text-content-tertiary">
          {t('carbon.sixd.wl_op_intro', {
            defaultValue:
              'Estimate B6 use-phase carbon from the model energy signals and the grid factor. Preview first, then save the draft lines for review. Nothing is written until you save.',
          })}
        </p>
        <AITrustNote
          surface="carbon_operational_compute"
          projectId={projectId}
          refId={inventoryId}
          producedBy={t('carbon.sixd.wl_op_produced_by', {
            defaultValue:
              'AI derived operational energy from the BIM asset register and grid factors. Review each line before you confirm it.',
          })}
          showFeedback={false}
        />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field
            label={t('carbon.sixd.wl_op_grid_country', {
              defaultValue: 'Grid country',
            })}
          >
            <input
              value={form.grid_country}
              onChange={(e) => update('grid_country', e.target.value)}
              placeholder="DE, GB, US..."
              maxLength={8}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_op_grid_year', {
              defaultValue: 'Grid year',
            })}
          >
            <input
              type="number"
              value={form.grid_year}
              onChange={(e) => update('grid_year', Number(e.target.value) || 2023)}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_op_grid_factor', {
              defaultValue: 'Grid factor (kg CO2e/kWh, optional)',
            })}
          >
            <input
              type="number"
              step="0.001"
              min="0"
              value={form.grid_factor}
              onChange={(e) => update('grid_factor', e.target.value)}
              placeholder={t('carbon.sixd.wl_auto', { defaultValue: 'auto' })}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_op_study_period', {
              defaultValue: 'Study period (years)',
            })}
          >
            <input
              type="number"
              min="1"
              value={form.study_period_years}
              onChange={(e) => update('study_period_years', Number(e.target.value) || 60)}
              className={inputCls}
            />
          </Field>
          <Field label={t('carbon.sixd.wl_op_end_use', { defaultValue: 'End use' })}>
            <select
              value={form.end_use}
              onChange={(e) => update('end_use', e.target.value)}
              className={inputCls}
            >
              <option value="regulated">
                {t('carbon.sixd.wl_end_use_regulated', {
                  defaultValue: 'Regulated',
                })}
              </option>
              <option value="unregulated">
                {t('carbon.sixd.wl_end_use_unregulated', {
                  defaultValue: 'Unregulated',
                })}
              </option>
              <option value="mixed">
                {t('carbon.sixd.wl_end_use_mixed', { defaultValue: 'Mixed' })}
              </option>
            </select>
          </Field>
          <Field
            label={t('carbon.sixd.wl_op_gfa', {
              defaultValue: 'Gross floor area (m2, optional)',
            })}
          >
            <input
              type="number"
              min="0"
              value={form.gross_floor_area_m2}
              onChange={(e) => update('gross_floor_area_m2', e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_op_intensity', {
              defaultValue: 'Modelled intensity (kWh/m2/yr, optional)',
            })}
            hint={t('carbon.sixd.wl_op_intensity_hint', {
              defaultValue: 'Adds one modelled whole-building line when area is also set.',
            })}
          >
            <input
              type="number"
              min="0"
              value={form.modelled_intensity}
              onChange={(e) => update('modelled_intensity', e.target.value)}
              className={inputCls}
            />
          </Field>
        </div>

        <OperationalPreview isPending={previewMut.isPending} preview={preview} summary={summary} />
      </div>
    </WideModal>
  );
}

function OperationalPreview({
  isPending,
  preview,
  summary,
}: {
  isPending: boolean;
  preview: OperationalCarbonComputeResult | null;
  summary: ReturnType<typeof summarizeCompute> | null;
}) {
  const { t } = useTranslation();
  if (isPending) {
    return (
      <div className="flex items-center gap-2 rounded-md bg-surface-secondary/60 p-3 text-sm text-content-tertiary">
        <Loader2 size={14} className="animate-spin" />
        {t('carbon.sixd.wl_op_previewing', {
          defaultValue: 'Estimating operational carbon...',
        })}
      </div>
    );
  }
  if (!preview || !summary) {
    return (
      <p className="text-xs text-content-tertiary">
        {t('carbon.sixd.wl_op_preview_hint', {
          defaultValue: 'Set the parameters, then preview the proposed B6 lines.',
        })}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant={summary.created > 0 ? 'success' : 'neutral'} size="sm">
          {t('carbon.sixd.wl_op_matched', {
            defaultValue: '{{count}} lines proposed',
            count: summary.created,
          })}
        </Badge>
        <Badge variant={preview.skipped_no_energy > 0 ? 'warning' : 'neutral'} size="sm">
          {t('carbon.sixd.wl_op_skipped_no_energy', {
            defaultValue: '{{count}} no energy signal',
            count: preview.skipped_no_energy,
          })}
        </Badge>
        {preview.skipped_existing > 0 && (
          <Badge variant="neutral" size="sm">
            {t('carbon.sixd.wl_skipped_existing', {
              defaultValue: '{{count}} already computed',
              count: preview.skipped_existing,
            })}
          </Badge>
        )}
      </div>
      <p className="text-xs text-content-tertiary">
        {t('carbon.sixd.wl_op_grid_factor_used', {
          defaultValue: 'Grid factor {{value}} kg CO2e/kWh ({{source}})',
          value: fmtFixed(toNumber(preview.grid_factor_kg_co2e_per_kwh), 3),
          source: preview.grid_factor_source,
        })}
      </p>
      <p className="text-sm font-medium text-content-primary">
        {t('carbon.sixd.wl_op_total', { defaultValue: 'Total B6 carbon' })}:{' '}
        <span className="tabular-nums">{formatCarbonKg(toNumber(preview.total_b6_carbon_kg))}</span>
      </p>
      {summary.hasProposals ? (
        <ul className="max-h-56 divide-y divide-border-light overflow-y-auto rounded border border-border-light text-sm">
          {preview.entries.slice(0, PROPOSAL_CAP).map((e, i) => (
            <li
              key={e.id || `${e.element_id ?? 'row'}-${i}`}
              className="flex items-center justify-between gap-2 px-3 py-1.5"
            >
              <span className="truncate text-content-secondary">
                {e.description || e.system || e.element_ref || '-'}
              </span>
              <span className="shrink-0 tabular-nums">{formatCarbonKg(toNumber(e.carbon_kg))}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
          {t('carbon.sixd.wl_op_empty', {
            defaultValue:
              'No elements carried an energy signal. Add annual energy or rated power to the asset register, or set a modelled intensity above.',
          })}
        </p>
      )}
    </div>
  );
}

/* --- Whole-life cost compute modal (dry-run preview then save) --- */

interface LccForm {
  discount_rate: string;
  study_period_years: number;
  currency: string;
  opex_rate_pct: string;
  eol_rate_pct: string;
  default_service_life_years: number;
  default_capex: string;
}

interface ManualLine {
  /** Stable client-side id so rows keep their identity across add / remove. */
  uid: string;
  description: string;
  category: string;
  capex: string;
  service_life_years: string;
}

let manualLineSeq = 0;
function newManualLine(): ManualLine {
  manualLineSeq += 1;
  return {
    uid: `ml-${manualLineSeq}`,
    description: '',
    category: '',
    capex: '',
    service_life_years: '',
  };
}

function LccComputeModal({
  inventoryId,
  projectId,
  currency,
  onClose,
  onDone,
}: {
  inventoryId: string;
  projectId: string;
  currency: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<LccForm>({
    discount_rate: '0.035',
    study_period_years: 60,
    currency: currency || 'EUR',
    opex_rate_pct: '2.0',
    eol_rate_pct: '10.0',
    default_service_life_years: 30,
    default_capex: '',
  });
  const [lines, setLines] = useState<ManualLine[]>([]);
  const [preview, setPreview] = useState<LifeCycleCostComputeResult | null>(null);

  function update<K extends keyof LccForm>(key: K, value: LccForm[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setPreview(null);
  }

  function updateLine(index: number, patch: Partial<ManualLine>) {
    setLines((ls) => ls.map((l, i) => (i === index ? { ...l, ...patch } : l)));
    setPreview(null);
  }
  function addLine() {
    setLines((ls) => [...ls, newManualLine()]);
    setPreview(null);
  }
  function removeLine(index: number) {
    setLines((ls) => ls.filter((_, i) => i !== index));
    setPreview(null);
  }

  function buildBody() {
    const cleanLines = lines
      .filter((l) => l.description.trim() !== '' || l.capex.trim() !== '')
      .map((l) => ({
        description: l.description || undefined,
        category: l.category || undefined,
        capex: l.capex.trim() !== '' ? Number(l.capex) : undefined,
        service_life_years:
          l.service_life_years.trim() !== '' ? Number(l.service_life_years) : undefined,
      }));
    return {
      discount_rate: Number(form.discount_rate) || 0,
      study_period_years: form.study_period_years,
      currency: form.currency || 'EUR',
      default_capex: form.default_capex.trim() !== '' ? Number(form.default_capex) : undefined,
      opex_rate_pct: Number(form.opex_rate_pct) || 0,
      eol_rate_pct: Number(form.eol_rate_pct) || 0,
      default_service_life_years: form.default_service_life_years,
      lines: cleanLines.length > 0 ? cleanLines : undefined,
    };
  }

  const previewMut = useMutation({
    mutationFn: () => computeLifeCycleCost(inventoryId, buildBody(), true),
    onSuccess: (res) => setPreview(res),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const confirmMut = useMutation({
    mutationFn: () => computeLifeCycleCost(inventoryId, buildBody(), false),
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('carbon.sixd.wl_saved_lcc', {
          defaultValue: 'Saved {{count}} whole-life cost draft lines',
          count: res.created,
        }),
      });
      onDone();
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const summary = preview ? summarizeCompute(preview) : null;
  const busy = previewMut.isPending || confirmMut.isPending;

  return (
    <WideModal
      open
      onClose={onClose}
      size="lg"
      busy={busy}
      title={t('carbon.sixd.wl_lcc_title', {
        defaultValue: 'Compute whole-life cost (ISO 15686-5)',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {summary && summary.hasProposals ? (
            <Button
              variant="primary"
              icon={<Check size={14} />}
              loading={confirmMut.isPending}
              disabled={busy}
              onClick={() => confirmMut.mutate()}
            >
              {t('carbon.sixd.wl_lcc_save', {
                defaultValue: 'Save {{count}} draft lines',
                count: summary.created,
              })}
            </Button>
          ) : (
            <Button
              variant="primary"
              icon={<Sparkles size={14} />}
              loading={previewMut.isPending}
              disabled={busy}
              onClick={() => previewMut.mutate()}
            >
              {t('carbon.sixd.wl_preview', { defaultValue: 'Preview' })}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-xs text-content-tertiary">
          {t('carbon.sixd.wl_lcc_intro', {
            defaultValue:
              'Discount capex, operation, the replacement cycle and end-of-life to a present value over the study period. BIM asset costs are used when present; add manual lines for anything not modelled. Preview first, then save the draft lines.',
          })}
        </p>
        <AITrustNote
          surface="carbon_lcc_compute"
          projectId={projectId}
          refId={inventoryId}
          producedBy={t('carbon.sixd.wl_lcc_produced_by', {
            defaultValue:
              'AI costed the model assets over the study period. Review each line before you confirm it.',
          })}
          showFeedback={false}
        />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field
            label={t('carbon.sixd.wl_lcc_discount_rate', {
              defaultValue: 'Discount rate (0-1)',
            })}
          >
            <input
              type="number"
              step="0.001"
              min="0"
              max="1"
              value={form.discount_rate}
              onChange={(e) => update('discount_rate', e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_lcc_study_period', {
              defaultValue: 'Study period (years)',
            })}
          >
            <input
              type="number"
              min="1"
              value={form.study_period_years}
              onChange={(e) => update('study_period_years', Number(e.target.value) || 60)}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_lcc_currency', {
              defaultValue: 'Currency',
            })}
          >
            <input
              value={form.currency}
              onChange={(e) => update('currency', e.target.value.toUpperCase())}
              maxLength={8}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_lcc_opex_rate', {
              defaultValue: 'Annual opex (% of capex)',
            })}
          >
            <input
              type="number"
              step="0.1"
              min="0"
              value={form.opex_rate_pct}
              onChange={(e) => update('opex_rate_pct', e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_lcc_eol_rate', {
              defaultValue: 'End-of-life (% of capex)',
            })}
          >
            <input
              type="number"
              step="0.1"
              min="0"
              value={form.eol_rate_pct}
              onChange={(e) => update('eol_rate_pct', e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_lcc_service_life', {
              defaultValue: 'Default service life (years)',
            })}
          >
            <input
              type="number"
              min="1"
              value={form.default_service_life_years}
              onChange={(e) => update('default_service_life_years', Number(e.target.value) || 30)}
              className={inputCls}
            />
          </Field>
          <Field
            label={t('carbon.sixd.wl_lcc_default_capex', {
              defaultValue: 'Default capex per element (optional)',
            })}
          >
            <input
              type="number"
              min="0"
              value={form.default_capex}
              onChange={(e) => update('default_capex', e.target.value)}
              className={inputCls}
            />
          </Field>
        </div>

        {/* Manual cost lines (optional) */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('carbon.sixd.wl_lcc_lines_title', {
                defaultValue: 'Manual cost lines (optional)',
              })}
            </h4>
            <Button variant="secondary" size="sm" icon={<Plus size={13} />} onClick={addLine}>
              {t('carbon.sixd.wl_lcc_add_line', {
                defaultValue: 'Add cost line',
              })}
            </Button>
          </div>
          {lines.length === 0 ? (
            <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
              {t('carbon.sixd.wl_lcc_lines_hint', {
                defaultValue:
                  'Add cost lines for elements not modelled with cost data (facades, fit-out, external works).',
              })}
            </p>
          ) : (
            <ul className="space-y-2">
              {lines.map((l, i) => (
                <li key={l.uid} className="grid grid-cols-1 gap-2 sm:grid-cols-12">
                  <input
                    value={l.description}
                    onChange={(e) => updateLine(i, { description: e.target.value })}
                    placeholder={t('carbon.sixd.wl_lcc_line_desc', {
                      defaultValue: 'Description',
                    })}
                    className={clsx(inputCls, 'sm:col-span-5')}
                  />
                  <input
                    value={l.category}
                    onChange={(e) => updateLine(i, { category: e.target.value })}
                    placeholder={t('carbon.sixd.wl_lcc_line_category', {
                      defaultValue: 'Category',
                    })}
                    className={clsx(inputCls, 'sm:col-span-3')}
                  />
                  <input
                    type="number"
                    min="0"
                    value={l.capex}
                    onChange={(e) => updateLine(i, { capex: e.target.value })}
                    placeholder={t('carbon.sixd.wl_lcc_line_capex', {
                      defaultValue: 'Capex',
                    })}
                    className={clsx(inputCls, 'sm:col-span-2')}
                  />
                  <input
                    type="number"
                    min="1"
                    value={l.service_life_years}
                    onChange={(e) => updateLine(i, { service_life_years: e.target.value })}
                    placeholder={t('carbon.sixd.wl_lcc_line_life', {
                      defaultValue: 'Life (yr)',
                    })}
                    className={clsx(inputCls, 'sm:col-span-1')}
                  />
                  <button
                    type="button"
                    onClick={() => removeLine(i)}
                    className="flex h-9 items-center justify-center rounded-lg text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error sm:col-span-1"
                    aria-label={t('carbon.sixd.wl_lcc_remove_line', {
                      defaultValue: 'Remove line',
                    })}
                    title={t('carbon.sixd.wl_lcc_remove_line', {
                      defaultValue: 'Remove line',
                    })}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <LccPreview
          isPending={previewMut.isPending}
          preview={preview}
          summary={summary}
          currency={form.currency || 'EUR'}
        />
      </div>
    </WideModal>
  );
}

function LccPreview({
  isPending,
  preview,
  summary,
  currency,
}: {
  isPending: boolean;
  preview: LifeCycleCostComputeResult | null;
  summary: ReturnType<typeof summarizeCompute> | null;
  currency: string;
}) {
  const { t } = useTranslation();
  if (isPending) {
    return (
      <div className="flex items-center gap-2 rounded-md bg-surface-secondary/60 p-3 text-sm text-content-tertiary">
        <Loader2 size={14} className="animate-spin" />
        {t('carbon.sixd.wl_lcc_previewing', {
          defaultValue: 'Costing the model...',
        })}
      </div>
    );
  }
  if (!preview || !summary) {
    return (
      <p className="text-xs text-content-tertiary">
        {t('carbon.sixd.wl_lcc_preview_hint', {
          defaultValue: 'Set the parameters, then preview the proposed cost lines.',
        })}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant={summary.created > 0 ? 'success' : 'neutral'} size="sm">
          {t('carbon.sixd.wl_lcc_matched', {
            defaultValue: '{{count}} lines proposed',
            count: summary.created,
          })}
        </Badge>
        <Badge variant={preview.skipped_no_cost > 0 ? 'warning' : 'neutral'} size="sm">
          {t('carbon.sixd.wl_lcc_skipped_no_cost', {
            defaultValue: '{{count}} no cost data',
            count: preview.skipped_no_cost,
          })}
        </Badge>
        {preview.skipped_existing > 0 && (
          <Badge variant="neutral" size="sm">
            {t('carbon.sixd.wl_skipped_existing', {
              defaultValue: '{{count}} already computed',
              count: preview.skipped_existing,
            })}
          </Badge>
        )}
      </div>
      <p className="text-sm font-medium text-content-primary">
        {t('carbon.sixd.wl_lcc_total', {
          defaultValue: 'Total whole-life cost',
        })}
        :{' '}
        <span className="tabular-nums">
          <MoneyDisplay amount={preview.total_whole_life_cost} currency={currency} />
        </span>
      </p>
      {summary.hasProposals ? (
        <ul className="max-h-56 divide-y divide-border-light overflow-y-auto rounded border border-border-light text-sm">
          {preview.entries.slice(0, PROPOSAL_CAP).map((e, i) => (
            <li
              key={e.id || `${e.element_id ?? 'row'}-${i}`}
              className="flex items-center justify-between gap-2 px-3 py-1.5"
            >
              <span className="truncate text-content-secondary">
                {e.description || e.category || e.element_ref || '-'}
              </span>
              <span className="shrink-0 tabular-nums">
                <MoneyDisplay
                  amount={e.whole_life_cost}
                  currency={e.currency || currency}
                  showCode
                  compact
                />
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
          {t('carbon.sixd.wl_lcc_empty', {
            defaultValue:
              'No elements carried cost data. Add capex or a default capex above, or add manual cost lines.',
          })}
        </p>
      )}
    </div>
  );
}
