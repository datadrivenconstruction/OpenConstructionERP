// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SendToTenderDialog — turn BOQ sections into a tender package.
 *
 * Creates a draft package on the tendering module straight from this estimate.
 * The dialog lists the bill's top-level rows (sections, and any priced line
 * sitting loose at the top) with every row ticked, so the default is still the
 * whole BOQ; unticking rows sends only the rest (and their descendants). Rows
 * already selected in the grid start as the only ticked ones. The server
 * copies a line-item template onto the package so bids can be seeded later, and
 * keeps the link back to the source BOQ for bid-vs-budget levelling.
 */

import { useState, useEffect, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Send, X } from 'lucide-react';
import { boqApi, type TenderPackageRef } from './api';
import { useToastStore } from '@/stores/useToastStore';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';

export interface SendToTenderDialogProps {
  boqId: string;
  projectId: string;
  /** Source estimate name, used to seed the package name. */
  baseName: string;
  /**
   * Top-level section ids the user has selected. Empty means "all sections of
   * the BOQ" (the backend treats an empty list as every top-level section).
   */
  sectionIds: string[];
  /**
   * The bill's top-level rows in bill order, offered as the scope picker.
   * Empty hides the picker and packages `sectionIds` (or the whole BOQ).
   */
  scopeRows?: TenderScopeRow[];
  isOpen: boolean;
  onClose: () => void;
  /** Called with the new package once it is created. */
  onCreated: (pkg: TenderPackageRef) => void;
}

/** One top-level row of the bill, as the scope picker lists it. */
export interface TenderScopeRow {
  id: string;
  ordinal: string;
  description: string;
}

const NO_ROWS: TenderScopeRow[] = [];

/**
 * The `section_ids` to send for a pick: an empty list when every row is
 * ticked, so the package records that it covers the whole bill, else the
 * ticked rows in bill order.
 */
export function scopeToSend(rows: TenderScopeRow[], picked: ReadonlySet<string>): string[] {
  if (rows.every((r) => picked.has(r.id))) return [];
  return rows.filter((r) => picked.has(r.id)).map((r) => r.id);
}

export function SendToTenderDialog({
  boqId,
  projectId,
  baseName,
  sectionIds,
  scopeRows = NO_ROWS,
  isOpen,
  onClose,
  onCreated,
}: SendToTenderDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const panelRef = useRef<HTMLDivElement>(null);
  useFocusTrap(panelRef, isOpen);

  const [name, setName] = useState('');
  const [deadline, setDeadline] = useState('');
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const hasPicker = scopeRows.length > 0;
  const scoped = sectionIds.length > 0;
  const sendIds = useMemo(
    () => (hasPicker ? scopeToSend(scopeRows, picked) : sectionIds),
    [hasPicker, scopeRows, picked, sectionIds],
  );
  const nothingPicked = hasPicker && picked.size === 0;

  useEffect(() => {
    if (isOpen) {
      setName(
        t('boq.tender_default_name', {
          defaultValue: 'Tender - {{name}}',
          name: baseName || t('boq.untitled_estimate', { defaultValue: 'Estimate' }),
        }),
      );
      setDeadline('');
    }
  }, [isOpen, baseName, t]);

  // Start from the grid selection when there is one, else from every row.
  // Keyed on opening only, so ticking rows is not undone by a re-render.
  useEffect(() => {
    if (!isOpen) return;
    const preselected = sectionIds.filter((id) => scopeRows.some((r) => r.id === id));
    setPicked(new Set(preselected.length > 0 ? preselected : scopeRows.map((r) => r.id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const toggleRow = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  useEffect(() => {
    if (!isOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener('keydown', onKey, { capture: true });
    return () => document.removeEventListener('keydown', onKey, { capture: true });
  }, [isOpen, onClose]);

  const mutation = useMutation({
    mutationFn: () =>
      boqApi.createTenderFromBoq({
        project_id: projectId,
        boq_id: boqId,
        section_ids: sendIds,
        package_name: name.trim() || baseName,
        deadline: deadline || undefined,
      }),
    onSuccess: (pkg) => {
      queryClient.invalidateQueries({ queryKey: ['tender-packages'] });
      addToast({
        type: 'success',
        title: t('boq.tender_created', { defaultValue: 'Tender package created' }),
      });
      onCreated(pkg);
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('boq.tender_failed', { defaultValue: 'Could not create tender package' }),
        message: err.message,
      });
    },
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-label={t('boq.tender_title', { defaultValue: 'Send to tender' })}
        className="relative z-10 w-full max-w-md mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in focus:outline-none"
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
              <Send size={15} />
            </span>
            <h2 className="text-base font-semibold text-content-primary">
              {t('boq.tender_title', { defaultValue: 'Send to tender' })}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-6 pt-4 pb-2 space-y-4">
          {hasPicker ? (
            <fieldset className="block">
              <div className="flex items-center justify-between">
                <legend className="text-xs font-medium text-content-secondary">
                  {t('boq.tender_scope_label', { defaultValue: 'Sections to package' })}
                </legend>
                <button
                  type="button"
                  className="text-xs text-oe-blue hover:underline"
                  onClick={() =>
                    setPicked(
                      picked.size === scopeRows.length ? new Set() : new Set(scopeRows.map((r) => r.id)),
                    )
                  }
                >
                  {picked.size === scopeRows.length
                    ? t('boq.tender_scope_none', { defaultValue: 'Clear all' })
                    : t('boq.tender_scope_every', { defaultValue: 'Select all' })}
                </button>
              </div>
              <div className="mt-1 max-h-56 overflow-y-auto rounded-md border border-border bg-surface-primary">
                {scopeRows.map((row) => (
                  <label
                    key={row.id}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm text-content-primary hover:bg-surface-secondary"
                  >
                    <input
                      type="checkbox"
                      checked={picked.has(row.id)}
                      onChange={() => toggleRow(row.id)}
                    />
                    {row.ordinal && (
                      <span className="shrink-0 tabular-nums text-content-tertiary">{row.ordinal}</span>
                    )}
                    <span className="truncate">
                      {row.description || t('boq.untitled_section', { defaultValue: '(untitled)' })}
                    </span>
                  </label>
                ))}
              </div>
              {nothingPicked && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('boq.tender_scope_empty', { defaultValue: 'Pick at least one section to package.' })}
                </p>
              )}
            </fieldset>
          ) : (
          <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2.5 text-xs text-content-secondary">
            {scoped
              ? t('boq.tender_scope_selected', {
                  defaultValue:
                    'Selected sections ({{count}}) and their items will be packaged.',
                  count: sectionIds.length,
                })
              : t('boq.tender_scope_all', {
                  defaultValue:
                    'All sections of this estimate will be packaged. Select sections first to send only part of it.',
                })}
          </div>
          )}

          <label className="block">
            <span className="text-xs font-medium text-content-secondary">
              {t('boq.tender_name_label', { defaultValue: 'Package name' })}
            </span>
            <input
              autoFocus
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              aria-label={t('boq.tender_name_label', { defaultValue: 'Package name' })}
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-content-secondary">
              {t('boq.tender_deadline_label', { defaultValue: 'Bid deadline (optional)' })}
            </span>
            <input
              type="date"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              aria-label={t('boq.tender_deadline_label', { defaultValue: 'Bid deadline (optional)' })}
            />
          </label>
        </div>

        <div className="flex gap-3 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium bg-surface-primary text-content-primary border border-border hover:bg-surface-secondary transition-all"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !name.trim() || nothingPicked}
            className="flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send size={14} />
            {mutation.isPending
              ? t('boq.tender_creating', { defaultValue: 'Creating...' })
              : t('boq.tender_create', { defaultValue: 'Create package' })}
          </button>
        </div>
      </div>
    </div>
  );
}
