// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// GlobalSearchPage — full page route ``/files/search`` for
// cross-project file lookup. Search box + kind filter + result list.
// Each result card opens the file inside its own project context
// (we keep the navigation explicit because the file-manager URL
// shape includes the project id).

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  ArrowUpDown,
  Clock,
  FileText,
  FolderOpen,
  Image as ImageIcon,
  Info,
  Layout,
  Search,
  X,
} from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { Input } from '@/shared/ui/Input';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ModuleGuideButton } from '@/shared/ui';
import { useGlobalFileSearch } from './hooks';
import { fileDistributionGuide } from './fileDistributionGuide';
import type { SearchHit, SearchHitKind } from './types';
import { compareNames } from '@/shared/lib/collator';

const RECENT_SEARCHES_KEY = 'oe_files_search_recent_v1';
const RECENT_MAX = 6;

type SortOrder = 'relevance' | 'name_asc' | 'project_asc';

const KIND_ICONS: Record<SearchHitKind, typeof FileText> = {
  document: FileText,
  sheet: Layout,
  photo: ImageIcon,
};

const ALL_KINDS: SearchHitKind[] = ['document', 'sheet', 'photo'];

interface SearchResultCardProps {
  hit: SearchHit;
}

export function SearchResultCard({ hit }: SearchResultCardProps) {
  const { t } = useTranslation();
  const Icon = KIND_ICONS[hit.kind] ?? FileText;
  // The file-manager page reads the project from the URL — point the
  // user there with the file pre-selected via ``selected`` query.
  const target = `/files?project=${encodeURIComponent(
    hit.project_id,
  )}&kind=${encodeURIComponent(hit.kind)}&selected=${encodeURIComponent(hit.file_id)}`;
  return (
    <Link
      to={target}
      data-testid={`search-result-${hit.file_id}`}
      className={clsx(
        'flex flex-col gap-1 rounded-lg border border-border bg-surface-primary',
        'px-4 py-3 hover:border-oe-blue hover:shadow-sm',
        'transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 shrink-0 text-content-secondary" />
        <span className="flex-1 truncate font-medium text-content-primary">
          {hit.canonical_name || t('files.global_search.unnamed', { defaultValue: '(unnamed)' })}
        </span>
        <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-[10px] uppercase tracking-wide text-content-tertiary">
          {hit.kind}
        </span>
      </div>
      <div className="flex items-center gap-2 text-xs text-content-tertiary">
        <span className="truncate">{hit.project_name}</span>
      </div>
      {hit.snippet && (
        <p className="line-clamp-2 text-xs text-content-secondary">{hit.snippet}</p>
      )}
    </Link>
  );
}

function loadRecentSearches(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_SEARCHES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((s): s is string => typeof s === 'string').slice(0, RECENT_MAX);
  } catch {
    return [];
  }
}

function saveRecentSearches(list: string[]) {
  try {
    localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch {
    /* localStorage full / unavailable — drop silently. */
  }
}

export function GlobalSearchPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQ = searchParams.get('q') ?? '';
  const [query, setQuery] = useState(initialQ);
  const [activeKinds, setActiveKinds] = useState<SearchHitKind[]>(ALL_KINDS);
  const [sort, setSort] = useState<SortOrder>('relevance');
  const [groupByProject, setGroupByProject] = useState(false);
  const [recent, setRecent] = useState<string[]>(() => loadRecentSearches());

  const { data, isFetching, error } = useGlobalFileSearch({
    q: query,
    kinds: activeKinds.length === ALL_KINDS.length ? undefined : activeKinds,
    limit: 200,
    enabled: query.trim().length > 0,
  });

  const rawHits = useMemo<SearchHit[]>(() => data?.items ?? [], [data]);

  const hits = useMemo<SearchHit[]>(() => {
    const list = [...rawHits];
    if (sort === 'name_asc') {
      list.sort((a, b) =>
        compareNames(a.canonical_name, b.canonical_name),
      );
    } else if (sort === 'project_asc') {
      list.sort((a, b) =>
        compareNames(a.project_name, b.project_name),
      );
    }
    return list;
  }, [rawHits, sort]);

  // Group hits by project_id (only used when `groupByProject` is on).
  // Preserves the order in which projects first appear in `hits`, so
  // the user still sees the most-relevant project at the top.
  const grouped = useMemo(() => {
    if (!groupByProject) return null;
    const map = new Map<string, { project_name: string; items: SearchHit[] }>();
    for (const hit of hits) {
      const key = hit.project_id;
      const bucket = map.get(key);
      if (bucket) {
        bucket.items.push(hit);
      } else {
        map.set(key, { project_name: hit.project_name ?? key, items: [hit] });
      }
    }
    return Array.from(map.entries()).map(([id, v]) => ({ id, ...v }));
  }, [hits, groupByProject]);

  const projectCount = useMemo(() => {
    if (rawHits.length === 0) return 0;
    return new Set(rawHits.map((h) => h.project_id)).size;
  }, [rawHits]);

  // Push the search term into the URL + local recent-searches list when
  // the user submits — so the page is shareable and the user gets quick
  // re-runs of their last few searches.
  const runSearch = (term: string) => {
    const trimmed = term.trim();
    setQuery(trimmed);
    const next = new URLSearchParams(searchParams);
    if (trimmed) {
      next.set('q', trimmed);
    } else {
      next.delete('q');
    }
    setSearchParams(next, { replace: true });
    if (trimmed) {
      setRecent((prev) => {
        const without = prev.filter((s) => s !== trimmed);
        const updated = [trimmed, ...without].slice(0, RECENT_MAX);
        saveRecentSearches(updated);
        return updated;
      });
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    runSearch(query);
  };

  const toggleKind = (kind: SearchHitKind) => {
    setActiveKinds((prev) => {
      if (prev.includes(kind)) {
        return prev.filter((k) => k !== kind);
      }
      return [...prev, kind];
    });
  };

  const clearRecent = () => {
    setRecent([]);
    saveRecentSearches([]);
  };

  // Re-fire a search when the URL ?q= changes externally (e.g. shared link)
  useEffect(() => {
    const urlQ = searchParams.get('q') ?? '';
    if (urlQ !== query) setQuery(urlQ);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.documents', { defaultValue: 'Documents' }), to: '/files' },
          {
            label: t('files.global_search.title', {
              defaultValue: 'Search across all projects',
            }),
          },
        ]}
      />

      <PageHeader
        srTitle={t('files.global_search.title', {
          defaultValue: 'Search across all projects',
        })}
        subtitle={t('files.global_search.subtitle', {
          defaultValue:
            'Find a document, sheet or photo by name across every project you can access.',
        })}
        actions={<ModuleGuideButton content={fileDistributionGuide} />}
      />

      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex flex-1 items-center gap-2 rounded-lg border border-border bg-surface-primary px-3 py-2 focus-within:border-oe-blue">
          <Search className="h-4 w-4 text-content-secondary shrink-0" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('files.global_search.placeholder', {
              defaultValue: 'e.g. foundation plan, RFI-014, IFC-arch',
            })}
            data-testid="global-search-input"
            className="flex-1 border-0 bg-transparent p-0 focus:ring-0"
            autoFocus
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label={t('files.global_search.clear', { defaultValue: 'Clear query' })}
              className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <Button type="submit" loading={isFetching}>
          {t('files.global_search.search_button', { defaultValue: 'Search' })}
        </Button>
      </form>

      {/* Recent searches — chip row (shows even with empty query). */}
      {recent.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-2"
          data-testid="global-search-recent"
        >
          <span className="inline-flex items-center gap-1 text-xs uppercase tracking-wide text-content-tertiary">
            <Clock className="h-3 w-3" />
            {t('files.global_search.recent_label', { defaultValue: 'Recent' })}
          </span>
          {recent.map((term) => (
            <button
              key={term}
              type="button"
              onClick={() => runSearch(term)}
              className="rounded-full border border-border bg-surface-primary px-2.5 py-1 text-xs text-content-secondary hover:border-oe-blue/40 hover:bg-oe-blue/5 hover:text-oe-blue"
            >
              {term}
            </button>
          ))}
          <button
            type="button"
            onClick={clearRecent}
            className="ml-1 text-[11px] text-content-tertiary underline-offset-2 hover:text-content-secondary hover:underline"
          >
            {t('files.global_search.clear_recent', { defaultValue: 'Clear' })}
          </button>
        </div>
      )}

      <div className="flex flex-col gap-4 lg:flex-row">
        {/* ── Filters rail ─────────────────────────────────────────────── */}
        <aside
          className="flex shrink-0 flex-col gap-4 lg:w-56"
          data-testid="global-search-filter-rail"
        >
          <section className="flex flex-col gap-2">
            <h2 className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('files.global_search.kind_filter_label', { defaultValue: 'File types' })}
            </h2>
            <div className="flex flex-wrap gap-1.5" data-testid="global-search-kind-filters">
              {ALL_KINDS.map((kind) => {
                const Icon = KIND_ICONS[kind];
                const on = activeKinds.includes(kind);
                const labelKey = `files.global_search.kind_${kind}`;
                return (
                  <button
                    key={kind}
                    type="button"
                    onClick={() => toggleKind(kind)}
                    aria-pressed={on}
                    className={clsx(
                      'inline-flex w-full items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs',
                      on
                        ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                        : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    <span className="flex-1 text-left capitalize">
                      {t(labelKey, { defaultValue: kind })}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('files.global_search.sort_label', { defaultValue: 'Sort by' })}
            </h2>
            <div className="flex flex-col gap-1">
              {(['relevance', 'name_asc', 'project_asc'] as const).map((key) => {
                const on = sort === key;
                const label = t(`files.global_search.sort_${key}`, {
                  defaultValue:
                    key === 'relevance' ? 'Relevance' : key === 'name_asc' ? 'Name (A→Z)' : 'Project (A→Z)',
                });
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setSort(key)}
                    aria-pressed={on}
                    className={clsx(
                      'inline-flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs',
                      on
                        ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                        : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                    )}
                  >
                    <ArrowUpDown className="h-3 w-3" />
                    <span className="flex-1 text-left">{label}</span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('files.global_search.view_label', { defaultValue: 'View' })}
            </h2>
            <button
              type="button"
              onClick={() => setGroupByProject((v) => !v)}
              aria-pressed={groupByProject}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs',
                groupByProject
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
              )}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              <span className="flex-1 text-left">
                {t('files.global_search.group_by_project', {
                  defaultValue: 'Group by project',
                })}
              </span>
            </button>
          </section>

          {data && !data.used_content_index && (
            <div
              role="note"
              className="flex items-start gap-1.5 rounded-md border border-border-light bg-surface-secondary px-2.5 py-2 text-[11px] text-content-secondary"
            >
              <Info className="mt-0.5 h-3 w-3 shrink-0 text-content-tertiary" />
              <span>
                {t('files.global_search.metadata_only_notice', {
                  defaultValue:
                    'Searching file names only - content-text index is not installed on this build.',
                })}
              </span>
            </div>
          )}
        </aside>

        {/* ── Results ──────────────────────────────────────────────────── */}
        <section className="flex min-w-0 flex-1 flex-col gap-3" data-testid="global-search-results">
          {/* Summary header — shown only when a search has produced data */}
          {query.trim().length > 0 && rawHits.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light pb-2">
              <p className="text-sm text-content-secondary">
                <strong className="text-content-primary">{rawHits.length}</strong>{' '}
                {t('files.global_search.summary_results', {
                  defaultValue: 'results across',
                })}{' '}
                <strong className="text-content-primary">{projectCount}</strong>{' '}
                {t('files.global_search.summary_projects', {
                  defaultValue: 'project',
                  defaultValue_other: 'projects',
                  count: projectCount,
                })}
              </p>
              {data?.used_content_index && (
                <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-emerald-600">
                  {t('files.global_search.content_index_badge', {
                    defaultValue: 'Full-text index',
                  })}
                </span>
              )}
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="rounded-md border border-semantic-error/40 bg-semantic-error/10 px-3 py-2 text-sm text-semantic-error"
            >
              {error instanceof Error ? error.message : String(error)}
            </div>
          )}

          {query.trim().length === 0 && (
            <p className="text-sm text-content-tertiary">
              {t('files.global_search.empty_state', {
                defaultValue: 'Type a search above to begin.',
              })}
            </p>
          )}
          {query.trim().length > 0 && !isFetching && hits.length === 0 && (
            <p className="text-sm text-content-tertiary">
              {t('files.global_search.no_results', {
                defaultValue: 'No files matched your search.',
              })}
            </p>
          )}

          {groupByProject && grouped ? (
            grouped.map((group) => (
              <div key={group.id} className="flex flex-col gap-2">
                <h3 className="sticky top-0 z-[1] bg-surface-secondary/80 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary backdrop-blur">
                  {group.project_name} · {group.items.length}
                </h3>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                  {group.items.map((hit) => (
                    <SearchResultCard key={`${hit.kind}-${hit.file_id}`} hit={hit} />
                  ))}
                </div>
              </div>
            ))
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {hits.map((hit) => (
                <SearchResultCard key={`${hit.kind}-${hit.file_id}`} hit={hit} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
