// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Bid / no-bid scorecard for one tender: rate five criteria 1-5, see the weighted
 * score against the threshold, record the decision (a person's, with a reason
 * when it goes against the score), then the outcome. Every change is logged.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle } from 'lucide-react';
import { Badge, Breadcrumb, Button, EmptyState, SkeletonTable } from '@/shared/ui';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { api, ledgerKey, scorecardKey, useLedger, useScorecard, type Scorecard, type ScorecardPatch } from './api';
import { CRITERIA, recommendationOf, weightedScore, type Criterion } from './logic';
import { fmtDate, fmtFixed, fmtNumberForInput } from '@/shared/lib/formatters';

const LABELS: Record<Criterion, [string, string]> = {
  client: ['Client', '5 = reliable payer, repeat or strategic client'],
  capacity: ['Capacity', '5 = people and equipment are free for this job'],
  risk: ['Risk', '5 = low risk: clear scope, fair contract, known site'],
  margin: ['Margin', '5 = healthy margin expected'],
  competition: ['Competition', '5 = few or weak competitors'],
};

function findingsOf(err: unknown): string[] {
  if (!(err instanceof ApiError) || err.status !== 409) return [];
  const detail = (err.body as { detail?: { findings?: { message: string }[] } } | null)?.detail;
  return detail?.findings?.map((f) => f.message) ?? [];
}

export function BidNoBidPage() {
  const { t } = useTranslation();
  const { tenderId } = useParams<{ tenderId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { data: card, isLoading, error } = useScorecard(tenderId);
  const { data: ledger } = useLedger(card?.project_id);
  const key = scorecardKey(tenderId ?? '');
  const [reason, setReason] = useState('');
  const [outcomeNote, setOutcomeNote] = useState('');
  const [blocked, setBlocked] = useState<string[]>([]);

  const fail = (err: unknown) => {
    const msgs = findingsOf(err);
    if (msgs.length) setBlocked(msgs);
    else addToast({ type: 'error', title: t('bid_no_bid.save_failed', { defaultValue: 'Change not saved' }), message: getErrorMessage(err) });
  };
  const done = (next: Scorecard) => {
    qc.setQueryData<Scorecard>(key, next);
    void qc.invalidateQueries({ queryKey: ledgerKey(next.project_id) });
    setBlocked([]);
  };

  const patch = async (body: ScorecardPatch, preview?: Scorecard) => {
    if (!card) return;
    if (preview) qc.setQueryData<Scorecard>(key, preview);
    try {
      done(await api.update(card.id, { ...body, version: card.version }));
    } catch (err) {
      qc.setQueryData<Scorecard>(key, card);
      fail(err);
    }
  };

  const rate = (k: Criterion, n: number) => {
    if (!card) return;
    const scores = { ...card.scores, [k]: n };
    const score = weightedScore(card.weights, scores);
    void patch(
      { scores: { [k]: n } },
      { ...card, scores, score: score == null ? null : fmtNumberForInput(score, 1), recommendation: recommendationOf(score, card.threshold) },
    );
  };

  const decide = async (decision: 'bid' | 'no_bid') => {
    if (!card) return;
    try {
      done(await api.decide(card.id, decision, reason, card.version));
      setReason('');
    } catch (err) {
      fail(err);
    }
  };

  const setOutcome = async (outcome: string) => {
    if (!card) return;
    try {
      done(await api.outcome(card.id, outcome, outcomeNote, card.version));
    } catch (err) {
      fail(err);
    }
  };

  if (isLoading) return <SkeletonTable rows={6} />;
  if (error || !card) {
    return (
      <EmptyState
        title={t('bid_no_bid.load_failed', { defaultValue: 'The scorecard could not be opened' })}
        description={error ? getErrorMessage(error) : ''}
      />
    );
  }

  const score = card.score == null ? null : Number(card.score);
  const recText =
    card.recommendation === 'bid'
      ? t('bid_no_bid.recommend_bid', { defaultValue: 'The score says: bid' })
      : card.recommendation === 'no_bid'
        ? t('bid_no_bid.recommend_no_bid', { defaultValue: 'The score says: no bid' })
        : t('bid_no_bid.incomplete', { defaultValue: 'Rate all five criteria to see the score' });
  const override = card.recommendation !== '' && reason.trim() === '';

  return (
    <div className="space-y-5 animate-fade-in pb-16" data-testid="bid-no-bid-page">
      <h1 className="sr-only">{t('bid_no_bid.title', { defaultValue: 'Bid / no-bid' })}</h1>
      <Breadcrumb
        items={[
          { label: t('tendering.title', { defaultValue: 'Tendering' }), to: '/tendering' },
          { label: card.tender_name },
          { label: t('bid_no_bid.title', { defaultValue: 'Bid / no-bid' }) },
        ]}
      />

      <section className="rounded-xl border border-border-light bg-surface-primary p-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-2xs uppercase tracking-wide text-content-tertiary">{t('bid_no_bid.score', { defaultValue: 'Score' })}</div>
            <div className="text-4xl font-bold tabular-nums text-content-primary" data-testid="bid-no-bid-score">
              {score == null ? '–' : fmtFixed(score, 1)}
              <span className="text-base font-normal text-content-tertiary"> / 100</span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-sm">
              <Badge variant={card.recommendation === 'bid' ? 'success' : card.recommendation === 'no_bid' ? 'warning' : 'neutral'}>{recText}</Badge>
            </div>
          </div>
          <label className="text-xs text-content-secondary">
            {t('bid_no_bid.threshold', { defaultValue: 'Threshold (bid from this score)' })}
            <input
              type="number"
              min={1}
              max={100}
              defaultValue={card.threshold}
              key={`th-${card.threshold}`}
              onBlur={(e) => {
                const n = Number(e.target.value);
                if (n >= 1 && n <= 100 && n !== card.threshold) void patch({ threshold: n });
              }}
              className="mt-1 block w-24 rounded border border-border-light bg-surface-primary px-2 py-1 text-right tabular-nums"
              data-testid="bid-no-bid-threshold"
            />
          </label>
        </div>
        <div className="relative mt-4 h-2 rounded-full bg-surface-secondary" aria-hidden="true">
          <div className="absolute inset-y-0 left-0 rounded-full bg-oe-blue" style={{ width: `${score ?? 0}%` }} />
          <div className="absolute -top-1 h-4 w-0.5 bg-content-primary" style={{ left: `${card.threshold}%` }} />
        </div>
      </section>

      <section className="overflow-x-auto rounded-xl border border-border-light bg-surface-primary">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-2xs uppercase tracking-wide text-content-tertiary">
              <th className="px-3 py-2">{t('bid_no_bid.criterion', { defaultValue: 'Criterion' })}</th>
              <th className="px-3 py-2">{t('bid_no_bid.weight', { defaultValue: 'Weight %' })}</th>
              <th className="px-3 py-2">{t('bid_no_bid.rating', { defaultValue: 'Rating 1-5' })}</th>
              <th className="px-3 py-2">{t('bid_no_bid.note', { defaultValue: 'Note' })}</th>
            </tr>
          </thead>
          <tbody>
            {CRITERIA.map((k) => (
              <tr key={k} className="border-t border-border-light align-top">
                <td className="px-3 py-2">
                  <div className="font-medium text-content-primary">{t(`bid_no_bid.criterion_${k}`, { defaultValue: LABELS[k][0] })}</div>
                  <div className="text-xs text-content-tertiary">{t(`bid_no_bid.hint_${k}`, { defaultValue: LABELS[k][1] })}</div>
                </td>
                <td className="px-3 py-2">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    defaultValue={card.weights[k]}
                    key={`w-${k}-${card.weights[k]}`}
                    onBlur={(e) => {
                      const n = Number(e.target.value);
                      if (n >= 0 && n <= 100 && n !== card.weights[k]) void patch({ weights: { [k]: n } });
                    }}
                    className="w-16 rounded border border-border-light bg-surface-primary px-2 py-1 text-right tabular-nums"
                    aria-label={t('bid_no_bid.weight', { defaultValue: 'Weight %' })}
                  />
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-1" role="group">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => rate(k, n)}
                        aria-pressed={card.scores[k] === n}
                        data-testid={`rate-${k}-${n}`}
                        className={clsx(
                          'h-8 w-8 rounded border text-sm tabular-nums',
                          card.scores[k] === n
                            ? 'border-oe-blue bg-oe-blue text-white'
                            : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                        )}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <input
                    type="text"
                    maxLength={500}
                    defaultValue={card.notes[k] ?? ''}
                    key={`n-${k}-${card.version}`}
                    onBlur={(e) => {
                      if (e.target.value !== (card.notes[k] ?? '')) void patch({ notes: { [k]: e.target.value } });
                    }}
                    className="w-full min-w-40 rounded border border-border-light bg-surface-primary px-2 py-1"
                    aria-label={t('bid_no_bid.note', { defaultValue: 'Note' })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {(card.findings.length > 0 || blocked.length > 0) && (
        <ul className="space-y-1 rounded-xl border border-border-light bg-surface-primary p-3 text-sm" data-testid="bid-no-bid-findings">
          {[...new Set([...blocked, ...card.findings.map((f) => f.message)])].map((m) => (
            <li key={m} className="flex items-start gap-2 text-semantic-warning">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{m}</span>
            </li>
          ))}
        </ul>
      )}

      <section className="rounded-xl border border-border-light bg-surface-primary p-4">
        <h2 className="text-sm font-semibold text-content-primary">{t('bid_no_bid.decision', { defaultValue: 'Decision' })}</h2>
        {card.decision && (
          <p className="mt-1 text-sm text-content-secondary" data-testid="bid-no-bid-decided">
            {t('bid_no_bid.decided_line', {
              defaultValue: 'Decided: {{decision}} by {{who}}',
              decision: card.decision === 'bid' ? t('bid_no_bid.bid', { defaultValue: 'Bid' }) : t('bid_no_bid.no_bid', { defaultValue: 'No bid' }),
              who: card.decided_by_name || '–',
            })}
            {card.decision_reason ? ` · ${card.decision_reason}` : ''}
          </p>
        )}
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={2000}
          rows={2}
          placeholder={t('bid_no_bid.reason_ph', { defaultValue: 'Reason (required when you go against the score)' })}
          className="mt-3 w-full rounded border border-border-light bg-surface-primary px-2 py-1 text-sm"
          data-testid="bid-no-bid-reason"
        />
        <div className="mt-2 flex flex-wrap gap-2">
          <Button variant={card.recommendation === 'bid' ? 'primary' : 'secondary'} onClick={() => void decide('bid')} data-testid="decide-bid">
            {t('bid_no_bid.decide_bid', { defaultValue: 'Record: bid' })}
          </Button>
          <Button variant={card.recommendation === 'no_bid' ? 'primary' : 'secondary'} onClick={() => void decide('no_bid')} data-testid="decide-no-bid">
            {t('bid_no_bid.decide_no_bid', { defaultValue: 'Record: no bid' })}
          </Button>
          {override && card.recommendation !== '' && (
            <span className="self-center text-xs text-content-tertiary">
              {t('bid_no_bid.override_hint', { defaultValue: 'Going against the score needs a reason.' })}
            </span>
          )}
        </div>

        {card.decision === 'bid' && (
          <div className="mt-4 border-t border-border-light pt-3">
            <div className="text-xs text-content-secondary">{t('bid_no_bid.outcome', { defaultValue: 'Outcome (feeds the win-loss ledger)' })}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {(['won', 'lost', 'withdrawn'] as const).map((o) => (
                <Button key={o} size="sm" variant={card.outcome === o ? 'primary' : 'secondary'} onClick={() => void setOutcome(card.outcome === o ? '' : o)}>
                  {t(`bid_no_bid.outcome_${o}`, { defaultValue: o === 'won' ? 'Won' : o === 'lost' ? 'Lost' : 'Withdrawn' })}
                </Button>
              ))}
              <input
                type="text"
                value={outcomeNote}
                onChange={(e) => setOutcomeNote(e.target.value)}
                placeholder={t('bid_no_bid.outcome_note', { defaultValue: 'Why (price, scope, relationship...)' })}
                className="min-w-56 flex-1 rounded border border-border-light bg-surface-primary px-2 py-1 text-sm"
              />
            </div>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-border-light bg-surface-primary p-4">
        <h2 className="text-sm font-semibold text-content-primary">{t('bid_no_bid.ledger', { defaultValue: 'Win-loss ledger of this project' })}</h2>
        {ledger && (
          <>
            <p className="mt-1 text-xs text-content-secondary" data-testid="bid-no-bid-ledger-summary">
              {t('bid_no_bid.ledger_summary', {
                defaultValue: '{{bid}} bid, {{noBid}} no bid, {{won}} won, {{lost}} lost, win rate {{rate}}',
                bid: ledger.summary.bid,
                noBid: ledger.summary.no_bid,
                won: ledger.summary.won,
                lost: ledger.summary.lost,
                rate: ledger.summary.win_rate_pct == null ? '–' : `${ledger.summary.win_rate_pct}%`,
              })}
            </p>
            <ul className="mt-2 divide-y divide-border-light text-sm">
              {ledger.rows.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                  <span className="text-content-primary">{r.tender_name}</span>
                  <span className="flex items-center gap-2 text-xs text-content-secondary">
                    <span className="tabular-nums">{r.score ?? '–'}</span>
                    {r.decision ? <Badge variant={r.decision === 'bid' ? 'blue' : 'neutral'}>{r.decision === 'bid' ? t('bid_no_bid.bid', { defaultValue: 'Bid' }) : t('bid_no_bid.no_bid', { defaultValue: 'No bid' })}</Badge> : null}
                    {r.outcome ? <Badge variant={r.outcome === 'won' ? 'success' : 'warning'}>{t(`bid_no_bid.outcome_${r.outcome}`, { defaultValue: r.outcome })}</Badge> : null}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="rounded-xl border border-border-light bg-surface-primary p-4">
        <h2 className="text-sm font-semibold text-content-primary">{t('bid_no_bid.trail', { defaultValue: 'Audit trail' })}</h2>
        <ul className="mt-2 space-y-1 text-xs text-content-secondary" data-testid="bid-no-bid-trail">
          {card.events.map((e) => (
            <li key={e.id}>
              <span className="tabular-nums text-content-tertiary">{fmtDate(e.created_at, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
              {' · '}
              {e.user_name || '–'}
              {' · '}
              {e.message}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
