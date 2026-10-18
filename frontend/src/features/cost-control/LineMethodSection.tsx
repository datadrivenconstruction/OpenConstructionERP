// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One line under every forecast method, side by side, and the choice of the
// method this line is read with. Seeing the four figures next to each other is
// what makes the choice obvious: the reader sees what "maximum" or "projected
// from progress" would say before picking it.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Save } from 'lucide-react';

import { Button } from '@/shared/ui';
import { fmtCurrency, fmtNumber } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { LINE_METHODS, costControlApi, type LineForecastMethod, type LineHistory } from './api';
import { methodHelp, methodLabel, sourceLabel } from './labels';

const PROJECT = 'project';

export interface LineMethodSectionProps {
  projectId: string;
  history: LineHistory;
  currency: string;
  canEdit: boolean;
}

export function LineMethodSection({ projectId, history, currency, canEdit }: LineMethodSectionProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const current = history.current;
  const choice = history.method_choice;
  const [picked, setPicked] = useState<LineForecastMethod | typeof PROJECT>(choice?.method ?? PROJECT);
  const [comment, setComment] = useState(choice?.comment ?? '');

  useEffect(() => {
    setPicked(choice?.method ?? PROJECT);
    setComment(choice?.comment ?? '');
  }, [choice?.method, choice?.comment]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['cost-control', 'report', projectId] });
    queryClient.invalidateQueries({ queryKey: ['cost-control', 'history', history.cost_line_id] });
    queryClient.invalidateQueries({ queryKey: ['cost-control', 'forecast-panel', projectId] });
  };

  const save = useMutation({
    mutationFn: async () => {
      if (picked === PROJECT) await costControlApi.clearLineMethod(history.cost_line_id);
      else await costControlApi.setLineMethod(history.cost_line_id, { method: picked, comment: comment.trim() });
    },
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('cost_control.line_method_saved', { defaultValue: 'Method saved for this line' }) });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.line_method_failed', { defaultValue: 'Could not change the method' }),
        message: getErrorMessage(err),
      }),
  });

  const origin =
    current.method_origin === 'manual'
      ? t('cost_control.origin_manual', { defaultValue: 'your own forecast' })
      : current.method_origin === 'line'
        ? t('cost_control.origin_line', { defaultValue: "this line's own choice" })
        : t('cost_control.origin_project', { defaultValue: "the project's method" });
  const unchanged = (choice?.method ?? PROJECT) === picked && (choice?.comment ?? '') === comment.trim();
  const differs = picked !== PROJECT && picked !== history.project_method;

  return (
    <section className="rounded-xl border border-border-light p-4">
      <h3 className="text-sm font-semibold text-content-primary">
        {t('cost_control.line_method_title', { defaultValue: 'Forecast method' })}
      </h3>
      <p className="mt-1 text-xs text-content-secondary">
        {t('cost_control.line_method_now', {
          defaultValue: 'Read with {{method}}, from {{origin}}.',
          method: methodLabel(t, current.forecast_method),
          origin,
        })}
        {!current.method_applied && (
          <>
            {' '}
            {t('cost_control.line_method_fallback', {
              defaultValue: 'The method has nothing to work with on this line yet, so the best available figure stands in.',
            })}
          </>
        )}
      </p>

      <table className="mt-3 w-full text-sm">
        <thead>
          <tr className="text-2xs uppercase tracking-wide text-content-tertiary">
            <th className="pb-1 text-start font-semibold">{t('cost_control.line_method_col', { defaultValue: 'Method' })}</th>
            <th className="pb-1 text-end font-semibold">{t('cost_control.col_forecast', { defaultValue: 'Forecast' })}</th>
            <th className="pb-1 ps-3 text-start font-semibold">
              {t('cost_control.line_method_from', { defaultValue: 'From' })}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {history.methods.map((m) => {
            const active = m.method === current.forecast_method;
            return (
              <tr key={m.method} className={active ? 'font-medium text-content-primary' : 'text-content-secondary'}>
                <td className="py-1.5" title={methodHelp(t, m.method)}>
                  {methodLabel(t, m.method)}
                </td>
                <td className="py-1.5 text-end tabular-nums">{fmtCurrency(m.amount, currency)}</td>
                <td className="py-1.5 ps-3 text-xs">
                  {m.applied
                    ? m.method === 'evm_cpi' && m.cpi
                      ? t('cost_control.line_method_evm_detail', {
                          defaultValue: '{{progress}}% done, CPI {{cpi}}',
                          progress: fmtNumber(Number(m.progress ?? 0) * 100, 0),
                          cpi: fmtNumber(m.cpi, 2),
                        })
                      : sourceLabel(t, m.source)
                    : t('cost_control.line_method_not_applied', { defaultValue: 'Nothing to work with yet' })}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {canEdit && current.method_origin !== 'manual' && (
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!unchanged) save.mutate();
          }}
        >
          <label className="block text-sm">
            <span className="text-content-secondary">
              {t('cost_control.line_method_pick', { defaultValue: 'Read this line with' })}
            </span>
            <select
              className="mt-1 h-9 w-full rounded-lg border border-border bg-surface-primary px-2"
              value={picked}
              onChange={(e) => setPicked(e.target.value as LineForecastMethod | typeof PROJECT)}
            >
              <option value={PROJECT}>
                {t('cost_control.line_method_project', {
                  defaultValue: "The project's method ({{method}})",
                  method: methodLabel(t, history.project_method),
                })}
              </option>
              {LINE_METHODS.map((m) => (
                <option key={m} value={m}>
                  {methodLabel(t, m)}
                </option>
              ))}
            </select>
          </label>
          {picked !== PROJECT && (
            <label className="block text-sm">
              <span className="text-content-secondary">
                {differs
                  ? t('cost_control.line_method_comment_needed', { defaultValue: 'Why this line differs from the project' })
                  : t('cost_control.line_method_comment', { defaultValue: 'Comment (optional)' })}
              </span>
              <textarea
                className="mt-1 w-full rounded-lg border border-border bg-surface-primary px-3 py-2"
                rows={2}
                maxLength={2000}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder={t('cost_control.line_method_comment_placeholder', {
                  defaultValue: 'e.g. claim still open, take the cautious figure',
                })}
              />
            </label>
          )}
          <div className="flex justify-end">
            <Button
              variant="secondary"
              size="sm"
              type="submit"
              icon={<Save size={14} />}
              disabled={unchanged || save.isPending}
            >
              {t('cost_control.line_method_save', { defaultValue: 'Use this method' })}
            </Button>
          </div>
        </form>
      )}
      {canEdit && current.method_origin === 'manual' && (
        <p className="mt-3 text-xs text-content-tertiary">
          {t('cost_control.line_method_manual_note', {
            defaultValue: 'Your own forecast is in force. Remove it to read the line by a method again.',
          })}
        </p>
      )}
    </section>
  );
}
