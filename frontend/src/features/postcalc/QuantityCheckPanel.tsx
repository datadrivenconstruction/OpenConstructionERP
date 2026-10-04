// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Quantity check: per bill position, the quantity the bill was let at against
 * the quantity the site measured, and what the difference costs.
 *
 * The contract side is the bill's quantity baseline, a snapshot captured when
 * the bill was first locked (or one a person chose, or froze here). It cannot
 * be the live bill: saving a measurement sheet in the editor writes the sheet's
 * total into the bill quantity, so after the first site measurement the live
 * bill already holds the measured figure. When there is no baseline the live
 * bill is used and the page says so in plain words.
 *
 * The measured side is the position's measurement sheet, typed in or written
 * by a GAEB X31 import; each row names which. Claimed-to-date quantities from
 * progress claims are not used: they are a percent of the contract quantity
 * capped at 100 and can never show an overrun.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, Ruler, Scale, TrendingDown, TrendingUp } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable, StatCard } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { formatValue } from '@/shared/lib/numberFormat';
import { fmtDate } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { snapshotDisplayName } from '@/features/boq/snapshotNames';
import { localizedUnitCode } from '@/shared/lib/unitLabels';
import {
  fetchQuantityCheck,
  setQuantityBaseline,
  type QuantityCheckLine,
  type QuantityCheckReport,
} from './api';
import {
  filterLines,
  isBeyondThreshold,
  num,
  readThreshold,
  totalsOf,
  writeThreshold,
  type QuantityFilter,
} from './quantityCheck';

const THRESHOLD_KEY = 'oce.postcalc.qc.threshold';
const CURRENT = '__current__';

const selectCls =
  'h-9 rounded-lg border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

function qty(value: string | null): string {
  const parsed = num(value);
  return Number.isNaN(parsed) ? '' : formatValue(parsed, 'number', { maximumFractionDigits: 3 });
}

/** A signed figure as one number, the sign where the reader's language puts it. */
function signedNumber(value: number, digits: number): string {
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      maximumFractionDigits: digits,
      signDisplay: 'exceptZero',
    }).format(value);
  } catch {
    return formatValue(value, 'number', { maximumFractionDigits: digits });
  }
}

function signedMoney(value: number, currency: string): string {
  return formatCurrency(value, currency, undefined, { signDisplay: 'exceptZero' });
}

function SourceBadge({ line }: { line: QuantityCheckLine }) {
  const { t } = useTranslation();
  if (line.measured_source === 'gaeb_x31') {
    return <Badge variant="blue">{t('postcalc.qc.source_x31', { defaultValue: 'GAEB X31' })}</Badge>;
  }
  if (line.measured_source === 'measurement_sheet') {
    return <Badge variant="neutral">{t('postcalc.qc.source_sheet', { defaultValue: 'Measurement sheet' })}</Badge>;
  }
  return null;
}

function StatusCell({ line }: { line: QuantityCheckLine }) {
  const { t } = useTranslation();
  if (line.status === 'not_measured') {
    return (
      <span className="text-content-tertiary" title={line.sheet_unchanged_since_baseline
        ? t('postcalc.qc.take_off_hint', {
            defaultValue: 'The sheet on this position is the take-off the bill was let with, not a site measurement.',
          })
        : undefined}
      >
        {line.sheet_unchanged_since_baseline
          ? t('postcalc.qc.status_take_off_only', { defaultValue: 'Take-off only' })
          : t('postcalc.qc.status_not_measured', { defaultValue: 'Not measured yet' })}
      </span>
    );
  }
  if (line.status === 'over') {
    return <Badge variant="error">{t('postcalc.qc.status_over', { defaultValue: 'Over contract' })}</Badge>;
  }
  if (line.status === 'under') {
    return <Badge variant="blue">{t('postcalc.qc.status_under', { defaultValue: 'Under contract' })}</Badge>;
  }
  return <Badge variant="success">{t('postcalc.qc.status_matches', { defaultValue: 'As contracted' })}</Badge>;
}

export function QuantityCheckTable({
  report,
  thresholdPct,
  filter,
}: {
  report: QuantityCheckReport;
  thresholdPct: number;
  filter: QuantityFilter;
}) {
  const { t, i18n } = useTranslation();
  const currency = report.currency ?? '';
  const rows = useMemo(() => filterLines(report.lines, filter, thresholdPct), [report.lines, filter, thresholdPct]);
  const shown = useMemo(() => totalsOf(rows), [rows]);

  if (report.lines.length === 0) {
    return (
      <EmptyState
        icon={<Ruler size={40} className="text-content-tertiary" />}
        title={t('postcalc.qc.empty_title', { defaultValue: 'No positions to check' })}
        description={t('postcalc.qc.empty_desc', {
          defaultValue: 'This bill has no priced positions yet. Quantities can be checked once the bill has positions.',
        })}
      />
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1080px] text-xs" data-testid="qc-table">
          <thead>
            <tr className="border-b border-border-light text-2xs text-content-tertiary">
              <th className="px-3 py-2 text-left">{t('postcalc.qc.col_ref', { defaultValue: 'Item' })}</th>
              <th className="px-3 py-2 text-left">{t('postcalc.qc.col_description', { defaultValue: 'Description' })}</th>
              <th className="px-3 py-2 text-left">{t('postcalc.qc.col_unit', { defaultValue: 'Unit' })}</th>
              <th className="border-l border-border-light px-3 py-2 text-right">
                {t('postcalc.qc.col_contract_qty', { defaultValue: 'Contract qty' })}
              </th>
              <th className="px-3 py-2 text-right">{t('postcalc.qc.col_measured_qty', { defaultValue: 'Measured qty' })}</th>
              <th className="px-3 py-2 text-left">{t('postcalc.qc.col_source', { defaultValue: 'Source' })}</th>
              <th className="border-l border-border-light px-3 py-2 text-right">
                {t('postcalc.qc.col_difference', { defaultValue: 'Difference' })}
              </th>
              <th className="px-3 py-2 text-right">{t('postcalc.qc.col_difference_pct', { defaultValue: 'Diff. %' })}</th>
              <th className="border-l border-border-light px-3 py-2 text-right">
                {t('postcalc.qc.col_rate', { defaultValue: 'Contract rate' })}
              </th>
              <th className="px-3 py-2 text-right">{t('postcalc.qc.col_cost_effect', { defaultValue: 'Cost effect' })}</th>
              <th className="border-l border-border-light px-3 py-2 text-left">
                {t('postcalc.qc.col_status', { defaultValue: 'Status' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((line) => {
              const beyond = isBeyondThreshold(line, thresholdPct);
              const pct = num(line.difference_pct);
              const diff = num(line.difference);
              const cost = num(line.cost_effect);
              return (
                <tr
                  key={line.position_id}
                  data-testid="qc-row"
                  data-beyond={beyond ? 'true' : 'false'}
                  className={clsx(
                    'border-b border-border-light last:border-0 hover:bg-surface-secondary/60',
                    beyond && 'bg-semantic-warning-bg',
                  )}
                >
                  <td className="px-3 py-2 font-mono text-2xs text-content-secondary">{line.ordinal || '-'}</td>
                  <td className="max-w-[260px] truncate px-3 py-2 text-content-primary" title={line.description}>
                    {line.description || '-'}
                    {!line.in_baseline && (
                      <span className="ml-1.5 text-2xs text-semantic-warning">
                        {t('postcalc.qc.added_since_baseline', { defaultValue: 'added after the baseline' })}
                      </span>
                    )}
                    {!line.in_bill && (
                      <span className="ml-1.5 text-2xs text-content-tertiary">
                        {t('postcalc.qc.removed_from_bill', { defaultValue: 'no longer in the bill' })}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-content-tertiary">{line.unit ? localizedUnitCode(line.unit, i18n.language) : '-'}</td>
                  <td className="border-l border-border-light px-3 py-2 text-right tabular-nums">
                    {line.contract_quantity === null ? (
                      <span className="text-content-tertiary">-</span>
                    ) : (
                      <span
                        className={clsx(line.contract_quantity_may_be_measured && 'text-semantic-warning')}
                        title={line.contract_quantity_may_be_measured
                          ? t('postcalc.qc.may_be_measured_hint', {
                              defaultValue:
                                'This figure equals the saved measurement. Without a baseline the contract quantity may already have been overwritten.',
                            })
                          : undefined}
                      >
                        {qty(line.contract_quantity)}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {line.measured_quantity === null ? (
                      <span className="text-content-tertiary">-</span>
                    ) : (
                      qty(line.measured_quantity)
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <SourceBadge line={line} />
                  </td>
                  <td
                    className={clsx(
                      'whitespace-nowrap border-l border-border-light px-3 py-2 text-right tabular-nums',
                      diff > 0 && 'text-semantic-error',
                      diff < 0 && 'text-oe-blue',
                    )}
                  >
                    {Number.isNaN(diff)
                      ? ''
                      : signedNumber(diff, 3)}
                  </td>
                  <td className={clsx('whitespace-nowrap px-3 py-2 text-right tabular-nums', beyond && 'font-semibold')}>
                    {Number.isNaN(pct)
                      ? Number.isNaN(diff)
                        ? ''
                        : <span className="text-content-tertiary">{t('postcalc.qc.no_ratio', { defaultValue: 'n/a' })}</span>
                      : t('postcalc.pct_value', {
                          value: signedNumber(pct, 1),
                        })}
                  </td>
                  <td className="whitespace-nowrap border-l border-border-light px-3 py-2 text-right tabular-nums text-content-secondary">
                    {line.contract_unit_rate === null ? '-' : formatCurrency(line.contract_unit_rate, currency)}
                  </td>
                  <td
                    className={clsx(
                      'whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums',
                      cost > 0 && 'text-semantic-error',
                      cost < 0 && 'text-oe-blue',
                    )}
                  >
                    {Number.isNaN(cost) ? '' : signedMoney(cost, currency)}
                  </td>
                  <td className="border-l border-border-light px-3 py-2">
                    <StatusCell line={line} />
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-border bg-surface-secondary/50 text-xs font-medium" data-testid="qc-footer">
              <td className="px-3 py-2" colSpan={6}>
                {t('postcalc.qc.footer_rows', {
                  count: shown.count,
                  defaultValue: 'Total of the {{count}} rows shown',
                })}
              </td>
              <td className="border-l border-border-light px-3 py-2 text-right" colSpan={3}>
                <span className="whitespace-nowrap text-semantic-error" data-testid="qc-footer-over">
                  {signedMoney(shown.over, currency)}
                </span>
                {' / '}
                <span className="whitespace-nowrap text-oe-blue" data-testid="qc-footer-under">
                  {signedMoney(shown.under, currency)}
                </span>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums" data-testid="qc-footer-net">
                {signedMoney(shown.net, currency)}
              </td>
              <td className="border-l border-border-light px-3 py-2" />
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="border-t border-border-light px-4 py-2 text-2xs text-content-tertiary">
        {t('postcalc.qc.legend', {
          defaultValue:
            'Cost effect = difference x contract unit rate, net of bill markups, in the bill currency. Over and under are totalled apart so they do not cancel out unseen.',
        })}
      </p>
    </Card>
  );
}

export function QuantityCheckPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [boqId, setBoqId] = useState<string | undefined>(undefined);
  const [viewSnapshotId, setViewSnapshotId] = useState<string | undefined>(undefined);
  const [filter, setFilter] = useState<QuantityFilter>('all');
  const [threshold, setThreshold] = useState<number>(() => readThreshold(THRESHOLD_KEY));

  const queryKey = ['postcalc', 'quantity-check', projectId, boqId ?? '', viewSnapshotId ?? ''];
  const query = useQuery({
    queryKey,
    queryFn: () => fetchQuantityCheck(projectId, boqId, viewSnapshotId),
    enabled: Boolean(projectId),
  });
  const report = query.data;

  const baselineMutation = useMutation({
    mutationFn: (body: { boq_id: string; snapshot_id?: string | null; freeze?: boolean }) =>
      setQuantityBaseline(projectId, body),
    onSuccess: (next) => {
      setViewSnapshotId(undefined);
      queryClient.setQueryData(['postcalc', 'quantity-check', projectId, boqId ?? '', ''], next);
      queryClient.invalidateQueries({ queryKey: ['postcalc', 'quantity-check', projectId] });
      addToast({ type: 'success', title: t('postcalc.qc.baseline_saved', { defaultValue: 'Baseline saved' }) });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('postcalc.qc.baseline_failed', { defaultValue: 'The baseline could not be saved' }),
        message: getErrorMessage(err),
      });
    },
  });

  const onThreshold = (raw: string) => {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || parsed < 0) return;
    setThreshold(parsed);
    writeThreshold(THRESHOLD_KEY, parsed);
  };

  if (query.isLoading) return <SkeletonTable rows={8} />;
  if (query.isError || !report) {
    return (
      <EmptyState
        icon={<Ruler size={40} className="text-semantic-error" />}
        title={t('postcalc.qc.load_failed', { defaultValue: 'The quantity check could not be loaded' })}
        description={getErrorMessage(query.error)}
        action={
          <Button variant="secondary" size="sm" onClick={() => query.refetch()}>
            {t('postcalc.retry')}
          </Button>
        }
      />
    );
  }
  if (!report.boq_id) {
    return (
      <EmptyState
        icon={<Ruler size={40} className="text-content-tertiary" />}
        title={t('postcalc.qc.no_bills_title', { defaultValue: 'No bill in this project yet' })}
        description={t('postcalc.qc.no_bills_desc', {
          defaultValue: 'Create or import a bill of quantities first. Its quantities are what the site measurement is checked against.',
        })}
      />
    );
  }

  const currency = report.currency ?? '';
  const totals = report.totals;
  const baseline = report.baseline;
  const warnings = report.warnings ?? [];
  const snapshots = report.snapshots ?? [];
  const isCurrent = baseline?.kind === 'current';
  const selectedBaseline = isCurrent ? CURRENT : (baseline?.snapshot_id ?? CURRENT);
  const viewingOther = Boolean(viewSnapshotId) && baseline?.designated === false;
  const net = num(totals.cost_effect_net);

  const onBaselinePick = (value: string) => {
    if (value === CURRENT) return;
    setViewSnapshotId(value === report.designated_snapshot_id ? undefined : value);
  };

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-end gap-3">
          {report.boqs.length > 1 && (
            <div className="flex flex-col gap-1">
              <label className="text-2xs text-content-tertiary" htmlFor="qc-bill">
                {t('postcalc.qc.bill_label', { defaultValue: 'Bill' })}
              </label>
              <select
                id="qc-bill"
                className={selectCls}
                value={report.boq_id}
                onChange={(e) => {
                  setViewSnapshotId(undefined);
                  setBoqId(e.target.value);
                }}
              >
                {report.boqs.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.currency ? `${b.name} (${b.currency})` : b.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex flex-col gap-1">
            <label className="text-2xs text-content-tertiary" htmlFor="qc-baseline">
              {t('postcalc.qc.baseline_label', { defaultValue: 'Contract quantities from' })}
            </label>
            <select
              id="qc-baseline"
              className={selectCls}
              value={selectedBaseline}
              onChange={(e) => onBaselinePick(e.target.value)}
              disabled={baselineMutation.isPending}
            >
              {snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.created_at
                    ? `${snapshotDisplayName(s.name, t)} (${fmtDate(s.created_at)})`
                    : snapshotDisplayName(s.name, t)}
                  {s.id === report.designated_snapshot_id
                    ? ` - ${t('postcalc.qc.baseline_marker', { defaultValue: 'baseline' })}`
                    : ''}
                </option>
              ))}
              {/* The live bill is offered only while there is no baseline: once
                  one exists, the live quantities are what it protects against. */}
              {isCurrent && (
                <option value={CURRENT}>
                  {t('postcalc.qc.baseline_current', { defaultValue: 'The bill as it stands now (no baseline)' })}
                </option>
              )}
            </select>
          </div>
          {viewingOther && (
            <Button
              variant="secondary"
              size="sm"
              disabled={baselineMutation.isPending}
              onClick={() => baselineMutation.mutate({ boq_id: report.boq_id ?? '', snapshot_id: viewSnapshotId })}
            >
              {t('postcalc.qc.use_as_baseline', { defaultValue: 'Use this snapshot as the baseline' })}
            </Button>
          )}
          {isCurrent && (
            <Button
              variant="primary"
              size="sm"
              disabled={baselineMutation.isPending}
              onClick={() => baselineMutation.mutate({ boq_id: report.boq_id ?? '', freeze: true })}
            >
              {t('postcalc.qc.freeze', { defaultValue: 'Freeze current quantities as baseline' })}
            </Button>
          )}
          <div className="ml-auto flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-2xs text-content-tertiary" htmlFor="qc-threshold">
                {t('postcalc.qc.threshold_label', { defaultValue: 'Highlight beyond +/- %' })}
              </label>
              <input
                id="qc-threshold"
                type="number"
                min={0}
                step={1}
                className={clsx(selectCls, 'w-24 text-right')}
                value={threshold}
                onChange={(e) => onThreshold(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-2xs text-content-tertiary" htmlFor="qc-filter">
                {t('postcalc.qc.filter_label', { defaultValue: 'Show' })}
              </label>
              <select
                id="qc-filter"
                className={selectCls}
                value={filter}
                onChange={(e) => setFilter(e.target.value as QuantityFilter)}
              >
                <option value="all">{t('postcalc.qc.filter_all', { defaultValue: 'All positions' })}</option>
                <option value="over">{t('postcalc.qc.filter_over', { defaultValue: 'Over contract' })}</option>
                <option value="under">{t('postcalc.qc.filter_under', { defaultValue: 'Under contract' })}</option>
                <option value="not_measured">
                  {t('postcalc.qc.filter_not_measured', { defaultValue: 'Not measured yet' })}
                </option>
                <option value="beyond">
                  {t('postcalc.qc.filter_beyond', { value: formatValue(threshold, 'number', { maximumFractionDigits: 2 }), defaultValue: 'Beyond +/- {{value}} %' })}
                </option>
              </select>
            </div>
          </div>
        </div>

        {baseline?.kind === 'snapshot' && (
          <p className="text-xs text-content-secondary">
            {baseline.designated_reason === 'lock'
              ? t('postcalc.qc.baseline_from_lock', {
                  name: snapshotDisplayName(baseline.name ?? '', t),
                  date: baseline.created_at ? fmtDate(baseline.created_at) : '',
                  defaultValue: 'Contract quantities and rates are read from "{{name}}", frozen when the bill was locked on {{date}}.',
                })
              : t('postcalc.qc.baseline_from_snapshot', {
                  name: snapshotDisplayName(baseline.name ?? '', t),
                  date: baseline.created_at ? fmtDate(baseline.created_at) : '',
                  defaultValue: 'Contract quantities and rates are read from the snapshot "{{name}}" of {{date}}.',
                })}
          </p>
        )}
        {warnings.includes('baseline_snapshot_missing') && (
          <p className="flex items-start gap-2 text-xs text-semantic-warning">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            {t('postcalc.qc.warning_snapshot_missing', {
              defaultValue: 'The snapshot this bill named as its baseline is no longer in its version history. The bill as it stands now is used instead.',
            })}
          </p>
        )}
        {isCurrent && (
          <p className="flex items-start gap-2 text-xs text-semantic-warning" data-testid="qc-no-baseline">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            {t('postcalc.qc.warning_no_baseline', {
              defaultValue:
                'This bill has no quantity baseline, so the bill quantities as they stand now are used as the contract side. Saving a measurement sheet in the bill writes its total into the bill quantity, so those positions may show no difference. Locking a bill freezes its quantities automatically; you can also freeze them now.',
            })}
          </p>
        )}
        {report.country_code === 'DE' && (
          <p className="text-2xs text-content-tertiary" data-testid="qc-de-hint">
            {t('postcalc.qc.hint_de', {
              defaultValue:
                'Under VOB/B section 2 (3), a quantity deviation of more than 10 % may entitle either party to agree a new unit price for the part beyond it. The band above is only a highlight.',
            })}
          </p>
        )}
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label={t('postcalc.qc.kpi_measured', { defaultValue: 'Positions measured' })}
          value={`${totals.measured_count} / ${totals.line_count}`}
          sub={t('postcalc.qc.kpi_measured_sub', {
            count: totals.not_measured_count,
            defaultValue: '{{count}} not measured yet',
          })}
          icon={Ruler}
        />
        <StatCard
          label={t('postcalc.qc.kpi_over', { defaultValue: 'Over contract' })}
          value={signedMoney(num(totals.cost_effect_over), currency)}
          sub={t('postcalc.qc.kpi_positions', { count: totals.over_count, defaultValue: '{{count}} positions' })}
          icon={TrendingUp}
          tone="danger"
          tintValue
        />
        <StatCard
          label={t('postcalc.qc.kpi_under', { defaultValue: 'Under contract' })}
          value={signedMoney(num(totals.cost_effect_under), currency)}
          sub={t('postcalc.qc.kpi_positions', { count: totals.under_count, defaultValue: '{{count}} positions' })}
          icon={TrendingDown}
          tone="blue"
          tintValue
        />
        <StatCard
          label={t('postcalc.qc.kpi_net', { defaultValue: 'Net cost effect' })}
          value={signedMoney(net, currency)}
          sub={t('postcalc.qc.kpi_net_sub', {
            value: formatCurrency(totals.contract_value, currency),
            defaultValue: 'against a contract value of {{value}}',
          })}
          icon={Scale}
          tone={net > 0 ? 'danger' : net < 0 ? 'blue' : 'default'}
          tintValue
        />
      </div>

      <QuantityCheckTable report={report} thresholdPct={threshold} filter={filter} />
    </div>
  );
}

export default QuantityCheckPanel;
