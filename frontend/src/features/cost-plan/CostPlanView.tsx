// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The NRM 1 elemental cost plan of one bill.
 *
 * Reads top to bottom the way a UK cost plan is printed: group elements 0-8
 * with their elements, the building works estimate, any NRM 1 groups 9-14 the
 * bill prices as items, what is not allocated to an element, the bill's direct
 * cost, then the bill's own markup cascade in compounding order and the total.
 * Every row carries cost per m2 of GIFA and its share of the total.
 *
 * Nothing on this screen is computed in the browser. The server regroups the
 * bill and guarantees the rows sum to its direct cost and grand total; the
 * screen formats strings. Element names come from the NRM 1 table as data;
 * every other word is a translation key.
 */

import { Fragment, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Download, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { Button, ErrorState, KpiBand } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import { fmtFixed, fmtPercent } from '@/shared/lib/formatters';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';
import { getErrorMessage } from '@/shared/lib/api';
import {
  costPlanApi,
  type CostPlanGroup,
  type CostPlanMarkup,
  type CostPlanSubtotal,
  type Nrm1CostPlan,
} from './api';

export interface CostPlanViewProps {
  boqId: string;
}

type TFn = ReturnType<typeof useTranslation>['t'];

function money(value: string | null | undefined, currency: string): string {
  if (value === null || value === undefined) return '-';
  return formatCurrency(value, currency);
}

function share(value: string | null): string {
  return value === null ? '-' : fmtPercent(value, 1);
}

/** How a markup line was priced, in the reader's language. */
function basisText(line: CostPlanMarkup, currency: string, t: TFn): string {
  const kind = (line.markup_type || 'percentage').toLowerCase();
  let text: string;
  if (kind === 'fixed') {
    text = t('cost_plan.basis_lump', { defaultValue: 'Lump sum' });
  } else if (kind === 'percentage') {
    const pct = line.percentage ?? '0';
    const compounding = line.apply_to === 'cumulative' || line.apply_to === 'subtotal';
    text = compounding
      ? t('cost_plan.basis_running', { defaultValue: '{{pct}}% on running subtotal', pct })
      : t('cost_plan.basis_direct', { defaultValue: '{{pct}}% on direct cost', pct });
  } else if (kind === 'banded') {
    text = t('cost_plan.basis_banded', { defaultValue: 'Banded scale' });
  } else if (kind === 'escalation') {
    text = t('cost_plan.basis_escalation', { defaultValue: 'Index escalation' });
  } else {
    text = line.markup_type;
  }
  if (line.base !== null) {
    text = `${text} · ${t('cost_plan.basis_of', { defaultValue: 'of {{amount}}', amount: money(line.base, currency) })}`;
  }
  if (line.scoped) {
    text = `${text} · ${t('cost_plan.basis_scoped', { defaultValue: 'section-scoped' })}`;
  }
  return text;
}

function categoryLabel(category: string, t: TFn): string {
  return t(`boq.markup_${category}`, { defaultValue: category.charAt(0).toUpperCase() + category.slice(1) });
}

const WARNING_DEFAULTS: Record<string, string> = {
  unallocated_positions:
    'Some positions carry no usable NRM code. They are listed below as not allocated to an element and are still in every total.',
  no_gifa:
    'No gross internal floor area is set, so cost per m2 is not shown. Enter one above, or set the gross floor area on the project.',
  addons_in_bill_and_markups:
    'The bill prices items coded to NRM 1 groups 9-14 and also carries markup lines. Check that preliminaries, fees or risk are not counted twice.',
  scoped_markups:
    'Some markup lines apply to one section only, so a line earns on several bases. Amounts are exact; no single base is shown.',
};

const REASON_DEFAULTS: Record<string, string> = {
  no_code: 'No NRM code on the position or its sections',
  invalid_code: 'Code is not an NRM number',
  unknown_group: 'NRM 1 has no such group',
};

interface RowProps {
  code?: string;
  label: ReactNode;
  positions?: number | null;
  row: CostPlanSubtotal;
  currency: string;
  tone?: 'group' | 'element' | 'subtotal' | 'total' | 'markup';
  testId?: string;
}

function PlanRow({ code, label, positions, row, currency, tone = 'element', testId }: RowProps) {
  const strong = tone === 'group' || tone === 'subtotal' || tone === 'total';
  return (
    <tr
      data-testid={testId}
      className={clsx(
        'border-b border-border-light',
        tone === 'subtotal' && 'bg-surface-secondary',
        tone === 'total' && 'bg-surface-secondary text-base',
        strong && 'font-semibold',
      )}
    >
      <td className="px-3 py-1.5 font-mono text-xs text-content-secondary whitespace-nowrap">{code ?? ''}</td>
      <td className={clsx('px-3 py-1.5', (tone === 'element' || tone === 'markup') && 'ps-7')}>{label}</td>
      <td className="px-3 py-1.5 text-end tabular-nums">{positions ?? ''}</td>
      <td className="px-3 py-1.5 text-end tabular-nums whitespace-nowrap">{money(row.total, currency)}</td>
      <td className="px-3 py-1.5 text-end tabular-nums whitespace-nowrap">
        {row.cost_per_m2 === null ? '-' : money(row.cost_per_m2, currency)}
      </td>
      <td className="px-3 py-1.5 text-end tabular-nums">{share(row.share_pct)}</td>
    </tr>
  );
}

function GroupRows({
  group,
  currency,
  showEmpty,
  t,
}: {
  group: CostPlanGroup;
  currency: string;
  showEmpty: boolean;
  t: TFn;
}) {
  return (
    <>
      <PlanRow
        code={group.code}
        label={group.name}
        positions={group.position_count}
        row={group}
        currency={currency}
        tone="group"
        testId={`cost-plan-group-${group.code}`}
      />
      {group.elements
        .filter((element) => showEmpty || element.position_count > 0 || Number(element.total) !== 0)
        .map((element) => (
          <PlanRow
            key={element.code}
            code={element.code}
            label={element.name}
            positions={element.position_count}
            row={element}
            currency={currency}
            testId={`cost-plan-element-${element.code}`}
          />
        ))}
      {group.group_level && (
        <PlanRow
          code={group.group_level.codes.join(', ')}
          label={
            <span className="italic text-content-secondary">
              {t('cost_plan.group_level', { defaultValue: 'Group level, no element given' })}
            </span>
          }
          positions={group.group_level.position_count}
          row={group.group_level}
          currency={currency}
          testId={`cost-plan-group-level-${group.code}`}
        />
      )}
    </>
  );
}

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <tr>
      <td colSpan={6} className="px-3 pt-4 pb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        {children}
      </td>
    </tr>
  );
}

function PlanTable({ plan, showEmpty, t }: { plan: Nrm1CostPlan; showEmpty: boolean; t: TFn }) {
  const currency = plan.currency;
  const pricedAddons = plan.addon_groups.filter((g) => g.position_count > 0 || Number(g.total) !== 0);
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm" data-testid="cost-plan-table">
        <thead className="bg-surface-secondary text-xs text-content-secondary">
          <tr>
            <th className="px-3 py-2 text-start font-medium">{t('cost_plan.col_code', { defaultValue: 'Code' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('cost_plan.col_element', { defaultValue: 'Element' })}</th>
            <th className="px-3 py-2 text-end font-medium">{t('cost_plan.col_positions', { defaultValue: 'Positions' })}</th>
            <th className="px-3 py-2 text-end font-medium">{t('cost_plan.col_total', { defaultValue: 'Total' })}</th>
            <th className="px-3 py-2 text-end font-medium">
              {t('cost_plan.col_per_m2', { defaultValue: 'Cost per m2 GIFA' })}
            </th>
            <th className="px-3 py-2 text-end font-medium">{t('cost_plan.col_share', { defaultValue: '% of total' })}</th>
          </tr>
        </thead>
        <tbody>
          {plan.groups.map((group) => (
            <GroupRows key={group.code} group={group} currency={currency} showEmpty={showEmpty} t={t} />
          ))}
          <PlanRow
            label={t('cost_plan.works_estimate', { defaultValue: 'Building works estimate' })}
            row={plan.works_estimate}
            currency={currency}
            tone="subtotal"
            testId="cost-plan-works-estimate"
          />
          {pricedAddons.length > 0 && (
            <>
              <SectionHeading>
                {t('cost_plan.addons_heading', { defaultValue: 'NRM 1 groups 9-14 priced as bill items' })}
              </SectionHeading>
              {pricedAddons.map((group) => (
                <GroupRows key={group.code} group={group} currency={currency} showEmpty={false} t={t} />
              ))}
            </>
          )}
          <PlanRow
            label={
              <span className={clsx(plan.unallocated.position_count > 0 && 'text-amber-700 dark:text-amber-300')}>
                {t('cost_plan.unallocated', { defaultValue: 'Not allocated to an element' })}
              </span>
            }
            positions={plan.unallocated.position_count}
            row={plan.unallocated}
            currency={currency}
            testId="cost-plan-unallocated"
          />
          <PlanRow
            label={t('cost_plan.direct_cost', { defaultValue: 'Direct cost of the bill' })}
            positions={plan.position_count}
            row={plan.direct_cost}
            currency={currency}
            tone="subtotal"
            testId="cost-plan-direct-cost"
          />
          {plan.markups.length > 0 && (
            <>
              <SectionHeading>
                {t('cost_plan.markups_heading', { defaultValue: "Markups, the bill's own cascade in order" })}
              </SectionHeading>
              {plan.markups.map((line, index) => (
                <PlanRow
                  key={line.id ?? `${line.name}-${index}`}
                  label={
                    <span className="flex flex-col">
                      <span>
                        {line.name}{' '}
                        <span className="text-xs font-normal text-content-tertiary">
                          ({categoryLabel(line.category, t)})
                        </span>
                      </span>
                      <span className="text-xs text-content-tertiary">
                        {basisText(line, currency, t)} ·{' '}
                        {t('cost_plan.running_total', {
                          defaultValue: 'running total {{amount}}',
                          amount: money(line.running_total, currency),
                        })}
                      </span>
                    </span>
                  }
                  row={line}
                  currency={currency}
                  tone="markup"
                  testId={`cost-plan-markup-${index}`}
                />
              ))}
              <PlanRow
                label={t('cost_plan.markups_total', { defaultValue: 'Markups total' })}
                row={plan.markups_total}
                currency={currency}
                tone="subtotal"
              />
            </>
          )}
          <PlanRow
            label={t('cost_plan.grand_total', { defaultValue: 'Cost plan total' })}
            row={plan.grand_total}
            currency={currency}
            tone="total"
            testId="cost-plan-grand-total"
          />
        </tbody>
      </table>
    </div>
  );
}

function UnallocatedList({ plan, t }: { plan: Nrm1CostPlan; t: TFn }) {
  const block = plan.unallocated;
  if (block.position_count === 0) return null;
  return (
    <details className="rounded-lg border border-amber-300/70 bg-amber-50/60 p-3 dark:border-amber-700/60 dark:bg-amber-950/30">
      <summary className="cursor-pointer text-sm font-medium">
        {t('cost_plan.unallocated_heading', {
          defaultValue: 'Positions not allocated to an element: {{n}}',
          n: block.position_count,
        })}
      </summary>
      <table className="mt-2 w-full text-xs" data-testid="cost-plan-unallocated-list">
        <thead className="text-content-secondary">
          <tr>
            <th className="px-2 py-1 text-start font-medium">{t('cost_plan.col_ordinal', { defaultValue: 'Ordinal' })}</th>
            <th className="px-2 py-1 text-start font-medium">
              {t('cost_plan.col_description', { defaultValue: 'Description' })}
            </th>
            <th className="px-2 py-1 text-start font-medium">
              {t('cost_plan.col_written_code', { defaultValue: 'Code as written' })}
            </th>
            <th className="px-2 py-1 text-start font-medium">{t('cost_plan.col_reason', { defaultValue: 'Reason' })}</th>
            <th className="px-2 py-1 text-end font-medium">{t('cost_plan.col_total', { defaultValue: 'Total' })}</th>
          </tr>
        </thead>
        <tbody>
          {block.positions.map((position) => (
            <tr key={position.id} className="border-t border-amber-200/70 dark:border-amber-800/50">
              <td className="px-2 py-1 font-mono">{position.ordinal}</td>
              <td className="px-2 py-1">{position.description}</td>
              <td className="px-2 py-1 font-mono">{position.code ?? ''}</td>
              <td className="px-2 py-1">
                {t(`cost_plan.reason_${position.reason}`, {
                  defaultValue: REASON_DEFAULTS[position.reason] ?? position.reason,
                })}
              </td>
              <td className="px-2 py-1 text-end tabular-nums">{money(position.total, plan.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {block.positions_truncated && (
        <p className="mt-2 text-xs text-content-secondary">
          {t('cost_plan.unallocated_truncated', {
            defaultValue: 'Showing {{shown}} of {{total}} here; the total covers all of them.',
            shown: block.positions.length,
            total: block.position_count,
          })}
        </p>
      )}
    </details>
  );
}

export function CostPlanView({ boqId }: CostPlanViewProps) {
  const { t } = useTranslation();
  const [gifaDraft, setGifaDraft] = useState('');
  const [enteredGifa, setEnteredGifa] = useState<string | null>(null);
  const [gifaError, setGifaError] = useState<string | null>(null);
  const [showEmpty, setShowEmpty] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const planQuery = useQuery({
    queryKey: ['cost-plan', 'nrm1', boqId, enteredGifa],
    queryFn: () => costPlanApi.nrm1(boqId, enteredGifa),
    enabled: Boolean(boqId),
  });
  const plan = planQuery.data;

  const applyGifa = () => {
    const value = parseDecimalInput(gifaDraft);
    if (value === null || value <= 0) {
      setGifaError(t('cost_plan.gifa_invalid', { defaultValue: 'Enter a floor area greater than zero.' }));
      return;
    }
    setGifaError(null);
    setEnteredGifa(String(value));
  };

  const resetGifa = () => {
    setGifaDraft('');
    setGifaError(null);
    setEnteredGifa(null);
  };

  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      await costPlanApi.exportNrm1Xlsx(boqId, enteredGifa);
    } catch (err) {
      setExportError(getErrorMessage(err));
    } finally {
      setExporting(false);
    }
  };

  const kpis = useMemo(() => {
    if (!plan) return [];
    return [
      {
        key: 'works',
        label: t('cost_plan.works_estimate', { defaultValue: 'Building works estimate' }),
        value: money(plan.works_estimate.total, plan.currency),
      },
      {
        key: 'total',
        label: t('cost_plan.grand_total', { defaultValue: 'Cost plan total' }),
        value: money(plan.grand_total.total, plan.currency),
      },
      {
        key: 'per_m2',
        label: t('cost_plan.kpi_per_m2', { defaultValue: 'Total per m2 GIFA' }),
        value: plan.grand_total.cost_per_m2 === null ? '-' : money(plan.grand_total.cost_per_m2, plan.currency),
        sub:
          plan.gifa === null
            ? t('cost_plan.gifa_source_none', { defaultValue: 'No GIFA set' })
            : `${fmtFixed(Number(plan.gifa), 2)} m2 · ${
                plan.gifa_source === 'entered'
                  ? t('cost_plan.gifa_source_entered', { defaultValue: 'entered here' })
                  : t('cost_plan.gifa_source_project', { defaultValue: 'from the project' })
              }`,
      },
      {
        key: 'allocated',
        label: t('cost_plan.kpi_allocated', { defaultValue: 'Positions on an element' }),
        value: `${plan.allocated_count} / ${plan.position_count}`,
        sub:
          plan.inherited_count > 0
            ? t('cost_plan.inherited_note', {
                defaultValue: 'Placed through their section code: {{n}}',
                n: plan.inherited_count,
              })
            : undefined,
      },
    ];
  }, [plan, t]);

  return (
    <div className="space-y-4" data-testid="cost-plan-view">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="cost-plan-gifa" className="text-xs font-medium text-content-secondary">
            {t('cost_plan.gifa_label', { defaultValue: 'GIFA (m2)' })}
          </label>
          <div className="flex items-center gap-2">
            <input
              id="cost-plan-gifa"
              inputMode="decimal"
              value={gifaDraft}
              onChange={(e) => setGifaDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') applyGifa();
              }}
              placeholder={
                plan?.gifa_source === 'project' && plan.gifa !== null
                  ? fmtFixed(Number(plan.gifa), 2)
                  : t('cost_plan.gifa_placeholder', { defaultValue: 'e.g. 2400' })
              }
              aria-invalid={gifaError !== null}
              className="h-9 w-36 rounded-lg border border-border bg-surface-primary px-3 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
            <Button variant="secondary" size="sm" onClick={applyGifa} disabled={!gifaDraft.trim()}>
              {t('cost_plan.gifa_apply', { defaultValue: 'Apply' })}
            </Button>
            {enteredGifa !== null && (
              <Button variant="ghost" size="sm" onClick={resetGifa}>
                {t('cost_plan.gifa_reset', { defaultValue: 'Use the project area' })}
              </Button>
            )}
          </div>
          {gifaError && (
            <p role="alert" className="text-xs text-semantic-error">
              {gifaError}
            </p>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm text-content-secondary">
          <input type="checkbox" checked={showEmpty} onChange={(e) => setShowEmpty(e.target.checked)} />
          {t('cost_plan.show_empty', { defaultValue: 'Show elements with no cost' })}
        </label>
        <div className="ms-auto flex flex-col items-end gap-1">
          <Button
            variant="primary"
            size="sm"
            onClick={handleExport}
            disabled={!plan || exporting}
            icon={exporting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
          >
            {t('cost_plan.export_xlsx', { defaultValue: 'Export to Excel' })}
          </Button>
          {exportError && (
            <p role="alert" className="text-xs text-semantic-error">
              {exportError}
            </p>
          )}
        </div>
      </div>

      {planQuery.isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-content-secondary">
          <Loader2 size={16} className="animate-spin" />
          {t('cost_plan.loading', { defaultValue: 'Rolling the bill up into NRM 1...' })}
        </div>
      )}

      {planQuery.isError && (
        <ErrorState
          title={t('cost_plan.load_failed', { defaultValue: 'The cost plan could not be built' })}
          hint={getErrorMessage(planQuery.error)}
          onRetry={() => void planQuery.refetch()}
        />
      )}

      {plan && (
        <>
          <KpiBand items={kpis} columns={4} />
          {plan.warnings.length > 0 && (
            <ul className="space-y-1" data-testid="cost-plan-warnings">
              {plan.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-2 text-xs text-amber-800 dark:text-amber-200">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                  <span>
                    {t(`cost_plan.warning_${warning}`, { defaultValue: WARNING_DEFAULTS[warning] ?? warning })}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {plan.position_count === 0 ? (
            <p className="py-6 text-center text-sm text-content-secondary">
              {t('cost_plan.empty_bill', { defaultValue: 'This bill has no priced positions yet.' })}
            </p>
          ) : (
            <Fragment>
              <PlanTable plan={plan} showEmpty={showEmpty} t={t} />
              <UnallocatedList plan={plan} t={t} />
            </Fragment>
          )}
        </>
      )}
    </div>
  );
}
