/**
 * LinkRequirementToBIMModal — pick a requirement and pin it to one or
 * more BIM elements.
 *
 * Mirrors the LinkActivityToBIMModal architecture exactly so the muscle
 * memory transfers: load all requirement sets in the project, flatten
 * their requirements into a single searchable list, click a row → PATCH
 * the requirement's `metadata_["bim_element_ids"]` (additive — appends
 * the new element ids to whatever's already there) → invalidate the
 * `bim-elements` query so the viewer's element details panel
 * immediately shows the new "Linked requirements" entry.
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
import {
  fetchRequirementSets,
  fetchRequirementSetDetail,
  linkRequirementToBIMElements,
  type Requirement,
  type RequirementSet,
} from '@/features/requirements/api';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import { useToastStore } from '@/stores/useToastStore';

interface LinkRequirementToBIMModalProps {
  projectId: string;
  /** Either a single element (click flow) or many (bulk filter flow). */
  elements: BIMElementData[];
  onClose: () => void;
  /** Called after a successful link so the parent can refetch. */
  onLinked?: () => void;
}

const PRIORITY_COLOR: Record<string, string> = {
  must: 'text-rose-700 bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900/60',
  should:
    'text-amber-700 bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-900/60',
  may: 'text-slate-700 bg-slate-50 dark:bg-slate-950/40 border-slate-200 dark:border-slate-800',
};

export default function LinkRequirementToBIMModal({
  projectId,
  elements,
  onClose,
  onLinked,
}: LinkRequirementToBIMModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [search, setSearch] = useState('');
  /** Paginated "show more" cursor — replaces the old hard 200-item cap
   *  so the user can reach any filtered requirement, not just the first
   *  two hundred. */
  const PAGE_SIZE = 50;
  const [visibleCount, setVisibleCount] = useState<number>(PAGE_SIZE);

  // Reset transient UI state when the modal is reopened with a new
  // element selection — mirrors AddToBOQModal's pattern.
  useEffect(() => {
    setSearch('');
    setVisibleCount(PAGE_SIZE);
  }, [elements]);

  // Reset the page cursor whenever the search changes so the user sees
  // the first page of results for their new query.
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [search]);

  // 1. Load all requirement sets in the project
  const setsQuery = useQuery({
    queryKey: ['requirement-sets-for-bim-link', projectId],
    queryFn: () => fetchRequirementSets(projectId),
    enabled: !!projectId,
  });
  const sets: RequirementSet[] = setsQuery.data ?? [];

  // 2. Flatten every requirement across every set in this project.
  // Typical projects have <5 sets with <500 reqs each, so the dataset
  // is bounded — same reasoning as the activities modal.
  const reqsQuery = useQuery({
    queryKey: [
      'requirements-for-bim-link',
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
          // ignore individual set failures so one bad row doesn't
          // tank the whole modal
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
      const elementIds = elements.map((el) => el.id);
      await linkRequirementToBIMElements(req.requirement_set_id, req.id, elementIds);
      return elements.length;
    },
    onSuccess: (count) => {
      addToast({
        type: 'success',
        title: t('bim.req_linked_title', { defaultValue: 'Requirement linked' }),
        message: t('bim.req_linked_msg', {
          defaultValue: 'Pinned to {{count}} BIM element(s)',
          count,
        }),
      });
      qc.invalidateQueries({ queryKey: ['bim-elements'] });
      qc.invalidateQueries({ queryKey: ['requirements-for-bim-link', projectId] });
      qc.invalidateQueries({ queryKey: ['requirement-sets-for-bim-link', projectId] });
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
              {t('bim.link_req_title', { defaultValue: 'Link a requirement' })}
            </h2>
            <span className="text-[11px] text-content-tertiary">
              {elements.length === 1
                ? '→ ' + (elements[0]!.name || elements[0]!.element_type)
                : t('bim.link_req_bulk', {
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
              placeholder={t('bim.search_requirements', {
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
                ? t('bim.no_req_sets', {
                    defaultValue:
                      'No requirement sets in this project yet — create one in /requirements first',
                  })
                : requirements.length === 0
                  ? t('bim.no_requirements', {
                      defaultValue: 'No requirements in any set yet',
                    })
                  : t('bim.no_req_match', {
                      defaultValue: 'No requirements match your search',
                    })}
            </div>
          ) : (
            <ul className="space-y-1">
              {filtered.slice(0, visibleCount).map((req) => {
                const linkedCount = Array.isArray(
                  (req.metadata as Record<string, unknown> | undefined)?.[
                    'bim_element_ids'
                  ],
                )
                  ? (
                      (req.metadata as Record<string, unknown>)[
                        'bim_element_ids'
                      ] as unknown[]
                    ).length
                  : 0;
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
                          {linkedCount > 0 && (
                            <span className="text-violet-700 dark:text-violet-400">
                              · {linkedCount} linked
                            </span>
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
