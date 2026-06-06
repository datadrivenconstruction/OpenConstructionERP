/**
 * Takt / Line-of-Balance scheduling page.
 *
 * Standalone surface under /takt. Pick a project and master schedule, create
 * takt schedules with a location sequence, import trade activities, then
 * compute the line-of-balance to see the diagonal "marching" diagram, the
 * crew-flow view and any takt-rhythm violations.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Plus,
  Trash2,
  PlayCircle,
  AlertTriangle,
  Download,
  LayoutList,
  GitBranch,
  Users,
  Layers,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  DismissibleInfo,
  IntroRichText,
  RecoveryCard,
  SkeletonTable,
  WideModal,
  ConfirmDialog,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
import { LineOfBalanceView } from './LineOfBalanceView';
import { TaktCrewFlowView } from './TaktCrewFlowView';
import {
  listMasterSchedules,
  listTaktSchedules,
  createTaktSchedule,
  deleteTaktSchedule,
  listTaktActivities,
  importTaktActivities,
  deleteTaktActivity,
  updateTaktActivity,
  computeLOB,
  type MasterSchedule,
  type TaktSchedule,
  type TaktActivity,
  type LineOfBalance,
  type TaktLocationInput,
  type TaktActivityInput,
} from './api';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

type LobView = 'lob' | 'crew';

export function TaktSchedulePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [projectId, setProjectId] = useState('');
  const [masterId, setMasterId] = useState('');
  const [taktId, setTaktId] = useState('');
  const [view, setView] = useState<LobView>('lob');
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [deleteTakt, setDeleteTakt] = useState<TaktSchedule | null>(null);
  const [lob, setLob] = useState<LineOfBalance | null>(null);

  const projectsQ = useQuery({
    queryKey: ['projects-list-for-takt'],
    queryFn: () => projectsApi.list(),
  });

  // Project selection lives in the global top-bar selector. Follow the
  // active project; fall back to the first project only when nothing is
  // active yet. Reset dependent selections whenever the project changes.
  useEffect(() => {
    const next = activeProjectId || projectsQ.data?.[0]?.id || '';
    if (!next || next === projectId) return;
    setProjectId(next);
    setMasterId('');
    setTaktId('');
  }, [activeProjectId, projectsQ.data, projectId]);

  const masterQ = useQuery({
    queryKey: ['takt', 'masters', projectId],
    queryFn: () => listMasterSchedules({ project_id: projectId, limit: 100 }),
    enabled: !!projectId,
  });

  useEffect(() => {
    if (!masterId && masterQ.data && masterQ.data.length > 0) {
      const first = masterQ.data[0];
      if (first) setMasterId(first.id);
    }
  }, [masterId, masterQ.data]);

  const taktQ = useQuery({
    queryKey: ['takt', 'schedules', masterId],
    queryFn: () => listTaktSchedules(masterId),
    enabled: !!masterId,
  });

  useEffect(() => {
    // Reset the LOB and selection whenever the underlying takt list changes
    // owner so we never show a chart for a different schedule.
    setLob(null);
  }, [taktId]);

  useEffect(() => {
    if (!taktId && taktQ.data && taktQ.data.length > 0) {
      const first = taktQ.data[0];
      if (first) setTaktId(first.id);
    }
  }, [taktId, taktQ.data]);

  const activitiesQ = useQuery({
    queryKey: ['takt', 'activities', taktId],
    queryFn: () => listTaktActivities(taktId),
    enabled: !!taktId,
  });

  const currentTakt: TaktSchedule | undefined = useMemo(
    () => (taktQ.data ?? []).find((ts) => ts.id === taktId),
    [taktQ.data, taktId],
  );

  const computeMut = useMutation({
    mutationFn: (id: string) => computeLOB(id),
    onSuccess: (data) => {
      setLob(data);
      addToast({
        type: 'success',
        title: t('takt.lob_computed', { defaultValue: 'Line-of-balance computed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteTaktMut = useMutation({
    mutationFn: (id: string) => deleteTaktSchedule(id),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ['takt', 'schedules', masterId] });
      if (id === taktId) setTaktId('');
      setDeleteTakt(null);
      addToast({
        type: 'success',
        title: t('takt.deleted', { defaultValue: 'Takt schedule deleted' }),
      });
    },
    onError: (err) => {
      setDeleteTakt(null);
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  const exportPDF = () => {
    // Deterministic, dependency-free: the browser's print dialog renders the
    // currently-visible chart + summary. The print stylesheet (global) hides
    // chrome; users pick "Save as PDF". No server round-trip needed.
    window.print();
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[{ label: t('nav.takt', { defaultValue: 'Takt Planning' }) }]}
      />

      <PageHeader
        srTitle={t('nav.takt', { defaultValue: 'Takt Planning' })}
        subtitle={t('takt.subtitle', {
          defaultValue:
            'Line-of-balance scheduling for repetitive work, cycling a crew through a sequence of locations at a steady takt rhythm.',
        })}
        actions={
          <Button
            variant="primary"
            icon={<Plus size={14} />}
            onClick={() => setCreateOpen(true)}
            disabled={!masterId}
          >
            {t('takt.new_takt_schedule', { defaultValue: 'New Takt Schedule' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="takt"
        title={t('takt.intro_title', {
          defaultValue: 'Keep crews flowing, not waiting',
        })}
        more={
          t('takt.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('takt.intro_more')} />
            : undefined
        }
        links={[
          { label: t('takt.intro_link_advanced', { defaultValue: 'Last Planner' }), onClick: () => navigate('/schedule-advanced') },
          { label: t('takt.intro_link_schedule', { defaultValue: '4D Schedule' }), onClick: () => navigate('/schedule') },
        ]}
      >
        {t('takt.intro_body', {
          defaultValue:
            'Pick a project and master schedule, set a sequence of locations, then import trade activities and compute the line of balance. You get the marching diagram, a crew-flow view and any takt-rhythm violations, so trades hand off zone to zone at a steady beat instead of colliding.',
        })}
      </DismissibleInfo>

      {!projectId ? (
        <Card>
          {projectsQ.isLoading ? (
            <SkeletonTable rows={6} columns={3} />
          ) : projectsQ.isError ? (
            <RecoveryCard error={projectsQ.error} onRetry={() => projectsQ.refetch()} />
          ) : (
            <RequiresProject
              emptyHint={t('takt.no_project_desc', {
                defaultValue: 'Create a project first to start takt planning.',
              })}
            >
              {null}
            </RequiresProject>
          )}
        </Card>
      ) : masterQ.isLoading ? (
        <Card padding="md">
          <SkeletonTable rows={4} columns={3} />
        </Card>
      ) : masterQ.isError ? (
        <Card className="py-12">
          <RecoveryCard error={masterQ.error} onRetry={() => masterQ.refetch()} />
        </Card>
      ) : (masterQ.data ?? []).length === 0 ? (
        <Card>
          <EmptyState
            icon={<Layers size={22} />}
            title={t('takt.no_master', { defaultValue: 'No master schedule yet' })}
            description={t('takt.no_master_desc', {
              defaultValue:
                'A takt schedule hangs off a master schedule. Create one on the Advanced Schedule page first.',
            })}
            action={{
              label: t('takt.no_master_action', {
                defaultValue: 'Go to Advanced Schedule',
              }),
              onClick: () => navigate('/schedule-advanced'),
            }}
          />
        </Card>
      ) : (
        <div className="space-y-5">
          {/* Master + takt selector row */}
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className={labelCls}>
                {t('takt.master', { defaultValue: 'Master schedule' })}
              </label>
              <select
                value={masterId}
                onChange={(e) => {
                  setMasterId(e.target.value);
                  setTaktId('');
                }}
                className={clsx(inputCls, 'min-w-[14rem]')}
              >
                {(masterQ.data ?? []).map((m: MasterSchedule) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>
                {t('takt.schedule', { defaultValue: 'Takt schedule' })}
              </label>
              <select
                value={taktId}
                onChange={(e) => setTaktId(e.target.value)}
                className={clsx(inputCls, 'min-w-[14rem]')}
                disabled={(taktQ.data ?? []).length === 0}
              >
                {(taktQ.data ?? []).length === 0 ? (
                  <option value="">
                    {t('takt.none', { defaultValue: '- none -' })}
                  </option>
                ) : (
                  (taktQ.data ?? []).map((ts) => (
                    <option key={ts.id} value={ts.id}>
                      {ts.name}
                    </option>
                  ))
                )}
              </select>
            </div>
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setCreateOpen(true)}
            >
              {t('takt.create', { defaultValue: 'New takt schedule' })}
            </Button>
            {currentTakt && (
              <Button
                variant="ghost"
                size="sm"
                icon={<Trash2 size={14} />}
                onClick={() => setDeleteTakt(currentTakt)}
              >
                {t('common.delete', { defaultValue: 'Delete' })}
              </Button>
            )}
          </div>

          {taktQ.isLoading ? (
            <Card padding="md">
              <SkeletonTable rows={4} columns={3} />
            </Card>
          ) : !currentTakt ? (
            <Card>
              <EmptyState
                icon={<GitBranch size={22} />}
                title={t('takt.no_takt', { defaultValue: 'No takt schedule yet' })}
                description={t('takt.no_takt_desc', {
                  defaultValue:
                    'Create a takt schedule with an ordered list of locations, then import the trade activities that cycle through them.',
                })}
                action={{
                  label: t('takt.create', { defaultValue: 'New takt schedule' }),
                  onClick: () => setCreateOpen(true),
                }}
              />
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_18rem]">
              <div className="space-y-4" id="takt-report">
                {/* Summary stat strip */}
                <Card padding="md">
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <Stat
                      label={t('takt.locations', { defaultValue: 'Locations' })}
                      value={currentTakt.location_sequence_count}
                    />
                    <Stat
                      label={t('takt.activities', { defaultValue: 'Activities' })}
                      value={activitiesQ.data?.length ?? 0}
                    />
                    <Stat
                      label={t('takt.targetCycleDays', { defaultValue: 'Target cycle' })}
                      value={`${currentTakt.target_cycle_days}d`}
                    />
                    <Stat
                      label={t('takt.makespan', { defaultValue: 'Makespan' })}
                      value={lob ? `${lob.total_makespan_days}d` : '—'}
                    />
                  </div>
                </Card>

                {/* Locations chips */}
                <Card padding="md">
                  <h3 className="mb-2 text-sm font-semibold">
                    {t('takt.location_sequence', { defaultValue: 'Location sequence' })}
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {currentTakt.locations
                      .slice()
                      .sort((a, b) => a.sequence_order - b.sequence_order)
                      .map((loc) => (
                        <span
                          key={loc.id}
                          className="inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-secondary px-2.5 py-1 text-xs"
                        >
                          <span className="text-content-tertiary tabular-nums">{loc.sequence_order}</span>
                          {loc.name}
                        </span>
                      ))}
                    {currentTakt.locations.length === 0 && (
                      <span className="text-xs text-content-tertiary">
                        {t('takt.no_locations', { defaultValue: 'No locations defined.' })}
                      </span>
                    )}
                  </div>
                </Card>

                {/* Activities */}
                <ActivitiesCard
                  taktId={taktId}
                  activities={activitiesQ.data ?? []}
                  loading={activitiesQ.isLoading}
                  isError={activitiesQ.isError}
                  error={activitiesQ.error}
                  onRetry={() => activitiesQ.refetch()}
                  onImport={() => setImportOpen(true)}
                />

                {/* Compute + view toggle + chart */}
                <Card padding="md">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="inline-flex rounded-lg border border-border-light bg-surface-secondary p-0.5">
                      <ViewToggle
                        active={view === 'lob'}
                        onClick={() => setView('lob')}
                        icon={<GitBranch size={12} />}
                        label={t('takt.lineOfBalance', { defaultValue: 'Line-of-Balance' })}
                      />
                      <ViewToggle
                        active={view === 'crew'}
                        onClick={() => setView('crew')}
                        icon={<Users size={12} />}
                        label={t('takt.crewFlow', { defaultValue: 'Crew Flow' })}
                      />
                    </div>
                    <div className="flex gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Download size={14} />}
                        onClick={exportPDF}
                        disabled={!lob}
                      >
                        {t('takt.export_pdf', { defaultValue: 'Export PDF' })}
                      </Button>
                      <Button
                        variant="primary"
                        size="sm"
                        icon={<PlayCircle size={14} />}
                        loading={computeMut.isPending}
                        disabled={(activitiesQ.data ?? []).length === 0}
                        onClick={() => computeMut.mutate(taktId)}
                      >
                        {t('takt.compute', { defaultValue: 'Compute' })}
                      </Button>
                    </div>
                  </div>

                  {!lob ? (
                    <div className="rounded-lg border border-dashed border-border-light bg-surface-secondary/40 p-8 text-center text-sm text-content-tertiary">
                      {(activitiesQ.data ?? []).length === 0
                        ? t('takt.add_activities_first', {
                            defaultValue: 'Import at least one activity, then compute the line-of-balance.',
                          })
                        : t('takt.click_compute', {
                            defaultValue: 'Click Compute to render the line-of-balance diagram.',
                          })}
                    </div>
                  ) : view === 'lob' ? (
                    <LineOfBalanceView lob={lob} />
                  ) : (
                    <TaktCrewFlowView lob={lob} />
                  )}
                </Card>
              </div>

              {/* Right rail — violations + critical path */}
              <aside className="space-y-4">
                <Card padding="md">
                  <h3 className="mb-2 text-sm font-semibold">
                    {t('takt.violations', { defaultValue: 'Violations' })}
                  </h3>
                  {!lob ? (
                    <p className="text-xs text-content-tertiary">
                      {t('takt.compute_to_see', { defaultValue: 'Compute to check the takt rhythm.' })}
                    </p>
                  ) : lob.violations.length === 0 ? (
                    <p className="text-xs text-emerald-600">
                      {t('takt.no_violations', { defaultValue: 'Takt rhythm is steady - no violations.' })}
                    </p>
                  ) : (
                    <ul className="space-y-2">
                      {lob.violations.map((v) => (
                        <li
                          key={`${v.activity_id}-${v.location_id ?? ''}`}
                          className={clsx(
                            'rounded-md border p-2 text-xs',
                            v.severity === 'error'
                              ? 'border-rose-300 bg-rose-500/10 text-rose-700 dark:text-rose-300'
                              : 'border-amber-300 bg-amber-500/10 text-amber-700 dark:text-amber-300',
                          )}
                        >
                          <div className="flex items-center gap-1 font-medium">
                            <AlertTriangle size={11} />
                            {v.activity_name} · {v.location_name}
                          </div>
                          <p className="mt-0.5 opacity-90">{v.message}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>

                {lob && (
                  <Card padding="md">
                    <h3 className="mb-2 text-sm font-semibold">
                      {t('takt.summary', { defaultValue: 'Summary' })}
                    </h3>
                    <dl className="space-y-1.5 text-xs">
                      <SummaryRow
                        label={t('takt.averageCycle', { defaultValue: 'Average cycle' })}
                        value={`${lob.average_cycle_days}d`}
                      />
                      <SummaryRow
                        label={t('takt.tolerance', { defaultValue: 'Rhythm tolerance' })}
                        value={`±${currentTakt.takt_rhythm_tolerance_days}d`}
                      />
                      <SummaryRow
                        label={t('takt.criticalPath', { defaultValue: 'Critical trade' })}
                        value={
                          lob.critical_path.length > 0
                            ? (lob.bars.find((b) => b.activity_id === lob.critical_path[0])?.activity_name ??
                              `${lob.critical_path.length}`)
                            : '—'
                        }
                      />
                    </dl>
                  </Card>
                )}
              </aside>
            </div>
          )}
        </div>
      )}

      {/* Modals */}
      {createOpen && masterId && (
        <CreateTaktModal
          masterId={masterId}
          onClose={() => setCreateOpen(false)}
          onCreated={(id) => {
            qc.invalidateQueries({ queryKey: ['takt', 'schedules', masterId] });
            setTaktId(id);
            setCreateOpen(false);
          }}
        />
      )}
      {importOpen && taktId && (
        <ImportActivitiesModal
          taktId={taktId}
          onClose={() => setImportOpen(false)}
          onImported={() => {
            qc.invalidateQueries({ queryKey: ['takt', 'activities', taktId] });
            setLob(null);
            setImportOpen(false);
          }}
        />
      )}
      <ConfirmDialog
        open={!!deleteTakt}
        title={t('takt.delete_title', { defaultValue: 'Delete takt schedule?' })}
        message={
          deleteTakt
            ? t('takt.delete_message', {
                name: deleteTakt.name,
                defaultValue:
                  '"{{name}}" and all of its locations and activities will be permanently deleted.',
              })
            : ''
        }
        onConfirm={() => deleteTakt && deleteTaktMut.mutate(deleteTakt.id)}
        onCancel={() => setDeleteTakt(null)}
        loading={deleteTaktMut.isPending}
      />
    </div>
  );
}

/* ── small helpers ───────────────────────────────────────────────────── */

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd className="mt-0.5 text-base font-semibold text-content-primary tabular-nums">{value}</dd>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-content-tertiary">{label}</dt>
      <dd className="font-medium text-content-primary">{value}</dd>
    </div>
  );
}

function ViewToggle({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
        active
          ? 'bg-surface-primary text-content-primary shadow-xs'
          : 'text-content-secondary hover:text-content-primary',
      )}
    >
      {icon}
      {label}
    </button>
  );
}

/* ── Activities card ─────────────────────────────────────────────────── */

function ActivitiesCard({
  taktId,
  activities,
  loading,
  isError,
  error,
  onRetry,
  onImport,
}: {
  taktId: string;
  activities: TaktActivity[];
  loading: boolean;
  isError?: boolean;
  error?: unknown;
  onRetry?: () => void;
  onImport: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [deleteAct, setDeleteAct] = useState<TaktActivity | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ['takt', 'activities', taktId] });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteTaktActivity(taktId, id),
    onSuccess: () => {
      invalidate();
      setDeleteAct(null);
      addToast({ type: 'success', title: t('takt.activity_deleted', { defaultValue: 'Activity removed' }) });
    },
    onError: (err) => {
      setDeleteAct(null);
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  const actualMut = useMutation({
    mutationFn: ({ id, value }: { id: string; value: number | null }) =>
      updateTaktActivity(taktId, id, { actual_cycle_duration_days: value }),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('takt.actual_saved', { defaultValue: 'Actual cycle saved' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <Card padding="none">
      <div className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-3">
        <h3 className="text-sm font-semibold">{t('takt.activities', { defaultValue: 'Activities' })}</h3>
        <Button variant="secondary" size="sm" icon={<LayoutList size={14} />} onClick={onImport}>
          {t('takt.import', { defaultValue: 'Import activities' })}
        </Button>
      </div>
      {loading ? (
        <div className="p-4">
          <SkeletonTable rows={3} columns={4} />
        </div>
      ) : isError ? (
        <div className="p-6">
          <RecoveryCard error={error} onRetry={onRetry} />
        </div>
      ) : activities.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-content-tertiary">
          {t('takt.no_activities', {
            defaultValue: 'No activities yet. Import the trades that cycle through your locations.',
          })}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2.5 text-left">#</th>
                <th className="px-4 py-2.5 text-left">{t('takt.activity', { defaultValue: 'Activity' })}</th>
                <th className="px-4 py-2.5 text-right">
                  {t('takt.planned', { defaultValue: 'Planned (d)' })}
                </th>
                <th className="px-4 py-2.5 text-right">{t('takt.crew', { defaultValue: 'Crew' })}</th>
                <th className="px-4 py-2.5 text-right">
                  {t('takt.actualCycleDays', { defaultValue: 'Actual (d)' })}
                </th>
                <th className="px-4 py-2.5 text-right">{t('common.actions', { defaultValue: 'Actions' })}</th>
              </tr>
            </thead>
            <tbody>
              {activities.map((a) => (
                <tr key={a.id} className="border-t border-border-light">
                  <td className="px-4 py-2 text-content-tertiary tabular-nums">{a.sequence_order}</td>
                  <td className="px-4 py-2 font-medium">
                    {a.name}
                    {a.activity_code && (
                      <span className="ml-2 text-2xs text-content-tertiary">{a.activity_code}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{a.planned_cycle_duration_days}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{a.crew_size}</td>
                  <td className="px-4 py-2 text-right">
                    <input
                      type="number"
                      min={0}
                      step="0.5"
                      defaultValue={a.actual_cycle_duration_days ?? ''}
                      placeholder="—"
                      className="h-7 w-20 rounded border border-border bg-surface-primary px-2 text-right text-xs tabular-nums"
                      onBlur={(e) => {
                        const raw = e.target.value.trim();
                        const value = raw === '' ? null : Number(raw);
                        const prev = a.actual_cycle_duration_days == null ? null : Number(a.actual_cycle_duration_days);
                        if (value !== prev && !(value != null && Number.isNaN(value))) {
                          actualMut.mutate({ id: a.id, value });
                        }
                      }}
                      aria-label={t('takt.actualCycleDays', { defaultValue: 'Actual (d)' })}
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={12} />}
                      onClick={() => setDeleteAct(a)}
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ConfirmDialog
        open={!!deleteAct}
        title={t('takt.delete_activity_title', { defaultValue: 'Remove activity?' })}
        message={
          deleteAct
            ? t('takt.delete_activity_message', {
                name: deleteAct.name,
                defaultValue: '"{{name}}" will be removed from this takt schedule.',
              })
            : ''
        }
        onConfirm={() => deleteAct && deleteMut.mutate(deleteAct.id)}
        onCancel={() => setDeleteAct(null)}
        loading={deleteMut.isPending}
      />
    </Card>
  );
}

/* ── Create takt modal ───────────────────────────────────────────────── */

function CreateTaktModal({
  masterId,
  onClose,
  onCreated,
}: {
  masterId: string;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [targetCycle, setTargetCycle] = useState(7);
  const [tolerance, setTolerance] = useState(1);
  const [locationsText, setLocationsText] = useState('Level 1\nLevel 2\nLevel 3');

  const mut = useMutation({
    mutationFn: () => {
      const locations: TaktLocationInput[] = locationsText
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean)
        .map((l, i) => ({ sequence_order: i + 1, name: l }));
      return createTaktSchedule({
        master_schedule_id: masterId,
        name: name.trim(),
        target_cycle_days: targetCycle,
        takt_rhythm_tolerance_days: tolerance,
        locations,
      });
    },
    onSuccess: (ts) => {
      addToast({ type: 'success', title: t('takt.created', { defaultValue: 'Takt schedule created' }) });
      onCreated(ts.id);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const locationCount = locationsText.split('\n').filter((l) => l.trim()).length;
  const canSubmit = name.trim().length > 0 && locationCount > 0;

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('takt.create', { defaultValue: 'New takt schedule' })}
      busy={mut.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            loading={mut.isPending}
            disabled={!canSubmit}
            onClick={() => mut.mutate()}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label className={labelCls}>{t('common.name', { defaultValue: 'Name' })}</label>
          <input
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('takt.name_placeholder', { defaultValue: 'Tower L1-L6 Formwork' }) as string}
            autoFocus
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('takt.targetCycleDays', { defaultValue: 'Target cycle (days)' })}
            </label>
            <input
              type="number"
              min={1}
              className={inputCls}
              value={targetCycle}
              onChange={(e) => setTargetCycle(Math.max(1, Number(e.target.value) || 1))}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('takt.tolerance', { defaultValue: 'Rhythm tolerance (days)' })}
            </label>
            <input
              type="number"
              min={0}
              className={inputCls}
              value={tolerance}
              onChange={(e) => setTolerance(Math.max(0, Number(e.target.value) || 0))}
            />
          </div>
        </div>
        <div>
          <label className={labelCls}>
            {t('takt.locations_one_per_line', { defaultValue: 'Locations (one per line, top to bottom)' })}
          </label>
          <textarea
            className={clsx(inputCls, 'h-32 py-2 resize-y')}
            value={locationsText}
            onChange={(e) => setLocationsText(e.target.value)}
          />
          <p className="mt-1 text-2xs text-content-tertiary">
            <Badge variant="neutral">{locationCount}</Badge>{' '}
            {t('takt.locations', { defaultValue: 'Locations' })}
          </p>
        </div>
      </div>
    </WideModal>
  );
}

/* ── Import activities modal ─────────────────────────────────────────── */

function ImportActivitiesModal({
  taktId,
  onClose,
  onImported,
}: {
  taktId: string;
  onClose: () => void;
  onImported: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  // One activity per line: "Name, plannedDays, crewSize, bufferDays".
  const [text, setText] = useState('Formwork, 5, 4, 0\nConcrete, 3, 3, 0\nFinishes, 7, 2, 0');

  const parsed: TaktActivityInput[] = useMemo(() => {
    return text
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .map((line, i) => {
        const parts = line.split(',').map((p) => p.trim());
        const name = parts[0] || `Activity ${i + 1}`;
        const planned = Math.max(1, Number(parts[1]) || 1);
        const crew = Math.max(1, Number(parts[2]) || 1);
        const buffer = Math.max(0, Number(parts[3]) || 0);
        return {
          name,
          sequence_order: i + 1,
          planned_cycle_duration_days: planned,
          crew_size: crew,
          buffer_days_before: buffer,
        };
      });
  }, [text]);

  const mut = useMutation({
    mutationFn: () => importTaktActivities(taktId, parsed),
    onSuccess: (rows) => {
      addToast({
        type: 'success',
        title: t('takt.imported', {
          count: rows.length,
          defaultValue: '{{count}} activities imported',
        }),
      });
      onImported();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('takt.import', { defaultValue: 'Import activities' })}
      busy={mut.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            loading={mut.isPending}
            disabled={parsed.length === 0}
            onClick={() => mut.mutate()}
          >
            {t('takt.import_n', { count: parsed.length, defaultValue: 'Import {{count}}' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-xs text-content-secondary">
          {t('takt.import_hint', {
            defaultValue:
              'One trade per line: Name, planned cycle days, crew size, buffer days. Each trade repeats once per location.',
          })}
        </p>
        <textarea
          className={clsx(inputCls, 'h-40 py-2 font-mono text-xs resize-y')}
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
        />
        <div className="rounded-md border border-border-light bg-surface-secondary/40 p-2 text-xs">
          {parsed.length === 0 ? (
            <span className="text-content-tertiary">
              {t('takt.nothing_to_import', { defaultValue: 'Nothing to import.' })}
            </span>
          ) : (
            <ul className="space-y-0.5">
              {parsed.map((a, i) => (
                <li key={i} className="flex justify-between gap-2 tabular-nums">
                  <span>{a.name}</span>
                  <span className="text-content-tertiary">
                    {a.planned_cycle_duration_days}d · {a.crew_size} crew · +{a.buffer_days_before}d
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </WideModal>
  );
}
