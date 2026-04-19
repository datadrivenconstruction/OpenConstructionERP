/**
 * LinkRequirementToDwgModal — pick a requirement and pin it to one or
 * more DWG entities.
 *
 * Mirrors LinkRequirementToBIMModal's architecture exactly. Requirements
 * already expose an additive metadata blob, so we merge the DWG entity
 * ids and the drawing id into `metadata.dwg_entity_ids` /
 * `metadata.dwg_drawing_id` without a dedicated backend column.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import {
  X,
  Search,
  ClipboardCheck,
  Link2,
  Loader2,
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react';
import { apiPatch } from '@/shared/lib/api';
import {
  fetchRequirementSets,
  fetchRequirementSetDetail,
  type Requirement,
  type RequirementSet,
} from '@/features/requirements/api';
import { useToastStore } from '@/stores/useToastStore';

interface LinkRequirementToDwgModalProps {
  projectId: string;
  entityIds: string[];
  drawingId: string;
  entityLabel?: string;
  onClose: () => void;
  onLinked?: () => void;
}

const PRIORITY_COLOR: Record<string, string> = {
  must: 'text-rose-700 bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900/60',
  should:
    'text-amber-700 bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-900/60',
  may: 'text-slate-700 bg-slate-50 dark:bg-slate-950/40 border-slate-200 dark:border-slate-800',
};

export default function LinkRequirementToDwgModal({
  projectId,
  entityIds,
  drawingId,
  entityLabel,
  onClose,
  onLinked,
}: LinkRequirementToDwgModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [search, setSearch] = useState('');
  const PAGE_SIZE = 50;
  const [visibleCount, setVisibleCount] = useState<number>(PAGE_SIZE);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [search]);

  const setsQuery = useQuery({
    queryKey: ['requirement-sets-for-dwg-link', projectId],
    queryFn: () => fetchRequirementSets(projectId),
    enabled: !!projectId,
  });
  const sets: RequirementSet[] = setsQuery.data ?? [];

  const reqsQuery = useQuery({
    queryKey: [
      'requirements-for-dwg-link',
      projectId,
      sets.map((s) => s.id).join(','),
    ],
    queryFn: async () => {
      const all: Array<Requirement & { set_name: string }> = [];
      for (const s of sets) {
        try {
          const detail = await fetchRequirementSetDetail(s.id);
          for (const req of detail.requirements ?? []) {
            all.push({ ...req, set_name: s.name });
          }
        } catch {
          /* ignore individual set failures */
        }
      }
      return all;
    },
    enabled: sets.length > 0,
  });
  const requirements = reqsQuery.data ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return requirements;
    return requirements.filter((r) => {
      const haystack = [
        r.entity,
        r.attribute,
        r.constraint_type,
        r.constraint_value,
        r.unit,
        r.category,
        r.notes,
        r.set_name,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [requirements, search]);

  const linkMut = useMutation({
    mutationFn: async (req: Requirement & { set_name: string }) => {
      const existing = (req.metadata ?? {}) as Record<string, unknown>;
      const existingIds = Array.isArray(existing['dwg_entity_ids'])
        ? (existing['dwg_entity_ids'] as string[])
        : [];
      const mergedIds = Array.from(new Set([...existingIds, ...entityIds]));
      const nextMetadata: Record<string, unknown> = {
        ...existing,
        dwg_drawing_id: drawingId,
        dwg_entity_ids: mergedIds,
      };
      await apiPatch<Requirement, { metadata: Record<string, unknown> }>(
        `/v1/requirements/${req.requirement_set_id}/requirements/${req.id}`,
        { metadata: nextMetadata },
      );
      return entityIds.length;
    },
    onSuccess: (count) => {
      addToast({
        type: 'success',
        title: t('dwg_takeoff.req_linked_title', { defaultValue: 'Requirement linked' }),
        message: t('dwg_takeoff.req_linked_msg', {
          defaultValue: 'Pinned to {{count}} DWG entity/entities',
          count,
        }),
      });
      qc.invalidateQueries({ queryKey: ['requirements-for-dwg-link', projectId] });
      qc.invalidateQueries({ queryKey: ['requirement-sets-for-dwg-link', projectId] });
      qc.invalidateQueries({ queryKey: ['requirement-set'] });
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

  const isLoading = setsQuery.isLoading || reqsQuery.isLoading;

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
            <ClipboardCheck size={16} className="text-violet-600" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t('dwg_takeoff.link_req_title', { defaultValue: 'Link a requirement' })}
            </h2>
            <span className="text-[11px] text-content-tertiary">
              {entityIds.length === 1
                ? '→ ' + (entityLabel || t('dwg_takeoff.entity', { defaultValue: 'Entity' }))
                : t('dwg_takeoff.link_req_bulk', {
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
              placeholder={t('dwg_takeoff.search_requirements', {
                defaultValue: 'Search by entity, attribute, constraint, notes…',
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
              {sets.length === 0
                ? t('dwg_takeoff.no_req_sets', {
                    defaultValue:
                      'No requirement sets in this project yet — create one in BIM Rules first',
                  })
                : requirements.length === 0
                  ? t('dwg_takeoff.no_requirements', {
                      defaultValue: 'No requirements in any set yet',
                    })
                  : t('dwg_takeoff.no_req_match', {
                      defaultValue: 'No requirements match your search',
                    })}
            </div>
          ) : (
            <ul className="space-y-1">
              {filtered.slice(0, visibleCount).map((req) => {
                const priorityClass =
                  PRIORITY_COLOR[req.priority] ?? PRIORITY_COLOR.may;
                return (
                  <li key={req.id}>
                    <button
                      type="button"
                      onClick={() => linkMut.mutate(req)}
                      disabled={linkMut.isPending}
                      className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded text-start hover:bg-violet-50 dark:hover:bg-violet-950/30 border border-transparent hover:border-violet-300/50 disabled:opacity-50 transition-colors"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-medium text-content-primary truncate">
                            {req.entity}
                            {req.attribute && (
                              <span className="text-content-tertiary">
                                .{req.attribute}
                              </span>
                            )}
                          </span>
                          <span
                            className={`shrink-0 inline-flex items-center px-1 py-0.5 text-[8px] font-bold uppercase rounded border ${priorityClass}`}
                          >
                            {req.priority}
                          </span>
                          {req.status === 'verified' && (
                            <CheckCircle2
                              size={9}
                              className="text-emerald-500 shrink-0"
                            />
                          )}
                          {req.status === 'conflict' && (
                            <AlertOctagon
                              size={9}
                              className="text-rose-500 shrink-0"
                            />
                          )}
                          {req.status === 'open' && (
                            <AlertTriangle
                              size={9}
                              className="text-amber-500 shrink-0"
                            />
                          )}
                        </div>
                        <div className="flex items-center gap-2 text-[10px] text-content-tertiary tabular-nums">
                          <span className="font-mono">
                            {req.constraint_type} {req.constraint_value}
                            {req.unit ? ` ${req.unit}` : ''}
                          </span>
                          {req.set_name && (
                            <span className="truncate">· {req.set_name}</span>
                          )}
                        </div>
                      </div>
                      <Link2 size={12} className="text-violet-600 shrink-0" />
                    </button>
                  </li>
                );
              })}
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
