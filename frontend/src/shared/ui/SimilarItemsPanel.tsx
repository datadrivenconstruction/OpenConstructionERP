/**
 * SimilarItemsPanel — universal "more like this" panel.
 *
 * Renders the top-N semantically similar rows for any module that
 * implements the unified `GET /{id}/similar/` endpoint contract:
 *
 *   - BOQ positions       → /api/v1/boq/positions/{id}/similar/
 *   - Documents           → /api/v1/documents/{id}/similar/
 *   - Tasks               → /api/v1/tasks/{id}/similar/
 *   - Risks               → /api/v1/risk/{id}/similar/  (cross-project)
 *   - BIM elements        → /api/v1/bim_hub/elements/{id}/similar/
 *
 * The panel is fully self-contained — drop it next to any record card
 * with `<SimilarItemsPanel module="boq" id={pos.id} />` and it handles
 * loading, empty state, error fallback, click-through navigation and a
 * "cross-project" toggle (off by default for in-model contexts like BIM,
 * on by default for everything else).
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Loader2, ExternalLink, Globe, Layers } from 'lucide-react';
import {
  fetchSimilarItems,
  hitToHref,
  type SimilarModuleKind,
  type UnifiedSearchHit,
} from '@/features/search/api';

interface SimilarItemsPanelProps {
  /** Which module the source record belongs to. */
  module: SimilarModuleKind;
  /** Source record ID — the panel will exclude it from results. */
  id: string;
  /** Override the cross-project default for this module. */
  crossProject?: boolean;
  /** Max number of hits to render (1..20). */
  limit?: number;
  /** Optional className passthrough. */
  className?: string;
  /** When false, the panel renders nothing on empty results so callers
   *  can hide the section header.  Default true. */
  showWhenEmpty?: boolean;
}

const DEFAULT_CROSS_PROJECT: Record<SimilarModuleKind, boolean> = {
  boq: true,
  documents: true,
  tasks: true,
  risks: true,
  bim_elements: false,
};

export default function SimilarItemsPanel({
  module,
  id,
  crossProject,
  limit = 5,
  className,
  showWhenEmpty = true,
}: SimilarItemsPanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const initialCross = crossProject ?? DEFAULT_CROSS_PROJECT[module];
  const [crossProjectState, setCrossProjectState] = useState(initialCross);

  const query = useQuery({
    queryKey: ['similar-items', module, id, crossProjectState, limit],
    queryFn: () =>
      fetchSimilarItems(module, id, {
        limit,
        crossProject: crossProjectState,
      }),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });

  const hits: UnifiedSearchHit[] = useMemo(
    () => query.data?.hits ?? [],
    [query.data],
  );

  const handleClick = (hit: UnifiedSearchHit) => {
    const href = hitToHref(hit);
    if (href && href !== '#') navigate(href);
  };

  if (!query.isLoading && hits.length === 0 && !showWhenEmpty) {
    return null;
  }

  return (
    <div
      className={`rounded-md border border-border-light bg-surface-secondary/50 p-3 ${
        className ?? ''
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <Sparkles size={12} className="text-amber-500" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('similar.title', { defaultValue: 'Similar items' })}
          </span>
          {query.data && (
            <span className="text-[10px] text-content-quaternary tabular-nums">
              {hits.length}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setCrossProjectState((v) => !v)}
          title={
            crossProjectState
              ? t('similar.scope_all_title', {
                  defaultValue: 'Searching across all projects — click to limit to current',
                })
              : t('similar.scope_one_title', {
                  defaultValue: 'Searching current project only — click to expand',
                })
          }
          className="inline-flex items-center gap-1 text-[10px] text-content-tertiary hover:text-content-primary"
        >
          {crossProjectState ? (
            <>
              <Globe size={10} />
              {t('similar.scope_all', { defaultValue: 'All projects' })}
            </>
          ) : (
            <>
              <Layers size={10} />
              {t('similar.scope_one', { defaultValue: 'This project' })}
            </>
          )}
        </button>
      </div>

      {query.isLoading && (
        <div className="flex items-center gap-2 text-[11px] text-content-tertiary py-2">
          <Loader2 size={11} className="animate-spin" />
          {t('similar.loading', { defaultValue: 'Searching…' })}
        </div>
      )}

      {!query.isLoading && query.isError && (
        <div className="text-[11px] text-rose-600 py-1.5">
          {t('similar.error', {
            defaultValue: 'Could not load similar items',
          })}
        </div>
      )}

      {!query.isLoading && !query.isError && hits.length === 0 && (
        <div className="text-[11px] text-content-tertiary italic py-1.5">
          {t('similar.empty', { defaultValue: 'No similar items found yet' })}
        </div>
      )}

      {hits.length > 0 && (
        <ul className="space-y-1">
          {hits.map((hit) => (
            <li key={`${hit.collection}:${hit.id}`}>
              <button
                type="button"
                onClick={() => handleClick(hit)}
                className="w-full flex items-start gap-2 px-2 py-1.5 rounded text-start hover:bg-surface-primary border border-transparent hover:border-border-light transition-colors group"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-medium text-content-primary truncate">
                      {hit.title || hit.id}
                    </span>
                    <span className="text-[9px] text-content-quaternary tabular-nums shrink-0">
                      {Math.round(hit.score * 100)}%
                    </span>
                  </div>
                  {hit.snippet && (
                    <div className="text-[10px] text-content-tertiary line-clamp-2 mt-0.5">
                      {hit.snippet}
                    </div>
                  )}
                </div>
                <ExternalLink
                  size={10}
                  className="text-content-quaternary group-hover:text-oe-blue shrink-0 mt-0.5"
                />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
