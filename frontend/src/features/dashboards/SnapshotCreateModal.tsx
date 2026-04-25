/**
 * Snapshot upload modal (T01).
 *
 * Multipart upload of 1..16 CAD/BIM files under a user-supplied label.
 * Backend validates format + size + label uniqueness and returns a
 * {@link SnapshotError} envelope on structured failures.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { UploadCloud, X, FileCog, Trash2 } from 'lucide-react';

import { Button, Input } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import { createSnapshot, type Snapshot, type SnapshotError } from './api';

const SUPPORTED_EXTENSIONS = ['ifc', 'rvt', 'dwg', 'dgn'] as const;
const MAX_BYTES = 200 * 1024 * 1024;
const MAX_FILES = 16;

export interface SnapshotCreateModalProps {
  projectId: string;
  onClose: () => void;
  onCreated: (snap: Snapshot) => void;
}

export function SnapshotCreateModal({
  projectId,
  onClose,
  onCreated,
}: SnapshotCreateModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [label, setLabel] = useState('');
  const [files, setFiles] = useState<File[]>([]);

  const invalidFiles = useMemo(() => {
    return files
      .map((f, i) => {
        const ext = f.name.split('.').pop()?.toLowerCase() ?? '';
        const badExt = !SUPPORTED_EXTENSIONS.includes(ext as (typeof SUPPORTED_EXTENSIONS)[number]);
        const badSize = f.size > MAX_BYTES;
        return badExt || badSize ? { index: i, badExt, badSize } : null;
      })
      .filter(Boolean) as Array<{ index: number; badExt: boolean; badSize: boolean }>;
  }, [files]);

  const canSubmit =
    label.trim().length > 0 &&
    files.length > 0 &&
    files.length <= MAX_FILES &&
    invalidFiles.length === 0;

  const mutation = useMutation({
    mutationFn: () => createSnapshot({ projectId, label: label.trim(), files }),
    onSuccess: (snap) => {
      queryClient.invalidateQueries({ queryKey: ['dashboards-snapshots', projectId] });
      onCreated(snap);
    },
    onError: (err: Error & { snapshotError?: SnapshotError }) => {
      toast({
        type: 'error',
        title: t('dashboards.snapshot_create_failed', {
          defaultValue: 'Snapshot upload failed',
        }),
        message: err.snapshotError?.message ?? err.message,
      });
    },
  });

  const pickFiles = useCallback((next: FileList | null) => {
    if (!next) return;
    setFiles((prev) => {
      const merged = [...prev];
      for (const f of Array.from(next)) {
        if (!merged.find((m) => m.name === f.name && m.size === f.size)) {
          merged.push(f);
        }
      }
      return merged.slice(0, MAX_FILES);
    });
  }, []);

  const removeFile = useCallback((idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const submit = () => {
    if (canSubmit) mutation.mutate();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="snapshot-create-modal"
    >
      <div className="w-full max-w-lg rounded-lg border border-border-light bg-surface-primary shadow-xl">
        <div className="flex items-center justify-between border-b border-border-light px-5 py-3">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('dashboards.create_snapshot', { defaultValue: 'Create snapshot' })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
            aria-label="close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-content-tertiary">
              {t('dashboards.snapshot_label', { defaultValue: 'Label' })}
            </span>
            <Input
              data-testid="snapshot-label-input"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('dashboards.snapshot_label_ph', {
                defaultValue: 'e.g. Issued-for-tender 2026-04',
              })}
              maxLength={200}
            />
          </label>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-content-tertiary">
                {t('dashboards.snapshot_files', { defaultValue: 'CAD / BIM files' })}
              </span>
              <span className="text-xs text-content-tertiary">
                {files.length} / {MAX_FILES}
              </span>
            </div>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="flex w-full items-center justify-center gap-2 rounded border border-dashed border-border-light px-3 py-4 text-sm text-content-tertiary hover:border-oe-blue/50 hover:text-content-secondary"
              data-testid="snapshot-pick-files"
            >
              <UploadCloud className="h-4 w-4" />
              {t('dashboards.snapshot_drop_hint', {
                defaultValue: 'Select IFC / RVT / DWG / DGN files',
              })}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".ifc,.rvt,.dwg,.dgn"
              className="hidden"
              onChange={(e) => pickFiles(e.target.files)}
              data-testid="snapshot-file-input"
            />

            {files.length > 0 && (
              <ul className="mt-2 space-y-1">
                {files.map((f, i) => {
                  const bad = invalidFiles.find((x) => x.index === i);
                  return (
                    <li
                      key={`${f.name}-${i}`}
                      className={`flex items-center gap-2 rounded border px-2 py-1 text-xs ${
                        bad
                          ? 'border-rose-400/50 bg-rose-50 text-rose-700'
                          : 'border-border-light bg-surface-secondary text-content-secondary'
                      }`}
                    >
                      <FileCog className="h-3 w-3 text-content-tertiary" />
                      <span className="flex-1 truncate">{f.name}</span>
                      <span className="tabular-nums text-content-tertiary">
                        {(f.size / (1024 * 1024)).toFixed(2)} MB
                      </span>
                      <button
                        type="button"
                        onClick={() => removeFile(i)}
                        className="text-content-tertiary hover:text-rose-500"
                        aria-label="remove"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}

            {invalidFiles.length > 0 && (
              <p className="mt-2 text-xs text-rose-600">
                {t('dashboards.snapshot_invalid_hint', {
                  defaultValue:
                    'Remove unsupported or oversized files (IFC/RVT/DWG/DGN only, ≤ 200 MB each).',
                })}
              </p>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-border-light px-5 py-3">
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            onClick={submit}
            disabled={!canSubmit || mutation.isPending}
            data-testid="snapshot-submit"
          >
            {mutation.isPending
              ? t('dashboards.snapshot_uploading', { defaultValue: 'Uploading…' })
              : t('dashboards.snapshot_create', { defaultValue: 'Create snapshot' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
