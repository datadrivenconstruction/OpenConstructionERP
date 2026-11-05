/** Inline payment schedule of an offer: instalment rows shaped like contract milestones. */
import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/shared/ui/Button';
import { formatCurrency } from '@/shared/lib/money';
import { minorDigits, rowsFromTemplate, scheduleBar, syncRows, takeTheRest, type ScheduleRow } from './schedule';

interface Props {
  rows: ScheduleRow[];
  /** Net total of the offer as a decimal string. */
  net: string;
  currency: string;
  readOnly?: boolean;
  onChange: (rows: ScheduleRow[]) => void;
}

const DUE_TYPES = ['signing', 'date', 'activity', 'acceptance'] as const;
const inputCls =
  'h-8 w-full rounded-md border border-border-light bg-surface-primary px-2 text-sm tabular-nums text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-60';

export function OfferScheduleEditor({ rows, net, currency, readOnly = false, onChange }: Props) {
  const { t } = useTranslation();
  const places = minorDigits(currency);
  const bar = scheduleBar(rows, net, currency);

  const edit = (index: number, patch: Partial<ScheduleRow>, field?: 'percent' | 'value') => {
    const next = rows.map((r, i) => (i === index ? { ...r, ...patch } : r));
    onChange(field ? syncRows(next, net, currency, { index, field }) : next);
  };
  const addRow = () => {
    const kind = rows.length === 0 ? 'deposit' : 'progress';
    const added: ScheduleRow = { code: String(rows.length + 1), name: '', kind, percent: '0', value: '0', due: { type: 'signing' }, lag_days: 0 };
    const demoted = rows.map((r, idx) => (idx === rows.length - 1 ? { ...r, kind: 'progress' as const } : r));
    onChange(takeTheRest([...demoted, { ...added, kind: 'final' as const }], net, places));
  };
  const removeRow = (index: number) => onChange(takeTheRest(rows.filter((_, i) => i !== index), net, places));
  const useTemplate = (key: string) => {
    const names: Record<string, string> = {
      deposit: t('offers.schedule.name_deposit', { defaultValue: 'Deposit' }),
      progress: t('offers.schedule.name_progress', { defaultValue: 'Progress' }),
      final: t('offers.schedule.name_final', { defaultValue: 'Final' }),
    };
    onChange(rowsFromTemplate(key, net, currency).map((r) => ({ ...r, name: names[r.kind] ?? r.name })));
  };
  const fillRest = () => onChange(takeTheRest(rows, net, places));

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border-light p-4 text-sm text-content-secondary">
        <p>{t('offers.schedule.empty', { defaultValue: 'No payment schedule. The customer pays the total on the invoice terms.' })}</p>
        {!readOnly && (
          <Button variant="secondary" size="sm" className="mt-3" onClick={() => useTemplate('30_40_30')}>
            {t('offers.schedule.use_30_40_30', { defaultValue: 'Use 30 / 40 / 30' })}
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-content-tertiary">
            <th className="w-8 py-1">#</th>
            <th className="py-1">{t('offers.schedule.instalment', { defaultValue: 'Instalment' })}</th>
            <th className="py-1">{t('offers.schedule.due_when', { defaultValue: 'Due when' })}</th>
            <th className="w-24 py-1 text-right">%</th>
            <th className="w-36 py-1 text-right">{t('offers.schedule.amount_net', { defaultValue: 'Amount (net)' })}</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const last = i === rows.length - 1;
            return (
              <tr key={i} className="align-top">
                <td className="py-1 text-content-tertiary">{i + 1}</td>
                <td className="py-1 pr-2">
                  <input
                    className={inputCls}
                    value={row.name}
                    disabled={readOnly}
                    aria-label={t('offers.schedule.instalment', { defaultValue: 'Instalment' })}
                    onChange={(e) => edit(i, { name: e.target.value })}
                  />
                </td>
                <td className="py-1 pr-2">
                  <select
                    className={inputCls}
                    value={String(row.due.type)}
                    disabled={readOnly}
                    aria-label={t('offers.schedule.due_when', { defaultValue: 'Due when' })}
                    onChange={(e) => edit(i, { due: { ...row.due, type: e.target.value } })}
                  >
                    {DUE_TYPES.map((d) => (
                      <option key={d} value={d}>
                        {t(`offers.schedule.due.${d}`, { defaultValue: d })}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="py-1 pr-2">
                  <input
                    className={`${inputCls} text-right`}
                    inputMode="decimal"
                    value={row.percent}
                    disabled={readOnly || last}
                    aria-label="%"
                    onChange={(e) => edit(i, { percent: e.target.value })}
                    onBlur={() => edit(i, {}, 'percent')}
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    className={`${inputCls} text-right`}
                    inputMode="decimal"
                    value={row.value}
                    disabled={readOnly || last}
                    aria-label={t('offers.schedule.amount_net', { defaultValue: 'Amount (net)' })}
                    onChange={(e) => edit(i, { value: e.target.value })}
                    onBlur={() => edit(i, {}, 'value')}
                  />
                  {last && (
                    <span className="text-xs text-content-tertiary">{t('offers.schedule.takes_rest', { defaultValue: 'Takes the rest' })}</span>
                  )}
                </td>
                <td className="py-1">
                  {!readOnly && rows.length > 1 && (
                    <button type="button" className="p-1 text-content-tertiary hover:text-semantic-error" onClick={() => removeRow(i)} aria-label={t('common.delete', { defaultValue: 'Delete' })}>
                      <Trash2 size={14} />
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="flex flex-wrap items-center justify-between gap-2">
        {!readOnly && (
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" icon={<Plus size={14} />} onClick={addRow}>
              {t('offers.schedule.add', { defaultValue: 'Add instalment' })}
            </Button>
            <select
              className={`${inputCls} w-auto`}
              value=""
              aria-label={t('offers.schedule.template', { defaultValue: 'Template' })}
              onChange={(e) => e.target.value && useTemplate(e.target.value)}
            >
              <option value="">{t('offers.schedule.template', { defaultValue: 'Template' })}</option>
              <option value="30_40_30">30 / 40 / 30</option>
              <option value="50_50">50 / 50</option>
              <option value="completion">{t('offers.schedule.completion', { defaultValue: '100% on completion' })}</option>
            </select>
          </div>
        )}
        <div
          role="status"
          aria-live="polite"
          data-state={bar.state}
          className={
            bar.state === 'ok'
              ? 'rounded-md bg-semantic-success-bg px-3 py-1 text-sm text-semantic-success'
              : bar.state === 'left'
                ? 'rounded-md bg-semantic-warning-bg px-3 py-1 text-sm text-semantic-warning'
                : 'rounded-md bg-semantic-error-bg px-3 py-1 text-sm text-semantic-error'
          }
        >
          {bar.state === 'ok' && t('offers.schedule.ok', { defaultValue: '100% scheduled' })}
          {bar.state === 'left' &&
            t('offers.schedule.left', { percent: `${bar.percent}%`, amount: formatCurrency(Number(bar.amount), currency), defaultValue: '{{percent}} scheduled, {{amount}} left' })}
          {bar.state === 'over' &&
            t('offers.schedule.over', { percent: `${bar.percent}%`, amount: formatCurrency(Number(bar.amount), currency), defaultValue: '{{percent}}, {{amount}} over the net' })}
          {!readOnly && bar.state !== 'ok' && (
            <button type="button" className="ml-3 underline" onClick={fillRest}>
              {t('offers.schedule.fill_rest', { defaultValue: 'Put the rest on the last instalment' })}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
