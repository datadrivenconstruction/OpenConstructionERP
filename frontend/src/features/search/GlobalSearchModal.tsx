/**
 * GlobalSearchModal — Cmd+K cross-module semantic search.
 *
 * Connects to the unified `/api/v1/search/` endpoint which fans out to
 * every registered vector collection (BOQ, documents, tasks, risks, BIM
 * elements, validation, chat history) and merges results via Reciprocal
 * Rank Fusion.
 *
 * Layout:
 *   ┌────────────────────────────────────────────┐
 *   │ 🔍  search across the whole ERP…           │
 *   │ ─────────────────────────────────────────  │
 *   │ [BOQ 8] [Docs 5] [Tasks 2] [Risks 1] …    │  ← facet pills
 *   │ ─────────────────────────────────────────  │
 *   │ ▸ BOQ                                      │
 *   │   • 03.02.001 Concrete wall 240mm   89%   │
 *   │   • 03.02.002 Reinforcement Ø12     76%   │
 *   │ ▸ Documents                                │
 *   │   • A-301 Basement waterproofing    82%   │
 *   │ ▸ Risks                                    │
 *   │   • Slope failure on south retaining 71%  │
 *   └────────────────────────────────────────────┘
 *
 * Each row navigates to its native module page on click.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Search as SearchIcon,
  X,
  Loader2,
  Sparkles,
  ArrowUpRight,
  Filter,
} from 'lucide-react';
import { useGlobalSearchStore } from '@/stores/useGlobalSearchStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  unifiedSearch,
  fetchSearchTypes,
  collectionLabel,
  hitToHref,
  type UnifiedSearchHit,
} from './api';

const FACET_COLOR: Record<string, string> = {
  oe_boq_positions: 'bg-blue-50 text-blue-700 border-blue-200',
  oe_documents: 'bg-violet-50 text-violet-700 border-violet-200',
  oe_tasks: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  oe_risks: 'bg-rose-50 text-rose-700 border-rose-200',
  oe_bim_elements: 'bg-amber-50 text-amber-700 border-amber-200',
  oe_validation: 'bg-orange-50 text-orange-700 border-orange-200',
  oe_chat: 'bg-slate-50 text-slate-700 border-slate-200',
};

export default function GlobalSearchModal() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const open = useGlobalSearchStore((s) => s.open);
  const closeModal = useGlobalSearchStore((s) => s.closeModal);
  const query = useGlobalSearchStore((s) => s.query);
  const setQuery = useGlobalSearchStore((s) => s.setQuery);
  const selectedTypes = useGlobalSearchStore((s) => s.selectedTypes);
  const toggleType = useGlobalSearchStore((s) => s.toggleType);
  const clearTypes = useGlobalSearchStore((s) => s.clearTypes);
  const projectId = useProjectContextStore((s) => s.activeProjectId);

  const inputRef = useRef<HTMLInputElement>(null);
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [scopeProject, setScopeProject] = useState(true);

  // Auto-focus on open
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Debounce input → server query
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query.trim()), 220);
    return () => clearTimeout(t);
  }, [query]);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeModal();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, closeModal]);

  const typesQuery = useQuery({
    queryKey: ['search-types'],
    queryFn: fetchSearchTypes,
    staleTime: 60 * 60 * 1000,
    enabled: open,
  });

  const searchQuery = useQuery({
    queryKey: [
      'unified-search',
      debouncedQuery,
      selectedTypes,
      scopeProject ? projectId : null,
    ],
    queryFn: () =>
      unifiedSearch({
        q: debouncedQuery,
        types: selectedTypes.length > 0 ? selectedTypes : undefined,
        projectId: scopeProject ? projectId : null,
        finalLimit: 30,
      }),
    enabled: open && debouncedQuery.length >= 2,
    staleTime: 30 * 1000,
  });

  // Group hits by collection for the rendered list.
  const grouped = useMemo(() => {
    const out: Record<string, UnifiedSearchHit[]> = {};
    for (const hit of searchQuery.data?.hits ?? []) {
      (out[hit.collection] ||= []).push(hit);
    }
    return out;
  }, [searchQuery.data]);

  if (!open) return null;

  const handleHitClick = (hit: UnifiedSearchHit) => {
    const href = hitToHref(hit);
    closeModal();
    if (href && href !== '#') navigate(href);
  };

  const facets = searchQuery.data?.facets ?? {};
  const totalHits = searchQuery.data?.total ?? 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm pt-[10vh] px-4"
      onClick={closeModal}
    >
      <div
        className="w-full max-w-3xl bg-surface-primary rounded-xl shadow-2xl border border-border-light flex flex-col max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border-light shrink-0">
          <SearchIcon size={16} className="text-content-tertiary" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('global_search.placeholder', {
              defaultValue:
                'Search anything — BOQ positions, drawings, tasks, risks, BIM elements…',
            })}
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-content-quaternary"
          />
          {searchQuery.isFetching && (
            <Loader2 size={14} className="text-content-tertiary animate-spin" />
          )}
          <button
            onClick={closeModal}
            className="p-1 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>

        {/* Filter row — type chips + scope toggle */}
        <div className="flex items-center justify-between gap-2 px-4 py-2 border-b border-border-light shrink-0 overflow-x-auto">
          <div className="flex items-center gap-1.5">
            <Filter size={11} className="text-content-quaternary" />
            {(typesQuery.data?.types ?? []).map((typeMeta) => {
              const isActive = selectedTypes.includes(typeMeta.short);
              const facetCount = facets[typeMeta.name] ?? 0;
              return (
                <button
                  key={typeMeta.name}
                  type="button"
                  onClick={() => toggleType(typeMeta.short)}
                  className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded border transition-colors ${
                    isActive
                      ? 'bg-oe-blue text-white border-oe-blue'
                      : `${FACET_COLOR[typeMeta.name] ?? 'bg-surface-secondary text-content-secondary border-border-light'} hover:opacity-80`
                  }`}
                >
                  {typeMeta.label}
                  {facetCount > 0 && (
                    <span className="tabular-nums opacity-80">
                      {facetCount}
                    </span>
                  )}
                </button>
              );
            })}
            {selectedTypes.length > 0 && (
              <button
                type="button"
                onClick={clearTypes}
                className="text-[10px] text-oe-blue hover:underline ms-1"
              >
                {t('common.clear', { defaultValue: 'Clear' })}
              </button>
            )}
          </div>
          <label className="flex items-center gap-1 text-[10px] text-content-tertiary cursor-pointer select-none whitespace-nowrap">
            <input
              type="checkbox"
              checked={scopeProject}
              onChange={(e) => setScopeProject(e.target.checked)}
              className="h-3 w-3 accent-oe-blue"
            />
            {t('global_search.scope_project', {
              defaultValue: 'Current project only',
            })}
          </label>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto">
          {debouncedQuery.length < 2 && (
            <div className="flex flex-col items-center justify-center py-16 text-content-tertiary">
              <Sparkles size={28} className="text-amber-400 mb-2" />
              <div className="text-xs">
                {t('global_search.hint', {
                  defaultValue:
                    'Start typing to search across every project module by meaning, not exact match.',
                })}
              </div>
            </div>
          )}

          {debouncedQuery.length >= 2 && searchQuery.isLoading && (
            <div className="flex items-center justify-center py-16 text-content-tertiary text-xs">
              <Loader2 size={14} className="animate-spin me-2" />
              {t('global_search.searching', { defaultValue: 'Searching…' })}
            </div>
          )}

          {debouncedQuery.length >= 2 &&
            !searchQuery.isLoading &&
            totalHits === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-content-tertiary">
                <SearchIcon size={24} className="mb-2 opacity-50" />
                <div className="text-xs italic">
                  {t('global_search.no_results', {
                    defaultValue: 'No matches yet — try a different phrasing',
                  })}
                </div>
              </div>
            )}

          {totalHits > 0 && (
            <div className="p-2 space-y-3">
              {Object.entries(grouped).map(([collection, hits]) => (
                <div key={collection}>
                  <div className="flex items-center gap-1.5 px-2 py-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
                      {collectionLabel(collection)}
                    </span>
                    <span className="text-[10px] text-content-quaternary tabular-nums">
                      {hits.length}
                    </span>
                  </div>
                  <ul className="space-y-0.5">
                    {hits.map((hit) => (
                      <li key={`${hit.collection}:${hit.id}`}>
                        <button
                          type="button"
                          onClick={() => handleHitClick(hit)}
                          className="w-full flex items-start gap-2 px-2 py-1.5 rounded text-start hover:bg-oe-blue/5 border border-transparent hover:border-oe-blue/30 transition-colors group"
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-medium text-content-primary truncate">
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
                          <ArrowUpRight
                            size={11}
                            className="text-content-quaternary group-hover:text-oe-blue shrink-0 mt-0.5"
                          />
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-border-light shrink-0 flex items-center justify-between text-[10px] text-content-quaternary">
          <span>
            {t('global_search.footer_hint', {
              defaultValue: 'Semantic search powered by vector embeddings',
            })}
          </span>
          <span className="font-mono">esc</span>
        </div>
      </div>
    </div>
  );
}
