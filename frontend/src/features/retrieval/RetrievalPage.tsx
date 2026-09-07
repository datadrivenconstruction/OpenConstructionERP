// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Find records - one faceted, ranked search across the whole project record
// (documents, correspondence, change orders). Every hit carries provenance
// (owning module, record type, id and the date the event occurred) so a claim
// or a dispute can be reconstructed from the evidence without hunting through
// each module in turn. Read-only and scoped to the selected project.
//
// Beyond the raw search the page adds the retrieval-quality basics: each result
// deep-links to the module that owns it, results can be re-sorted and paged,
// the query term is highlighted in titles and snippets, and searches can be
// saved or re-run from history. The backend indexes exactly three record types
// today (see RetrievalService.gather); broadening coverage needs a backend
// change, so the type filter deliberately lists only those three.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  FileSearch,
  Inbox,
  Search,
  SlidersHorizontal,
} from 'lucide-react';
import { Badge, Card, DismissibleInfo, EmptyState, IntroRichText, SkeletonTable } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  createSavedSearch,
  deleteSavedSearch,
  listSavedSearches,
  recordSavedSearchUse,
  searchRecords,
} from './api';
import { buildHighlightTerms, HighlightedText } from './highlight';
import { NoProjectState } from './NoProjectState';
import { SavedSearches } from './SavedSearchesPanel';
import {
  clearRecent,
  isMeaningfulQuery,
  pushRecent,
  querySignature,
  readRecent,
} from './savedSearches';
import type { RetrievalQuery, RetrievalResult, SavedSearch } from './types';
import { fmtList, fmtFixed } from '@/shared/lib/formatters';
import { compareNames } from '@/shared/lib/collator';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';
type SortMode = 'relevance' | 'date' | 'type';

/** Client-side page size (the API returns the full ranked set in one call). */
const PAGE_SIZE = 10;

/** Stable empty array so memo deps do not change when a search returns nothing. */
const NO_RESULTS: RetrievalResult[] = [];

/** Same, for the pinned-search list while it loads or comes back empty. */
const NO_SAVED: SavedSearch[] = [];

const RECORD_TYPE_VARIANT: Record<string, BadgeVariant> = {
  document: 'blue',
  correspondence: 'success',
  change_order: 'warning',
};

// Long-form intro shown behind "Show more". Kept as a module constant so the
// JSX stays readable; the markers (blank line, "- ", **bold**) are what
// IntroRichText renders. No em-dashes, per the house style.
const INTRO_MORE = [
  'Find Records searches three parts of the project record at once:',
  '',
  '- **Documents** - files, drawings and their descriptions',
  '- **Correspondence** - letters, emails and logged messages',
  '- **Change orders** - variations and their commercial detail',
  '',
  'Results are ranked by how well they match your terms, how recent they are and which party they involve. Every hit shows its source module, record id and date, and opens straight to the record it came from. Use Filters to narrow by party, record type or date range, change Sort to reorder the list, and Save this search to re-run it later.',
].join('\n');

function recordTypeLabel(
  t: (k: string, o: { defaultValue: string }) => string,
  recordType: string,
): string {
  switch (recordType) {
    case 'document':
      return t('retrieval.type_document', { defaultValue: 'Document' });
    case 'correspondence':
      return t('retrieval.type_correspondence', { defaultValue: 'Correspondence' });
    case 'change_order':
      return t('retrieval.type_change_order', { defaultValue: 'Change order' });
    default:
      return recordType;
  }
}

/**
 * Deep-link a result to the module that owns it, or null when the type has no
 * destination (then the card renders as plain text, never a dead link). Routes
 * verified against App.tsx:
 *   - document       -> /files?file=<id>  (File Manager focuses that file)
 *   - correspondence -> /correspondence   (list; no per-record route exists)
 *   - change_order   -> /changeorders     (list; the detail view is in-page state)
 */
function recordHref(result: RetrievalResult): string | null {
  switch (result.record_type) {
    case 'document':
      return `/files?file=${encodeURIComponent(result.record_id)}`;
    case 'correspondence':
      return '/correspondence';
    case 'change_order':
      return '/changeorders';
    default:
      return null;
  }
}

/** Leading ISO date (YYYY-MM-DD) of a value, or "" when unknown. */
function dateKey(iso: string): string {
  return iso ? iso.slice(0, 10) : '';
}

/**
 * Re-order a returned result set client-side. Relevance keeps the server order
 * (already score-then-recency ranked); date is newest-first with unknown dates
 * last; type groups alphabetically by the translated label. Array.sort is
 * stable, so ties inside date/type keep their relevance order.
 */
function sortResults(
  list: RetrievalResult[],
  mode: SortMode,
  typeLabel: (recordType: string) => string,
): RetrievalResult[] {
  if (mode === 'relevance') return list;
  const copy = [...list];
  if (mode === 'date') {
    copy.sort((a, b) => {
      const ka = dateKey(a.occurred_at);
      const kb = dateKey(b.occurred_at);
      if (ka === kb) return 0;
      if (!ka) return 1;
      if (!kb) return -1;
      return ka < kb ? 1 : -1;
    });
    return copy;
  }
  copy.sort((a, b) => compareNames(typeLabel(a.record_type), typeLabel(b.record_type)));
  return copy;
}

function ResultCard({
  result,
  highlightTerms,
}: {
  result: RetrievalResult;
  highlightTerms: string[];
}) {
  const { t } = useTranslation();
  const variant = RECORD_TYPE_VARIANT[result.record_type] ?? 'neutral';
  const href = recordHref(result);
  const untitled = t('retrieval.untitled', { defaultValue: 'Untitled' });
  const title = result.title ? (
    <HighlightedText text={result.title} terms={highlightTerms} />
  ) : (
    untitled
  );

  return (
    <Card className="space-y-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={variant}>{recordTypeLabel(t, result.record_type)}</Badge>
        {href ? (
          <Link
            to={href}
            className="text-sm font-semibold text-content-primary transition-colors hover:text-oe-blue-text hover:underline"
          >
            {title}
          </Link>
        ) : (
          <span className="text-sm font-semibold text-content-primary">{title}</span>
        )}
        <div className="ms-auto flex items-center gap-2">
          <span className="text-xs tabular-nums text-content-tertiary">
            {t('retrieval.score', {
              defaultValue: 'score {{score}}',
              score: fmtFixed(result.score, 2),
            })}
          </span>
          {href && (
            <Link
              to={href}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium text-oe-blue-text transition-colors hover:bg-oe-blue/10"
            >
              <ArrowUpRight className="h-3.5 w-3.5" />
              {t('retrieval.open', { defaultValue: 'Open' })}
            </Link>
          )}
        </div>
      </div>
      {result.snippet && (
        <p className="text-sm text-content-secondary">
          <HighlightedText text={result.snippet} terms={highlightTerms} />
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-tertiary">
        <span>{result.source_module}</span>
        {result.party && <span>{result.party}</span>}
        {result.occurred_at && <span>{result.occurred_at.slice(0, 10)}</span>}
        {result.entity_refs.map((ref) => (
          <code key={ref} className="rounded bg-surface-secondary px-1.5 py-0.5">
            {ref}
          </code>
        ))}
      </div>
      {result.matched_facets.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-content-tertiary">
            {t('retrieval.matched', { defaultValue: 'Matched:' })}
          </span>
          {result.matched_facets.map((facet) => (
            <Badge key={facet} variant="neutral">
              {facet}
            </Badge>
          ))}
        </div>
      )}
    </Card>
  );
}

export function RetrievalPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId ?? activeProjectId ?? '';

  // The form state is the draft; `query` is the committed search the API runs.
  const [text, setText] = useState('');
  const [party, setParty] = useState('');
  const [recordType, setRecordType] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [query, setQuery] = useState<RetrievalQuery | null>(null);

  // View state over the returned set (all client-side - the API has no sort or
  // paging params).
  const [sort, setSort] = useState<SortMode>('relevance');
  const [page, setPage] = useState(1);

  // Recent searches are per-device scratch and stay in localStorage. Pinned
  // searches are server-owned, so they survive a reload and follow the person
  // to another machine.
  const [recent, setRecent] = useState<RetrievalQuery[]>(() => readRecent());

  const searchQuery = useQuery({
    queryKey: ['retrieval', 'search', projectId, query],
    queryFn: () => searchRecords(projectId, query ?? {}),
    enabled: !!projectId && query !== null,
    retry: false,
  });

  const queryClient = useQueryClient();
  const savedKey = useMemo(() => ['retrieval', 'saved-searches', projectId], [projectId]);
  const savedSearchesQuery = useQuery({
    queryKey: savedKey,
    queryFn: () => listSavedSearches(projectId),
    // The page renders before the project context resolves; asking for pins on
    // no project is a guaranteed 422.
    enabled: !!projectId,
    retry: false,
  });
  const saved = savedSearchesQuery.data?.results ?? NO_SAVED;

  const invalidateSaved = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: savedKey });
  }, [queryClient, savedKey]);

  const saveMutation = useMutation({
    mutationFn: (vars: { label: string; query: RetrievalQuery }) =>
      createSavedSearch(projectId, vars.label, vars.query),
    onSuccess: invalidateSaved,
  });

  const removeMutation = useMutation({
    mutationFn: (savedId: string) => deleteSavedSearch(savedId),
    onSuccess: invalidateSaved,
  });

  // Replaying a pin bumps it up the list. Nobody asked for this write, so a
  // failure stays quiet: the search itself already ran and the only casualty
  // is the ordering of a list the user is looking straight at.
  const recordUseMutation = useMutation({
    mutationFn: (savedId: string) => recordSavedSearchUse(savedId),
    onSuccess: invalidateSaved,
    meta: { suppressGlobalErrorToast: true },
  });

  const runSearch = () => {
    const next: RetrievalQuery = {
      text,
      party,
      record_type: recordType,
      date_from: dateFrom,
      date_to: dateTo,
    };
    setQuery(next);
    setRecent(pushRecent(next));
    setPage(1);
  };

  // Re-run a saved / recent search: reflect it in the form and commit it.
  const applyQuery = (q: RetrievalQuery) => {
    setText(q.text ?? '');
    setParty(q.party ?? '');
    setRecordType(q.record_type ?? '');
    setDateFrom(q.date_from ?? '');
    setDateTo(q.date_to ?? '');
    setQuery(q);
    setRecent(pushRecent(q));
    setPage(1);
  };

  // A short, translated label for a query - the search text if any, else a
  // summary of the active facets.
  const describeQuery = (q: RetrievalQuery): string => {
    const queryText = q.text?.trim();
    if (queryText) return queryText;
    const parts: string[] = [];
    const type = q.record_type?.trim();
    if (type) parts.push(recordTypeLabel(t, type));
    const partyValue = q.party?.trim();
    if (partyValue) {
      parts.push(t('retrieval.saved_party', { defaultValue: 'Party {{party}}', party: partyValue }));
    }
    const from = q.date_from?.trim();
    if (from) parts.push(t('retrieval.saved_from', { defaultValue: 'from {{date}}', date: from }));
    const to = q.date_to?.trim();
    if (to) parts.push(t('retrieval.saved_to', { defaultValue: 'to {{date}}', date: to }));
    return parts.length > 0
      ? fmtList(parts)
      : t('retrieval.saved_all', { defaultValue: 'All records' });
  };

  // Re-run a pin, and tell the server it was used so the list keeps ordering
  // itself by what this person actually reaches for.
  const runSavedSearch = (s: SavedSearch) => {
    applyQuery(s.query);
    recordUseMutation.mutate(s.id);
  };

  const handleSaveCurrent = () => {
    if (!query || !isMeaningfulQuery(query)) return;
    saveMutation.mutate({ label: describeQuery(query), query });
  };

  // Compared through the client signature on both sides rather than against the
  // server's `signature` field: the two are computed differently, and the only
  // question here is whether these facets are already pinned.
  const currentIsSaved = useMemo(
    () =>
      query ? saved.some((s) => querySignature(s.query) === querySignature(query)) : false,
    [query, saved],
  );
  const currentCanSave = query ? isMeaningfulQuery(query) : false;

  const results = searchQuery.data?.results ?? NO_RESULTS;
  const sortedResults = useMemo(
    () => sortResults(results, sort, (rt) => recordTypeLabel(t, rt)),
    [results, sort, t],
  );
  const highlightTerms = useMemo(() => buildHighlightTerms(query?.text ?? ''), [query]);

  const total = sortedResults.length;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageResults = useMemo(
    () => sortedResults.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [sortedResults, page],
  );

  // A new search or a re-sort returns the reader to the first page.
  useEffect(() => {
    setPage(1);
  }, [query, sort]);

  // Never strand the reader past the last page if a refetch shrinks the set.
  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  if (!projectId) {
    return <NoProjectState />;
  }

  const rangeFrom = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeTo = Math.min(page * PAGE_SIZE, total);

  return (
    <div className="space-y-4 p-1">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold text-content-primary">
          <FileSearch className="h-5 w-5" />
          {t('retrieval.title', { defaultValue: 'Find Records' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('retrieval.subtitle', {
            defaultValue:
              'Search documents, correspondence and change orders in one place, ranked and with provenance.',
          })}
        </p>
      </div>

      <DismissibleInfo
        storageKey="retrieval-intro"
        title={t('retrieval.intro_title', { defaultValue: 'Claim-grade search' })}
        more={<IntroRichText text={t('retrieval.intro_more', { defaultValue: INTRO_MORE })} />}
        links={[
          {
            label: t('retrieval.link_documents', { defaultValue: 'Documents' }),
            onClick: () => navigate('/files'),
          },
          {
            label: t('retrieval.link_correspondence', { defaultValue: 'Correspondence' }),
            onClick: () => navigate('/correspondence'),
          },
          {
            label: t('retrieval.link_change_orders', { defaultValue: 'Change orders' }),
            onClick: () => navigate('/changeorders'),
          },
        ]}
      >
        {t('retrieval.intro_body', {
          defaultValue:
            'One search runs across every part of the project record at once. Narrow by party, date range or record type. Each result carries its source module, record id and the date it happened, so you can rebuild the chain of evidence behind a claim or a dispute. Leave the box empty and search to browse everything, newest first.',
        })}
      </DismissibleInfo>

      <Card className="space-y-3 p-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute start-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') runSearch();
              }}
              placeholder={t('retrieval.text_ph', { defaultValue: 'Search the project record...' })}
              className="w-full rounded-md border border-border-light bg-surface-primary ps-8 pe-2 py-2 text-sm text-content-primary"
            />
          </div>
          <button
            type="button"
            onClick={runSearch}
            className="inline-flex items-center justify-center gap-1.5 rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white"
          >
            <Search className="h-4 w-4" />
            {t('retrieval.search', { defaultValue: 'Search' })}
          </button>
        </div>

        <details className="text-sm">
          <summary className="flex cursor-pointer items-center gap-1.5 text-content-secondary">
            <SlidersHorizontal className="h-4 w-4" />
            {t('retrieval.filters', { defaultValue: 'Filters' })}
          </summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm text-content-secondary">
              {t('retrieval.party', { defaultValue: 'Party' })}
              <input
                value={party}
                onChange={(e) => setParty(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') runSearch();
                }}
                placeholder={t('retrieval.party_ph', { defaultValue: 'e.g. contractor-a' })}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm text-content-secondary">
              {t('retrieval.record_type', { defaultValue: 'Record type' })}
              <select
                value={recordType}
                onChange={(e) => setRecordType(e.target.value)}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
              >
                <option value="">{t('retrieval.type_any', { defaultValue: 'Any type' })}</option>
                <option value="document">
                  {t('retrieval.type_document', { defaultValue: 'Document' })}
                </option>
                <option value="correspondence">
                  {t('retrieval.type_correspondence', { defaultValue: 'Correspondence' })}
                </option>
                <option value="change_order">
                  {t('retrieval.type_change_order', { defaultValue: 'Change order' })}
                </option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm text-content-secondary">
              {t('retrieval.date_from', { defaultValue: 'From date' })}
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') runSearch();
                }}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm text-content-secondary">
              {t('retrieval.date_to', { defaultValue: 'To date' })}
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') runSearch();
                }}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
              />
            </label>
          </div>
        </details>
      </Card>

      <SavedSearches
        recent={recent}
        saved={saved}
        currentCanSave={currentCanSave}
        currentIsSaved={currentIsSaved}
        saveBusy={saveMutation.isPending}
        describeQuery={describeQuery}
        onRun={applyQuery}
        onRunSaved={runSavedSearch}
        onSaveCurrent={handleSaveCurrent}
        onRemoveSaved={(id) => removeMutation.mutate(id)}
        onClearRecent={() => setRecent(clearRecent())}
      />

      {searchQuery.isLoading ? (
        <SkeletonTable rows={3} />
      ) : searchQuery.isError ? (
        <EmptyState
          icon={<Inbox className="h-6 w-6" />}
          title={t('retrieval.error_title', { defaultValue: 'Search failed' })}
          description={getErrorMessage(searchQuery.error)}
        />
      ) : query === null ? (
        <EmptyState
          icon={<FileSearch className="h-6 w-6" />}
          title={t('retrieval.start_title', { defaultValue: 'Search the project record' })}
          description={t('retrieval.start_desc', {
            defaultValue:
              'Enter a term or open Filters, then search. Leave the box empty to browse everything.',
          })}
        />
      ) : total === 0 ? (
        <EmptyState
          icon={<Inbox className="h-6 w-6" />}
          title={t('retrieval.empty_title', { defaultValue: 'No matching records' })}
          description={t('retrieval.empty_desc', {
            defaultValue:
              'Nothing on the project record matched these facets. Try widening the search.',
          })}
        />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-content-tertiary">
              {pageCount > 1
                ? t('retrieval.showing_range', {
                    defaultValue: 'Showing {{from}}-{{to}} of {{total}}',
                    from: rangeFrom,
                    to: rangeTo,
                    total,
                  })
                : t('retrieval.result_count', { defaultValue: '{{total}} results', total })}
            </p>
            <label className="flex items-center gap-1.5 text-xs text-content-secondary">
              {t('retrieval.sort_label', { defaultValue: 'Sort by' })}
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as SortMode)}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary"
              >
                <option value="relevance">
                  {t('retrieval.sort_relevance', { defaultValue: 'Relevance' })}
                </option>
                <option value="date">
                  {t('retrieval.sort_date', { defaultValue: 'Newest first' })}
                </option>
                <option value="type">
                  {t('retrieval.sort_type', { defaultValue: 'Record type' })}
                </option>
              </select>
            </label>
          </div>

          {pageResults.map((result) => (
            <ResultCard
              key={`${result.record_type}:${result.record_id}`}
              result={result}
              highlightTerms={highlightTerms}
            />
          ))}

          {pageCount > 1 && (
            <div className="flex items-center justify-center gap-2 pt-1">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary disabled:pointer-events-none disabled:opacity-40"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
                {t('retrieval.prev', { defaultValue: 'Previous' })}
              </button>
              <span className="text-xs tabular-nums text-content-tertiary">
                {t('retrieval.page_of', {
                  defaultValue: 'Page {{page}} of {{pages}}',
                  page,
                  pages: pageCount,
                })}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                disabled={page >= pageCount}
                className="inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary disabled:pointer-events-none disabled:opacity-40"
              >
                {t('retrieval.next', { defaultValue: 'Next' })}
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default RetrievalPage;
