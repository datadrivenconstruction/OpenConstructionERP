/**
 * CVR by WBS: the selected report's lines rolled up the project's WBS tree.
 * A parent is its own lines plus its children; open a node to see the
 * children, and the report lines booked to it. Figures come straight from the API.
 */
import { Fragment, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Card, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { fmtPercent } from '@/shared/lib/formatters';
import { fetchCvrWbsRollup, type CvrLine, type CvrWbsNode } from './api';
import { CommercialFindings } from './CommercialFindings';

/** Nodes whose every ancestor is open; parents always arrive before their children. */
export function visibleNodes(nodes: CvrWbsNode[], open: Set<string>): CvrWbsNode[] {
  const shown = new Set<string>();
  const out: CvrWbsNode[] = [];
  for (const node of nodes) {
    if (node.parent_id === null || (shown.has(node.parent_id) && open.has(node.parent_id))) {
      shown.add(node.id);
      out.push(node);
    }
  }
  return out;
}

interface Props {
  reportId: string;
  lines: CvrLine[];
}

export function WbsRollupCard({ reportId, lines }: Props) {
  const { t } = useTranslation();
  const [show, setShow] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [sourcesOf, setSourcesOf] = useState<string | null>(null);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['cvr-wbs-rollup', reportId],
    queryFn: () => fetchCvrWbsRollup(reportId),
    enabled: show && !!reportId,
  });
  const currency = data?.currency ?? '';
  const lineById = useMemo(() => new Map(lines.map((l) => [l.id, l])), [lines]);
  const rows = useMemo(() => {
    if (!data) return [];
    const tree = visibleNodes(data.nodes, open);
    return data.unallocated.line_count > 0 ? [...tree, data.unallocated] : tree;
  }, [data, open]);

  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const money = (v: string) => formatCurrency(v, currency);

  return (
    <Card padding="md">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setShow((v) => !v)}
        aria-expanded={show}
      >
        <span>
          <span className="oe-card-title">{t('cvr.wbs_title', { defaultValue: 'CVR by WBS' })}</span>
          <span className="ml-2 text-xs text-content-tertiary">
            {t('cvr.wbs_hint', {
              defaultValue: 'Budget, committed, cost, value and forecast per WBS element; a parent is its own lines plus its children',
            })}
          </span>
        </span>
        {show ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {show && (
        <div className="mt-3 space-y-3">
          {isLoading ? (
            <SkeletonTable rows={4} columns={8} />
          ) : isError ? (
            <RecoveryCard error={error} onRetry={() => refetch()} />
          ) : !data || data.line_count === 0 ? (
            <EmptyState
              title={t('cvr.wbs_empty', { defaultValue: 'No cost heads to roll up' })}
              description={t('cvr.wbs_empty_desc', {
                defaultValue: 'Fill the report from the cost spine to get one line per WBS element.',
              })}
            />
          ) : (
            <>
              {data.wbs_count === 0 && (
                <p className="text-xs text-content-tertiary">
                  {t('cvr.wbs_no_tree', {
                    defaultValue: 'This project has no WBS yet, so every line is shown as unallocated.',
                  })}
                </p>
              )}
              <CommercialFindings findings={data.findings} />
              <div className="overflow-x-auto">
                <table className="oe-table w-full min-w-[1040px]">
                  <thead>
                    <tr className="text-left text-2xs">
                      <th className="pr-3">{t('cvr.wbs_col_element', { defaultValue: 'WBS element' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_budget', { defaultValue: 'Budget' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_committed', { defaultValue: 'Committed' })}</th>
                      <th className="pr-3 text-right">{t('cvr.col_cost_to_date', { defaultValue: 'Cost to date' })}</th>
                      <th className="pr-3 text-right">{t('cvr.col_value_to_date', { defaultValue: 'Value to date' })}</th>
                      <th className="pr-3 text-right">{t('cvr.col_forecast_cost', { defaultValue: 'FC cost' })}</th>
                      <th className="pr-3 text-right">{t('cvr.forecast_margin', { defaultValue: 'Forecast margin' })}</th>
                      <th className="pr-3 text-right">{t('cvr.wbs_col_sources', { defaultValue: 'Sources' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((node) => {
                      const isUnallocated = node.id === '';
                      const key = isUnallocated ? '__unallocated' : node.id;
                      const isOpen = open.has(node.id);
                      const negative = toNum(node.total.forecast_margin) < 0;
                      const ownLines = node.line_ids.map((id) => lineById.get(id)).filter((l): l is CvrLine => !!l);
                      return (
                        <Fragment key={key}>
                          <tr data-testid={`wbs-row-${node.code || 'unallocated'}`}>
                            <td className="pr-3">
                              <div className="flex items-center gap-1.5" style={{ paddingLeft: `${node.depth * 1.25}rem` }}>
                                {node.child_count > 0 ? (
                                  <button
                                    type="button"
                                    className="text-content-tertiary hover:text-content-primary"
                                    aria-expanded={isOpen}
                                    aria-label={t('cvr.wbs_toggle_children', { defaultValue: 'Show or hide the elements beneath' })}
                                    onClick={() => toggle(node.id)}
                                  >
                                    {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                  </button>
                                ) : (
                                  <span className="inline-block w-[14px]" />
                                )}
                                {isUnallocated ? (
                                  <span className="italic text-content-secondary">
                                    {t('cvr.wbs_unallocated', { defaultValue: 'Without a WBS element' })}
                                  </span>
                                ) : (
                                  <>
                                    <span className="font-medium">{node.code}</span>
                                    <span className="max-w-[18rem] truncate text-content-secondary" title={node.name}>
                                      {node.name}
                                    </span>
                                  </>
                                )}
                              </div>
                            </td>
                            <td className="pr-3 text-right tabular-nums">{money(node.total.budget_cost)}</td>
                            <td className="pr-3 text-right tabular-nums">{money(node.total.committed_cost)}</td>
                            <td className="pr-3 text-right tabular-nums">{money(node.total.cost_to_date)}</td>
                            <td className="pr-3 text-right tabular-nums">{money(node.total.value_to_date)}</td>
                            <td className="pr-3 text-right tabular-nums">{money(node.total.forecast_cost)}</td>
                            <td className={'pr-3 text-right tabular-nums ' + (negative ? 'text-semantic-error' : '')}>
                              {money(node.total.forecast_margin)}
                              <span className="ml-1 text-2xs text-content-tertiary">
                                {fmtPercent(toNum(node.total.forecast_margin_pct))}
                              </span>
                            </td>
                            <td className="pr-3 text-right">
                              <button
                                type="button"
                                className="text-xs text-oe-blue hover:underline disabled:text-content-tertiary disabled:no-underline"
                                disabled={node.line_ids.length === 0}
                                onClick={() => setSourcesOf(sourcesOf === key ? null : key)}
                                title={t('cvr.wbs_show_lines', { defaultValue: 'Show the report lines booked to this element' })}
                              >
                                {t('cvr.wbs_sources', {
                                  defaultValue: 'Lines: {{lines}}, positions: {{positions}}',
                                  lines: node.line_count,
                                  positions: node.positions,
                                })}
                              </button>
                            </td>
                          </tr>
                          {sourcesOf === key && (
                            <tr>
                              <td colSpan={8} className="bg-surface-secondary px-3 py-2">
                                <ul className="space-y-0.5 text-xs" data-testid="wbs-own-lines">
                                  {ownLines.map((l) => (
                                    <li key={l.id} className="flex gap-3">
                                      <span className="font-medium">{l.cost_code || '-'}</span>
                                      <span className="flex-1 truncate text-content-secondary">{l.description}</span>
                                      <span className="tabular-nums">{money(l.cost_to_date)}</span>
                                      <span className="tabular-nums text-content-tertiary">{money(l.value_to_date)}</span>
                                    </li>
                                  ))}
                                </ul>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td className="pr-3">{t('cvr.totals', { defaultValue: 'Totals' })}</td>
                      <td className="pr-3 text-right tabular-nums">{money(data.totals.budget_cost)}</td>
                      <td className="pr-3 text-right tabular-nums">{money(data.totals.committed_cost)}</td>
                      <td className="pr-3 text-right tabular-nums">{money(data.totals.cost_to_date)}</td>
                      <td className="pr-3 text-right tabular-nums">{money(data.totals.value_to_date)}</td>
                      <td className="pr-3 text-right tabular-nums">{money(data.totals.forecast_cost)}</td>
                      <td className="pr-3 text-right tabular-nums">{money(data.totals.forecast_margin)}</td>
                      <td className="pr-3 text-right text-xs text-content-tertiary">
                        {t('cvr.wbs_sources', {
                          defaultValue: 'Lines: {{lines}}, positions: {{positions}}',
                          lines: data.line_count,
                          positions: data.nodes.filter((n) => n.depth === 0).reduce((s, n) => s + n.positions, 0) + data.unallocated.positions,
                        })}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  );
}
