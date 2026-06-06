/**
 * Snapshots list page (Dashboards T01).
 *
 * Lists every data snapshot for the active project and lets the user
 * create a new one from uploaded CAD/BIM files. A snapshot is the
 * frozen parquet dataset that later tasks (T02 auto-chart, T03
 * autocomplete, T04 filters, …) analyse.
 */
import { useCallback, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import {
  Plus,
  Trash2,
  FolderOpen,
  FileSpreadsheet,
  Boxes,
  List,
  GitCompare,
  History,
  Calculator,
  Ruler,
} from 'lucide-react';

import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  EmptyState,
  Skeleton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DismissibleInfo, IntroRichText } from '@/shared/ui/DismissibleInfo';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import {
  deleteSnapshot,
  listSnapshots,
  type Snapshot,
  type SnapshotSummary,
} from './api';
import { SnapshotCreateModal } from './SnapshotCreateModal';
import { SnapshotTimeline } from './SnapshotTimeline';
import { SnapshotDiffView } from './SnapshotDiffView';

type DashboardsView = 'list' | 'timeline' | 'diff';

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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const toast = useToastStore((s) => s.addToast);

  const [createOpen, setCreateOpen] = useState(false);
  const [view, setView] = useState<DashboardsView>('list');
  // Diff view: the two snapshots the user wants to compare (older A, newer B).
  const [diffA, setDiffA] = useState<string>('');
  const [diffB, setDiffB] = useState<string>('');

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
      <div className="space-y-5 animate-fade-in">
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
    <div className="space-y-5 animate-fade-in" data-testid="dashboards-snapshots-page">
      <Breadcrumb
        items={[
          ...(activeProjectName
            ? [{ label: activeProjectName, to: `/projects/${activeProjectId}` }]
            : []),
          { label: t('nav.snapshots', { defaultValue: 'Snapshots' }) },
        ]}
      />

      {/* Header — module name + icon live in the global top bar; this page
          renders only the muted subtitle + actions (canon §2). */}
      <PageHeader
        srTitle={t('dashboards.snapshots_title', { defaultValue: 'Data snapshots' })}
        subtitle={t('dashboards.snapshots_subtitle', {
          defaultValue:
            'Freeze a parquet dataset from your CAD/BIM files, then compare snapshots over time.',
        })}
        actions={
          <>
            <div className="flex rounded-lg border border-border-light p-0.5" role="tablist">
              <ViewTab
                active={view === 'list'}
                onClick={() => setView('list')}
                icon={<List className="h-3.5 w-3.5" />}
                label={t('dashboards.view_list', { defaultValue: 'Snapshots' })}
                testId="dashboards-view-list"
              />
              <ViewTab
                active={view === 'timeline'}
                onClick={() => setView('timeline')}
                icon={<History className="h-3.5 w-3.5" />}
                label={t('dashboards.view_timeline', { defaultValue: 'Timeline' })}
                testId="dashboards-view-timeline"
              />
              <ViewTab
                active={view === 'diff'}
                onClick={() => setView('diff')}
                icon={<GitCompare className="h-3.5 w-3.5" />}
                label={t('dashboards.view_diff', { defaultValue: 'Compare' })}
                testId="dashboards-view-diff"
              />
            </div>
            {view === 'list' && (
              <Button
                size="sm"
                icon={<Plus className="h-3.5 w-3.5" />}
                onClick={() => setCreateOpen(true)}
                data-testid="dashboards-new-snapshot-btn"
              >
                {t('dashboards.new_snapshot', { defaultValue: 'New snapshot' })}
              </Button>
            )}
          </>
        }
      />

      <DismissibleInfo
        storageKey="dashboards"
        title={t('dashboards.intro_title', {
          defaultValue: 'Freeze the model so changes are provable',
        })}
        more={
          t('dashboards.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('dashboards.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.data_explorer', { defaultValue: 'Data Explorer' }),
            onClick: () => navigate('/data-explorer'),
          },
          {
            label: t('nav.bim', { defaultValue: 'BIM' }),
            onClick: () => navigate('/bim'),
          },
          {
            // The frozen element/category dataset is the same model a
            // user prices in CAD-BIM Match -> Cost. Carry the active
            // project so the wizard lands on the right project (it reads
            // ?project=). The match wizard sources from BIM models, not
            // the parquet snapshot itself, so this is a navigation tie,
            // not a data import.
            label: t('nav.match_elements', { defaultValue: 'CAD-BIM Match → Cost' }),
            onClick: () =>
              navigate(`/match-elements?project=${encodeURIComponent(activeProjectId)}`),
          },
          {
            // PDF Takeoff is the other quantity source feeding the BOQ.
            // Takeoff scopes to the globally active project (project
            // context store), so no project param is needed; ?tab= is the
            // consumed deep-link param.
            label: t('nav.takeoff', { defaultValue: 'PDF Takeoff' }),
            onClick: () => navigate('/takeoff?tab=documents'),
          },
        ]}
      >
        {t('dashboards.intro_body', {
          defaultValue:
            'Pick a project, then freeze its uploaded IFC, RVT, DWG or DGN files into a dated parquet snapshot of every element and category. Compare two snapshots side by side to see exactly what changed between model revisions, and use the timeline to track growth over time. The frozen dataset is what later charts and the Data Explorer query.',
        })}
      </DismissibleInfo>

      {view === 'timeline' && (
        <SnapshotTimeline projectId={activeProjectId} />
      )}

      {view === 'diff' && (
        <div className="space-y-3">
          <Card>
            <div className="grid gap-3 p-4 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-xs font-medium text-neutral-400">
                  {t('dashboards.diff_pick_a', { defaultValue: 'Older snapshot (A)' })}
                </span>
                <select
                  value={diffA}
                  onChange={(e) => setDiffA(e.target.value)}
                  data-testid="dashboards-diff-a"
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
                >
                  <option value="">
                    {t('dashboards.diff_pick_placeholder', { defaultValue: 'Select a snapshot…' })}
                  </option>
                  {snapshots.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-neutral-400">
                  {t('dashboards.diff_pick_b', { defaultValue: 'Newer snapshot (B)' })}
                </span>
                <select
                  value={diffB}
                  onChange={(e) => setDiffB(e.target.value)}
                  data-testid="dashboards-diff-b"
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
                >
                  <option value="">
                    {t('dashboards.diff_pick_placeholder', { defaultValue: 'Select a snapshot…' })}
                  </option>
                  {snapshots.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </Card>
          {diffA && diffB && diffA !== diffB ? (
            <SnapshotDiffView snapshotAId={diffA} snapshotBId={diffB} />
          ) : (
            <EmptyState
              icon={<GitCompare className="h-10 w-10 text-neutral-500" />}
              title={t('dashboards.diff_pick_two_title', {
                defaultValue: 'Pick two snapshots to compare',
              })}
              description={t('dashboards.diff_pick_two_desc', {
                defaultValue:
                  'Select an older and a newer snapshot above to see the schema-level changes between them.',
              })}
            />
          )}
        </div>
      )}

      {view === 'list' && (
        <>

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
              onMatchToCost={() =>
                navigate(`/match-elements?project=${encodeURIComponent(activeProjectId)}`)
              }
              onTakeoff={() => navigate('/takeoff?tab=documents')}
            />
          ))}
        </div>
      )}
        </>
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

interface ViewTabProps {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
  testId: string;
}

function ViewTab({ active, onClick, icon, label, testId }: ViewTabProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      data-testid={testId}
      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
        active
          ? 'bg-oe-blue text-white'
          : 'text-neutral-400 hover:bg-neutral-800/60 hover:text-neutral-200'
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

interface SnapshotCardProps {
  snapshot: SnapshotSummary;
  onDelete: () => void;
  deleting: boolean;
  /** Deep link to CAD-BIM Match -> Cost for this snapshot's project. */
  onMatchToCost: () => void;
  /** Deep link to PDF Takeoff (project comes from global context). */
  onTakeoff: () => void;
}

function SnapshotCard({
  snapshot,
  onDelete,
  deleting,
  onMatchToCost,
  onTakeoff,
}: SnapshotCardProps) {
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
        {/* Use-this-snapshot deep links (CONN-73). The frozen dataset is
            the model a user prices in matching or measures off in
            takeoff; surface both quantity flows straight from the card so
            the snapshot is not a dead end. */}
        <div className="flex flex-wrap gap-2 border-t border-neutral-800/60 pt-3">
          <button
            type="button"
            onClick={onMatchToCost}
            data-testid={`snapshot-match-${snapshot.id}`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-neutral-200 transition-colors hover:bg-oe-blue/10 hover:text-oe-blue"
          >
            <Calculator className="h-3.5 w-3.5" />
            {t('dashboards.snapshot_match_to_cost', {
              defaultValue: 'Match to cost',
            })}
          </button>
          <button
            type="button"
            onClick={onTakeoff}
            data-testid={`snapshot-takeoff-${snapshot.id}`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-neutral-200 transition-colors hover:bg-oe-blue/10 hover:text-oe-blue"
          >
            <Ruler className="h-3.5 w-3.5" />
            {t('dashboards.snapshot_takeoff', { defaultValue: 'Takeoff' })}
          </button>
        </div>
      </div>
    </Card>
  );
}
