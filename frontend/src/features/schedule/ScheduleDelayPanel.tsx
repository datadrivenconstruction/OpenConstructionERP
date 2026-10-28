// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// Guided forensic delay analysis panel (T2.2). A persisted, exhibit-producing
// flow over a base schedule, driven by the /v1/schedule-advanced/delay-analyses
// endpoints (see derived contract in features/schedule-advanced/api.ts):
//   - list the project's delay analyses + a "New analysis" create form
//     (name + method) [useQuery + useMutation]
//   - select one -> show its causative delay events + an "Add delay event" form
//     (title / responsibility / type via risk category / affected activity /
//      start-end work-days). A single "Auto fragnet" button synthesises a
//      default fragnet for an event (no full fragnet editor).
//   - "Run analysis" computes the method and renders the headline result:
//     total excusable/compensable (net entitlement) days, concurrent days and
//     the per-window attribution table (gross slip -> employer / contractor /
//     neutral / concurrent / net days, with the narrative).
//   - secondary actions once computed: "Issue" (e-sign, freeze) and
//     "Raise EOT claim" (pre-fills an Extension-of-Time claim).
//
// Activity ids/refs arrive as raw UUID strings; an optional ``activitiesById``
// name map (the caller already holds the Gantt rows) renders readable labels.
// Industry terms (TIA, windows, as-planned vs as-built, fragnet, excusable /
// compensable, EOT) are used deliberately and are vendor-neutral.

import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Scale,
  Plus,
  Play,
  Loader2,
  FileSignature,
  Gavel,
  ChevronRight,
  Zap,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react';

import { Button, Card, Badge, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listDelayAnalyses,
  getDelayAnalysis,
  createDelayAnalysis,
  addDelayEvent,
  autoDelayFragnet,
  computeDelayAnalysis,
  issueDelayAnalysis,
  raiseEotClaim,
  type DelayAnalysis,
  type DelayAnalysisListItem,
  type DelayMethod,
  type DelayResponsibility,
  type DelayStatus,
} from '@/features/schedule-advanced/api';

// English fallbacks for the computed `schedule.delay.status_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const DELAY_STATUS_LABELS: Record<string, string> = {
  draft: 'Draft', computed: 'Computed', issued: 'Issued'
};


interface ScheduleDelayPanelProps {
  scheduleId: string;
  projectId: string;
  /** Optional id -> display name map so events/windows show names, not UUIDs. */
  activitiesById?: Record<string, string>;
}

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls =
  'block text-2xs font-medium uppercase tracking-wide text-content-secondary mb-1';

const METHODS: DelayMethod[] = [
  'tia',
  'windows',
  'as_planned_vs_as_built',
  'impacted_as_planned',
  'collapsed_as_built',
];

const RESPONSIBILITIES: DelayResponsibility[] = [
  'employer',
  'contractor',
  'neutral',
  'shared',
];

const STATUS_BADGE: Record<DelayStatus, 'neutral' | 'blue' | 'success'> = {
  draft: 'neutral',
  computed: 'blue',
  issued: 'success',
};

export function ScheduleDelayPanel({
  scheduleId,
  projectId,
  activitiesById,
}: ScheduleDelayPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [selectedId, setSelectedId] = useState<string | null>(null);

  const nameFor = useMemo(
    () => (ref: string) => (ref ? (activitiesById?.[ref] ?? ref) : '-'),
    [activitiesById],
  );

  const methodLabel = useMemo(
    () =>
      (m: DelayMethod): string =>
        ({
          tia: t('schedule.delay.method_tia', { defaultValue: 'Time Impact Analysis (TIA)' }),
          windows: t('schedule.delay.method_windows', { defaultValue: 'Windows analysis' }),
          as_planned_vs_as_built: t('schedule.delay.method_apvab', {
            defaultValue: 'As-planned vs as-built',
          }),
          impacted_as_planned: t('schedule.delay.method_iap', {
            defaultValue: 'Impacted as-planned',
          }),
          collapsed_as_built: t('schedule.delay.method_cab', {
            defaultValue: 'Collapsed as-built',
          }),
        })[m],
    [t],
  );

  /* ── List of analyses ─────────────────────────────────────────────── */
  const listQ = useQuery<DelayAnalysisListItem[]>({
    queryKey: ['schedule', 'delay', 'list', projectId],
    queryFn: () => listDelayAnalyses(projectId),
    enabled: !!projectId,
  });

  /* ── Selected analysis detail ─────────────────────────────────────── */
  const detailQ = useQuery<DelayAnalysis>({
    queryKey: ['schedule', 'delay', 'detail', selectedId],
    queryFn: () => getDelayAnalysis(selectedId as string),
    enabled: !!selectedId,
  });

  const invalidateList = () =>
    queryClient.invalidateQueries({ queryKey: ['schedule', 'delay', 'list', projectId] });
  const invalidateDetail = () =>
    queryClient.invalidateQueries({ queryKey: ['schedule', 'delay', 'detail', selectedId] });

  const toastError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('common.error', { defaultValue: 'Error' }),
      message: getErrorMessage(e),
    });

  /* ── Create analysis ──────────────────────────────────────────────── */
  const [newName, setNewName] = useState('');
  const [newMethod, setNewMethod] = useState<DelayMethod>('windows');

  const createMut = useMutation({
    mutationFn: () =>
      createDelayAnalysis(projectId, {
        name: newName.trim(),
        method: newMethod,
        schedule_id: scheduleId,
      }),
    onSuccess: (data) => {
      setNewName('');
      setSelectedId(data.id);
      invalidateList();
      addToast({
        type: 'success',
        title: t('schedule.delay.created', { defaultValue: 'Analysis created' }),
        message: t('schedule.delay.created_detail', {
          defaultValue: 'Draft "{{name}}" is ready - add delay events, then run it.',
          name: data.name,
        }),
      });
    },
    onError: toastError,
  });

  /* ── Add delay event ──────────────────────────────────────────────── */
  interface EventForm {
    title: string;
    responsibility: DelayResponsibility;
    risk_event_category: string;
    insert_at_activity_ref: string;
    start_workday: string;
    end_workday: string;
    is_concurrent: boolean;
  }
  const EMPTY_EVENT: EventForm = {
    title: '',
    responsibility: 'employer',
    risk_event_category: '',
    insert_at_activity_ref: '',
    start_workday: '',
    end_workday: '',
    is_concurrent: false,
  };
  const [eventForm, setEventForm] = useState<EventForm>(EMPTY_EVENT);

  const addEventMut = useMutation({
    mutationFn: () => {
      if (!selectedId) throw new Error('No analysis selected');
      const startWd = eventForm.start_workday.trim();
      const endWd = eventForm.end_workday.trim();
      return addDelayEvent(selectedId, {
        title: eventForm.title.trim(),
        responsibility: eventForm.responsibility,
        risk_event_category: eventForm.risk_event_category.trim() || undefined,
        insert_at_activity_ref: eventForm.insert_at_activity_ref.trim() || undefined,
        start_workday: startWd === '' ? null : Number(startWd),
        end_workday: endWd === '' ? null : Number(endWd),
        is_concurrent: eventForm.is_concurrent,
      });
    },
    onSuccess: () => {
      setEventForm(EMPTY_EVENT);
      invalidateDetail();
      addToast({
        type: 'success',
        title: t('schedule.delay.event_added', { defaultValue: 'Delay event added' }),
        message: t('schedule.delay.event_added_detail', {
          defaultValue: 'Add more events or run the analysis to attribute the slip.',
        }),
      });
    },
    onError: toastError,
  });

  /* ── Auto-fragnet for an event ────────────────────────────────────── */
  const autoFragnetMut = useMutation({
    mutationFn: (ev: { id: string; ref: string; days: number }) => {
      if (!selectedId) throw new Error('No analysis selected');
      return autoDelayFragnet(selectedId, {
        delay_event_id: ev.id,
        insert_at_activity_ref: ev.ref,
        added_days: ev.days,
      });
    },
    onSuccess: () => {
      invalidateDetail();
      addToast({
        type: 'success',
        title: t('schedule.delay.fragnet_added', { defaultValue: 'Fragnet attached' }),
        message: t('schedule.delay.fragnet_added_detail', {
          defaultValue: 'A default fragnet was synthesised for the event.',
        }),
      });
    },
    onError: toastError,
  });

  /* ── Compute ──────────────────────────────────────────────────────── */
  const computeMut = useMutation({
    mutationFn: () => {
      if (!selectedId) throw new Error('No analysis selected');
      return computeDelayAnalysis(selectedId);
    },
    onSuccess: (data) => {
      invalidateDetail();
      invalidateList();
      addToast({
        type: 'success',
        title: t('schedule.delay.computed', { defaultValue: 'Analysis computed' }),
        message: t('schedule.delay.computed_detail', {
          defaultValue: '{{days}} entitlement day(s) across {{windows}} window(s).',
          days: data.total_entitlement_days,
          windows: data.window_count,
        }),
      });
    },
    onError: toastError,
  });

  /* ── Issue (e-sign) ───────────────────────────────────────────────── */
  const issueMut = useMutation({
    mutationFn: () => {
      if (!selectedId) throw new Error('No analysis selected');
      return issueDelayAnalysis(selectedId);
    },
    onSuccess: () => {
      invalidateDetail();
      invalidateList();
      addToast({
        type: 'success',
        title: t('schedule.delay.issued', { defaultValue: 'Analysis issued' }),
        message: t('schedule.delay.issued_detail', {
          defaultValue: 'The analysis is now e-signed and frozen.',
        }),
      });
    },
    onError: toastError,
  });

  /* ── Raise EOT claim ──────────────────────────────────────────────── */
  const eotMut = useMutation({
    mutationFn: () => {
      if (!selectedId) throw new Error('No analysis selected');
      return raiseEotClaim(selectedId);
    },
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('schedule.delay.eot_raised', { defaultValue: 'EOT claim raised' }),
        message: t('schedule.delay.eot_raised_detail', {
          defaultValue: 'Draft claim created for {{days}} day(s).',
          days: res.requested_days,
        }),
      });
    },
    onError: toastError,
  });

  /* ── Render ───────────────────────────────────────────────────────── */
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]" data-testid="schedule-delay-panel">
      {/* ── Left rail: list + create ──────────────────────────────────── */}
      <div className="space-y-4">
        <Card padding="none">
          <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
            <Scale size={16} className="text-content-secondary" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('schedule.delay.title', { defaultValue: 'Forensic delay analysis' })}
            </h3>
          </div>

          {listQ.isLoading ? (
            <div className="p-4">
              <SkeletonTable rows={4} columns={1} />
            </div>
          ) : listQ.isError ? (
            <div className="p-4">
              <RecoveryCard error={listQ.error} onRetry={() => listQ.refetch()} />
            </div>
          ) : (listQ.data?.length ?? 0) === 0 ? (
            <div className="px-4 py-6">
              <p className="text-sm text-content-tertiary">
                {t('schedule.delay.list_empty', {
                  defaultValue: 'No delay analyses yet. Create one below.',
                })}
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-border-light" data-testid="delay-analysis-list">
              {listQ.data!.map((a) => {
                const active = a.id === selectedId;
                return (
                  <li key={a.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(a.id)}
                      aria-pressed={active}
                      className={`flex w-full items-center gap-2 px-4 py-3 text-left transition-colors ${
                        active ? 'bg-oe-blue-subtle/50' : 'hover:bg-surface-secondary/40'
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-content-primary">
                          {a.name}
                        </p>
                        <p className="mt-0.5 text-2xs text-content-tertiary">
                          {methodLabel(a.method)}
                        </p>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <Badge variant={STATUS_BADGE[a.status]} size="sm">
                          {t(`schedule.delay.status_${a.status}`, { defaultValue: DELAY_STATUS_LABELS[a.status] ?? a.status })}
                        </Badge>
                        {a.status !== 'draft' && (
                          <span className="text-2xs tabular-nums text-content-tertiary">
                            {t('schedule.delay.days_short', {
                              defaultValue: '{{count}}d',
                              count: a.total_entitlement_days,
                            })}
                          </span>
                        )}
                      </div>
                      <ChevronRight size={14} className="shrink-0 text-content-tertiary" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        {/* Create form */}
        <Card padding="md">
          <h4 className="mb-3 text-sm font-semibold text-content-primary">
            {t('schedule.delay.new', { defaultValue: 'New analysis' })}
          </h4>
          <div className="space-y-3">
            <div>
              <label htmlFor="delay-new-name" className={labelCls}>
                {t('schedule.delay.name', { defaultValue: 'Name' })}
              </label>
              <input
                id="delay-new-name"
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={t('schedule.delay.name_ph', {
                  defaultValue: 'e.g. Window 3 - foundation delay',
                })}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="delay-new-method" className={labelCls}>
                {t('schedule.delay.method', { defaultValue: 'Method' })}
              </label>
              <select
                id="delay-new-method"
                value={newMethod}
                onChange={(e) => setNewMethod(e.target.value as DelayMethod)}
                className={inputCls}
              >
                {METHODS.map((m) => (
                  <option key={m} value={m}>
                    {methodLabel(m)}
                  </option>
                ))}
              </select>
            </div>
            <Button
              variant="primary"
              onClick={() => createMut.mutate()}
              disabled={createMut.isPending || newName.trim().length === 0 || !scheduleId}
              icon={
                createMut.isPending ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <Plus size={16} />
                )
              }
            >
              {t('schedule.delay.create', { defaultValue: 'Create analysis' })}
            </Button>
          </div>
        </Card>
      </div>

      {/* ── Right: detail ─────────────────────────────────────────────── */}
      <div className="min-w-0">
        {!selectedId ? (
          <Card padding="md">
            <EmptyState
              icon={<Scale size={28} strokeWidth={1.5} />}
              title={t('schedule.delay.select_empty', {
                defaultValue: 'Select or create an analysis',
              })}
              description={t('schedule.delay.select_empty_desc', {
                defaultValue:
                  'A forensic delay analysis attributes schedule slip to its causes window by window, separating excusable/compensable delay from contractor and concurrent delay - the evidence behind an Extension-of-Time claim.',
              })}
            />
          </Card>
        ) : detailQ.isLoading ? (
          <Card padding="md" data-testid="delay-detail-loading">
            <SkeletonTable rows={6} columns={4} />
          </Card>
        ) : detailQ.isError ? (
          <Card padding="md">
            <RecoveryCard error={detailQ.error} onRetry={() => detailQ.refetch()} />
          </Card>
        ) : detailQ.data ? (
          <DelayDetail
            analysis={detailQ.data}
            nameFor={nameFor}
            methodLabel={methodLabel}
            responsibilities={RESPONSIBILITIES}
            eventForm={eventForm}
            setEventForm={setEventForm}
            onAddEvent={() => addEventMut.mutate()}
            addEventPending={addEventMut.isPending}
            onAutoFragnet={(ev) => autoFragnetMut.mutate(ev)}
            autoFragnetPending={autoFragnetMut.isPending}
            onCompute={() => computeMut.mutate()}
            computePending={computeMut.isPending}
            onIssue={() => issueMut.mutate()}
            issuePending={issueMut.isPending}
            onRaiseEot={() => eotMut.mutate()}
            eotPending={eotMut.isPending}
          />
        ) : null}
      </div>
    </div>
  );
}

/* ── Detail subcomponent ─────────────────────────────────────────────── */

interface EventFormShape {
  title: string;
  responsibility: DelayResponsibility;
  risk_event_category: string;
  insert_at_activity_ref: string;
  start_workday: string;
  end_workday: string;
  is_concurrent: boolean;
}

function DelayDetail({
  analysis,
  nameFor,
  methodLabel,
  responsibilities,
  eventForm,
  setEventForm,
  onAddEvent,
  addEventPending,
  onAutoFragnet,
  autoFragnetPending,
  onCompute,
  computePending,
  onIssue,
  issuePending,
  onRaiseEot,
  eotPending,
}: {
  analysis: DelayAnalysis;
  nameFor: (ref: string) => string;
  methodLabel: (m: DelayMethod) => string;
  responsibilities: DelayResponsibility[];
  eventForm: EventFormShape;
  setEventForm: React.Dispatch<React.SetStateAction<EventFormShape>>;
  onAddEvent: () => void;
  addEventPending: boolean;
  onAutoFragnet: (ev: { id: string; ref: string; days: number }) => void;
  autoFragnetPending: boolean;
  onCompute: () => void;
  computePending: boolean;
  onIssue: () => void;
  issuePending: boolean;
  onRaiseEot: () => void;
  eotPending: boolean;
}) {
  const { t } = useTranslation();
  const isDraft = analysis.status === 'draft';
  const isComputed = analysis.status === 'computed';
  const isIssued = analysis.status === 'issued';
  const hasResult = isComputed || isIssued;

  const respLabel = (r: DelayResponsibility): string =>
    ({
      employer: t('schedule.delay.resp_employer', { defaultValue: 'Employer' }),
      contractor: t('schedule.delay.resp_contractor', { defaultValue: 'Contractor' }),
      neutral: t('schedule.delay.resp_neutral', { defaultValue: 'Neutral' }),
      shared: t('schedule.delay.resp_shared', { defaultValue: 'Shared' }),
    })[r];

  return (
    <div className="space-y-4">
      {/* ── Header + actions ──────────────────────────────────────────── */}
      <Card padding="md">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="truncate text-base font-semibold text-content-primary">
                {analysis.name}
              </h3>
              <Badge variant={STATUS_BADGE[analysis.status]}>
                {t(`schedule.delay.status_${analysis.status}`, { defaultValue: DELAY_STATUS_LABELS[analysis.status] ?? analysis.status })}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-content-secondary">
              {methodLabel(analysis.method)}
              {' · '}
              {t('schedule.delay.apportionment', { defaultValue: 'Apportionment' })}:{' '}
              {analysis.apportionment_method}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={onCompute}
              disabled={computePending || isIssued}
              icon={
                computePending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Play size={14} />
                )
              }
            >
              {hasResult
                ? t('schedule.delay.recompute', { defaultValue: 'Recompute' })
                : t('schedule.delay.run', { defaultValue: 'Run analysis' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={onIssue}
              disabled={issuePending || !isComputed}
              icon={
                issuePending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <FileSignature size={14} />
                )
              }
            >
              {t('schedule.delay.issue', { defaultValue: 'Issue (e-sign)' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={onRaiseEot}
              disabled={eotPending || !hasResult}
              icon={
                eotPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Gavel size={14} />
                )
              }
            >
              {t('schedule.delay.raise_eot', { defaultValue: 'Raise EOT claim' })}
            </Button>
          </div>
        </div>

        {isIssued && (
          <div className="mt-3 flex items-center gap-2 rounded-lg bg-semantic-success-bg px-3 py-2 text-xs text-semantic-success">
            <ShieldCheck size={14} className="shrink-0" />
            {t('schedule.delay.issued_note', {
              defaultValue: 'This analysis is issued and immutable. Recompute and edits are locked.',
            })}
          </div>
        )}
      </Card>

      {/* ── Headline result ───────────────────────────────────────────── */}
      {hasResult ? (
        <Card padding="md" data-testid="delay-result">
          <h4 className="mb-3 text-sm font-semibold text-content-primary">
            {t('schedule.delay.result', { defaultValue: 'Result' })}
          </h4>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat
              label={t('schedule.delay.total_entitlement', {
                defaultValue: 'Excusable / compensable (days)',
              })}
              value={String(analysis.total_entitlement_days)}
              tone={analysis.total_entitlement_days > 0 ? 'warning' : 'neutral'}
            />
            <Stat
              label={t('schedule.delay.concurrent', { defaultValue: 'Concurrent (days)' })}
              value={String(analysis.concurrent_days)}
            />
            <Stat
              label={t('schedule.delay.windows_count', { defaultValue: 'Windows' })}
              value={String(analysis.window_count)}
            />
            <Stat
              label={t('schedule.delay.cp_impact', { defaultValue: 'Critical-path impact' })}
              value={
                analysis.total_entitlement_days > 0
                  ? t('schedule.delay.cp_yes', { defaultValue: 'Yes' })
                  : t('schedule.delay.cp_no', { defaultValue: 'No' })
              }
              tone={analysis.total_entitlement_days > 0 ? 'warning' : 'neutral'}
            />
          </dl>

          {/* Per-window attribution */}
          {analysis.windows.length > 0 ? (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm" data-testid="delay-windows">
                <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
                  <tr>
                    <th className="px-3 py-2 text-left">
                      {t('schedule.delay.window', { defaultValue: 'Window' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('schedule.delay.gross_slip', { defaultValue: 'Gross slip' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('schedule.delay.resp_employer', { defaultValue: 'Employer' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('schedule.delay.resp_contractor', { defaultValue: 'Contractor' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('schedule.delay.resp_neutral', { defaultValue: 'Neutral' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('schedule.delay.concurrent_short', { defaultValue: 'Concurrent' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('schedule.delay.net_entitlement', { defaultValue: 'Net entitlement' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.windows.map((w) => (
                    <tr key={w.id} className="border-t border-border-light align-top">
                      <td className="px-3 py-2">
                        <span className="font-mono tabular-nums text-content-secondary">
                          {w.sequence_order + 1}
                        </span>
                        {w.narrative && (
                          <p className="mt-0.5 max-w-xs text-2xs text-content-tertiary">
                            {w.narrative}
                          </p>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {w.gross_slip_days}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {w.employer_days}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {w.contractor_days}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {w.neutral_days}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {w.concurrent_days}
                      </td>
                      <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums">
                        {w.net_entitlement_days}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-4 text-sm text-content-tertiary">
              {t('schedule.delay.no_windows', {
                defaultValue:
                  'No window breakdown for this method. The headline entitlement above is the result.',
              })}
            </p>
          )}
        </Card>
      ) : (
        <Card padding="md">
          <div className="flex items-start gap-2 text-sm text-content-secondary">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" />
            <p>
              {t('schedule.delay.not_computed', {
                defaultValue:
                  'Not computed yet. Add the causative delay events below, then run the analysis to attribute the slip and total the entitlement.',
              })}
            </p>
          </div>
        </Card>
      )}

      {/* ── Delay events ──────────────────────────────────────────────── */}
      <Card padding="none">
        <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
          <h4 className="text-sm font-semibold text-content-primary">
            {t('schedule.delay.events', { defaultValue: 'Delay events' })}
          </h4>
          <Badge variant="neutral" size="sm">
            {analysis.events.length}
          </Badge>
        </div>

        {analysis.events.length === 0 ? (
          <div className="px-4 py-6 text-sm text-content-tertiary">
            {t('schedule.delay.events_empty', {
              defaultValue: 'No delay events yet. Add the first causative event below.',
            })}
          </div>
        ) : (
          <ul className="divide-y divide-border-light" data-testid="delay-events">
            {analysis.events.map((ev) => {
              const hasFragnet = ev.fragnets.length > 0;
              return (
                <li key={ev.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-content-primary">{ev.title}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-2xs text-content-tertiary">
                        <Badge variant="neutral" size="sm">
                          {respLabel(ev.responsibility)}
                        </Badge>
                        {ev.risk_event_category && (
                          <span className="rounded bg-surface-secondary px-1.5 py-0.5">
                            {ev.risk_event_category}
                          </span>
                        )}
                        {ev.is_concurrent && (
                          <Badge variant="warning" size="sm">
                            {t('schedule.delay.concurrent_tag', { defaultValue: 'Concurrent' })}
                          </Badge>
                        )}
                        {ev.insert_at_activity_ref && (
                          <span title={ev.insert_at_activity_ref}>
                            {t('schedule.delay.at_activity', { defaultValue: 'at' })}{' '}
                            {nameFor(ev.insert_at_activity_ref)}
                          </span>
                        )}
                        {(ev.start_workday != null || ev.end_workday != null) && (
                          <span className="font-mono tabular-nums">
                            {t('schedule.delay.workdays', {
                              defaultValue: 'WD {{start}}-{{end}}',
                              start: ev.start_workday ?? '?',
                              end: ev.end_workday ?? '?',
                            })}
                          </span>
                        )}
                        {hasFragnet && (
                          <Badge variant="blue" size="sm">
                            {t('schedule.delay.has_fragnet', { defaultValue: 'Fragnet' })}
                          </Badge>
                        )}
                      </div>
                    </div>
                    {isDraft && !hasFragnet && ev.insert_at_activity_ref && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          onAutoFragnet({
                            id: ev.id,
                            ref: ev.insert_at_activity_ref,
                            days: Math.max(
                              1,
                              (ev.end_workday ?? 0) - (ev.start_workday ?? 0) || 1,
                            ),
                          })
                        }
                        disabled={autoFragnetPending}
                        icon={
                          autoFragnetPending ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <Zap size={14} />
                          )
                        }
                      >
                        {t('schedule.delay.auto_fragnet', { defaultValue: 'Auto fragnet' })}
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {/* Add event form (draft only) */}
        {isDraft ? (
          <div className="border-t border-border-light bg-surface-secondary/20 px-4 py-4">
            <h5 className="mb-3 text-xs font-semibold uppercase tracking-wide text-content-secondary">
              {t('schedule.delay.add_event', { defaultValue: 'Add delay event' })}
            </h5>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label htmlFor="delay-ev-title" className={labelCls}>
                  {t('schedule.delay.event_title', { defaultValue: 'Title' })}
                </label>
                <input
                  id="delay-ev-title"
                  type="text"
                  value={eventForm.title}
                  onChange={(e) => setEventForm((f) => ({ ...f, title: e.target.value }))}
                  placeholder={t('schedule.delay.event_title_ph', {
                    defaultValue: 'e.g. Late design release for foundations',
                  })}
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor="delay-ev-resp" className={labelCls}>
                  {t('schedule.delay.responsibility', { defaultValue: 'Responsibility' })}
                </label>
                <select
                  id="delay-ev-resp"
                  value={eventForm.responsibility}
                  onChange={(e) =>
                    setEventForm((f) => ({
                      ...f,
                      responsibility: e.target.value as DelayResponsibility,
                    }))
                  }
                  className={inputCls}
                >
                  {responsibilities.map((r) => (
                    <option key={r} value={r}>
                      {respLabel(r)}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="delay-ev-cat" className={labelCls}>
                  {t('schedule.delay.event_type', { defaultValue: 'Type / risk category' })}
                </label>
                <input
                  id="delay-ev-cat"
                  type="text"
                  value={eventForm.risk_event_category}
                  onChange={(e) =>
                    setEventForm((f) => ({ ...f, risk_event_category: e.target.value }))
                  }
                  placeholder={t('schedule.delay.event_type_ph', {
                    defaultValue: 'e.g. design, weather, variation',
                  })}
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor="delay-ev-act" className={labelCls}>
                  {t('schedule.delay.affected_activity', { defaultValue: 'Affected activity (id)' })}
                </label>
                <input
                  id="delay-ev-act"
                  type="text"
                  value={eventForm.insert_at_activity_ref}
                  onChange={(e) =>
                    setEventForm((f) => ({ ...f, insert_at_activity_ref: e.target.value }))
                  }
                  placeholder={t('schedule.delay.affected_activity_ph', {
                    defaultValue: 'activity id the delay hits',
                  })}
                  className={inputCls}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="delay-ev-start" className={labelCls}>
                    {t('schedule.delay.start_wd', { defaultValue: 'Start work-day' })}
                  </label>
                  <input
                    id="delay-ev-start"
                    type="number"
                    value={eventForm.start_workday}
                    onChange={(e) =>
                      setEventForm((f) => ({ ...f, start_workday: e.target.value }))
                    }
                    className={inputCls}
                  />
                </div>
                <div>
                  <label htmlFor="delay-ev-end" className={labelCls}>
                    {t('schedule.delay.end_wd', { defaultValue: 'End work-day' })}
                  </label>
                  <input
                    id="delay-ev-end"
                    type="number"
                    value={eventForm.end_workday}
                    onChange={(e) =>
                      setEventForm((f) => ({ ...f, end_workday: e.target.value }))
                    }
                    className={inputCls}
                  />
                </div>
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-content-secondary sm:col-span-2">
                <input
                  type="checkbox"
                  checked={eventForm.is_concurrent}
                  onChange={(e) =>
                    setEventForm((f) => ({ ...f, is_concurrent: e.target.checked }))
                  }
                  className="h-4 w-4 rounded border-border accent-oe-blue"
                />
                {t('schedule.delay.is_concurrent', {
                  defaultValue: 'Concurrent with a contractor-culpable delay',
                })}
              </label>
            </div>
            <div className="mt-3">
              <Button
                variant="secondary"
                size="sm"
                onClick={onAddEvent}
                disabled={addEventPending || eventForm.title.trim().length === 0}
                icon={
                  addEventPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Plus size={14} />
                  )
                }
              >
                {t('schedule.delay.add_event_btn', { defaultValue: 'Add event' })}
              </Button>
            </div>
          </div>
        ) : (
          <div className="border-t border-border-light px-4 py-3 text-2xs text-content-tertiary">
            {t('schedule.delay.events_locked', {
              defaultValue: 'Events can only be edited while the analysis is a draft.',
            })}
          </div>
        )}
      </Card>
    </div>
  );
}

/* ── helpers ─────────────────────────────────────────────────────────── */

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'warning';
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
      <dt className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd
        className={
          'mt-0.5 text-xl font-bold tabular-nums ' +
          (tone === 'warning' ? 'text-semantic-warning' : 'text-content-primary')
        }
      >
        {value}
      </dd>
    </div>
  );
}

export default ScheduleDelayPanel;
