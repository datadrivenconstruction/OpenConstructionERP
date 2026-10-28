// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Source of an imported schedule. The original file is kept in the project's
// documents and every imported activity keeps the dates it had in the file.
// Until the recalculated dates are accepted this panel shows "dates as in
// source" beside the current dates with the deviation in days; the planner
// accepts the recalculation or puts the source dates back. Renders nothing
// for a schedule that was not imported from a file.

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, FileText, RotateCcw } from 'lucide-react';

import { Badge, Button, Card, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { interopApi } from './interopApi';
import { formatShift, isDeviating } from './interopLogic';

interface ImportSourcePanelProps {
  scheduleId: string;
  canEdit: boolean;
  /** Banner mode: one line with the deviation count and a link to the full panel. */
  compact?: boolean;
  onOpen?: () => void;
}

export function importSourceQueryKey(scheduleId: string) {
  return ['schedule-import-source', scheduleId] as const;
}

export function ImportSourcePanel({ scheduleId, canEdit, compact = false, onOpen }: ImportSourcePanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const { confirm, ...confirmProps } = useConfirm();
  const [onlyDeviating, setOnlyDeviating] = useState(true);

  const source = useQuery({
    queryKey: importSourceQueryKey(scheduleId),
    queryFn: async () => {
      try {
        return await interopApi.getImportSource(scheduleId);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    retry: false,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: importSourceQueryKey(scheduleId) });
    queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
  };
  const fail = (err: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });

  const accept = useMutation({
    mutationFn: () => interopApi.acceptImportRecalculation(scheduleId),
    onSuccess: () => {
      refresh();
      addToast({
        type: 'success',
        title: t('schedule.import_source.accepted_toast', { defaultValue: 'Recalculated dates accepted' }),
      });
    },
    onError: fail,
  });
  const restore = useMutation({
    mutationFn: () => interopApi.restoreImportSourceDates(scheduleId),
    onSuccess: (res) => {
      refresh();
      addToast({
        type: 'success',
        title: t('schedule.import_source.restored_toast', {
          defaultValue: '{{count}} activities back on their source dates',
          count: res.moved,
        }),
      });
    },
    onError: fail,
  });

  const data = source.data;
  const rows = useMemo(() => {
    const all = data?.activities ?? [];
    return onlyDeviating ? all.filter(isDeviating) : all;
  }, [data, onlyDeviating]);
  if (!data?.source) return null;
  const pending = data.source.status !== 'accepted';

  if (compact) {
    if (!pending || data.deviating_count === 0) return null;
    return (
      <div
        className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-900/20 dark:text-amber-200"
        data-testid="import-source-banner"
      >
        <FileText size={14} />
        <span>
          {t('schedule.import_source.banner', {
            defaultValue: '{{count}} activities differ from the imported file {{file}}.',
            count: data.deviating_count,
            file: data.source.filename,
          })}
        </span>
        {onOpen && (
          <button type="button" className="font-medium underline" onClick={onOpen}>
            {t('schedule.import_source.review', { defaultValue: 'Review' })}
          </button>
        )}
      </div>
    );
  }

  return (
    <Card padding="md" data-testid="import-source-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium text-content-primary">
            <FileText size={16} />
            {t('schedule.import_source.title', { defaultValue: 'Imported source' })}
            <Badge variant={pending ? 'warning' : 'success'} size="sm">
              {pending
                ? t('schedule.import_source.status_pending', { defaultValue: 'Under review' })
                : t('schedule.import_source.status_accepted', { defaultValue: 'Recalculation accepted' })}
            </Badge>
          </div>
          <div className="text-xs text-content-secondary">
            {t('schedule.import_source.file_line', {
              defaultValue: '{{file}} ({{format}}), {{count}} activities, imported {{date}}',
              file: data.source.filename || '-',
              format: data.source.format.toUpperCase(),
              count: data.source.activity_count,
              date: (data.source.imported_at ?? '').slice(0, 10),
            })}
          </div>
          <div className="text-xs text-content-tertiary">
            {data.source.document_id
              ? t('schedule.import_source.stored', {
                  defaultValue: 'The original file is stored in the project documents.',
                })
              : t('schedule.import_source.not_stored', {
                  defaultValue: 'The original file could not be stored in the project documents.',
                })}
          </div>
        </div>
        {pending && canEdit && (
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              icon={<RotateCcw size={14} />}
              loading={restore.isPending}
              disabled={data.deviating_count === 0}
              onClick={async () => {
                const ok = await confirm({
                  title: t('schedule.import_source.restore_title', { defaultValue: 'Restore the source dates?' }),
                  message: t('schedule.import_source.restore_message', {
                    defaultValue: '{{count}} activities go back to the dates in the imported file.',
                    count: data.deviating_count,
                  }),
                  confirmLabel: t('schedule.import_source.restore', { defaultValue: 'Restore source dates' }),
                  variant: 'warning',
                });
                if (ok) restore.mutate();
              }}
              data-testid="import-source-restore"
            >
              {t('schedule.import_source.restore', { defaultValue: 'Restore source dates' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<CheckCircle2 size={14} />}
              loading={accept.isPending}
              onClick={() => accept.mutate()}
              data-testid="import-source-accept"
            >
              {t('schedule.import_source.accept', { defaultValue: 'Accept recalculated dates' })}
            </Button>
          </div>
        )}
      </div>

      {pending && (
        <>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              <Badge variant={data.deviating_count ? 'warning' : 'success'} size="sm">
                {t('schedule.import_source.deviating', {
                  defaultValue: '{{count}} of {{total}} activities deviate',
                  count: data.deviating_count,
                  total: data.activity_count,
                })}
              </Badge>
              {data.project_finish_deviation_days !== null && (
                <Badge variant="neutral" size="sm">
                  {t('schedule.import_source.finish_deviation', {
                    defaultValue: 'Project finish {{days}} days',
                    days: formatShift(data.project_finish_deviation_days),
                  })}
                </Badge>
              )}
            </div>
            <label className="flex items-center gap-2 text-xs text-content-secondary">
              <input type="checkbox" checked={onlyDeviating} onChange={(e) => setOnlyDeviating(e.target.checked)} />
              {t('schedule.import_source.only_deviating', { defaultValue: 'Only deviating activities' })}
            </label>
          </div>
          <div className="mt-2 max-h-[50vh] overflow-auto rounded-lg border border-border-light">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface-secondary text-content-secondary">
                <tr>
                  <th className="px-2 py-2 text-left">
                    {t('schedule.import_source.col_activity', { defaultValue: 'Activity' })}
                  </th>
                  <th className="px-2 py-2 text-left">
                    {t('schedule.import_source.col_source', { defaultValue: 'Dates as in source' })}
                  </th>
                  <th className="px-2 py-2 text-left">
                    {t('schedule.import_source.col_current', { defaultValue: 'Recalculated' })}
                  </th>
                  <th className="px-2 py-2 text-right">
                    {t('schedule.import_source.col_start_dev', { defaultValue: 'Start deviation' })}
                  </th>
                  <th className="px-2 py-2 text-right">
                    {t('schedule.import_source.col_finish_dev', { defaultValue: 'Finish deviation' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.activity_id} className="border-t border-border-light">
                    <td className="px-2 py-1.5">
                      <div className="font-medium text-content-primary">{row.name}</div>
                      <div className="text-content-tertiary">
                        {row.activity_code}
                        {row.source_id ? ` · ${row.source_id}` : ''}
                      </div>
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-content-secondary">
                      {row.source_start} – {row.source_finish}
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-content-primary">
                      {row.current_start} – {row.current_finish}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{formatShift(row.start_deviation_days)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{formatShift(row.finish_deviation_days)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}
