// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * EditMarkupModal — edit title / description / color of an existing markup.
 *
 * Currently markups can only be created or deleted, so users who want
 * to fix a typo in a label have to delete + recreate, which loses the
 * markup position on the document. This modal exposes the existing
 * PATCH /v1/markups/{id} endpoint so the row's geometry / position
 * stays intact.
 *
 * Mirrors the visual + interaction patterns of AddMarkupModal in
 * MarkupsPage.tsx (backdrop click, Escape key, animated panel, preset
 * color swatches) — the codebase has no shared Modal primitive so the
 * inline pattern is intentional.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Edit3, X, Flag, CalendarClock } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { fetchUsers, type User as AssigneeUser } from '@/features/users/api';
import { updateMarkup } from './api';
import type { Markup, UpdateMarkupPayload } from './api';
import {
  MARKUP_PRIORITIES,
  PRIORITY_LABELS,
  getMarkupPriority,
  getMarkupDueDate,
  type MarkupPriority,
} from './issueTracking';

const PRESET_COLORS = [
  { name: 'Red', value: '#EF4444' },
  { name: 'Orange', value: '#F97316' },
  { name: 'Yellow', value: '#EAB308' },
  { name: 'Green', value: '#22C55E' },
  { name: 'Blue', value: '#3B82F6' },
  { name: 'Purple', value: '#A855F7' },
];

const inputCls =
  'h-8 rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors';

export interface EditMarkupModalProps {
  open: boolean;
  markup: Markup | null;
  projectId: string;
  onClose: () => void;
  /** Called after the PATCH lands successfully — page can refetch / invalidate. */
  onUpdated?: (updated: Markup) => void;
}

export function EditMarkupModal({
  open,
  markup,
  projectId,
  onClose,
  onUpdated,
}: EditMarkupModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const dialogRef = useRef<HTMLDivElement>(null);

  const [label, setLabel] = useState('');
  const [text, setText] = useState('');
  const [color, setColor] = useState(PRESET_COLORS[4]!.value); // Blue default
  // M3 — assignee can now be re-assigned through this modal. Empty
  // string = clear (NULL on the wire). Loaded lazily only while the
  // modal is open so closed-page renders don't pay the /v1/users/ cost.
  const [assigneeId, setAssigneeId] = useState<string>('');
  // Issue-tracking fields, persisted in the markup's metadata. Empty string
  // = clear that key. "" priority means "no priority".
  const [priority, setPriority] = useState<MarkupPriority | ''>('');
  const [dueDate, setDueDate] = useState<string>('');

  const { data: users = [] } = useQuery({
    queryKey: ['markups', 'users'],
    queryFn: () =>
      fetchUsers({ is_active: true, limit: 200 }).catch(
        () => [] as AssigneeUser[],
      ),
    enabled: open,
    staleTime: 5 * 60_000,
  });

  // Reseed form whenever a different markup is opened.
  useEffect(() => {
    if (open && markup) {
      setLabel(markup.label ?? '');
      setText(markup.text ?? '');
      setColor(markup.color || PRESET_COLORS[4]!.value);
      setAssigneeId(markup.assignee_id ?? '');
      setPriority(getMarkupPriority(markup) ?? '');
      setDueDate(getMarkupDueDate(markup) ?? '');
    }
  }, [open, markup]);

  // Close on Escape — capture phase so it wins over inner inputs.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onClose]);

  // Close on backdrop click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onClose]);

  const updateMut = useMutation({
    mutationFn: (payload: UpdateMarkupPayload) => {
      if (!markup) throw new Error('No markup selected');
      return updateMarkup(markup.id, payload);
    },
    onSuccess: (updated) => {
      // Optimistic write-through so the row reflects the new label/color
      // before the network round-trip for the next list query resolves.
      const patchCache = (key: readonly unknown[]) => {
        qc.setQueriesData<Markup[] | undefined>({ queryKey: key }, (prev) => {
          if (!prev) return prev;
          return prev.map((m) => (m.id === updated.id ? { ...m, ...updated } : m));
        });
      };
      patchCache(['markups', projectId]);
      patchCache(['unified-markups', projectId, 'hub']);
      // Schedule a refetch so any filter-specific query keys catch up too.
      qc.invalidateQueries({ queryKey: ['markups'] });
      qc.invalidateQueries({ queryKey: ['unified-markups'] });

      addToast({
        type: 'success',
        title: t('markups.updated', { defaultValue: 'Markup updated' }),
      });
      onUpdated?.(updated);
      onClose();
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      });
    },
  });

  if (!open || !markup) return null;

  const trimmedLabel = label.trim();
  const trimmedText = text.trim();
  // Mirror the creation contract (AddMarkupModal): a markup is valid with
  // either a label or text. Requiring a label here used to lock text-only
  // markups out of editing entirely.
  const canSubmit = (trimmedLabel.length > 0 || trimmedText.length > 0) && !updateMut.isPending;

  const handleSubmit = () => {
    if (!canSubmit) return;
    const payload: UpdateMarkupPayload = {
      // Pass null (not "") when empty so the column is cleared to NULL
      // rather than stored as an empty string. The `text` and `label`
      // columns are nullable and the rest of the app treats NULL as
      // "no value". Sending undefined would mean "no change" in PATCH
      // semantics, so we send null explicitly to clear.
      label: trimmedLabel || null,
      text: trimmedText || null,
      color,
      // M3 — re-assign (or clear) the markup owner. Empty select value ⇒
      // null on the wire (Unassigned); a UUID sets the assignee.
      assignee_id: assigneeId || null,
      // Issue-tracking fields ride in metadata. The backend shallow-MERGES
      // this, so we only send these two keys and any linked ``punch_item_id``
      // survives. ``null`` clears a key; a value sets it.
      metadata: {
        priority: priority || null,
        due_date: dueDate || null,
      },
    };
    updateMut.mutate(payload);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('markups.editTitle', { defaultValue: 'Edit Markup' })}
        className="relative z-10 w-full max-w-lg mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-light">
          <h2 className="text-base font-semibold text-content-primary flex items-center gap-2">
            <Edit3 size={16} className="text-oe-blue" />
            {t('markups.editTitle', { defaultValue: 'Edit Markup' })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-md hover:bg-surface-secondary text-content-tertiary transition-colors"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {/* Title (label) */}
          <div>
            <label
              htmlFor="edit-markup-label"
              className="block text-xs font-medium text-content-secondary mb-1.5"
            >
              {t('markups.label_field', { defaultValue: 'Title' })}
            </label>
            <input
              id="edit-markup-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && canSubmit) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              placeholder={t('markups.label_placeholder', {
                defaultValue: 'Short label...',
              })}
              maxLength={255}
              autoFocus
              className={inputCls + ' w-full'}
            />
          </div>

          {/* Description (text) */}
          <div>
            <label
              htmlFor="edit-markup-text"
              className="block text-xs font-medium text-content-secondary mb-1.5"
            >
              {t('markups.text_field', { defaultValue: 'Description' })}
            </label>
            <textarea
              id="edit-markup-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t('markups.text_placeholder', {
                defaultValue: 'Annotation text...',
              })}
              rows={3}
              maxLength={10_000}
              className="w-full rounded-lg border border-border bg-surface-primary px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors resize-y"
            />
          </div>

          {/* Color */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1.5">
              {t('markups.color', { defaultValue: 'Color' })}
            </label>
            <div
              role="radiogroup"
              aria-label={t('markups.color', { defaultValue: 'Color' })}
              className="flex items-center gap-2"
            >
              {PRESET_COLORS.map((c) => {
                const selected = color.toLowerCase() === c.value.toLowerCase();
                return (
                  <button
                    key={c.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    aria-label={c.name}
                    onClick={() => setColor(c.value)}
                    title={c.name}
                    className={clsx(
                      'w-7 h-7 rounded-full border-2 transition-all',
                      selected
                        ? 'border-content-primary scale-110 ring-2 ring-offset-1 ring-oe-blue/40'
                        : 'border-transparent hover:scale-105',
                    )}
                    style={{ backgroundColor: c.value }}
                  />
                );
              })}
            </div>
          </div>

          {/* Assignee (M3) — re-assign the markup owner without losing the
              annotation's position on the document. */}
          <div>
            <label
              htmlFor="edit-markup-assignee"
              className="block text-xs font-medium text-content-secondary mb-1.5"
            >
              {t('markups.assignee', { defaultValue: 'Assignee' })}
            </label>
            <select
              id="edit-markup-assignee"
              value={assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              className={inputCls + ' w-full'}
            >
              <option value="">
                {t('markups.unassigned', { defaultValue: 'Unassigned' })}
              </option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.email}
                </option>
              ))}
            </select>
          </div>

          {/* Priority + Due date - turns a bare annotation into a tracked
              issue. Both are optional and stored in the markup's metadata. */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label
                htmlFor="edit-markup-priority"
                className="flex items-center gap-1 text-xs font-medium text-content-secondary mb-1.5"
              >
                <Flag size={12} />
                {t('markups.priority', { defaultValue: 'Priority' })}
              </label>
              <select
                id="edit-markup-priority"
                value={priority}
                onChange={(e) => setPriority(e.target.value as MarkupPriority | '')}
                className={inputCls + ' w-full'}
              >
                <option value="">
                  {t('markups.no_priority', { defaultValue: 'None' })}
                </option>
                {MARKUP_PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {t(`markups.priority_${p}`, { defaultValue: PRIORITY_LABELS[p] })}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label
                htmlFor="edit-markup-due"
                className="flex items-center gap-1 text-xs font-medium text-content-secondary mb-1.5"
              >
                <CalendarClock size={12} />
                {t('markups.due_date', { defaultValue: 'Due date' })}
              </label>
              <input
                id="edit-markup-due"
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className={inputCls + ' w-full'}
              />
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light">
          {!trimmedLabel && !trimmedText && (
            <span className="mr-auto text-2xs text-content-tertiary">
              {t('markups.label_or_text_required', {
                defaultValue: 'Enter a title or description to save.',
              })}
            </span>
          )}
          <Button variant="ghost" size="sm" onClick={onClose} disabled={updateMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            loading={updateMut.isPending}
            disabled={!canSubmit}
            icon={<Edit3 size={14} />}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
