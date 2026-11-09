// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Bid outcome ledger: how each bid we submitted ended, what the winner and the
 * runner-up charged, the money left on the table and our hit rate by client,
 * trade and size. Record the outcome once; the numbers follow.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, X } from 'lucide-react';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { formatCurrency } from '@/shared/lib/money';
import {
  LOST_REASONS,
  OUTCOMES,
  winLossApi,
  type BidOutcome,
  type BidOutcomeInput,
  type BidOutcomeStatus,
  type GroupStat,
  type LostReason,
  type ValidationFinding,
} from './api';

type GroupBy = 'by_client' | 'by_trade' | 'by_size';

const blank = (currency: string): BidOutcomeInput => ({
  title: '',
  client_name: '',
  trade: '',
  submitted_on: null,
  outcome: 'pending',
  currency,
  our_price: '',
  winning_price: null,
  second_price: null,
  competitor_count: null,
  lost_reason: null,
  notes: '',
});

const toInput = (e: BidOutcome): BidOutcomeInput => ({
  title: e.title,
  client_name: e.client_name,
  trade: e.trade,
  submitted_on: e.submitted_on,
  outcome: e.outcome,
  currency: e.currency,
  our_price: e.our_price,
  winning_price: e.winning_price,
  second_price: e.second_price,
  competitor_count: e.competitor_count,
  lost_reason: e.lost_reason,
  notes: e.notes,
});

const inputCls =
  'w-full rounded-lg border border-border bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary';

export function WinLossPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [groupBy, setGroupBy] = useState<GroupBy>('by_client');
  const [form, setForm] = useState<BidOutcomeInput | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<ValidationFinding[]>([]);

  const entries = useQuery({ queryKey: ['win-loss', 'list'], queryFn: winLossApi.list });
  const summary = useQuery({
    queryKey: ['win-loss', 'summary', currency ?? null],
    queryFn: () => winLossApi.summary(currency),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['win-loss'] });
  const save = useMutation({
    mutationFn: (body: BidOutcomeInput) =>
      editingId ? winLossApi.update(editingId, body) : winLossApi.create(body),
    onSuccess: (saved) => {
      setWarnings(saved.warnings);
      setForm(null);
      setEditingId(null);
      void refresh();
    },
  });
  const remove = useMutation({ mutationFn: winLossApi.remove, onSuccess: () => void refresh() });

  const s = summary.data;
  const money = (v: string | null | undefined, cur: string) =>
    v == null ? '' : formatCurrency(v, cur || undefined);
  const pct = (v: string | null | undefined) => (v == null ? '-' : `${v}%`);
  const outcomeLabel = (o: BidOutcomeStatus) => t(`winloss.outcome_${o}`, { defaultValue: o });
  const groupLabel = (key: string) =>
    groupBy === 'by_size'
      ? t(`winloss.band_${key}`, { defaultValue: key })
      : key || t('winloss.unspecified', { defaultValue: 'Not specified' });

  const set = <K extends keyof BidOutcomeInput>(k: K, v: BidOutcomeInput[K]) =>
    setForm((f) => (f ? { ...f, [k]: v } : f));
  const numOrNull = (v: string) => (v.trim() === '' ? null : v);
  const canSave = !!form && form.title.trim() !== '' && form.our_price.trim() !== '';

  const field = (label: string, node: React.ReactNode) => (
    <label className="flex flex-col gap-1 text-xs font-medium text-content-secondary">
      {label}
      {node}
    </label>
  );

  const cards: Array<[string, string]> = s
    ? [
        [t('winloss.hit_rate', { defaultValue: 'Hit rate' }), pct(s.hit_rate_pct)],
        [
          t('winloss.won_lost', { defaultValue: 'Won / lost' }),
          `${s.won} / ${s.lost}`,
        ],
        [t('winloss.open_bids', { defaultValue: 'Open bids' }), String(s.open)],
        [
          t('winloss.left_on_table', { defaultValue: 'Left on the table' }),
          money(s.left_on_table, s.currency),
        ],
        [
          t('winloss.avg_gap', { defaultValue: 'Average gap on lost bids' }),
          pct(s.avg_gap_to_winner_pct),
        ],
        [
          t('winloss.avg_competitors', { defaultValue: 'Average competitors' }),
          s.avg_competitors ?? '-',
        ],
      ]
    : [];

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('winloss.title', { defaultValue: 'Bid outcomes' })}
        subtitle={t('winloss.subtitle', {
          defaultValue:
            'Record how each bid ended. See what the winner charged, how much you left on the table and where you win.',
        })}
        actions={
          <Button
            icon={<Plus size={16} />}
            onClick={() => {
              setEditingId(null);
              setForm(blank(s?.currency ?? ''));
            }}
          >
            {t('winloss.add', { defaultValue: 'Record a bid' })}
          </Button>
        }
      />

      {s && s.currencies.length > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-content-secondary">
            {t('winloss.currency', { defaultValue: 'Currency' })}
          </span>
          <select
            className={`${inputCls} w-28`}
            value={s.currency}
            onChange={(e) => setCurrency(e.target.value)}
          >
            {s.currencies.map((c) => (
              <option key={c} value={c}>
                {c || '-'}
              </option>
            ))}
          </select>
        </div>
      )}

      {warnings.length > 0 && !form && (
        <div role="status" className="rounded-xl border border-border bg-surface-secondary p-3 text-sm" data-testid="winloss-warnings">
          <ul className="list-disc space-y-1 pl-5">
            {warnings.map((w) => (
              <li key={w.rule_id}>
                {w.message}
                {w.suggestion ? ` ${w.suggestion}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      {s && s.submitted > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6" data-testid="winloss-cards">
          {cards.map(([label, value]) => (
            <div key={label} className="rounded-xl border border-border bg-surface-primary p-3">
              <div className="text-xs text-content-secondary">{label}</div>
              <div className="mt-1 text-lg font-semibold text-content-primary">{value}</div>
            </div>
          ))}
        </div>
      )}

      {form && (
        <div className="space-y-3 rounded-xl border border-border bg-surface-primary p-4" data-testid="winloss-form">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {field(
              t('winloss.f_title', { defaultValue: 'Bid' }),
              <input className={inputCls} value={form.title} onChange={(e) => set('title', e.target.value)} />,
            )}
            {field(
              t('winloss.f_client', { defaultValue: 'Client' }),
              <input
                className={inputCls}
                value={form.client_name}
                onChange={(e) => set('client_name', e.target.value)}
              />,
            )}
            {field(
              t('winloss.f_trade', { defaultValue: 'Trade' }),
              <input className={inputCls} value={form.trade} onChange={(e) => set('trade', e.target.value)} />,
            )}
            {field(
              t('winloss.f_outcome', { defaultValue: 'Outcome' }),
              <select
                className={inputCls}
                value={form.outcome}
                onChange={(e) => set('outcome', e.target.value as BidOutcomeStatus)}
              >
                {OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {outcomeLabel(o)}
                  </option>
                ))}
              </select>,
            )}
            {field(
              t('winloss.f_submitted', { defaultValue: 'Submitted on' }),
              <input
                type="date"
                className={inputCls}
                value={form.submitted_on ?? ''}
                onChange={(e) => set('submitted_on', e.target.value || null)}
              />,
            )}
            {field(
              t('winloss.currency', { defaultValue: 'Currency' }),
              <input
                className={inputCls}
                maxLength={3}
                value={form.currency}
                onChange={(e) => set('currency', e.target.value.toUpperCase())}
              />,
            )}
            {field(
              t('winloss.f_our_price', { defaultValue: 'Our price' }),
              <input
                type="number"
                min="0"
                className={inputCls}
                value={form.our_price}
                onChange={(e) => set('our_price', e.target.value)}
              />,
            )}
            {field(
              t('winloss.f_winning_price', { defaultValue: 'Winning price' }),
              <input
                type="number"
                min="0"
                className={inputCls}
                value={form.winning_price ?? ''}
                onChange={(e) => set('winning_price', numOrNull(e.target.value))}
              />,
            )}
            {field(
              t('winloss.f_second_price', { defaultValue: 'Second price' }),
              <input
                type="number"
                min="0"
                className={inputCls}
                value={form.second_price ?? ''}
                onChange={(e) => set('second_price', numOrNull(e.target.value))}
              />,
            )}
            {field(
              t('winloss.f_competitors', { defaultValue: 'Other bidders' }),
              <input
                type="number"
                min="0"
                className={inputCls}
                value={form.competitor_count ?? ''}
                onChange={(e) =>
                  set('competitor_count', e.target.value === '' ? null : Number(e.target.value))
                }
              />,
            )}
            {form.outcome === 'lost' &&
              field(
                t('winloss.f_reason', { defaultValue: 'Main reason' }),
                <select
                  className={inputCls}
                  value={form.lost_reason ?? ''}
                  onChange={(e) => set('lost_reason', (e.target.value || null) as LostReason | null)}
                >
                  <option value="">-</option>
                  {LOST_REASONS.map((r) => (
                    <option key={r} value={r}>
                      {t(`winloss.reason_${r}`, { defaultValue: r })}
                    </option>
                  ))}
                </select>,
              )}
          </div>
          {save.isError && (
            <p role="alert" className="text-sm text-semantic-error">
              {t('winloss.save_failed', { defaultValue: 'Could not save the bid. Check the prices.' })}
            </p>
          )}
          <div className="flex gap-2">
            <Button disabled={!canSave || save.isPending} onClick={() => save.mutate(form)}>
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
            <Button
              variant="secondary"
              icon={<X size={16} />}
              onClick={() => {
                setForm(null);
                setEditingId(null);
              }}
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}

      {s && s.submitted > 0 && (
        <section className="rounded-xl border border-border bg-surface-primary p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-content-primary">
              {t('winloss.hit_rate_by', { defaultValue: 'Hit rate by' })}
            </h2>
            {(['by_client', 'by_trade', 'by_size'] as GroupBy[]).map((g) => (
              <button
                key={g}
                type="button"
                aria-pressed={groupBy === g}
                onClick={() => setGroupBy(g)}
                className={`rounded-full border px-3 py-1 text-xs ${
                  groupBy === g
                    ? 'border-oe-blue bg-oe-blue text-white'
                    : 'border-border text-content-secondary'
                }`}
              >
                {t(`winloss.${g}`, {
                  defaultValue: g === 'by_client' ? 'Client' : g === 'by_trade' ? 'Trade' : 'Size',
                })}
              </button>
            ))}
          </div>
          <table className="w-full text-sm" data-testid="winloss-groups">
            <thead>
              <tr className="text-left text-xs text-content-secondary">
                <th className="py-1">{t('winloss.group', { defaultValue: 'Group' })}</th>
                <th>{t('winloss.submitted', { defaultValue: 'Submitted' })}</th>
                <th>{t('winloss.won', { defaultValue: 'Won' })}</th>
                <th>{t('winloss.lost', { defaultValue: 'Lost' })}</th>
                <th>{t('winloss.hit_rate', { defaultValue: 'Hit rate' })}</th>
                <th className="text-right">{t('winloss.won_value', { defaultValue: 'Won value' })}</th>
              </tr>
            </thead>
            <tbody>
              {s[groupBy].map((g: GroupStat) => (
                <tr key={g.key} className="border-t border-border">
                  <td className="py-1.5">{groupLabel(g.key)}</td>
                  <td>{g.submitted}</td>
                  <td>{g.won}</td>
                  <td>{g.lost}</td>
                  <td>{pct(g.hit_rate_pct)}</td>
                  <td className="text-right">{money(g.won_value, s.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {entries.data && entries.data.length === 0 && !form && (
        <EmptyState
          title={t('winloss.empty_title', { defaultValue: 'No bids recorded yet' })}
          description={t('winloss.empty_desc', {
            defaultValue:
              'Record each bid you submit and how it ended. After a few decided bids the hit rate and the money left on the table appear here.',
          })}
          action={{
            label: t('winloss.add', { defaultValue: 'Record a bid' }),
            onClick: () => setForm(blank('')),
          }}
        />
      )}

      {entries.data && entries.data.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface-primary">
          <table className="w-full text-sm" data-testid="winloss-entries">
            <thead>
              <tr className="text-left text-xs text-content-secondary">
                <th className="px-3 py-2">{t('winloss.f_title', { defaultValue: 'Bid' })}</th>
                <th>{t('winloss.f_client', { defaultValue: 'Client' })}</th>
                <th>{t('winloss.f_outcome', { defaultValue: 'Outcome' })}</th>
                <th className="text-right">{t('winloss.f_our_price', { defaultValue: 'Our price' })}</th>
                <th className="text-right">
                  {t('winloss.f_winning_price', { defaultValue: 'Winning price' })}
                </th>
                <th className="text-right">{t('winloss.gap', { defaultValue: 'Gap' })}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {entries.data.map((e) => (
                <tr key={e.id} className="border-t border-border">
                  <td className="px-3 py-1.5">
                    <button
                      type="button"
                      className="text-left font-medium text-oe-blue-text hover:underline"
                      onClick={() => {
                        setEditingId(e.id);
                        setForm(toInput(e));
                      }}
                    >
                      {e.title}
                    </button>
                  </td>
                  <td>{e.client_name}</td>
                  <td>{outcomeLabel(e.outcome)}</td>
                  <td className="text-right">{money(e.our_price, e.currency)}</td>
                  <td className="text-right">{money(e.winning_price, e.currency)}</td>
                  <td className="text-right">
                    {e.left_on_table != null
                      ? `+${money(e.left_on_table, e.currency)}`
                      : e.gap_to_winner != null
                        ? `-${money(e.gap_to_winner, e.currency)}`
                        : ''}
                  </td>
                  <td className="px-2 text-right">
                    <button
                      type="button"
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                      className="text-content-tertiary hover:text-semantic-error"
                      onClick={() => remove.mutate(e.id)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
