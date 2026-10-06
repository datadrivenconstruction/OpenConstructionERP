// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The screen for a module that was built on this instance.
 *
 * The frontend is a compiled bundle. A module installed at runtime cannot ship
 * a screen of its own, so it ships a description of one - the specification it
 * serves at `{base_path}/ui-spec` - and this page renders the list, the detail
 * and the form from it. One component serves every module ever built here.
 *
 * Where `base_path` comes from is the part worth being careful about. The
 * loader mounts a module at the hyphenated form of its key, and that rule lives
 * in the loader. Rebuilding it here from the route parameter would be a second
 * copy of it, so the page looks the module up in the installed list the server
 * returns and uses the `base_path` it was given. The route carries the key,
 * which is stable and readable; the URL the key resolves to is the server's
 * business.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlarmClock,
  ArrowDown,
  ArrowUp,
  Boxes,
  ChevronsUpDown,
  Download,
  FolderOpen,
  Loader2,
  Pencil,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import clsx from 'clsx';

import {
  Button,
  CollapsibleSection,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonTable,
} from '@/shared/ui';
import { ChipBar } from '@/shared/ui/ChipBar';
import { downloadWithAuth, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import {
  RUNTIME_MODULE_QUERY_KEY,
  deleteModuleRecord,
  fetchInstalledModules,
  fetchModuleRecords,
  fetchModuleUiSpec,
  isQuarantined,
  moduleExportUrl,
  type GeneratedRecord,
  type LinkTarget,
  type ModuleFieldSpec,
} from './api';
import {
  STATUS_KEY,
  compareByField,
  dueState,
  formatValue,
  isDoneStatus,
  listColumns,
  statusStates,
} from './fields';
import { useLinkLabelsByTarget } from './LinkPicker';
import { RecordFormModal } from './RecordFormModal';
import { StatusBadge } from './StatusBadge';
import { ExtendModuleButton } from './ExtendModuleButton';
import { QuarantineBadge, QuarantineMessage } from './QuarantineNotice';

/** The chip that clears the status filter. Not a stage code: those are snake_case. */
const ALL_STATUSES = '__all__';

// Kept where the wizard can reach it without loading this page.
export { RUNTIME_MODULE_QUERY_KEY };

/**
 * Rows per request. The generated router caps `limit` at 500 and defaults to
 * 100; this asks for a size that fills a screen many times over while leaving
 * the cap room, and pages past it by offset rather than by asking for more.
 */
const PAGE_SIZE = 200;

export function GeneratedModulePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { moduleKey, projectId: routeProjectId } = useParams<{
    moduleKey?: string;
    projectId?: string;
  }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<GeneratedRecord | null>(null);
  const [pendingDelete, setPendingDelete] = useState<GeneratedRecord | null>(null);

  const installedQuery = useQuery({
    queryKey: ['module-builder', 'installed'],
    queryFn: fetchInstalledModules,
    staleTime: 5 * 60_000,
  });
  const installed = installedQuery.data?.items.find((m) => m.key === moduleKey);
  // A module switched off for safety answers nothing at its address, so its
  // spec and records are not asked for at all.
  const quarantined = isQuarantined(installed);
  const basePath = quarantined ? '' : (installed?.base_path ?? '');

  const specQuery = useQuery({
    queryKey: [RUNTIME_MODULE_QUERY_KEY, 'ui-spec', basePath],
    queryFn: () => fetchModuleUiSpec(basePath),
    enabled: basePath !== '',
    // The spec only changes when the module is reinstalled, and the install
    // invalidates this key itself.
    staleTime: 30 * 60_000,
  });
  const spec = specQuery.data;

  const scoped = spec?.entity.project_scoped ?? false;
  const missingProject = scoped && !projectId;

  // Paged rather than a single capped read. The previous version asked for 200
  // rows and rendered them; a register holding more showed the first 200 and
  // said nothing at all, which is the one failure a list must not have, because
  // nothing on screen distinguishes "these are all of them" from "these are the
  // ones that fit".
  const recordsQuery = useInfiniteQuery({
    queryKey: [RUNTIME_MODULE_QUERY_KEY, 'records', basePath, scoped ? projectId : null],
    queryFn: ({ pageParam }) =>
      fetchModuleRecords(basePath, {
        projectId: scoped ? projectId : null,
        limit: PAGE_SIZE,
        offset: pageParam,
      }),
    enabled: basePath !== '' && spec !== undefined && !missingProject,
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, p) => sum + p.items.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });

  const columns = useMemo(() => (spec ? listColumns(spec) : []), [spec]);

  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ name: string; dir: 'asc' | 'desc' } | null>(null);

  const loaded = useMemo(
    () => recordsQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [recordsQuery.data],
  );
  const total = recordsQuery.data?.pages[0]?.total ?? 0;
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = recordsQuery;

  const states = useMemo(() => (spec ? statusStates(spec) : []), [spec]);
  const due = spec?.features?.due ?? null;
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  // One labels request per target for everything loaded, rather than one per
  // cell: a register of 200 rows linking to contracts asks once.
  const linkRequests = useMemo(
    () =>
      columns
        .filter((c) => c.type === 'link' && c.target)
        .map((c) => ({
          target: c.target as LinkTarget,
          ids: loaded
            .map((r) => r[c.name])
            .filter((v): v is string => typeof v === 'string' && v !== ''),
        })),
    [columns, loaded],
  );
  const { labels: linkLabels, loaded: linkLoaded } = useLinkLabelsByTarget(linkRequests);

  // A search or a stage filter over a partly loaded register answers "nothing
  // found" about rows it never looked at, which is a wrong answer rather than
  // a partial one. So either one pulls the rest in first. Each fetch settles,
  // this runs again, and it stops when there is no next page.
  const searching = query.trim() !== '' || statusFilter.length > 0;
  useEffect(() => {
    if (searching && hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [searching, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Sorting is offered only once every row is here, for the same reason. The
  // generated router orders by created_at and takes no sort parameter, so a
  // sort is client-side by construction; over a partial set it would put a
  // plausible row at the top that is simply not the largest, and unlike an
  // empty search result nothing about the screen would look wrong.
  const canSort = !hasNextPage && !recordsQuery.isFetching;

  // Memoised because the filter below depends on it: rebuilt inline it would be
  // a new object on every render and the filter would re-run over every loaded
  // row each time. Stable rather than guaranteed constant - `t` takes a new
  // identity when a locale finishes loading, and the filter re-runs then. That
  // is the one moment it should, because the strings it matches against have
  // just changed.
  const labels = useMemo(
    () => ({
      yes: t('common.yes', { defaultValue: 'Yes' }),
      no: t('common.no', { defaultValue: 'No' }),
      empty: '—',
    }),
    [t],
  );

  /**
   * A cell as the reader sees it. A link shows the name of what it points at;
   * one the reader may not see says so instead of showing an id.
   */
  const cellText = useCallback(
    (column: ModuleFieldSpec, record: GeneratedRecord): string => {
      if (column.type === 'link' && column.target) {
        const id = record[column.name];
        if (typeof id !== 'string' || id === '') return labels.empty;
        const name = linkLabels[column.target]?.[id];
        if (name) return name;
        return linkLoaded[column.target]
          ? t('runtime_module.link_hidden', { defaultValue: 'Not visible to you' })
          : '…';
      }
      return formatValue(column, record[column.name], labels);
    },
    [labels, linkLabels, linkLoaded, t],
  );

  const statusCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const record of loaded) {
      const code = record[STATUS_KEY];
      if (typeof code === 'string') counts.set(code, (counts.get(code) ?? 0) + 1);
    }
    return counts;
  }, [loaded]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let rows = loaded;
    if (statusFilter.length > 0) {
      rows = rows.filter((record) => statusFilter.includes(String(record[STATUS_KEY] ?? '')));
    }
    if (needle) {
      // Matched against the text the user can actually see, so a search for
      // "1 234,50" finds the row that renders that, not only the row whose
      // stored value happens to be spelled the same way.
      rows = rows.filter(
        (record) =>
          columns.some((column) => cellText(column, record).toLowerCase().includes(needle)) ||
          (states.find((s) => s.code === record[STATUS_KEY])?.label.toLowerCase().includes(needle) ?? false),
      );
    }
    if (sort) {
      const column = columns.find((c) => c.name === sort.name);
      if (column) {
        const factor = sort.dir === 'asc' ? 1 : -1;
        const blank = (v: unknown) => v === null || v === undefined || v === '';
        rows = [...rows].sort((a, b) => {
          const av = a[column.name];
          const bv = b[column.name];
          // Blanks are held out of the flip on purpose. Multiplying the whole
          // comparison by -1 would send every empty cell to the top the moment
          // the user sorts descending, burying the rows they asked to see
          // behind the rows that have nothing to show.
          const aBlank = blank(av);
          const bBlank = blank(bv);
          if (aBlank && bBlank) return 0;
          if (aBlank) return 1;
          if (bBlank) return -1;
          // A link sorts by the name on screen; its id is meaningless order.
          if (column.type === 'link') {
            return cellText(column, a).localeCompare(cellText(column, b)) * factor;
          }
          return compareByField(column, av, bv) * factor;
        });
      }
    }
    return rows;
  }, [loaded, query, sort, columns, statusFilter, states, cellText]);

  const runExport = async (format: 'csv' | 'xlsx') => {
    if (!spec) return;
    setExportOpen(false);
    setExporting(true);
    try {
      await downloadWithAuth(
        moduleExportUrl(basePath, format, scoped ? projectId : null),
        `${spec.key}.${format}`,
      );
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setExporting(false);
    }
  };

  const removal = useMutation({
    mutationFn: (record: GeneratedRecord) => deleteModuleRecord(basePath, record.id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('runtime_module.deleted', { defaultValue: 'Deleted' }) });
      void qc.invalidateQueries({ queryKey: [RUNTIME_MODULE_QUERY_KEY, 'records', basePath] });
      setPendingDelete(null);
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
      setPendingDelete(null);
    },
  });

  if (installedQuery.isLoading) {
    return <SkeletonTable rows={6} columns={5} />;
  }

  if (installedQuery.isError) {
    return (
      <ErrorState
        title={t('runtime_module.load_failed', { defaultValue: 'This module could not be loaded' })}
        hint={getErrorMessage(installedQuery.error)}
        onRetry={() => void installedQuery.refetch()}
      />
    );
  }

  if (!installed) {
    return (
      <EmptyState
        icon={<Boxes size={28} strokeWidth={1.5} />}
        title={t('runtime_module.not_installed', { defaultValue: 'No such module on this instance' })}
        description={t('runtime_module.not_installed_hint', {
          defaultValue:
            'It may have been removed. The modules built here are listed on the module builder page.',
        })}
        action={
          <Link
            to="/module-builder"
            className="text-sm font-medium text-oe-blue-text hover:text-oe-blue-hover"
          >
            {t('module_builder.title', { defaultValue: 'Module builder' })}
          </Link>
        }
      />
    );
  }

  if (quarantined) {
    return (
      <div className="mx-auto max-w-xl space-y-3 py-10" data-testid="runtime-module-quarantined">
        <p className="flex flex-wrap items-center gap-2 text-lg font-semibold text-content-primary">
          {installed.display_name}
          <QuarantineBadge />
        </p>
        <QuarantineMessage problem={installed.problem} />
        <Link to="/module-builder" className="inline-block text-sm font-medium text-oe-blue-text hover:text-oe-blue-hover">
          {t('module_builder.title', { defaultValue: 'Module builder' })}
        </Link>
      </div>
    );
  }

  if (specQuery.isError) {
    return (
      <ErrorState
        title={t('runtime_module.no_spec', { defaultValue: 'This module did not describe its screen' })}
        hint={getErrorMessage(specQuery.error)}
        onRetry={() => void specQuery.refetch()}
      />
    );
  }

  if (!spec) {
    return <SkeletonTable rows={6} columns={5} />;
  }

  return (
    <div className="space-y-4" data-testid="runtime-module-page">
      <PageHeader
        srTitle={spec.display_name}
        subtitle={spec.description || undefined}
        actions={
          <div className="flex items-center gap-2">
            {moduleKey && basePath && <ExtendModuleButton moduleKey={moduleKey} basePath={basePath} />}
            {spec.features?.export && (
              <div className="relative">
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Download size={14} />}
                  loading={exporting}
                  disabled={missingProject}
                  onClick={() => setExportOpen((v) => !v)}
                  aria-haspopup="menu"
                  aria-expanded={exportOpen}
                  data-testid="runtime-module-export"
                >
                  {t('runtime_module.export', { defaultValue: 'Export' })}
                </Button>
                {exportOpen && (
                  <div
                    role="menu"
                    className="absolute end-0 z-30 mt-1 min-w-[10rem] rounded-lg border border-border-light bg-surface-primary py-1 shadow-lg"
                  >
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => void runExport('xlsx')}
                      className="block w-full px-3 py-1.5 text-start text-sm text-content-primary hover:bg-surface-secondary"
                      data-testid="runtime-module-export-xlsx"
                    >
                      {t('runtime_module.export_xlsx', { defaultValue: 'Excel workbook' })}
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => void runExport('csv')}
                      className="block w-full px-3 py-1.5 text-start text-sm text-content-primary hover:bg-surface-secondary"
                      data-testid="runtime-module-export-csv"
                    >
                      {t('runtime_module.export_csv', { defaultValue: 'CSV file' })}
                    </button>
                  </div>
                )}
              </div>
            )}
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              disabled={missingProject}
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
              data-testid="runtime-module-new"
            >
              {t('runtime_module.new_record', {
                entity: spec.entity.display_name,
                defaultValue: 'New {{entity}}',
              })}
            </Button>
          </div>
        }
      />

      {/* What this module is and what it checks. The rules are the module's own
          promise about its data, so they belong on the screen rather than only
          in whatever the author typed into the wizard. */}
      <CollapsibleSection
        storageKey={`runtime_module.${spec.key}.how`}
        title={spec.display_name}
        icon={<Boxes size={15} strokeWidth={1.9} />}
        subtitle={t('runtime_module.built_here', {
          defaultValue: 'Built on this instance from a description of it.',
        })}
      >
        <div className="space-y-3 text-sm text-content-secondary">
          {spec.description && <p>{spec.description}</p>}
          <div>
            <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              <ShieldCheck size={13} strokeWidth={2} />
              {t('runtime_module.rules_heading', { defaultValue: 'What this module checks' })}
            </p>
            {spec.rules.length > 0 ? (
              <ul className="space-y-1">
                {spec.rules.map((rule) => (
                  <li key={rule.code} className="text-xs text-content-tertiary">
                    {/* The author's own wording, shown as written. */}
                    {rule.message}
                  </li>
                ))}
              </ul>
            ) : (
              // A module can be built with no rules. Leaving the heading over
              // an empty list reads as a module whose checks failed to load
              // rather than one that was described without any.
              <p className="text-xs text-content-quaternary">
                {t('runtime_module.no_rules', {
                  defaultValue: 'This module was described without any checks.',
                })}
              </p>
            )}
          </div>
        </div>
      </CollapsibleSection>

      {missingProject ? (
        <EmptyState
          icon={<FolderOpen size={28} strokeWidth={1.5} />}
          title={t('requiresProject.title', { defaultValue: 'No project selected' })}
          description={t('runtime_module.needs_project', {
            defaultValue: 'These records belong to a project. Choose one before saving.',
          })}
        />
      ) : recordsQuery.isLoading ? (
        <SkeletonTable rows={6} columns={Math.max(columns.length, 3)} />
      ) : recordsQuery.isError ? (
        <ErrorState
          title={t('runtime_module.records_failed', { defaultValue: 'The records could not be read' })}
          hint={getErrorMessage(recordsQuery.error)}
          onRetry={() => void recordsQuery.refetch()}
        />
      ) : loaded.length === 0 ? (
        <EmptyState
          icon={<Boxes size={28} strokeWidth={1.5} />}
          title={t('runtime_module.empty_title', {
            entity: spec.entity.plural_name,
            defaultValue: 'No {{entity}} yet',
          })}
          description={t('runtime_module.empty_hint', {
            defaultValue: 'Nothing has been recorded here yet.',
          })}
          action={{
            label: t('runtime_module.new_record', {
              entity: spec.entity.display_name,
              defaultValue: 'New {{entity}}',
            }),
            onClick: () => {
              setEditing(null);
              setFormOpen(true);
            },
          }}
        />
      ) : (
        <div className="space-y-2">
          {/* Search and the honest count sit together above the table: the
              count is what qualifies the search's answer. */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-0 flex-1 basis-56">
              <Search
                size={14}
                aria-hidden
                className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-content-quaternary"
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('common.search', { defaultValue: 'Search' })}
                aria-label={t('common.search', { defaultValue: 'Search' })}
                data-testid="runtime-module-search"
                className="w-full rounded-lg border border-border-light bg-surface-primary py-1.5 ps-8 pe-8 text-sm text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              />
              {query !== '' && (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  aria-label={t('common.clear', { defaultValue: 'Clear' })}
                  className="absolute end-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-content-tertiary hover:text-content-primary"
                >
                  <X size={13} />
                </button>
              )}
            </div>

            {/* Shown always, not only when truncated. A count that appears only
                on overflow is a count nobody learns to trust. */}
            <span
              className="shrink-0 text-xs tabular-nums text-content-tertiary"
              data-testid="runtime-module-count"
            >
              {t('runtime_module.showing_of', {
                shown: visible.length,
                total,
                defaultValue: 'Showing {{shown}} of {{total}}',
              })}
            </span>

            {hasNextPage && (
              <button
                type="button"
                onClick={() => void fetchNextPage()}
                disabled={isFetchingNextPage}
                data-testid="runtime-module-more"
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary disabled:opacity-60"
              >
                {isFetchingNextPage && <Loader2 size={12} className="animate-spin" />}
                {t('common.show_more', { defaultValue: 'Show more' })}
              </button>
            )}
          </div>

          {states.length > 0 && (
            <div data-testid="runtime-module-status-filter">
              <ChipBar<string>
                size="sm"
                chips={[
                  { value: ALL_STATUSES, label: t('runtime_module.all_statuses', { defaultValue: 'All' }) },
                  ...states.map((state) => ({
                    value: state.code,
                    // The author's own stage name. The count is only shown
                    // once every row is here, since a count over part of the
                    // register would be a wrong number, not a partial one.
                    label: state.label,
                    count: hasNextPage ? undefined : (statusCounts.get(state.code) ?? 0),
                  })),
                ]}
                selected={statusFilter.length > 0 ? statusFilter : [ALL_STATUSES]}
                onToggle={(code) => {
                  if (code === ALL_STATUSES) {
                    setStatusFilter([]);
                    return;
                  }
                  setStatusFilter((prev) =>
                    prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
                  );
                }}
              />
            </div>
          )}

          <div className="overflow-x-auto rounded-xl border border-border-light bg-surface-primary">
          <table className="w-full text-sm" data-testid="runtime-module-table">
            <thead>
              <tr className="border-b border-border-light text-left text-xs uppercase tracking-wide text-content-tertiary">
                {columns.map((column) => {
                  const active = sort?.name === column.name;
                  // The author's label. Not translated: it is their data.
                  const head = (
                    <>
                      {column.label}
                      {column.unit && <span className="ml-1 normal-case">({column.unit})</span>}
                    </>
                  );
                  return (
                    <th
                      key={column.name}
                      scope="col"
                      className="px-3 py-2 font-medium"
                      aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                    >
                      {canSort ? (
                        <button
                          type="button"
                          onClick={() =>
                            setSort((prev) =>
                              prev?.name === column.name
                                ? { name: column.name, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
                                : { name: column.name, dir: 'asc' },
                            )
                          }
                          data-testid={`runtime-module-sort-${column.name}`}
                          className="group inline-flex items-center gap-1 rounded uppercase tracking-wide hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                        >
                          {head}
                          {active ? (
                            sort.dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                          ) : (
                            <ChevronsUpDown
                              size={12}
                              className="opacity-0 transition-opacity group-hover:opacity-60"
                            />
                          )}
                        </button>
                      ) : (
                        // Not a button while rows are still arriving. A sort
                        // over part of the set puts a plausible row on top that
                        // is not the largest, and nothing on screen would say
                        // so. Show more first, then sort.
                        head
                      )}
                    </th>
                  );
                })}
                {states.length > 0 && (
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t('runtime_module.status', { defaultValue: 'Status' })}
                  </th>
                )}
                <th scope="col" className="w-20 px-3 py-2 text-right font-medium">
                  {t('common.actions', { defaultValue: 'Actions' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((record) => (
                <tr
                  key={record.id}
                  className="border-b border-border-light/60 last:border-0 hover:bg-surface-secondary/60"
                >
                  {columns.map((column) => {
                    const text = cellText(column, record);
                    const deadline =
                      due && due.field === column.name
                        ? dueState(
                            column,
                            record[column.name],
                            due.remind_days_before,
                            isDoneStatus(spec, record[STATUS_KEY]),
                          )
                        : null;
                    return (
                      <td
                        key={column.name}
                        className={clsx(
                          'px-3 py-2',
                          deadline === 'overdue'
                            ? 'font-medium text-semantic-error'
                            : deadline === 'soon'
                              ? 'font-medium text-semantic-warning'
                              : 'text-content-primary',
                        )}
                        data-due={deadline ?? undefined}
                      >
                        <span className="inline-flex items-center gap-1.5">
                          {deadline && <AlarmClock size={13} aria-hidden className="shrink-0" />}
                          {text}
                          {deadline && (
                            <span className="sr-only">
                              {deadline === 'overdue'
                                ? t('runtime_module.overdue', { defaultValue: 'Overdue' })
                                : t('runtime_module.due_soon', { defaultValue: 'Due soon' })}
                            </span>
                          )}
                        </span>
                      </td>
                    );
                  })}
                  {states.length > 0 && (
                    <td className="px-3 py-2">
                      <StatusBadge spec={spec} code={record[STATUS_KEY]} />
                    </td>
                  )}
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(record);
                          setFormOpen(true);
                        }}
                        aria-label={t('common.edit', { defaultValue: 'Edit' })}
                        className="rounded-md p-1.5 text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setPendingDelete(record)}
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        className="rounded-md p-1.5 text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {visible.length === 0 && (
            // Only reachable with a search running, since an empty register
            // took the EmptyState branch above. The message is deliberately
            // not shown while pages are still arriving: at that point "no
            // results" would be a claim about rows this screen has not read.
            <p className="px-3 py-6 text-center text-sm text-content-tertiary" data-testid="runtime-module-no-results">
              {searching && hasNextPage
                ? t('common.loading', { defaultValue: 'Loading...' })
                : t('common.no_results', { defaultValue: 'No results found' })}
            </p>
          )}
          </div>
        </div>
      )}

      <RecordFormModal
        open={formOpen}
        spec={spec}
        basePath={basePath}
        projectId={scoped ? projectId || null : null}
        record={editing}
        onClose={() => setFormOpen(false)}
        onSaved={() => {
          setFormOpen(false);
          void qc.invalidateQueries({ queryKey: [RUNTIME_MODULE_QUERY_KEY, 'records', basePath] });
        }}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('runtime_module.confirm_delete_title', {
          entity: spec.entity.display_name,
          defaultValue: 'Delete this {{entity}}?',
        })}
        message={t('runtime_module.confirm_delete_message', {
          defaultValue: 'The record is removed for everyone. This cannot be undone.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        loading={removal.isPending}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) removal.mutate(pendingDelete);
        }}
      />
    </div>
  );
}

export default GeneratedModulePage;
