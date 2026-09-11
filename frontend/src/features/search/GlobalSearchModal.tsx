// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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
  Bookmark,
} from 'lucide-react';
import { useGlobalSearchStore } from '@/stores/useGlobalSearchStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  unifiedSearch,
  fetchSearchTypes,
  collectionLabel,
  hitLabel,
  hitToHref,
  type UnifiedSearchHit,
} from './api';

const FACET_COLOR: Record<string, string> = {
  oe_boq_positions: 'bg-blue-50 text-blue-700 border-blue-200',
  oe_documents: 'bg-violet-50 text-violet-700 border-violet-200',
  oe_tasks: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  oe_risks: 'bg-rose-50 text-rose-700 border-rose-200',
  oe_bim_elements: 'bg-amber-50 text-amber-700 border-amber-200',
  oe_requirements: 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200',
  oe_rfi_rfis: 'bg-cyan-50 text-cyan-700 border-cyan-200',
  oe_submittals_submittals: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  oe_correspondence_correspondence: 'bg-teal-50 text-teal-700 border-teal-200',
  oe_validation: 'bg-orange-50 text-orange-700 border-orange-200',
  oe_chat: 'bg-slate-50 text-slate-700 border-slate-200',
};

/* ── Saved searches (localStorage) ─────────────────────────────────────── */

const SAVED_SEARCHES_KEY = 'oce-saved-searches';
const MAX_SAVED = 10;

interface SavedSearch {
  query: string;
  savedAt: string;
}

function loadSavedSearches(): SavedSearch[] {
  try {
    const raw = localStorage.getItem(SAVED_SEARCHES_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as SavedSearch[];
  } catch {
    return [];
  }
}

function persistSavedSearches(entries: SavedSearch[]): void {
  try {
    localStorage.setItem(SAVED_SEARCHES_KEY, JSON.stringify(entries.slice(0, MAX_SAVED)));
  } catch {
    // Silently ignore storage errors
  }
}

function addSavedSearch(q: string): SavedSearch[] {
  const current = loadSavedSearches().filter((s) => s.query !== q);
  const next = [{ query: q, savedAt: new Date().toISOString() }, ...current].slice(0, MAX_SAVED);
  persistSavedSearches(next);
  return next;
}

function removeSavedSearch(q: string): SavedSearch[] {
  const next = loadSavedSearches().filter((s) => s.query !== q);
  persistSavedSearches(next);
  return next;
}

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
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);

  // Auto-focus on open + reload saved searches
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => inputRef.current?.focus());
      setSavedSearches(loadSavedSearches());
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
  const isQuerySaved = savedSearches.some((s) => s.query === query.trim());

  const handleSaveSearch = () => {
    const q = query.trim();
    if (!q) return;
    setSavedSearches(addSavedSearch(q));
  };

  const handleRemoveSaved = (q: string) => {
    setSavedSearches(removeSavedSearch(q));
  };

  const handleClickSaved = (q: string) => {
    setQuery(q);
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/70 backdrop-blur-lg pt-[8vh] px-3 sm:px-4 pb-4"
      onClick={closeModal}
    >
      <div
        className="w-full max-w-3xl bg-surface-primary rounded-2xl shadow-2xl ring-1 ring-black/5 border border-border-light flex flex-col max-h-[85vh] min-h-0 overflow-hidden"
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
                'Search anything - BOQ positions, drawings, tasks, risks, BIM elements…',
            })}
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-content-quaternary"
          />
          {searchQuery.isFetching && (
            <Loader2 size={14} className="text-content-tertiary animate-spin" />
          )}
          {debouncedQuery.length >= 2 && totalHits > 0 && !isQuerySaved && (
            <button
              onClick={handleSaveSearch}
              className="p-1 rounded text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/5 transition-colors"
              aria-label={t('search.save_search', { defaultValue: 'Save search' })}
              title={t('search.save_search', { defaultValue: 'Save search' })}
            >
              <Bookmark size={14} />
            </button>
          )}
          <button
            onClick={closeModal}
            className="p-1 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={14} />
          </button>
        </div>

        {/* Filter row — type chips (horizontal scroller) + pinned scope toggle.
            The chips live in their own min-w-0 overflow-x-auto track so a long
            chip list never squashes/wraps; the scope toggle is shrink-0 and
            stays pinned on the right, separated by a border. */}
        <div className="flex items-stretch gap-2 ps-4 pe-3 py-2 border-b border-border-light shrink-0">
          <Filter
            size={11}
            className="text-content-tertiary shrink-0 self-center"
          />
          <div className="flex items-center gap-1.5 min-w-0 flex-1 overflow-x-auto scrollbar-none py-0.5">
            {(typesQuery.data?.types ?? []).map((typeMeta) => {
              const isActive = selectedTypes.includes(typeMeta.short);
              const facetCount = facets[typeMeta.name] ?? 0;
              return (
                <button
                  key={typeMeta.name}
                  type="button"
                  onClick={() => toggleType(typeMeta.short)}
                  aria-pressed={isActive}
                  className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap px-2 py-1 text-[11px] font-medium rounded-full border transition-colors ${
                    isActive
                      ? 'bg-oe-blue text-white border-oe-blue'
                      : `${FACET_COLOR[typeMeta.name] ?? 'bg-surface-secondary text-content-secondary border-border-light'} hover:opacity-80`
                  }`}
                >
                  {collectionLabel(t, typeMeta.name)}
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
                className="shrink-0 whitespace-nowrap text-[11px] text-oe-blue-text hover:underline ms-1"
              >
                {t('common.clear', { defaultValue: 'Clear' })}
              </button>
            )}
          </div>
          <label className="flex items-center gap-1.5 shrink-0 self-center ps-2 border-s border-border-light text-[11px] text-content-secondary cursor-pointer select-none whitespace-nowrap">
            <input
              type="checkbox"
              checked={scopeProject}
              onChange={(e) => setScopeProject(e.target.checked)}
              className="h-3.5 w-3.5 accent-oe-blue"
            />
            {t('global_search.scope_project', {
              defaultValue: 'Current project only',
            })}
          </label>
        </div>

        {/* Results — the single flex-grow scroll region. Header/input above and
            footer below stay pinned; only this area scrolls. */}
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
          {/* Saved searches */}
          {savedSearches.length > 0 && (
            <div className="px-4 pt-3 pb-1">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-content-secondary mb-1.5">
                {t('search.saved_searches', { defaultValue: 'Saved searches' })}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {savedSearches.map((s) => (
                  <button
                    key={s.query}
                    type="button"
                    onClick={() => handleClickSaved(s.query)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-full border border-border-light bg-surface-secondary text-content-secondary hover:bg-oe-blue/5 hover:text-oe-blue hover:border-oe-blue/30 transition-colors group"
                  >
                    <Bookmark size={10} className="shrink-0 opacity-60" />
                    <span className="truncate max-w-[180px]">{s.query}</span>
                    <span
                      role="button"
                      aria-label={t('search.remove_saved', { defaultValue: 'Remove' })}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRemoveSaved(s.query);
                      }}
                      className="shrink-0 rounded-full p-0.5 hover:bg-red-100 hover:text-red-600 transition-colors"
                    >
                      <X size={10} />
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

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
                    defaultValue: 'No matches yet - try a different phrasing',
                  })}
                </div>
              </div>
            )}

          {totalHits > 0 && (
            <div className="p-2 space-y-4">
              {Object.entries(grouped).map(([collection, hits]) => (
                <div key={collection}>
                  <div className="sticky top-0 z-10 flex items-center gap-2 px-2 py-1.5 bg-surface-primary/95 backdrop-blur-sm">
                    <span className="text-[11px] font-bold uppercase tracking-wide text-content-secondary">
                      {collectionLabel(t, collection)}
                    </span>
                    <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-surface-secondary text-[10px] font-semibold text-content-secondary tabular-nums">
                      {hits.length}
                    </span>
                    <span className="flex-1 h-px bg-border-light" />
                  </div>
                  <ul className="space-y-0.5">
                    {hits.map((hit) => {
                      // A collection the backend has grown and this build has
                      // not heard of has no route, and a row that looks
                      // clickable and then does nothing is worse than one
                      // that says so. Every collection the backend can return
                      // today is routed, so this is for the next one.
                      const navigable = hitToHref(hit) !== '#';
                      return (
                        <li key={`${hit.collection}:${hit.id}`}>
                          <button
                            type="button"
                            onClick={() => handleHitClick(hit)}
                            disabled={!navigable}
                            className={`w-full flex items-start gap-2 px-2.5 py-2 rounded-lg text-start border border-transparent transition-colors group ${
                              navigable
                                ? 'hover:bg-oe-blue/5 focus-visible:bg-oe-blue/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 hover:border-oe-blue/30'
                                : 'cursor-default opacity-60'
                            }`}
                          >
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-[13px] font-medium text-content-primary truncate">
                                  {hitLabel(
                                    hit,
                                    (c) => collectionLabel(t, c),
                                    (kind, ref) =>
                                      t('global_search.unnamed_hit', {
                                        defaultValue: '{{kind}} {{ref}}',
                                        kind,
                                        ref,
                                      }),
                                  )}
                                </span>
                                <span className="text-[10px] text-content-tertiary tabular-nums shrink-0">
                                  {Math.round(hit.score * 100)}%
                                </span>
                              </div>
                              {hit.snippet && (
                                <div className="text-[11px] text-content-tertiary line-clamp-2 mt-0.5 leading-snug">
                                  {hit.snippet}
                                </div>
                              )}
                            </div>
                            {navigable && (
                              <ArrowUpRight
                                size={13}
                                className="text-content-quaternary group-hover:text-oe-blue shrink-0 mt-0.5"
                              />
                            )}
                          </button>
                        </li>
                      );
                    })}
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
