// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Progress sheet round-trip. Export: pick the scope (WBS, responsible person,
// date window) and download a locked XLSX for site staff. Upload: read the
// filled sheet back, see per activity what would change and what the checks
// found, tick the rows to take, set the status date and apply. Nothing is
// written before Apply, and Apply sends the digest of the previewed file.

import { useMemo, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Upload } from 'lucide-react';

import { Badge, Button, WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  interopApi,
  InteropApiError,
  type SheetApplyResult,
  type SheetPreview,
  type SheetPreviewRow,
} from './interopApi';
import {
  assigneeOptions,
  canSelectRow,
  defaultSelectedRows,
  todayIso,
  wbsPrefixes,
  type ScopeActivity,
} from './interopLogic';

interface ProgressSheetDialogProps {
  open: boolean;
  onClose: () => void;
  scheduleId: string;
  activities: ScopeActivity[];
  canEdit: boolean;
}

const FIELD_KEYS = ['percent_complete', 'actual_start', 'actual_finish', 'remaining_duration', 'notes'] as const;

const FIELD_DEFAULTS: Record<string, string> = {
  percent_complete: '% complete',
  actual_start: 'Actual start',
  actual_finish: 'Actual finish',
  remaining_duration: 'Remaining (days)',
  notes: 'Notes',
};

export function ProgressSheetDialog({ open, onClose, scheduleId, activities, canEdit }: ProgressSheetDialogProps) {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);

  const [tab, setTab] = useState<'export' | 'upload'>('export');
  const [wbs, setWbs] = useState('');
  const [assigneeId, setAssigneeId] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [includeCompleted, setIncludeCompleted] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [statusDate, setStatusDate] = useState(todayIso());
  const [preview, setPreview] = useState<SheetPreview | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const prefixes = useMemo(() => wbsPrefixes(activities), [activities]);
  const people = useMemo(() => assigneeOptions(activities), [activities]);

  const fieldLabel = (key: string) =>
    t(`schedule.progress_sheet.field_${key}`, { defaultValue: FIELD_DEFAULTS[key] ?? key });

  const errorText = (err: unknown) => {
    if (err instanceof InteropApiError && err.code) {
      return t(`schedule.progress_sheet.error_${err.code}`, { defaultValue: err.message });
    }
    return err instanceof Error ? err.message : String(err);
  };

  const download = useMutation({
    mutationFn: () =>
      interopApi.downloadProgressSheet(scheduleId, {
        wbs: wbs || undefined,
        assigneeId: assigneeId || undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
        includeCompleted,
        locale: i18n.language,
      }),
    onSuccess: (rows) =>
      addToast({
        type: 'success',
        title: t('schedule.progress_sheet.exported', { defaultValue: 'Progress sheet downloaded' }),
        message: t('schedule.progress_sheet.exported_rows', { defaultValue: '{{count}} activities', count: rows }),
      }),
    onError: (err) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: errorText(err) }),
  });

  const check = useMutation({
    mutationFn: (f: File) => interopApi.previewProgressSheet(scheduleId, f, statusDate, i18n.language),
    onSuccess: (result) => {
      setPreview(result);
      setSelected(defaultSelectedRows(result.rows));
    },
    onError: (err) => {
      setPreview(null);
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: errorText(err) });
    },
  });

  const apply = useMutation({
    mutationFn: () => {
      if (!file || !preview) throw new Error('no preview');
      return interopApi.applyProgressSheet(scheduleId, file, {
        sha256: preview.sha256,
        statusDate,
        rowNumbers: [...selected].sort((a, b) => a - b),
        locale: i18n.language,
      });
    },
    onSuccess: (result: SheetApplyResult) => {
      queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
      queryClient.invalidateQueries({ queryKey: ['schedule-record', scheduleId] });
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      addToast({
        type: result.skipped.length ? 'warning' : 'success',
        title: t('schedule.progress_sheet.applied', {
          defaultValue: '{{count}} progress updates applied',
          count: result.applied_count,
        }),
        message: result.skipped.length
          ? t('schedule.progress_sheet.applied_skipped', {
              defaultValue: '{{count}} rows were not applied',
              count: result.skipped.length,
            })
          : undefined,
      });
      setPreview(null);
      setFile(null);
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: errorText(err) }),
  });

  const toggle = (row: SheetPreviewRow) => {
    if (!canSelectRow(row)) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(row.row_number)) next.delete(row.row_number);
      else next.add(row.row_number);
      return next;
    });
  };

  const inputClass =
    'h-9 rounded-lg border border-border-light bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40';

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="2xl"
      busy={apply.isPending}
      title={t('schedule.progress_sheet.title', { defaultValue: 'Progress sheet' })}
      subtitle={t('schedule.progress_sheet.subtitle', {
        defaultValue:
          'Download a sheet for the site, let the team fill in progress offline, then upload it to review and apply the updates.',
      })}
      testId="progress-sheet-dialog"
      footer={
        tab === 'upload' && preview ? (
          <div className="flex w-full items-center justify-between gap-3">
            <span className="text-xs text-content-tertiary">
              {t('schedule.progress_sheet.selected_count', {
                defaultValue: '{{count}} rows selected',
                count: selected.size,
              })}
            </span>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={onClose}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                icon={<CheckCircle2 size={16} />}
                loading={apply.isPending}
                disabled={!canEdit || selected.size === 0}
                onClick={() => apply.mutate()}
                data-testid="progress-sheet-apply"
              >
                {t('schedule.progress_sheet.apply', {
                  defaultValue: 'Apply {{count}} updates',
                  count: selected.size,
                })}
              </Button>
            </div>
          </div>
        ) : undefined
      }
    >
      <div className="mb-4 flex gap-1 rounded-lg border border-border-light p-0.5 w-fit" role="tablist">
        {(['export', 'upload'] as const).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`px-3 py-1 text-xs font-medium rounded-md ${
              tab === key ? 'bg-oe-blue text-white' : 'text-content-secondary hover:bg-surface-secondary'
            }`}
          >
            {key === 'export'
              ? t('schedule.progress_sheet.tab_export', { defaultValue: '1. Download sheet' })
              : t('schedule.progress_sheet.tab_upload', { defaultValue: '2. Upload filled sheet' })}
          </button>
        ))}
      </div>

      {tab === 'export' ? (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('schedule.progress_sheet.filter_wbs', { defaultValue: 'WBS' })}
              <select className={inputClass} value={wbs} onChange={(e) => setWbs(e.target.value)} data-testid="ps-wbs">
                <option value="">{t('schedule.progress_sheet.filter_all', { defaultValue: 'All' })}</option>
                {prefixes.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('schedule.progress_sheet.filter_responsible', { defaultValue: 'Responsible' })}
              <select
                className={inputClass}
                value={assigneeId}
                onChange={(e) => setAssigneeId(e.target.value)}
                data-testid="ps-assignee"
              >
                <option value="">{t('schedule.progress_sheet.filter_all', { defaultValue: 'All' })}</option>
                {people.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('schedule.progress_sheet.filter_from', { defaultValue: 'Planned from' })}
              <input type="date" className={inputClass} value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('schedule.progress_sheet.filter_to', { defaultValue: 'Planned to' })}
              <input type="date" className={inputClass} value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm text-content-secondary">
            <input
              type="checkbox"
              checked={includeCompleted}
              onChange={(e) => setIncludeCompleted(e.target.checked)}
            />
            {t('schedule.progress_sheet.include_completed', { defaultValue: 'Include completed activities' })}
          </label>
          <p className="text-xs text-content-tertiary">
            {t('schedule.progress_sheet.export_hint', {
              defaultValue:
                'The sheet lists one row per activity. Only % complete, actual dates, remaining duration and notes can be edited; the other columns are locked.',
            })}
          </p>
          <Button
            variant="primary"
            icon={<Download size={16} />}
            loading={download.isPending}
            onClick={() => download.mutate()}
            data-testid="progress-sheet-download"
          >
            {t('schedule.progress_sheet.download', { defaultValue: 'Download progress sheet' })}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('schedule.progress_sheet.status_date', { defaultValue: 'Status date' })}
              <input
                type="date"
                className={inputClass}
                value={statusDate}
                onChange={(e) => setStatusDate(e.target.value)}
                data-testid="ps-status-date"
              />
            </label>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="hidden"
              data-testid="ps-file"
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                setFile(f);
                setPreview(null);
                if (f) check.mutate(f);
                e.target.value = '';
              }}
            />
            <Button
              variant="secondary"
              icon={<Upload size={16} />}
              loading={check.isPending}
              disabled={!canEdit}
              onClick={() => fileRef.current?.click()}
            >
              {t('schedule.progress_sheet.choose_file', { defaultValue: 'Choose filled sheet' })}
            </Button>
            {file && (
              <span className="flex items-center gap-1 text-xs text-content-secondary">
                <FileSpreadsheet size={14} /> {file.name}
              </span>
            )}
          </div>

          {preview && (
            <>
              <div className="flex flex-wrap gap-2" data-testid="ps-summary">
                <Badge variant="neutral" size="sm">
                  {t('schedule.progress_sheet.rows', { defaultValue: '{{count}} rows', count: preview.row_count })}
                </Badge>
                <Badge variant="blue" size="sm">
                  {t('schedule.progress_sheet.changes', {
                    defaultValue: '{{count}} with changes',
                    count: preview.changed_count,
                  })}
                </Badge>
                {preview.error_count > 0 && (
                  <Badge variant="error" size="sm">
                    {t('schedule.progress_sheet.errors', {
                      defaultValue: '{{count}} with errors',
                      count: preview.error_count,
                    })}
                  </Badge>
                )}
                {preview.stale_count > 0 && (
                  <Badge variant="warning" size="sm">
                    {t('schedule.progress_sheet.stale', {
                      defaultValue: '{{count}} changed in the app since export',
                      count: preview.stale_count,
                    })}
                  </Badge>
                )}
              </div>
              <div className="max-h-[50vh] overflow-auto rounded-lg border border-border-light">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-surface-secondary text-content-secondary">
                    <tr>
                      <th className="w-8 px-2 py-2" />
                      <th className="px-2 py-2 text-left">{t('schedule.progress_sheet.col_row', { defaultValue: 'Row' })}</th>
                      <th className="px-2 py-2 text-left">
                        {t('schedule.progress_sheet.col_activity', { defaultValue: 'Activity' })}
                      </th>
                      <th className="px-2 py-2 text-left">
                        {t('schedule.progress_sheet.col_changes', { defaultValue: 'Changes' })}
                      </th>
                      <th className="px-2 py-2 text-left">
                        {t('schedule.progress_sheet.col_checks', { defaultValue: 'Checks' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row) => (
                      <tr
                        key={row.row_number}
                        className="border-t border-border-light align-top"
                        data-testid={`ps-row-${row.row_number}`}
                      >
                        <td className="px-2 py-2">
                          <input
                            type="checkbox"
                            aria-label={t('schedule.progress_sheet.select_row', {
                              defaultValue: 'Apply row {{row}}',
                              row: row.row_number,
                            })}
                            checked={selected.has(row.row_number)}
                            disabled={!canSelectRow(row)}
                            onChange={() => toggle(row)}
                          />
                        </td>
                        <td className="px-2 py-2 tabular-nums text-content-tertiary">{row.row_number}</td>
                        <td className="px-2 py-2">
                          <div className="font-medium text-content-primary">{row.name ?? '-'}</div>
                          <div className="text-content-tertiary">{row.activity_code}</div>
                          {row.stale && (
                            <Badge variant="warning" size="sm">
                              {t('schedule.progress_sheet.stale_badge', { defaultValue: 'Changed since export' })}
                            </Badge>
                          )}
                        </td>
                        <td className="px-2 py-2">
                          {Object.keys(row.changes).length === 0 ? (
                            <span className="text-content-tertiary">
                              {t('schedule.progress_sheet.no_changes', { defaultValue: 'No changes' })}
                            </span>
                          ) : (
                            <ul className="space-y-0.5">
                              {FIELD_KEYS.filter((k) => row.changes[k]).map((k) => (
                                <li key={k}>
                                  <span className="text-content-tertiary">{fieldLabel(k)}: </span>
                                  {k !== 'notes' && (
                                    <span className="line-through text-content-tertiary">
                                      {String(row.changes[k]?.old ?? '-')}
                                    </span>
                                  )}{' '}
                                  <span className="font-medium text-content-primary">
                                    {String(row.changes[k]?.new ?? '-')}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </td>
                        <td className="px-2 py-2">
                          <ul className="space-y-1">
                            {row.issues.map((issue, i) => (
                              <li
                                key={`${issue.rule_id}-${issue.code}-${i}`}
                                className={`flex items-start gap-1 ${
                                  issue.severity === 'error' ? 'text-semantic-error' : 'text-amber-600'
                                }`}
                              >
                                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                                <span>{issue.message}</span>
                              </li>
                            ))}
                          </ul>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </WideModal>
  );
}
