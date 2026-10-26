// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CreateBranchDialog — fork a branch (variant) from the open estimate, either
 * from its current state or from one of its saved snapshots.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { GitBranch, X } from 'lucide-react';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { useToastStore } from '@/stores/useToastStore';
import { fmtDate } from '@/shared/lib/formatters';
import { boqApi } from '../api';
import { branchApi } from './branchApi';

export interface CreateBranchDialogProps {
  sourceBoqId: string;
  sourceName: string;
  isOpen: boolean;
  onClose: () => void;
  onCreated: (branchId: string) => void;
}

export function CreateBranchDialog({ sourceBoqId, sourceName, isOpen, onClose, onCreated }: CreateBranchDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const panelRef = useRef<HTMLDivElement>(null);
  useFocusTrap(panelRef, isOpen);
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const [snapshotId, setSnapshotId] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    setName('');
    setNote('');
    setSnapshotId('');
  }, [isOpen]);

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

  const { data: snapshots } = useQuery({
    queryKey: ['boq-snapshots', sourceBoqId],
    queryFn: () => boqApi.getSnapshots(sourceBoqId),
    enabled: isOpen && !!sourceBoqId,
  });

  const mutation = useMutation({
    mutationFn: () =>
      branchApi.create(sourceBoqId, {
        name: name.trim(),
        note: note.trim(),
        snapshot_id: snapshotId || null,
      }),
    onSuccess: (boq) => {
      queryClient.invalidateQueries({ queryKey: ['boq-branches'] });
      addToast({ type: 'success', title: t('boq.branch.created', { defaultValue: 'Branch created' }) });
      onCreated(boq.id);
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('boq.branch.create_failed', { defaultValue: 'Could not create the branch' }),
        message: err.message,
      });
    },
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-label={t('boq.branch.create_title', { defaultValue: 'New branch' })}
        className="relative z-10 w-full max-w-md mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in focus:outline-none"
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
              <GitBranch size={16} />
            </span>
            <h2 className="text-base font-semibold text-content-primary">
              {t('boq.branch.create_title', { defaultValue: 'New branch' })}
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
          <p className="text-xs text-content-secondary leading-relaxed">
            {t('boq.branch.create_intro', {
              defaultValue:
                'A branch is a full copy of "{{name}}" you can change on its own. Compare it later, carry single positions across, or merge it back as the main estimate.',
              name: sourceName,
            })}
          </p>
          <label className="block">
            <span className="text-xs font-medium text-content-secondary">
              {t('boq.branch.name_label', { defaultValue: 'Branch name' })}
            </span>
            <input
              autoFocus
              type="text"
              value={name}
              maxLength={255}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('boq.branch.name_placeholder', { defaultValue: 'e.g. Alternative with precast' })}
              className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-content-secondary">
              {t('boq.branch.from_label', { defaultValue: 'Start from' })}
            </span>
            <select
              value={snapshotId}
              onChange={(e) => setSnapshotId(e.target.value)}
              className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            >
              <option value="">{t('boq.branch.from_current', { defaultValue: 'Current state' })}</option>
              {(snapshots ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {t('boq.branch.from_snapshot', {
                    defaultValue: 'Snapshot: {{name}} ({{date}})',
                    name: s.name,
                    date: fmtDate(s.created_at),
                  })}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-content-secondary">
              {t('boq.branch.note_label', { defaultValue: 'Note (optional)' })}
            </span>
            <textarea
              value={note}
              maxLength={4000}
              rows={2}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t('boq.branch.note_placeholder', { defaultValue: 'What does this variant test?' })}
              className="mt-1 w-full rounded-md border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
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
            disabled={mutation.isPending || !name.trim()}
            className="flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <GitBranch size={15} />
            {mutation.isPending
              ? t('boq.branch.creating', { defaultValue: 'Creating...' })
              : t('boq.branch.create_button', { defaultValue: 'Create branch' })}
          </button>
        </div>
      </div>
    </div>
  );
}
