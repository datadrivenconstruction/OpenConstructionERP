// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Scheduling profiles: the CPM settings a project schedules with (how
// progressed work is placed, which calendar counts lags, how open ends and
// the critical path are treated). Pick the profile this schedule uses, edit
// or add profiles, preview a recalculation that names the setting behind
// every moved date, and apply it.

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Calculator, CheckCircle2, Pencil, Plus, Star, Trash2 } from 'lucide-react';

import { Badge, Button, Card, ConfirmDialog, EmptyState } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  DEFAULT_PROFILE_SETTINGS,
  interopApi,
  type ChangeCause,
  type ProfileDraft,
  type RecalculateResult,
  type SchedulingProfile,
} from './interopApi';
import { formatShift, isChangedActivity, sortedEffects } from './interopLogic';

interface SchedulingProfilesPanelProps {
  scheduleId: string;
  projectId: string;
  canEdit: boolean;
}

const OPTIONS = {
  progress_mode: ['retained_logic', 'progress_override', 'actual_dates'],
  lag_calendar: ['elapsed', 'predecessor', 'successor', 'project'],
  open_ends: ['project_finish', 'own_finish'],
  critical_rule: ['total_float', 'longest_path'],
} as const;

type OptionKey = keyof typeof OPTIONS;

const OPTION_DEFAULTS: Record<string, string> = {
  progress_mode: 'Progressed work',
  lag_calendar: 'Lag calendar',
  open_ends: 'Open ends',
  critical_rule: 'Critical path',
  retained_logic: 'Retained logic: remaining work waits for open predecessors',
  progress_override: 'Progress override: remaining work runs from the status date',
  actual_dates: 'Actual dates: planned duration runs from the actual start',
  elapsed: 'Calendar days',
  predecessor: "Predecessor's calendar",
  successor: "Successor's calendar",
  project: 'Project calendar',
  project_finish: 'Bound to the project finish',
  own_finish: 'Own finish (open ends become critical)',
  total_float: 'Total float at or below a threshold',
  longest_path: 'Longest path to the finish',
};

const CAUSE_DEFAULTS: Record<ChangeCause, string> = {
  progress_mode: 'Progressed work',
  lag_calendar: 'Lag calendar',
  status: 'Status date and actuals',
  open_ends: 'Open ends',
  critical_rule: 'Critical path rule',
  critical_float_threshold: 'Float threshold',
};

function emptyDraft(): ProfileDraft {
  return { name: '', description: '', is_default: false, ...DEFAULT_PROFILE_SETTINGS };
}

export function SchedulingProfilesPanel({ scheduleId, projectId, canEdit }: SchedulingProfilesPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const { confirm, ...confirmProps } = useConfirm();

  const [editing, setEditing] = useState<SchedulingProfile | 'new' | null>(null);
  const [draft, setDraft] = useState<ProfileDraft>(emptyDraft());
  const [result, setResult] = useState<RecalculateResult | null>(null);
  const [onlyChanged, setOnlyChanged] = useState(true);

  const profiles = useQuery({
    queryKey: ['scheduling-profiles', projectId],
    queryFn: () => interopApi.listProfiles(projectId),
  });
  const effective = useQuery({
    queryKey: ['schedule-profile', scheduleId],
    queryFn: () => interopApi.getScheduleProfile(scheduleId),
  });

  useEffect(() => {
    if (editing === 'new') setDraft(emptyDraft());
    else if (editing) {
      const { name, description, is_default, progress_mode, lag_calendar, open_ends, critical_rule } = editing;
      setDraft({
        name,
        description,
        is_default,
        progress_mode,
        lag_calendar,
        open_ends,
        critical_rule,
        critical_float_threshold: editing.critical_float_threshold,
      });
    }
  }, [editing]);

  const label = (key: string) => t(`schedule.profiles.opt_${key}`, { defaultValue: OPTION_DEFAULTS[key] ?? key });
  const causeLabel = (key: ChangeCause) =>
    t(`schedule.profiles.cause_${key}`, { defaultValue: CAUSE_DEFAULTS[key] ?? key });
  const fail = (err: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });

  const refreshProfiles = () => {
    queryClient.invalidateQueries({ queryKey: ['scheduling-profiles', projectId] });
    queryClient.invalidateQueries({ queryKey: ['schedule-profile', scheduleId] });
  };

  const save = useMutation({
    mutationFn: () =>
      editing === 'new' || editing === null
        ? interopApi.createProfile(projectId, draft)
        : interopApi.updateProfile(editing.id, draft),
    onSuccess: () => {
      refreshProfiles();
      setEditing(null);
      setResult(null);
      addToast({ type: 'success', title: t('schedule.profiles.saved', { defaultValue: 'Profile saved' }) });
    },
    onError: fail,
  });

  const remove = useMutation({
    mutationFn: (id: string) => interopApi.deleteProfile(id),
    onSuccess: () => {
      refreshProfiles();
      setResult(null);
    },
    onError: fail,
  });

  const assign = useMutation({
    mutationFn: (profileId: string | null) => interopApi.assignScheduleProfile(scheduleId, profileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedule-profile', scheduleId] });
      setResult(null);
    },
    onError: fail,
  });

  const previewRun = useMutation({
    mutationFn: () => interopApi.previewRecalculation(scheduleId, null),
    onSuccess: setResult,
    onError: fail,
  });

  const applyRun = useMutation({
    mutationFn: () => interopApi.applyRecalculation(scheduleId, null),
    onSuccess: (res) => {
      setResult(res);
      queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
      queryClient.invalidateQueries({ queryKey: ['schedule-record', scheduleId] });
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      addToast({
        type: 'success',
        title: t('schedule.profiles.applied', {
          defaultValue: 'Dates recalculated for {{count}} activities',
          count: res.changed_count,
        }),
      });
    },
    onError: fail,
  });

  const rows = useMemo(
    () => (result ? (onlyChanged ? result.activities.filter(isChangedActivity) : result.activities) : []),
    [result, onlyChanged],
  );

  const selectClass =
    'h-9 w-full rounded-lg border border-border-light bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40';
  const currentId = effective.data?.source === 'schedule' ? effective.data.profile_id : '';

  return (
    <div className="space-y-4" data-testid="scheduling-profiles-panel">
      <Card padding="md">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <label className="flex min-w-[260px] flex-col gap-1 text-xs text-content-secondary">
            {t('schedule.profiles.used_by_schedule', { defaultValue: 'Profile used by this schedule' })}
            <select
              className={selectClass}
              value={currentId ?? ''}
              disabled={!canEdit || assign.isPending}
              onChange={(e) => assign.mutate(e.target.value || null)}
              data-testid="profile-assign"
            >
              <option value="">
                {t('schedule.profiles.project_default', { defaultValue: 'Project default' })}
              </option>
              {(profiles.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-2">
            {effective.data && (
              <Badge variant="neutral" size="sm">
                {effective.data.profile_name ??
                  t('schedule.profiles.builtin', { defaultValue: 'Built-in settings' })}
              </Badge>
            )}
            <Button
              variant="secondary"
              icon={<Calculator size={16} />}
              loading={previewRun.isPending}
              onClick={() => previewRun.mutate()}
              data-testid="profile-preview"
            >
              {t('schedule.profiles.preview', { defaultValue: 'Preview recalculation' })}
            </Button>
          </div>
        </div>

        <div className="mt-4 space-y-2">
          {(profiles.data ?? []).length === 0 && !profiles.isLoading && (
            <EmptyState
              title={t('schedule.profiles.empty_title', { defaultValue: 'No scheduling profiles yet' })}
              description={t('schedule.profiles.empty_text', {
                defaultValue:
                  'Without a profile the schedule uses retained logic, calendar-day lags and a zero-float critical path.',
              })}
            />
          )}
          {(profiles.data ?? []).map((p) => (
            <div
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-light px-3 py-2"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-medium text-content-primary">
                  {p.is_default && <Star size={14} className="text-amber-500" aria-hidden />}
                  {p.name}
                </div>
                <div className="text-xs text-content-tertiary">
                  {label(p.progress_mode)} · {label(p.lag_calendar)} · {label(p.open_ends)} · {label(p.critical_rule)}
                  {p.critical_rule === 'total_float' && ` (${p.critical_float_threshold})`}
                </div>
              </div>
              {canEdit && (
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" icon={<Pencil size={14} />} onClick={() => setEditing(p)}>
                    {t('common.edit', { defaultValue: 'Edit' })}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 size={14} />}
                    onClick={async () => {
                      const ok = await confirm({
                        title: t('schedule.profiles.delete_title', { defaultValue: 'Delete this profile?' }),
                        message: t('schedule.profiles.delete_message', {
                          defaultValue: 'Schedules that use it will fall back to the project default.',
                        }),
                        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
                        variant: 'danger',
                      });
                      if (ok) remove.mutate(p.id);
                    }}
                  >
                    {t('common.delete', { defaultValue: 'Delete' })}
                  </Button>
                </div>
              )}
            </div>
          ))}
          {canEdit && editing === null && (
            <Button variant="ghost" size="sm" icon={<Plus size={14} />} onClick={() => setEditing('new')}>
              {t('schedule.profiles.add', { defaultValue: 'Add profile' })}
            </Button>
          )}
        </div>
      </Card>

      {editing !== null && (
        <Card padding="md" data-testid="profile-editor">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('schedule.profiles.name', { defaultValue: 'Name' })}
              <input
                className={selectClass}
                value={draft.name}
                maxLength={120}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                data-testid="profile-name"
              />
            </label>
            <label className="flex items-center gap-2 self-end text-sm text-content-secondary">
              <input
                type="checkbox"
                checked={draft.is_default}
                onChange={(e) => setDraft({ ...draft, is_default: e.target.checked })}
              />
              {t('schedule.profiles.is_default', { defaultValue: 'Default for the project' })}
            </label>
            {(Object.keys(OPTIONS) as OptionKey[]).map((key) => (
              <label key={key} className="flex flex-col gap-1 text-xs text-content-secondary">
                {label(key)}
                <select
                  className={selectClass}
                  value={draft[key]}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value } as ProfileDraft)}
                  data-testid={`profile-${key}`}
                >
                  {(OPTIONS[key] as readonly string[]).map((opt) => (
                    <option key={opt} value={opt}>
                      {label(opt)}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            {draft.critical_rule === 'total_float' && (
              <label className="flex flex-col gap-1 text-xs text-content-secondary">
                {t('schedule.profiles.threshold', { defaultValue: 'Critical when total float is at most (working days)' })}
                <input
                  type="number"
                  min={0}
                  max={365}
                  className={selectClass}
                  value={draft.critical_float_threshold}
                  onChange={(e) =>
                    setDraft({ ...draft, critical_float_threshold: Math.max(0, Number(e.target.value) || 0) })
                  }
                />
              </label>
            )}
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setEditing(null)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              loading={save.isPending}
              disabled={!draft.name.trim()}
              onClick={() => save.mutate()}
              data-testid="profile-save"
            >
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
          </div>
        </Card>
      )}

      {result && (
        <Card padding="md" data-testid="recalc-result">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <div className="text-sm font-medium text-content-primary">
                {t('schedule.profiles.finish_change', {
                  defaultValue: 'Finish {{before}} → {{after}}',
                  before: result.current_finish ?? '-',
                  after: result.new_finish ?? '-',
                })}
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge variant="blue" size="sm">
                  {t('schedule.profiles.changed', {
                    defaultValue: '{{count}} activities change',
                    count: result.changed_count,
                  })}
                </Badge>
                <Badge variant="error" size="sm">
                  {t('schedule.profiles.critical', { defaultValue: '{{count}} critical', count: result.critical_count })}
                </Badge>
                {result.out_of_sequence_count > 0 && (
                  <Badge variant="warning" size="sm">
                    {t('schedule.profiles.out_of_sequence', {
                      defaultValue: '{{count}} out of sequence',
                      count: result.out_of_sequence_count,
                    })}
                  </Badge>
                )}
                {result.open_end_count > 0 && (
                  <Badge variant="neutral" size="sm">
                    {t('schedule.profiles.open_ends_count', {
                      defaultValue: '{{count}} open ends',
                      count: result.open_end_count,
                    })}
                  </Badge>
                )}
                {sortedEffects(result.setting_effects).map(([cause, n]) => (
                  <Badge key={cause} variant="purple" size="sm">
                    {causeLabel(cause)}: {n}
                  </Badge>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-content-secondary">
                <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
                {t('schedule.profiles.only_changed', { defaultValue: 'Only changed activities' })}
              </label>
              {canEdit && !result.applied && (
                <Button
                  variant="primary"
                  icon={<CheckCircle2 size={16} />}
                  loading={applyRun.isPending}
                  disabled={result.changed_count === 0}
                  onClick={async () => {
                    const ok = await confirm({
                      title: t('schedule.profiles.apply_title', { defaultValue: 'Apply the recalculated dates?' }),
                      message: t('schedule.profiles.apply_message', {
                        defaultValue: '{{count}} activities get new dates or a new critical flag. The change is logged.',
                        count: result.changed_count,
                      }),
                      confirmLabel: t('schedule.profiles.apply', { defaultValue: 'Apply dates' }),
                      variant: 'warning',
                    });
                    if (ok) applyRun.mutate();
                  }}
                  data-testid="recalc-apply"
                >
                  {t('schedule.profiles.apply', { defaultValue: 'Apply dates' })}
                </Button>
              )}
              {result.applied && (
                <Badge variant="success" size="sm">
                  {t('schedule.profiles.applied_badge', { defaultValue: 'Applied' })}
                </Badge>
              )}
            </div>
          </div>
          <div className="mt-3 max-h-[55vh] overflow-auto rounded-lg border border-border-light">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface-secondary text-content-secondary">
                <tr>
                  <th className="px-2 py-2 text-left">{t('schedule.profiles.col_activity', { defaultValue: 'Activity' })}</th>
                  <th className="px-2 py-2 text-left">{t('schedule.profiles.col_current', { defaultValue: 'Current' })}</th>
                  <th className="px-2 py-2 text-left">
                    {t('schedule.profiles.col_recalculated', { defaultValue: 'Recalculated' })}
                  </th>
                  <th className="px-2 py-2 text-right">
                    {t('schedule.profiles.col_finish_shift', { defaultValue: 'Finish shift (days)' })}
                  </th>
                  <th className="px-2 py-2 text-right">{t('schedule.profiles.col_float', { defaultValue: 'Float' })}</th>
                  <th className="px-2 py-2 text-left">
                    {t('schedule.profiles.col_changed_by', { defaultValue: 'Changed by' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.activity_id} className="border-t border-border-light">
                    <td className="px-2 py-1.5">
                      <div className="font-medium text-content-primary">{row.name}</div>
                      <div className="flex flex-wrap gap-1 text-content-tertiary">
                        {row.activity_code}
                        {row.is_critical && (
                          <Badge variant="error" size="sm">
                            {t('schedule.profiles.flag_critical', { defaultValue: 'Critical' })}
                          </Badge>
                        )}
                        {row.out_of_sequence && (
                          <Badge variant="warning" size="sm">
                            {t('schedule.profiles.flag_oos', { defaultValue: 'Out of sequence' })}
                          </Badge>
                        )}
                        {row.open_finish && !row.completed && (
                          <Badge variant="neutral" size="sm">
                            {t('schedule.profiles.flag_open_end', { defaultValue: 'Open end' })}
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-content-secondary">
                      {row.current_start} – {row.current_end}
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-content-primary">
                      {row.new_start} – {row.new_end}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{formatShift(row.finish_shift_days)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{row.total_float}</td>
                    <td className="px-2 py-1.5">
                      <div className="flex flex-wrap gap-1">
                        {row.changed_by.map((cause) => (
                          <Badge key={cause} variant="purple" size="sm">
                            {causeLabel(cause)}
                          </Badge>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
