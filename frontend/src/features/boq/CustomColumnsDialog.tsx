/**
 * CustomColumnsDialog — Manage user-defined columns in a BOQ.
 *
 * Lets the user add/remove arbitrary columns (text, number, date, select)
 * that show up in the BOQ grid alongside the standard ones. Useful for
 * supplier names, internal notes, procurement-related fields, etc.
 *
 * Backend stores the column definitions in `boq.metadata_.custom_columns`,
 * and per-position values in `position.metadata_.custom_fields`. Values
 * are preserved when a column is deleted (only the definition is removed).
 *
 * Design choices:
 *
 * - **Presets**: real users don't think "I need a Supplier column" — they
 *   think "I need procurement tracking". One-click presets create groups of
 *   related columns (Procurement, Quality, Sustainability, Notes).
 *
 * - **Fill rate**: each existing column shows "X of Y positions filled" so
 *   the user can spot empty/dead columns at a glance.
 *
 * - **Reserved-name guard**: same list as backend prevents the user from
 *   shadowing built-in fields like `unit`, `quantity`, etc.
 *
 * - **Type-aware editor**: select columns require options up-front; the
 *   form hides irrelevant inputs.
 */

import { useMemo, useState, useCallback, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  X, Plus, Trash2, Columns3,
  Type, Hash, Calendar, List, Sigma,
  AlertCircle, Check, ChevronDown, Globe, PlayCircle,
} from 'lucide-react';
import { Button, Badge, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { boqApi, type CustomColumnDef, type Position, type BOQVariable } from './api';
import { getErrorMessage } from '@/shared/lib/api';
import {
  type ColumnPreset,
  getUniversalPresets,
  getRegionalPresets,
} from './presets';
import {
  buildFormulaContext,
  evaluateFormulaRaw,
  isFormula,
  normaliseFormula,
  type FormulaVariable,
} from './grid/formula';

interface CustomColumnsDialogProps {
  open: boolean;
  onClose: () => void;
  boqId: string;
  /** Positions used to compute fill-rate stats per column. Optional — if not
   *  provided, fill rates are not shown. */
  positions?: Position[];
  /** BOQ variables — used by the calculated-column "Test" button to preview
   *  formulas with the same context the grid will see at runtime. */
  variables?: BOQVariable[];
}

const COLUMN_TYPE_ICONS: Record<CustomColumnDef['column_type'], typeof Type> = {
  text: Type,
  number: Hash,
  date: Calendar,
  select: List,
  calculated: Sigma,
};

/** Quick-insert formula presets surfaced as chips below the textarea. */
const FORMULA_PRESETS: { label: string; snippet: string; hint: string }[] = [
  { label: '× 1.19 (VAT)', snippet: '=$QUANTITY * $UNIT_RATE * 1.19', hint: 'Total with German VAT' },
  { label: 'qty × rate', snippet: '=$QUANTITY * $UNIT_RATE', hint: 'Net total' },
  { label: 'pos ref', snippet: '=pos("01.001").qty', hint: 'Pull qty from another row' },
  { label: 'if branch', snippet: '=if($QUANTITY > 100, $UNIT_RATE * 0.95, $UNIT_RATE)', hint: 'Volume discount' },
  { label: '$VAR', snippet: '=$QUANTITY * $LABOR_RATE', hint: 'Use a BOQ variable' },
  { label: 'round', snippet: '=round($QUANTITY * $UNIT_RATE, 2)', hint: 'Round to 2 decimals' },
];

/* ── Helpers ───────────────────────────────────────────────────────────── */

const RESERVED_NAMES = new Set([
  'ordinal', 'description', 'unit', 'quantity', 'unit_rate',
  'total', 'id', 'parent_id', 'classification', 'sort_order',
  'metadata', 'created_at', 'updated_at',
]);

function normalizeColumnName(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/\s+/g, '_')
    // Strip only characters that aren't Unicode letters/digits or
    // underscore. \p{L}=any letter (Cyrillic, CJK, Arabic, etc.),
    // \p{N}=any digit. Mirrors Python's str.isidentifier() so the
    // frontend and backend agree on what's a valid key.
    .replace(/[^\p{L}\p{N}_]/gu, '');
}

/** Count how many positions have a non-empty value for a given column name. */
function fillRateFor(positions: Position[] | undefined, columnName: string): { filled: number; total: number } {
  if (!positions || positions.length === 0) return { filled: 0, total: 0 };
  // Skip section rows when computing fill rate — sections never carry custom values.
  const dataRows = positions.filter((p) => p.unit !== '');
  let filled = 0;
  for (const p of dataRows) {
    const meta = (p.metadata as Record<string, unknown> | undefined) ?? {};
    const cf = (meta.custom_fields as Record<string, unknown> | undefined) ?? {};
    const v = cf[columnName];
    if (v != null && v !== '') filled++;
  }
  return { filled, total: dataRows.length };
}

/* ── Component ────────────────────────────────────────────────────────── */

export function CustomColumnsDialog({
  open,
  onClose,
  boqId,
  positions,
  variables,
}: CustomColumnsDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  // ── State for the manual "Add column" form ───────────────────────────
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<CustomColumnDef['column_type']>('text');
  const [newOptions, setNewOptions] = useState('');
  // v2.7.0/E — calculated-column-only state.
  const [newFormula, setNewFormula] = useState('');
  const [newDecimals, setNewDecimals] = useState(2);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [showCustomForm, setShowCustomForm] = useState(false);

  /** Live syntax validation for the formula textarea. We accept anything
   *  `isFormula` recognises and only flag it red when `normaliseFormula`
   *  throws (mismatched quotes, etc) — actual evaluation errors surface
   *  via the Test button. */
  const formulaError = useMemo(() => {
    if (newType !== 'calculated') return null;
    const v = newFormula.trim();
    if (!v) return null;
    if (!isFormula(v)) return 'Must start with `=` or contain a math operator / function.';
    try {
      normaliseFormula(v.startsWith('=') ? v.slice(1) : v);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : 'Invalid formula syntax.';
    }
  }, [newType, newFormula]);

  /** Run the user's formula against the first non-section position so they
   *  can see the result before saving. Mirrors the runtime path in
   *  `getCustomColumnDefs` / `makeCalculatedValueGetter`. */
  const handleTestFormula = useCallback(() => {
    setTestResult(null);
    const formula = newFormula.trim();
    if (!formula) return;
    const sample = (positions ?? []).find((p) => p.unit !== '');
    if (!sample) {
      setTestResult('No position to test against.');
      return;
    }
    const varMap = new Map<string, FormulaVariable>();
    if (variables) {
      for (const v of variables) {
        varMap.set(v.name.toUpperCase(), { type: v.type, value: v.value });
      }
    }
    // Same shape the runtime uses — quantity / unit_rate / total exposed
    // both via `col(...)` (currentRow) and as $-variables.
    const sampleRow = sample as unknown as Record<string, unknown>;
    if (typeof sample.quantity === 'number') varMap.set('QUANTITY', { type: 'number', value: sample.quantity });
    if (typeof sample.unit_rate === 'number') varMap.set('UNIT_RATE', { type: 'number', value: sample.unit_rate });
    if (typeof sample.total === 'number') varMap.set('TOTAL', { type: 'number', value: sample.total });
    const ctx = buildFormulaContext({
      positions: positions ?? [],
      variables: varMap,
      currentPositionId: sample.id,
      currentRow: sampleRow,
    });
    try {
      const r = evaluateFormulaRaw(formula, ctx);
      if (r === null) setTestResult('(empty)');
      else if (typeof r === 'number') setTestResult(r.toFixed(Math.max(0, Math.min(6, newDecimals))));
      else setTestResult(String(r));
    } catch (e) {
      setTestResult(`#ERR: ${e instanceof Error ? e.message : 'unknown'}`);
    }
  }, [newFormula, newDecimals, positions, variables]);

  const { data: columns = [], isLoading } = useQuery({
    queryKey: ['boq-custom-columns', boqId],
    queryFn: () => boqApi.listCustomColumns(boqId),
    enabled: open,
  });

  const existingNames = useMemo(() => new Set(columns.map((c) => c.name)), [columns]);

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['boq-custom-columns', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq-with-positions', boqId] });
  }, [queryClient, boqId]);

  const addMut = useMutation({
    mutationFn: (data: CustomColumnDef) => boqApi.addCustomColumn(boqId, data),
    onSuccess: () => {
      invalidateAll();
      setNewName('');
      setNewType('text');
      setNewOptions('');
      setNewFormula('');
      setNewDecimals(2);
      setTestResult(null);
      setShowCustomForm(false);
      addToast({
        type: 'success',
        title: t('boq.column_added', { defaultValue: 'Column added' }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.column_add_failed', { defaultValue: 'Could not add column' }),
        message: getErrorMessage(err),
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (columnName: string) => boqApi.deleteCustomColumn(boqId, columnName),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('boq.column_removed', { defaultValue: 'Column removed' }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.column_delete_failed', { defaultValue: 'Could not remove column' }),
        message: getErrorMessage(err),
      });
    },
  });

  /* Apply a preset: add each column that doesn't already exist. We do this
   * sequentially to give the backend's per-call uniqueness check a chance
   * to flag any race condition (and to keep error toasts attributable). */
  const applyPreset = useCallback(
    async (preset: ColumnPreset) => {
      const toAdd = preset.columns.filter((c) => !existingNames.has(c.name));
      if (toAdd.length === 0) {
        addToast({
          type: 'info',
          title: t('boq.preset_already_applied', {
            defaultValue: 'All columns from this preset already exist',
          }),
        });
        return;
      }
      let added = 0;
      for (const col of toAdd) {
        try {
          await boqApi.addCustomColumn(boqId, col);
          added++;
        } catch (err) {
          addToast({
            type: 'error',
            title: t('boq.preset_partial', {
              defaultValue: 'Preset partially applied',
            }),
            message: getErrorMessage(err),
          });
          break;
        }
      }
      if (added > 0) {
        invalidateAll();
        addToast({
          type: 'success',
          title: t('boq.preset_applied', {
            defaultValue: '{{count}} columns added from "{{name}}" preset',
            count: added,
            name: preset.name,
          }),
        });
      }
    },
    [boqId, existingNames, invalidateAll, addToast, t],
  );

  /* Render one preset card. Used by both Universal and Regional sections so
   * the card markup stays consistent and the diff between the two sections
   * is just the wrapper. */
  const renderPresetCard = useCallback(
    (preset: ColumnPreset) => {
      const Icon = preset.icon;
      const allApplied = preset.columns.every((c) => existingNames.has(c.name));
      const someApplied = preset.columns.some((c) => existingNames.has(c.name));
      return (
        <button
          key={preset.id}
          onClick={() => applyPreset(preset)}
          disabled={allApplied || addMut.isPending}
          className="flex items-start gap-3 rounded-lg border border-border-light bg-surface-primary p-3 text-left transition-all hover:border-oe-blue/40 hover:bg-oe-blue-subtle/30 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <div
            className={`flex h-9 w-9 items-center justify-center rounded-lg shrink-0 ${preset.iconClass}`}
          >
            <Icon size={16} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-content-primary">{preset.name}</p>
              {allApplied && (
                <span className="inline-flex items-center gap-0.5 text-2xs font-medium text-emerald-600">
                  <Check size={11} />
                  {t('boq.applied', { defaultValue: 'Applied' })}
                </span>
              )}
              {someApplied && !allApplied && (
                <span className="text-2xs font-medium text-amber-600">
                  {t('boq.partial', { defaultValue: 'Partial' })}
                </span>
              )}
            </div>
            <p className="text-2xs text-content-tertiary mt-0.5 line-clamp-2">
              {preset.description}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {preset.columns.map((c) => (
                <span
                  key={c.name}
                  className={`inline-block rounded px-1.5 py-0.5 text-2xs ${existingNames.has(c.name) ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : 'bg-surface-secondary text-content-secondary'}`}
                >
                  {c.display_name}
                </span>
              ))}
            </div>
          </div>
        </button>
      );
    },
    [existingNames, applyPreset, addMut.isPending, t],
  );

  /* Manual add form submit */
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = newName.trim();
    if (!trimmed) return;

    const normalizedName = normalizeColumnName(trimmed);
    if (!normalizedName || /^\p{N}/u.test(normalizedName)) {
      addToast({
        type: 'error',
        title: t('boq.column_name_invalid', { defaultValue: 'Column name is invalid' }),
        message: t('boq.column_name_invalid_hint', {
          defaultValue: 'Use letters (any script), numbers and spaces. Must start with a letter.',
        }),
      });
      return;
    }
    if (RESERVED_NAMES.has(normalizedName)) {
      addToast({
        type: 'error',
        title: t('boq.column_name_reserved', {
          defaultValue: '"{{name}}" is a reserved column name',
          name: normalizedName,
        }),
      });
      return;
    }
    if (existingNames.has(normalizedName)) {
      addToast({
        type: 'error',
        title: t('boq.column_name_duplicate', {
          defaultValue: 'A column named "{{name}}" already exists',
          name: normalizedName,
        }),
      });
      return;
    }

    const payload: CustomColumnDef = {
      name: normalizedName,
      display_name: trimmed,
      column_type: newType,
    };
    if (newType === 'select') {
      const opts = newOptions
        .split(/[,\n]/)
        .map((o) => o.trim())
        .filter(Boolean);
      if (opts.length === 0) {
        addToast({
          type: 'error',
          title: t('boq.column_select_needs_options', {
            defaultValue: 'Select column needs at least one option',
          }),
        });
        return;
      }
      payload.options = opts;
    } else if (newType === 'calculated') {
      const formula = newFormula.trim();
      if (!formula) {
        addToast({
          type: 'error',
          title: t('boq.column_calc_needs_formula', {
            defaultValue: 'Calculated column needs a formula',
          }),
        });
        return;
      }
      if (formulaError) {
        addToast({
          type: 'error',
          title: t('boq.column_calc_invalid_formula', {
            defaultValue: 'Formula has a syntax error',
          }),
          message: formulaError,
        });
        return;
      }
      payload.formula = formula;
      payload.decimals = Math.max(0, Math.min(6, newDecimals));
    }
    addMut.mutate(payload);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="relative w-full max-w-3xl mx-4 max-h-[90vh] rounded-2xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 shrink-0 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle">
              <Columns3 size={20} className="text-oe-blue" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-content-primary">
                {t('boq.custom_columns', { defaultValue: 'Custom Columns' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('boq.custom_columns_subtitle', {
                  defaultValue: 'Add your own fields — supplier, notes, procurement info…',
                })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto px-6 py-5 flex-1 space-y-6">
          {/* ── Existing columns ─────────────────────────────────────── */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('boq.existing_columns', { defaultValue: 'Existing custom columns' })}
              </h3>
              {columns.length > 0 && (
                <span className="text-2xs text-content-tertiary tabular-nums">
                  {columns.length} {t('boq.columns_count', { defaultValue: 'columns' })}
                </span>
              )}
            </div>
            {isLoading ? (
              <p className="text-sm text-content-tertiary py-3">
                {t('common.loading', { defaultValue: 'Loading…' })}
              </p>
            ) : columns.length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg border border-dashed border-border-light px-4 py-5 text-sm text-content-tertiary">
                <AlertCircle size={16} />
                {t('boq.no_custom_columns', {
                  defaultValue: 'No custom columns yet. Pick a preset below or add your own.',
                })}
              </div>
            ) : (
              <div className="rounded-lg border border-border-light divide-y divide-border-light">
                {columns.map((col) => {
                  const Icon = COLUMN_TYPE_ICONS[col.column_type] ?? Type;
                  // Calculated columns aren't stored per-position — fill rate
                  // is meaningless. Suppress the bar.
                  const fr =
                    col.column_type === 'calculated'
                      ? { filled: 0, total: 0 }
                      : fillRateFor(positions, col.name);
                  const fillPct = fr.total > 0 ? Math.round((fr.filled / fr.total) * 100) : 0;
                  return (
                    <div
                      key={col.name}
                      className="flex items-center gap-3 px-4 py-3 hover:bg-surface-secondary/50 transition-colors"
                    >
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-surface-secondary text-content-tertiary shrink-0">
                        <Icon size={15} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-content-primary truncate">
                            {col.display_name}
                          </p>
                          <Badge variant="neutral" size="sm">
                            {col.column_type}
                          </Badge>
                          {col.column_type === 'select' && col.options && col.options.length > 0 && (
                            <span className="text-2xs text-content-tertiary">
                              {col.options.length} {t('boq.options', { defaultValue: 'options' })}
                            </span>
                          )}
                        </div>
                        {col.column_type === 'calculated' && col.formula && (
                          <div className="mt-0.5">
                            <code className="font-mono text-2xs text-content-secondary truncate block">
                              {col.formula}
                            </code>
                          </div>
                        )}
                        <div className="mt-0.5 flex items-center gap-2 text-2xs text-content-tertiary">
                          <code className="font-mono">{col.name}</code>
                          {fr.total > 0 && (
                            <>
                              <span>·</span>
                              <span className="tabular-nums">
                                {fr.filled}/{fr.total} {t('boq.filled', { defaultValue: 'filled' })}
                              </span>
                              <div className="h-1 w-16 rounded-full bg-surface-secondary overflow-hidden">
                                <div
                                  className={`h-full ${fillPct >= 50 ? 'bg-emerald-500' : fillPct >= 10 ? 'bg-amber-500' : 'bg-content-quaternary'}`}
                                  style={{ width: `${fillPct}%` }}
                                />
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                      <button
                        onClick={async () => {
                          const ok = await confirm({
                            title: t('boq.column_delete_confirm_title', { defaultValue: 'Remove column?' }),
                            message: t('boq.column_delete_confirm', {
                              defaultValue:
                                'Remove the "{{name}}" column? Existing values in positions are preserved but no longer shown.',
                              name: col.display_name,
                            }),
                          });
                          if (ok) deleteMut.mutate(col.name);
                        }}
                        disabled={deleteMut.isPending}
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-colors shrink-0"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* ── Presets ─────────────────────────────────────────────── */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('boq.preset_universal', { defaultValue: 'Quick start with a preset' })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {getUniversalPresets().map((preset) => renderPresetCard(preset))}
            </div>

            <details className="group mt-4 rounded-xl border border-border-light bg-surface-secondary/30">
              <summary className="flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-content-secondary hover:text-content-primary">
                <span className="flex items-center gap-2">
                  <Globe size={14} className="text-content-tertiary" />
                  {t('boq.preset_regional', { defaultValue: 'Regional standards' })}
                  <span className="rounded-full bg-surface-primary px-1.5 py-0.5 text-2xs font-medium text-content-tertiary">
                    {getRegionalPresets().length}
                  </span>
                </span>
                <ChevronDown
                  size={14}
                  className="text-content-tertiary transition-transform group-open:rotate-180"
                />
              </summary>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 p-3 pt-0">
                {getRegionalPresets().map((preset) => renderPresetCard(preset))}
              </div>
            </details>
          </section>

          {/* ── Manual add ──────────────────────────────────────────── */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('boq.add_custom_column', { defaultValue: 'Or add a custom one' })}
              </h3>
              {!showCustomForm && (
                <button
                  type="button"
                  onClick={() => setShowCustomForm(true)}
                  className="text-xs font-medium text-oe-blue hover:underline"
                >
                  {t('boq.show_form', { defaultValue: 'Show form' })}
                </button>
              )}
            </div>
            {showCustomForm && (
              <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-4">
                <form onSubmit={handleSubmit} className="space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label
                        htmlFor="column-name"
                        className="block text-xs font-medium text-content-secondary mb-1.5"
                      >
                        {t('boq.column_name', { defaultValue: 'Column name' })}
                      </label>
                      <input
                        id="column-name"
                        type="text"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder={t('boq.column_name_placeholder', {
                          defaultValue: 'e.g. Supplier, Notes, PO Number',
                        })}
                        className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all"
                        autoFocus
                      />
                      {newName && (
                        <p className="mt-1 text-2xs text-content-tertiary">
                          {t('boq.internal_name', { defaultValue: 'Internal name' })}:{' '}
                          <code className="font-mono">{normalizeColumnName(newName)}</code>
                        </p>
                      )}
                    </div>
                    <div>
                      <span
                        id="column-type-label"
                        className="block text-xs font-medium text-content-secondary mb-1.5"
                      >
                        {t('boq.column_type', { defaultValue: 'Type' })}
                      </span>
                      <div
                        role="radiogroup"
                        aria-labelledby="column-type-label"
                        className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-surface-primary p-1"
                      >
                        {(['text', 'number', 'calculated'] as const).map((tp) => {
                          const Icon = COLUMN_TYPE_ICONS[tp];
                          const active = newType === tp;
                          const labels: Record<typeof tp, string> = {
                            text: t('boq.column_type_text', { defaultValue: 'Text' }),
                            number: t('boq.column_type_number', { defaultValue: 'Number' }),
                            calculated: t('boq.column_type_calculated', { defaultValue: 'Calculated' }),
                          };
                          return (
                            <button
                              key={tp}
                              type="button"
                              role="radio"
                              aria-checked={active}
                              onClick={() => setNewType(tp)}
                              className={`flex h-7 items-center justify-center gap-1 rounded text-2xs font-medium transition-colors ${
                                active
                                  ? 'bg-oe-blue text-white shadow-sm'
                                  : 'text-content-secondary hover:bg-surface-secondary'
                              }`}
                            >
                              <Icon size={12} />
                              {labels[tp]}
                            </button>
                          );
                        })}
                      </div>
                      {/* Date / Select still reachable for power users via a
                          secondary control — kept off the primary radio so
                          the new "Calculated" option stays prominent. */}
                      <div className="mt-1 flex gap-2 text-2xs">
                        <button
                          type="button"
                          onClick={() => setNewType('date')}
                          className={`underline-offset-2 hover:underline ${newType === 'date' ? 'text-oe-blue' : 'text-content-tertiary'}`}
                        >
                          {t('boq.column_type_date', { defaultValue: 'Date' })}
                        </button>
                        <span className="text-content-tertiary">·</span>
                        <button
                          type="button"
                          onClick={() => setNewType('select')}
                          className={`underline-offset-2 hover:underline ${newType === 'select' ? 'text-oe-blue' : 'text-content-tertiary'}`}
                        >
                          {t('boq.column_type_select', { defaultValue: 'Select' })}
                        </button>
                      </div>
                    </div>
                  </div>

                  {newType === 'select' && (
                    <div>
                      <label
                        htmlFor="column-options"
                        className="block text-xs font-medium text-content-secondary mb-1.5"
                      >
                        {t('boq.column_options', { defaultValue: 'Options (comma or newline separated)' })}
                      </label>
                      <textarea
                        id="column-options"
                        value={newOptions}
                        onChange={(e) => setNewOptions(e.target.value)}
                        placeholder="Approved, Pending, Rejected"
                        rows={2}
                        className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all resize-none"
                      />
                    </div>
                  )}

                  {newType === 'calculated' && (
                    <div className="space-y-2">
                      <div>
                        <label
                          htmlFor="column-formula"
                          className="block text-xs font-medium text-content-secondary mb-1.5"
                        >
                          {t('boq.column_formula', { defaultValue: 'Formula' })}
                        </label>
                        <textarea
                          id="column-formula"
                          value={newFormula}
                          onChange={(e) => {
                            setNewFormula(e.target.value);
                            setTestResult(null);
                          }}
                          placeholder="=quantity * unit_rate * 1.19"
                          rows={3}
                          spellCheck={false}
                          className={`w-full rounded-lg border bg-surface-primary px-3 py-2 font-mono text-xs text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 transition-all resize-none ${
                            formulaError
                              ? 'border-semantic-error focus:ring-semantic-error/30 focus:border-semantic-error'
                              : 'border-border focus:ring-oe-blue/30 focus:border-oe-blue'
                          }`}
                        />
                        {formulaError && (
                          <p className="mt-1 text-2xs text-semantic-error">{formulaError}</p>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {FORMULA_PRESETS.map((p) => (
                          <button
                            key={p.label}
                            type="button"
                            title={p.hint}
                            onClick={() => {
                              setNewFormula(p.snippet);
                              setTestResult(null);
                            }}
                            className="rounded-full border border-border-light bg-surface-primary px-2 py-0.5 text-2xs font-mono text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue transition-colors"
                          >
                            {p.label}
                          </button>
                        ))}
                      </div>
                      <div className="flex items-end gap-3">
                        <div>
                          <label
                            htmlFor="column-decimals"
                            className="block text-xs font-medium text-content-secondary mb-1.5"
                          >
                            {t('boq.column_decimals', { defaultValue: 'Decimals' })}
                          </label>
                          <input
                            id="column-decimals"
                            type="number"
                            min={0}
                            max={6}
                            value={newDecimals}
                            onChange={(e) => {
                              const n = parseInt(e.target.value, 10);
                              setNewDecimals(isNaN(n) ? 2 : Math.max(0, Math.min(6, n)));
                            }}
                            className="h-9 w-20 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all"
                          />
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={handleTestFormula}
                          disabled={!newFormula.trim() || !!formulaError}
                        >
                          <PlayCircle size={14} className="mr-1.5" />
                          {t('boq.column_test_formula', { defaultValue: 'Test' })}
                        </Button>
                        {testResult !== null && (
                          <div className="flex-1 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 font-mono text-xs">
                            <span className="text-content-tertiary">
                              {t('boq.column_test_result', { defaultValue: 'Result:' })}{' '}
                            </span>
                            <span className="text-content-primary">{testResult}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="flex justify-end gap-2 pt-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setShowCustomForm(false);
                        setNewName('');
                        setNewOptions('');
                        setNewFormula('');
                        setNewDecimals(2);
                        setTestResult(null);
                      }}
                    >
                      {t('common.cancel', { defaultValue: 'Cancel' })}
                    </Button>
                    <Button
                      type="submit"
                      variant="primary"
                      size="sm"
                      disabled={!newName.trim() || addMut.isPending}
                    >
                      <Plus size={14} className="mr-1.5" />
                      {t('boq.add_column_btn', { defaultValue: 'Add column' })}
                    </Button>
                  </div>
                </form>
              </div>
            )}
          </section>
        </div>

        {/* Footer */}
        <div className="border-t border-border-light px-6 py-3 shrink-0">
          <p className="text-xs text-content-tertiary">
            {t('boq.custom_columns_hint', {
              defaultValue:
                'Custom columns appear in the BOQ grid before the actions column. Values are stored per position and exported with the BOQ. Removing a column hides it but preserves the underlying data.',
            })}
          </p>
        </div>
      </div>
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
