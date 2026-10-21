// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Project File Manager — Issue #109.
 *
 * Unified file & folder hub. The default view (no category selected) is
 * a folder-card grid; clicking a folder drills into the existing
 * grid/list view with the rest of the UI (path bar, search, sort,
 * preview pane) intact.
 */

import { ConverterReleaseNotice } from '@/shared/ui/ConverterReleaseNotice';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueries, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ChevronRight, HardDrive, UploadCloud, Search, Send, Loader2, ClipboardCheck } from 'lucide-react';
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
  fileManagerKeys,
  useFavorites,
  useInfiniteFileList,
  useFileTree,
  useFolderPermissionCounts,
  useIsProjectOwner,
  useProjectsLite,
  useStorageLocations,
  useToggleFavorite,
} from './hooks';
import { useFileUpload } from './useFileUpload';
import { PathBar } from './components/PathBar';
import { FileTree } from './components/FileTree';
import { FileGrid } from './components/FileGrid';
import { FileList } from './components/FileList';
import { FileContextMenu } from './components/FileContextMenu';
import { RenameDialog } from './components/RenameDialog';
import { FilePreviewPane } from './components/FilePreviewPane';
import { FileActionsBar, type ViewMode } from './components/FileActionsBar';
import { useContentSearch, useReindexProject } from '@/features/file-search/hooks';
import type { SearchMode } from '@/features/file-search/types';
import { softDelete } from '@/features/file-trash/api';
import { useRestoreFromTrash } from '@/features/file-trash/hooks';
import { showUndoDeleteToast } from '@/features/file-trash/UndoDeleteToast';
import type { TrashKind } from '@/features/file-trash/types';
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
import { primaryModule, isInlinePreviewRow, isLightboxRow } from './kindModule';
import { InlinePdfPreviewModal } from '@/features/file-references/InlinePdfPreviewModal';
import { MediaLightbox, type MediaLightboxItem } from './components/MediaLightbox';
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
  // #284: a PDF document opens in a focused inline reader overlay by default
  // instead of jumping to PDF Takeoff. This holds the row whose bytes the
  // InlinePdfPreviewModal is showing (null = closed).
  const [inlinePdfRow, setInlinePdfRow] = useState<FileRow | null>(null);
  // #284 follow-up (ITEM 10): an image / video opens in the MediaLightbox
  // instead of falling through to PDF Takeoff. We track the active media file
  // by id (null = closed) so prev/next can page through the visible media rows
  // even as the underlying list re-renders.
  const [lightboxId, setLightboxId] = useState<string | null>(null);
  const [showExport, setShowExport] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [emailRow, setEmailRow] = useState<FileRow | null>(null);
  const [shareRow, setShareRow] = useState<FileRow | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadKind, setUploadKind] = useState<FileKind | null>(null);
  const [permsKind, setPermsKind] = useState<FileKind | null>(null);
  const [showCheatsheet, setShowCheatsheet] = useState(false);
  // Right-click context menu (row + cursor position) and the rename modal.
  const [menu, setMenu] = useState<{ row: FileRow; x: number; y: number } | null>(null);
  const [renameRow, setRenameRow] = useState<FileRow | null>(null);
  // Filename vs content (OCR) search mode.
  const [searchMode, setSearchMode] = useState<SearchMode>('filename');
  // Page-level drag-and-drop upload overlay.
  const [pageDragOver, setPageDragOver] = useState(false);
  const dragDepthRef = useRef(0);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

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
  // (potentially very large) full-file list response entirely. Paged with
  // useInfiniteQuery so a large category streams in on scroll rather than
  // loading every row up front.
  const {
    data: listPages,
    isLoading: listLoading,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useInfiniteFileList(selectedKind ? projectId : null, filters);
  const flatItems = useMemo<FileRow[]>(
    () => listPages?.pages.flatMap((p) => p.items) ?? [],
    [listPages],
  );
  const listTotal = listPages?.pages[0]?.total ?? 0;

  // ── Content (OCR) search ─────────────────────────────────────────────
  // Fires only in content mode with a non-empty query. Hits are mapped to
  // FileRow-shaped rows so they render through the very same grid/list and
  // reuse selection, open, context-menu and favourite wiring.
  const contentActive = searchMode === 'content' && query.trim().length > 0;
  const contentSearch = useContentSearch(
    projectId,
    searchMode === 'content' ? query : '',
    selectedKind ?? undefined,
    'content',
  );
  const reindex = useReindexProject();
  const searchRows = useMemo<FileRow[]>(() => {
    const hits = contentSearch.data?.hits ?? [];
    return hits.map((hit) => {
      const dot = hit.canonical_name.lastIndexOf('.');
      const extension = dot > 0 ? hit.canonical_name.slice(dot) : null;
      const kind = hit.kind as FileKind;
      return {
        id: hit.file_id,
        kind,
        name: hit.canonical_name,
        project_id: projectId as string,
        size_bytes: 0,
        mime_type: null,
        extension,
        modified_at: null,
        physical_path: '',
        relative_path: '',
        storage_backend: 'local',
        download_url:
          kind === 'document' ? `/api/v1/documents/${hit.file_id}/download/` : null,
        preview_url: null,
        thumbnail_url: null,
        discipline: null,
        category: null,
        extra: {
          snippet: hit.snippet,
          score: hit.score,
          page_count: hit.page_count,
        },
      } satisfies FileRow;
    });
  }, [contentSearch.data, projectId]);

  // Rows the current view is built from: search hits in content mode, the
  // paged file list otherwise. All find-by-id / selection lookups use this.
  const baseItems = contentActive ? searchRows : flatItems;

  // Shared upload routine for the page-level drag-and-drop drop zone.
  const { doUpload } = useFileUpload(projectId);

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
  const visibleItems = baseItems;
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

  // #284 follow-up (ITEM 10): the set of visible image/video rows the
  // MediaLightbox pages through, plus the active one's index. Derived from the
  // already-filtered ``displayItems`` so prev/next walks exactly what the user
  // sees. Trimmed to the MediaLightbox shape so the overlay stays decoupled
  // from the full FileRow type.
  const mediaItems = useMemo<MediaLightboxItem[]>(
    () =>
      displayItems.filter(isLightboxRow).map((r) => ({
        id: r.id,
        kind: r.kind,
        name: r.name,
        extension: r.extension,
        mime_type: r.mime_type,
        download_url: r.download_url,
      })),
    [displayItems],
  );
  const lightboxIndex = lightboxId
    ? mediaItems.findIndex((m) => m.id === lightboxId)
    : -1;

  // Whenever the paged filename list changes, drop selection that no longer
  // matches the accumulated result set so the preview pane never shows a
  // stale row. Skipped during content search (a shrinking hit list must not
  // wipe a selection made in the filename view) and tolerant of pagination:
  // ``flatItems`` only grows as pages load, so prior selection survives.
  useEffect(() => {
    if (contentActive || !listPages) return;
    const visibleIds = new Set(flatItems.map((r) => r.id));
    setSelectedIds((prev) => {
      const next = new Set([...prev].filter((id) => visibleIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
    if (previewRow && !visibleIds.has(previewRow.id)) {
      setPreviewRow(null);
    }
  }, [listPages, flatItems, previewRow, contentActive]);

  // Deep-link: `?file={id}` pre-selects that file in the preview pane.
  // Used by the "Open in File Manager" secondary action so users land
  // directly on the focused file rather than just the category grid.
  const fileIdParam = searchParams.get('file');
  useEffect(() => {
    if (!fileIdParam || flatItems.length === 0) return;
    const target = flatItems.find((r) => r.id === fileIdParam);
    if (target) {
      setPreviewRow(target);
      setSelectedIds(new Set([fileIdParam]));
    }
  }, [fileIdParam, flatItems]);

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
        const row = baseItems.find((r) => r.id === id);
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
    const row = baseItems.find((r) => r.id === id);
    if (row) setPreviewRow(row);
  }

  function handleOpen(row: FileRow) {
    // Opening a file means "take me to the tool that processes it" —
    // IFC/RVT to BIM 3D Viewer, DWG to DWG Takeoff. A PDF document is the
    // exception (#284): it opens in a focused inline reader here, because
    // most project PDFs are contracts / specs / letters the user just wants
    // to read. PDF Takeoff stays one explicit click away in the preview
    // pane and the context menu. Plain download stays available too.
    if (isInlinePreviewRow(row)) {
      recordRecentlyViewed(row);
      setInlinePdfRow(row);
      return;
    }
    // ITEM 10: images / videos open in the MediaLightbox, never PDF Takeoff.
    if (isLightboxRow(row)) {
      recordRecentlyViewed(row);
      setLightboxId(row.id);
      return;
    }
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
    navigate(target.route(row.project_id, row.id, row.extra));
  }

  function handleOpenRecent(item: RecentItem) {
    // A recent PDF document opens in the same inline reader as a fresh open.
    // Prefer the live FileRow when the file is in the loaded list; otherwise
    // reconstruct the minimal row from the recents entry. We only do this for
    // the ``document`` kind, whose id IS a Document id the download route
    // resolves - a ``sheet`` id is a Sheet PK and must keep its takeoff route.
    const recentRow: FileRow | undefined = flatItems.find((r) => r.id === item.id);
    if (recentRow && isInlinePreviewRow(recentRow)) {
      setInlinePdfRow(recentRow);
      return;
    }
    // ITEM 10: a recent image / video that is in the loaded list opens in the
    // MediaLightbox (paging through the other visible media rows).
    if (recentRow && isLightboxRow(recentRow)) {
      setLightboxId(recentRow.id);
      return;
    }
    const ext = (item.extension ?? '').toLowerCase().replace(/^\./, '');
    const isPdfDoc = ext === 'pdf' && item.kind === 'document';
    if (isPdfDoc) {
      // Synthesize the minimal FileRow the inline modal needs. The download
      // route mirrors what _collect_documents serialises for a document row.
      setInlinePdfRow({
        id: item.id,
        kind: item.kind,
        name: item.name,
        project_id: item.project_id,
        size_bytes: 0,
        mime_type: 'application/pdf',
        extension: item.extension ?? '.pdf',
        modified_at: null,
        physical_path: '',
        relative_path: '',
        storage_backend: 'local',
        download_url: `/api/v1/documents/${item.id}/download/`,
        preview_url: null,
        thumbnail_url: null,
        discipline: null,
        category: null,
        extra: {},
      });
      return;
    }
    const target = primaryModule(item.kind, item.extension);
    if (target.setsActiveProject) {
      const ctx = useProjectContextStore.getState();
      const name =
        ctx.activeProjectId === item.project_id
          ? ctx.activeProjectName
          : projectsLite.find((p) => p.id === item.project_id)?.name ?? ctx.activeProjectName;
      ctx.setActiveProject(item.project_id, name);
    }
    navigate(target.route(item.project_id, item.id));
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

  // Single-file delete from the context menu — soft-delete (recycle bin)
  // plus the inline Undo toast, mirroring the bulk-bar delete pattern.
  const restoreMutation = useRestoreFromTrash(projectId);
  function handleContextDelete(row: FileRow) {
    if (!projectId) return;
    softDelete({
      project_id: projectId,
      kind: row.kind as TrashKind,
      original_id: row.id,
      canonical_name: row.name,
    })
      .then((trash) => {
        queryClient.invalidateQueries({ queryKey: [fileManagerKeys.tree, projectId] });
        queryClient.invalidateQueries({ queryKey: [fileManagerKeys.list, projectId] });
        setSelectedIds((prev) => {
          if (!prev.has(row.id)) return prev;
          const next = new Set(prev);
          next.delete(row.id);
          return next;
        });
        if (previewRow?.id === row.id) setPreviewRow(null);
        showUndoDeleteToast({
          fileName: row.name,
          trashId: trash.id,
          onUndo: (tid: string) => restoreMutation.mutate(tid),
          t,
        });
      })
      .catch((err: unknown) =>
        addToast({
          type: 'error',
          title: t('files.bulk.delete_failed', { defaultValue: 'Bulk delete failed' }),
          message: err instanceof Error ? err.message : String(err),
        }),
      );
  }

  // "Update search index" — re-OCR every file so recent uploads become
  // searchable by their text content.
  function handleReindex() {
    if (!projectId || reindex.isPending) return;
    reindex.mutate(projectId, {
      onSuccess: (res) =>
        addToast({
          type: 'success',
          title: t('files.search.reindex_done', { defaultValue: 'Search index updated' }),
          message: t('files.search.reindex_summary', {
            defaultValue: '{{indexed}} indexed, {{skipped}} skipped',
            indexed: res.indexed,
            skipped: res.skipped,
          }),
        }),
      onError: (err: Error) =>
        addToast({
          type: 'error',
          title: t('files.search.reindex_failed', {
            defaultValue: 'Could not update the index',
          }),
          message: err.message,
        }),
    });
  }

  // Page-level drag-and-drop upload. A depth counter keeps the overlay
  // stable while dragging over nested children (each fires its own
  // enter/leave). Files drop into the current category via the shared
  // upload path.
  const dragHasFiles = (e: React.DragEvent) =>
    Array.from(e.dataTransfer.types).includes('Files');
  function handlePageDragEnter(e: React.DragEvent) {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    dragDepthRef.current += 1;
    setPageDragOver(true);
  }
  function handlePageDragOver(e: React.DragEvent) {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
  }
  function handlePageDragLeave(e: React.DragEvent) {
    if (!dragHasFiles(e)) return;
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setPageDragOver(false);
  }
  function handlePageDrop(e: React.DragEvent) {
    e.preventDefault();
    dragDepthRef.current = 0;
    setPageDragOver(false);
    if (e.dataTransfer.files.length > 0) {
      void doUpload(e.dataTransfer.files, selectedKind);
    }
  }

  // IntersectionObserver-driven load-more for the filename list. Attaches
  // only when a next page exists and content search is off. Older runtimes
  // without the API fall back to the visible "Load more" button.
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || contentActive || !hasNextPage) return;
    if (typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((en) => en.isIntersecting) && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      { rootMargin: '300px 0px', threshold: 0 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [contentActive, hasNextPage, isFetchingNextPage, fetchNextPage, flatItems.length]);

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
        <h1 className="sr-only">{t('nav.documents', { defaultValue: 'Documents' })}</h1>
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

  const selectedRows = baseItems.filter((r) => selectedIds.has(r.id));
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
      <h1 className="sr-only">{t('nav.documents', { defaultValue: 'Documents' })}</h1>
      {isFirstLoad && (
        <InitialLoadProgress
          storageDone={!!locations}
          treeDone={!!tree}
          projectName={ctxProjectName}
        />
      )}
      <ConverterReleaseNotice className="mx-4 mt-3" />
      <div className="px-4 pt-3">
        <Breadcrumb
          items={[
            ...(ctxProjectName
              ? [{ label: ctxProjectName, to: `/projects/${projectId}` }]
              : []),
            { label: t('nav.documents') },
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
          {/* Project-wide file-approvals register + one-click Excel export */}
          <Link
            to="/files/approvals"
            data-guide="files-approvals-link"
            className="hidden sm:inline-flex items-center gap-1.5 h-9 px-2.5 rounded-lg text-xs font-medium text-content-secondary hover:text-content-primary hover:bg-surface-secondary transition-colors"
            title={t('files.approvals.register_title', { defaultValue: 'Approvals register' })}
          >
            <ClipboardCheck size={13} />
            <span className="hidden md:inline">
              {t('files.approvals.register_title', { defaultValue: 'Approvals register' })}
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
                  contentActive
                    ? contentSearch.data?.total ?? displayItems.length
                    : showFavoritesOnly || tagFilterActive
                      ? displayItems.length
                      : listTotal
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
                searchMode={searchMode}
                onSearchModeChange={setSearchMode}
                onReindex={handleReindex}
                reindexing={reindex.isPending}
              />
              <BulkActionsBar
                selectedRows={selectedRows}
                projectId={projectId}
                onClear={() => setSelectedIds(new Set())}
              />
              <div
                className="relative flex-1 overflow-auto"
                onDragEnter={handlePageDragEnter}
                onDragOver={handlePageDragOver}
                onDragLeave={handlePageDragLeave}
                onDrop={handlePageDrop}
              >
                {/* A failed content search returns no hits, which the grid
                    below would draw as "nothing matched" - the same picture a
                    successful search of an unindexed project gives. Say which
                    one it was, and offer the retry, because a search the user
                    believes came back empty is worse than one that admits it
                    broke. */}
                {contentActive && contentSearch.isError && (
                  <div
                    role="alert"
                    className="mx-3 mt-3 flex items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200"
                  >
                    <span>
                      {t('files.search.failed', {
                        defaultValue:
                          'The content search did not come back, so these results are incomplete.',
                      })}
                    </span>
                    <button
                      type="button"
                      onClick={() => void contentSearch.refetch()}
                      className="shrink-0 rounded-md border border-amber-400 px-2 py-0.5 font-medium hover:bg-amber-100 dark:border-amber-800 dark:hover:bg-amber-900/40"
                    >
                      {t('common.retry', { defaultValue: 'Retry' })}
                    </button>
                  </div>
                )}
                {view === 'grid' ? (
                  <FileGrid
                    items={displayItems}
                    selectedIds={selectedIds}
                    onSelect={handleSelect}
                    onOpen={handleOpen}
                    isLoading={contentActive ? contentSearch.isLoading : listLoading}
                    favoriteKeys={favorites.keys}
                    onToggleFavorite={handleToggleFavorite}
                    onContextMenu={(row, x, y) => setMenu({ row, x, y })}
                    searchQuery={contentActive ? query : undefined}
                  />
                ) : (
                  <FileList
                    items={displayItems}
                    selectedIds={selectedIds}
                    onSelect={handleSelect}
                    onOpen={handleOpen}
                    sort={sort}
                    onSortChange={setSort}
                    isLoading={contentActive ? contentSearch.isLoading : listLoading}
                    favoriteKeys={favorites.keys}
                    onToggleFavorite={handleToggleFavorite}
                    onContextMenu={(row, x, y) => setMenu({ row, x, y })}
                    searchQuery={contentActive ? query : undefined}
                  />
                )}

                {/* Load-more sentinel — auto-fetches the next page when it
                    scrolls into view (filename list only). The button is a
                    click fallback for runtimes without IntersectionObserver. */}
                {!contentActive && hasNextPage && (
                  <div ref={sentinelRef} className="flex justify-center py-4">
                    <button
                      type="button"
                      onClick={() => fetchNextPage()}
                      disabled={isFetchingNextPage}
                      className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-medium border border-border-light text-content-secondary hover:bg-surface-secondary disabled:opacity-60"
                    >
                      {isFetchingNextPage && <Loader2 size={13} className="animate-spin" />}
                      {t('files.load_more', { defaultValue: 'Load more' })}
                    </button>
                  </div>
                )}

                {/* Drop overlay — shown while dragging files over the list. */}
                {pageDragOver && (
                  <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center bg-oe-blue/10 backdrop-blur-sm">
                    <div className="flex flex-col items-center gap-2 rounded-xl border-2 border-dashed border-oe-blue bg-surface-elevated/90 px-8 py-6 shadow-lg">
                      <UploadCloud size={28} className="text-oe-blue" />
                      <p className="text-sm font-semibold text-content-primary">
                        {t('files.drop_to_upload', {
                          defaultValue: 'Drop files to upload to {{category}}',
                          category: activeKindLabel,
                        })}
                      </p>
                    </div>
                  </div>
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
      {/* #284 - focused inline PDF reader. Opened by handleOpen for a PDF
          document so reading a contract / spec no longer drops the user
          into the takeoff tool. */}
      <InlinePdfPreviewModal
        open={inlinePdfRow !== null}
        downloadUrl={inlinePdfRow?.download_url ?? null}
        title={inlinePdfRow?.name ?? ''}
        onClose={() => setInlinePdfRow(null)}
      />
      {/* ITEM 10 - image viewer / video player. Opened by handleOpen for an
          image or video document so it no longer falls through to the takeoff
          tool. Pages through every visible media row via prev/next. */}
      <MediaLightbox
        open={lightboxId !== null && lightboxIndex >= 0}
        items={mediaItems}
        index={lightboxIndex >= 0 ? lightboxIndex : 0}
        onClose={() => setLightboxId(null)}
        onIndexChange={(next) => {
          const item = mediaItems[next];
          if (item) setLightboxId(item.id);
        }}
      />
      {/* Right-click context menu — Open / Download / Copy link / Rename /
          Delete. Rename opens the modal below; Delete soft-deletes with an
          inline Undo toast. */}
      {menu && (
        <FileContextMenu
          row={menu.row}
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          onRename={(row) => setRenameRow(row)}
          onDelete={(row) => handleContextDelete(row)}
          onInlinePreview={(row) => setInlinePdfRow(row)}
          onMediaPreview={(row) => setLightboxId(row.id)}
        />
      )}
      <RenameDialog
        open={renameRow !== null}
        row={renameRow}
        projectId={projectId}
        onClose={() => setRenameRow(null)}
      />
    </div>
  );
}
