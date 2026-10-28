// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FX — the rates a project prices against, and where they came from.
 *
 * The screen answers three separate questions and keeps them apart, because
 * conflating them is how a converted figure ends up with nobody able to say
 * which rates produced it.
 *
 * `Convert` is the everyday question. Every answer carries its provenance:
 * which set, dated when, from which source. The conversion happens on the
 * server and the figure is rendered exactly as it arrived - nothing here
 * multiplies money. The only arithmetic on this screen is on rates, and it is
 * labelled as derived where it appears.
 *
 * `Rate sets` is the register. Locking is the operation that matters: a pin
 * onto an unlocked set is not a pin at all, because the next refresh can
 * rewrite the quotes underneath it and move a reproducible estimate without
 * anybody touching the project. The panel says so where the pin is made rather
 * than in a footnote.
 *
 * `Project policy` is the commitment. A project with no policy is the ordinary
 * state, not an error, so a 404 there renders as an invitation. And a
 * validation report over a project with no policy comes back with nothing
 * examined, which is shown as unchecked rather than as a pass - a project must
 * not be able to bank a green light from checks that never ran.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRightLeft,
  CalendarClock,
  CircleAlert,
  Coins,
  Lock,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Unlock,
  WifiOff,
} from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import {
  type ConvertMode,
  type ConvertResult,
  type FxPolicyRequest,
  type RateMode,
  type RateSetSummary,
  convert,
  deletePolicy,
  deleteRateSet,
  fetchPolicy,
  fetchRateSet,
  fetchRates,
  fetchStatus,
  fetchValidation,
  listRateSets,
  refreshRates,
  savePolicy,
  setRateSetLock,
} from './api';
import {
  type RateFreshness,
  type ValidationVerdict,
  appliedDateGapDays,
  formatDerivedRate,
  freshnessTone,
  inverseRate,
  normaliseCurrency,
  pinHolds,
  policyCurrencies,
  sourceTone,
  rateFreshness,
  uncoveredPolicyCurrencies,
  validationVerdict,
  verdictTone,
} from './fxRates';
import { fmtList } from '@/shared/lib/formatters';

type Tab = 'convert' | 'sets' | 'policy';

/** Today as `YYYY-MM-DD`, which is what every date field here speaks. */
function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * The three currency roles a policy declares, in the order they are worked in.
 *
 * Held as a typed tuple rather than built inline so the editor's `onChange`
 * writes a key TypeScript can still see is one of the three, instead of
 * widening the draft to a bare record.
 */
const CURRENCY_FIELDS = [
  'estimating_currency',
  'procurement_currency',
  'reporting_currency',
] as const;

type CurrencyField = (typeof CURRENCY_FIELDS)[number];

function currencyFieldLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  field: CurrencyField,
): string {
  switch (field) {
    case 'estimating_currency':
      return t('fx.field_estimating', { defaultValue: 'Estimates in' });
    case 'procurement_currency':
      return t('fx.field_procurement', { defaultValue: 'Buys in' });
    case 'reporting_currency':
      return t('fx.field_reporting', { defaultValue: 'Reports in' });
  }
}

/* ── Provenance, rendered the same way everywhere ──────────────────────── */

interface ProvenanceProps {
  asOf: string | null;
  source: string;
  origin: string;
  isLocked: boolean;
  requestedDate?: string | null;
}

/**
 * Where a figure's rates came from.
 *
 * The gap between the applied set and the date that was asked for is computed
 * here because the backend cannot report it: its lookup already filters to sets
 * on or before the date, so a set three years stale still "covers" the request.
 */
function Provenance({ asOf, source, origin, isLocked, requestedDate }: ProvenanceProps) {
  const { t } = useTranslation();
  const gap = appliedDateGapDays(asOf, requestedDate);

  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <Badge variant={sourceTone(source)} size="sm">
        {source || t('fx.source_unknown', { defaultValue: 'unknown source' })}
      </Badge>
      {asOf && (
        <span className="text-content-tertiary">
          {t('fx.rates_dated', { defaultValue: 'rates of {{date}}', date: asOf })}
        </span>
      )}
      {isLocked && (
        <Badge variant="blue" size="sm">
          <Lock size={10} className="mr-0.5 inline" />
          {t('fx.locked', { defaultValue: 'locked' })}
        </Badge>
      )}
      {origin && origin !== source && (
        <span className="text-content-tertiary">{origin}</span>
      )}
      {gap !== null && gap > 0 && (
        <Badge variant={gap > 30 ? 'warning' : 'neutral'} size="sm">
          {t('fx.applied_gap', {
            defaultValue: '{{count}} days before the date asked for',
            count: gap,
          })}
        </Badge>
      )}
    </div>
  );
}

/* ── Convert ───────────────────────────────────────────────────────────── */

function ConvertTab({ projectId }: { projectId: string | null }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [amount, setAmount] = useState('1000');
  const [from, setFrom] = useState('EUR');
  const [to, setTo] = useState('USD');
  const [mode, setMode] = useState<ConvertMode>('market');
  const [onDate, setOnDate] = useState('');
  const [result, setResult] = useState<ConvertResult | null>(null);

  const convertMutation = useMutation({
    mutationFn: () =>
      convert({
        amount: amount.trim(),
        from_currency: normaliseCurrency(from),
        to_currency: normaliseCurrency(to),
        mode,
        on_date: onDate || null,
        project_id: projectId,
      }),
    onSuccess: (data) => setResult(data),
    onError: (err) => {
      setResult(null);
      addToast({
        type: 'error',
        title: t('fx.convert_failed', { defaultValue: 'That could not be converted' }),
        message: getErrorMessage(err),
      });
    },
  });

  const derivedInverse = formatDerivedRate(inverseRate(result?.rate ?? null));
  const badPair =
    normaliseCurrency(from) === '' || normaliseCurrency(to) === '' || amount.trim() === '';

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-5">
        <label className="block sm:col-span-2">
          <span className="text-xs text-content-secondary">
            {t('fx.field_amount', { defaultValue: 'Amount' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm tabular-nums"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
          />
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('fx.field_from', { defaultValue: 'From' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm uppercase"
            value={from}
            maxLength={3}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('fx.field_to', { defaultValue: 'To' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm uppercase"
            value={to}
            maxLength={3}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('fx.field_on_date', { defaultValue: 'As it stood on' })}
          </span>
          <input
            type="date"
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
            value={onDate}
            onChange={(e) => setOnDate(e.target.value)}
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-content-secondary">
          <input
            type="radio"
            checked={mode === 'market'}
            onChange={() => setMode('market')}
          />
          {t('fx.mode_market', { defaultValue: 'Market rate' })}
        </label>
        <label className="flex items-center gap-1.5 text-xs text-content-secondary">
          <input type="radio" checked={mode === 'ppp'} onChange={() => setMode('ppp')} />
          {t('fx.mode_ppp', { defaultValue: 'Purchasing power' })}
        </label>
        <Button
          variant="primary"
          size="sm"
          disabled={badPair}
          loading={convertMutation.isPending}
          icon={<ArrowRightLeft size={14} />}
          onClick={() => convertMutation.mutate()}
        >
          {t('fx.action_convert', { defaultValue: 'Convert' })}
        </Button>
      </div>

      <p className="text-xs text-content-tertiary">
        {mode === 'ppp'
          ? t('fx.mode_ppp_note', {
              defaultValue:
                'Purchasing power answers what an amount buys in the other place, which is not what it exchanges for. Use it to compare costs across countries, never to settle an invoice.',
            })
          : t('fx.mode_market_note', {
              defaultValue:
                'Nothing is stored. The figure comes back from the server with the rate set that produced it named beside it.',
            })}
      </p>

      {result && (
        <div className="rounded-lg border border-border bg-surface-secondary p-3">
          {result.available && result.converted !== null ? (
            <>
              <div className="text-sm text-content-primary">
                <span className="tabular-nums">{result.amount}</span> {result.from_currency}
                {' = '}
                <span className="font-medium tabular-nums">{result.converted}</span>{' '}
                {result.to_currency}
              </div>
              {result.rate && (
                <div className="mt-0.5 text-xs text-content-tertiary">
                  {t('fx.rate_line', {
                    defaultValue: '1 {{from}} = {{rate}} {{to}}',
                    from: result.from_currency,
                    rate: result.rate,
                    to: result.to_currency,
                  })}
                  {derivedInverse && (
                    <span>
                      {' · '}
                      {t('fx.rate_inverse', {
                        defaultValue: '1 {{to}} = {{rate}} {{from}} (derived here)',
                        from: result.from_currency,
                        rate: derivedInverse,
                        to: result.to_currency,
                      })}
                    </span>
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="flex items-start gap-1.5 text-sm text-content-primary">
              <CircleAlert size={14} className="mt-0.5 shrink-0 text-semantic-error" />
              {t('fx.convert_unavailable', {
                defaultValue:
                  'These rates cannot price that pair. Nothing was converted, and no figure is shown rather than one that would be wrong.',
              })}
            </p>
          )}
          {result.note && <p className="mt-1 text-xs text-content-tertiary">{result.note}</p>}
          <div className="mt-2">
            <Provenance
              asOf={result.as_of}
              source={result.source}
              origin={result.origin}
              isLocked={result.is_locked}
              requestedDate={onDate || null}
            />
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Rate sets ─────────────────────────────────────────────────────────── */

function RateSetsTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [openId, setOpenId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RateSetSummary | null>(null);

  const setsQuery = useQuery({
    queryKey: ['fx', 'rate-sets'],
    queryFn: () => listRateSets({ limit: 50 }),
  });

  const detailQuery = useQuery({
    queryKey: ['fx', 'rate-set', openId],
    queryFn: () => fetchRateSet(openId as string),
    enabled: !!openId,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['fx', 'rate-sets'] });
    queryClient.invalidateQueries({ queryKey: ['fx', 'rate-set'] });
  };

  const lockMutation = useMutation({
    mutationFn: (args: { id: string; locked: boolean }) => setRateSetLock(args.id, args.locked),
    onSuccess: invalidate,
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('fx.lock_failed', { defaultValue: 'The set was not changed' }),
        message: getErrorMessage(err),
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteRateSet(id),
    onSuccess: () => {
      setPendingDelete(null);
      setOpenId(null);
      invalidate();
    },
    onError: (err) => {
      setPendingDelete(null);
      addToast({
        type: 'error',
        title: t('fx.delete_set_failed', { defaultValue: 'The set was not deleted' }),
        message: getErrorMessage(err),
      });
    },
  });

  const sets = setsQuery.data?.items ?? [];

  return (
    <div className="space-y-3">
      <p className="text-xs text-content-tertiary">
        {t('fx.sets_intro', {
          defaultValue:
            'Every set is the quotes of one base currency on one day, kept as it was recorded. Locking a set is what lets a project pin to it: an unlocked set can be rewritten by the next refresh, and an estimate pinned to it moves without anybody touching the project.',
        })}
      </p>

      {setsQuery.isLoading && (
        <p className="text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      )}

      {!setsQuery.isLoading && sets.length === 0 && (
        <EmptyState
          icon={<Coins size={28} />}
          title={t('fx.sets_empty_title', { defaultValue: 'The register is empty' })}
          description={t('fx.sets_empty_description', {
            defaultValue:
              'Pull the live feed to record the first set, or enter one by hand if this instance has no outbound network.',
          })}
        />
      )}

      {sets.length > 0 && (
        <ul className="space-y-1.5">
          {sets.map((set) => (
            <li key={set.id} className="rounded-lg border border-border bg-surface-primary p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  className="text-left text-sm text-content-primary hover:underline"
                  onClick={() => setOpenId(openId === set.id ? null : set.id)}
                >
                  <span className="font-medium">{set.base_currency}</span>{' '}
                  <span className="tabular-nums">{set.rate_date}</span>{' '}
                  <span className="text-xs text-content-tertiary">
                    {t('fx.set_quote_count', {
                      defaultValue: '{{count}} quotes',
                      count: set.quote_count,
                    })}
                  </span>
                </button>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant={sourceTone(set.source)} size="sm">
                    {set.source}
                  </Badge>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={set.is_locked ? <Unlock size={13} /> : <Lock size={13} />}
                    onClick={() => lockMutation.mutate({ id: set.id, locked: !set.is_locked })}
                  >
                    {set.is_locked
                      ? t('fx.action_unlock', { defaultValue: 'Unlock' })
                      : t('fx.action_lock', { defaultValue: 'Lock' })}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={set.is_locked}
                    icon={<Trash2 size={13} />}
                    onClick={() => setPendingDelete(set)}
                  >
                    {t('common.delete', { defaultValue: 'Delete' })}
                  </Button>
                </div>
              </div>
              {set.note && <p className="mt-1 text-xs text-content-tertiary">{set.note}</p>}

              {openId === set.id && (
                <div className="mt-2 border-t border-border pt-2">
                  {detailQuery.isLoading && (
                    <p className="text-xs text-content-tertiary">
                      {t('common.loading', { defaultValue: 'Loading...' })}
                    </p>
                  )}
                  {detailQuery.data && (
                    <div className="grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-3">
                      {Object.entries(detailQuery.data.rates)
                        .sort(([a], [b]) => a.localeCompare(b))
                        .map(([code, rate]) => (
                          <div key={code} className="flex justify-between gap-2">
                            <span className="text-content-secondary">{code}</span>
                            <span className="tabular-nums text-content-primary">{rate}</span>
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* The register asks for 50 of a 200 cap and has no way to ask for the
          next 50, so a long-running instance keeps recording sets that this
          list stops showing. Says so rather than ending on the 50th row. */}
      {setsQuery.data && <TruncationNotice page={setsQuery.data} />}

      <ConfirmDialog
        open={pendingDelete !== null}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && deleteMutation.mutate(pendingDelete.id)}
        title={t('fx.delete_set_title', { defaultValue: 'Delete this rate set?' })}
        message={t('fx.delete_set_message', {
          defaultValue:
            'Any figure that was converted with it stays as it was, but the rates behind it will no longer be here to show.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        variant="danger"
      />
    </div>
  );
}

/* ── Project policy ────────────────────────────────────────────────────── */

function PolicyTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<FxPolicyRequest>({
    estimating_currency: 'EUR',
    procurement_currency: 'EUR',
    reporting_currency: 'EUR',
    rate_mode: 'live',
    pinned_rate_set_id: null,
    max_rate_age_days: 7,
    note: '',
  });
  const [confirmClear, setConfirmClear] = useState(false);

  const policyQuery = useQuery({
    queryKey: ['fx', 'policy', projectId],
    queryFn: () => fetchPolicy(projectId),
    retry: false,
  });

  const validationQuery = useQuery({
    queryKey: ['fx', 'validation', projectId],
    queryFn: () => fetchValidation(projectId),
    retry: false,
  });

  const setsQuery = useQuery({
    queryKey: ['fx', 'rate-sets'],
    queryFn: () => listRateSets({ limit: 50 }),
  });

  const ratesQuery = useQuery({
    queryKey: ['fx', 'rates', 'policy-coverage'],
    queryFn: () => fetchRates({}),
  });

  const saveMutation = useMutation({
    mutationFn: () => savePolicy(projectId, draft),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ['fx', 'policy', projectId] });
      queryClient.invalidateQueries({ queryKey: ['fx', 'validation', projectId] });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('fx.policy_save_failed', { defaultValue: 'The policy was not saved' }),
        message: getErrorMessage(err),
      }),
  });

  const clearMutation = useMutation({
    mutationFn: () => deletePolicy(projectId),
    onSuccess: () => {
      setConfirmClear(false);
      queryClient.invalidateQueries({ queryKey: ['fx', 'policy', projectId] });
      queryClient.invalidateQueries({ queryKey: ['fx', 'validation', projectId] });
    },
    onError: (err) => {
      setConfirmClear(false);
      addToast({
        type: 'error',
        title: t('fx.policy_clear_failed', { defaultValue: 'The policy was not removed' }),
        message: getErrorMessage(err),
      });
    },
  });

  const policy = policyQuery.data;
  const verdict: ValidationVerdict = validationVerdict(validationQuery.data);
  const uncovered = useMemo(
    () =>
      policy && ratesQuery.data
        ? uncoveredPolicyCurrencies(policy, ratesQuery.data.rates, ratesQuery.data.base)
        : [],
    [policy, ratesQuery.data],
  );
  const holds = pinHolds(policy);

  const beginEdit = () => {
    if (policy) {
      setDraft({
        estimating_currency: policy.estimating_currency,
        procurement_currency: policy.procurement_currency,
        reporting_currency: policy.reporting_currency,
        rate_mode: policy.rate_mode,
        pinned_rate_set_id: policy.pinned_rate_set_id,
        max_rate_age_days: policy.max_rate_age_days,
        note: policy.note,
      });
    }
    setEditing(true);
  };

  if (policyQuery.isLoading) {
    return (
      <p className="text-sm text-content-tertiary">
        {t('common.loading', { defaultValue: 'Loading...' })}
      </p>
    );
  }

  // A 404 means the project has no policy, which is the ordinary state and is
  // rendered as an invitation below. Any other failure - a 500, a dropped
  // connection - must not borrow that wording: telling somebody "nothing is
  // broken" while the server is down is how a missing policy gets set twice.
  const policyLoadFailed =
    policyQuery.isError && !(policyQuery.error instanceof ApiError && policyQuery.error.status === 404);

  if (policyLoadFailed && !editing) {
    return (
      <ErrorState
        title={getErrorMessage(policyQuery.error)}
        onRetry={() => {
          void policyQuery.refetch();
        }}
      />
    );
  }

  if (!policy && !editing) {
    return (
      <EmptyState
        icon={<Coins size={28} />}
        title={t('fx.policy_empty_title', { defaultValue: 'This project has no currency policy' })}
        description={t('fx.policy_empty_description', {
          defaultValue:
            'That is the ordinary state and nothing is broken. Set one to declare which currency the project estimates in, buys in and reports in, and how old the rates behind it may be.',
        })}
        action={{
          label: t('fx.action_set_policy', { defaultValue: 'Set a policy' }),
          onClick: beginEdit,
        }}
      />
    );
  }

  return (
    <div className="space-y-3">
      {editing ? (
        <div className="space-y-3 rounded-lg border border-border bg-surface-primary p-3">
          <div className="grid gap-2 sm:grid-cols-3">
            {CURRENCY_FIELDS.map((field) => (
              <label key={field} className="block">
                <span className="text-xs text-content-secondary">
                  {currencyFieldLabel(t, field)}
                </span>
                <input
                  className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm uppercase"
                  maxLength={3}
                  value={draft[field]}
                  onChange={(e) =>
                    setDraft((current) => ({ ...current, [field]: e.target.value.toUpperCase() }))
                  }
                />
              </label>
            ))}
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs text-content-secondary">
                {t('fx.field_rate_mode', { defaultValue: 'Which rates apply' })}
              </span>
              <select
                className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
                value={draft.rate_mode}
                onChange={(e) =>
                  setDraft({ ...draft, rate_mode: e.target.value as RateMode })
                }
              >
                <option value="live">
                  {t('fx.rate_mode_live', { defaultValue: 'Whatever is current' })}
                </option>
                <option value="pinned">
                  {t('fx.rate_mode_pinned', { defaultValue: 'One set, pinned' })}
                </option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs text-content-secondary">
                {t('fx.field_max_age', { defaultValue: 'Rates may be this many days old' })}
              </span>
              <input
                type="number"
                min={0}
                className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm tabular-nums"
                value={draft.max_rate_age_days}
                onChange={(e) =>
                  setDraft({ ...draft, max_rate_age_days: Number(e.target.value) })
                }
              />
            </label>
          </div>

          {draft.rate_mode === 'pinned' && (
            <label className="block">
              <span className="text-xs text-content-secondary">
                {t('fx.field_pinned_set', { defaultValue: 'Pinned to' })}
              </span>
              <select
                className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
                value={draft.pinned_rate_set_id ?? ''}
                onChange={(e) =>
                  setDraft({ ...draft, pinned_rate_set_id: e.target.value || null })
                }
              >
                <option value="">
                  {t('fx.pinned_none', { defaultValue: 'Not chosen yet' })}
                </option>
                {(setsQuery.data?.items ?? []).map((set) => (
                  <option key={set.id} value={set.id}>
                    {set.base_currency} {set.rate_date} {set.source}
                    {set.is_locked ? '' : ` - ${t('fx.pinned_unlocked_suffix', { defaultValue: 'not locked' })}`}
                  </option>
                ))}
              </select>
              {/* A set the picker never loaded cannot be pinned, and the
                  hint below is about which set to pick, not about how many
                  were offered. */}
              {setsQuery.data && <TruncationNotice page={setsQuery.data} className="mt-1" />}
              <span className="mt-0.5 block text-[11px] text-content-tertiary">
                {t('fx.field_pinned_set_hint', {
                  defaultValue:
                    'Pin to a locked set. An unlocked one can be rewritten by the next refresh, and then the pin holds a moving target.',
                })}
              </span>
            </label>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
          </div>
        </div>
      ) : (
        policy && (
          <div className="space-y-2 rounded-lg border border-border bg-surface-primary p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="text-sm text-content-primary">
                {t('fx.policy_summary', {
                  defaultValue:
                    'Estimates in {{estimating}}, buys in {{procurement}}, reports in {{reporting}}.',
                  estimating: policy.estimating_currency,
                  procurement: policy.procurement_currency,
                  reporting: policy.reporting_currency,
                })}
              </div>
              <div className="flex gap-1.5">
                <Button variant="secondary" size="sm" onClick={beginEdit}>
                  {t('common.edit', { defaultValue: 'Edit' })}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmClear(true)}>
                  {t('fx.action_clear_policy', { defaultValue: 'Remove' })}
                </Button>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant={policy.rate_mode === 'pinned' ? 'blue' : 'neutral'} size="sm">
                {policy.rate_mode === 'pinned'
                  ? t('fx.rate_mode_pinned', { defaultValue: 'One set, pinned' })
                  : t('fx.rate_mode_live', { defaultValue: 'Whatever is current' })}
              </Badge>
              <Badge variant="neutral" size="sm">
                {t('fx.max_age_badge', {
                  defaultValue: 'up to {{count}} days old',
                  count: policy.max_rate_age_days,
                })}
              </Badge>
              {policy.pinned_rate_set && (
                <Badge variant={holds ? 'success' : 'warning'} size="sm">
                  {policy.pinned_rate_set.base_currency} {policy.pinned_rate_set.rate_date}
                </Badge>
              )}
            </div>

            {policy.rate_mode === 'pinned' && !holds && (
              <p className="flex items-start gap-1.5 rounded-md bg-semantic-warning-bg px-2 py-1.5 text-xs text-[#b45309]">
                <CircleAlert size={13} className="mt-0.5 shrink-0" />
                {policy.pinned_rate_set === null
                  ? t('fx.pin_missing', {
                      defaultValue:
                        'This project is set to price against a pinned set, and no set is pinned. Until one is, it is pricing against whatever is current.',
                    })
                  : t('fx.pin_unlocked', {
                      defaultValue:
                        'The pinned set is not locked, so the next refresh can rewrite the quotes underneath it. A pin onto an unlocked set does not hold.',
                    })}
              </p>
            )}

            {uncovered.length > 0 && (
              <p className="flex items-start gap-1.5 rounded-md bg-semantic-error-bg px-2 py-1.5 text-xs text-semantic-error">
                <CircleAlert size={13} className="mt-0.5 shrink-0" />
                {t('fx.policy_uncovered', {
                  defaultValue:
                    'The current rates cannot price {{codes}}, which this project declares. Figures in it will look finished and cannot be converted.',
                  codes: fmtList(uncovered),
                })}
              </p>
            )}

            {policy.note && <p className="text-xs text-content-tertiary">{policy.note}</p>}
            <p className="text-xs text-content-tertiary">
              {t('fx.policy_currencies_note', {
                defaultValue: 'Currencies in play: {{codes}}.',
                codes: fmtList(policyCurrencies(policy)),
              })}
            </p>
          </div>
        )
      )}

      {/* The rule set's own verdict, kept apart from what this screen derives. */}
      <div className="rounded-lg border border-border bg-surface-secondary p-3">
        <div className="flex items-center gap-1.5">
          <ShieldCheck size={13} />
          <span className="text-xs font-medium text-content-primary">
            {t('fx.validation_title', { defaultValue: 'What the rules say' })}
          </span>
          <Badge variant={verdictTone(verdict)} size="sm">
            {verdict === 'unchecked'
              ? t('fx.verdict_unchecked', { defaultValue: 'nothing was checked' })
              : verdict === 'errors'
                ? t('fx.verdict_errors', { defaultValue: 'errors' })
                : verdict === 'warnings'
                  ? t('fx.verdict_warnings', { defaultValue: 'warnings' })
                  : t('fx.verdict_passed', { defaultValue: 'passed' })}
          </Badge>
        </div>
        {verdict === 'unchecked' ? (
          <p className="mt-1 text-xs text-content-tertiary">
            {t('fx.verdict_unchecked_note', {
              defaultValue:
                'No rule examined this project, which is not the same as passing. Set a policy and the checks have something to read.',
            })}
          </p>
        ) : (
          <ul className="mt-1.5 space-y-1">
            {[...(validationQuery.data?.errors ?? []), ...(validationQuery.data?.warnings ?? [])].map(
              (finding, index) => (
                <li key={`${finding.rule_id}-${index}`} className="text-xs">
                  <span className="text-content-primary">{finding.message}</span>
                  {finding.suggestion && (
                    <span className="block text-content-tertiary">{finding.suggestion}</span>
                  )}
                </li>
              ),
            )}
          </ul>
        )}
      </div>

      <ConfirmDialog
        open={confirmClear}
        onCancel={() => setConfirmClear(false)}
        onConfirm={() => clearMutation.mutate()}
        title={t('fx.clear_policy_title', { defaultValue: 'Remove this policy?' })}
        message={t('fx.clear_policy_message', {
          defaultValue:
            'The project goes back to the platform defaults, and any pin it held is dropped.',
        })}
        confirmLabel={t('fx.action_clear_policy', { defaultValue: 'Remove' })}
        variant="danger"
      />
    </div>
  );
}

/* ── The panel ─────────────────────────────────────────────────────────── */

export function FxPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [tab, setTab] = useState<Tab>('convert');

  const statusQuery = useQuery({
    queryKey: ['fx', 'status'],
    queryFn: fetchStatus,
  });

  const policyQuery = useQuery({
    queryKey: ['fx', 'policy', activeProjectId],
    queryFn: () => fetchPolicy(activeProjectId as string),
    enabled: !!activeProjectId,
    retry: false,
  });

  const refreshMutation = useMutation({
    mutationFn: refreshRates,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['fx'] });
      addToast({
        type: result.network_ok ? 'success' : 'warning',
        title: result.network_ok
          ? t('fx.refresh_done', { defaultValue: 'The register was refreshed' })
          : t('fx.refresh_offline', { defaultValue: 'The feed could not be reached' }),
        message: result.note,
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('fx.refresh_failed', { defaultValue: 'The refresh did not run' }),
        message: getErrorMessage(err),
      }),
  });

  const status = statusQuery.data;
  const freshness: RateFreshness = rateFreshness({
    rateDate: status?.rates_as_of,
    onDate: todayIso(),
    maxAgeDays: policyQuery.data?.max_rate_age_days ?? 7,
    pinned: policyQuery.data?.rate_mode === 'pinned',
  });

  const tabs: Array<{ key: Tab; label: string }> = [
    { key: 'convert', label: t('fx.tab_convert', { defaultValue: 'Convert' }) },
    { key: 'sets', label: t('fx.tab_sets', { defaultValue: 'Rate sets' }) },
    { key: 'policy', label: t('fx.tab_policy', { defaultValue: 'This project' }) },
  ];

  /* Every hook is above this line. */

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface-primary p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={freshnessTone(freshness)} size="sm">
            <CalendarClock size={10} className="mr-0.5 inline" />
            {freshness === 'pinned'
              ? t('fx.freshness_pinned', { defaultValue: 'pinned' })
              : freshness === 'current'
                ? t('fx.freshness_current', { defaultValue: 'current' })
                : freshness === 'stale'
                  ? t('fx.freshness_stale', { defaultValue: 'older than this project allows' })
                  : freshness === 'future'
                    ? t('fx.freshness_future', { defaultValue: 'dated ahead' })
                    : t('fx.freshness_unknown', { defaultValue: 'no date' })}
          </Badge>
          {status?.rates_as_of && (
            <span className="text-xs text-content-tertiary">
              {t('fx.rates_dated', { defaultValue: 'rates of {{date}}', date: status.rates_as_of })}
            </span>
          )}
          {status && (
            <Badge variant={sourceTone(status.source)} size="sm">
              {status.source}
            </Badge>
          )}
          {status && (
            <span className="text-xs text-content-tertiary">
              {t('fx.status_counts', {
                defaultValue: '{{currencies}} currencies, {{sets}} sets',
                currencies: status.cached_currencies,
                sets: status.rate_sets,
              })}
            </span>
          )}
          {status && !status.network_ok && (
            <Badge variant="warning" size="sm">
              <WifiOff size={10} className="mr-0.5 inline" />
              {t('fx.offline', { defaultValue: 'feed unreachable' })}
            </Badge>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw size={13} />}
          loading={refreshMutation.isPending}
          onClick={() => refreshMutation.mutate()}
        >
          {t('fx.action_refresh', { defaultValue: 'Pull the feed now' })}
        </Button>
      </div>

      <div className="flex gap-1 border-b border-border">
        {tabs.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            className={
              'px-3 py-1.5 text-xs ' +
              (tab === entry.key
                ? 'border-b-2 border-oe-blue text-oe-blue-text'
                : 'text-content-secondary hover:text-content-primary')
            }
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === 'convert' && <ConvertTab projectId={activeProjectId} />}
      {tab === 'sets' && <RateSetsTab />}
      {tab === 'policy' &&
        (activeProjectId ? (
          <PolicyTab projectId={activeProjectId} />
        ) : (
          <EmptyState
            icon={<Coins size={28} />}
            title={t('fx.no_project', { defaultValue: 'Pick a project first' })}
            description={t('fx.no_project_hint', {
              defaultValue: 'A currency policy belongs to one project and is set on that project.',
            })}
          />
        ))}
    </div>
  );
}
