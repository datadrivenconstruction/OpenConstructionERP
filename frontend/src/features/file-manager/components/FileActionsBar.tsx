// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Toolbar above the file grid/list — search, filters, view toggle, export/import. */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, X, ChevronDown, LayoutGrid, List, Download, Upload, MoreHorizontal, Star, Loader2, RefreshCw } from 'lucide-react';
import clsx from 'clsx';
import type { FileFilters } from '../types';
import { SaveViewButton } from '@/features/file-saved-views';
import type { FilterSnapshot } from '@/features/file-saved-views';
import { TagFilterFacet } from '@/features/file-tags/TagFilterFacet';
import { SearchModeToggle } from '@/features/file-search/SearchModeToggle';
import type { SearchMode } from '@/features/file-search/types';

type SortKey = NonNullable<FileFilters['sort']>;
export type ViewMode = 'grid' | 'list';

interface FileActionsBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  sort: SortKey;
  onSortChange: (s: SortKey) => void;
  view: ViewMode;
  onViewChange: (v: ViewMode) => void;
  onExport: () => void;
  onImport: () => void;
  totalCount: number;
  extension?: string | undefined;
  onExtensionChange?: (ext: string | undefined) => void;
  /** Active project — enables Save-view + Tag filter facet (W4/W5). */
  projectId?: string | null;
  /** Current category — used to build the FilterSnapshot for Save view. */
  category?: string | null;
  /** W4 — multi-select tag filter state. Owned by the page so the URL
   *  round-trip (saved views + bookmarkable filters) stays loss-less. */
  selectedTagIds?: string[];
  onSelectedTagsChange?: (tagIds: string[]) => void;
  /** "Favourites only" filter — keeps just the rows the user has starred. */
  favoritesOnly?: boolean;
  onFavoritesOnlyChange?: (on: boolean) => void;
  /** Number of favourites in this project — shown on the chip. */
  favoritesCount?: number;
  /** W3 — filename vs content (OCR) search. Omitting ``onSearchModeChange``
   *  hides the toggle and keeps the plain filename search behaviour. */
  searchMode?: SearchMode;
  onSearchModeChange?: (mode: SearchMode) => void;
  /** Re-run OCR/index for the whole project (content search). */
  onReindex?: () => void;
  reindexing?: boolean;
}

/* Always-visible type pills — the high-traffic AECO formats. Each maps to one
   `?extension=` value passed to the backend. */
const TYPE_PILLS: { key: string; label: string; ext?: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'pdf', label: 'PDF', ext: 'pdf' },
  { key: 'image', label: 'Images', ext: 'jpg' },
  { key: 'cad', label: 'CAD', ext: 'dwg' },
  { key: 'bim', label: 'BIM', ext: 'ifc' },
  { key: 'office', label: 'Office', ext: 'xlsx' },
];

/* Long tail of less-frequent but still essential AECO formats. Surface them
   in a "More" overflow popover so the primary row stays compact. */
const EXTRA_PILLS: { key: string; label: string; ext: string }[] = [
  { key: 'rvt', label: 'BIM Model (RVT)', ext: 'rvt' },
  { key: 'rfa', label: 'BIM Family (RFA)', ext: 'rfa' },
  { key: 'nwd', label: 'Coordination Model (NWD)', ext: 'nwd' },
  { key: 'dwf', label: 'Design Web Format (DWF)', ext: 'dwf' },
  { key: 'docx', label: 'Word (DOCX)', ext: 'docx' },
  { key: 'mpp', label: 'MS Project (MPP)', ext: 'mpp' },
  { key: 'pptx', label: 'PowerPoint (PPTX)', ext: 'pptx' },
  { key: 'zip', label: 'Archive (ZIP)', ext: 'zip' },
];

export function FileActionsBar({
  query,
  onQueryChange,
  sort,
  onSortChange,
  view,
  onViewChange,
  onExport,
  onImport,
  totalCount,
  extension,
  onExtensionChange,
  projectId,
  category,
  selectedTagIds,
  onSelectedTagsChange,
  favoritesOnly = false,
  onFavoritesOnlyChange,
  favoritesCount,
  searchMode = 'filename',
  onSearchModeChange,
  onReindex,
  reindexing = false,
}: FileActionsBarProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(query);
  const [sortOpen, setSortOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const sortRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);

  // Sync external query changes back into the draft (e.g. when user clears).
  useEffect(() => {
    setDraft(query);
  }, [query]);

  // Debounce the search-box → URL/query update so we don't spam the API
  // on every keystroke. 250 ms feels instant while still batching typing.
  useEffect(() => {
    const handle = setTimeout(() => {
      if (draft !== query) onQueryChange(draft);
    }, 250);
    return () => clearTimeout(handle);
  }, [draft, query, onQueryChange]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (sortRef.current && !sortRef.current.contains(e.target as Node)) {
        setSortOpen(false);
      }
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) {
        setMoreOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const extraActive = !!extension && EXTRA_PILLS.some((p) => p.ext === extension);

  const sortLabels: Record<SortKey, string> = {
    modified: t('files.sort.modified', { defaultValue: 'Modified' }),
    name: t('files.sort.name', { defaultValue: 'Name' }),
    size: t('files.sort.size', { defaultValue: 'Size' }),
    kind: t('files.sort.kind', { defaultValue: 'Type' }),
  };

  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b border-border-light bg-surface-elevated">
      <div className="relative flex-1 min-w-[200px] max-w-md">
        <Search
          size={14}
          className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none"
        />
        <input
          type="search"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            searchMode === 'content'
              ? t('files.search.inside', { defaultValue: 'Search inside files' })
              : t('files.search_placeholder', { defaultValue: 'Search files…' })
          }
          className="w-full h-9 ps-8 pe-8 text-sm rounded-lg border border-border-light bg-surface-primary text-content-primary placeholder:text-content-tertiary focus:outline-none focus:border-oe-blue focus:ring-2 focus:ring-oe-blue/20"
        />
        {draft && (
          <button
            type="button"
            onClick={() => setDraft('')}
            aria-label={t('common.clear', { defaultValue: 'Clear' })}
            className="absolute end-2 top-1/2 -translate-y-1/2 p-0.5 text-content-tertiary hover:text-content-primary"
          >
            <X size={12} />
          </button>
        )}
      </div>

      {/* W3 — filename vs content (OCR) search toggle, sitting right next to
          the search box. Content mode searches inside the files' text. */}
      {onSearchModeChange && (
        <SearchModeToggle mode={searchMode} onChange={onSearchModeChange} />
      )}
      {onReindex && searchMode === 'content' && (
        <button
          type="button"
          onClick={onReindex}
          disabled={reindexing}
          className="inline-flex items-center gap-1.5 h-7 px-2 rounded-full text-[11px] font-medium text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors disabled:opacity-60"
          title={t('files.search.reindex_hint', {
            defaultValue: 'Re-scan every file so recent uploads become searchable by their text',
          })}
        >
          {reindexing ? (
            <Loader2 size={11} className="animate-spin" />
          ) : (
            <RefreshCw size={11} />
          )}
          <span className="hidden md:inline">
            {t('files.search.reindex', { defaultValue: 'Update search index' })}
          </span>
        </button>
      )}

      <span className="text-2xs text-content-tertiary tabular-nums">
        {totalCount} {t('files.count_files', { defaultValue: 'files' })}
      </span>

      {onExtensionChange && (
        <div className="inline-flex items-center gap-1">
          {TYPE_PILLS.map((p) => {
            const active = p.ext ? extension === p.ext : !extension;
            return (
              <button
                key={p.key}
                type="button"
                onClick={() => onExtensionChange(p.ext)}
                className={clsx(
                  'inline-flex h-7 items-center rounded-full px-2.5 text-[11px] font-medium transition-colors',
                  active
                    ? 'bg-oe-blue text-white'
                    : 'border border-border-light text-content-secondary hover:bg-surface-secondary',
                )}
                aria-pressed={active}
              >
                {t(`files.type_pill.${p.key}`, { defaultValue: p.label })}
              </button>
            );
          })}
          <div ref={moreRef} className="relative">
            <button
              type="button"
              onClick={() => setMoreOpen((p) => !p)}
              aria-haspopup="listbox"
              aria-expanded={moreOpen}
              className={clsx(
                'inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11px] font-medium transition-colors',
                extraActive
                  ? 'bg-oe-blue text-white'
                  : 'border border-border-light text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {extraActive
                ? EXTRA_PILLS.find((p) => p.ext === extension)?.label.split(' ')[0]
                : t('files.type_pill.more', { defaultValue: 'More' })}
              <MoreHorizontal size={11} />
            </button>
            {moreOpen && (
              <div
                role="listbox"
                className="absolute left-0 top-full mt-1 w-48 rounded-lg border border-border-light bg-surface-elevated shadow-lg z-20 overflow-hidden"
              >
                {EXTRA_PILLS.map((p) => (
                  <button
                    key={p.key}
                    role="option"
                    aria-selected={extension === p.ext}
                    onClick={() => {
                      onExtensionChange(extension === p.ext ? undefined : p.ext);
                      setMoreOpen(false);
                    }}
                    className={clsx(
                      'w-full px-3 py-1.5 text-left text-[11px] transition-colors',
                      extension === p.ext
                        ? 'bg-oe-blue/10 text-oe-blue font-medium'
                        : 'text-content-secondary hover:bg-surface-secondary',
                    )}
                  >
                    {t(`files.type_pill.${p.key}`, { defaultValue: p.label })}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="ms-auto flex items-center gap-2">
        {onFavoritesOnlyChange && (
          <button
            type="button"
            onClick={() => onFavoritesOnlyChange(!favoritesOnly)}
            aria-pressed={favoritesOnly}
            className={clsx(
              'inline-flex items-center gap-1.5 h-9 px-3 text-xs font-medium rounded-lg border transition-colors',
              favoritesOnly
                ? 'border-amber-400 bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400 dark:border-amber-500/40'
                : 'border-border-light text-content-secondary hover:bg-surface-secondary',
            )}
            title={t('files.favorites.filter', { defaultValue: 'Show favourites only' })}
          >
            <Star size={13} strokeWidth={2} fill={favoritesOnly ? 'currentColor' : 'none'} />
            <span>{t('files.favorites.label', { defaultValue: 'Favourites' })}</span>
            {typeof favoritesCount === 'number' && favoritesCount > 0 && (
              <span className="tabular-nums opacity-70">{favoritesCount}</span>
            )}
          </button>
        )}
        {projectId && onSelectedTagsChange && (
          <TagFilterFacet
            projectId={projectId}
            selectedTagIds={selectedTagIds ?? []}
            onChange={onSelectedTagsChange}
          />
        )}
        {projectId && (
          <SaveViewButton
            projectId={projectId}
            filter={{
              kind: category ?? null,
              q: query || null,
              sort: sort || null,
              extension: extension ?? null,
              ...(selectedTagIds && selectedTagIds.length > 0
                ? { tag_ids: selectedTagIds }
                : {}),
            } as FilterSnapshot}
            visible={Boolean(
              query ||
                category ||
                extension ||
                (sort && sort !== 'modified') ||
                (selectedTagIds && selectedTagIds.length > 0),
            )}
          />
        )}
        <div ref={sortRef} className="relative">
          <button
            type="button"
            onClick={() => setSortOpen((p) => !p)}
            aria-haspopup="listbox"
            aria-expanded={sortOpen}
            className="flex items-center gap-1.5 h-9 px-3 text-xs font-medium rounded-lg border border-border-light text-content-secondary hover:bg-surface-secondary"
          >
            {t('files.sort_by', { defaultValue: 'Sort' })}: {sortLabels[sort]}
            <ChevronDown size={12} className={clsx('transition-transform', sortOpen && 'rotate-180')} />
          </button>
          {sortOpen && (
            <div
              role="listbox"
              className="absolute right-0 top-full mt-1 w-40 rounded-lg border border-border-light bg-surface-elevated shadow-lg z-20 overflow-hidden"
            >
              {(['modified', 'name', 'size', 'kind'] as SortKey[]).map((k) => (
                <button
                  key={k}
                  role="option"
                  aria-selected={sort === k}
                  onClick={() => {
                    onSortChange(k);
                    setSortOpen(false);
                  }}
                  className={clsx(
                    'w-full px-3 py-2 text-left text-xs transition-colors',
                    sort === k
                      ? 'bg-oe-blue/10 text-oe-blue font-medium'
                      : 'text-content-secondary hover:bg-surface-secondary',
                  )}
                >
                  {sortLabels[k]}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="inline-flex rounded-lg border border-border-light overflow-hidden">
          <ViewBtn
            active={view === 'grid'}
            onClick={() => onViewChange('grid')}
            label={t('files.view_grid', { defaultValue: 'Grid view' })}
          >
            <LayoutGrid size={14} />
          </ViewBtn>
          <ViewBtn
            active={view === 'list'}
            onClick={() => onViewChange('list')}
            label={t('files.view_list', { defaultValue: 'List view' })}
          >
            <List size={14} />
          </ViewBtn>
        </div>

        <button
          type="button"
          onClick={onImport}
          className="inline-flex items-center gap-1.5 h-9 px-3 text-xs font-medium rounded-lg border border-border-light text-content-secondary hover:bg-surface-secondary"
        >
          <Upload size={13} />
          {t('files.actions.import', { defaultValue: 'Import' })}
        </button>
        <button
          type="button"
          onClick={onExport}
          className="inline-flex items-center gap-1.5 h-9 px-3 text-xs font-medium rounded-lg bg-oe-blue text-white hover:bg-oe-blue-hover"
        >
          <Download size={13} />
          {t('files.actions.export', { defaultValue: 'Export' })}
        </button>
      </div>
    </div>
  );
}

function ViewBtn({
  active,
  onClick,
  label,
  children,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      title={label}
      className={clsx(
        'flex items-center justify-center w-9 h-9 transition-colors',
        active
          ? 'bg-oe-blue/10 text-oe-blue'
          : 'text-content-tertiary hover:bg-surface-secondary hover:text-content-primary',
      )}
    >
      {children}
    </button>
  );
}
