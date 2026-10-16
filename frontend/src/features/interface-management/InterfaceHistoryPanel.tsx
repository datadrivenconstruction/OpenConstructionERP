// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { History, ArrowRight } from 'lucide-react';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchInterfaceHistory, type InterfaceHistoryEntry } from './api';

// English fallbacks for the computed `interface_management.history_event_*` keys.
const EVENT_LABEL: Record<string, string> = {
  created: 'Created',
  status_changed: 'Status changed',
  approval_requested: 'Sent for approval',
  approval_approved: 'Approved on route',
  approval_rejected: 'Rejected on route',
  approval_cancelled: 'Approval withdrawn',
};

// English fallbacks for the computed `interface_management.status_*` keys.
const STATUS_LABEL: Record<string, string> = {
  identified: 'Identified',
  open: 'Open',
  in_progress: 'In progress',
  agreed: 'Agreed',
  closed: 'Closed',
  disputed: 'Disputed',
  on_hold: 'On hold',
};

const humanize = (value: string): string => value.replace(/_/g, ' ');

/**
 * Status history of one interface: who moved it, when, from which status to
 * which, and the comment left with the move. Includes the steps its approval
 * route took (sent, approved, rejected, withdrawn). Loaded only when mounted,
 * i.e. when the interface row is expanded.
 */
export function InterfaceHistoryPanel({
  projectId,
  interfaceId,
}: {
  projectId: string;
  interfaceId: string;
}) {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: ['interface-management', 'history', projectId, interfaceId],
    queryFn: () => fetchInterfaceHistory(projectId, interfaceId),
    enabled: !!projectId && !!interfaceId,
  });

  const statusText = (value: string | null) =>
    value
      ? t(`interface_management.status_${value}`, { defaultValue: STATUS_LABEL[value] ?? humanize(value) })
      : '';

  const entries: InterfaceHistoryEntry[] = query.data ?? [];

  return (
    <div className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="interface-history">
      <div className="mb-2 flex items-center gap-1.5">
        <History size={14} className="text-content-tertiary" />
        <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('interface_management.history_title', { defaultValue: 'Status history' })}
        </span>
      </div>
      {query.isLoading ? (
        <p className="py-1 text-xs text-content-tertiary">{t('common.loading', { defaultValue: 'Loading...' })}</p>
      ) : query.isError ? (
        <p className="py-1 text-xs text-semantic-error">{getErrorMessage(query.error)}</p>
      ) : entries.length === 0 ? (
        <p className="py-1 text-xs text-content-tertiary">
          {t('interface_management.history_empty', {
            defaultValue: 'No changes recorded yet. Changes made from now on appear here.',
          })}
        </p>
      ) : (
        <ol className="space-y-1.5">
          {entries.map((h) => {
            const moved = h.from_status && h.to_status && h.from_status !== h.to_status;
            return (
              <li key={h.id} className="rounded-md bg-surface-primary/70 px-2.5 py-1.5 text-sm">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className="font-medium text-content-primary">
                    {t(`interface_management.history_event_${h.event}`, {
                      defaultValue: EVENT_LABEL[h.event] ?? humanize(h.event),
                    })}
                  </span>
                  {moved ? (
                    <span className="inline-flex items-center gap-1 text-xs text-content-secondary">
                      {statusText(h.from_status)}
                      <ArrowRight size={11} className="shrink-0 rtl:rotate-180" aria-hidden="true" />
                      {statusText(h.to_status)}
                    </span>
                  ) : h.to_status ? (
                    <span className="text-xs text-content-secondary">{statusText(h.to_status)}</span>
                  ) : null}
                  <span className="ms-auto text-2xs text-content-tertiary">
                    <DateDisplay value={h.changed_at} format="datetime" />
                    {' · '}
                    {h.actor_name ||
                      (h.actor_id
                        ? t('interface_management.history_unknown_user', { defaultValue: 'Unknown user' })
                        : t('interface_management.history_system', { defaultValue: 'System' }))}
                  </span>
                </div>
                {h.comment && <p className="mt-0.5 whitespace-pre-wrap text-xs text-content-secondary">{h.comment}</p>}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
