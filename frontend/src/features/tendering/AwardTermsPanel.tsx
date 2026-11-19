// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The Award panel of a tender package: one place for the negotiated figures.
 *
 * Pick the firm, record its negotiation rounds (a revised lump sum or the
 * priced lines with a discount), mark the final offer and approve it, agree
 * the award terms (discount, lump sum, retention and cap, payment discount),
 * and read the contract sum the award will draft, recomputed by the server as
 * the terms are typed. Whatever stops the award is listed with its reason and,
 * for a firm the directory blocks or a lapsed certificate, a link to the firm.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Flag, Gavel, Trash2 } from 'lucide-react';
import { Badge, Button, Card, EmptyState } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { fmtCurrency, fmtDate } from '@/shared/lib/formatters';
import {
  addRound,
  approveRound,
  deleteRound,
  emptyTerms,
  getAwardTerms,
  listRounds,
  markRoundFinal,
  previewAwardTerms,
  ruleKey,
  saveAwardTerms,
  termsFromRound,
  type AwardRule,
  type AwardTerms,
  type GateFinding,
  type PricingMode,
} from './awardTerms';

export interface AwardPanelBid {
  id: string;
  company_name: string;
  status: string;
  total_amount: string;
  currency: string;
}

interface Props {
  packageId: string;
  packageStatus: string;
  bids: AwardPanelBid[];
  onAward: (bidId: string) => void;
  awarding: boolean;
}

const OPEN_STATES = new Set(['draft', 'issued', 'collecting', 'evaluating']);

/** Wait for typing to settle before asking the server again. */
function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return settled;
}

/** An empty field is "not agreed" (null), anything else goes as typed; the server validates. */
function optional(raw: string): string | null {
  const text = raw.trim().replace(',', '.');
  return text === '' ? null : text;
}

export function AwardTermsPanel({ packageId, packageStatus, bids, onAward, awarding }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const editable = OPEN_STATES.has(packageStatus);

  const candidates = useMemo(() => bids.filter((b) => b.status !== 'rejected' || !editable), [bids, editable]);

  const stored = useQuery({
    queryKey: ['tendering-award-terms', packageId],
    queryFn: () => getAwardTerms(packageId),
  });
  const rounds = useQuery({
    queryKey: ['tendering-rounds', packageId],
    queryFn: () => listRounds(packageId),
  });

  const [draft, setDraft] = useState<AwardTerms | null>(null);
  useEffect(() => {
    if (draft !== null || !stored.data) return;
    const accepted = bids.find((b) => b.status === 'accepted');
    const first = stored.data.terms?.bid_id ?? accepted?.id ?? candidates[0]?.id;
    if (first) setDraft(stored.data.terms ?? emptyTerms(first));
  }, [stored.data, draft, bids, candidates]);

  const settled = useDebounced(draft, 350);
  const preview = useQuery({
    queryKey: ['tendering-award-preview', packageId, settled],
    queryFn: () => previewAwardTerms(packageId, settled as AwardTerms),
    enabled: settled !== null,
    placeholderData: (prev) => prev,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['tendering-award-terms', packageId] });
    queryClient.invalidateQueries({ queryKey: ['tendering-rounds', packageId] });
    queryClient.invalidateQueries({ queryKey: ['tendering-award-preview', packageId] });
  };
  const onError = (error: Error) =>
    addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });

  const save = useMutation({
    mutationFn: (terms: AwardTerms) => saveAwardTerms(packageId, terms),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('tendering.award_panel.saved', { defaultValue: 'Award terms saved' }) });
    },
    onError,
  });

  const [roundMode, setRoundMode] = useState<PricingMode>('lump_sum');
  const [roundLump, setRoundLump] = useState('');
  const [roundDiscount, setRoundDiscount] = useState('');
  const [roundNote, setRoundNote] = useState('');
  const add = useMutation({
    mutationFn: (bidId: string) =>
      addRound(packageId, bidId, {
        pricing_mode: roundMode,
        lump_sum: roundMode === 'lump_sum' ? optional(roundLump) : null,
        discount_percent: optional(roundDiscount) ?? '0',
        note: roundNote,
      }),
    onSuccess: () => {
      setRoundLump('');
      setRoundDiscount('');
      setRoundNote('');
      invalidate();
    },
    onError,
  });
  const final = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) => markRoundFinal(packageId, id, value),
    onSuccess: invalidate,
    onError,
  });
  const approve = useMutation({ mutationFn: (id: string) => approveRound(packageId, id), onSuccess: invalidate, onError });
  const remove = useMutation({ mutationFn: (id: string) => deleteRound(packageId, id), onSuccess: invalidate, onError });

  if (candidates.length === 0) {
    return (
      <EmptyState
        icon={<Gavel size={40} />}
        title={t('tendering.award_panel.no_bids', { defaultValue: 'No bids to award yet' })}
        description={t('tendering.award_panel.no_bids_hint', {
          defaultValue: 'Once firms have priced the package, agree the award terms here.',
        })}
      />
    );
  }
  if (!draft) return null;

  const set = (patch: Partial<AwardTerms>) => setDraft({ ...draft, ...patch });
  const bidRounds = (rounds.data ?? []).filter((r) => r.bid_id === draft.bid_id);
  const p = editable ? preview.data : (stored.data?.preview ?? preview.data);
  const currency = p?.currency || candidates.find((b) => b.id === draft.bid_id)?.currency || '';
  const money = (v: string | null | undefined) => (v == null ? '-' : fmtCurrency(v, currency));
  const subId = p?.gate.subcontractor_id ?? null;

  const ruleText = (rule: AwardRule) => t(ruleKey(rule.rule_id), { defaultValue: rule.message });
  const findingText = (f: GateFinding) =>
    f.document_type
      ? t('tendering.award_panel.certificate', {
          defaultValue: '{{type}}: {{state}}',
          type: t(`tendering.award_panel.cert_type.${f.document_type}`, { defaultValue: f.document_type }),
          state: t(`tendering.award_panel.cert_state.${f.state}`, { defaultValue: f.state ?? '' }),
        })
      : t(`tendering.award_panel.block_reason.${f.code}`, { defaultValue: f.code });

  const field = (
    id: keyof AwardTerms,
    label: string,
    suffix: string,
    hint?: string,
  ) => (
    <label className="flex flex-col gap-1" key={id}>
      <span className="oe-label">{label}</span>
      <span className="flex items-center gap-1">
        <input
          className="oe-input w-full text-right tabular-nums"
          inputMode="decimal"
          disabled={!editable}
          value={draft[id] == null ? '' : String(draft[id])}
          onChange={(e) => {
            const v = optional(e.target.value);
            if (id === 'payment_discount_days') set({ payment_discount_days: v == null ? null : Number.parseInt(v, 10) || 0 });
            else if (id === 'discount_percent') set({ discount_percent: v ?? '0' });
            else set({ [id]: v } as Partial<AwardTerms>);
          }}
          data-testid={`award-terms-${id}`}
        />
        <span className="w-10 text-xs text-content-tertiary">{suffix}</span>
      </span>
      {hint && <span className="text-2xs text-content-tertiary">{hint}</span>}
    </label>
  );

  return (
    <div className="flex flex-col gap-4" data-testid="award-terms-panel">
      <div className="flex flex-wrap items-center gap-2">
        <label className="oe-label" htmlFor="award-bid">
          {t('tendering.award_panel.firm', { defaultValue: 'Award to' })}
        </label>
        <select
          id="award-bid"
          className="oe-select w-72"
          value={draft.bid_id}
          disabled={!editable}
          onChange={(e) => setDraft(stored.data?.terms?.bid_id === e.target.value ? stored.data.terms : emptyTerms(e.target.value))}
        >
          {candidates.map((b) => (
            <option key={b.id} value={b.id}>
              {b.company_name} ({fmtCurrency(b.total_amount, b.currency)})
            </option>
          ))}
        </select>
        {subId && (
          <Link to={`/subcontractors?sub=${subId}`} className="text-xs text-oe-blue hover:underline">
            {t('tendering.award_panel.open_firm', { defaultValue: 'Open the firm' })}
          </Link>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-4 lg:col-span-2">
          <Card className="p-4">
            <h3 className="oe-card-title mb-3">
              {t('tendering.award_panel.rounds', { defaultValue: 'Negotiation rounds' })}
            </h3>
            {bidRounds.length === 0 ? (
              <p className="text-sm text-content-tertiary">
                {t('tendering.award_panel.no_rounds', {
                  defaultValue: 'No rounds yet: the award rests on the bid as submitted.',
                })}
              </p>
            ) : (
              <table className="oe-table oe-table-compact w-full">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t('tendering.award_panel.offer', { defaultValue: 'Offer' })}</th>
                    <th className="text-right">{t('tendering.award_panel.discount', { defaultValue: 'Discount' })}</th>
                    <th className="text-right">{t('tendering.award_panel.contract_sum', { defaultValue: 'Contract sum' })}</th>
                    <th />
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {bidRounds.map((r) => (
                    <tr key={r.id}>
                      <td className="tabular-nums">{r.round_no}</td>
                      <td>
                        {r.pricing_mode === 'lump_sum'
                          ? t('tendering.award_panel.lump_sum_of', { defaultValue: 'Lump sum {{amount}}', amount: money(r.lump_sum) })
                          : t('tendering.award_panel.unit_prices_of', { defaultValue: 'Unit prices {{amount}}', amount: money(r.lines_total) })}
                        {r.note && <span className="block text-2xs text-content-tertiary">{r.note}</span>}
                      </td>
                      <td className="text-right tabular-nums">{r.discount_percent} %</td>
                      <td className="text-right tabular-nums">{money(r.contract_sum)}</td>
                      <td>
                        {r.is_final && (
                          <Badge variant={r.approved_at ? 'success' : 'warning'}>
                            {r.approved_at
                              ? t('tendering.award_panel.final_approved', {
                                  defaultValue: 'Final, approved {{date}}',
                                  date: fmtDate(r.approved_at),
                                })
                              : t('tendering.award_panel.final', { defaultValue: 'Final offer' })}
                          </Badge>
                        )}
                      </td>
                      <td className="whitespace-nowrap text-right">
                        {editable && (
                          <span className="inline-flex gap-1">
                            <Button size="sm" variant="ghost" onClick={() => setDraft(termsFromRound(draft, r))}>
                              {t('tendering.award_panel.use_round', { defaultValue: 'Use' })}
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              icon={<Flag size={14} />}
                              onClick={() => final.mutate({ id: r.id, value: !r.is_final })}
                            >
                              {r.is_final
                                ? t('tendering.award_panel.unmark_final', { defaultValue: 'Not final' })
                                : t('tendering.award_panel.mark_final', { defaultValue: 'Mark final' })}
                            </Button>
                            {r.is_final && !r.approved_at && (
                              <Button
                                size="sm"
                                variant="secondary"
                                icon={<CheckCircle2 size={14} />}
                                loading={approve.isPending}
                                onClick={() => approve.mutate(r.id)}
                              >
                                {t('tendering.award_panel.approve', { defaultValue: 'Approve' })}
                              </Button>
                            )}
                            {!r.approved_at && (
                              <Button
                                size="sm"
                                variant="ghost"
                                icon={<Trash2 size={14} />}
                                aria-label={t('tendering.award_panel.delete_round', { defaultValue: 'Delete round' })}
                                onClick={() => remove.mutate(r.id)}
                              />
                            )}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {editable && (
              <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-border-light pt-3">
                <select
                  className="oe-select w-44"
                  value={roundMode}
                  onChange={(e) => setRoundMode(e.target.value as PricingMode)}
                  aria-label={t('tendering.award_panel.round_mode', { defaultValue: 'Offer type' })}
                >
                  <option value="lump_sum">{t('tendering.award_panel.mode_lump_sum', { defaultValue: 'Revised lump sum' })}</option>
                  <option value="unit_price">{t('tendering.award_panel.mode_unit_price', { defaultValue: 'Unit prices with discount' })}</option>
                </select>
                {roundMode === 'lump_sum' && (
                  <input
                    className="oe-input w-36 text-right tabular-nums"
                    inputMode="decimal"
                    value={roundLump}
                    onChange={(e) => setRoundLump(e.target.value)}
                    placeholder={t('tendering.award_panel.lump_sum', { defaultValue: 'Lump sum' })}
                  />
                )}
                <input
                  className="oe-input w-24 text-right tabular-nums"
                  inputMode="decimal"
                  value={roundDiscount}
                  onChange={(e) => setRoundDiscount(e.target.value)}
                  placeholder={t('tendering.award_panel.discount_pct', { defaultValue: 'Discount %' })}
                />
                <input
                  className="oe-input min-w-40 flex-1"
                  value={roundNote}
                  onChange={(e) => setRoundNote(e.target.value)}
                  placeholder={t('tendering.award_panel.round_note', { defaultValue: 'What was agreed (optional)' })}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  loading={add.isPending}
                  disabled={roundMode === 'lump_sum' && !optional(roundLump)}
                  onClick={() => add.mutate(draft.bid_id)}
                >
                  {t('tendering.award_panel.add_round', { defaultValue: 'Add round' })}
                </Button>
              </div>
            )}
          </Card>

          <Card className="p-4">
            <h3 className="oe-card-title mb-3">{t('tendering.award_panel.terms', { defaultValue: 'Award terms' })}</h3>
            <div className="grid gap-3 sm:grid-cols-3">
              {field('discount_percent', t('tendering.award_panel.discount', { defaultValue: 'Discount' }), '%')}
              {field(
                'lump_sum',
                t('tendering.award_panel.lump_sum', { defaultValue: 'Lump sum' }),
                currency,
                t('tendering.award_panel.lump_sum_hint', { defaultValue: 'Empty: the priced lines decide.' }),
              )}
              {field('retention_percent', t('tendering.award_panel.retention', { defaultValue: 'Retention per payment' }), '%')}
              {field(
                'retention_cap_percent',
                t('tendering.award_panel.retention_cap', { defaultValue: 'Retention cap' }),
                '%',
                t('tendering.award_panel.retention_cap_hint', { defaultValue: 'Of the contract sum' }),
              )}
              {field('payment_discount_percent', t('tendering.award_panel.payment_discount', { defaultValue: 'Payment discount' }), '%')}
              {field('payment_discount_days', t('tendering.award_panel.payment_discount_days', { defaultValue: 'If paid within' }), t('tendering.award_panel.days', { defaultValue: 'days' }))}
            </div>
            <label className="mt-3 flex flex-col gap-1">
              <span className="oe-label">{t('tendering.award_panel.note', { defaultValue: 'Note' })}</span>
              <textarea
                className="oe-textarea"
                rows={2}
                disabled={!editable}
                value={draft.note}
                onChange={(e) => set({ note: e.target.value })}
              />
            </label>
            {editable && (
              <div className="mt-3 flex justify-end">
                <Button variant="secondary" loading={save.isPending} onClick={() => save.mutate(draft)}>
                  {t('tendering.award_panel.save', { defaultValue: 'Save terms' })}
                </Button>
              </div>
            )}
          </Card>
        </div>

        <Card className="flex flex-col gap-3 p-4" data-testid="award-summary">
          <h3 className="oe-card-title">{t('tendering.award_panel.summary', { defaultValue: 'Contract draft' })}</h3>
          {p && (
            <>
              <dl className="grid grid-cols-2 gap-y-1 text-sm">
                <dt className="text-content-secondary">{t('tendering.award_panel.offer', { defaultValue: 'Offer' })}</dt>
                <dd className="text-right tabular-nums">{money(p.offer_total)}</dd>
                <dt className="text-content-secondary">
                  {t('tendering.award_panel.discount_amount', { defaultValue: 'Discount {{pct}} %', pct: p.discount_percent })}
                </dt>
                <dd className="text-right tabular-nums">- {money(p.discount_amount)}</dd>
                <dt className="font-medium text-content-primary">{t('tendering.award_panel.contract_sum', { defaultValue: 'Contract sum' })}</dt>
                <dd className="text-right text-xl font-semibold tabular-nums" data-testid="award-contract-sum">
                  {money(p.contract_sum)}
                </dd>
                <dt className="text-content-secondary">{t('tendering.award_panel.contract_type', { defaultValue: 'Contract type' })}</dt>
                <dd className="text-right">
                  {p.contract_type === 'lump_sum'
                    ? t('tendering.award_panel.type_lump_sum', { defaultValue: 'Lump sum' })
                    : t('tendering.award_panel.type_unit_price', { defaultValue: 'Unit price' })}
                </dd>
                {p.retention_cap_amount && (
                  <>
                    <dt className="text-content-secondary">{t('tendering.award_panel.retention_cap', { defaultValue: 'Retention cap' })}</dt>
                    <dd className="text-right tabular-nums">{money(p.retention_cap_amount)}</dd>
                  </>
                )}
              </dl>
              {p.round_no !== null && (
                <p className="text-xs text-content-tertiary">
                  {t('tendering.award_panel.rests_on_round', { defaultValue: 'Rests on round {{no}}', no: p.round_no })}
                </p>
              )}
              {p.blockers.length > 0 && (
                <ul className="flex flex-col gap-1 rounded-lg border border-semantic-error/30 bg-semantic-error-bg p-2 text-xs" data-testid="award-blockers">
                  {p.blockers.map((rule, i) => (
                    <li key={`${rule.rule_id}-${i}`} className="flex gap-1 text-semantic-error">
                      <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
                      <span>{ruleText(rule)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {p.gate.findings.length > 0 && (
                <ul className="flex flex-col gap-0.5 text-xs text-content-secondary" data-testid="award-gate">
                  {p.gate.findings.map((f, i) => (
                    <li key={`${f.code}-${i}`} className={f.severity === 'error' ? 'text-semantic-error' : 'text-semantic-warning'}>
                      {findingText(f)}
                      {f.lapsed_on ? ` (${fmtDate(f.lapsed_on)})` : ''}
                    </li>
                  ))}
                  {subId && (
                    <li>
                      <Link to={`/subcontractors?sub=${subId}`} className="text-oe-blue hover:underline">
                        {t('tendering.award_panel.open_firm', { defaultValue: 'Open the firm' })}
                      </Link>
                    </li>
                  )}
                </ul>
              )}
              {p.warnings.length > 0 && (
                <ul className="flex flex-col gap-1 text-xs text-semantic-warning">
                  {p.warnings.map((rule, i) => (
                    <li key={`${rule.rule_id}-${i}`}>{ruleText(rule)}</li>
                  ))}
                </ul>
              )}
              {editable ? (
                <Button
                  variant="primary"
                  icon={<Gavel size={16} />}
                  disabled={!p.can_award || awarding || save.isPending}
                  loading={awarding}
                  onClick={async () => {
                    await save.mutateAsync(draft);
                    onAward(draft.bid_id);
                  }}
                  data-testid="award-submit"
                >
                  {t('tendering.award_panel.award', { defaultValue: 'Save terms and award' })}
                </Button>
              ) : (
                stored.data?.contract_code && (
                  <p className="text-xs text-content-secondary">
                    {t('tendering.award_panel.contract_drafted', {
                      defaultValue: 'Contract {{code}} drafted from these terms.',
                      code: stored.data.contract_code,
                    })}
                  </p>
                )
              )}
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
