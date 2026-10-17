// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CostSpinePanel - the v6.4 cost-spine keystone surface.
//
// Renders the whole-project spine rollup as an account-grouped grid: every
// cost line shows its Estimate next to the downstream Budget / Committed (PO)
// / Contracted / Actual (claimed) figures and the estimate-vs-budget
// Variance. A left-hand control-account tree filters the grid; clicking a row
// opens the per-line rollup drawer.
//
// Money note: rollup amounts arrive as Decimal-encoded STRINGS. We format them
// with the shared locale-aware ``fmtCurrency`` (which accepts strings) and
// never coerce them to a number for anything but display. When the spine spans
// more than one currency the backend sets ``mixed_currency`` and the summed
// totals are not meaningful, so we surface a banner instead of a blended sum.

import { Fragment, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Network, AlertTriangle, Inbox } from 'lucide-react';

import { Card, Skeleton, EmptyState } from '@/shared/ui';
import { fmtCurrency } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { sumMoneyStrings } from '@/shared/lib/exactDecimal';
import {
  costModelApi,
  type ControlAccount,
  type CostLineRollup,
  type SpineRollupTotals,
} from './api';
import { ControlAccountTree } from './ControlAccountTree';
import { GenerateSpineButton } from './GenerateSpineButton';
import { CostLineRollupDrawer } from './CostLineRollupDrawer';

export interface CostSpinePanelProps {
  projectId: string;
  /** Project currency, used as a fallback when the rollup omits one. */
  currency?: string;
  /** Optional BOQ id forwarded to the generate-from-BOQ action. */
  boqId?: string;
}

/** Tailwind text colour for a variance value (Decimal string). */
function varianceColor(value: string): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return 'text-content-secondary';
  // Convention: a positive estimate-vs-budget variance means the estimate is
  // above budget (unfavourable) -> red; negative means under budget -> green.
  return n > 0 ? 'text-semantic-error' : 'text-semantic-success';
}

/** Sum a set of Decimal-string amounts for a per-account subtotal, exactly. */
function sumAmounts(values: string[]): string {
  return sumMoneyStrings(values);
}

/** Column descriptor for the grid header + per-row cells. */
type ColumnKey = keyof Pick<
  CostLineRollup,
  | 'estimate_amount'
  | 'budget_planned'
  | 'po_committed'
  | 'contracted_value'
  | 'claimed_to_date'
  | 'variance_estimate_vs_budget'
>;

/**
 * Whole-project cost spine grid with a control-account tree filter.
 */
export function CostSpinePanel({ projectId, currency, boqId }: CostSpinePanelProps) {
  const { t } = useTranslation();
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [drawerLine, setDrawerLine] = useState<CostLineRollup | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['spine', projectId],
    queryFn: () => costModelApi.getSpineRollup(projectId),
    retry: false,
  });

  const resolvedCurrency = data?.currency || currency || 'EUR';

  const columns: { key: ColumnKey; label: string }[] = useMemo(
    () => [
      { key: 'estimate_amount', label: t('costmodel.spine.col_estimate', { defaultValue: 'Estimate' }) },
      { key: 'budget_planned', label: t('costmodel.spine.col_budget', { defaultValue: 'Budget' }) },
      { key: 'po_committed', label: t('costmodel.spine.col_committed', { defaultValue: 'Committed (PO)' }) },
      { key: 'contracted_value', label: t('costmodel.spine.col_contracted', { defaultValue: 'Contracted' }) },
      { key: 'claimed_to_date', label: t('costmodel.spine.col_actual', { defaultValue: 'Actual (claimed)' }) },
      { key: 'variance_estimate_vs_budget', label: t('costmodel.spine.col_variance', { defaultValue: 'Variance' }) },
    ],
    [t],
  );

  // Group cost-line rollups by their control account, preserving the
  // tree-ordered account sequence from the backend. An "Unassigned" bucket
  // collects lines with no control account.
  const grouped = useMemo(() => {
    const lines = data?.lines ?? [];
    const accounts = data?.accounts ?? [];

    const linesByAccount = new Map<string, CostLineRollup[]>();
    const unassigned: CostLineRollup[] = [];
    for (const line of lines) {
      if (line.control_account_id) {
        const bucket = linesByAccount.get(line.control_account_id) ?? [];
        bucket.push(line);
        linesByAccount.set(line.control_account_id, bucket);
      } else {
        unassigned.push(line);
      }
    }

    type Group = { account: ControlAccount | null; lines: CostLineRollup[] };
    const groups: Group[] = [];
    for (const account of accounts) {
      const accountLines = linesByAccount.get(account.id) ?? [];
      if (accountLines.length > 0) groups.push({ account, lines: accountLines });
    }
    if (unassigned.length > 0) groups.push({ account: null, lines: unassigned });

    return groups;
  }, [data]);

  // Per-account line counts for the tree badges.
  const accountCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const line of data?.lines ?? []) {
      if (line.control_account_id) {
        counts[line.control_account_id] = (counts[line.control_account_id] ?? 0) + 1;
      }
    }
    return counts;
  }, [data]);

  // Apply the tree filter (selected account only).
  const visibleGroups = useMemo(() => {
    if (!selectedAccountId) return grouped;
    return grouped.filter((g) => g.account?.id === selectedAccountId);
  }, [grouped, selectedAccountId]);

  const totals: SpineRollupTotals | undefined = data?.totals;
  const lineCount = data?.lines?.length ?? 0;

  /* ── Loading / error / empty ───────────────────────────────────────────── */

  if (isLoading) {
    return (
      <Card>
        <div className="space-y-3">
          <Skeleton height={32} className="w-1/3" rounded="md" />
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} height={44} className="w-full" rounded="md" />
          ))}
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <div className="flex items-start gap-3 rounded-lg border border-semantic-error/30 bg-semantic-error-bg/30 p-3">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-semantic-error" />
          <div>
            <p className="text-sm font-medium text-content-primary">
              {t('costmodel.spine.load_failed', { defaultValue: 'Could not load the cost spine' })}
            </p>
            <p className="mt-0.5 text-xs text-content-tertiary">{getErrorMessage(error)}</p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card padding="none">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-light px-5 py-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
            <Network size={16} />
          </div>
          <div>
            <h3 className="text-base font-semibold text-content-primary">
              {t('costmodel.spine.title', { defaultValue: 'Cost Spine' })}
            </h3>
            <p className="text-xs text-content-tertiary">
              {t('costmodel.spine.subtitle', {
                defaultValue:
                  'Estimate vs budget, commitment, contract and actual, rolled up across the project.',
              })}
            </p>
          </div>
        </div>
        <GenerateSpineButton projectId={projectId} boqId={boqId} />
      </div>

      {/* Mixed-currency banner */}
      {data?.mixed_currency && (
        <div
          role="alert"
          className="flex items-start gap-2 border-b border-amber-200 bg-amber-50/70 px-5 py-2.5 dark:border-amber-800/50 dark:bg-amber-950/20"
        >
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
          <p className="text-xs text-amber-800 dark:text-amber-300">
            {t('costmodel.spine.mixed_currency', {
              defaultValue:
                'This spine contains cost lines in more than one currency. Totals are not summed across currencies, compare lines within the same currency only.',
            })}
          </p>
        </div>
      )}

      {lineCount === 0 ? (
        <div className="p-6">
          <EmptyState
            icon={<Inbox size={28} strokeWidth={1.5} />}
            title={t('costmodel.spine.empty_title', { defaultValue: 'No cost lines yet' })}
            description={t('costmodel.spine.empty_desc', {
              defaultValue:
                'Generate the cost spine from a BOQ to populate control accounts and cost lines, then link budget, purchase orders and contracts to track estimate vs actual.',
            })}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr]">
          {/* Tree */}
          <div className="border-b border-border-light p-3 lg:border-b-0 lg:border-r">
            <ControlAccountTree
              accounts={data?.accounts ?? []}
              selectedId={selectedAccountId}
              onSelect={setSelectedAccountId}
              counts={accountCounts}
            />
          </div>

          {/* Grid */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
                  <th scope="col" className="px-4 py-2 font-medium">
                    {t('costmodel.spine.col_line', { defaultValue: 'Cost line' })}
                  </th>
                  {columns.map((col) => (
                    <th key={col.key} scope="col" className="px-4 py-2 text-right font-medium">
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleGroups.map((group) => {
                  const headerKey = group.account?.id ?? 'unassigned';
                  return (
                    <Fragment key={headerKey}>
                      {/* Account group header row with subtotals */}
                      <tr className="bg-surface-secondary/50">
                        <th
                          scope="colgroup"
                          className="px-4 py-1.5 text-left text-xs font-semibold text-content-primary"
                        >
                          {group.account ? (
                            <span className="inline-flex items-center gap-2">
                              <span className="font-mono text-2xs text-content-tertiary">
                                {group.account.code}
                              </span>
                              {group.account.title || group.account.name}
                            </span>
                          ) : (
                            t('costmodel.spine.unassigned', { defaultValue: 'Unassigned' })
                          )}
                        </th>
                        {columns.map((col) => (
                          <td
                            key={col.key}
                            className={`px-4 py-1.5 text-right text-xs font-semibold tabular-nums ${
                              col.key === 'variance_estimate_vs_budget'
                                ? varianceColor(sumAmounts(group.lines.map((l) => l[col.key])))
                                : 'text-content-secondary'
                            }`}
                          >
                            {fmtCurrency(
                              sumAmounts(group.lines.map((l) => l[col.key])),
                              resolvedCurrency,
                            )}
                          </td>
                        ))}
                      </tr>

                      {/* Cost line rows */}
                      {group.lines.map((line) => (
                        <tr
                          key={line.cost_line_id}
                          tabIndex={0}
                          onClick={() => setDrawerLine(line)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              setDrawerLine(line);
                            }
                          }}
                          className="cursor-pointer border-b border-border-light/60 last:border-0 hover:bg-surface-secondary/40 focus-visible:outline-none focus-visible:bg-surface-secondary/60"
                        >
                          <td className="px-4 py-2">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-2xs text-content-tertiary">
                                {line.code}
                              </span>
                              <span className="truncate text-content-primary">
                                {line.description}
                              </span>
                            </div>
                          </td>
                          {columns.map((col) => (
                            <td
                              key={col.key}
                              className={`px-4 py-2 text-right tabular-nums ${
                                col.key === 'variance_estimate_vs_budget'
                                  ? varianceColor(line[col.key])
                                  : 'text-content-primary'
                              }`}
                            >
                              {fmtCurrency(line[col.key], resolvedCurrency)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </Fragment>
                  );
                })}
              </tbody>

              {/* Project totals (suppressed when currencies are mixed) */}
              {totals && !data?.mixed_currency && (
                <tfoot>
                  <tr className="border-t-2 border-border bg-surface-secondary/60">
                    <th scope="row" className="px-4 py-2 text-left text-xs font-semibold text-content-primary">
                      {t('costmodel.spine.total', { defaultValue: 'Project total' })}
                    </th>
                    {columns.map((col) => (
                      <td
                        key={col.key}
                        className={`px-4 py-2 text-right text-xs font-bold tabular-nums ${
                          col.key === 'variance_estimate_vs_budget'
                            ? varianceColor(totals[col.key])
                            : 'text-content-primary'
                        }`}
                      >
                        {fmtCurrency(totals[col.key], resolvedCurrency)}
                      </td>
                    ))}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      )}

      {/* Per-line rollup drawer */}
      <CostLineRollupDrawer
        open={drawerLine !== null}
        onClose={() => setDrawerLine(null)}
        lineId={drawerLine?.cost_line_id ?? null}
        initial={drawerLine}
      />
    </Card>
  );
}
