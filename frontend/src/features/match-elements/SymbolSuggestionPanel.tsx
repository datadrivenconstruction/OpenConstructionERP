// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Item #18 — Symbol-signature suggestion panel.
//
// Shows ranked symbol suggestions for one match group, each with an
// honest confidence chip (0..1) and the contributing factors. The
// recogniser is deterministic and works only on already-structured
// geometry/properties — it is NOT computer vision. Raster CV symbol
// detection from drawing pixels is the separate cv-pipeline service
// (YOLO / PaddleOCR, roadmap Phase 3).
//
// AI/heuristic SUGGESTS; the human confirms. The "Apply (review)"
// affordance NEVER auto-commits — it hands the chosen symbol up to the
// host via onApplyForReview so the existing confirm/no-match flow can
// open with the suggestion pre-filled.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  matchElementsApi,
  type SymbolSuggestion,
  type SymbolSuggestRequest,
} from './api';

interface Props {
  /** Session that owns the referenced group (authorised server-side). */
  sessionId?: string;
  /** Group key whose stored geometry/properties drive the suggestion. */
  groupKey?: string;
  /** Inline descriptor fields, used when no group is referenced (or to
   *  override the resolved group fields). */
  category?: string;
  quantities?: Record<string, number>;
  properties?: Record<string, unknown>;
  /** Review-only apply: the host opens the confirm/no-match flow with the
   *  chosen symbol pre-filled. Nothing is committed here. */
  onApplyForReview?: (suggestion: SymbolSuggestion) => void;
}

function bandClasses(band: SymbolSuggestion['confidence_band']): string {
  if (band === 'high') return 'bg-emerald-500';
  if (band === 'medium') return 'bg-amber-500';
  return 'bg-rose-500';
}

function ConfidenceChip({
  band,
  confidence,
}: {
  band: SymbolSuggestion['confidence_band'];
  confidence: number;
}) {
  return (
    <span
      data-testid="symbol-confidence-chip"
      data-band={band}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium text-white ${bandClasses(
        band,
      )}`}
    >
      {Math.round(confidence * 100)}%
    </span>
  );
}

export function SymbolSuggestionPanel({
  sessionId,
  groupKey,
  category,
  quantities,
  properties,
  onApplyForReview,
}: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<string | null>(null);

  const request: SymbolSuggestRequest = useMemo(
    () => ({
      session_id: sessionId ?? null,
      group_key: groupKey ?? null,
      category: category ?? null,
      quantities: quantities ?? {},
      properties: properties ?? {},
      top_k: 5,
    }),
    [sessionId, groupKey, category, quantities, properties],
  );

  // Only fetch when we have something to fingerprint — either a stored
  // group reference or an inline descriptor with a category/geometry.
  const hasInput =
    (!!sessionId && !!groupKey) ||
    !!category ||
    (quantities && Object.keys(quantities).length > 0);

  const q = useQuery({
    enabled: !!hasInput,
    queryKey: ['symbol-suggest', request],
    queryFn: () => matchElementsApi.suggestSymbols(request),
  });

  return (
    <section
      data-testid="symbol-suggestion-panel"
      className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900"
      aria-label={t('match_elements.symbols.title', {
        defaultValue: 'Symbol suggestions',
      })}
    >
      <header className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {t('match_elements.symbols.title', {
            defaultValue: 'Symbol suggestions',
          })}
        </h3>
      </header>

      {/* Honesty note: deterministic heuristic, not computer vision. */}
      <p
        data-testid="symbol-honesty-note"
        className="mb-3 text-xs leading-snug text-slate-500 dark:text-slate-400"
      >
        {t('match_elements.symbols.note', {
          defaultValue:
            'Deterministic shape-signature heuristic over structured geometry and properties. Raster computer-vision symbol detection is a separate service.',
        })}
      </p>

      {q.isLoading && (
        <p className="text-xs text-slate-500" data-testid="symbol-loading">
          {t('match_elements.symbols.loading', { defaultValue: 'Analysing…' })}
        </p>
      )}

      {q.isError && (
        <p className="text-xs text-rose-600" data-testid="symbol-error">
          {t('match_elements.symbols.error', {
            defaultValue: 'Could not compute symbol suggestions.',
          })}
        </p>
      )}

      {!q.isLoading &&
        !q.isError &&
        (q.data?.suggestions.length ?? 0) === 0 && (
          <p
            className="text-xs text-slate-500"
            data-testid="symbol-empty"
          >
            {t('match_elements.symbols.empty', {
              defaultValue:
                'No symbol could be recognised from the available data.',
            })}
          </p>
        )}

      {!q.isLoading && !q.isError && (q.data?.suggestions.length ?? 0) > 0 && (
        <ul className="space-y-1.5" data-testid="symbol-suggestion-list">
          {q.data!.suggestions.map((s) => {
            const isOpen = expanded === s.symbol;
            return (
              <li
                key={s.symbol}
                data-testid={`symbol-suggestion-${s.symbol}`}
                className="rounded border border-slate-100 p-2 dark:border-slate-800"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400">
                      #{s.rank + 1}
                    </span>
                    <span className="text-sm font-medium capitalize text-slate-800 dark:text-slate-100">
                      {t(`match_elements.symbols.kind.${s.symbol}`, {
                        defaultValue: s.symbol,
                      })}
                    </span>
                    <ConfidenceChip
                      band={s.confidence_band}
                      confidence={s.confidence}
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      data-testid={`symbol-why-${s.symbol}`}
                      className="text-xs text-slate-500 underline-offset-2 hover:underline"
                      onClick={() => setExpanded(isOpen ? null : s.symbol)}
                      aria-expanded={isOpen}
                    >
                      {t('match_elements.symbols.why', {
                        defaultValue: 'Why?',
                      })}
                    </button>
                    {onApplyForReview && (
                      <button
                        type="button"
                        data-testid={`symbol-apply-${s.symbol}`}
                        className="rounded bg-sky-600 px-2 py-1 text-xs font-medium text-white hover:bg-sky-700"
                        onClick={() => onApplyForReview(s)}
                      >
                        {t('match_elements.symbols.apply_review', {
                          defaultValue: 'Apply (review)',
                        })}
                      </button>
                    )}
                  </div>
                </div>

                {isOpen && (
                  <ul
                    data-testid={`symbol-factors-${s.symbol}`}
                    className="mt-2 space-y-1 border-t border-slate-100 pt-2 dark:border-slate-800"
                  >
                    {s.factors.length === 0 && (
                      <li className="text-xs text-slate-400">
                        {t('match_elements.symbols.no_factors', {
                          defaultValue: 'No contributing factors.',
                        })}
                      </li>
                    )}
                    {s.factors.map((f, i) => (
                      <li
                        key={`${s.symbol}-${f.name}-${i}`}
                        className="text-xs text-slate-600 dark:text-slate-300"
                      >
                        <span className="font-mono text-slate-400">
                          {f.name}
                        </span>
                        {f.detail ? ` - ${f.detail}` : ''}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default SymbolSuggestionPanel;
