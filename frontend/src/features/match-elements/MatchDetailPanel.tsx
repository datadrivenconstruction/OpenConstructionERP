// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Slide-over detail panel for a single match group.
// 3 tabs: Elements · Method comparison · Apply preview.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, CheckCircle2, ChevronRight, Loader2, AlertCircle, XCircle, Sparkles } from 'lucide-react';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { AITrustNote } from '@/shared/ui';
import {
  matchElementsApi,
  type ConfidenceBand,
  type GroupSummary,
  type MatchCandidate,
} from './api';
import {
  buildMatchReasons,
  indexTemplatesBySignature,
  isPriorPickCandidate,
  priorConfirmReason,
  priorPickForSignature,
  reasoningText,
  type MatchReason,
} from './matchReasons';
import { NoMatchModal } from './NoMatchModal';
import { SymbolSuggestionPanel } from './SymbolSuggestionPanel';
import { getIntlLocale, fmtFixed } from '@/shared/lib/formatters';

type DetailTabKey = 'methods' | 'elements' | 'apply';
const DETAIL_TAB_IDS: readonly DetailTabKey[] = ['methods', 'elements', 'apply'];

interface Props {
  sessionId: string;
  group: GroupSummary | null;
  // Project the session belongs to - threaded so a match-quality verdict can
  // be attributed to the right project (verified server-side).
  projectId?: string | null;
  onClose: () => void;
}

function ConfidencePill({ band, score }: { band: ConfidenceBand; score: number }) {
  const cls =
    band === 'high'
      ? 'bg-emerald-500'
      : band === 'medium'
        ? 'bg-amber-500'
        : band === 'low'
          ? 'bg-rose-500'
          : 'bg-slate-400';
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-white text-xs ${cls}`}>
      {fmtFixed(score, 2)}
    </span>
  );
}

/** Plain-language chips explaining why a candidate ranked - matched unit,
 *  trade, size, keyword overlap, prior confirmations. The reasons are
 *  derived in the tested matchReasons helper; here we only translate and
 *  colour them by tone. */
function ReasonChips({ reasons }: { reasons: MatchReason[] }) {
  const { t } = useTranslation();
  if (reasons.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {reasons.map((r) => (
        <span
          key={r.id}
          className={
            r.tone === 'negative'
              ? 'inline-flex items-center rounded px-1.5 py-0.5 text-[10px] bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300'
              : r.tone === 'neutral'
                ? 'inline-flex items-center rounded px-1.5 py-0.5 text-[10px] bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
                : 'inline-flex items-center rounded px-1.5 py-0.5 text-[10px] bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
          }
        >
          {t(r.i18nKey, { defaultValue: r.defaultLabel, ...(r.vars ?? {}) })}
        </span>
      ))}
    </div>
  );
}

export function MatchDetailPanel({ sessionId, group, projectId, onClose }: Props) {
  const { t } = useTranslation();
  // Issue #270: the apply-preview shows quantities x rates; convert each
  // quantity to the user's system and restate the paired rate reciprocally so
  // the line reconciles. Money line totals + the grand total are invariant.
  const q = useDisplayQuantity();
  const qc = useQueryClient();
  const [tab, setTab] = useState<DetailTabKey>('methods');
  const onTabKeyDown = useTabKeyboardNav<DetailTabKey>({
    ids: DETAIL_TAB_IDS,
    activeId: tab,
    onChange: setTab,
    orientation: 'horizontal',
  });
  const [noMatchOpen, setNoMatchOpen] = useState(false);
  const panelRef = useRef<HTMLElement | null>(null);
  const closeBtnRef = useRef<HTMLButtonElement | null>(null);

  const detailQ = useQuery({
    enabled: !!group,
    queryKey: ['match-detail', sessionId, group?.group_key],
    queryFn: () => matchElementsApi.getGroup(sessionId, group!.group_key),
  });

  const applyQ = useQuery({
    enabled: !!group && tab === 'apply',
    queryKey: ['match-apply-preview', sessionId, group?.group_key],
    queryFn: () =>
      matchElementsApi.apply(sessionId, {
        dry_run: true,
        group_keys: [group!.group_key],
      }),
  });

  const confirmMut = useMutation({
    mutationFn: async (cand: MatchCandidate) => {
      if (!group) throw new Error('no group');
      return matchElementsApi.confirm(sessionId, {
        group_key: group.group_key,
        candidate_id: cand.id,
        method: 'manual',
        confidence: cand.score,
        save_to_template_library: true,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-detail', sessionId] });
    },
  });

  const methods = detailQ.data?.methods ?? {};
  const methodNames = useMemo(
    () => Object.keys(methods).filter((k) => (methods[k] ?? []).length > 0),
    [methods],
  );

  // The honest confidence to surface is the best candidate score across the
  // methods that ran (scores are already 0..1). null when nothing has matched
  // yet, so the trust note simply omits a confidence rather than implying one.
  const topScore = useMemo(() => {
    let best: number | null = null;
    for (const name of methodNames) {
      for (const cand of methods[name] ?? []) {
        if (typeof cand.score === 'number' && (best === null || cand.score > best)) {
          best = cand.score;
        }
      }
    }
    return best;
  }, [methodNames, methods]);

  // Cross-project memory: did the caller map a group with this same
  // signature before? The library query shares the ['match-templates'] key
  // with the TemplatesPanel so it dedupes. When there is a prior pick we
  // badge the group and mark the exact candidate that was chosen last time.
  const templatesQ = useQuery({
    queryKey: ['match-templates'],
    queryFn: matchElementsApi.listTemplates,
    staleTime: 60_000,
  });
  const priorPick = useMemo(
    () =>
      priorPickForSignature(
        group?.signature ?? null,
        indexTemplatesBySignature(templatesQ.data ?? []),
      ),
    [templatesQ.data, group?.signature],
  );

  // Escape closes the slide-over (parent listens for Escape too — this
  // ensures the inner panel handles it first when the user is focused
  // inside the table or footer). Only attaches while a group is active.
  useEffect(() => {
    if (!group) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !noMatchOpen) {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [group, noMatchOpen, onClose]);

  // Move focus into the slide-over the moment it opens. Without this a
  // keyboard / screen-reader user stays parked on the review table that
  // is now visually behind a backdrop, with no obvious way into the
  // panel — the dialog is effectively invisible to them.
  useEffect(() => {
    if (!group) return;
    closeBtnRef.current?.focus();
  }, [group]);

  // Lightweight focus containment: keep Tab / Shift+Tab inside the
  // slide-over while it is open (and the nested No-match modal isn't
  // capturing). A full focus-trap lib would be overkill for one panel;
  // wrapping focus at the first/last tabbable is enough to stop the
  // keyboard escaping to the obscured page underneath.
  useEffect(() => {
    if (!group || noMatchOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const root = panelRef.current;
      if (!root) return;
      const focusable = root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (!root.contains(active)) {
        e.preventDefault();
        first?.focus();
        return;
      }
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [group, noMatchOpen]);

  if (!group) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
        aria-hidden
      />

      {/* Slide-over */}
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="match-detail-title"
        className="fixed top-0 right-0 bottom-0 w-full sm:w-[680px] bg-white dark:bg-slate-900 z-50 shadow-2xl flex flex-col border-l border-slate-200 dark:border-slate-700"
      >
        <header className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
          <div className="min-w-0 flex-1">
            <div
              id="match-detail-title"
              className="text-sm font-semibold truncate"
              title={group.group_key}
            >
              {group.display_label || group.group_key}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">
              {t('match_elements.detail.elements_count', '{{count}} elements', {
                count: group.element_count,
              })}{' '}
              · {Object.entries(group.quantities).slice(0, 3).map(
                ([k, v]) => `${k}=${fmtFixed(v as number, 1)}`,
              ).join(' · ')}
              {group.opening_warning && (
                <span className="ml-2 inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
                  <AlertCircle className="w-3 h-3" />
                  {t(
                    'match_elements.detail.opening_warning',
                    'host has openings but gross == net (IFC export bug)',
                  )}
                </span>
              )}
            </div>
            {priorPick && (
              <div className="mt-1.5">
                <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200">
                  <Sparkles className="w-3 h-3" />
                  {t('match_elements.detail.prior_pick', {
                    defaultValue: 'You mapped this before ({{count}}x)',
                    count: priorPick.use_count,
                  })}
                  {priorPick.last_used_at && (
                    <span className="opacity-80">
                      {t('match_elements.detail.prior_pick_last', {
                        defaultValue: '· last {{date}}',
                        date: new Date(priorPick.last_used_at).toLocaleDateString(getIntlLocale()),
                      })}
                    </span>
                  )}
                </span>
              </div>
            )}
          </div>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            aria-label={t('match_elements.detail.close', 'Close detail panel')}
            className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </header>

        <nav
          className="px-4 border-b border-slate-200 dark:border-slate-700 flex gap-1"
          role="tablist"
          aria-label={t('match_elements.detail.tabs_label', 'Detail panel sections')}
          onKeyDown={onTabKeyDown}
        >
          {DETAIL_TAB_IDS.map((tabKey) => (
            <button
              key={tabKey}
              type="button"
              role="tab"
              id={`detail-tab-${tabKey}`}
              aria-selected={tab === tabKey}
              aria-controls={`detail-tabpanel-${tabKey}`}
              tabIndex={tab === tabKey ? 0 : -1}
              onClick={() => setTab(tabKey)}
              className={`px-3 py-2 text-sm border-b-2 transition ${
                tab === tabKey
                  ? 'border-indigo-500 text-indigo-600 dark:text-indigo-300'
                  : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
              }`}
            >
              {tabKey === 'methods'
                ? t('match_elements.tab.methods', 'Match candidates')
                : tabKey === 'elements'
                ? t('match_elements.tab.elements', 'Elements ({{count}})', { count: group.element_count })
                : t('match_elements.tab.apply', 'Apply preview')}
            </button>
          ))}
        </nav>

        <div className="flex-1 overflow-auto p-4">
          {detailQ.isLoading && (
            <div className="text-center text-slate-500 py-8">
              <Loader2 className="w-5 h-5 animate-spin inline mr-2" />
              {t('match_elements.loading_detail', 'Loading detail…')}
            </div>
          )}

          {detailQ.isError && !detailQ.isLoading && (
            <div
              className="rounded border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-900/20 px-3 py-3 text-sm text-rose-800 dark:text-rose-100 flex items-start gap-2"
              role="alert"
            >
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="font-semibold">
                  {t('match_elements.detail.error_title', 'Could not load detail')}
                </div>
                <div className="text-xs mt-0.5 break-all opacity-80">
                  {String((detailQ.error as Error | null)?.message ?? detailQ.error ?? '')}
                </div>
                <button
                  type="button"
                  onClick={() => detailQ.refetch()}
                  className="mt-1.5 text-xs underline hover:opacity-80"
                >
                  {t('match_elements.detail.retry', 'Retry')}
                </button>
              </div>
            </div>
          )}

          {/* Tab: methods */}
          {tab === 'methods' && detailQ.data && (
            <div role="tabpanel" id="detail-tabpanel-methods" aria-labelledby="detail-tab-methods">
              {methodNames.length === 0 && (
                <div className="text-center py-12 text-slate-500">
                  <AlertCircle className="w-6 h-6 mx-auto mb-2 opacity-40" />
                  <p className="text-sm">{t('match_elements.detail.no_matchers_run', 'No matchers run yet for this group.')}</p>
                  <p className="text-xs mt-1">{t('match_elements.detail.use_action_bar', 'Use the action bar buttons above.')}</p>
                </div>
              )}
              {methodNames.map((name) => (
                <div key={name} className="mb-6">
                  <h3 className="text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
                    {name}
                  </h3>
                  <table className="w-full text-sm border border-slate-200 dark:border-slate-700 rounded">
                    <thead className="bg-slate-50 dark:bg-slate-800">
                      <tr>
                        <th className="text-left px-2 py-1.5 font-medium">{t('match_elements.detail.col.code', 'Code')}</th>
                        <th className="text-left px-2 py-1.5 font-medium">{t('match_elements.detail.col.description', 'Description')}</th>
                        <th className="text-right px-2 py-1.5 font-medium">{t('match_elements.detail.col.unit_rate', 'Unit · Rate')}</th>
                        <th className="text-right px-2 py-1.5 font-medium">{t('match_elements.detail.col.conf', 'Conf.')}</th>
                        <th className="text-right px-2 py-1.5"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {(methods[name] ?? []).slice(0, 10).map((cand, idx) => {
                        // Why did this candidate rank? Plain-language chips from
                        // its boosts + semantic score, plus a "you picked this
                        // last time" reason when it is the saved template's pick.
                        const isPrior = isPriorPickCandidate(cand.id, priorPick);
                        const reasons = buildMatchReasons(cand);
                        if (isPrior && priorPick) {
                          reasons.unshift(priorConfirmReason(priorPick.use_count));
                        }
                        const note = reasoningText(cand);
                        return (
                        <tr
                          key={`${name}-${cand.code}-${idx}`}
                          className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50"
                        >
                          <td className="px-2 py-1.5 font-mono text-xs align-top">
                            {cand.code}
                            {isPrior && (
                              <span className="mt-1 flex items-center gap-1 text-[10px] font-sans font-medium text-indigo-600 dark:text-indigo-300">
                                <Sparkles className="w-2.5 h-2.5" />
                                {t('match_elements.detail.your_pick', {
                                  defaultValue: 'Your pick last time',
                                })}
                              </span>
                            )}
                          </td>
                          <td className="px-2 py-1.5 text-xs align-top">
                            <div>{cand.description}</div>
                            <ReasonChips reasons={reasons} />
                            {note && (
                              <div className="mt-1 text-[10px] italic text-slate-500 dark:text-slate-400">
                                {t('match_elements.detail.model_note', {
                                  defaultValue: 'Model note: {{note}}',
                                  note,
                                })}
                              </div>
                            )}
                          </td>
                          <td className="px-2 py-1.5 text-right text-xs tabular-nums align-top">
                            {fmtFixed(Number(cand.unit_rate), 2)} {cand.currency}/{cand.unit}
                          </td>
                          <td className="px-2 py-1.5 text-right align-top">
                            <ConfidencePill band={cand.confidence_band} score={cand.score} />
                          </td>
                          <td className="px-2 py-1.5 text-right align-top">
                            <button
                              onClick={() => confirmMut.mutate(cand)}
                              disabled={confirmMut.isPending || !cand.id}
                              title={
                                !cand.id
                                  ? t(
                                      'match_elements.detail.candidate_no_id',
                                      'Candidate has no DB id - cannot confirm',
                                    )
                                  : undefined
                              }
                              className="px-2 py-0.5 text-xs rounded bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50"
                            >
                              {t('match_elements.detail.confirm', 'Confirm')}
                            </button>
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ))}

              {/* Trust signal + feedback on the match result: candidates are
                  ranked from your loaded catalogue, the best score is the honest
                  confidence, and the user can tell us whether the suggestion was
                  right - feeding the same trust loop the agents use. */}
              {methodNames.length > 0 && (
                <AITrustNote
                  surface="match_elements"
                  refId={`${sessionId}:${group.group_key}`}
                  projectId={projectId}
                  confidence={topScore}
                  producedBy={t('match_elements.detail.trust_produced', {
                    defaultValue: 'Candidates ranked from your loaded cost catalogue - confirm before you apply.',
                  })}
                />
              )}
            </div>
          )}

          {/* Tab: elements */}
          {tab === 'elements' && detailQ.data && (
            <div role="tabpanel" id="detail-tabpanel-elements" aria-labelledby="detail-tab-elements">
              {/* Item #18 — deterministic symbol-signature suggestions for
                  this group. The backend resolves the descriptor from the
                  stored group (geometry + properties); a human reviews and
                  confirms via the existing flow. NOT computer vision. */}
              <div className="mb-3">
                <SymbolSuggestionPanel
                  sessionId={sessionId}
                  groupKey={group.group_key}
                />
              </div>
              <p className="text-xs text-slate-500 mb-2">
                {t('match_elements.detail.element_ids_count', '{{count}} element id(s)', { count: detailQ.data.element_ids.length })}
              </p>
              <div className="font-mono text-xs leading-tight max-h-[60vh] overflow-auto bg-slate-50 dark:bg-slate-800 p-2 rounded">
                {detailQ.data.element_ids.slice(0, 200).map((id) => (
                  <div key={id} className="truncate text-slate-600 dark:text-slate-300">{id}</div>
                ))}
                {detailQ.data.element_ids.length > 200 && (
                  <div className="text-slate-500">{t('match_elements.detail.and_more', '…and {{count}} more', { count: detailQ.data.element_ids.length - 200 })}</div>
                )}
              </div>
            </div>
          )}

          {/* Tab: apply preview */}
          {tab === 'apply' && (
            <div role="tabpanel" id="detail-tabpanel-apply" aria-labelledby="detail-tab-apply">
              {applyQ.isLoading && (
                <div className="text-center text-slate-500 py-8">
                  <Loader2 className="w-5 h-5 animate-spin inline mr-2" />
                  {t('match_elements.detail.building_preview', 'Building preview…')}
                </div>
              )}
              {applyQ.data && (
                <div className="mb-3 px-3 py-2 rounded bg-slate-50 dark:bg-slate-800 text-sm flex items-center justify-between">
                  <span className="text-slate-600 dark:text-slate-300">
                    {t('match_elements.detail.apply_total', 'Total')}
                  </span>
                  <strong className="tabular-nums">
                    {fmtFixed(Number(applyQ.data.grand_total), 2)}{' '}
                    {applyQ.data.currency ?? ''}
                  </strong>
                </div>
              )}
              {applyQ.data && applyQ.data.positions.map((p) => (
                <div key={p.group_key} className="mb-4 border border-slate-200 dark:border-slate-700 rounded p-3">
                  <div className="text-xs text-slate-500 mb-1">{p.section_path.join(' → ')}</div>
                  <div className="font-medium text-sm">{p.description}</div>
                  <div className="text-xs text-slate-600 dark:text-slate-300 mt-1">
                    {(() => {
                      const dq = q.convert(Number(p.quantity), p.unit || '');
                      const dr = q.convertRate(Number(p.unit_rate), p.unit || '');
                      return `${fmtFixed(dq.value, 2)} ${p.unit ? dq.unit : ''}`.trim()
                        + ` × ${fmtFixed(dr, 2)} ${p.currency}`;
                    })()}{' '}={' '}
                    <strong className="tabular-nums">{fmtFixed(Number(p.line_total), 2)} {p.currency}</strong>
                  </div>
                  {p.resources.length > 0 && (
                    <div className="mt-2 pl-3 border-l-2 border-slate-200 dark:border-slate-700">
                      <div className="text-xs text-slate-500 mb-1">{t('match_elements.detail.auto_loaded_resources', 'Auto-loaded resources:')}</div>
                      {p.resources.map((r, i) => {
                        const dr = q.convert(Number(r.quantity), r.unit || '');
                        return (
                          <div key={i} className="text-xs flex justify-between text-slate-600 dark:text-slate-300">
                            <span>{r.description} (×{r.factor})</span>
                            <span className="tabular-nums">{`${fmtFixed(dr.value, 2)} ${r.unit ? dr.unit : ''}`.trim()}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
              {applyQ.data && applyQ.data.positions.length === 0 && (
                <div className="text-center text-slate-500 py-8 text-sm">
                  {t('match_elements.detail.confirm_first', 'Confirm a match first to see the BOQ preview.')}
                </div>
              )}
            </div>
          )}
        </div>

        <footer className="px-4 py-3 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
          <button
            onClick={() => setNoMatchOpen(true)}
            className="text-xs text-slate-600 hover:text-rose-600 inline-flex items-center gap-1"
          >
            <XCircle className="w-3.5 h-3.5" />
            {t('match_elements.no_match', 'No match…')}
          </button>
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            {t('match_elements.col.status', 'Status')}: <strong>{t(`match_elements.status.${group.status}`, { defaultValue: group.status })}</strong>
            <ChevronRight className="w-3 h-3" />
            <CheckCircle2 className={`w-4 h-4 ${group.status === 'confirmed' ? 'text-emerald-500' : 'text-slate-300'}`} />
          </div>
        </footer>
      </aside>

      {noMatchOpen && (
        <NoMatchModal
          sessionId={sessionId}
          groupKey={group.group_key}
          onClose={() => setNoMatchOpen(false)}
          onDone={() => {
            setNoMatchOpen(false);
            onClose();
          }}
        />
      )}
    </>
  );
}
