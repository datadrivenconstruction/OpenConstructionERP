// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SeriesActionRegisterDialog — the per-series action register. One place to see
// every action raised across a recurring meeting series with its owner, due
// date and current status, plus a roll-up of how many are open, done and
// overdue. Read-only: actions are worked in each meeting's row.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { Badge, WideModal } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import {
  fetchSeriesActionRegister,
  type ActionStatus,
  type SeriesActionRegister,
} from './api';

interface SeriesActionRegisterDialogProps {
  seriesId: string;
  onClose: () => void;
}

const STATUS_VARIANT: Record<ActionStatus, 'neutral' | 'blue' | 'warning' | 'success'> = {
  open: 'blue',
  in_progress: 'warning',
  done: 'success',
  cancelled: 'neutral',
};

export function SeriesActionRegisterDialog({ seriesId, onClose }: SeriesActionRegisterDialogProps) {
  const { t } = useTranslation();

  const registerQ = useQuery<SeriesActionRegister>({
    queryKey: ['series-actions', seriesId],
    queryFn: () => fetchSeriesActionRegister(seriesId),
    staleTime: 15_000,
  });

  const data = registerQ.data;
  const actions = data?.actions ?? [];

  const statusLabel = (status: ActionStatus): string => {
    const fallback: Record<ActionStatus, string> = {
      open: 'Open',
      in_progress: 'In progress',
      done: 'Done',
      cancelled: 'Cancelled',
    };
    return t(`meetings.action_status_${status}`, { defaultValue: fallback[status] });
  };

  return (
    <WideModal
      open
      onClose={onClose}
      size="lg"
      title={t('meetings.series_register_title', { defaultValue: 'Series action register' })}
      subtitle={t('meetings.series_register_subtitle', {
        defaultValue: 'Every action raised across this recurring meeting series.',
      })}
    >
      {registerQ.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-content-tertiary py-8 justify-center">
          <Loader2 size={16} className="animate-spin" />
          {t('common.loading', { defaultValue: 'Loading…' })}
        </div>
      ) : (
        <div className="space-y-4">
          {/* Roll-up chips */}
          <div className="flex flex-wrap gap-2">
            <SummaryChip label={t('meetings.stat_total', { defaultValue: 'Total' })} value={data?.total ?? 0} />
            <SummaryChip
              label={statusLabel('open')}
              value={data?.open ?? 0}
              tone="text-oe-blue"
            />
            <SummaryChip
              label={statusLabel('in_progress')}
              value={data?.in_progress ?? 0}
              tone="text-amber-500"
            />
            <SummaryChip
              label={statusLabel('done')}
              value={data?.done ?? 0}
              tone="text-semantic-success"
            />
            <SummaryChip
              label={t('meetings.overdue', { defaultValue: 'Overdue' })}
              value={data?.overdue ?? 0}
              tone="text-semantic-error"
            />
          </div>

          {actions.length === 0 ? (
            <p className="text-sm text-content-tertiary italic py-4 text-center">
              {t('meetings.no_series_actions', {
                defaultValue: 'No action items have been raised in this series yet.',
              })}
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border-light">
              <table className="w-full text-sm min-w-[560px]">
                <thead>
                  <tr className="bg-surface-secondary/40 text-2xs uppercase tracking-wide text-content-tertiary">
                    <th className="text-left font-medium px-3 py-2">
                      {t('meetings.action_description', { defaultValue: 'Action item' })}
                    </th>
                    <th className="text-left font-medium px-3 py-2 w-24">
                      {t('meetings.col_raised', { defaultValue: 'Raised' })}
                    </th>
                    <th className="text-left font-medium px-3 py-2 w-28">
                      {t('meetings.action_owner', { defaultValue: 'Owner' })}
                    </th>
                    <th className="text-left font-medium px-3 py-2 w-28">
                      {t('meetings.action_due', { defaultValue: 'Due' })}
                    </th>
                    <th className="text-left font-medium px-3 py-2 w-28">
                      {t('meetings.action_status', { defaultValue: 'Status' })}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {actions.map((a) => (
                    <tr key={a.id} className="hover:bg-surface-secondary/30">
                      <td className="px-3 py-2 text-content-primary">{a.description}</td>
                      <td className="px-3 py-2 text-content-tertiary font-mono text-xs">
                        {a.origin_meeting_number || '—'}
                      </td>
                      <td className="px-3 py-2 text-content-secondary">
                        {a.owner_name || a.owner_id || '—'}
                      </td>
                      <td className="px-3 py-2 text-content-secondary">
                        {a.due_date ? <DateDisplay value={a.due_date} /> : '—'}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5">
                          <Badge variant={STATUS_VARIANT[a.status]} size="sm">
                            {statusLabel(a.status)}
                          </Badge>
                          {a.overdue && (
                            <Badge variant="error" size="sm">
                              {t('meetings.overdue', { defaultValue: 'Overdue' })}
                            </Badge>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </WideModal>
  );
}

function SummaryChip({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-elevated/80 px-3 py-2 min-w-[84px]">
      <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">{label}</p>
      <p className={'text-lg font-semibold tabular-nums ' + (tone ?? 'text-content-primary')}>{value}</p>
    </div>
  );
}
