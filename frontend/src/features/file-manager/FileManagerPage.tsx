/** Project File Manager — Issue #109.
 *
 * Unified file & folder hub. The default view (no category selected) is
 * a folder-card grid; clicking a folder drills into the existing
 * grid/list view with the rest of the UI (path bar, search, sort,
 * preview pane) intact.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueries } from '@tanstack/react-query';
import { ArrowLeft, ChevronRight, HardDrive, UploadCloud, Search, Send } from 'lucide-react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { EmptyState, ModuleGuideButton } from '@/shared/ui';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { filesGuide } from './filesGuide';
import { fetchTagsForFile } from '@/features/file-tags/api';
import { fileTagsKeys } from '@/features/file-tags/hooks';
import type { TagRecord } from '@/features/file-tags/types';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  useFavorites,
  useFileList,
  useFileTree,
  useFolderPermissionCounts,
  useIsProjectOwner,
  useProjectsLite,
  useStorageLocations,
  useToggleFavorite,
} from './hooks';
import { PathBar } from './components/PathBar';
import { FileTree } from './components/FileTree';
import { FileGrid } from './components/FileGrid';
import { FileList } from './components/FileList';
import { FilePreviewPane } from './components/FilePreviewPane';
import { FileActionsBar, type ViewMode } from './components/FileActionsBar';
import { ExportWizard } from './components/ExportWizard';
import { ImportWizard } from './components/ImportWizard';
import { EmailDialog } from './components/EmailDialog';
import { ShareLinkModal } from './components/ShareLinkModal';
import { FolderPermissionsModal } from './components/FolderPermissionsModal';
import { FolderCardGrid } from './components/FolderCardGrid';
import { UploadDialog } from './components/UploadDialog';
import { BulkActionsBar } from './components/BulkActionsBar';
import { InitialLoadProgress } from './components/InitialLoadProgress';
import { FilesStatsStrip } from './components/FilesStatsStrip';
import {
  RecentlyViewedStrip,
  recordRecentlyViewed,
  type RecentItem,
} from './components/RecentlyViewedStrip';
import { ShortcutsCheatsheet } from './components/ShortcutsCheatsheet';
import { useFileShortcuts } from './useFileShortcuts';
import { primaryModule } from './kindModule';
import type { FileFilters, FileKind, FileRow } from './types';

const VIEW_MODE_KEY = 'file-manager:view-mode';

function readViewMode(): ViewMode {
  try {
    const stored = localStorage.getItem(VIEW_MODE_KEY);
    if (stored === 'grid' || stored === 'list') return stored;
  } catch {
    /* localStorage unavailable */
  }
  return 'grid';
}

function writeViewMode(view: ViewMode) {
  try {
    localStorage.setItem(VIEW_MODE_KEY, view);
  } catch {
    /* localStorage unavailable */
  }
}

const VALID_KINDS: ReadonlySet<string> = new Set([
  'document',
  'photo',
  'sheet',
  'bim_model',
  'dwg_drawing',
  'takeoff',
  'report',
  'markup',
]);

export function FileManagerPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const ctxProjectId = useProjectContextStore((s) => s.activeProjectId);
  const ctxProjectName = useProjectContextStore((s) => s.activeProjectName);

  const projectId = routeProjectId ?? ctxProjectId;

  // Selected category drives both the URL (?kind=) and the view —
  // landing on /files renders the folder grid; /files?kind=document
  // jumps straight to that category's grid view. Strip any legacy
  // "category:" prefix that older bookmarks may carry.
  const rawKind = searchParams.get('kind');
  const queryKind = rawKind ? rawKind.replace(/^category:/, '') : null;
  const initialKind: FileKind | null =
    queryKind && VALID_KINDS.has(queryKind) ? (queryKind as FileKind) : null;

  // Saved-view filter hydration — when SavedViewsRail applies a view
  // it serialises ``q``/``sort``/``extension``/``tag_ids`` into the
  // URL and navigates here. We pick those up on mount so the file
  // list opens with the saved filter pre-applied instead of an empty
  // toolbar.
  const initialQuery = searchParams.get('q') ?? '';
  const initialSortParam = searchParams.get('sort');
  const initialSort: NonNullable<FileFilters['sort']> =
    initialSortParam === 'name' ||
    initialSortParam === 'size' ||
    initialSortParam === 'kind' ||
    initialSortParam === 'modified'
      ? initialSortParam
      : 'modified';
  const initialExtension = searchParams.get('extension') ?? undefined;
  const initialTagIds = (searchParams.get('tag_ids') ?? '')
    .split(',')
    .map((id) => id.trim())
    .filter((id) => id.length > 0);

  const [selectedKind, setSelectedKind] = useState<FileKind | null>(initialKind);
  const [query, setQuery] = useState(initialQuery);
  const [sort, setSort] = useState<NonNullable<FileFilters['sort']>>(initialSort);
  const [view, setView] = useState<ViewMode>(() => readViewMode());
  const [extension, setExtension] = useState<string | undefined>(initialExtension);
  // W4 — tag filter facet state. Multi-select tag ids that filter the
  // file list client-side (until the backend ``?tag_ids=`` param is
  // wired). SavedViewsRail can hydrate this via ``?tag_ids=...``.
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>(initialTagIds);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false);
  const [previewRow, setPreviewRow] = useState<FileRow | null>(null);
  const [showExport, setShowExport] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [emailRow, setEmailRow] = useState<FileRow | null>(null);
  const [shareRow, setShareRow] = useState<FileRow | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadKind, setUploadKind] = useState<FileKind | null>(null);
  const [permsKind, setPermsKind] = useState<FileKind | null>(null);
  const [showCheatsheet, setShowCheatsheet] = useState(false);

  // Folder-permissions surface — gear + lock badge.
  const isOwner = useIsProjectOwner(projectId);
  const permissionCounts = useFolderPermissionCounts(projectId, isOwner);
  // Resolve a file's project name when opening into a context-store
  // destination (Clash / BI Explorer) — keeps the global project label
  // correct even from the cross-project global /files view.
  const { data: projectsLite = [] } = useProjectsLite();

  useEffect(() => {
    writeViewMode(view);
  }, [view]);

  // ── URL → state hydration ────────────────────────────────────────────
  // The state→URL writer below also runs whenever ``searchParams`` change.
  // Without this effect, an external navigation (SavedViewsRail clicking a
  // view → ``navigate('/files?kind=...&q=...&sort=...')``) would race that
  // writer: the writer reads the old state, rebuilds the URL from it, and
  // overwrites the freshly-applied saved-view params. We pull values FROM
  // the URL into state when they differ, so the writer's diff guard short-
  // circuits on the next render and the round-trip stays loss-less.
  //
  // ``hydratingFromUrlRef`` flips true while we're applying URL → state, so
  // any cascaded state change does not bounce back into the writer mid-
  // hydration and clobber the URL we just read.
  const hydratingFromUrlRef = useRef(false);
  useEffect(() => {
    const urlKindRaw = searchParams.get('kind');
    const urlKindClean = urlKindRaw ? urlKindRaw.replace(/^category:/, '') : null;
    const urlKind: FileKind | null =
      urlKindClean && VALID_KINDS.has(urlKindClean) ? (urlKindClean as FileKind) : null;
    const urlQuery = searchParams.get('q') ?? '';
    const urlSortParam = searchParams.get('sort');
    const urlSort: NonNullable<FileFilters['sort']> =
      urlSortParam === 'name' ||
      urlSortParam === 'size' ||
      urlSortParam === 'kind' ||
      urlSortParam === 'modified'
        ? urlSortParam
        : 'modified';
    const urlExtension = searchParams.get('extension') ?? undefined;
    const urlTagIdsRaw = searchParams.get('tag_ids') ?? '';
    const urlTagIds = urlTagIdsRaw
      .split(',')
      .map((id) => id.trim())
      .filter((id) => id.length > 0);

    let changed = false;
    if (urlKind !== selectedKind) {
      changed = true;
    } else if (urlQuery !== query) {
      changed = true;
    } else if (urlSort !== sort) {
      changed = true;
    } else if (urlExtension !== extension) {
      changed = true;
    } else if (
      urlTagIds.length !== selectedTagIds.length ||
      urlTagIds.some((id, i) => id !== selectedTagIds[i])
    ) {
      changed = true;
    }
    if (!changed) return;

    hydratingFromUrlRef.current = true;
    setSelectedKind(urlKind);
    setQuery(urlQuery);
    setSort(urlSort);
    setExtension(urlExtension);
    setSelectedTagIds(urlTagIds);
    // The writer effect runs after these setters batch-commit; release the
    // flag on the next microtask so it observes ``hydratingFromUrlRef`` as
    // true and skips the redundant write.
    queueMicrotask(() => {
      hydratingFromUrlRef.current = false;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Keep the URL ?kind=, ?q=, ?sort=, ?extension=, ?tag_ids= params in
  // sync with the active filter state so deep-links work both ways:
  // pasted URL → loads the right filter; UI back-button → returns to
  // the folder-grid view. SavedViewsRail re-uses these keys when it
  // applies a view, so the round trip stays loss-less.
  useEffect(() => {
    if (hydratingFromUrlRef.current) return;
    const next = new URLSearchParams(searchParams);
    if (selectedKind) next.set('kind', selectedKind);
    else next.delete('kind');
    if (query.trim()) next.set('q', query.trim());
    else next.delete('q');
    if (sort && sort !== 'modified') next.set('sort', sort);
    else next.delete('sort');
    if (extension) next.set('extension', extension);
    else next.delete('extension');
    if (selectedTagIds.length > 0) next.set('tag_ids', selectedTagIds.join(','));
    else next.delete('tag_ids');
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [
    selectedKind,
    query,
    sort,
    extension,
    selectedTagIds,
    searchParams,
    setSearchParams,
  ]);

  const filters = useMemo<FileFilters>(
    () => ({
      sort,
      ...(selectedKind ? { category: selectedKind } : {}),
      ...(query.trim() ? { q: query.trim() } : {}),
      ...(extension ? { extension } : {}),
    }),
    [sort, selectedKind, query, extension],
  );

  // Tree counts mirror the same q/extension filters as the list so the
  // sidebar can't show "Documents 9" while a free-text query is hiding
  // every row in the right pane.
  const treeFilters = useMemo(
    () => ({
      ...(query.trim() ? { q: query.trim() } : {}),
      ...(extension ? { extension } : {}),
    }),
    [query, extension],
  );
  const { data: tree, isLoading: treeLoading } = useFileTree(projectId, treeFilters);
  const { data: locations, isLoading: locLoading } = useStorageLocations(projectId);
  // The list query is only needed when a category is selected; the
  // folder-grid view reads counts straight off the tree and skips the
  // (potentially very large) full-file list response entirely.
  const { data: list, isLoading: listLoading } = useFileList(
    selectedKind ? projectId : null,
    filters,
  );

  // Per-user favourites — drives the star toggle + the "Favourites only"
  // filter chip. The hook returns an O(1) membership set keyed by
  // ``kind:id`` so a large grid doesn't scan the row list per tile.
  const favorites = useFavorites(projectId);
  const toggleFavorite = useToggleFavorite(projectId);
  const addToast = useToastStore((s) => s.addToast);
  const handleToggleFavorite = (row: FileRow, isFavorite: boolean) => {
    toggleFavorite.mutate(
      { kind: row.kind, fileId: row.id, isFavorite },
      {
        onError: (err: unknown) =>
          addToast({
            type: 'error',
            title: t('common.error', { defaultValue: 'Error' }),
            message: err instanceof Error ? err.message : String(err),
          }),
      },
    );
  };

  // W4 — when a tag filter is active, fetch the tags assigned to each
  // visible file and drop rows that don't carry ALL selected tags.
  // ``useQueries`` fans out one request per visible item; the shared
  // React Query cache (same key the per-row TagPill renderer uses) keeps
  // repeated visits warm and never re-issues an in-flight request.
  // Until the backend learns a ``?tag_ids=`` filter this is the
  // smallest change that gives the toolbar real teeth.
  const visibleItems = list?.items ?? [];
  const tagFilterActive = selectedTagIds.length > 0 && Boolean(projectId);
  const tagQueries = useQueries({
    queries: tagFilterActive
      ? visibleItems.map((row) => ({
          queryKey: [fileTagsKeys.byFile, projectId, row.kind, row.id],
          queryFn: () =>
            fetchTagsForFile(projectId as string, row.kind, row.id),
          staleTime: 30_000,
        }))
      : [],
  });
  // Build the row-id → tag-id set lookup. When tag fetches are still
  // pending for a row we leave it visible (optimistic; gets re-filtered
  // once the cache settles) so the page never blanks during the
  // initial fetch.
  const tagFilteredItems = useMemo(() => {
    if (!tagFilterActive) return visibleItems;
    return visibleItems.filter((_row, idx) => {
      const q = tagQueries[idx];
      const tags = (q?.data as TagRecord[] | undefined) ?? [];
      if (q?.isLoading || q?.isFetching) return true;
      const tagIds = new Set(tags.map((t) => t.id));
      return selectedTagIds.every((id) => tagIds.has(id));
    });
  }, [tagFilterActive, visibleItems, tagQueries, selectedTagIds]);

  // Final filter pass — when "Favourites only" is on, keep just the rows
  // the current user has starred (membership keyed by ``kind:id``).
  const displayItems = useMemo(() => {
    if (!showFavoritesOnly) return tagFilteredItems;
    return tagFilteredItems.filter((row) =>
      favorites.keys.has(`${row.kind}:${row.id}`),
    );
  }, [showFavoritesOnly, tagFilteredItems, favorites.keys]);

  // Whenever filters change, drop selection that no longer matches the
  // visible result set so the preview pane never shows a stale row.
  useEffect(() => {
    if (!list) return;
    const visibleIds = new Set(list.items.map((r) => r.id));
    setSelectedIds((prev) => {
      const next = new Set([...prev].filter((id) => visibleIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
    if (previewRow && !visibleIds.has(previewRow.id)) {
      setPreviewRow(null);
    }
  }, [list, previewRow]);

  // Deep-link: `?file={id}` pre-selects that file in the preview pane.
  // Used by the "Open in File Manager" secondary action so users land
  // directly on the focused file rather than just the category grid.
  const fileIdParam = searchParams.get('file');
  useEffect(() => {
    if (!fileIdParam || !list) return;
    const target = list.items.find((r) => r.id === fileIdParam);
    if (target) {
      setPreviewRow(target);
      setSelectedIds(new Set([fileIdParam]));
    }
  }, [fileIdParam, list]);

  /* Anchor for shift-click range selection — the last single-clicked id.
     Shift+click expands the visible range from anchor to target; plain click
     resets the anchor. We keep this in a ref so it does not trigger renders. */
  const lastClickedRef = useRef<string | null>(null);

  function handleSelect(id: string, additive: boolean, shift = false) {
    const items = tagFilteredItems;
    if (shift && lastClickedRef.current) {
      const anchor = lastClickedRef.current;
      const a = items.findIndex((r) => r.id === anchor);
      const b = items.findIndex((r) => r.id === id);
      if (a >= 0 && b >= 0) {
        const [lo, hi] = a < b ? [a, b] : [b, a];
        const range = items.slice(lo, hi + 1).map((r) => r.id);
        setSelectedIds((prev) => {
          const next = new Set(additive ? prev : []);
          for (const rid of range) next.add(rid);
          return next;
        });
        const row = list?.items.find((r) => r.id === id);
        if (row) setPreviewRow(row);
        return;
      }
    }

    setSelectedIds((prev) => {
      const next = new Set(additive ? prev : []);
      if (prev.has(id) && additive) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
    lastClickedRef.current = id;
    const row = list?.items.find((r) => r.id === id);
    if (row) setPreviewRow(row);
  }

  function handleOpen(row: FileRow) {
    // Opening a file means "take me to the tool that processes it" —
    // PDFs jump to PDF Takeoff, IFC/RVT to BIM 3D Viewer, DWG to DWG
    // Takeoff. Plain download stays available from the preview pane.
    const target = primaryModule(row.kind, row.extension);
    // Destinations that resolve the project from the global context
    // store (Clash, BI Explorer) need it bound first or they land on
    // the empty "no project" state. Reuse the known context name when
    // it's the same project.
    if (target.setsActiveProject) {
      const ctx = useProjectContextStore.getState();
      const name =
        ctx.activeProjectId === row.project_id
          ? ctx.activeProjectName
          : projectsLite.find((p) => p.id === row.project_id)?.name ?? ctx.activeProjectName;
      ctx.setActiveProject(row.project_id, name);
    }
    recordRecentlyViewed(row);
    navigate(target.route(row.project_id, row.id, row));
  }

  function handleOpenRecent(item: RecentItem) {
    const target = primaryModule(item.kind, item.extension);
    if (target.setsActiveProject) {
      const ctx = useProjectContextStore.getState();
      const name =
        ctx.activeProjectId === item.project_id
          ? ctx.activeProjectName
          : projectsLite.find((p) => p.id === item.project_id)?.name ?? ctx.activeProjectName;
      ctx.setActiveProject(item.project_id, name);
    }
    navigate(target.route(item.project_id, item.id, item));
  }

  function handleOpenCategory(kind: FileKind) {
    setSelectedKind(kind);
    setSelectedIds(new Set());
    setPreviewRow(null);
  }

  function handleBackToAll() {
    setSelectedKind(null);
    setSelectedIds(new Set());
    setPreviewRow(null);
    setQuery('');
  }

  function handleOpenUpload(kind: FileKind | null) {
    setUploadKind(kind);
    setShowUpload(true);
  }

  useFileShortcuts({
    enabled: !showCheatsheet && !showUpload && !showExport && !showImport,
    onFocusSearch: () => {
      const input = document.querySelector<HTMLInputElement>(
        'input[type="search"]',
      );
      input?.focus();
      input?.select();
    },
    onSetView: setView,
    onEscape: () => {
      if (previewRow) {
        setPreviewRow(null);
        return;
      }
      if (selectedIds.size > 0) {
        setSelectedIds(new Set());
      }
    },
    onToggleCheatsheet: () => setShowCheatsheet((p) => !p),
  });

  if (!projectId) {
    return (
      <div className="flex items-center justify-center h-full">
        <h1 className="sr-only">{t('nav.project_files', { defaultValue: 'Project Files' })}</h1>
        <EmptyState
          icon={<HardDrive size={28} />}
          title={t('files.no_project_title', { defaultValue: 'No active project' })}
          description={t('files.no_project_desc', {
            defaultValue:
              'Pick a project from the dashboard to see all of its documents, photos, BIM and DWG files in one place.',
          })}
          action={{
            label: t('files.go_to_projects', { defaultValue: 'Go to projects' }),
            onClick: () => navigate('/projects'),
          }}
        />
      </div>
    );
  }

  const selectedRows = list?.items.filter((r) => selectedIds.has(r.id)) ?? [];
  const showFolderGrid = selectedKind === null;
  const activeKindLabel = selectedKind
    ? t(`files.category.${selectedKind}`, { defaultValue: selectedKind })
    : '';

  // First-load overlay: shown only when at least one of the bootstrap
  // queries is still in flight AND we have no cached data yet. After both
  // queries resolve, the overlay disappears and never reappears for this
  // mount (React Query caches the result).
  const isFirstLoad = (treeLoading || locLoading) && (!tree || !locations);

  return (
    <div className="flex flex-col h-full">
      {/* Accessible page heading. The visible module title lives in the
          global top bar (shown lg+), so this sr-only h1 gives the page the
          single semantic heading screen readers and a11y checks expect. */}
      <h1 className="sr-only">{t('nav.project_files', { defaultValue: 'Project Files' })}</h1>
      {isFirstLoad && (
        <InitialLoadProgress
          storageDone={!!locations}
          treeDone={!!tree}
          projectName={ctxProjectName}
        />
      )}
      <div className="px-4 pt-3">
        <Breadcrumb
          items={[
            ...(ctxProjectName
              ? [{ label: ctxProjectName, to: `/projects/${projectId}` }]
              : []),
            { label: t('nav.project_files') },
          ]}
        />
      </div>
      <PathBar locations={locations} isLoading={locLoading} selectedKind={selectedKind} />

      {/* Page-level breadcrumb + primary upload CTA. Lives outside the
          tree/main split so it's always visible whether the user is on
          the folder grid or drilled into a category. */}
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-border-light bg-surface-elevated">
        <nav
          className="flex items-center gap-1.5 text-sm min-w-0"
          aria-label={t('common.breadcrumb', { defaultValue: 'Breadcrumb' })}
        >
          <button
            type="button"
            onClick={handleBackToAll}
            className={clsx(
              'inline-flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors',
              showFolderGrid
                ? 'text-content-primary font-semibold cursor-default'
                : 'text-content-secondary hover:text-content-primary hover:bg-surface-secondary',
            )}
            disabled={showFolderGrid}
          >
            {!showFolderGrid && <ArrowLeft size={13} />}
            {t('files.title_all', { defaultValue: 'All files' })}
          </button>
          {!showFolderGrid && (
            <>
              <ChevronRight size={12} className="text-content-quaternary shrink-0" />
              <span className="px-2 py-1 text-content-primary font-semibold truncate" title={activeKindLabel}>
                {activeKindLabel}
              </span>
            </>
          )}
        </nav>

        <div className="flex items-center gap-2">
          {/* "How it works" guide — concepts + how to upload and feed
              takeoff/BOQ. Sits in the page action cluster; its closing CTA
              opens the upload dialog. */}
          <ModuleGuideButton
            content={filesGuide}
            onCta={() => handleOpenUpload(selectedKind)}
          />
          {/* W10 — cross-project search */}
          <Link
            to="/files/search"
            className="hidden sm:inline-flex items-center gap-1.5 h-9 px-2.5 rounded-lg text-xs font-medium text-content-secondary hover:text-content-primary hover:bg-surface-secondary transition-colors"
            title={t('files.global_search.title', { defaultValue: 'Search across projects' })}
          >
            <Search size={13} />
            <span className="hidden md:inline">
              {t('files.global_search.short', { defaultValue: 'Search all projects' })}
            </span>
          </Link>
          {/* W7 — transmittal log entry point */}
          <Link
            to="/files/transmittals"
            data-guide="files-transmittal-link"
            className="hidden sm:inline-flex items-center gap-1.5 h-9 px-2.5 rounded-lg text-xs font-medium text-content-secondary hover:text-content-primary hover:bg-surface-secondary transition-colors"
            title={t('files.transmittals.open_log', { defaultValue: 'Transmittal log' })}
          >
            <Send size={13} />
            <span className="hidden md:inline">
              {t('files.transmittals.open_log', { defaultValue: 'Transmittal log' })}
            </span>
          </Link>
          <button
            type="button"
            data-guide="files-upload-button"
            onClick={() => handleOpenUpload(selectedKind)}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-xs font-semibold bg-oe-blue text-white hover:bg-oe-blue-hover transition-colors shrink-0"
          >
            <UploadCloud size={14} />
            {t('files.upload', { defaultValue: 'Upload files' })}
          </button>
        </div>
      </div>

      <div className="flex-1 flex min-h-0">
        <FileTree
          nodes={tree ?? []}
          selectedId={selectedKind}
          onSelect={(id) => {
            setSelectedKind(id as FileKind | null);
            setSelectedIds(new Set());
            setPreviewRow(null);
          }}
          isLoading={treeLoading}
          projectId={projectId}
        />

        <main className="flex-1 flex flex-col min-w-0">
          {showFolderGrid ? (
            <div className="flex-1 overflow-auto">
              <FilesStatsStrip tree={tree} locations={locations} />
              <RecentlyViewedStrip projectId={projectId} onOpen={handleOpenRecent} />
              <FolderCardGrid
                nodes={tree ?? []}
                isLoading={treeLoading}
                onOpenCategory={handleOpenCategory}
                onUpload={handleOpenUpload}
                onManageAccess={(kind) => setPermsKind(kind)}
                permissionCounts={permissionCounts}
                canManageAccess={isOwner}
              />
            </div>
          ) : (
            <>
              <FileActionsBar
                query={query}
                onQueryChange={setQuery}
                sort={sort}
                onSortChange={setSort}
                view={view}
                onViewChange={setView}
                onExport={() => setShowExport(true)}
                onImport={() => setShowImport(true)}
                totalCount={
                  showFavoritesOnly || tagFilterActive
                    ? displayItems.length
                    : list?.total ?? 0
                }
                extension={extension}
                onExtensionChange={setExtension}
                projectId={projectId}
                category={selectedKind}
                selectedTagIds={selectedTagIds}
                onSelectedTagsChange={setSelectedTagIds}
                favoritesOnly={showFavoritesOnly}
                onFavoritesOnlyChange={setShowFavoritesOnly}
                favoritesCount={favorites.keys.size}
              />
              <BulkActionsBar
                selectedRows={selectedRows}
                projectId={projectId}
                onClear={() => setSelectedIds(new Set())}
              />
              <div className="flex-1 overflow-auto">
                {view === 'grid' ? (
                  <FileGrid
                    items={displayItems}
                    selectedIds={selectedIds}
                    onSelect={handleSelect}
                    onOpen={handleOpen}
                    isLoading={listLoading}
                    favoriteKeys={favorites.keys}
                    onToggleFavorite={handleToggleFavorite}
                  />
                ) : (
                  <FileList
                    items={displayItems}
                    selectedIds={selectedIds}
                    onSelect={handleSelect}
                    onOpen={handleOpen}
                    sort={sort}
                    onSortChange={setSort}
                    isLoading={listLoading}
                    favoriteKeys={favorites.keys}
                    onToggleFavorite={handleToggleFavorite}
                  />
                )}
              </div>
            </>
          )}
        </main>

        {!showFolderGrid && (
          <FilePreviewPane
            row={previewRow}
            onClose={() => setPreviewRow(null)}
            onEmail={(row) => setEmailRow(row)}
            onShare={(row) => setShareRow(row)}
            onManageAccess={
              isOwner ? (row) => setPermsKind(row.kind) : undefined
            }
          />
        )}
      </div>

      <ExportWizard
        open={showExport}
        projectId={projectId}
        projectName={locations?.project_name ?? ctxProjectName}
        onClose={() => setShowExport(false)}
      />
      <ImportWizard open={showImport} onClose={() => setShowImport(false)} />
      <ShareLinkModal
        open={shareRow !== null}
        row={shareRow}
        onClose={() => setShareRow(null)}
      />
      <EmailDialog
        open={emailRow !== null}
        row={emailRow}
        onClose={() => setEmailRow(null)}
      />
      <UploadDialog
        open={showUpload}
        projectId={projectId}
        defaultKind={uploadKind}
        onClose={() => setShowUpload(false)}
      />
      <FolderPermissionsModal
        open={permsKind !== null}
        projectId={projectId ?? null}
        scopeKind={permsKind}
        folderLabel={
          permsKind ? t(`files.category.${permsKind}`, { defaultValue: permsKind }) : undefined
        }
        onClose={() => setPermsKind(null)}
      />
      <ShortcutsCheatsheet
        open={showCheatsheet}
        onClose={() => setShowCheatsheet(false)}
      />
    </div>
  );
}
