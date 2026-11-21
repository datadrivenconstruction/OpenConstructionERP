/**
 * Two small sales reports for the Insights tab:
 *  - calls, meetings and emails logged per owner in a period;
 *  - expected revenue (deal value x probability) per expected close month.
 *
 * Money is never added across currencies: the chart shows one currency at a time.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { fetchUsers } from '@/features/users/api';
import { getOwnerActivitySummary, getRevenueByMonth, type RevenueMonthRow } from './api';

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** Month bars for one currency: pure so the grouping can be tested. */
export function monthSeries(rows: RevenueMonthRow[], currency: string) {
  return rows
    .filter((r) => r.currency === currency)
    .map((r) => ({ month: r.month, expected: Number(r.expected), deals: r.deals }));
}

export function OwnerActivityCard() {
  const { t } = useTranslation();
  const [from, setFrom] = useState(() => isoDay(new Date(Date.now() - 30 * 86_400_000)));
  const [to, setTo] = useState(() => isoDay(new Date()));
  const invalid = Boolean(from && to && from > to);

  const q = useQuery({
    queryKey: ['crm', 'activity-summary', from, to],
    queryFn: () => getOwnerActivitySummary({ date_from: from, date_to: to }),
    enabled: !invalid,
  });
  const usersQ = useQuery({ queryKey: ['users', 'crm-names'], queryFn: () => fetchUsers(), staleTime: 300_000 });
  const names = useMemo(() => {
    const m: Record<string, string> = {};
    (usersQ.data ?? []).forEach((u: { id: string; full_name?: string | null; email?: string }) => {
      m[u.id] = u.full_name || u.email || u.id;
    });
    return m;
  }, [usersQ.data]);

  const rows = q.data?.rows ?? [];
  return (
    <Card padding="md" data-testid="owner-activity-card">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="oe-overline">
          {t('crm.rep_activity_title', { defaultValue: 'Activity per owner' })}
        </p>
        <span className="flex items-center gap-1 text-xs text-content-secondary">
          <input
            type="date"
            value={from}
            max={to || undefined}
            onChange={(e) => setFrom(e.target.value)}
            className="oe-input"
            aria-label={t('crm.rep_from', { defaultValue: 'From' })}
          />
          <span>-</span>
          <input
            type="date"
            value={to}
            min={from || undefined}
            onChange={(e) => setTo(e.target.value)}
            className="oe-input"
            aria-label={t('crm.rep_to', { defaultValue: 'To' })}
          />
        </span>
      </div>
      {invalid ? (
        <p className="text-sm text-semantic-error">
          {t('crm.rep_period_invalid', { defaultValue: 'The start date must not be after the end date.' })}
        </p>
      ) : rows.length === 0 ? (
        <p className="py-2 text-sm text-content-tertiary">
          {t('crm.rep_activity_empty', { defaultValue: 'No activities logged in this period.' })}
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-content-tertiary">
              <th className="py-1 font-medium">{t('crm.rep_owner', { defaultValue: 'Owner' })}</th>
              <th className="py-1 text-right font-medium">{t('crm.rep_calls', { defaultValue: 'Calls' })}</th>
              <th className="py-1 text-right font-medium">{t('crm.rep_meetings', { defaultValue: 'Meetings' })}</th>
              <th className="py-1 text-right font-medium">{t('crm.rep_emails', { defaultValue: 'Emails' })}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.owner_user_id ?? 'none'} className="border-t border-border-light">
                <td className="py-1.5 text-content-primary">
                  {r.owner_user_id
                    ? (names[r.owner_user_id] ?? r.owner_user_id)
                    : t('crm.rep_unassigned', { defaultValue: 'Unassigned' })}
                </td>
                <td className="py-1.5 text-right tabular-nums">{r.calls}</td>
                <td className="py-1.5 text-right tabular-nums">{r.meetings}</td>
                <td className="py-1.5 text-right tabular-nums">{r.emails}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export function RevenueByMonthCard() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ['crm', 'revenue-by-month'], queryFn: () => getRevenueByMonth() });
  const rows = q.data?.rows ?? [];
  const currencies = useMemo(() => [...new Set(rows.map((r) => r.currency))].sort(), [rows]);
  const [picked, setPicked] = useState('');
  const currency = currencies.includes(picked) ? picked : (currencies[0] ?? '');
  const series = useMemo(() => monthSeries(rows, currency), [rows, currency]);
  const scheduled = series.filter((s) => s.month !== '');
  const undated = series.find((s) => s.month === '');

  return (
    <Card padding="md" data-testid="revenue-by-month-card">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <p className="oe-overline">
          {t('crm.rep_revenue_title', { defaultValue: 'Expected revenue by month' })}
        </p>
        {currencies.length > 1 && (
          <select
            value={currency}
            onChange={(e) => setPicked(e.target.value)}
            className="oe-select h-8"
            aria-label={t('crm.currency', { defaultValue: 'Currency' })}
          >
            {currencies.map((c) => (
              <option key={c} value={c}>
                {c || t('crm.rep_currency_unset', { defaultValue: 'Currency not set' })}
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="mb-3 text-xs text-content-tertiary">
        {t('crm.rep_revenue_hint', {
          defaultValue: 'Open deals: value x probability, by expected close date. Currencies are never added together.',
        })}
      </p>
      {scheduled.length === 0 ? (
        <p className="py-2 text-sm text-content-tertiary">
          {t('crm.rep_revenue_empty', { defaultValue: 'No open deals with an expected close date.' })}
        </p>
      ) : (
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={scheduled}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} width={56} />
              <Tooltip />
              <Bar dataKey="expected" fill="#2563eb" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {undated && (
        <p className="mt-2 flex items-center gap-2 text-xs text-content-secondary">
          {t('crm.rep_revenue_undated', { defaultValue: 'Without a close date' })}:
          <MoneyDisplay amount={undated.expected} currency={currency || undefined} compact />
          <span className="text-content-tertiary">({undated.deals})</span>
        </p>
      )}
    </Card>
  );
}
