/**
 * LinkActivityToBIMModal — pick a schedule activity and link it to one or
 * more BIM elements (4D linking).
 *
 * Lists every activity in every schedule of the project, lets the user
 * search by name, click a row → PATCH the activity's bim_element_ids
 * (additive: appends the new element ids to whatever's already there) →
 * invalidate the bim-elements query.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { X, Search, Calendar, Link2, Loader2 } from 'lucide-react';
import { apiGet, apiPatch } from '@/shared/lib/api';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
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
}

interface LinkActivityToBIMModalProps {
  projectId: string;
  elements: BIMElementData[];
  onClose: () => void;
  onLinked?: () => void;
}

export default function LinkActivityToBIMModal({
  projectId,
  elements,
  onClose,
  onLinked,
}: LinkActivityToBIMModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [search, setSearch] = useState('');
  /** Paginated "show more" cursor — how many filtered rows to render.
   *  Grows by PAGE_SIZE each time the user clicks "Load more".  Replaces
   *  the old hard 200-item cap which prevented linking past that point. */
  const PAGE_SIZE = 50;
  const [visibleCount, setVisibleCount] = useState<number>(PAGE_SIZE);

  // Reset transient UI state when the modal is reopened with a new
  // element selection — mirrors AddToBOQModal's pattern.
  useEffect(() => {
    setSearch('');
    setVisibleCount(PAGE_SIZE);
  }, [elements]);

  // Reset the page cursor whenever the search changes so the user
  // always sees the first page of results for their new query.
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [search]);

  // 1. Load all schedules in the project
  const schedulesQuery = useQuery({
    queryKey: ['schedules-for-bim-link', projectId],
    queryFn: () =>
      apiGet<ScheduleHeader[]>(
        `/v1/schedule/schedules/?project_id=${encodeURIComponent(projectId)}`,
      ),
    enabled: !!projectId,
  });
  const schedules = schedulesQuery.data ?? [];

  // 2. For each schedule, load its activities (parallel via React Query)
  // We use a single derived query that flattens all activities into one
  // list — typical projects have <5 schedules with <500 activities each,
  // so the dataset is bounded.
  const activitiesQuery = useQuery({
    queryKey: ['activities-for-bim-link', projectId, schedules.map((s) => s.id).join(',')],
    queryFn: async () => {
      const all: Activity[] = [];
      for (const s of schedules) {
        try {
          const acts = await apiGet<Activity[]>(
            `/v1/schedule/schedules/${encodeURIComponent(s.id)}/activities/`,
          );
          all.push(...acts);
        } catch {
          // ignore individual schedule failures
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
    return activities.filter((a) =>
      (a.name || '').toLowerCase().includes(q),
    );
  }, [activities, search]);

  const linkMut = useMutation({
    mutationFn: async (activity: Activity) => {
      // Append new element ids to whatever's already there (idempotent set)
      const existing = new Set(activity.bim_element_ids || []);
      for (const el of elements) existing.add(el.id);
      const merged = Array.from(existing);
      await apiPatch<Activity, { bim_element_ids: string[] }>(
        `/v1/schedule/activities/${encodeURIComponent(activity.id)}/bim-links`,
        { bim_element_ids: merged },
      );
      return elements.length;
    },
    onSuccess: (count) => {
      addToast({
        type: 'success',
        title: t('bim.act_linked_title', { defaultValue: 'Activity linked' }),
        message: t('bim.act_linked_msg', {
          defaultValue: 'Linked to {{count}} BIM element(s)',
          count,
        }),
      });
      qc.invalidateQueries({ queryKey: ['bim-elements'] });
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
              {t('bim.link_act_title', { defaultValue: 'Link a schedule activity' })}
            </h2>
            <span className="text-[11px] text-content-tertiary">
              {elements.length === 1
                ? '→ ' + (elements[0]!.name || elements[0]!.element_type)
                : t('bim.link_act_bulk', {
                    defaultValue: '→ {{count}} elements',
                    count: elements.length,
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
              placeholder={t('bim.search_activities', {
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
                ? t('bim.no_schedules', {
                    defaultValue: 'No schedules in this project yet — create one in /schedule first',
                  })
                : activities.length === 0
                  ? t('bim.no_activities', {
                      defaultValue: 'No activities in any project schedule yet',
                    })
                  : t('bim.no_act_match', { defaultValue: 'No activities match your search' })}
            </div>
          ) : (
            <ul className="space-y-1">
              {filtered.slice(0, visibleCount).map((act) => {
                const linkedCount = act.bim_element_ids?.length ?? 0;
                return (
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
                          {linkedCount > 0 && (
                            <span className="text-emerald-700 dark:text-emerald-400">
                              · {linkedCount} linked
                            </span>
                          )}
                        </div>
                      </div>
                      <Link2 size={12} className="text-emerald-600 shrink-0" />
                    </button>
                  </li>
                );
              })}
              {filtered.length > visibleCount && (
                <li className="py-2">
                  <button
                    type="button"
                    onClick={() =>
                      setVisibleCount((c) =>
                        Math.min(c + PAGE_SIZE, filtered.length),
                      )
                    }
                    className="w-full text-center text-[11px] text-oe-blue hover:bg-oe-blue/5 rounded py-1.5 border border-dashed border-oe-blue/30"
                  >
                    {t('bim.load_more', {
                      defaultValue:
                        'Load more ({{remaining}} remaining)',
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
