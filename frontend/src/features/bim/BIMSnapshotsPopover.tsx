/**
 * BIMSnapshotsPopover — data-snapshot registry surfaced inside the BIM
 * viewer.
 *
 * Relocated here from the standalone /dashboards page because frozen
 * project datasets belong next to the BIM workspace where the estimator
 * actually works with the model. The popover lists every snapshot for
 * the active project with quick create / delete, and the existing
 * upload modal is reused verbatim so we don't duplicate validation.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, X, Layers, Inbox } from 'lucide-react';

import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import {
  deleteSnapshot,
  listSnapshots,
  SnapshotCreateModal,
  type Snapshot,
  type SnapshotSummary,
} from '@/features/dashboards';

interface BIMSnapshotsPopoverProps {
  projectId: string;
  onClose: () => void;
}

function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-US').format(n);
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default function BIMSnapshotsPopover({
  projectId,
  onClose,
}: BIMSnapshotsPopoverProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const [createOpen, setCreateOpen] = useState(false);

  const query = useQuery({
    queryKey: ['dashboards-snapshots', projectId],
    queryFn: () => listSnapshots(projectId),
    enabled: !!projectId,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSnapshot(id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['dashboards-snapshots', projectId],
      });
      toast({
        type: 'success',
        title: t('dashboards.snapshot_deleted', { defaultValue: 'Snapshot deleted' }),
      });
    },
    onError: (err: Error) => {
      toast({
        type: 'error',
        title: t('dashboards.snapshot_delete_failed', {
          defaultValue: 'Failed to delete snapshot',
        }),
        message: err.message,
      });
    },
  });

  const handleCreated = (snap: Snapshot) => {
    setCreateOpen(false);
    toast({
      type: 'success',
      title: t('dashboards.snapshot_created', { defaultValue: 'Snapshot created' }),
      message: `${formatNumber(snap.total_entities)} entities · ${formatNumber(
        snap.total_categories,
      )} categories`,
    });
  };

  const items = query.data?.items ?? [];

  return (
    <>
      <div
        className="fixed inset-0 z-[45]"
        onClick={onClose}
        data-testid="bim-snapshots-backdrop"
      />
      <div
        className="absolute right-4 top-16 z-[46] w-[380px] max-h-[70vh] overflow-hidden rounded-lg border border-border-light bg-surface-primary shadow-xl flex flex-col"
        data-testid="bim-snapshots-popover"
      >
        <div className="flex items-center justify-between border-b border-border-light px-3 py-2">
          <div className="flex items-center gap-2">
            <Layers size={14} className="text-oe-blue" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('dashboards.snapshots_title', { defaultValue: 'Data snapshots' })}
            </h3>
            {items.length > 0 && (
              <span className="rounded-full bg-surface-secondary px-1.5 py-0.5 text-[10px] tabular-nums text-content-tertiary">
                {items.length}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={14} />
          </button>
        </div>

        <div className="border-b border-border-light px-3 py-2">
          <Button
            onClick={() => setCreateOpen(true)}
            data-testid="bim-snapshot-create-btn"
          >
            <Plus size={14} className="mr-1" />
            {t('dashboards.new_snapshot', { defaultValue: 'New snapshot' })}
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {query.isLoading && (
            <div className="p-4 text-xs text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          )}
          {query.isError && (
            <div className="p-4 text-xs text-rose-600">
              {t('dashboards.snapshots_load_failed', {
                defaultValue: 'Could not load snapshots.',
              })}
            </div>
          )}
          {!query.isLoading && !query.isError && items.length === 0 && (
            <div className="flex flex-col items-center gap-2 p-6 text-center">
              <Inbox size={28} className="text-content-tertiary" />
              <p className="text-xs text-content-tertiary">
                {t('dashboards.no_snapshots_desc', {
                  defaultValue:
                    'Upload IFC, RVT, DWG or DGN files to freeze a parquet dataset.',
                })}
              </p>
            </div>
          )}
          {items.length > 0 && (
            <ul className="divide-y divide-border-light">
              {items.map((s) => (
                <SnapshotRow
                  key={s.id}
                  snapshot={s}
                  onDelete={() => deleteMutation.mutate(s.id)}
                  deleting={
                    deleteMutation.isPending && deleteMutation.variables === s.id
                  }
                />
              ))}
            </ul>
          )}
        </div>
      </div>

      {createOpen && (
        <SnapshotCreateModal
          projectId={projectId}
          onClose={() => setCreateOpen(false)}
          onCreated={handleCreated}
        />
      )}
    </>
  );
}

interface SnapshotRowProps {
  snapshot: SnapshotSummary;
  onDelete: () => void;
  deleting: boolean;
}

function SnapshotRow({ snapshot, onDelete, deleting }: SnapshotRowProps) {
  const { t } = useTranslation();
  return (
    <li
      className="flex items-center gap-2 px-3 py-2 hover:bg-surface-secondary"
      data-testid={`bim-snapshot-row-${snapshot.id}`}
    >
      <div className="flex-1 min-w-0">
        <div className="truncate text-xs font-medium text-content-primary">
          {snapshot.label}
        </div>
        <div className="flex items-center gap-2 mt-0.5 text-[10px] text-content-tertiary">
          <span className="tabular-nums">
            {formatNumber(snapshot.total_entities)}{' '}
            {t('dashboards.entities_short', { defaultValue: 'entities' })}
          </span>
          <span>·</span>
          <span className="tabular-nums">
            {snapshot.total_categories}{' '}
            {t('dashboards.categories_short', { defaultValue: 'cat.' })}
          </span>
          <span>·</span>
          <span>{formatDate(snapshot.created_at)}</span>
        </div>
      </div>
      <button
        type="button"
        onClick={onDelete}
        disabled={deleting}
        className="rounded p-1 text-content-tertiary hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40"
        aria-label={t('common.delete', { defaultValue: 'Delete' })}
        data-testid={`bim-snapshot-delete-${snapshot.id}`}
      >
        <Trash2 size={12} />
      </button>
    </li>
  );
}
