// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { ArrowRight, History, AlertTriangle } from 'lucide-react';
import { Badge, Skeleton } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet } from '@/shared/lib/api';
import { projectsApi } from './api';
import { ProjectStatusBadge } from './ProjectStatusBadge';

/**
 * StatusHistoryTimeline (#274) - shows the audit trail of project status
 * changes, newest-first, as "from -> to" rows with the actor (resolved to a
 * display name when possible) and the change time via the app date
 * formatter. Handles loading / empty / error states.
 */

interface UserResult {
  id: string;
  email: string;
  full_name: string;
}

export function StatusHistoryTimeline({
  projectId,
  hideHeader = false,
}: {
  projectId: string;
  /** Hide the internal heading when the caller already labels the section. */
  hideHeader?: boolean;
}) {
  const { t } = useTranslation();

  const {
    data: history,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['project-status-history', projectId],
    queryFn: () => projectsApi.statusHistory(projectId),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  // Resolve changed_by ids to display names. Mirrors the RFI detail page
  // pattern (GET /v1/users/?limit=100), keyed independently so React Query
  // dedupes the lookup across pages that need it.
  const canListUsers = useHasPermission('users.list');
  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () => apiGet<UserResult[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
    enabled: canListUsers,
  });

  const userById = useMemo(() => {
    const map = new Map<string, string>();
    for (const u of users) map.set(u.id, u.full_name || u.email);
    return map;
  }, [users]);

  const displayUser = (id: string | null): string | null => {
    if (!id) return null;
    return userById.get(id) ?? id;
  };

  return (
    <div>
      {!hideHeader && (
        <div className="mb-3 flex items-center gap-2">
          <History size={16} className="text-content-tertiary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('projects.status_history.title', { defaultValue: 'Status history' })}
          </h3>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} height={48} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : isError ? (
        <div className="flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2.5">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-semantic-warning" />
          <p className="text-sm text-content-secondary">
            {t('projects.status_history.error', {
              defaultValue: 'Could not load the status history for this project.',
            })}
          </p>
        </div>
      ) : !history || history.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-4 text-center text-sm text-content-tertiary">
          {t('projects.status_history.empty', {
            defaultValue: 'No status changes recorded yet.',
          })}
        </p>
      ) : (
        <ol className="space-y-2.5">
          {history.map((entry) => {
            const actor = displayUser(entry.changed_by);
            return (
              <li
                key={entry.id}
                className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-border-light bg-surface-elevated px-3 py-2.5"
              >
                <div className="flex items-center gap-2">
                  {entry.from_status ? (
                    <ProjectStatusBadge status={entry.from_status} dot={false} />
                  ) : (
                    <Badge variant="neutral" size="sm">
                      {t('projects.status_history.created', { defaultValue: 'Created' })}
                    </Badge>
                  )}
                  <ArrowRight
                    size={14}
                    className="shrink-0 text-content-tertiary"
                    aria-label={t('projects.status_history.changed_to', {
                      defaultValue: 'changed to',
                    })}
                  />
                  <ProjectStatusBadge status={entry.to_status} dot={false} />
                </div>
                <div className="ml-auto flex flex-wrap items-center gap-x-2 text-xs text-content-tertiary">
                  {actor && (
                    <span className="text-content-secondary">
                      {t('projects.status_history.by', {
                        defaultValue: 'by {{name}}',
                        name: actor,
                      })}
                    </span>
                  )}
                  <DateDisplay value={entry.created_at} format="datetime" />
                </div>
                {entry.note && (
                  <p className="w-full text-xs text-content-secondary">{entry.note}</p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
