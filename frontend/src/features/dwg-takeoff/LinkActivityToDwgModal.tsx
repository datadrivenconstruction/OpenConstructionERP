/**
 * LinkActivityToDwgModal — pick a schedule activity and link it to one
 * or more DWG entities (4D linking from the drawing side).
 *
 * Mirrors LinkActivityToBIMModal. We reuse the activity's existing
 * metadata blob to store the DWG link — no dedicated backend endpoint
 * is needed because the activity PATCH endpoint already accepts a
 * metadata dict, and consumers can locate DWG-linked activities by
 * filtering on `metadata.dwg_entity_ids`.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { X, Search, Calendar, Link2, Loader2 } from 'lucide-react';
import { apiGet, apiPatch } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

interface ScheduleHeader {
  id: string;
  project_id: string;
  name: string;
  status?: string;
  created_at?: string;
}

interface Activity {
  id: string;
  schedule_id: string;
  name: string;
  start_date: string | null;
  end_date: string | null;
  status: string | null;
  percent_complete: number | null;
  bim_element_ids: string[] | null;
  metadata?: Record<string, unknown> | null;
}

interface LinkActivityToDwgModalProps {
  projectId: string;
  entityIds: string[];
  drawingId: string;
  entityLabel?: string;
  onClose: () => void;
  onLinked?: () => void;
}

export default function LinkActivityToDwgModal({
  projectId,
  entityIds,
  drawingId,
  entityLabel,
  onClose,
  onLinked,
}: LinkActivityToDwgModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [search, setSearch] = useState('');
  const PAGE_SIZE = 50;
  const [visibleCount, setVisibleCount] = useState<number>(PAGE_SIZE);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [search]);

  const schedulesQuery = useQuery({
    queryKey: ['schedules-for-dwg-link', projectId],
    queryFn: () =>
      apiGet<ScheduleHeader[]>(
        `/v1/schedule/schedules/?project_id=${encodeURIComponent(projectId)}`,
      ),
    enabled: !!projectId,
  });
  const schedules = schedulesQuery.data ?? [];

  const activitiesQuery = useQuery({
    queryKey: [
      'activities-for-dwg-link',
      projectId,
      schedules.map((s) => s.id).join(','),
    ],
    queryFn: async () => {
      const all: Activity[] = [];
      for (const s of schedules) {
        try {
          const acts = await apiGet<Activity[]>(
            `/v1/schedule/schedules/${encodeURIComponent(s.id)}/activities/`,
          );
          all.push(...acts);
        } catch {
          // ignore per-schedule failures
        }
      }
      return all;
    },
    enabled: schedules.length > 0,
  });
  const activities = activitiesQuery.data ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return activities;
    return activities.filter((a) => (a.name || '').toLowerCase().includes(q));
  }, [activities, search]);

  const linkMut = useMutation({
    mutationFn: async (activity: Activity) => {
      const existing = (activity.metadata ?? {}) as Record<string, unknown>;
      const existingIds = Array.isArray(existing['dwg_entity_ids'])
        ? (existing['dwg_entity_ids'] as string[])
        : [];
      const mergedIds = Array.from(new Set([...existingIds, ...entityIds]));
      const nextMetadata: Record<string, unknown> = {
        ...existing,
        dwg_drawing_id: drawingId,
        dwg_entity_ids: mergedIds,
      };
      await apiPatch<Activity, { metadata: Record<string, unknown> }>(
        `/v1/schedule/activities/${encodeURIComponent(activity.id)}`,
        { metadata: nextMetadata },
      );
      return entityIds.length;
    },
    onSuccess: (count) => {
      addToast({
        type: 'success',
        title: t('dwg_takeoff.act_linked_title', { defaultValue: 'Activity linked' }),
        message: t('dwg_takeoff.act_linked_msg', {
          defaultValue: 'Linked to {{count}} DWG entity/entities',
          count,
        }),
      });
      qc.invalidateQueries({ queryKey: ['activities-for-dwg-link', projectId] });
      qc.invalidateQueries({ queryKey: ['schedule-activities'] });
      onLinked?.();
      onClose();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message || String(err),
      });
    },
  });

  const isLoading = schedulesQuery.isLoading || activitiesQuery.isLoading;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="bg-surface-primary rounded-xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col border border-border-light"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-light shrink-0">
          <div className="flex items-center gap-2">
            <Calendar size={16} className="text-emerald-600" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t('dwg_takeoff.link_act_title', {
                defaultValue: 'Link a schedule activity',
              })}
            </h2>
            <span className="text-[11px] text-content-tertiary">
              {entityIds.length === 1
                ? '→ ' + (entityLabel || t('dwg_takeoff.entity', { defaultValue: 'Entity' }))
                : t('dwg_takeoff.link_act_bulk', {
                    defaultValue: '→ {{count}} entities',
                    count: entityIds.length,
                  })}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3 border-b border-border-light shrink-0">
          <div className="relative">
            <Search
              size={13}
              className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-quaternary pointer-events-none"
            />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('dwg_takeoff.search_activities', {
                defaultValue: 'Search activities by name…',
              })}
              autoFocus
              className="w-full ps-8 pe-3 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto p-3">
          {isLoading ? (
            <div className="flex items-center justify-center py-8 text-content-tertiary">
              <Loader2 size={16} className="animate-spin mr-2" />
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-8 text-[11px] text-content-tertiary italic">
              {schedules.length === 0
                ? t('dwg_takeoff.no_schedules', {
                    defaultValue:
                      'No schedules in this project yet — create one in /schedule first',
                  })
                : activities.length === 0
                  ? t('dwg_takeoff.no_activities', {
                      defaultValue: 'No activities in any project schedule yet',
                    })
                  : t('dwg_takeoff.no_act_match', {
                      defaultValue: 'No activities match your search',
                    })}
            </div>
          ) : (
            <ul className="space-y-1">
              {filtered.slice(0, visibleCount).map((act) => (
                <li key={act.id}>
                  <button
                    type="button"
                    onClick={() => linkMut.mutate(act)}
                    disabled={linkMut.isPending}
                    className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded text-start hover:bg-emerald-50 dark:hover:bg-emerald-950/30 border border-transparent hover:border-emerald-300/50 disabled:opacity-50 transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium text-content-primary truncate">
                        {act.name}
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-content-tertiary tabular-nums">
                        {act.start_date && <span>{act.start_date.slice(0, 10)}</span>}
                        {act.start_date && act.end_date && <span>→</span>}
                        {act.end_date && <span>{act.end_date.slice(0, 10)}</span>}
                        {typeof act.percent_complete === 'number' && (
                          <span>· {act.percent_complete}%</span>
                        )}
                      </div>
                    </div>
                    <Link2 size={12} className="text-emerald-600 shrink-0" />
                  </button>
                </li>
              ))}
              {filtered.length > visibleCount && (
                <li className="py-2">
                  <button
                    type="button"
                    onClick={() =>
                      setVisibleCount((c) => Math.min(c + PAGE_SIZE, filtered.length))
                    }
                    className="w-full text-center text-[11px] text-oe-blue hover:bg-oe-blue/5 rounded py-1.5 border border-dashed border-oe-blue/30"
                  >
                    {t('dwg_takeoff.load_more', {
                      defaultValue: 'Load more ({{remaining}} remaining)',
                      remaining: filtered.length - visibleCount,
                    })}
                  </button>
                </li>
              )}
            </ul>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end px-5 py-3 border-t border-border-light shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-content-tertiary hover:text-content-primary px-2"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
        </div>
      </div>
    </div>
  );
}
