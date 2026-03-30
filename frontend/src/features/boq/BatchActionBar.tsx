import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Trash2, Ruler, X, ChevronDown } from 'lucide-react';

const UNITS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'] as const;

export interface BatchActionBarProps {
  /** IDs of the currently selected positions. */
  selectedIds: string[];
  /** Called to delete all selected positions (after user confirms). */
  onBatchDelete: (ids: string[]) => void;
  /** Called to change the unit of all selected positions. */
  onBatchChangeUnit: (ids: string[], unit: string) => void;
  /** Called to clear the current selection. */
  onClearSelection: () => void;
}

export function BatchActionBar({
  selectedIds,
  onBatchDelete,
  onBatchChangeUnit,
  onClearSelection,
}: BatchActionBarProps) {
  const { t } = useTranslation();
  const [unitDropdownOpen, setUnitDropdownOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const unitDropdownRef = useRef<HTMLDivElement>(null);
  const count = selectedIds.length;

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

  // Close confirm dialog on Escape
  useEffect(() => {
    if (!confirmDeleteOpen) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        setConfirmDeleteOpen(false);
      }
    }

    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [confirmDeleteOpen]);

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

  return (
    <>
      {/* Floating batch action bar */}
      <div
        className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 animate-slide-up"
        role="toolbar"
        aria-label={t('boq.batch_actions', { defaultValue: 'Batch actions' })}
      >
        <div className="flex items-center gap-3 rounded-2xl border border-border-light bg-surface-elevated shadow-xl px-5 py-3">
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
              className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue-subtle px-3 py-1.5 text-xs font-medium text-oe-blue hover:bg-oe-blue-subtle/80 transition-colors"
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
            className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in"
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
    </>
  );
}
