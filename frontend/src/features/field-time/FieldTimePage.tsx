// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field Time - the foreman's end-of-day record of who and which machine
 * worked, how long, and against which cost code. Scoped to the active
 * project: a summary, a filterable list of timesheets, and a full editor
 * (opened per timesheet) for adding cost-coded labour and plant lines and
 * running them through the submit / approve / reverse flow.
 */

import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Clock,
  ClipboardCheck,
  HardHat,
  PenLine,
  Tag,
  ArrowRight,
  Wrench,
  ChevronRight,
  Loader2,
} from 'lucide-react';
import {
  Button,
  Badge,
  CollapsibleSection,
  EmptyState,
  ErrorState,
  KpiBand,
  PageHeader,
} from '@/shared/ui';
import type { KpiBandItem } from '@/shared/ui';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildFieldTimeInsights } from './fieldTimeInsights';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { todayLocalISO } from '@/shared/lib/dates';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { TimesheetEditor } from './TimesheetEditor';
import { OfflineDayRecorder } from './OfflineDayRecorder';
import { WorkingTimeRecordPanel } from './WorkingTimeRecord';
import { ClockPanel } from './ClockPanel';
import { ClockApprovals } from './ClockApprovals';
import { ClockEventsLog } from './ClockEventsLog';
import { ClockSettingsCard } from './ClockSettingsCard';
import { GeofenceEditor } from './GeofenceEditor';
import { useClockStatus } from './clockApi';
import {
  listTimesheets,
  fetchTimesheetSummary,
  createTimesheet,
  formatHours,
  type FieldTimesheet,
  type TimesheetStatus,
} from './api';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

const STATUS_BADGE: Record<TimesheetStatus, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'warning',
  approved: 'success',
  reversed: 'error',
};

const STATUS_ORDER: TimesheetStatus[] = ['draft', 'submitted', 'approved', 'reversed'];

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer: what Field Time is for and how it connects.
 *
 * Step three carries the point most people miss. Daywork is recovered against
 * a variation and measured work against the bill, so a week where daywork
 * quietly grows is a week where the final account is drifting.
 */
function HowFieldTimeWorks() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <HardHat size={14} className="text-oe-blue" />,
      title: t('field_time.flow_1_title', { defaultValue: 'Book the day' }),
      desc: t('field_time.flow_1_desc', {
        defaultValue:
          'Record labour and plant hours as they happen, from the field app or here, one line per gang and activity.',
      }),
    },
    {
      icon: <Tag size={14} className="text-oe-blue" />,
      title: t('field_time.flow_2_title', { defaultValue: 'Code the hours' }),
      desc: t('field_time.flow_2_desc', {
        defaultValue:
          'Put every line against a cost code. Hours without a code cannot be recovered against anything later.',
      }),
    },
    {
      icon: <PenLine size={14} className="text-oe-blue" />,
      title: t('field_time.flow_3_title', { defaultValue: 'Mark the basis' }),
      desc: t('field_time.flow_3_desc', {
        defaultValue:
          'Flag daywork lines. Daywork is recovered against a variation, measured work against the bill, and the two must not be mixed.',
      }),
    },
    {
      icon: <ClipboardCheck size={14} className="text-oe-blue" />,
      title: t('field_time.flow_4_title', { defaultValue: 'Approve and report' }),
      desc: t('field_time.flow_4_desc', {
        defaultValue:
          'A submitted sheet is a claim until someone approves it. Approved hours land in cost reporting and the valuation.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="field_time.how"
      icon={<Clock size={15} className="text-oe-blue" />}
      title={t('field_time.flow_title', { defaultValue: 'How Field Time fits together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('field_time.flow_intro', {
          defaultValue:
            'Turn hours worked on site into hours a valuation can defend: book the day against a cost code, mark what was daywork rather than measured work, get the sheet approved, and let the approved hours feed cost reporting.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('field_time.flow_connects', { defaultValue: 'Connects with:' })}
          </span>{' '}
          <ModLink to="/variations">
            {t('field_time.mod_variations', { defaultValue: 'Variations' })}
          </ModLink>{' '}
          · <ModLink to="/costs">{t('field_time.mod_cost', { defaultValue: 'Cost control' })}</ModLink>{' '}
          · <ModLink to="/field">{t('field_time.mod_field', { defaultValue: 'Field app' })}</ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

export function FieldTimePage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('field_time.title', { defaultValue: 'Field Time' })}
        subtitle={t('field_time.subtitle', {
          defaultValue:
            'Cost-coded, signed timesheets for the labour and plant that worked on site each day.',
        })}
      />
      <RequiresProject>
        <FieldTimeContent />
      </RequiresProject>
    </div>
  );
}

type FieldTab = 'timesheets' | 'clock' | 'approvals' | 'geofences' | 'settings';
const FIELD_TABS: FieldTab[] = ['timesheets', 'clock', 'approvals', 'geofences', 'settings'];

function FieldTimeContent() {
  const { t } = useTranslation();
  const projectId = useActiveProjectId();
  const [params, setParams] = useSearchParams();
  const raw = params.get('tab');
  const tab: FieldTab = FIELD_TABS.includes(raw as FieldTab) ? (raw as FieldTab) : 'timesheets';
  // A timesheet built from the clock log opens in the timesheets tab's editor.
  const [openId, setOpenId] = useState<string | null>(null);
  const statusQ = useClockStatus(projectId);
  const pending = statusQ.data?.pending_approvals ?? 0;

  const goTab = (next: FieldTab) => {
    const p = new URLSearchParams(params);
    if (next === 'timesheets') p.delete('tab');
    else p.set('tab', next);
    setParams(p, { replace: true });
  };

  const labels: Record<FieldTab, string> = {
    timesheets: t('field_clock.tab_timesheets', { defaultValue: 'Timesheets' }),
    clock: t('field_clock.tab_clock', { defaultValue: 'Clock' }),
    approvals: t('field_clock.tab_approvals', { defaultValue: 'Approvals' }),
    geofences: t('field_clock.tab_geofences', { defaultValue: 'Geofences' }),
    settings: t('field_clock.tab_settings', { defaultValue: 'Settings' }),
  };

  return (
    <div className="space-y-5">
      <div
        role="tablist"
        aria-label={t('field_clock.tabs_label', { defaultValue: 'Field time sections' })}
        className="-mx-1 flex gap-1 overflow-x-auto border-b border-border-light px-1"
      >
        {FIELD_TABS.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            onClick={() => goTab(k)}
            className={
              'min-h-[44px] shrink-0 whitespace-nowrap border-b-2 px-4 text-sm font-medium transition-colors ' +
              (tab === k
                ? 'border-oe-blue text-oe-blue-text'
                : 'border-transparent text-content-secondary hover:text-content-primary')
            }
          >
            {labels[k]}
            {k === 'approvals' && pending > 0 && (
              <span className="ml-1.5 rounded-full bg-semantic-warning-bg px-1.5 py-0.5 text-2xs font-semibold text-semantic-warning">
                {pending}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === 'timesheets' && (
        <TimesheetsTab externalOpenId={openId} onExternalOpened={() => setOpenId(null)} />
      )}
      {tab === 'clock' && <ClockPanel projectId={projectId} />}
      {tab === 'approvals' && (
        <div className="space-y-6">
          <ClockApprovals projectId={projectId} />
          <ClockEventsLog
            projectId={projectId}
            onOpenTimesheet={(id) => {
              setOpenId(id);
              goTab('timesheets');
            }}
          />
        </div>
      )}
      {tab === 'geofences' && <GeofenceEditor projectId={projectId} />}
      {tab === 'settings' && <ClockSettingsCard projectId={projectId} />}
    </div>
  );
}

function TimesheetsTab({
  externalOpenId,
  onExternalOpened,
}: {
  externalOpenId: string | null;
  onExternalOpened: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useActiveProjectId();

  const [selectedId, setSelectedId] = useState<string | null>(externalOpenId);
  useEffect(() => {
    if (externalOpenId) onExternalOpened();
  }, [externalOpenId, onExternalOpened]);
  const [statusFilter, setStatusFilter] = useState<TimesheetStatus | ''>('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  // Null means nobody has chosen on this screen yet, which is not the same as
  // choosing none: with no choice the page follows what the project's own
  // timesheets already say, so a site that records its working time keeps doing
  // so without anybody re-ticking a box every morning.
  const [regimeChoice, setRegimeChoice] = useState<string | null>(null);

  const listQ = useQuery({
    queryKey: ['field-time', 'list', projectId, statusFilter, dateFrom, dateTo],
    queryFn: () =>
      listTimesheets(projectId, {
        status: statusFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: 200,
      }),
    enabled: !!projectId,
  });

  const summaryQ = useQuery({
    queryKey: ['field-time', 'summary', projectId],
    queryFn: () => fetchTimesheetSummary(projectId),
    enabled: !!projectId,
  });

  // What this project already does, read off the days it has recorded rather
  // than kept in a second place that could disagree with them. A choice made in
  // the panel below overrides it for the rest of the session.
  const observedRegime = useMemo(
    () => (listQ.data?.items ?? []).find((ts) => ts.working_time_regime)?.working_time_regime ?? '',
    [listQ.data],
  );
  const regime = regimeChoice ?? observedRegime;

  const createMut = useMutation({
    mutationFn: () =>
      createTimesheet({
        project_id: projectId,
        date: todayLocalISO(),
        working_time_regime: regime || null,
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['field-time', 'list'] });
      queryClient.invalidateQueries({ queryKey: ['field-time', 'summary'] });
      setSelectedId(created.id);
    },
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const summary = summaryQ.data;
  const kpiItems = useMemo<KpiBandItem[]>(() => {
    if (!summary) return [];
    return [
      {
        key: 'total',
        label: t('field_time.kpi_total', { defaultValue: 'Timesheets' }),
        value: summary.total,
        icon: Clock,
      },
      {
        key: 'labour',
        label: t('field_time.labour_hours', { defaultValue: 'Labour hours' }),
        value: formatHours(summary.labour_hours),
        icon: HardHat,
        tone: 'blue' as const,
      },
      {
        key: 'plant',
        label: t('field_time.plant_hours', { defaultValue: 'Plant hours' }),
        value: formatHours(summary.plant_hours),
        icon: Wrench,
      },
      {
        // Sheets, not hours, and submitted only. The two tiles either side of
        // it are hours, and the Insights panel carries an hours figure over a
        // wider population (drafts included), so this label has to name both
        // its unit and its scope or the two read as one number disagreeing.
        key: 'submitted',
        label: t('field_time.kpi_awaiting', { defaultValue: 'Sheets awaiting approval' }),
        value: summary.by_status.submitted ?? 0,
        tone: 'warning' as const,
      },
    ];
  }, [summary, t]);

  const timesheets = listQ.data?.items ?? [];

  // Line level, not sheet level: cost code and daywork live on the line, and
  // the KPI band above already answers "how many sheets and how many hours".
  const insights = useModuleInsights('field-time', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildFieldTimeInsights(timesheets, t),
    [timesheets, t],
  );

  return (
    <div className="space-y-5">
      <HowFieldTimeWorks />

      {/* Above the list, not inside a tab: a foreman who cannot find where to
          record a day without signal will record it on paper instead. */}
      <OfflineDayRecorder
        projectId={projectId}
        onRecorded={() => {
          void listQ.refetch();
          void summaryQ.refetch();
        }}
      />

      {/* Collapsed until somebody opens it, and empty of any obligation until
          somebody chooses a regime inside it. A German legal duty must not
          arrive on the screen of a foreman in Chile who did not ask for it. */}
      <WorkingTimeRecordPanel
        projectId={projectId}
        regime={regime}
        onRegimeChange={setRegimeChoice}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {/* The toggle lives here rather than in PageHeader actions because
              FieldTimePage owns the header while this component owns the data. */}
          <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as TimesheetStatus | '')}
            aria-label={t('field_time.filter_status', { defaultValue: 'Filter by status' })}
            className="h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary"
          >
            <option value="">{t('field_time.all_statuses', { defaultValue: 'All statuses' })}</option>
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>
                {t(`field_time.status_${s}`, { defaultValue: s })}
              </option>
            ))}
          </select>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            aria-label={t('field_time.date_from', { defaultValue: 'From date' })}
            className="h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            aria-label={t('field_time.date_to', { defaultValue: 'To date' })}
            className="h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary"
          />
        </div>
        <Button
          variant="primary"
          size="md"
          icon={<Plus size={16} />}
          loading={createMut.isPending}
          onClick={() => createMut.mutate()}
        >
          {t('field_time.new_timesheet', { defaultValue: 'New timesheet' })}
        </Button>
      </div>

      {kpiItems.length > 0 && <KpiBand items={kpiItems} />}

      <InsightsPanel
        open={insights.open}
        title={t('field_time.insights.title', { defaultValue: 'Field time insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      {listQ.isLoading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-content-tertiary">
          <Loader2 size={16} className="animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      ) : listQ.isError ? (
        <ErrorState
          title={t('field_time.list_failed', { defaultValue: 'Could not load timesheets' })}
          hint={getErrorMessage(listQ.error)}
          onRetry={() => listQ.refetch()}
        />
      ) : timesheets.length === 0 ? (
        <EmptyState
          icon={<Clock size={28} strokeWidth={1.5} />}
          title={t('field_time.empty_title', { defaultValue: 'No timesheets yet' })}
          description={t('field_time.empty_hint', {
            defaultValue:
              'Create a timesheet here or book time from the field app, then add a line for each gang against its cost code.',
          })}
          action={{
            label: t('field_time.new_timesheet', { defaultValue: 'New timesheet' }),
            onClick: () => createMut.mutate(),
          }}
        />
      ) : (
        <>
          <ul className="flex flex-col gap-2">
            {timesheets.map((ts) => (
              <li key={ts.id}>
                <TimesheetRow timesheet={ts} onOpen={() => setSelectedId(ts.id)} />
              </li>
            ))}
          </ul>
          {/* The page asks for 200 of a 500 ceiling and the filters above are
              applied server-side, so this reports how much of the filtered
              register is on screen. */}
          {listQ.data && <TruncationNotice page={listQ.data} className="mt-2" />}
        </>
      )}

      {selectedId && (
        <TimesheetEditor
          timesheetId={selectedId}
          projectId={projectId}
          workingTimeRegime={regime}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}

function TimesheetRow({
  timesheet,
  onOpen,
}: {
  timesheet: FieldTimesheet;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-3 rounded-lg border border-border-light bg-surface-primary px-4 py-3 text-left transition-colors hover:bg-surface-secondary"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold text-content-primary">
            {timesheet.reference || t('field_time.untitled', { defaultValue: 'Draft timesheet' })}
          </span>
          <Badge variant={STATUS_BADGE[timesheet.status]} size="sm">
            {t(`field_time.status_${timesheet.status}`, { defaultValue: timesheet.status })}
          </Badge>
        </div>
        <div className="mt-0.5 text-xs text-content-tertiary">
          <DateDisplay value={timesheet.date} />
        </div>
      </div>
      <div className="hidden shrink-0 items-center gap-4 text-xs text-content-secondary sm:flex">
        <span className="inline-flex items-center gap-1 tabular-nums">
          <HardHat size={13} className="text-oe-blue" />
          {t('field_time.hours_value', {
            defaultValue: '{{hours}} h',
            hours: formatHours(timesheet.labour_hours),
          })}
        </span>
        <span className="inline-flex items-center gap-1 tabular-nums">
          <Wrench size={13} />
          {t('field_time.hours_value', {
            defaultValue: '{{hours}} h',
            hours: formatHours(timesheet.plant_hours),
          })}
        </span>
        <span className="tabular-nums">
          {t('field_time.lines_count', {
            defaultValue: '{{count}} lines',
            count: timesheet.lines.length,
          })}
        </span>
      </div>
      <ChevronRight size={16} className="shrink-0 text-content-tertiary" />
    </button>
  );
}
