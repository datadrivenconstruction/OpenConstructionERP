// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Rename modal for a single document row.
 *
 * PATCHes ``/v1/documents/{id}`` with the new name (via
 * ``useRenameDocument``) and, on success, invalidates the file list + tree
 * queries so the label refreshes everywhere. Only the ``document`` kind is
 * backed by the documents table that owns the ``name`` column, so the
 * caller (context menu) already disables rename for other kinds; this
 * dialog additionally guards defensively.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, X } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import { useRenameDocument } from '../hooks';
import type { FileRow } from '../types';

interface RenameDialogProps {
  open: boolean;
  row: FileRow | null;
  projectId: string | null | undefined;
  onClose: () => void;
}

export function RenameDialog({ open, row, projectId, onClose }: RenameDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState('');
  const rename = useRenameDocument(projectId);

  // Seed the field with the current name each time the dialog opens for a
  // new row, and focus + select so the user can type over it immediately.
  useEffect(() => {
    if (!open || !row) return;
    setName(row.name);
    const handle = window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 30);
    return () => window.clearTimeout(handle);
  }, [open, row]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open || !row) return null;

  const trimmed = name.trim();
  const unchanged = trimmed === row.name.trim();
  const canSubmit =
    row.kind === 'document' && trimmed.length > 0 && !unchanged && !rename.isPending;

  const submit = () => {
    if (!canSubmit) return;
    rename.mutate(
      { documentId: row.id, name: trimmed },
      {
        onSuccess: () => {
          addToast({
            type: 'success',
            title: t('files.rename.done', { defaultValue: 'File renamed' }),
          });
          onClose();
        },
        onError: (err: unknown) =>
          addToast({
            type: 'error',
            title: t('files.rename.failed', { defaultValue: 'Could not rename the file' }),
            message: err instanceof Error ? err.message : String(err),
          }),
      },
    );
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('files.rename.title', { defaultValue: 'Rename file' })}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md mx-4 rounded-xl bg-surface-elevated shadow-2xl border border-border-light overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('files.rename.title', { defaultValue: 'Rename file' })}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={14} />
          </button>
        </div>

        <div className="p-5">
          <label
            htmlFor="file-rename-input"
            className="block text-xs font-medium text-content-secondary mb-1.5"
          >
            {t('files.rename.label', { defaultValue: 'File name' })}
          </label>
          <input
            id="file-rename-input"
            ref={inputRef}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                submit();
              }
            }}
            className="w-full h-9 px-3 text-sm rounded-lg border border-border-light bg-surface-primary text-content-primary placeholder:text-content-tertiary focus:outline-none focus:border-oe-blue focus:ring-2 focus:ring-oe-blue/20"
          />

          <div className="mt-4 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="inline-flex items-center h-9 px-3 rounded-lg text-xs font-medium border border-border-light text-content-secondary hover:bg-surface-secondary"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={!canSubmit}
              className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg text-xs font-semibold bg-oe-blue text-white hover:bg-oe-blue-hover disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {rename.isPending && <Loader2 size={13} className="animate-spin" />}
              {t('files.rename.save', { defaultValue: 'Save' })}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
