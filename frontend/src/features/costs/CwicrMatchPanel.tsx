// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useState, useCallback, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Sparkles, CheckCircle2, Loader2 } from 'lucide-react';
import { matchCwicr, type CwicrMatchMode, type CwicrMatchResult } from './api';

/* ── Component ────────────────────────────────────────────────────────── */

export interface CwicrMatchPanelProps {
  /** Pre-fill the search box (e.g. with a BOQ position description). */
  initialQuery?: string;
  /** Optional unit-of-measure hint forwarded to the matcher. */
  unitHint?: string;
  /** Optional language hint (ISO-639-1) forwarded to the matcher. */
  langHint?: string;
  /** Optional region filter forwarded to the matcher. */
  region?: string;
  /** Initial number of results to fetch (default 10). */
  initialTopK?: number;
  /** Called when the user clicks Apply on a row.  Parent owns the side
   *  effect (e.g. patches a BOQ position with the chosen rate / id). */
  onApply: (match: CwicrMatchResult) => void;
  /** Optional override for the default lexical mode toggle starting state. */
  initialMode?: CwicrMatchMode;
  /** Optional className passed to the outer wrapper for layout integration. */
  className?: string;
}

/** Format a 0..1 score as a percent for display. */
function formatScore(score: number): string {
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`;
}

export function CwicrMatchPanel(props: CwicrMatchPanelProps) {
  const {
    initialQuery = '',
    unitHint,
    langHint,
    region,
    initialTopK = 10,
    onApply,
    initialMode = 'lexical',
    className,
  } = props;

  const { t } = useTranslation();
  const [query, setQuery] = useState(initialQuery);
  const [mode, setMode] = useState<CwicrMatchMode>(initialMode);
  const [results, setResults] = useState<CwicrMatchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [appliedId, setAppliedId] = useState<string | null>(null);

  // Reset the "Applied!" check mark when the user retypes.
  useEffect(() => {
    setAppliedId(null);
  }, [query, mode]);

  const trimmed = query.trim();

  const runSearch = useCallback(async () => {
    if (!trimmed) {
      setResults([]);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await matchCwicr({
        query: trimmed,
        unit: unitHint || undefined,
        lang: langHint || undefined,
        region: region || undefined,
        top_k: initialTopK,
        mode,
      });
      setResults(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [trimmed, unitHint, langHint, region, initialTopK, mode]);

  const onSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      void runSearch();
    },
    [runSearch],
  );

  const handleApply = useCallback(
    (match: CwicrMatchResult) => {
      onApply(match);
      setAppliedId(match.cost_item_id);
    },
    [onApply],
  );

  const placeholder = t('costs.cwicr_match.placeholder', {
    defaultValue: 'Describe the work item (e.g. reinforced concrete wall)',
  });

  const titleLabel = t('costs.cwicr_match.title', {
    defaultValue: 'CWICR rate match',
  });

  const modeOptions = useMemo(
    () => [
      { value: 'lexical' as const, label: t('costs.cwicr_match.mode_lexical', { defaultValue: 'Lexical' }) },
      { value: 'semantic' as const, label: t('costs.cwicr_match.mode_semantic', { defaultValue: 'Semantic' }) },
      { value: 'hybrid' as const, label: t('costs.cwicr_match.mode_hybrid', { defaultValue: 'Hybrid' }) },
    ],
    [t],
  );

  return (
    <div
      className={['oe-cwicr-match-panel', className].filter(Boolean).join(' ')}
      data-testid="cwicr-match-panel"
    >
      <header className="oe-cwicr-match-panel__header">
        <Sparkles size={16} aria-hidden />
        <h3 className="oe-cwicr-match-panel__title">{titleLabel}</h3>
      </header>

      <form onSubmit={onSubmit} className="oe-cwicr-match-panel__form">
        <label className="oe-cwicr-match-panel__field">
          <span className="oe-cwicr-match-panel__label">
            {t('costs.cwicr_match.query_label', { defaultValue: 'Query' })}
          </span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            aria-label={titleLabel}
            data-testid="cwicr-match-input"
          />
        </label>

        <label className="oe-cwicr-match-panel__field">
          <span className="oe-cwicr-match-panel__label">
            {t('costs.cwicr_match.mode_label', { defaultValue: 'Mode' })}
          </span>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as CwicrMatchMode)}
            aria-label={t('costs.cwicr_match.mode_label', { defaultValue: 'Mode' })}
            data-testid="cwicr-match-mode"
          >
            {modeOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <button
          type="submit"
          disabled={loading || !trimmed}
          data-testid="cwicr-match-submit"
        >
          {loading ? (
            <Loader2 size={14} className="oe-cwicr-match-panel__spinner" aria-hidden />
          ) : (
            <Search size={14} aria-hidden />
          )}
          {t('costs.cwicr_match.search', { defaultValue: 'Search' })}
        </button>
      </form>

      {error && (
        <div role="alert" className="oe-cwicr-match-panel__error" data-testid="cwicr-match-error">
          {t('costs.cwicr_match.error', {
            defaultValue: 'Match failed: {{message}}',
            message: error,
          })}
        </div>
      )}

      {!error && !loading && trimmed && results.length === 0 && (
        <div className="oe-cwicr-match-panel__empty" data-testid="cwicr-match-empty">
          {t('costs.cwicr_match.empty', {
            defaultValue: 'No matching CWICR items found.',
          })}
        </div>
      )}

      {results.length > 0 && (
        <table className="oe-cwicr-match-panel__table" data-testid="cwicr-match-results">
          <thead>
            <tr>
              <th>{t('costs.cwicr_match.col_code', { defaultValue: 'Code' })}</th>
              <th>{t('costs.cwicr_match.col_description', { defaultValue: 'Description' })}</th>
              <th>{t('costs.cwicr_match.col_unit', { defaultValue: 'Unit' })}</th>
              <th>{t('costs.cwicr_match.col_rate', { defaultValue: 'Rate' })}</th>
              <th>{t('costs.cwicr_match.col_score', { defaultValue: 'Score' })}</th>
              <th aria-label={t('costs.cwicr_match.col_actions', { defaultValue: 'Actions' })} />
            </tr>
          </thead>
          <tbody>
            {results.map((row) => (
              <tr key={row.cost_item_id} data-testid={`cwicr-match-row-${row.code}`}>
                <td>{row.code}</td>
                <td title={row.description}>{row.description}</td>
                <td>{row.unit}</td>
                <td>
                  {row.unit_rate.toFixed(2)} {row.currency}
                </td>
                <td title={`source=${row.source}`}>{formatScore(row.score)}</td>
                <td>
                  <button
                    type="button"
                    onClick={() => handleApply(row)}
                    data-testid={`cwicr-match-apply-${row.code}`}
                  >
                    {appliedId === row.cost_item_id ? (
                      <>
                        <CheckCircle2 size={14} aria-hidden />
                        {t('costs.cwicr_match.applied', { defaultValue: 'Applied' })}
                      </>
                    ) : (
                      t('costs.cwicr_match.apply', { defaultValue: 'Apply' })
                    )}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
