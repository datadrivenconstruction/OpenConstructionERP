/**
 * Submitted / assessed / certified side by side, per line, for one valuation
 * document: a client progress claim or a subcontractor payment application.
 *
 * Every amount says where it comes from (recorded on the line, quantity times
 * a named rate, or nothing to price it with), and a running total that drops
 * below the previous document's is flagged until the valuation note says why.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Scale } from 'lucide-react';

import { Button } from './Button';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';
import { MoneyDisplay } from './MoneyDisplay';
import { QuantityDisplay } from './QuantityDisplay';
import { Skeleton } from './Skeleton';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';

export type ValuationStage = 'submitted' | 'assessed' | 'certified';

export interface ValuationFigure {
  value: string | null;
  source: 'stored' | 'computed' | 'missing';
  field: string | null;
}

export interface ValuationGridRow {
  id: string;
  label: string;
  unit: string | null;
  rate: string | null;
  rate_source: string | null;
  stages: Record<ValuationStage, { qty: ValuationFigure; amount: ValuationFigure }>;
  cumulative_certified_qty: string;
  prior_cumulative: string | null;
  cumulative: string | null;
  cumulative_field: string | null;
  findings: { rule_id: string; severity: string; message: string }[];
}

export interface ValuationGridData {
  source_kind: string;
  source_id: string;
  document_number: string;
  status: string;
  currency: string;
  note: string;
  rows: ValuationGridRow[];
  totals: Record<ValuationStage, string | null>;
}

export interface ValuationGridProps {
  queryKey: readonly unknown[];
  fetchGrid: () => Promise<ValuationGridData>;
  saveNote?: (note: string) => Promise<ValuationGridData>;
  /** Running totals on a pay application are quantities; on a claim, money. */
  cumulativeIsMoney?: boolean;
}

const STAGES: ValuationStage[] = ['submitted', 'assessed', 'certified'];

export function ValuationGrid({ queryKey, fetchGrid, saveNote, cumulativeIsMoney = false }: ValuationGridProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const q = useQuery({ queryKey, queryFn: fetchGrid });
  const [note, setNote] = useState('');
  useEffect(() => setNote(q.data?.note ?? ''), [q.data?.note]);
  const noteM = useMutation({
    mutationFn: (value: string) => (saveNote ? saveNote(value) : Promise.reject(new Error('read only'))),
    onSuccess: (data) => {
      qc.setQueryData(queryKey, data);
      addToast({ type: 'success', title: t('valuation_grid.note_saved', { defaultValue: 'Valuation note saved' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  if (q.isLoading) return <Skeleton className="h-32 w-full" />;
  if (q.isError || !q.data) {
    return (
      <ErrorState
        title={t('valuation_grid.load_failed', { defaultValue: 'The valuation grid could not be loaded' })}
        onRetry={() => q.refetch()}
      />
    );
  }
  const grid = q.data;
  if (grid.rows.length === 0) {
    return (
      <EmptyState
        icon={<Scale size={22} />}
        title={t('valuation_grid.empty', { defaultValue: 'No lines to value yet' })}
        description={t('valuation_grid.empty_desc', {
          defaultValue: 'Once lines are on this document, their submitted, assessed and certified figures line up here.',
        })}
      />
    );
  }

  const stageLabel = (s: ValuationStage) =>
    t(`valuation_grid.stage_${s}`, {
      defaultValue: s === 'submitted' ? 'Submitted' : s === 'assessed' ? 'Assessed' : 'Certified',
    });

  const provenance = (f: ValuationFigure, row: ValuationGridRow) => {
    if (f.source === 'stored')
      return t('valuation_grid.src_stored', { defaultValue: 'Recorded on the line ({{field}})', field: f.field ?? '' });
    if (f.source === 'computed')
      return t('valuation_grid.src_computed', {
        defaultValue: 'Quantity x rate {{rate}} ({{field}})',
        rate: row.rate ?? '',
        field: f.field ?? '',
      });
    return t('valuation_grid.src_missing', { defaultValue: 'No rate to price this quantity' });
  };

  const amountCell = (f: ValuationFigure, row: ValuationGridRow) => (
    <div title={provenance(f, row)} data-source={f.source}>
      {f.value === null ? (
        <span className="text-content-tertiary">—</span>
      ) : (
        <MoneyDisplay amount={f.value} currency={grid.currency} />
      )}
      <div className="text-2xs text-content-tertiary">
        {f.source === 'stored'
          ? t('valuation_grid.tag_stored', { defaultValue: 'recorded' })
          : f.source === 'computed'
            ? t('valuation_grid.tag_computed', { defaultValue: 'qty x rate' })
            : t('valuation_grid.tag_missing', { defaultValue: 'no rate' })}
      </div>
    </div>
  );

  const total = (v: string | null) =>
    v === null ? <span className="text-content-tertiary">—</span> : <MoneyDisplay amount={v} currency={grid.currency} />;

  const running = (v: string | null, unit: string | null) =>
    v === null ? (
      <span className="text-content-tertiary">{t('valuation_grid.first_document', { defaultValue: 'first' })}</span>
    ) : cumulativeIsMoney ? (
      <MoneyDisplay amount={v} currency={grid.currency} />
    ) : (
      <QuantityDisplay value={Number(v)} unit={unit ?? ''} />
    );

  return (
    <div className="space-y-3" data-testid="valuation-grid">
      <div className="overflow-x-auto">
        <table className="oe-table w-full text-sm">
          <thead>
            <tr>
              <th rowSpan={2} className="text-left">
                {t('valuation_grid.line', { defaultValue: 'Line' })}
              </th>
              {STAGES.map((s) => (
                <th key={s} colSpan={2} className="text-center">
                  {stageLabel(s)}
                </th>
              ))}
              <th rowSpan={2} className="text-right">
                {t('valuation_grid.cumulative_certified', { defaultValue: 'Certified to date (qty)' })}
              </th>
              <th rowSpan={2} className="text-right">
                {t('valuation_grid.running_total', { defaultValue: 'Running total: previous / now' })}
              </th>
            </tr>
            <tr>
              {STAGES.flatMap((s) => [
                <th key={`${s}-q`} className="text-right">
                  {t('valuation_grid.qty', { defaultValue: 'Qty' })}
                </th>,
                <th key={`${s}-a`} className="text-right">
                  {t('valuation_grid.amount', { defaultValue: 'Amount' })}
                </th>,
              ])}
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row) => (
              <tr key={row.id} data-testid="valuation-grid-row">
                <td>
                  {row.label}
                  {row.findings.length > 0 && (
                    <span
                      className="ml-1 inline-flex align-middle text-semantic-warning"
                      title={row.findings.map((f) => f.message).join(' ')}
                      data-testid="valuation-grid-finding"
                    >
                      <AlertTriangle size={13} />
                    </span>
                  )}
                </td>
                {STAGES.flatMap((s) => [
                  <td
                    key={`${s}-q`}
                    className="text-right tabular-nums"
                    title={t('valuation_grid.src_stored', {
                      defaultValue: 'Recorded on the line ({{field}})',
                      field: row.stages[s].qty.field ?? '',
                    })}
                  >
                    <QuantityDisplay value={Number(row.stages[s].qty.value ?? 0)} unit={row.unit ?? ''} />
                  </td>,
                  <td key={`${s}-a`} className="text-right tabular-nums">
                    {amountCell(row.stages[s].amount, row)}
                  </td>,
                ])}
                <td className="text-right tabular-nums">
                  <QuantityDisplay value={Number(row.cumulative_certified_qty)} unit={row.unit ?? ''} />
                </td>
                <td
                  className="text-right tabular-nums"
                  title={t('valuation_grid.src_stored', {
                    defaultValue: 'Recorded on the line ({{field}})',
                    field: row.cumulative_field ?? '',
                  })}
                >
                  {running(row.prior_cumulative, row.unit)} / {running(row.cumulative, row.unit)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="font-medium">
              <td>{t('valuation_grid.total_priced', { defaultValue: 'Total of priced lines' })}</td>
              {STAGES.flatMap((s) => [
                <td key={`${s}-q`} />,
                <td key={`${s}-a`} className="text-right tabular-nums" data-testid={`valuation-total-${s}`}>
                  {total(grid.totals[s])}
                </td>,
              ])}
              <td />
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      {saveNote && (
        <div className="flex items-end gap-2">
          <label className="oe-label flex-1">
            {t('valuation_grid.note', { defaultValue: 'Valuation note (why a running total went down)' })}
            <textarea
              className="oe-textarea mt-1 w-full"
              rows={2}
              value={note}
              maxLength={2000}
              onChange={(e) => setNote(e.target.value)}
              data-testid="valuation-grid-note"
            />
          </label>
          <Button
            variant="secondary"
            size="sm"
            disabled={noteM.isPending || note === grid.note}
            onClick={() => noteM.mutate(note)}
          >
            {t('valuation_grid.save_note', { defaultValue: 'Save note' })}
          </Button>
        </div>
      )}
    </div>
  );
}
