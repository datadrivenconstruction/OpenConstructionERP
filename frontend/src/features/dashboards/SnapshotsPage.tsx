/**
 * Snapshots list page (Dashboards T01).
 *
 * Lists every data snapshot for the active project and lets the user
 * create a new one from uploaded CAD/BIM files. A snapshot is the
 * frozen parquet dataset that later tasks (T02 auto-chart, T03
 * autocomplete, T04 filters, …) analyse.
 */
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Plus,
  Layers,
  Trash2,
  FolderOpen,
  FileSpreadsheet,
  Boxes,
} from 'lucide-react';

import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  EmptyState,
  Skeleton,
} from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import {
  deleteSnapshot,
  listSnapshots,
  type Snapshot,
  type SnapshotSummary,
} from './api';
import { SnapshotCreateModal } from './SnapshotCreateModal';

function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-US').format(n);
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export function SnapshotsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const toast = useToastStore((s) => s.addToast);

  const [createOpen, setCreateOpen] = useState(false);

  const snapshotsQuery = useQuery({
    queryKey: ['dashboards-snapshots', activeProjectId],
    queryFn: () => listSnapshots(activeProjectId!),
    enabled: !!activeProjectId,
  });

  const deleteMutation = useMutation({
    mutationFn: (snapshotId: string) => deleteSnapshot(snapshotId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['dashboards-snapshots', activeProjectId],
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

  const handleCreated = useCallback(
    (snap: Snapshot) => {
      setCreateOpen(false);
      toast({
        type: 'success',
        title: t('dashboards.snapshot_created', { defaultValue: 'Snapshot created' }),
        message: t('dashboards.snapshot_created_detail', {
          defaultValue: '{{entities}} entities · {{categories}} categories',
          entities: formatNumber(snap.total_entities),
          categories: formatNumber(snap.total_categories),
        }),
      });
    },
    [t, toast],
  );

  if (!activeProjectId) {
    return (
      <div className="space-y-4 p-4">
        <EmptyState
          icon={<FolderOpen className="h-10 w-10 text-neutral-500" />}
          title={t('dashboards.no_project_title', { defaultValue: 'Select a project first' })}
          description={t('dashboards.no_project_desc', {
            defaultValue:
              'Snapshots are scoped to a project. Pick one from the Projects page to continue.',
          })}
          action={
            <Link to="/projects">
              <Button>{t('common.browse_projects', { defaultValue: 'Browse projects' })}</Button>
            </Link>
          }
        />
      </div>
    );
  }

  const snapshots = snapshotsQuery.data?.items ?? [];

  return (
    <div className="space-y-4 p-4" data-testid="dashboards-snapshots-page">
      <Breadcrumb
        items={[
          { label: t('common.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('dashboards.snapshots', { defaultValue: 'Dashboards' }) },
        ]}
      />

      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold text-neutral-100">
            <Layers className="h-5 w-5 text-oe-blue" />
            {t('dashboards.snapshots_title', { defaultValue: 'Data snapshots' })}
          </h1>
          <p className="text-sm text-neutral-400">
            {activeProjectName || activeProjectId}
          </p>
        </div>
        <Button
          onClick={() => setCreateOpen(true)}
          data-testid="dashboards-new-snapshot-btn"
        >
          <Plus className="mr-1 h-4 w-4" />
          {t('dashboards.new_snapshot', { defaultValue: 'New snapshot' })}
        </Button>
      </header>

      {snapshotsQuery.isLoading && (
        <div className="grid gap-3 md:grid-cols-2">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      )}

      {snapshotsQuery.isError && (
        <Card>
          <div className="p-4 text-sm text-rose-300">
            {t('dashboards.snapshots_load_failed', {
              defaultValue: 'Could not load snapshots.',
            })}
          </div>
        </Card>
      )}

      {!snapshotsQuery.isLoading && !snapshotsQuery.isError && snapshots.length === 0 && (
        <EmptyState
          icon={<Boxes className="h-10 w-10 text-neutral-500" />}
          title={t('dashboards.no_snapshots_title', {
            defaultValue: 'No snapshots yet',
          })}
          description={t('dashboards.no_snapshots_desc', {
            defaultValue:
              'Upload IFC, RVT, DWG or DGN files to freeze a parquet dataset that later dashboards can query.',
          })}
          action={
            <Button
              onClick={() => setCreateOpen(true)}
              data-testid="dashboards-empty-new-snapshot-btn"
            >
              <Plus className="mr-1 h-4 w-4" />
              {t('dashboards.new_snapshot', { defaultValue: 'New snapshot' })}
            </Button>
          }
        />
      )}

      {snapshots.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {snapshots.map((s) => (
            <SnapshotCard
              key={s.id}
              snapshot={s}
              onDelete={() => deleteMutation.mutate(s.id)}
              deleting={deleteMutation.isPending && deleteMutation.variables === s.id}
            />
          ))}
        </div>
      )}

      {createOpen && (
        <SnapshotCreateModal
          projectId={activeProjectId}
          onClose={() => setCreateOpen(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}

interface SnapshotCardProps {
  snapshot: SnapshotSummary;
  onDelete: () => void;
  deleting: boolean;
}

function SnapshotCard({ snapshot, onDelete, deleting }: SnapshotCardProps) {
  const { t } = useTranslation();
  return (
    <Card className="overflow-hidden" data-testid={`snapshot-card-${snapshot.id}`}>
      <div className="flex flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="truncate text-sm font-semibold text-neutral-100">
              {snapshot.label}
            </h3>
            <p className="mt-0.5 text-xs text-neutral-500">
              {formatDate(snapshot.created_at)}
            </p>
          </div>
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            className="rounded p-1 text-neutral-500 hover:bg-rose-500/10 hover:text-rose-300 disabled:opacity-40"
            aria-label="delete"
            data-testid={`snapshot-delete-${snapshot.id}`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded bg-neutral-800/60 px-2 py-1">
            <div className="text-neutral-500">
              {t('dashboards.entities', { defaultValue: 'Entities' })}
            </div>
            <div className="tabular-nums font-medium text-neutral-100">
              {formatNumber(snapshot.total_entities)}
            </div>
          </div>
          <div className="rounded bg-neutral-800/60 px-2 py-1">
            <div className="text-neutral-500">
              {t('dashboards.categories', { defaultValue: 'Categories' })}
            </div>
            <div className="tabular-nums font-medium text-neutral-100">
              {formatNumber(snapshot.total_categories)}
            </div>
          </div>
        </div>
        {Object.keys(snapshot.summary_stats ?? {}).length > 0 && (
          <div className="flex flex-wrap gap-1">
            {Object.entries(snapshot.summary_stats)
              .slice(0, 6)
              .map(([k, v]) => (
                <Badge key={k} variant="neutral">
                  <FileSpreadsheet className="mr-1 h-3 w-3" />
                  {k}: {formatNumber(v)}
                </Badge>
              ))}
          </div>
        )}
      </div>
    </Card>
  );
}
