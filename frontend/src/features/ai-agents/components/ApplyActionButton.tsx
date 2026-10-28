// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Apply-action affordances for a completed agent run.
//
// The BOQ-drafter agent's whole value is "turn a brief into priced BOQ
// positions". The runner emits each line as a `create_position` observation
// during the loop, but the run's final answer is markdown - so the structured
// proposals used to be lost and this panel could only deep-link to the BOQ
// editor and ask the user to re-type every line by hand.
//
// Now it reads the run's recovered proposals from the backend
// (`GET /runs/{id}/proposals`, which extracts them from the persisted steps),
// lets the user pick a BOQ, and applies them as REAL positions via
// `POST /runs/{id}/apply`. Per the architecture guide "AI-augmented,
// human-confirmed" the user explicitly clicks Apply against a chosen BOQ -
// nothing is ever written automatically, and currencies are never blended.
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ListChecks,
  Copy,
  Check,
  ArrowRight,
  Loader2,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react';
import clsx from 'clsx';

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { copyToClipboard } from '@/shared/lib/browser';
import { aiAgentsApi, type ApplyProposalsResult } from '../api';
import { fmtFixed } from '@/shared/lib/formatters';

// ── Legacy client-side proposal parser ────────────────────────────────────────
// Kept as an exported pure helper: the live panel now reads proposals from the
// backend (recovered from the run's steps, the authoritative source), but this
// JSON-final-output parser remains a useful, tested fallback for callers that
// only have the raw output text.

interface ParsedProposal {
  description: string;
  unit: string;
  qty: number;
  unit_rate: number;
  total: number;
  currency: string;
}

function asNumber(v: unknown): number {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function isPositionLike(v: unknown): v is Record<string, unknown> {
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof (v as Record<string, unknown>).description === 'string' &&
    'unit' in v
  );
}

/** Pull BOQ-position proposals out of a JSON final-output string, if any. */
export function extractPositionProposals(text: string): ParsedProposal[] {
  const trimmed = text.trim();
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return [];
  }
  let candidates: unknown[] = [];
  if (Array.isArray(parsed)) candidates = parsed;
  else if (isPositionLike(parsed)) candidates = [parsed];
  else if (parsed && typeof parsed === 'object') {
    const obj = parsed as Record<string, unknown>;
    const arr = obj.positions ?? obj.proposals ?? obj.items;
    if (Array.isArray(arr)) candidates = arr;
    else if (isPositionLike(parsed)) candidates = [parsed];
  }

  return candidates.filter(isPositionLike).map((c) => {
    const qty = asNumber(c.qty ?? c.quantity);
    const rate = asNumber(c.unit_rate ?? c.rate);
    return {
      description: String(c.description ?? '').trim(),
      unit: String(c.unit ?? '').trim(),
      qty,
      unit_rate: rate,
      total: asNumber(c.total) || Number((qty * rate).toFixed(2)),
      currency: String(c.currency ?? '').trim().toUpperCase(),
    };
  });
}

interface ApplyActionButtonProps {
  /** The completed run's id - proposals + apply are keyed by it. */
  runId: string;
}

export function ApplyActionButton({ runId }: ApplyActionButtonProps): JSX.Element | null {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [selectedBoqId, setSelectedBoqId] = useState<string>('');
  const [result, setResult] = useState<ApplyProposalsResult | null>(null);

  // The proposals come from the backend (recovered from the run's steps), so
  // markdown-only runs correctly report zero and this panel hides itself.
  const proposalsQuery = useQuery({
    queryKey: ['ai-agents', 'proposals', runId],
    queryFn: () => aiAgentsApi.getRunProposals(runId),
    staleTime: 60_000,
  });

  // BOQs the user can apply into - only fetched once there are proposals AND a
  // project is active (the apply target lives in a project's BOQ).
  const hasProposals = (proposalsQuery.data?.count ?? 0) > 0;
  const boqsQuery = useQuery({
    queryKey: ['ai-agents', 'apply-boqs', projectId ?? null],
    queryFn: () => aiAgentsApi.listProjectBoqs(projectId!),
    enabled: hasProposals && !!projectId,
    staleTime: 30_000,
  });

  const applyMutation = useMutation({
    mutationFn: (boqId: string) => aiAgentsApi.applyRunProposals(runId, { boq_id: boqId }),
    onSuccess: (res) => {
      setResult(res);
      // The target BOQ now has new rows - drop its cached detail/list so the
      // BOQ editor reflects them when the user clicks through.
      queryClient.invalidateQueries({ queryKey: ['boq'] });
      if (res.created > 0) {
        addToast({
          type: 'success',
          title: t('agents.apply.applied_toast', {
            defaultValue: '{{count}} position(s) added to the BOQ',
            count: res.created,
          }),
          message:
            res.skipped > 0
              ? t('agents.apply.skipped_note', {
                  defaultValue: '{{count}} line(s) skipped (currency mismatch or no price).',
                  count: res.skipped,
                })
              : undefined,
        });
      } else {
        addToast({
          type: 'warning',
          title: t('agents.apply.none_applied', {
            defaultValue: 'No positions were added',
          }),
          message: t('agents.apply.all_skipped', {
            defaultValue: 'Every line was skipped - check the currency matches the project.',
          }),
        });
      }
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('agents.apply.apply_error', { defaultValue: 'Could not apply the positions' }),
      });
    },
  });

  const proposals = proposalsQuery.data?.proposals ?? [];

  // Money rule: never blend currencies. Only show a combined total when every
  // proposal shares one currency; otherwise show the count only.
  const { singleCurrency, combinedTotal } = useMemo(() => {
    const currencies = new Set(proposals.map((p) => p.currency).filter(Boolean));
    const single = currencies.size === 1 ? [...currencies][0] : null;
    const total = single
      ? proposals.reduce((sum, p) => sum + (Number(p.total) || 0), 0)
      : null;
    return { singleCurrency: single, combinedTotal: total };
  }, [proposals]);

  if (proposalsQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 p-3 text-xs text-content-tertiary">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t('agents.apply.checking', { defaultValue: 'Checking for BOQ positions…' })}
      </div>
    );
  }

  // No structured proposals -> this run was advisory; render nothing.
  if (!hasProposals) return null;

  const boqs = boqsQuery.data ?? [];
  const effectiveBoqId = selectedBoqId || boqs[0]?.id || '';

  const onCopy = () => {
    void copyToClipboard(JSON.stringify(proposals, null, 2)).then((ok) => {
      if (ok) {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1800);
      }
    });
  };

  return (
    <div className="rounded-lg border border-oe-blue/30 bg-oe-blue-subtle/50 p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-oe-blue-text">
        <ListChecks className="h-3.5 w-3.5" aria-hidden="true" />
        {t('agents.apply.title', { defaultValue: 'BOQ positions proposed' })}
      </div>
      <p className="mt-1 text-xs text-content-secondary">
        {t('agents.apply.detected', {
          defaultValue:
            '{{count}} position(s) detected. Pick a BOQ and apply them, or review first - nothing is added until you click Apply.',
          count: proposals.length,
        })}
      </p>

      <ul className="mt-2 space-y-1">
        {proposals.slice(0, 5).map((p, i) => (
          <li
            key={`${p.description}-${i}`}
            className="flex items-center justify-between gap-3 rounded-md bg-surface-elevated/70 px-2.5 py-1.5 text-xs"
          >
            <span className="min-w-0 truncate text-content-primary">{p.description || '—'}</span>
            <span className="shrink-0 text-content-tertiary">
              {p.qty} {p.unit}
              {p.currency ? ` · ${fmtFixed(Number(p.total), 2)} ${p.currency}` : ''}
            </span>
          </li>
        ))}
        {proposals.length > 5 && (
          <li className="px-2.5 text-2xs text-content-tertiary">
            {t('agents.apply.more', {
              defaultValue: '+{{count}} more',
              count: proposals.length - 5,
            })}
          </li>
        )}
      </ul>

      {combinedTotal !== null && singleCurrency && (
        <p className="mt-2 text-xs font-medium text-content-secondary">
          {t('agents.apply.combined_total', { defaultValue: 'Combined total' })}:{' '}
          {fmtFixed(combinedTotal, 2)} {singleCurrency}
        </p>
      )}

      {proposalsQuery.data?.mixed_currency && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-semantic-warning">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {t('agents.apply.mixed_currency', {
            defaultValue:
              'These lines span more than one currency. Only lines matching the project currency will be applied.',
          })}
        </p>
      )}

      {/* Apply result summary (after a successful apply). */}
      {result && (
        <div className="mt-3 rounded-md border border-semantic-success/30 bg-semantic-success-bg/60 p-2.5 text-xs">
          <p className="flex items-center gap-1.5 font-medium text-semantic-success">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            {t('agents.apply.result', {
              defaultValue: '{{created}} added, {{skipped}} skipped',
              created: result.created,
              skipped: result.skipped,
            })}
          </p>
          {result.skipped_reasons.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-content-tertiary">
              {result.skipped_reasons.slice(0, 4).map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Apply controls. */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {projectId ? (
          boqsQuery.isLoading ? (
            <span className="inline-flex items-center gap-1.5 text-2xs text-content-tertiary">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t('agents.apply.loading_boqs', { defaultValue: 'Loading BOQs…' })}
            </span>
          ) : boqs.length > 0 ? (
            <>
              <label htmlFor="apply-boq-select" className="sr-only">
                {t('agents.apply.choose_boq', { defaultValue: 'Choose a BOQ' })}
              </label>
              <select
                id="apply-boq-select"
                value={effectiveBoqId}
                onChange={(e) => setSelectedBoqId(e.target.value)}
                className="rounded-lg border border-border bg-surface-primary px-2.5 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
              >
                {boqs.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={!effectiveBoqId || applyMutation.isPending}
                onClick={() => effectiveBoqId && applyMutation.mutate(effectiveBoqId)}
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-semibold text-content-inverse transition-all',
                  'hover:bg-oe-blue-hover disabled:cursor-not-allowed disabled:opacity-40',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
                )}
              >
                {applyMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {t('agents.apply.apply_to_boq', { defaultValue: 'Apply to BOQ' })}
              </button>
            </>
          ) : (
            <Link
              to={`/projects/${projectId}/boq`}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-semibold text-content-inverse transition-all',
                'hover:bg-oe-blue-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
              )}
            >
              {t('agents.apply.create_boq_first', { defaultValue: 'Create a BOQ first' })}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          )
        ) : (
          <span className="text-2xs text-content-tertiary">
            {t('agents.apply.no_project', {
              defaultValue: 'Open a project to apply these positions to its BOQ.',
            })}
          </span>
        )}

        {projectId && (
          <Link
            to={`/projects/${projectId}/boq`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary hover:text-content-primary"
          >
            {t('agents.apply.review_in_boq', { defaultValue: 'Review in BOQ editor' })}
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        )}

        <button
          type="button"
          onClick={onCopy}
          className={clsx(
            'inline-flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-xs font-medium transition-colors',
            copied
              ? 'text-semantic-success'
              : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
          )}
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied
            ? t('agents.copied', { defaultValue: 'Copied' })
            : t('agents.apply.copy_json', { defaultValue: 'Copy as JSON' })}
        </button>
      </div>
    </div>
  );
}

export default ApplyActionButton;
