// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <TimesheetEditor> - open a single field timesheet in a full-width modal.
 *
 * While the sheet is a draft the foreman can add, edit and delete labour and
 * plant lines, with a live labour / plant hours rollup and a validation
 * panel. The lifecycle actions (submit, approve, reverse) live in the footer
 * and follow the backend's draft -> submitted -> approved -> reversed flow;
 * once approved the sheet is read-only and only a reversal is offered.
 */

import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Send, CheckCircle2, RotateCcw, Trash2, HardHat, Wrench, ListChecks } from 'lucide-react';
import { Button, Badge, WideModal, ErrorState, DateDisplay } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { listResources } from '@/features/resources/api';
import { listEquipment } from '@/features/equipment/api';
import { listVariationRequests } from '@/features/variations/api';
import { listSubcontractors } from '@/features/subcontractors/api';
import { TimesheetLineRow, type PickOption } from './TimesheetLineRow';
import { LineComposer } from './LineComposer';
import { ValidationPanel } from './ValidationPanel';
import {
  fetchTimesheet,
  fetchTimesheetValidation,
  updateTimesheet,
  deleteTimesheet,
  addLine,
  updateLine,
  deleteLine,
  submitTimesheet,
  approveTimesheet,
  reverseTimesheet,
  listWorkingTimeRegimes,
  formatHours,
  type FieldTimesheet,
  type TimesheetStatus,
  type LineCreatePayload,
  type LineUpdatePayload,
} from './api';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

const STATUS_BADGE: Record<TimesheetStatus, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'warning',
  approved: 'success',
  reversed: 'error',
};

function joinLabel(...parts: (string | null | undefined)[]): string {
  const cleaned = parts.map((p) => (p ?? '').trim()).filter((p) => p.length > 0);
  return cleaned.join(' - ');
}

export interface TimesheetEditorProps {
  timesheetId: string;
  projectId: string;
  /**
   * The statutory working-time regime the page is set to, or '' for none. It
   * only decides whether the controls for one are offered here; what the sheet
   * is actually recorded under is its own `working_time_regime`.
   */
  workingTimeRegime?: string;
  onClose: () => void;
}

export function TimesheetEditor({
  timesheetId,
  projectId,
  workingTimeRegime = '',
  onClose,
}: TimesheetEditorProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [reverseOpen, setReverseOpen] = useState(false);
  const [reverseNote, setReverseNote] = useState('');

  const detailKey = ['field-time', 'detail', timesheetId] as const;

  const detailQ = useQuery({
    queryKey: detailKey,
    queryFn: () => fetchTimesheet(timesheetId),
  });

  const validationQ = useQuery({
    queryKey: ['field-time', 'validation', timesheetId],
    queryFn: () => fetchTimesheetValidation(timesheetId),
  });

  const resourcesQ = useQuery({
    // Same scoping as the day recorder, and the same key: a timesheet line
    // belongs to one project, so the picker must offer that project's roster
    // and the unhomed company pool, nothing else.
    queryKey: ['resources', 'list', 'field-time', projectId],
    queryFn: () => listResources({ limit: 500, project_id: projectId }),
    enabled: !!projectId,
  });

  const equipmentQ = useQuery({
    queryKey: ['equipment', 'list', 'field-time'],
    queryFn: () => listEquipment({ limit: 500 }),
  });

  const variationsQ = useQuery({
    queryKey: ['variations', 'requests', projectId, 'field-time'],
    queryFn: () => listVariationRequests({ project_id: projectId, limit: 200 }),
    enabled: !!projectId,
  });

  const labour: PickOption[] = useMemo(
    () =>
      (resourcesQ.data?.items ?? [])
        .filter((r) => r.resource_type !== 'equipment')
        .map((r) => ({ id: r.id, label: joinLabel(r.code, r.name) || r.id })),
    [resourcesQ.data],
  );

  const plant: PickOption[] = useMemo(
    () => (equipmentQ.data?.items ?? []).map((e) => ({ id: e.id, label: joinLabel(e.code, e.name) || e.id })),
    [equipmentQ.data],
  );

  const variations: PickOption[] = useMemo(
    () => (variationsQ.data?.items ?? []).map((v) => ({ id: v.id, label: joinLabel(v.code, v.title) || v.id })),
    [variationsQ.data],
  );

  // The working-time controls appear when this sheet is recorded under a regime,
  // or when the page is set to record new days under one. Everywhere else the
  // editor is the editor it has always been.
  const showWorkingTime = !!(detailQ.data?.working_time_regime || workingTimeRegime);

  const regimesQ = useQuery({
    queryKey: ['field-time', 'working-time-regimes'],
    queryFn: listWorkingTimeRegimes,
    staleTime: Infinity,
    enabled: showWorkingTime,
  });

  const subcontractorsQ = useQuery({
    queryKey: ['subcontractors', 'list', 'field-time'],
    // 200 is the route ceiling. This asked for 500, which FastAPI rejects with
    // a 422 rather than trimming, so the employer picker was empty rather than
    // short and a worker could not be attributed to their firm at all.
    queryFn: () => listSubcontractors({ limit: 200, active_only: true }),
    enabled: showWorkingTime,
  });

  const employers: PickOption[] = useMemo(
    () => (subcontractorsQ.data?.items ?? []).map((s) => ({ id: s.id, label: s.legal_name || s.id })),
    [subcontractorsQ.data],
  );

  // Shared post-mutation cache sync: adopt the returned timesheet as the
  // detail cache, then refresh the surrounding lists and the validation panel.
  const applyUpdated = (updated: FieldTimesheet) => {
    queryClient.setQueryData(detailKey, updated);
    queryClient.invalidateQueries({ queryKey: ['field-time', 'validation', timesheetId] });
    queryClient.invalidateQueries({ queryKey: ['field-time', 'list'] });
    queryClient.invalidateQueries({ queryKey: ['field-time', 'summary'] });
  };

  const onMutationError = (e: unknown) => {
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
  };

  const headerMut = useMutation({
    mutationFn: (payload: { date?: string; note?: string | null; working_time_regime?: string | null }) =>
      updateTimesheet(timesheetId, payload),
    onSuccess: applyUpdated,
    onError: onMutationError,
  });

  const addLineMut = useMutation({
    mutationFn: (payload: LineCreatePayload) => addLine(timesheetId, payload),
    onSuccess: applyUpdated,
    onError: onMutationError,
  });

  const updateLineMut = useMutation({
    mutationFn: ({ lineId, payload }: { lineId: string; payload: LineUpdatePayload }) =>
      updateLine(timesheetId, lineId, payload),
    onSuccess: applyUpdated,
    onError: onMutationError,
  });

  const deleteLineMut = useMutation({
    mutationFn: (lineId: string) => deleteLine(timesheetId, lineId),
    onSuccess: applyUpdated,
    onError: onMutationError,
  });

  const submitMut = useMutation({
    mutationFn: () => submitTimesheet(timesheetId),
    onSuccess: (updated) => {
      applyUpdated(updated);
      addToast({
        type: 'success',
        title: '',
        message: t('field_time.submitted', { defaultValue: 'Timesheet submitted for approval' }),
      });
    },
    onError: (e) => {
      // Surface the blocking validation and refresh the panel so the foreman
      // can see exactly what needs fixing before re-submitting.
      queryClient.invalidateQueries({ queryKey: ['field-time', 'validation', timesheetId] });
      onMutationError(e);
    },
  });

  const approveMut = useMutation({
    mutationFn: () => approveTimesheet(timesheetId),
    onSuccess: (updated) => {
      applyUpdated(updated);
      addToast({
        type: 'success',
        title: '',
        message: t('field_time.approved', { defaultValue: 'Timesheet approved' }),
      });
    },
    onError: onMutationError,
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteTimesheet(timesheetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['field-time', 'list'] });
      queryClient.invalidateQueries({ queryKey: ['field-time', 'summary'] });
      addToast({
        type: 'success',
        title: '',
        message: t('field_time.deleted', { defaultValue: 'Draft timesheet deleted' }),
      });
      onClose();
    },
    onError: onMutationError,
  });

  const reverseMut = useMutation({
    mutationFn: (note: string) => reverseTimesheet(timesheetId, { note: note || null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['field-time'] });
      addToast({
        type: 'success',
        title: '',
        message: t('field_time.reversed', { defaultValue: 'Timesheet reversed' }),
      });
      setReverseOpen(false);
      onClose();
    },
    onError: onMutationError,
  });

  const timesheet = detailQ.data;
  const isDraft = timesheet?.status === 'draft';
  const lifecycleBusy =
    submitMut.isPending || approveMut.isPending || deleteMut.isPending || reverseMut.isPending;

  const title = timesheet?.reference
    ? timesheet.reference
    : t('field_time.new_timesheet', { defaultValue: 'New timesheet' });

  const footer = timesheet ? (
    <div className="flex w-full items-center gap-2">
      {isDraft && (
        <Button
          variant="ghost"
          size="sm"
          icon={<Trash2 size={14} />}
          disabled={lifecycleBusy}
          onClick={() => deleteMut.mutate()}
          className="mr-auto text-semantic-error hover:bg-semantic-error-bg"
        >
          {t('field_time.delete_timesheet', { defaultValue: 'Delete draft' })}
        </Button>
      )}
      <Button variant="secondary" size="sm" onClick={onClose} className={isDraft ? '' : 'ml-auto'}>
        {t('common.close', { defaultValue: 'Close' })}
      </Button>
      {isDraft && (
        <Button
          variant="primary"
          size="sm"
          icon={<Send size={14} />}
          loading={submitMut.isPending}
          disabled={lifecycleBusy}
          onClick={() => submitMut.mutate()}
        >
          {t('field_time.submit', { defaultValue: 'Submit' })}
        </Button>
      )}
      {timesheet.status === 'submitted' && (
        <Button
          variant="primary"
          size="sm"
          icon={<CheckCircle2 size={14} />}
          loading={approveMut.isPending}
          disabled={lifecycleBusy}
          onClick={() => approveMut.mutate()}
        >
          {t('field_time.approve', { defaultValue: 'Approve' })}
        </Button>
      )}
      {timesheet.status === 'approved' && (
        <Button
          variant="danger"
          size="sm"
          icon={<RotateCcw size={14} />}
          disabled={lifecycleBusy}
          onClick={() => setReverseOpen(true)}
        >
          {t('field_time.reverse', { defaultValue: 'Reverse' })}
        </Button>
      )}
    </div>
  ) : null;

  return (
    <>
      <WideModal
        open
        onClose={onClose}
        size="full"
        busy={lifecycleBusy}
        title={title}
        subtitle={
          timesheet ? (
            <span className="inline-flex items-center gap-2">
              <DateDisplay value={timesheet.date} />
              <Badge variant={STATUS_BADGE[timesheet.status]} size="sm">
                {t(`field_time.status_${timesheet.status}`, { defaultValue: timesheet.status })}
              </Badge>
            </span>
          ) : undefined
        }
        footer={footer}
      >
        {detailQ.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
            {t('common.loading', { defaultValue: 'Loading...' })}
          </div>
        ) : detailQ.isError || !timesheet ? (
          <ErrorState
            title={t('field_time.load_failed', { defaultValue: 'Could not load this timesheet' })}
            hint={getErrorMessage(detailQ.error)}
            onRetry={() => detailQ.refetch()}
          />
        ) : (
          <div className="flex flex-col gap-5">
            {/* Header fields */}
            <div
              key={`${timesheet.id}:${timesheet.updated_at}:header`}
              className="grid grid-cols-1 gap-4 sm:grid-cols-2"
            >
              <label className="flex flex-col">
                <span className="mb-1.5 text-xs font-medium text-content-primary">
                  {t('field_time.date', { defaultValue: 'Date' })}
                </span>
                <input
                  type="date"
                  defaultValue={timesheet.date}
                  disabled={!isDraft}
                  className="h-9 w-full rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary disabled:opacity-60"
                  onChange={(e) => {
                    if (e.target.value && e.target.value !== timesheet.date) {
                      headerMut.mutate({ date: e.target.value });
                    }
                  }}
                />
              </label>
              <label className="flex flex-col">
                <span className="mb-1.5 text-xs font-medium text-content-primary">
                  {t('field_time.note', { defaultValue: 'Note' })}
                </span>
                <input
                  defaultValue={timesheet.note ?? ''}
                  disabled={!isDraft}
                  placeholder={t('field_time.note_placeholder', {
                    defaultValue: 'Crew, area, shift notes (optional)',
                  })}
                  className="h-9 w-full rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary disabled:opacity-60"
                  onBlur={(e) => {
                    const next = e.target.value.trim();
                    if (next !== (timesheet.note ?? '')) {
                      headerMut.mutate({ note: next || null });
                    }
                  }}
                />
              </label>
            </div>

            {/* Statutory working-time record, offered only where it applies */}
            {showWorkingTime && (
              <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
                <div className="flex flex-wrap items-end gap-3">
                  <label className="flex flex-col">
                    <span className="mb-1 text-2xs font-medium text-content-tertiary">
                      {/* Which regime this timesheet is already tracked under, a
                          different question from field_time.working_time.regime
                          in WorkingTimeRecord.tsx, which asks under which regime
                          new days get filed. The two shared one key until the
                          drift was caught: once a locale answers a key, its
                          value wins over either call site's own defaultValue,
                          so one of the two screens was silently speaking the
                          other's sentence. */}
                      {t('field_time.working_time.timesheet_regime', { defaultValue: 'Recording regime' })}
                    </span>
                    <select
                      value={timesheet.working_time_regime ?? ''}
                      disabled={!isDraft}
                      className="h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary disabled:opacity-60"
                      onChange={(e) => headerMut.mutate({ working_time_regime: e.target.value || null })}
                    >
                      <option value="">
                        {t('field_time.working_time.regime_none', { defaultValue: 'None' })}
                      </option>
                      {(regimesQ.data ?? []).map((r) => (
                        <option key={r.code} value={r.code}>
                          {t(`field_time.working_time.regime_${r.code}`, { defaultValue: r.label })}
                        </option>
                      ))}
                    </select>
                  </label>
                  {timesheet.working_time && (
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-content-tertiary">
                      <span>
                        {t('field_time.working_time.due_by', { defaultValue: 'Record due by' })}{' '}
                        <DateDisplay value={timesheet.working_time.deadline} format="numeric" />
                      </span>
                      <span>
                        {t('field_time.working_time.retain_until', { defaultValue: 'Keep until' })}{' '}
                        <DateDisplay value={timesheet.working_time.retain_until} format="numeric" />
                      </span>
                      {timesheet.working_time.late && (
                        <Badge variant="warning" size="sm">
                          {t('field_time.working_time.late', {
                            defaultValue: 'written up after {{count}} days',
                            count: timesheet.working_time.days_taken,
                          })}
                        </Badge>
                      )}
                    </div>
                  )}
                </div>
                <p className="mt-2 text-2xs leading-relaxed text-content-tertiary">
                  {t('field_time.working_time.line_hint', {
                    defaultValue:
                      'Give each labour line a start and an end and its hours come from them, less the break. A worker booked to two cost codes needs two segments that do not overlap, not the same hours twice.',
                  })}
                </p>
              </div>
            )}

            {/* Hours rollup */}
            <div className="grid grid-cols-3 gap-3">
              <RollupTile
                icon={<HardHat size={15} className="text-oe-blue" />}
                label={t('field_time.labour_hours', { defaultValue: 'Labour hours' })}
                value={formatHours(timesheet.labour_hours)}
              />
              <RollupTile
                icon={<Wrench size={15} className="text-content-secondary" />}
                label={t('field_time.plant_hours', { defaultValue: 'Plant hours' })}
                value={formatHours(timesheet.plant_hours)}
              />
              <RollupTile
                icon={<ListChecks size={15} className="text-content-secondary" />}
                label={t('field_time.lines', { defaultValue: 'Lines' })}
                value={String(timesheet.lines.length)}
              />
            </div>

            {/* Lines */}
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold text-content-primary">
                {t('field_time.lines', { defaultValue: 'Lines' })}
              </h3>
              {timesheet.lines.length === 0 ? (
                <p className="rounded-lg border border-dashed border-border-light px-3 py-6 text-center text-sm text-content-tertiary">
                  {isDraft
                    ? t('field_time.no_lines_draft', {
                        defaultValue: 'No lines yet. Add labour or plant below.',
                      })
                    : t('field_time.no_lines', { defaultValue: 'This timesheet has no lines.' })}
                </p>
              ) : (
                timesheet.lines.map((line) => (
                  <TimesheetLineRow
                    key={`${line.id}:${line.updated_at}`}
                    line={line}
                    editable={isDraft}
                    projectId={projectId}
                    labour={labour}
                    plant={plant}
                    variations={variations}
                    employers={employers}
                    workingTime={showWorkingTime}
                    timesheetDate={timesheet.date}
                    busy={updateLineMut.isPending || deleteLineMut.isPending}
                    onUpdate={(lineId, payload) => updateLineMut.mutate({ lineId, payload })}
                    onDelete={(lineId) => deleteLineMut.mutate(lineId)}
                  />
                ))
              )}

              {isDraft && (
                <LineComposer
                  projectId={projectId}
                  labour={labour}
                  plant={plant}
                  variations={variations}
                  busy={addLineMut.isPending}
                  onAdd={(payload) => addLineMut.mutateAsync(payload)}
                />
              )}
            </div>

            {/* Validation */}
            <ValidationPanel report={validationQ.data} isLoading={validationQ.isLoading} />
          </div>
        )}
      </WideModal>

      {/* Reverse dialog */}
      <WideModal
        open={reverseOpen}
        onClose={() => setReverseOpen(false)}
        size="sm"
        busy={reverseMut.isPending}
        title={t('field_time.reverse_title', { defaultValue: 'Reverse timesheet' })}
        subtitle={t('field_time.reverse_subtitle', {
          defaultValue:
            'This posts a mirrored, netting timesheet that cancels the approved hours. Add a short reason.',
        })}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setReverseOpen(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="danger"
              size="sm"
              icon={<RotateCcw size={14} />}
              loading={reverseMut.isPending}
              onClick={() => reverseMut.mutate(reverseNote.trim())}
            >
              {t('field_time.reverse_confirm', { defaultValue: 'Reverse timesheet' })}
            </Button>
          </>
        }
      >
        <label className="flex flex-col">
          <span className="mb-1.5 text-xs font-medium text-content-primary">
            {t('field_time.reverse_reason', { defaultValue: 'Reason' })}
          </span>
          <textarea
            value={reverseNote}
            onChange={(e) => setReverseNote(e.target.value)}
            rows={3}
            placeholder={t('field_time.reverse_reason_placeholder', {
              defaultValue: 'e.g. hours booked to the wrong cost code',
            })}
            className="w-full resize-y rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
          />
        </label>
      </WideModal>
    </>
  );
}

function RollupTile({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-3">
      <div className="flex items-center gap-1.5 text-xs text-content-tertiary">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-content-primary">{value}</div>
    </div>
  );
}
