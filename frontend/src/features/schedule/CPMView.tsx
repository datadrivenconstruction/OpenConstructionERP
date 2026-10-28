// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// CPM Slice 1 — Critical Path Method view with forward/backward pass results
// and a serial-greedy resource leveling modal. Reuses Card/Button/Badge from
// the shared UI kit; no new global components introduced.

import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Layers, AlertTriangle, X } from 'lucide-react';
import { Button, Card, Badge, Breadcrumb, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { apiGet, apiPost, getErrorMessage, type Page } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface ActivityRow {
  id: string;
  name: string;
  wbs_code: string;
  duration_days: number;
  early_start: string | null;
  early_finish: string | null;
  late_start: string | null;
  late_finish: string | null;
  total_float: number | null;
  free_float: number | null;
  is_critical: boolean;
  resources?: Array<{ name?: string }>;
}

interface CPMComputeSummary {
  schedule_id: string;
  critical_path: string[];
  project_duration_days: number;
  num_critical: number;
  num_activities: number;
}

interface LevelResourcesShift {
  activity_id: string;
  original_es: number;
  shifted_es: number;
  delta_days: number;
}

interface LevelResourcesUnresolvable {
  activity_id: string;
  resource: string;
  required: number;
  limit: number;
}

interface LevelResourcesResponse {
  schedule_id: string;
  shifts: LevelResourcesShift[];
  num_shifted: number;
  // An activity demanding more than a ceiling on its own cannot be helped by
  // moving it, so it never appears among the shifts. Without this list it
  // would read as an activity that needed nothing.
  unresolvable?: LevelResourcesUnresolvable[];
}

interface CPMViewProps {
  scheduleId: string;
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function CPMView({ scheduleId }: CPMViewProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [levelOpen, setLevelOpen] = useState(false);
  const [levelResult, setLevelResult] = useState<LevelResourcesResponse | null>(null);

  // Pull the activity rows so we can render ES/EF/LS/LF columns.
  const activitiesQuery = useQuery<ActivityRow[]>({
    queryKey: ['schedule', scheduleId, 'activities'],
    queryFn: () =>
      apiGet<Page<ActivityRow>>(`/v1/schedule/schedules/${scheduleId}/activities/`).then(
        (page) => page.items,
      ),
    enabled: Boolean(scheduleId),
  });

  // Distinct resource codes — drives the leveling modal inputs.
  const distinctResources = useMemo(() => {
    const set = new Set<string>();
    for (const a of activitiesQuery.data ?? []) {
      for (const r of a.resources ?? []) {
        if (r.name) set.add(r.name);
      }
    }
    return Array.from(set).sort();
  }, [activitiesQuery.data]);

  const [resourceLimits, setResourceLimits] = useState<Record<string, string>>({});

  // Recompute CPM mutation.
  const recomputeMut = useMutation<CPMComputeSummary, Error, void>({
    mutationFn: () =>
      apiPost<CPMComputeSummary>(
        `/v1/schedule-advanced/${scheduleId}/compute-cpm`,
        {},
      ),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: ['schedule', scheduleId, 'activities'] });
      addToast({
        type: 'success',
        title: t('schedule.cpm.recomputed', { defaultValue: 'Critical path recalculated' }),
        message: t('schedule.cpm.recomputed_detail', {
          defaultValue: '{{count}} critical of {{total}} activities',
          count: data.num_critical,
          total: data.num_activities,
        }),
      });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  // Level resources mutation.
  const levelMut = useMutation<LevelResourcesResponse, Error, Record<string, number>>({
    mutationFn: (limits) =>
      apiPost<LevelResourcesResponse>(
        `/v1/schedule-advanced/${scheduleId}/level-resources`,
        { resource_limits: limits },
      ),
    onSuccess: (data) => {
      setLevelResult(data);
      // This endpoint proposes shifts, it does not write them. The refresh is
      // here because the CPM figures behind the modal are read from the same
      // query and a stale table next to a fresh proposal reads as a conflict.
      void qc.invalidateQueries({ queryKey: ['schedule', scheduleId, 'activities'] });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  const handleLevelSubmit = () => {
    const parsed: Record<string, number> = {};
    for (const [k, v] of Object.entries(resourceLimits)) {
      const n = Number(v);
      if (!Number.isNaN(n) && n > 0) parsed[k] = Math.floor(n);
    }
    levelMut.mutate(parsed);
  };

  // Single close path for the leveling modal so the dialog state is always
  // reset consistently (used by the X button, Cancel, backdrop click and
  // the Escape key).
  const closeLevelModal = () => {
    setLevelOpen(false);
    setLevelResult(null);
  };

  // Dismiss the leveling modal on Escape (WCAG 2.1.2 - no keyboard trap).
  // The shared WideModal/ModalShell handle this for the other dialogs in
  // this module; this view's hand-rolled overlay needs it wired explicitly.
  useEffect(() => {
    if (!levelOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeLevelModal();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [levelOpen]);

  const activities = activitiesQuery.data ?? [];
  const numCritical = activities.filter((a) => a.is_critical).length;
  const projectDuration = activities.reduce(
    (acc, a) => Math.max(acc, Number(a.early_finish ?? 0)),
    0,
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('schedule.title', { defaultValue: '4D Schedule' }), to: '/schedule' },
          { label: t('schedule.cpm.title', { defaultValue: 'Critical Path' }) },
        ]}
      />
      <PageHeader
        srTitle={t('schedule.cpm.title', { defaultValue: 'Critical Path' })}
        subtitle={t('schedule.cpm.subtitle', {
          defaultValue: 'Forward and backward pass, early and late dates, float and the critical path.',
        })}
      />
      <DismissibleInfo
        storageKey="schedule_cpm"
        title={t('schedule_cpm.intro_title', {
          defaultValue: 'Know which activities cannot slip',
        })}
        more={
          t('schedule_cpm.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('schedule_cpm.intro_more')} />
            : undefined
        }
        links={[
          { label: t('schedule_cpm.intro_link_schedule', { defaultValue: 'Back to schedule' }), onClick: () => navigate('/schedule') },
        ]}
      >
        {t('schedule_cpm.intro_body', {
          defaultValue:
            'Runs the Critical Path Method over one schedule, showing the forward and backward pass, early and late dates and total float for every activity, with the critical path flagged. Use the resource-leveling step to shift non-critical activities and ease over-allocated crews without moving the finish date.',
        })}
      </DismissibleInfo>

      {/* ── Toolbar + summary ─────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm text-content-secondary">
          <Badge variant="blue">
            {t('schedule.cpm.summary_duration', { days: projectDuration })}
          </Badge>
          <Badge variant={numCritical > 0 ? 'error' : 'neutral'}>
            {t('schedule.cpm.summary_critical', { count: numCritical })}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={() => recomputeMut.mutate()}
            disabled={recomputeMut.isPending}
          >
            <RefreshCw className="mr-1.5 h-4 w-4" />
            {recomputeMut.isPending
              ? t('schedule.cpm.recomputing')
              : t('schedule.cpm.recompute')}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setLevelOpen(true)}
          >
            <Layers className="mr-1.5 h-4 w-4" />
            {t('schedule.cpm.level_resources')}
          </Button>
        </div>
      </div>

      {/* ── Activity table ────────────────────────────────────────────── */}
      <Card>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wide text-gray-600">
              <tr>
                <th className="px-3 py-2">{t('schedule.cpm.col_wbs')}</th>
                <th className="px-3 py-2">{t('schedule.cpm.col_name')}</th>
                <th className="px-3 py-2 text-right">{t('schedule.cpm.col_dur')}</th>
                <th className="px-3 py-2 text-right">{t('schedule.cpm.col_es')}</th>
                <th className="px-3 py-2 text-right">{t('schedule.cpm.col_ef')}</th>
                <th className="px-3 py-2 text-right">{t('schedule.cpm.col_ls')}</th>
                <th className="px-3 py-2 text-right">{t('schedule.cpm.col_lf')}</th>
                <th className="px-3 py-2 text-right">{t('schedule.cpm.col_float')}</th>
                <th className="px-3 py-2">{t('schedule.cpm.col_critical')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {activities.map((a) => (
                <tr
                  key={a.id}
                  className={a.is_critical ? 'bg-red-50' : 'hover:bg-gray-50'}
                >
                  <td className="px-3 py-2 font-mono text-xs">{a.wbs_code}</td>
                  <td className="px-3 py-2">{a.name}</td>
                  <td className="px-3 py-2 text-right">{a.duration_days}</td>
                  <td className="px-3 py-2 text-right">{a.early_start ?? '-'}</td>
                  <td className="px-3 py-2 text-right">{a.early_finish ?? '-'}</td>
                  <td className="px-3 py-2 text-right">{a.late_start ?? '-'}</td>
                  <td className="px-3 py-2 text-right">{a.late_finish ?? '-'}</td>
                  <td className="px-3 py-2 text-right">
                    {a.total_float ?? '-'}
                  </td>
                  <td className="px-3 py-2">
                    {a.is_critical ? (
                      <Badge variant="error">
                        <AlertTriangle className="mr-1 h-3 w-3" />
                        {t('schedule.cpm.critical_badge')}
                      </Badge>
                    ) : null}
                  </td>
                </tr>
              ))}
              {activities.length === 0 && !activitiesQuery.isLoading && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-gray-500">
                    {t('schedule.cpm.empty')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── Level-resources modal ─────────────────────────────────────── */}
      {levelOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
          onClick={closeLevelModal}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="cpm-level-modal-title"
            className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h3 id="cpm-level-modal-title" className="text-lg font-semibold">
                {t('schedule.cpm.level_modal_title')}
              </h3>
              <button
                type="button"
                onClick={closeLevelModal}
                className="text-gray-400 hover:text-gray-600"
                aria-label={t('common.close', { defaultValue: 'Close' })}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {!levelResult ? (
              <>
                <p className="mb-3 text-sm text-gray-600">
                  {t('schedule.cpm.level_modal_hint')}
                </p>
                {distinctResources.length === 0 ? (
                  <p className="text-sm text-gray-500">
                    {t('schedule.cpm.level_modal_no_resources')}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {distinctResources.map((code) => (
                      <div key={code} className="flex items-center justify-between gap-2">
                        <label
                          htmlFor={`limit-${code}`}
                          className="text-sm font-medium text-gray-700"
                        >
                          {code}
                        </label>
                        <input
                          id={`limit-${code}`}
                          type="number"
                          min={1}
                          step={1}
                          value={resourceLimits[code] ?? ''}
                          onChange={(e) =>
                            setResourceLimits((s) => ({
                              ...s,
                              [code]: e.target.value,
                            }))
                          }
                          className="w-24 rounded border border-gray-300 px-2 py-1 text-sm"
                          placeholder="∞"
                        />
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-4 flex justify-end gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={closeLevelModal}
                  >
                    {t('schedule.cpm.cancel')}
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleLevelSubmit}
                    disabled={levelMut.isPending}
                  >
                    {levelMut.isPending
                      ? t('schedule.cpm.leveling')
                      : t('schedule.cpm.run_leveling')}
                  </Button>
                </div>
              </>
            ) : (
              <div>
                <p className="mb-3 text-sm">
                  {t('schedule.cpm.level_result', { count: levelResult.num_shifted })}
                </p>
                {levelResult.unresolvable && levelResult.unresolvable.length > 0 && (
                  <div
                    className="mb-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
                    data-testid="level-unresolvable"
                  >
                    <p className="font-medium">
                      {t('schedule.cpm.level_unresolvable', {
                        count: levelResult.unresolvable.length,
                      })}
                    </p>
                    <ul className="mt-1 space-y-0.5">
                      {levelResult.unresolvable.map((u) => (
                        <li key={`${u.activity_id}-${u.resource}`}>
                          <span className="font-mono">{u.activity_id.slice(0, 8)}</span>{' '}
                          {t('schedule.cpm.level_unresolvable_row', {
                            resource: u.resource,
                            required: u.required,
                            limit: u.limit,
                          })}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="max-h-60 overflow-y-auto rounded border border-gray-200">
                  <table className="min-w-full text-xs">
                    <thead className="bg-gray-50 text-left">
                      <tr>
                        <th className="px-2 py-1">{t('schedule.cpm.col_activity')}</th>
                        <th className="px-2 py-1 text-right">{t('schedule.cpm.col_es_old')}</th>
                        <th className="px-2 py-1 text-right">{t('schedule.cpm.col_es_new')}</th>
                        <th
                          className="px-2 py-1 text-right"
                          title={t('schedule.cpm.col_es_delta', { defaultValue: 'Shift in days' })}
                        >
                          {t('schedule.cpm.col_es_delta_short', { defaultValue: 'Δ days' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {levelResult.shifts.map((s) => (
                        <tr key={s.activity_id}>
                          <td className="px-2 py-1 font-mono">
                            {s.activity_id.slice(0, 8)}
                          </td>
                          <td className="px-2 py-1 text-right">{s.original_es}</td>
                          <td className="px-2 py-1 text-right">{s.shifted_es}</td>
                          <td className="px-2 py-1 text-right">+{s.delta_days}</td>
                        </tr>
                      ))}
                      {levelResult.shifts.length === 0 && (
                        <tr>
                          <td colSpan={4} className="px-2 py-4 text-center text-gray-500">
                            {t('schedule.cpm.level_no_change')}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <div className="mt-4 flex justify-end">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={closeLevelModal}
                  >
                    {t('schedule.cpm.close')}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
