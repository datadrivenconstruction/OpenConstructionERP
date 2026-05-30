/**
 * ProjectionEditor — shared "how to compute the quantity" editor.
 *
 * Option C (binding/projection split): the *binding* (which BIM elements) is
 * owned elsewhere (oe_bim_boq_link); this component edits the *projection*
 * (how to turn those elements into one quantity). It is deliberately
 * presentation-only + controlled so the SAME editor powers both the inline
 * {@link BIMQuantityPicker} and the {@link ModelLinkPanel} — one source of
 * truth for the projection UX (toggle, param chips, autocomplete, live
 * validation + preview).
 *
 * Two modes:
 *   • "simple"  — aggregate one canonical quantity field (sum/max/min/first)
 *                 or count the bound elements.
 *   • "formula" — a per-element expression (e.g. `area_m2 * 2`) evaluated for
 *                 every element then aggregated. `count` is reserved to simple
 *                 mode, so formula aggregations are sum/max/min/first only.
 *
 * Live preview/validation calls the read-only `previewQuantityFormula`
 * endpoint, which reuses the EXACT evaluator "refresh from model" runs, so
 * what the user sees here is what will actually be applied.
 */

import { useCallback, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Loader2, FunctionSquare, Sigma, CheckCircle2, AlertTriangle } from 'lucide-react';
import { previewQuantityFormula } from '@/features/bim/api';
import type { QuantityAggregation } from './api';

export interface ProjectionValue {
  projection_kind: 'simple' | 'formula';
  quantity_field: string;
  aggregation: QuantityAggregation;
  formula: string;
}

const SIMPLE_AGGREGATIONS: QuantityAggregation[] = ['sum', 'max', 'min', 'count', 'first'];
const FORMULA_AGGREGATIONS: QuantityAggregation[] = ['sum', 'max', 'min', 'first'];

export interface ProjectionEditorProps {
  /** Position whose bound elements the preview evaluates against. */
  positionId: string;
  /** Canonical param names available across the bound elements (chips + field). */
  availableParams: string[];
  value: ProjectionValue;
  onChange: (v: ProjectionValue) => void;
  /** Enable the live preview/validation (requires the position to be bound). */
  livePreview?: boolean;
}

export function ProjectionEditor({
  positionId,
  availableParams,
  value,
  onChange,
  livePreview = true,
}: ProjectionEditorProps) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [debouncedFormula, setDebouncedFormula] = useState(value.formula);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isFormula = value.projection_kind === 'formula';

  /* ── Mode toggle ────────────────────────────────────────────────── */
  const setMode = useCallback(
    (kind: 'simple' | 'formula') => {
      if (kind === value.projection_kind) return;
      // `count` is invalid in formula mode — fall back to sum on switch.
      const aggregation =
        kind === 'formula' && value.aggregation === 'count' ? 'sum' : value.aggregation;
      onChange({ ...value, projection_kind: kind, aggregation });
    },
    [onChange, value],
  );

  /* ── Formula edits (debounced into the preview query) ───────────── */
  const setFormula = useCallback(
    (formula: string) => {
      onChange({ ...value, formula });
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => setDebouncedFormula(formula), 350);
    },
    [onChange, value],
  );

  /** Insert a param token at the caret (or replace the selection). */
  const insertParam = useCallback(
    (param: string) => {
      const ta = textareaRef.current;
      const cur = value.formula;
      let next: string;
      if (ta) {
        const start = ta.selectionStart ?? cur.length;
        const end = ta.selectionEnd ?? cur.length;
        next = cur.slice(0, start) + param + cur.slice(end);
        // Restore caret just after the inserted token on next tick.
        requestAnimationFrame(() => {
          ta.focus();
          const pos = start + param.length;
          ta.setSelectionRange(pos, pos);
        });
      } else {
        next = cur + param;
      }
      setFormula(next);
    },
    [setFormula, value.formula],
  );

  /* ── Live preview (formula mode only) ───────────────────────────── */
  const previewEnabled =
    livePreview && isFormula && !!positionId && debouncedFormula.trim().length > 0;

  const { data: preview, isFetching: previewLoading } = useQuery({
    queryKey: ['quantity-formula-preview', positionId, debouncedFormula, value.aggregation],
    queryFn: () =>
      previewQuantityFormula({
        boq_position_id: positionId,
        formula: debouncedFormula,
        aggregation: value.aggregation,
      }),
    enabled: previewEnabled,
    staleTime: 30 * 1000,
    retry: false,
  });

  /* ── Autocomplete: params matching the token under the caret ────── */
  const [suggestOpen, setSuggestOpen] = useState(false);
  const currentToken = useMemo(() => {
    const ta = textareaRef.current;
    if (!ta) return '';
    const upto = value.formula.slice(0, ta.selectionStart ?? value.formula.length);
    const m = upto.match(/[A-Za-z_][A-Za-z0-9_]*$/);
    return m ? m[0] : '';
  }, [value.formula]);

  const suggestions = useMemo(() => {
    if (!currentToken) return [];
    const tok = currentToken.toLowerCase();
    return availableParams
      .filter((p) => p.toLowerCase().includes(tok) && p.toLowerCase() !== tok)
      .slice(0, 6);
  }, [availableParams, currentToken]);

  /** Replace the token under the caret with the chosen param. */
  const applySuggestion = useCallback(
    (param: string) => {
      const ta = textareaRef.current;
      const cur = value.formula;
      if (!ta) {
        setFormula(cur + param);
        return;
      }
      const caret = ta.selectionStart ?? cur.length;
      const before = cur.slice(0, caret).replace(/[A-Za-z_][A-Za-z0-9_]*$/, '');
      const after = cur.slice(caret);
      const next = before + param + after;
      requestAnimationFrame(() => {
        ta.focus();
        const pos = before.length + param.length;
        ta.setSelectionRange(pos, pos);
      });
      setFormula(next);
      setSuggestOpen(false);
    },
    [setFormula, value.formula],
  );

  const aggregations = isFormula ? FORMULA_AGGREGATIONS : SIMPLE_AGGREGATIONS;

  return (
    <div className="space-y-3">
      {/* Mode toggle */}
      <div className="inline-flex rounded-lg border border-border-light overflow-hidden">
        <button
          type="button"
          onClick={() => setMode('simple')}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors ${
            !isFormula
              ? 'bg-oe-blue/10 text-oe-blue'
              : 'bg-surface-primary text-content-tertiary hover:bg-surface-secondary/60'
          }`}
        >
          <Sigma size={13} />
          {t('boq.projection_mode_simple', { defaultValue: 'Value' })}
        </button>
        <button
          type="button"
          onClick={() => setMode('formula')}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors border-l border-border-light ${
            isFormula
              ? 'bg-oe-blue/10 text-oe-blue'
              : 'bg-surface-primary text-content-tertiary hover:bg-surface-secondary/60'
          }`}
        >
          <FunctionSquare size={13} />
          {t('boq.projection_mode_formula', { defaultValue: 'Formula' })}
        </button>
      </div>

      {/* Aggregation (shared by both modes) */}
      <label className="block">
        <span className="block text-2xs font-medium text-content-secondary mb-1">
          {t('boq.model_link_aggregation', { defaultValue: 'Aggregation' })}
        </span>
        <select
          value={value.aggregation}
          onChange={(e) => onChange({ ...value, aggregation: e.target.value as QuantityAggregation })}
          className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
        >
          {aggregations.map((a) => (
            <option key={a} value={a}>
              {t(`boq.model_link_agg_${a}`, { defaultValue: a })}
            </option>
          ))}
        </select>
      </label>

      {/* Simple mode — pick a quantity field */}
      {!isFormula && value.aggregation !== 'count' && (
        <label className="block">
          <span className="block text-2xs font-medium text-content-secondary mb-1">
            {t('boq.model_link_quantity_field', { defaultValue: 'Quantity field' })}
          </span>
          <select
            value={value.quantity_field}
            onChange={(e) => onChange({ ...value, quantity_field: e.target.value })}
            className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            <option value="">
              {t('boq.model_link_pick_field', { defaultValue: '— Select a quantity —' })}
            </option>
            {availableParams.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
      )}

      {/* Formula mode — expression editor */}
      {isFormula && (
        <div className="space-y-2">
          <span className="block text-2xs font-medium text-content-secondary">
            {t('boq.projection_formula_label', {
              defaultValue: 'Per-element formula (evaluated for each element, then aggregated)',
            })}
          </span>

          {/* Clickable param chips */}
          {availableParams.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {availableParams.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => insertParam(p)}
                  title={t('boq.projection_insert_param', { defaultValue: 'Insert into formula' })}
                  className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-200 dark:hover:bg-emerald-900/50 transition-colors"
                >
                  {p}
                </button>
              ))}
            </div>
          )}

          {/* Textarea + autocomplete */}
          <div className="relative">
            <textarea
              ref={textareaRef}
              value={value.formula}
              onChange={(e) => {
                setFormula(e.target.value);
                setSuggestOpen(true);
              }}
              onKeyUp={() => setSuggestOpen(true)}
              onBlur={() => setTimeout(() => setSuggestOpen(false), 150)}
              rows={2}
              spellCheck={false}
              placeholder={t('boq.projection_formula_placeholder', {
                defaultValue: 'e.g. area_m2 * 2',
              })}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm font-mono text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
            {suggestOpen && suggestions.length > 0 && (
              <ul className="absolute z-50 mt-0.5 w-48 max-h-40 overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-lg">
                {suggestions.map((s) => (
                  <li key={s}>
                    <button
                      type="button"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        applySuggestion(s);
                      }}
                      className="w-full text-left px-3 py-1 text-xs font-mono text-content-secondary hover:bg-oe-blue/10 hover:text-oe-blue"
                    >
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Live validation + preview */}
          {previewEnabled && (
            <div className="rounded-lg border border-border-light bg-surface-secondary/30 px-3 py-2 text-xs">
              {previewLoading ? (
                <span className="flex items-center gap-1.5 text-content-tertiary">
                  <Loader2 size={12} className="animate-spin" />
                  {t('boq.projection_preview_loading', { defaultValue: 'Evaluating…' })}
                </span>
              ) : preview ? (
                <FormulaPreview preview={preview} t={t} />
              ) : null}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Preview readout ──────────────────────────────────────────────── */

function FormulaPreview({
  preview,
  t,
}: {
  preview: import('@/features/bim/api').QuantityFormulaPreviewResponse;
  t: ReturnType<typeof useTranslation>['t'];
}) {
  if (!preview.valid) {
    return (
      <span className="flex items-center gap-1.5 text-semantic-error">
        <AlertTriangle size={12} className="shrink-0" />
        {preview.error
          ? t('boq.projection_invalid_reason', {
              defaultValue: 'Invalid formula: {{reason}}',
              reason: preview.error,
            } as Record<string, unknown>)
          : t('boq.projection_invalid', { defaultValue: 'Invalid formula' })}
      </span>
    );
  }
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 font-medium">
        <CheckCircle2 size={12} className="shrink-0" />
        <span className="tabular-nums">
          {preview.total ?? '0'}
          <span className="text-content-tertiary font-normal ml-1">
            ({preview.aggregation})
          </span>
        </span>
      </div>
      <p className="text-2xs text-content-tertiary">
        {t('boq.projection_preview_counts', {
          defaultValue: '{{ok}} of {{total}} element(s) contribute',
          ok: preview.contributing_count,
          total: preview.link_count,
        } as Record<string, unknown>)}
        {preview.missing_count > 0
          ? ` · ${t('boq.projection_preview_missing', {
              defaultValue: '{{n}} skipped (missing params)',
              n: preview.missing_count,
            } as Record<string, unknown>)}`
          : ''}
      </p>
      {preview.referenced_params.length > 0 && (
        <p className="text-2xs text-content-quaternary font-mono truncate">
          {preview.referenced_params.join(', ')}
        </p>
      )}
    </div>
  );
}
