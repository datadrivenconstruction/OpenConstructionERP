// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Progress-rigor panel (T3.2). One place to make activity progress mean
// something precise:
//   - a live Planned-Value header: pick a data date, preview time-phased PV
//     vs BAC, and "Advance" the data date to refresh the EVM snapshot;
//   - per activity: a 3-way percent-complete type picker (Duration / Units /
//     Physical) with an amber EVM-distortion callout shown BEFORE you commit;
//   - per-type input affordances (duration % slider with live remaining days,
//     units installed/budgeted with derived %, physical % + independent
//     remaining or a step-managed badge);
//   - a weighted step checklist (name, weight, %, milestone) whose roll-up
//     drives the parent % live;
//   - suspend / resume with a reason, freezing remaining duration.
//
// All math is computed server-side by the pure engine; this panel only renders
// the results and the deterministic warning keys.

import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Gauge,
  Clock,
  Boxes,
  ListChecks,
  PauseCircle,
  PlayCircle,
  AlertTriangle,
  Plus,
  Trash2,
  Flag,
  CalendarClock,
  Loader2,
} from 'lucide-react';

import { Button, Card, Badge, Input, EmptyState } from '@/shared/ui';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import {
  scheduleApi,
  type PercentCompleteType,
  type EvmWarningKey,
  type TypedActivityView,
  type TypedProgressResponse,
} from './api';
import {
  EVM_WARNING_DEFAULTS,
  PERCENT_TYPES,
  mergeProgressState,
  pvPercentOfBac,
  rollupSteps,
  totalWeight,
  unitsProgressBody,
  viewFromTyped,
} from './progressRigor';
import { fmtPercent } from '@/shared/lib/formatters';

interface ActivityLite {
  id: string;
  name: string;
  progress_pct?: number | string;
  status?: string;
  percent_complete_type?: string;
}

interface ProgressRigorPanelProps {
  scheduleId: string;
  /** The Gantt activity rows already held by the page (id + name at minimum). */
  activities: ActivityLite[];
  /** Project ISO currency for PV money formatting (blank -> no symbol). */
  currency?: string;
  /** Schedule data date (ISO), if known, to seed the header. */
  dataDate?: string | null;
}

const TYPE_META: Record<PercentCompleteType, { label: string; icon: typeof Gauge; hint: string }> = {
  duration: { label: 'Duration', icon: Clock, hint: 'Remaining days derived from %' },
  units: { label: 'Units', icon: Boxes, hint: '% derived from installed / budgeted' },
  physical: { label: 'Physical', icon: Gauge, hint: 'Manual % or weighted steps' },
};

/** i18n key per warning, with the shared default-value text. */
const WARNING_I18N_KEY: Record<EvmWarningKey, string> = {
  units_type_without_budgeted_units: 'schedule.warn_units_no_budget',
  duration_type_on_nonlinear_cost: 'schedule.warn_duration_nonlinear',
  physical_manual_pct_is_subjective: 'schedule.warn_physical_subjective',
  all_steps_zero_weight: 'schedule.warn_steps_zero_weight',
};

/** Human-readable text for each deterministic EVM-distortion warning key. */
function warningText(key: EvmWarningKey, t: (k: string, o?: Record<string, unknown>) => string): string {
  return t(WARNING_I18N_KEY[key], { defaultValue: EVM_WARNING_DEFAULTS[key] });
}

function EvmWarnings({ warnings }: { warnings: EvmWarningKey[] }) {
  const { t } = useTranslation();
  if (!warnings.length) return null;
  return (
    <div className="mt-2 space-y-1">
      {warnings.map((w) => (
        <div
          key={w}
          className="flex items-start gap-2 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800 ring-1 ring-amber-200"
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span>{warningText(w, t)}</span>
        </div>
      ))}
    </div>
  );
}

export function ProgressRigorPanel({ scheduleId, activities, currency, dataDate }: ProgressRigorPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [selectedId, setSelectedId] = useState<string>(activities[0]?.id ?? '');
  const [asOf, setAsOf] = useState<string>(dataDate?.slice(0, 10) ?? new Date().toISOString().slice(0, 10));

  const selected = useMemo(
    () => activities.find((a) => a.id === selectedId) ?? activities[0],
    [activities, selectedId],
  );

  // ── Live planned value preview at the chosen date ──────────────────────
  const pv = useQuery({
    queryKey: ['schedule', scheduleId, 'planned-value', asOf],
    queryFn: () => scheduleApi.getPlannedValue(scheduleId, asOf),
    enabled: Boolean(scheduleId && asOf),
  });

  const advance = useMutation({
    mutationFn: () => scheduleApi.advanceDataDate(scheduleId, asOf),
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('common.success', { defaultValue: 'Success' }),
        message: t('schedule.data_date_advanced', {
          defaultValue: 'Data date advanced to {{date}}; PV refreshed.',
          date: res.data_date ?? asOf,
        }),
      });
      qc.invalidateQueries({ queryKey: ['schedule', scheduleId, 'evm'] });
      qc.invalidateQueries({ queryKey: ['schedule', scheduleId, 'planned-value'] });
    },
    onError: () =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: t('schedule.data_date_failed', { defaultValue: 'Could not advance the data date.' }),
      }),
  });

  if (!activities.length) {
    return (
      <EmptyState
        icon={<Gauge size={40} />}
        title={t('schedule.progress_no_activities_title', { defaultValue: 'No activities to track' })}
        description={t('schedule.progress_no_activities_desc', {
          defaultValue: 'Add activities to the schedule to set typed progress, steps and suspend/resume.',
        })}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* ── Live PV header ──────────────────────────────────────────────── */}
      <Card>
        <div className="flex flex-wrap items-end justify-between gap-3 p-4">
          <div>
            <div className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
              <CalendarClock size={15} /> {t('schedule.live_pv', { defaultValue: 'Live planned value' })}
            </div>
            <p className="mt-0.5 text-xs text-content-secondary">
              {t('schedule.live_pv_hint', {
                defaultValue: 'PV is time-phased to the data date - it moves as the date advances instead of sitting frozen at BAC.',
              })}
            </p>
          </div>
          <div className="flex items-end gap-2">
            <label className="flex flex-col text-xs text-content-secondary">
              {t('schedule.data_date', { defaultValue: 'Data date' })}
              <Input
                type="date"
                value={asOf}
                onChange={(e) => setAsOf(e.target.value)}
                className="mt-1 w-40"
              />
            </label>
            <Button
              variant="primary"
              icon={<CalendarClock size={15} />}
              loading={advance.isPending}
              onClick={() => advance.mutate()}
            >
              {t('schedule.advance', { defaultValue: 'Advance' })}
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-px border-t border-border-light bg-border-light sm:grid-cols-3">
          <PvStat
            label={t('schedule.pv', { defaultValue: 'Planned value' })}
            value={pv.data ? formatCurrency(toNum(pv.data.planned_value), currency || undefined) : '-'}
            loading={pv.isLoading}
          />
          <PvStat
            label={t('schedule.bac', { defaultValue: 'Budget at completion' })}
            value={pv.data ? formatCurrency(toNum(pv.data.budget_at_completion), currency || undefined) : '-'}
            loading={pv.isLoading}
          />
          <PvStat
            label={t('schedule.pv_pct', { defaultValue: 'PV % of BAC' })}
            value={pvPercentOfBac(pv.data?.planned_value, pv.data?.budget_at_completion)}
            loading={pv.isLoading}
          />
        </div>
      </Card>

      {/* ── Activity picker ─────────────────────────────────────────────── */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 p-3">
          <label className="text-xs font-medium text-content-secondary">
            {t('schedule.activity', { defaultValue: 'Activity' })}
          </label>
          <select
            value={selected?.id ?? ''}
            onChange={(e) => setSelectedId(e.target.value)}
            className="min-w-[16rem] flex-1 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm"
          >
            {activities.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        {selected && <ActivityProgressEditor key={selected.id} scheduleId={scheduleId} activityId={selected.id} />}
      </Card>
    </div>
  );
}

function PvStat({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return (
    <div className="bg-surface-primary px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className="mt-0.5 text-base font-semibold text-content-primary">
        {loading ? <Loader2 size={15} className="animate-spin" /> : value}
      </div>
    </div>
  );
}

/* ── Per-activity editor ───────────────────────────────────────────────── */

function ActivityProgressEditor({ scheduleId, activityId }: { scheduleId: string; activityId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // The typed activity view + steps. We refetch both after every mutation.
  const steps = useQuery({
    queryKey: ['schedule', 'steps', activityId],
    queryFn: () => scheduleApi.listSteps(activityId),
    enabled: Boolean(activityId),
  });

  // Local snapshot of the activity's typed state, seeded by the first typed
  // write's response and kept in sync after each mutation.
  const [view, setView] = useState<TypedActivityView | null>(null);
  const [warnings, setWarnings] = useState<EvmWarningKey[]>([]);
  const [previewWarnings, setPreviewWarnings] = useState<EvmWarningKey[]>([]);

  // Seed the view once (a no-op typed update returns the current state).
  const seed = useQuery({
    queryKey: ['schedule', 'typed-activity', activityId],
    queryFn: async () => {
      const res = await scheduleApi.updateProgressTyped(activityId, {});
      setView(viewFromTyped(res));
      setWarnings(res.evm_warnings ?? []);
      return res;
    },
    enabled: Boolean(activityId) && view === null,
    staleTime: 0,
  });

  const pctType = (view?.percent_complete_type ?? 'physical') as PercentCompleteType;
  const hasSteps = (steps.data?.length ?? 0) > 0;

  const applyResult = (res: TypedProgressResponse) => {
    setView(viewFromTyped(res));
    setWarnings(res.evm_warnings);
    setPreviewWarnings([]);
    qc.invalidateQueries({ queryKey: ['schedule', scheduleId] });
  };

  const typedUpdate = useMutation({
    mutationFn: (body: Parameters<typeof scheduleApi.updateProgressTyped>[1]) =>
      scheduleApi.updateProgressTyped(activityId, body),
    onSuccess: applyResult,
    onError: () => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('schedule.progress_save_failed', { defaultValue: 'Could not save progress.' }) }),
  });

  const changeType = useMutation({
    mutationFn: (type: PercentCompleteType) => scheduleApi.setPercentType(activityId, type),
    // The PUT answers with the new type and its warnings only, so merge rather
    // than replace the view.
    onSuccess: (res) => {
      setView((v) => (v ? { ...v, percent_complete_type: res.percent_complete_type } : v));
      setWarnings(res.evm_warnings);
      setPreviewWarnings([]);
      qc.invalidateQueries({ queryKey: ['schedule', scheduleId] });
    },
  });

  const suspendResume = useMutation({
    mutationFn: (action: 'suspend' | 'resume') => {
      if (action === 'suspend') {
        const reason = window.prompt(t('schedule.suspend_reason_prompt', { defaultValue: 'Reason for suspension?' })) ?? '';
        if (!reason.trim()) return Promise.reject(new Error('cancelled'));
        return scheduleApi.suspendActivity(activityId, reason);
      }
      return scheduleApi.resumeActivity(activityId);
    },
    onSuccess: (res) => {
      setView((v) => (v ? mergeProgressState(v, res) : v));
      qc.invalidateQueries({ queryKey: ['schedule', scheduleId] });
    },
    onError: (e) => {
      if ((e as Error).message !== 'cancelled') {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('schedule.suspend_failed', { defaultValue: 'Action failed.' }) });
      }
    },
  });

  // Preview the warnings a type change would raise, before committing.
  const previewType = async (type: PercentCompleteType) => {
    if (type === pctType) {
      setPreviewWarnings([]);
      return;
    }
    try {
      const res = await scheduleApi.previewPercentType(activityId, type);
      setPreviewWarnings(res.evm_warnings);
    } catch {
      setPreviewWarnings([]);
    }
  };

  if (seed.isLoading || !view) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-content-secondary">
        <Loader2 size={15} className="animate-spin" /> {t('common.loading', { defaultValue: 'Loading…' })}
      </div>
    );
  }

  const suspended = view.status === 'suspended';

  return (
    <div className="space-y-4 border-t border-border-light p-4">
      {/* status + suspend/resume */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge variant={suspended ? 'warning' : view.status === 'completed' ? 'success' : 'neutral'}>
            {t(`schedule.status_${view.status}`, { defaultValue: view.status })}
          </Badge>
          {suspended && view.suspended_at && (
            <span className="text-xs text-amber-700">
              {t('schedule.suspended_since', { defaultValue: 'Suspended since {{date}}', date: view.suspended_at })}
              {view.suspend_reason ? ` - ${view.suspend_reason}` : ''}
            </span>
          )}
          {view.forecast_finish && (
            <span className="text-xs text-content-secondary">
              {t('schedule.forecast_finish', { defaultValue: 'Forecast finish' })}: {view.forecast_finish}
            </span>
          )}
        </div>
        {suspended ? (
          <Button variant="secondary" icon={<PlayCircle size={15} />} onClick={() => suspendResume.mutate('resume')} loading={suspendResume.isPending}>
            {t('schedule.resume', { defaultValue: 'Resume' })}
          </Button>
        ) : (
          <Button variant="ghost" icon={<PauseCircle size={15} />} onClick={() => suspendResume.mutate('suspend')} loading={suspendResume.isPending}>
            {t('schedule.suspend', { defaultValue: 'Suspend' })}
          </Button>
        )}
      </div>

      {/* % type picker */}
      <div>
        <div className="text-xs font-medium text-content-secondary">
          {t('schedule.percent_type', { defaultValue: 'Percent-complete method' })}
        </div>
        <div className="mt-1.5 flex gap-1.5">
          {PERCENT_TYPES.map((typeKey) => {
            const meta = TYPE_META[typeKey];
            const Icon = meta.icon;
            const active = pctType === typeKey;
            return (
              <button
                key={typeKey}
                type="button"
                aria-pressed={active}
                onMouseEnter={() => previewType(typeKey)}
                onFocus={() => previewType(typeKey)}
                onClick={() => changeType.mutate(typeKey)}
                title={meta.hint}
                className={`flex flex-1 flex-col items-center gap-1 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
                  active
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border-light text-content-secondary hover:bg-surface-secondary'
                }`}
              >
                <Icon size={16} />
                {t(`schedule.ptype_${typeKey}`, { defaultValue: meta.label })}
              </button>
            );
          })}
        </div>
        {/* preview warnings (before commit) take priority; else committed ones */}
        <EvmWarnings warnings={previewWarnings.length ? previewWarnings : warnings} />
      </div>

      {/* per-type input */}
      {pctType === 'units' ? (
        <UnitsInput view={view} onSave={(installed, budgeted) => typedUpdate.mutate(unitsProgressBody(installed, budgeted))} saving={typedUpdate.isPending} />
      ) : pctType === 'duration' ? (
        <PercentSlider
          label={t('schedule.progress', { defaultValue: 'Progress' })}
          value={toNum(view.progress_pct ?? '0')}
          remaining={view.remaining_duration}
          onCommit={(p) => typedUpdate.mutate({ percent_complete_type: 'duration', percent: p })}
          saving={typedUpdate.isPending}
        />
      ) : hasSteps ? (
        <div className="rounded-md bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
          <Badge variant="neutral">{t('schedule.managed_by_steps', { defaultValue: 'Managed by steps' })}</Badge>
          <span className="ml-2">
            {t('schedule.rolled_up_pct', { defaultValue: 'Rolled-up: {{pct}}%', pct: view.progress_pct ?? '0' })}
          </span>
        </div>
      ) : (
        <PercentSlider
          label={t('schedule.progress', { defaultValue: 'Progress' })}
          value={toNum(view.progress_pct ?? '0')}
          remaining={view.remaining_duration}
          editableRemaining
          onCommit={(p, rd) => typedUpdate.mutate({ percent_complete_type: 'physical', percent: p, ...(rd != null ? { remaining_duration: rd } : {}) })}
          saving={typedUpdate.isPending}
        />
      )}

      {/* steps (physical only) */}
      {pctType === 'physical' && (
        <StepChecklist
          activityId={activityId}
          steps={steps.data ?? []}
          loading={steps.isLoading}
          onChanged={() => {
            steps.refetch();
            // The parent % is recomputed server-side; re-seed the view.
            scheduleApi.updateProgressTyped(activityId, {}).then(applyResult);
          }}
        />
      )}
    </div>
  );
}

function UnitsInput({
  view,
  onSave,
  saving,
}: {
  view: TypedActivityView;
  onSave: (installed: string, budgeted: string) => void;
  saving: boolean;
}) {
  const { t } = useTranslation();
  const [installed, setInstalled] = useState(view.installed_units ?? '');
  const [budgeted, setBudgeted] = useState(view.budgeted_units ?? '');
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col text-xs text-content-secondary">
        {t('schedule.installed_units', { defaultValue: 'Installed' })}
        <Input type="number" min={0} value={installed} onChange={(e) => setInstalled(e.target.value)} className="mt-1 w-32" />
      </label>
      <label className="flex flex-col text-xs text-content-secondary">
        {t('schedule.budgeted_units', { defaultValue: 'Budgeted' })}
        <Input type="number" min={0} value={budgeted} onChange={(e) => setBudgeted(e.target.value)} className="mt-1 w-32" />
      </label>
      <div className="flex flex-col text-xs text-content-secondary">
        {t('schedule.derived_pct', { defaultValue: 'Derived %' })}
        <span className="mt-1 py-1.5 text-sm font-semibold text-content-primary">{view.progress_pct ?? '0'}%</span>
      </div>
      <Button variant="secondary" onClick={() => onSave(installed, budgeted)} loading={saving}>
        {t('common.save', { defaultValue: 'Save' })}
      </Button>
      {view.remaining_duration != null && (
        <span className="pb-1.5 text-xs text-content-secondary">
          {t('schedule.remaining_days', { defaultValue: 'Remaining: {{n}} working days', n: view.remaining_duration })}
        </span>
      )}
    </div>
  );
}

function PercentSlider({
  label,
  value,
  remaining,
  editableRemaining,
  onCommit,
  saving,
}: {
  label: string;
  value: number;
  remaining: number | null;
  editableRemaining?: boolean;
  onCommit: (pct: number, remaining?: number) => void;
  saving: boolean;
}) {
  const { t } = useTranslation();
  const [pct, setPct] = useState(value);
  const [rd, setRd] = useState<string>(remaining != null ? String(remaining) : '');
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <label className="text-xs text-content-secondary">{label}</label>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={pct}
          onChange={(e) => setPct(Number(e.target.value))}
          className="flex-1 accent-oe-blue"
        />
        <span className="w-12 text-right text-sm font-semibold text-content-primary">{pct}%</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {editableRemaining ? (
          <label className="flex items-center gap-2 text-xs text-content-secondary">
            {t('schedule.remaining_days_label', { defaultValue: 'Remaining (working days)' })}
            <Input type="number" min={0} value={rd} onChange={(e) => setRd(e.target.value)} className="w-24" />
          </label>
        ) : (
          remaining != null && (
            <span className="text-xs text-content-secondary">
              {t('schedule.remaining_days', { defaultValue: 'Remaining: {{n}} working days', n: remaining })}
            </span>
          )
        )}
        <Button
          variant="secondary"
          onClick={() => onCommit(pct, editableRemaining && rd !== '' ? Number(rd) : undefined)}
          loading={saving}
        >
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </div>
  );
}

function StepChecklist({
  activityId,
  steps,
  loading,
  onChanged,
}: {
  activityId: string;
  steps: import('./api').ActivityStep[];
  loading: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [newName, setNewName] = useState('');

  const tw = useMemo(() => totalWeight(steps), [steps]);
  const rolled = useMemo(() => rollupSteps(steps), [steps]);

  const add = useMutation({
    mutationFn: () => scheduleApi.createStep(activityId, { name: newName || t('schedule.step', { defaultValue: 'Step' }), weight: 1, percent_complete: 0 }),
    onSuccess: () => {
      setNewName('');
      onChanged();
    },
    onError: () => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('schedule.step_add_failed', { defaultValue: 'Could not add the step.' }) }),
  });
  const update = useMutation({
    mutationFn: (args: { id: string; data: Parameters<typeof scheduleApi.updateStep>[1] }) => scheduleApi.updateStep(args.id, args.data),
    onSuccess: onChanged,
  });
  const remove = useMutation({
    mutationFn: (id: string) => scheduleApi.deleteStep(id),
    onSuccess: onChanged,
  });

  return (
    <div className="rounded-lg border border-border-light">
      <div className="flex items-center gap-1.5 border-b border-border-light px-3 py-2 text-xs font-semibold text-content-primary">
        <ListChecks size={14} /> {t('schedule.steps', { defaultValue: 'Weighted steps' })}
      </div>
      {loading ? (
        <div className="flex items-center gap-2 p-3 text-xs text-content-secondary">
          <Loader2 size={13} className="animate-spin" /> {t('common.loading', { defaultValue: 'Loading…' })}
        </div>
      ) : (
        <ul className="divide-y divide-border-light">
          {steps.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
              <Input
                defaultValue={s.name}
                onBlur={(e) => e.target.value !== s.name && update.mutate({ id: s.id, data: { name: e.target.value } })}
                className="min-w-[10rem] flex-1"
                aria-label={t('schedule.step_name', { defaultValue: 'Step name' })}
              />
              <label className="flex items-center gap-1 text-[11px] text-content-tertiary">
                {t('schedule.step_weight', { defaultValue: 'Weight' })}
                <Input
                  type="number"
                  min={0}
                  defaultValue={s.weight}
                  onBlur={(e) => toNum(e.target.value) !== toNum(s.weight) && update.mutate({ id: s.id, data: { weight: Number(e.target.value) } })}
                  className="w-16"
                />
              </label>
              <label className="flex items-center gap-1 text-[11px] text-content-tertiary">
                %
                <Input
                  type="number"
                  min={0}
                  max={100}
                  defaultValue={s.percent_complete}
                  onBlur={(e) => toNum(e.target.value) !== toNum(s.percent_complete) && update.mutate({ id: s.id, data: { percent_complete: Number(e.target.value) } })}
                  className="w-16"
                />
              </label>
              <button
                type="button"
                title={t('schedule.milestone', { defaultValue: 'Milestone' })}
                aria-pressed={s.is_milestone}
                onClick={() => update.mutate({ id: s.id, data: { is_milestone: !s.is_milestone } })}
                className={`rounded p-1 ${s.is_milestone ? 'text-amber-600' : 'text-content-tertiary hover:text-content-secondary'}`}
              >
                <Flag size={14} />
              </button>
              <button
                type="button"
                title={t('common.delete', { defaultValue: 'Delete' })}
                onClick={() => remove.mutate(s.id)}
                className="rounded p-1 text-content-tertiary hover:text-red-600"
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
          {!steps.length && (
            <li className="px-3 py-3 text-xs text-content-secondary">
              {t('schedule.no_steps', { defaultValue: 'No steps yet. Add one to roll progress up from weighted parts.' })}
            </li>
          )}
        </ul>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border-light px-3 py-2">
        <div className="flex items-center gap-2">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t('schedule.new_step_placeholder', { defaultValue: 'New step name…' })}
            className="w-48"
          />
          <Button variant="ghost" icon={<Plus size={14} />} onClick={() => add.mutate()} loading={add.isPending}>
            {t('schedule.add_step', { defaultValue: 'Add step' })}
          </Button>
        </div>
        <div className="text-xs text-content-secondary">
          {tw === 0 && steps.length > 0 && (
            <Badge variant="warning" className="mr-2">
              {t('schedule.all_steps_zero_weight', { defaultValue: 'All weights zero' })}
            </Badge>
          )}
          {t('schedule.rolled_up', { defaultValue: 'Rolled-up' })}:{' '}
          <span className="font-semibold text-content-primary">{fmtPercent(rolled)}</span>
        </div>
      </div>
    </div>
  );
}

export default ProgressRigorPanel;
