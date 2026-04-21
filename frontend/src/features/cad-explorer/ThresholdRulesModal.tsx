/**
 * ThresholdRulesModal — UI for editing conditional-formatting rules that
 * colour Data Explorer pivot cells.
 *
 * One rule per aggregate column, up to MAX_RULES. Users pick a numeric
 * column, set a low/high breakpoint, and choose three colour swatches.
 * Rules persist through `CadDataExplorerPage` URL state.
 */

import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2, X, RotateCcw, Palette } from 'lucide-react';
import { Button } from '@/shared/ui';
import {
  type ThresholdRule,
  createDefaultRule,
  isRuleValid,
  MAX_RULES,
  DEFAULT_LOW_COLOR,
  DEFAULT_MID_COLOR,
  DEFAULT_HIGH_COLOR,
} from './thresholds';

interface ThresholdRulesModalProps {
  open: boolean;
  onClose: () => void;
  /** Aggregate columns currently selected in the pivot — the only valid targets. */
  availableColumns: readonly string[];
  /** Current rules (the modal edits a local copy and only commits on Save). */
  rules: readonly ThresholdRule[];
  onChange: (next: ThresholdRule[]) => void;
}

export function ThresholdRulesModal({
  open,
  onClose,
  availableColumns,
  rules,
  onChange,
}: ThresholdRulesModalProps): React.ReactElement | null {
  const { t } = useTranslation();

  // Draft state — edited locally, committed on every keystroke so the
  // pivot preview updates live. "Reset" / "Close" map to the committed
  // state, not a deep rollback.
  const [draft, setDraft] = useState<ThresholdRule[]>(() => rules.map((r) => ({ ...r })));

  // Re-sync the draft if the modal is re-opened with a different rule
  // set (e.g. user switched session).
  React.useEffect(() => {
    if (open) setDraft(rules.map((r) => ({ ...r })));
  }, [open, rules]);

  const unusedColumns = useMemo(
    () => availableColumns.filter((c) => !draft.some((r) => r.column === c)),
    [availableColumns, draft],
  );

  const canAdd = draft.length < MAX_RULES && unusedColumns.length > 0;

  const commit = (next: ThresholdRule[]): void => {
    setDraft(next);
    onChange(next);
  };

  const addRule = (): void => {
    if (!canAdd) return;
    const first = unusedColumns[0];
    if (!first) return;
    commit([...draft, createDefaultRule(first)]);
  };

  const removeRule = (idx: number): void => {
    commit(draft.filter((_, i) => i !== idx));
  };

  const updateRule = (idx: number, patch: Partial<ThresholdRule>): void => {
    commit(draft.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const resetDefaults = (): void => {
    commit([]);
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="threshold-rules-modal"
    >
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />
      <div className="relative w-full max-w-2xl mx-4 rounded-2xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-primary/10">
              <Palette size={20} className="text-accent-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-content-primary">
                {t('explorer.thresholds_title', {
                  defaultValue: 'Conditional Formatting',
                })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('explorer.thresholds_subtitle', {
                  defaultValue:
                    'Colour pivot cells by value. Add up to {{max}} rules — one per numeric column.',
                  max: MAX_RULES,
                })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-hover transition-colors"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 pb-4 overflow-y-auto flex-1">
          {draft.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border-light bg-surface-secondary/30 p-8 text-center">
              <Palette size={28} className="mx-auto text-content-quaternary mb-2" />
              <p className="text-sm text-content-secondary font-medium">
                {t('explorer.thresholds_empty_title', {
                  defaultValue: 'No rules yet',
                })}
              </p>
              <p className="text-xs text-content-tertiary mt-1 mb-4">
                {t('explorer.thresholds_empty_hint', {
                  defaultValue:
                    'Add a rule to colour cells red / amber / green based on their value.',
                })}
              </p>
              {availableColumns.length === 0 ? (
                <p className="text-2xs text-content-quaternary">
                  {t('explorer.thresholds_no_cols', {
                    defaultValue:
                      'Pick at least one aggregate column in the pivot first.',
                  })}
                </p>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={addRule}
                  data-testid="threshold-add-first"
                >
                  <Plus size={14} className="mr-1" />
                  {t('explorer.thresholds_add_first', {
                    defaultValue: 'Add your first rule',
                  })}
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {draft.map((rule, idx) => {
                const valid = isRuleValid(rule, availableColumns);
                const colOptions = [
                  rule.column,
                  ...availableColumns.filter(
                    (c) => c !== rule.column && !draft.some((r) => r.column === c),
                  ),
                ];
                return (
                  <div
                    key={`rule-${idx}`}
                    data-testid={`threshold-rule-${idx}`}
                    className={`rounded-lg border p-3 space-y-2.5 ${
                      valid
                        ? 'border-border-light bg-surface-secondary/30'
                        : 'border-red-500/40 bg-red-500/5'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-2xs font-semibold text-content-tertiary uppercase tracking-wide shrink-0">
                        {t('explorer.thresholds_rule_label', {
                          defaultValue: 'Rule {{n}}',
                          n: idx + 1,
                        })}
                      </span>
                      <select
                        value={rule.column}
                        onChange={(e) =>
                          updateRule(idx, { column: e.target.value })
                        }
                        className="flex-1 h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                        data-testid={`threshold-rule-${idx}-column`}
                      >
                        {colOptions.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => removeRule(idx)}
                        className="flex h-8 w-8 items-center justify-center rounded-md text-content-tertiary hover:text-red-500 hover:bg-red-500/10 transition-colors shrink-0"
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        data-testid={`threshold-rule-${idx}-delete`}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <label className="flex flex-col gap-1">
                        <span className="text-2xs font-medium text-content-tertiary">
                          {t('explorer.thresholds_low', {
                            defaultValue: 'Low threshold',
                          })}
                        </span>
                        <input
                          type="number"
                          step="any"
                          value={Number.isFinite(rule.low) ? rule.low : ''}
                          onChange={(e) =>
                            updateRule(idx, { low: parseFloat(e.target.value) })
                          }
                          className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                          data-testid={`threshold-rule-${idx}-low`}
                        />
                      </label>
                      <label className="flex flex-col gap-1">
                        <span className="text-2xs font-medium text-content-tertiary">
                          {t('explorer.thresholds_high', {
                            defaultValue: 'High threshold',
                          })}
                        </span>
                        <input
                          type="number"
                          step="any"
                          value={Number.isFinite(rule.high) ? rule.high : ''}
                          onChange={(e) =>
                            updateRule(idx, { high: parseFloat(e.target.value) })
                          }
                          className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                          data-testid={`threshold-rule-${idx}-high`}
                        />
                      </label>
                    </div>

                    <div className="flex items-center gap-3">
                      <ColorSwatch
                        label={t('explorer.thresholds_color_low', {
                          defaultValue: 'Low',
                        })}
                        value={rule.lowColor}
                        onChange={(v) => updateRule(idx, { lowColor: v })}
                        testId={`threshold-rule-${idx}-color-low`}
                      />
                      <ColorSwatch
                        label={t('explorer.thresholds_color_mid', {
                          defaultValue: 'Mid',
                        })}
                        value={rule.midColor}
                        onChange={(v) => updateRule(idx, { midColor: v })}
                        testId={`threshold-rule-${idx}-color-mid`}
                      />
                      <ColorSwatch
                        label={t('explorer.thresholds_color_high', {
                          defaultValue: 'High',
                        })}
                        value={rule.highColor}
                        onChange={(v) => updateRule(idx, { highColor: v })}
                        testId={`threshold-rule-${idx}-color-high`}
                      />
                    </div>

                    {!valid && (
                      <p
                        className="text-2xs text-red-500"
                        data-testid={`threshold-rule-${idx}-error`}
                      >
                        {rule.low >= rule.high
                          ? t('explorer.thresholds_err_order', {
                              defaultValue: 'Low must be less than High.',
                            })
                          : t('explorer.thresholds_err_column', {
                              defaultValue:
                                'Column must be one of the pivot aggregate columns.',
                            })}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 px-6 py-4 border-t border-border-light shrink-0">
          <div className="flex items-center gap-2">
            <button
              onClick={resetDefaults}
              disabled={draft.length === 0}
              className="h-8 px-2.5 rounded-md text-xs text-content-tertiary hover:text-content-primary hover:bg-surface-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
              data-testid="threshold-reset"
            >
              <RotateCcw size={13} />
              {t('explorer.thresholds_reset', {
                defaultValue: 'Reset to defaults',
              })}
            </button>
          </div>
          <div className="flex items-center gap-2">
            {draft.length > 0 && (
              <span className="text-2xs text-content-quaternary tabular-nums">
                {draft.length}/{MAX_RULES}
              </span>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={addRule}
              disabled={!canAdd}
              data-testid="threshold-add"
            >
              <Plus size={14} className="mr-1" />
              {t('explorer.thresholds_add', { defaultValue: 'Add rule' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={onClose}
              data-testid="threshold-close"
            >
              {t('common.close', { defaultValue: 'Close' })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Inline colour swatch ─────────────────────────────────────────────── */

interface ColorSwatchProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testId?: string;
}

function ColorSwatch({
  label,
  value,
  onChange,
  testId,
}: ColorSwatchProps): React.ReactElement {
  // Standard palette for quick picking. Users can still pick any colour
  // via the native <input type="color"> picker.
  const presets = [
    DEFAULT_LOW_COLOR,
    DEFAULT_MID_COLOR,
    DEFAULT_HIGH_COLOR,
    '#3b82f6', // blue
    '#8b5cf6', // violet
    '#6b7280', // neutral
  ];
  return (
    <label className="flex flex-col gap-1 flex-1 min-w-0">
      <span className="text-2xs font-medium text-content-tertiary">{label}</span>
      <div className="flex items-center gap-1.5">
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-7 rounded-md border border-border cursor-pointer bg-surface-primary"
          data-testid={testId}
        />
        <div className="flex items-center gap-0.5">
          {presets.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onChange(p)}
              className={`h-5 w-5 rounded-sm border transition-transform hover:scale-110 ${
                value.toLowerCase() === p.toLowerCase()
                  ? 'border-content-primary ring-1 ring-content-primary'
                  : 'border-border-light'
              }`}
              style={{ backgroundColor: p }}
              aria-label={p}
            />
          ))}
        </div>
      </div>
    </label>
  );
}
