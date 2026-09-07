// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Trash2, Ruler, X, ChevronDown, Percent, Hash, Tag, Replace, Equal } from 'lucide-react';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';
import { getUnitsForLocale } from './boqHelpers';

const UNITS = getUnitsForLocale();

/**
 * v3.12.0 Stream A — kinds of bulk action emitted by the bar.
 * `factor` is the multiplier (e.g. 1.10 for +10 %).
 * `code` is the classification code string for the "set classification" action.
 */
export type BatchFactorKind = 'rate' | 'quantity';
export type BatchClassificationStandard = 'din276' | 'nrm' | 'masterformat';

export interface BatchActionBarProps {
  /** IDs of the currently selected positions. */
  selectedIds: string[];
  /** Called to delete all selected positions (after user confirms). */
  onBatchDelete: (ids: string[]) => void;
  /** Called to change the unit of all selected positions. */
  onBatchChangeUnit: (ids: string[], unit: string) => void;
  /** Called to clear the current selection. */
  onClearSelection: () => void;
  /**
   * v3.12.0 — multiply each selected row's unit_rate / quantity by a factor.
   * Optional: caller may omit if the bulk-update endpoint is unavailable.
   */
  onBatchFactor?: (ids: string[], kind: BatchFactorKind, factor: number) => void;
  /** v3.12.0 — set the classification code on all selected positions. */
  onBatchSetClassification?: (
    ids: string[],
    standard: BatchClassificationStandard,
    code: string,
  ) => void;
  /** Find and replace text across the descriptions of all selected positions. */
  onBatchFindReplace?: (
    ids: string[],
    find: string,
    replace: string,
    caseSensitive: boolean,
  ) => void;
  /** Set an exact unit_rate / quantity on all selected positions (Excel-style fill). */
  onBatchSetValue?: (ids: string[], field: 'unit_rate' | 'quantity', value: number) => void;
}

interface FactorDialogState {
  kind: BatchFactorKind;
  value: string;
}

interface ClassificationDialogState {
  standard: BatchClassificationStandard;
  code: string;
}

interface FindReplaceDialogState {
  find: string;
  replace: string;
  caseSensitive: boolean;
}

interface SetValueDialogState {
  field: 'unit_rate' | 'quantity';
  value: string;
}

export function BatchActionBar({
  selectedIds,
  onBatchDelete,
  onBatchChangeUnit,
  onClearSelection,
  onBatchFactor,
  onBatchSetClassification,
  onBatchFindReplace,
  onBatchSetValue,
}: BatchActionBarProps) {
  const { t } = useTranslation();
  const [unitDropdownOpen, setUnitDropdownOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [factorDialog, setFactorDialog] = useState<FactorDialogState | null>(null);
  const [classDialog, setClassDialog] = useState<ClassificationDialogState | null>(null);
  const [findReplaceDialog, setFindReplaceDialog] = useState<FindReplaceDialogState | null>(null);
  const [setValueDialog, setSetValueDialog] = useState<SetValueDialogState | null>(null);
  const unitDropdownRef = useRef<HTMLDivElement>(null);
  const findReplacePanelRef = useRef<HTMLDivElement>(null);
  const setValuePanelRef = useRef<HTMLDivElement>(null);
  const factorPanelRef = useRef<HTMLDivElement>(null);
  const classPanelRef = useRef<HTMLDivElement>(null);
  const count = selectedIds.length;

  // Trap Tab / restore focus on close, matching the shared modal a11y pattern.
  useFocusTrap(findReplacePanelRef, !!findReplaceDialog);
  useFocusTrap(setValuePanelRef, !!setValueDialog);
  useFocusTrap(factorPanelRef, !!factorDialog);
  useFocusTrap(classPanelRef, !!classDialog);

  // Set-value input validity. parseDecimalInput (not parseFloat) so '1.2.3',
  // '--' and 'abc' are rejected rather than silently truncated. Drives both
  // the Apply button and the inline error, so invalid input never just
  // no-ops. It replaces a `.replace(',', '.')`, which read `48,60` correctly
  // but turned `1.234,56` into `1.234.56` and rejected it - String.replace
  // with a string pattern only swaps the FIRST match.
  const setValueParsed = setValueDialog ? parseDecimalInput(setValueDialog.value) : null;
  const setValueValid = setValueParsed !== null && setValueParsed >= 0;

  // Close unit dropdown on outside click
  useEffect(() => {
    if (!unitDropdownOpen) return;

    function handleClickOutside(e: MouseEvent) {
      if (unitDropdownRef.current && !unitDropdownRef.current.contains(e.target as Node)) {
        setUnitDropdownOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [unitDropdownOpen]);

  // Close any open dialog on Escape
  useEffect(() => {
    if (!confirmDeleteOpen && !factorDialog && !classDialog && !findReplaceDialog && !setValueDialog)
      return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        setConfirmDeleteOpen(false);
        setFactorDialog(null);
        setClassDialog(null);
        setFindReplaceDialog(null);
        setSetValueDialog(null);
      }
    }

    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [confirmDeleteOpen, factorDialog, classDialog, findReplaceDialog, setValueDialog]);

  if (count === 0) return null;

  const handleDeleteClick = () => {
    setConfirmDeleteOpen(true);
  };

  const handleConfirmDelete = () => {
    setConfirmDeleteOpen(false);
    onBatchDelete(selectedIds);
  };

  const handleUnitSelect = (unit: string) => {
    setUnitDropdownOpen(false);
    onBatchChangeUnit(selectedIds, unit);
  };

  const handleConfirmFactor = () => {
    if (!factorDialog || !onBatchFactor) return;
    const parsed = parseDecimalInput(factorDialog.value);
    if (parsed === null || parsed <= 0) return;
    onBatchFactor(selectedIds, factorDialog.kind, parsed);
    setFactorDialog(null);
  };

  const handleConfirmClassification = () => {
    if (!classDialog || !onBatchSetClassification) return;
    const code = classDialog.code.trim();
    if (!code) return;
    onBatchSetClassification(selectedIds, classDialog.standard, code);
    setClassDialog(null);
  };

  const handleConfirmFindReplace = () => {
    if (!findReplaceDialog || !onBatchFindReplace) return;
    if (!findReplaceDialog.find.trim()) return;
    onBatchFindReplace(
      selectedIds,
      findReplaceDialog.find,
      findReplaceDialog.replace,
      findReplaceDialog.caseSensitive,
    );
    setFindReplaceDialog(null);
  };

  const handleConfirmSetValue = () => {
    // Null-check the parsed value itself rather than the derived boolean so
    // the narrowing reaches the call below.
    if (!setValueDialog || !onBatchSetValue || setValueParsed === null || !setValueValid) return;
    onBatchSetValue(selectedIds, setValueDialog.field, setValueParsed);
    setSetValueDialog(null);
  };

  return (
    <>
      {/* Floating batch action bar */}
      <div
        className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40"
        role="toolbar"
        aria-label={t('boq.batch_actions', { defaultValue: 'Batch actions' })}
      >
        {/* The slide and the centring offset have to live on DIFFERENT nodes;
            see RequiresProject.tsx for the canonical form. slideUp declares
            `transform` on its `from` frame, so on a single node it replaces
            -translate-x-1/2 outright: the bar rises half its own width to the
            right of centre and snaps into place when the animation ends.
            Offset on the wrapper, slide on the bar. */}
        <div className="flex items-center gap-3 rounded-2xl border border-border-light bg-surface-elevated shadow-xl px-5 py-3 animate-slide-up">
          {/* Selection count */}
          <span className="text-sm font-medium text-content-primary tabular-nums whitespace-nowrap">
            {t('boq.n_selected', {
              defaultValue: '{{count}} positions selected',
              count,
            })}
          </span>

          {/* Divider */}
          <div className="h-5 w-px bg-border-light" />

          {/* Delete selected */}
          <button
            type="button"
            onClick={handleDeleteClick}
            aria-label={t('boq.batch_delete', { defaultValue: 'Delete selected' })}
            className="inline-flex items-center gap-1.5 rounded-lg bg-semantic-error/10 px-3 py-1.5 text-xs font-medium text-semantic-error hover:bg-semantic-error/20 transition-colors"
          >
            <Trash2 size={14} />
            {t('boq.batch_delete', { defaultValue: 'Delete selected' })}
          </button>

          {/* Change unit */}
          <div ref={unitDropdownRef} className="relative">
            <button
              type="button"
              onClick={() => setUnitDropdownOpen((prev) => !prev)}
              aria-label={t('boq.batch_change_unit', { defaultValue: 'Change unit' })}
              aria-expanded={unitDropdownOpen}
              aria-haspopup="listbox"
              className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue-subtle px-3 py-1.5 text-xs font-medium text-oe-blue-text hover:bg-oe-blue-subtle/80 transition-colors"
            >
              <Ruler size={14} />
              {t('boq.batch_change_unit', { defaultValue: 'Change unit' })}
              <ChevronDown size={12} />
            </button>

            {unitDropdownOpen && (
              <div role="listbox" aria-label={t('boq.unit_options', { defaultValue: 'Unit options' })} className="absolute bottom-full mb-2 left-0 w-36 rounded-xl border border-border-light bg-surface-elevated shadow-lg overflow-hidden animate-fade-in">
                <div className="py-1 max-h-52 overflow-y-auto">
                  {UNITS.map((unit) => (
                    <button
                      key={unit}
                      type="button"
                      role="option"
                      onClick={() => handleUnitSelect(unit)}
                      className="flex w-full items-center px-3 py-2 text-xs font-mono uppercase text-content-primary hover:bg-surface-secondary transition-colors"
                    >
                      {unit}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* v3.12.0 Stream A — multiply rate by factor */}
          {onBatchFactor && (
            <button
              type="button"
              onClick={() => setFactorDialog({ kind: 'rate', value: '1.10' })}
              aria-label={t('boq.batch_rate_factor', { defaultValue: 'Multiply rate by factor' })}
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-300 hover:bg-amber-500/20 transition-colors"
            >
              <Percent size={14} />
              {t('boq.batch_rate_factor', { defaultValue: 'Multiply rate' })}
            </button>
          )}

          {/* v3.12.0 Stream A — multiply quantity by factor */}
          {onBatchFactor && (
            <button
              type="button"
              onClick={() => setFactorDialog({ kind: 'quantity', value: '1.00' })}
              aria-label={t('boq.batch_qty_factor', { defaultValue: 'Multiply quantity by factor' })}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/20 transition-colors"
            >
              <Hash size={14} />
              {t('boq.batch_qty_factor', { defaultValue: 'Multiply qty' })}
            </button>
          )}

          {/* v3.12.0 Stream A — set classification */}
          {onBatchSetClassification && (
            <button
              type="button"
              onClick={() => setClassDialog({ standard: 'din276', code: '' })}
              aria-label={t('boq.batch_set_classification', { defaultValue: 'Set classification' })}
              className="inline-flex items-center gap-1.5 rounded-lg bg-purple-500/10 px-3 py-1.5 text-xs font-medium text-purple-700 dark:text-purple-300 hover:bg-purple-500/20 transition-colors"
            >
              <Tag size={14} />
              {t('boq.batch_set_classification', { defaultValue: 'Classification' })}
            </button>
          )}

          {/* Find & replace across the descriptions of the selected rows */}
          {onBatchFindReplace && (
            <button
              type="button"
              onClick={() => setFindReplaceDialog({ find: '', replace: '', caseSensitive: false })}
              aria-label={t('boq.batch_find_replace', { defaultValue: 'Find and replace' })}
              className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500/10 px-3 py-1.5 text-xs font-medium text-sky-700 dark:text-sky-300 hover:bg-sky-500/20 transition-colors"
            >
              <Replace size={14} />
              {t('boq.batch_find_replace_short', { defaultValue: 'Find & replace' })}
            </button>
          )}

          {/* Set an exact rate / quantity on every selected row */}
          {onBatchSetValue && (
            <button
              type="button"
              onClick={() => setSetValueDialog({ field: 'unit_rate', value: '' })}
              aria-label={t('boq.batch_set_value', { defaultValue: 'Set value' })}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-500/10 px-3 py-1.5 text-xs font-medium text-indigo-700 dark:text-indigo-300 hover:bg-indigo-500/20 transition-colors"
            >
              <Equal size={14} />
              {t('boq.batch_set_value_short', { defaultValue: 'Set value' })}
            </button>
          )}

          {/* Clear selection */}
          <button
            type="button"
            onClick={onClearSelection}
            aria-label={t('boq.batch_clear_selection', { defaultValue: 'Clear selection' })}
            className="inline-flex items-center gap-1.5 rounded-lg bg-surface-secondary px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-tertiary transition-colors"
          >
            <X size={14} />
            {t('boq.batch_clear_selection', { defaultValue: 'Clear selection' })}
          </button>
        </div>
      </div>

      {/* Inline confirmation dialog for batch delete */}
      {confirmDeleteOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
            onClick={() => setConfirmDeleteOpen(false)}
            aria-hidden="true"
          />

          {/* Dialog */}
          <div
            role="alertdialog"
            aria-modal="true"
            aria-label={t('boq.batch_delete_confirm_title', { defaultValue: 'Delete positions' })}
            tabIndex={-1}
            className="relative z-10 w-full max-w-sm mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in focus:outline-none"
          >
            <div className="px-6 pt-6 pb-4">
              <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-semantic-error/10 text-semantic-error mb-4">
                <Trash2 size={20} />
              </div>
              <h2 className="text-base font-semibold text-content-primary text-center">
                {t('boq.batch_delete_confirm_title', { defaultValue: 'Delete positions' })}
              </h2>
              <p className="mt-2 text-sm text-content-secondary text-center leading-relaxed">
                {t('boq.batch_delete_confirm_message', {
                  defaultValue: 'Are you sure you want to delete {{count}} selected positions? This action cannot be undone.',
                  count,
                })}
              </p>
            </div>
            <div className="flex gap-3 px-6 pb-6">
              <button
                type="button"
                onClick={() => setConfirmDeleteOpen(false)}
                className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium bg-surface-primary text-content-primary border border-border hover:bg-surface-secondary active:bg-surface-tertiary transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                autoFocus
                className="flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium text-content-inverse bg-semantic-error hover:opacity-90 active:opacity-80 shadow-xs hover:shadow-md transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-semantic-error focus-visible:ring-offset-2"
              >
                {t('boq.batch_delete_confirm', {
                  defaultValue: 'Delete {{count}} positions',
                  count,
                })}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* v3.12.0 — Factor prompt dialog (rate or quantity) */}
      {factorDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
            onClick={() => setFactorDialog(null)}
            aria-hidden="true"
          />
          <div
            ref={factorPanelRef}
            role="dialog"
            aria-modal="true"
            tabIndex={-1}
            aria-label={
              factorDialog.kind === 'rate'
                ? t('boq.batch_rate_factor_title', { defaultValue: 'Multiply rate by factor' })
                : t('boq.batch_qty_factor_title', { defaultValue: 'Multiply quantity by factor' })
            }
            className="relative z-10 w-full max-w-sm mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in focus:outline-none"
          >
            <div className="px-6 pt-6 pb-4">
              <h2 className="text-base font-semibold text-content-primary">
                {factorDialog.kind === 'rate'
                  ? t('boq.batch_rate_factor_title', { defaultValue: 'Multiply rate by factor' })
                  : t('boq.batch_qty_factor_title', { defaultValue: 'Multiply quantity by factor' })}
              </h2>
              <p className="mt-1 text-xs text-content-secondary">
                {t('boq.batch_factor_hint', {
                  defaultValue: 'Applied to {{count}} selected positions. Example: 1.10 = +10%.',
                  count,
                })}
              </p>
              <label className="mt-4 block">
                <span className="text-xs font-medium text-content-secondary">
                  {t('boq.batch_factor_label', { defaultValue: 'Factor (> 0)' })}
                </span>
                <input
                  autoFocus
                  type="text"
                  inputMode="decimal"
                  value={factorDialog.value}
                  onChange={(e) =>
                    setFactorDialog({ ...factorDialog, value: e.target.value })
                  }
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleConfirmFactor();
                  }}
                  className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm font-mono text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                  aria-label={t('boq.batch_factor_label', { defaultValue: 'Factor (> 0)' })}
                />
              </label>
            </div>
            <div className="flex gap-3 px-6 pb-6">
              <button
                type="button"
                onClick={() => setFactorDialog(null)}
                className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium bg-surface-primary text-content-primary border border-border hover:bg-surface-secondary transition-all"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                type="button"
                onClick={handleConfirmFactor}
                className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-all"
              >
                {t('common.apply', { defaultValue: 'Apply' })}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* v3.12.0 — Classification dialog */}
      {classDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
            onClick={() => setClassDialog(null)}
            aria-hidden="true"
          />
          <div
            ref={classPanelRef}
            role="dialog"
            aria-modal="true"
            tabIndex={-1}
            aria-label={t('boq.batch_set_classification', { defaultValue: 'Set classification' })}
            className="relative z-10 w-full max-w-sm mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in focus:outline-none"
          >
            <div className="px-6 pt-6 pb-4">
              <h2 className="text-base font-semibold text-content-primary">
                {t('boq.batch_set_classification', { defaultValue: 'Set classification' })}
              </h2>
              <p className="mt-1 text-xs text-content-secondary">
                {t('boq.batch_class_hint', {
                  defaultValue: 'Applies to {{count}} selected positions.',
                  count,
                })}
              </p>
              <label className="mt-4 block">
                <span className="text-xs font-medium text-content-secondary">
                  {t('boq.batch_class_standard', { defaultValue: 'Standard' })}
                </span>
                <select
                  value={classDialog.standard}
                  onChange={(e) =>
                    setClassDialog({
                      ...classDialog,
                      standard: e.target.value as BatchClassificationStandard,
                    })
                  }
                  className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                >
                  <option value="din276">DIN 276</option>
                  <option value="nrm">NRM</option>
                  <option value="masterformat">MasterFormat</option>
                </select>
              </label>
              <label className="mt-3 block">
                <span className="text-xs font-medium text-content-secondary">
                  {t('boq.batch_class_code', { defaultValue: 'Code' })}
                </span>
                <input
                  autoFocus
                  type="text"
                  value={classDialog.code}
                  onChange={(e) =>
                    setClassDialog({ ...classDialog, code: e.target.value })
                  }
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleConfirmClassification();
                  }}
                  placeholder={
                    classDialog.standard === 'din276'
                      ? '330'
                      : classDialog.standard === 'nrm'
                        ? '2.6.1'
                        : '03 30 00'
                  }
                  className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm font-mono text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                  aria-label={t('boq.batch_class_code', { defaultValue: 'Code' })}
                />
              </label>
            </div>
            <div className="flex gap-3 px-6 pb-6">
              <button
                type="button"
                onClick={() => setClassDialog(null)}
                className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium bg-surface-primary text-content-primary border border-border hover:bg-surface-secondary transition-all"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                type="button"
                onClick={handleConfirmClassification}
                disabled={!classDialog.code.trim()}
                className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('common.apply', { defaultValue: 'Apply' })}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Find & replace dialog (description text) */}
      {findReplaceDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
            onClick={() => setFindReplaceDialog(null)}
            aria-hidden="true"
          />
          <div
            ref={findReplacePanelRef}
            role="dialog"
            aria-modal="true"
            tabIndex={-1}
            aria-label={t('boq.batch_find_replace', { defaultValue: 'Find and replace' })}
            className="relative z-10 w-full max-w-sm mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in focus:outline-none"
          >
            <div className="px-6 pt-6 pb-4">
              <h2 className="text-base font-semibold text-content-primary">
                {t('boq.batch_find_replace', { defaultValue: 'Find and replace' })}
              </h2>
              <p className="mt-1 text-xs text-content-secondary">
                {t('boq.batch_find_replace_hint', {
                  defaultValue:
                    'Rewrites the description on the selected positions ({{count}}). Rows with no match stay unchanged.',
                  count,
                })}
              </p>
              <label className="mt-4 block">
                <span className="text-xs font-medium text-content-secondary">
                  {t('boq.batch_find_label', { defaultValue: 'Find' })}
                </span>
                <input
                  autoFocus
                  type="text"
                  value={findReplaceDialog.find}
                  onChange={(e) =>
                    setFindReplaceDialog({ ...findReplaceDialog, find: e.target.value })
                  }
                  className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                  aria-label={t('boq.batch_find_label', { defaultValue: 'Find' })}
                />
              </label>
              <label className="mt-3 block">
                <span className="text-xs font-medium text-content-secondary">
                  {t('boq.batch_replace_label', { defaultValue: 'Replace with' })}
                </span>
                <input
                  type="text"
                  value={findReplaceDialog.replace}
                  onChange={(e) =>
                    setFindReplaceDialog({ ...findReplaceDialog, replace: e.target.value })
                  }
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleConfirmFindReplace();
                  }}
                  className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                  aria-label={t('boq.batch_replace_label', { defaultValue: 'Replace with' })}
                />
              </label>
              <label className="mt-3 flex items-center gap-2 text-xs text-content-secondary">
                <input
                  type="checkbox"
                  checked={findReplaceDialog.caseSensitive}
                  onChange={(e) =>
                    setFindReplaceDialog({ ...findReplaceDialog, caseSensitive: e.target.checked })
                  }
                  className="accent-oe-blue"
                />
                {t('boq.batch_find_case', { defaultValue: 'Case sensitive' })}
              </label>
            </div>
            <div className="flex gap-3 px-6 pb-6">
              <button
                type="button"
                onClick={() => setFindReplaceDialog(null)}
                className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium bg-surface-primary text-content-primary border border-border hover:bg-surface-secondary transition-all"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                type="button"
                onClick={handleConfirmFindReplace}
                disabled={!findReplaceDialog.find.trim()}
                className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('common.apply', { defaultValue: 'Apply' })}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Set an exact value (rate / quantity) on the selected rows */}
      {setValueDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
            onClick={() => setSetValueDialog(null)}
            aria-hidden="true"
          />
          <div
            ref={setValuePanelRef}
            role="dialog"
            aria-modal="true"
            tabIndex={-1}
            aria-label={t('boq.batch_set_value', { defaultValue: 'Set value' })}
            className="relative z-10 w-full max-w-sm mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in focus:outline-none"
          >
            <div className="px-6 pt-6 pb-4">
              <h2 className="text-base font-semibold text-content-primary">
                {t('boq.batch_set_value', { defaultValue: 'Set value' })}
              </h2>
              <p className="mt-1 text-xs text-content-secondary">
                {t('boq.batch_set_value_hint', {
                  defaultValue:
                    'Writes the same value to the selected positions ({{count}}), overwriting what is there.',
                  count,
                })}
              </p>
              <label className="mt-4 block">
                <span className="text-xs font-medium text-content-secondary">
                  {t('boq.batch_set_value_field', { defaultValue: 'Field' })}
                </span>
                <select
                  value={setValueDialog.field}
                  onChange={(e) =>
                    setSetValueDialog({
                      ...setValueDialog,
                      field: e.target.value as 'unit_rate' | 'quantity',
                    })
                  }
                  className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                >
                  <option value="unit_rate">
                    {t('boq.batch_set_value_rate', { defaultValue: 'Unit rate' })}
                  </option>
                  <option value="quantity">
                    {t('boq.batch_set_value_qty', { defaultValue: 'Quantity' })}
                  </option>
                </select>
              </label>
              <label className="mt-3 block">
                <span className="text-xs font-medium text-content-secondary">
                  {t('boq.batch_set_value_value', { defaultValue: 'Value' })}
                </span>
                <input
                  autoFocus
                  type="text"
                  inputMode="decimal"
                  value={setValueDialog.value}
                  onChange={(e) => setSetValueDialog({ ...setValueDialog, value: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleConfirmSetValue();
                  }}
                  className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm font-mono text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                  aria-label={t('boq.batch_set_value_value', { defaultValue: 'Value' })}
                />
              </label>
              {setValueDialog.value.trim() !== '' && !setValueValid && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('boq.batch_set_value_invalid', {
                    defaultValue: 'Enter a number 0 or greater.',
                  })}
                </p>
              )}
            </div>
            <div className="flex gap-3 px-6 pb-6">
              <button
                type="button"
                onClick={() => setSetValueDialog(null)}
                className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium bg-surface-primary text-content-primary border border-border hover:bg-surface-secondary transition-all"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                type="button"
                onClick={handleConfirmSetValue}
                disabled={!setValueValid}
                className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('common.apply', { defaultValue: 'Apply' })}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
