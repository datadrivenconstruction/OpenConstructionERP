/** Bulk-actions bar — visible when one or more files are selected.
 *
 * Bulk delete dispatches per-kind:
 *   - documents → POST /v1/documents/batch/delete/ (server-side batch)
 *   - everything else (photos, sheets, BIM models, DWG drawings, takeoff
 *     uploads, reports, markups) → DELETE one-id-at-a-time on the module's
 *     own per-id endpoint, in parallel.
 *
 * The toast surface reports a per-kind tally: how many files of each kind
 * were deleted, and — on partial failure — which kinds had errors so the
 * user can retry just those.
 *
 * Bulk download fans each selected row's existing ``download_url`` out to
 * the browser (staggered so the burst isn't throttled) - no new endpoint
 * needed. Bulk tag + transmittal are wired through the tag and transmittal
 * modules. Bulk move / reclassify is not yet possible because the file
 * manager exposes no cross-kind move endpoint.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient, useMutation } from '@tanstack/react-query';
import { Trash2, X, Loader2, Tag, Send, Download } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import { fileManagerKeys } from '../hooks';
import { bulkDeleteDocuments, deleteByKind, downloadProtectedFile } from '../api';
import type { FileKind, FileRow } from '../types';
import { softDelete } from '@/features/file-trash/api';
import { useRestoreFromTrash } from '@/features/file-trash/hooks';
import { showUndoDeleteToast } from '@/features/file-trash/UndoDeleteToast';
import type { TrashKind } from '@/features/file-trash/types';
import { BulkTagDrawer } from '@/features/file-tags/BulkTagDrawer';
import { NewTransmittalWizard } from '@/features/file-transmittals/NewTransmittalWizard';

interface BulkActionsBarProps {
  selectedRows: FileRow[];
  projectId: string;
  onClear: () => void;
}

interface PerKindResult {
  kind: FileKind;
  requested: number;
  deleted: number;
  failed: { id: string; message: string }[];
}

interface DispatchSummary {
  total: number;
  deleted: number;
  failed: number;
  perKind: PerKindResult[];
  /** Trash rows created — used to show the per-file Undo toast. */
  trashIds: { id: string; name: string; trashId: string }[];
}

/** Group selected rows by their file kind. Exported for the unit test. */
export function groupByKind(rows: FileRow[]): Map<FileKind, FileRow[]> {
  const out = new Map<FileKind, FileRow[]>();
  for (const row of rows) {
    const bucket = out.get(row.kind);
    if (bucket) {
      bucket.push(row);
    } else {
      out.set(row.kind, [row]);
    }
  }
  return out;
}

/**
 * Run the per-kind delete dispatch and tally results.
 *
 * - ``document`` rows are batch-deleted in one server round-trip.
 * - All other kinds loop client-side with ``Promise.allSettled`` so a
 *   404 on one id doesn't abort siblings.
 *
 * Returns the same summary shape the toast renderer consumes.
 */
export async function dispatchBulkDelete(
  rows: FileRow[],
  projectId: string,
): Promise<DispatchSummary> {
  const groups = groupByKind(rows);
  const perKind: PerKindResult[] = [];
  const trashIds: { id: string; name: string; trashId: string }[] = [];

  for (const [kind, items] of groups) {
    const ids = items.map((r) => r.id);

    // W2 — soft-delete: every row passes through the recycle bin so an
    // accidental purge is recoverable for 30 days. The trash service
    // snapshots the row and flags the original as is_trashed in one
    // call.
    const settled = await Promise.allSettled(
      items.map((row) =>
        softDelete({
          project_id: projectId,
          kind: kind as TrashKind,
          original_id: row.id,
          canonical_name: row.name,
        }),
      ),
    );
    const failed: { id: string; message: string }[] = [];
    settled.forEach((res, idx) => {
      if (res.status === 'rejected') {
        failed.push({
          id: ids[idx]!,
          message: res.reason instanceof Error ? res.reason.message : String(res.reason),
        });
      } else {
        trashIds.push({
          id: ids[idx]!,
          name: items[idx]!.name,
          trashId: res.value.id,
        });
      }
    });
    perKind.push({
      kind,
      requested: ids.length,
      deleted: ids.length - failed.length,
      failed,
    });
  }

  const total = perKind.reduce((acc, r) => acc + r.requested, 0);
  const deleted = perKind.reduce((acc, r) => acc + r.deleted, 0);
  const failed = perKind.reduce((acc, r) => acc + r.failed.length, 0);
  return { total, deleted, failed, perKind, trashIds };
}

/** Legacy hard-delete path — kept around so tests + admin tools that
 *  bypass the recycle bin can still wipe rows. Not used in the normal
 *  UI flow. */
export async function dispatchHardBulkDelete(rows: FileRow[]): Promise<DispatchSummary> {
  const groups = groupByKind(rows);
  const perKind: PerKindResult[] = [];

  for (const [kind, items] of groups) {
    const ids = items.map((r) => r.id);

    if (kind === 'document') {
      try {
        const resp = await bulkDeleteDocuments(ids);
        perKind.push({
          kind,
          requested: ids.length,
          deleted: resp.deleted,
          failed:
            resp.deleted < ids.length
              ? [
                  {
                    id: '*',
                    message: `${ids.length - resp.deleted} document(s) skipped (no access)`,
                  },
                ]
              : [],
        });
      } catch (err) {
        perKind.push({
          kind,
          requested: ids.length,
          deleted: 0,
          failed: ids.map((id) => ({
            id,
            message: err instanceof Error ? err.message : String(err),
          })),
        });
      }
      continue;
    }

    const settled = await Promise.allSettled(ids.map((id) => deleteByKind(kind, id)));
    const failed = settled.flatMap((res, idx) =>
      res.status === 'rejected'
        ? [
            {
              id: ids[idx]!,
              message: res.reason instanceof Error ? res.reason.message : String(res.reason),
            },
          ]
        : [],
    );
    perKind.push({
      kind,
      requested: ids.length,
      deleted: ids.length - failed.length,
      failed,
    });
  }

  const total = perKind.reduce((acc, r) => acc + r.requested, 0);
  const deleted = perKind.reduce((acc, r) => acc + r.deleted, 0);
  const failed = perKind.reduce((acc, r) => acc + r.failed.length, 0);
  return { total, deleted, failed, perKind, trashIds: [] };
}

/** Small delay between sequential downloads. Browsers throttle / drop
 *  rapid-fire programmatic downloads, so we pace them out. */
const DOWNLOAD_STAGGER_MS = 350;

/** Download every selected row that carries an addressable ``download_url``,
 *  staggered so the browser doesn't drop the burst. Each file is fetched WITH
 *  the bearer token (see ``downloadProtectedFile``) because the file endpoints
 *  are bearer-protected and a plain anchor navigation 401s. Returns how many
 *  were dispatched and how many had no URL to download. */
export async function dispatchBulkDownload(
  rows: FileRow[],
): Promise<{ dispatched: number; skipped: number }> {
  const downloadable = rows.filter((r) => Boolean(r.download_url));
  const skipped = rows.length - downloadable.length;
  let dispatched = 0;
  for (let i = 0; i < downloadable.length; i += 1) {
    const row = downloadable[i]!;
    try {
      await downloadProtectedFile(row.download_url as string, row.name);
      dispatched += 1;
    } catch {
      /* one failed file shouldn't abort the rest of the batch */
    }
    if (i < downloadable.length - 1) {
      await new Promise((resolve) => setTimeout(resolve, DOWNLOAD_STAGGER_MS));
    }
  }
  return { dispatched, skipped: skipped + (downloadable.length - dispatched) };
}

export function BulkActionsBar({ selectedRows, projectId, onClear }: BulkActionsBarProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [confirming, setConfirming] = useState(false);
  const [tagDrawerOpen, setTagDrawerOpen] = useState(false);
  const [transmittalOpen, setTransmittalOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);

  // Restore-from-trash mutation feeds the Undo toast.
  const restoreMutation = useRestoreFromTrash(projectId);

  // All 8 file kinds now have a delete endpoint — nothing is filtered out.
  const deletableRows = selectedRows;

  const deleteMutation = useMutation({
    mutationFn: async (rows: FileRow[]) => dispatchBulkDelete(rows, projectId),
    onSuccess: (summary: DispatchSummary) => {
      queryClient.invalidateQueries({ queryKey: [fileManagerKeys.tree, projectId] });
      queryClient.invalidateQueries({ queryKey: [fileManagerKeys.list, projectId] });

      // W2 — single-file delete shows the inline Undo toast; bulk uses
      // a summary toast that points to the Recycle Bin for fine-grained
      // restore.
      if (summary.trashIds.length === 1) {
        const only = summary.trashIds[0]!;
        showUndoDeleteToast({
          fileName: only.name,
          trashId: only.trashId,
          onUndo: (tid: string) => restoreMutation.mutate(tid),
          t,
        });
      } else if (summary.trashIds.length > 1) {
        addToast({
          type: 'info',
          title: t('files.trash.bulk_deleted', {
            defaultValue: '{{count}} file(s) moved to Recycle Bin',
            count: summary.trashIds.length,
          }),
          message: t('files.trash.bulk_deleted_hint', {
            defaultValue: 'Open the Recycle Bin to restore individual files.',
          }),
        });
      }

      if (summary.failed === 0) {
        // success path already covered by the trash toasts above; no
        // additional toast needed.
      } else if (summary.deleted === 0) {
        addToast({
          type: 'error',
          title: t('files.bulk.delete_failed', { defaultValue: 'Bulk delete failed' }),
          message: t('files.bulk.delete_all_failed', {
            defaultValue: 'None of the {{count}} selected file(s) could be deleted.',
            count: summary.total,
          }),
        });
      } else {
        addToast({
          type: 'warning',
          title: t('files.bulk.delete_partial', {
            defaultValue: '{{deleted}} of {{total}} deleted',
            deleted: summary.deleted,
            total: summary.total,
          }),
          message: t('files.bulk.delete_partial_detail', {
            defaultValue: '{{failed}} file(s) could not be deleted.',
            failed: summary.failed,
          }),
        });
      }
      setConfirming(false);
      onClear();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('files.bulk.delete_failed', { defaultValue: 'Bulk delete failed' }),
        message: err.message,
      });
      setConfirming(false);
    },
  });

  // Count how many of the selected rows actually have a download URL so the
  // button can disable + the toast can report what was skipped.
  const downloadableCount = selectedRows.filter((r) => Boolean(r.download_url)).length;

  const handleBulkDownload = async () => {
    if (downloading || downloadableCount === 0) return;
    setDownloading(true);
    try {
      const { dispatched, skipped } = await dispatchBulkDownload(selectedRows);
      if (dispatched === 0) {
        addToast({
          type: 'warning',
          title: t('files.bulk.download_none', {
            defaultValue: 'Nothing to download',
          }),
          message: t('files.bulk.download_none_detail', {
            defaultValue: 'None of the selected files expose a downloadable file.',
          }),
        });
      } else {
        addToast({
          type: 'success',
          title: t('files.bulk.download_started', {
            defaultValue: 'Downloading {{count}} file(s)',
            count: dispatched,
          }),
          message:
            skipped > 0
              ? t('files.bulk.download_skipped', {
                  defaultValue: '{{count}} file(s) had nothing to download and were skipped.',
                  count: skipped,
                })
              : undefined,
        });
      }
    } finally {
      setDownloading(false);
    }
  };

  if (selectedRows.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-border-light bg-oe-blue/5">
      <span className="text-xs font-medium text-content-primary">
        {t('files.bulk.n_selected', {
          defaultValue: '{{count}} selected',
          count: selectedRows.length,
        })}
      </span>

      <button
        type="button"
        onClick={onClear}
        className="text-2xs text-content-tertiary hover:text-content-primary underline-offset-2 hover:underline"
      >
        {t('files.bulk.clear', { defaultValue: 'Clear' })}
      </button>

      <div className="ms-auto flex items-center gap-2">
        {/* Bulk download: fans each selected file's download URL out to the
            browser, staggered so the burst isn't throttled. */}
        <button
          type="button"
          onClick={handleBulkDownload}
          disabled={downloading || downloadableCount === 0}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-medium border border-border-light text-content-secondary hover:bg-surface-secondary disabled:opacity-50 disabled:cursor-not-allowed"
          title={
            downloadableCount === 0
              ? t('files.bulk.download_none', { defaultValue: 'Nothing to download' })
              : t('files.bulk.download', { defaultValue: 'Download' })
          }
        >
          {downloading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
          {t('files.bulk.download', { defaultValue: 'Download' })}
          {downloadableCount > 0 && downloadableCount !== selectedRows.length && (
            <span className="tabular-nums opacity-70">{downloadableCount}</span>
          )}
        </button>

        {/* W4 — bulk-tag selected files. */}
        <button
          type="button"
          onClick={() => setTagDrawerOpen(true)}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-medium border border-border-light text-content-secondary hover:bg-surface-secondary"
        >
          <Tag size={13} />
          {t('files.tags.bulk.button', { defaultValue: 'Tag selected' })}
        </button>

        {/* W7 — Send transmittal for the selection. */}
        <button
          type="button"
          onClick={() => setTransmittalOpen(true)}
          disabled={selectedRows.length === 0}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-medium border border-border-light text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
        >
          <Send size={13} />
          {t('files.transmittals.send_action', { defaultValue: 'Send transmittal' })}
        </button>

        {confirming ? (
          <div className="flex items-center gap-2 animate-fade-in">
            <span className="text-2xs text-semantic-error font-medium">
              {t('files.bulk.confirm_delete', {
                defaultValue: 'Delete {{count}} file(s)?',
                count: deletableRows.length,
              })}
            </span>
            <button
              type="button"
              disabled={deleteMutation.isPending || deletableRows.length === 0}
              onClick={() => deleteMutation.mutate(deletableRows)}
              className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-2xs font-semibold bg-semantic-error text-white hover:opacity-90 disabled:opacity-50"
            >
              {deleteMutation.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Trash2 size={12} />
              )}
              {t('files.bulk.delete', { defaultValue: 'Delete' })}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="inline-flex items-center justify-center h-7 w-7 rounded-md text-content-tertiary hover:bg-surface-secondary"
              aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
            >
              <X size={12} />
            </button>
          </div>
        ) : (
          <button
            type="button"
            disabled={deletableRows.length === 0}
            onClick={() => setConfirming(true)}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-medium border border-border-light text-content-secondary hover:bg-surface-secondary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Trash2 size={13} />
            {t('files.bulk.delete', { defaultValue: 'Delete' })}
          </button>
        )}
      </div>

      {/* W4 — bulk tag operations drawer. */}
      <BulkTagDrawer
        open={tagDrawerOpen}
        onClose={() => setTagDrawerOpen(false)}
        projectId={projectId}
        selectedRows={selectedRows.map((r) => ({ id: r.id, kind: r.kind }))}
      />

      {/* W7 — transmittal wizard pre-populated with selection. */}
      <NewTransmittalWizard
        open={transmittalOpen}
        onClose={() => setTransmittalOpen(false)}
        projectId={projectId}
        preselectedItems={selectedRows.map((row) => ({
          file_kind: row.kind,
          file_id: row.id,
          canonical_name_snapshot: row.name,
        }))}
      />
    </div>
  );
}
