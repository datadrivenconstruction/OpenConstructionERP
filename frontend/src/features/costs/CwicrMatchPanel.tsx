// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Sparkles, CheckCircle2, Loader2 } from 'lucide-react';
import { Badge } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import {
  matchCwicr,
  type CostItemMetadata,
  type CostVariant,
  type CwicrMatchMode,
  type CwicrMatchResult,
} from './api';
import { VariantPicker } from './VariantPicker';

/** Slim view of `CostItemResponse` — just the fields we need to drive
 *  the variant picker. */
interface CostItemDetail {
  id: string;
  unit: string;
  rate: number;
  currency: string;
  metadata: CostItemMetadata;
}

/** Pending variant pick — stored in state so the picker can render once
 *  outside the apply handler and the handler can resolve sequentially. */
interface PendingVariantPick {
  detail: CostItemDetail;
  match: CwicrMatchResult;
  anchorEl: HTMLElement | null;
  resolve: (chosen: CostVariant | null) => void;
}

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
  /** While true, the row's Apply button shows a spinner (we're fetching
   *  the full CostItem to discover whether variants exist). */
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [activeVariantPick, setActiveVariantPick] = useState<PendingVariantPick | null>(null);
  /** Per-row Apply button refs so the picker can anchor next to the click. */
  const applyButtonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

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
    async (match: CwicrMatchResult) => {
      // Fetch the full cost item to discover whether it carries CWICR
      // abstract-resource variants.  One extra GET only when the user
      // actually clicks Apply — negligible.
      setResolvingId(match.cost_item_id);
      let detail: CostItemDetail | null = null;
      try {
        detail = await apiGet<CostItemDetail>(`/v1/costs/${match.cost_item_id}`);
      } catch {
        // Fetch failed — fall back to the original flow so the user
        // doesn't get stuck.  Apply with the matcher's scalar fields.
        detail = null;
      } finally {
        setResolvingId(null);
      }

      const variants = detail?.metadata?.variants;
      const stats = detail?.metadata?.variant_stats;

      // No variants or fetch failed → original behaviour.
      if (!detail || !variants || variants.length < 2 || !stats) {
        onApply(match);
        setAppliedId(match.cost_item_id);
        return;
      }

      // Has variants → run the picker, anchored at the row's Apply
      // button so positioning is stable.
      const anchorEl = applyButtonRefs.current.get(match.cost_item_id) ?? null;
      const chosen = await new Promise<CostVariant | null>((resolve) => {
        setActiveVariantPick({ detail: detail as CostItemDetail, match, anchorEl, resolve });
      });

      // Cancelled — leave the row untouched.
      if (!chosen) return;

      onApply({
        ...match,
        unit_rate: chosen.price,
        applied_variant: {
          label: chosen.label,
          price: chosen.price,
          index: chosen.index,
        },
      });
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
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.375rem' }}>
                    <span>
                      {row.unit_rate.toFixed(2)} {row.currency}
                    </span>
                    {/* Variant badge — backend MatchResult currently doesn't
                        carry variant_count, so this is a no-op until the
                        schema is extended.  Forward-compatible only. */}
                    {(row.variant_count ?? 0) >= 2 && (
                      <Badge variant="blue" size="sm" className="text-2xs">
                        <span
                          title={
                            row.variant_min != null && row.variant_max != null
                              ? `${row.variant_min.toFixed(2)} – ${row.variant_max.toFixed(2)} ${row.currency}`
                              : undefined
                          }
                        >
                          {t('costs.variants_count', {
                            count: row.variant_count ?? 0,
                            defaultValue: '{{count}} variants',
                          })}
                        </span>
                      </Badge>
                    )}
                  </span>
                </td>
                <td title={`source=${row.source}`}>{formatScore(row.score)}</td>
                <td>
                  <button
                    type="button"
                    ref={(el) => {
                      if (el) applyButtonRefs.current.set(row.cost_item_id, el);
                      else applyButtonRefs.current.delete(row.cost_item_id);
                    }}
                    onClick={() => void handleApply(row)}
                    disabled={resolvingId === row.cost_item_id}
                    data-testid={`cwicr-match-apply-${row.code}`}
                  >
                    {resolvingId === row.cost_item_id ? (
                      <Loader2 size={14} aria-hidden className="oe-cwicr-match-panel__spinner" />
                    ) : appliedId === row.cost_item_id ? (
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

      {/* Variant picker — anchored at the row's Apply button. */}
      {activeVariantPick
        && activeVariantPick.detail.metadata?.variants
        && activeVariantPick.detail.metadata?.variant_stats && (
        <VariantPicker
          variants={activeVariantPick.detail.metadata.variants}
          stats={activeVariantPick.detail.metadata.variant_stats}
          anchorEl={activeVariantPick.anchorEl}
          unitLabel={activeVariantPick.detail.unit || ''}
          currency={activeVariantPick.detail.currency || activeVariantPick.match.currency || 'USD'}
          onApply={(chosen) => {
            const pending = activeVariantPick;
            setActiveVariantPick(null);
            pending.resolve(chosen);
          }}
          onClose={() => {
            const pending = activeVariantPick;
            setActiveVariantPick(null);
            pending.resolve(null);
          }}
        />
      )}
    </div>
  );
}
