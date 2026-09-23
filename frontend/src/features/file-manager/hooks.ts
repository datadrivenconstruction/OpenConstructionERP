// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** React Query hooks for the file manager. */

import { useMemo } from 'react';
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  keepPreviousData,
} from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchFavorites,
  fetchFileList,
  fetchFileTree,
  fetchStorageLocations,
  listFolderPermissions,
  renameDocument,
  setDocumentCdeState,
  starFile,
  unstarFile,
  type CdeState,
} from './api';
import type { FileListResponse } from './types';
import {
  favoriteKey,
  type FileFavorite,
  type FileFilters,
  type FileKind,
  type FolderPermissionRow,
} from './types';

const KEY_TREE = 'file-manager-tree';
const KEY_LIST = 'file-manager-list';
const KEY_LOC = 'file-manager-locations';
const KEY_FOLDER_PERMS = 'folder-permission-counts';
const KEY_IS_PROJECT_OWNER = 'is-project-owner';
const KEY_FAVORITES = 'file-manager-favorites';

export function useFileTree(
  projectId: string | null | undefined,
  filters: { q?: string; extension?: string } = {},
) {
  return useQuery({
    queryKey: [KEY_TREE, projectId, filters],
    queryFn: () => fetchFileTree(projectId as string, filters),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });
}

export function useFileList(
  projectId: string | null | undefined,
  filters: FileFilters,
) {
  return useQuery({
    queryKey: [KEY_LIST, projectId, filters],
    queryFn: () => fetchFileList(projectId as string, filters),
    enabled: Boolean(projectId),
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });
}

/** Default page size for the infinite file list. Large enough that most
 * categories fit in one page, small enough that a 10k-file category paints
 * the first screen quickly and streams the rest on scroll. */
export const FILE_LIST_PAGE_SIZE = 60;

/**
 * Infinite (offset-paged) variant of {@link useFileList} used by the main
 * File Manager grid/list. Pages the existing ``limit``/``offset`` list
 * endpoint and stops when the accumulated item count reaches
 * ``FileListResponse.total``. The caller flattens ``data.pages`` into a
 * single array and drives an IntersectionObserver sentinel off
 * ``fetchNextPage`` / ``hasNextPage``.
 */
export function useInfiniteFileList(
  projectId: string | null | undefined,
  filters: FileFilters,
  pageSize: number = FILE_LIST_PAGE_SIZE,
) {
  return useInfiniteQuery<FileListResponse, Error>({
    queryKey: [KEY_LIST, projectId, filters, 'infinite', pageSize],
    queryFn: ({ pageParam }) =>
      fetchFileList(projectId as string, {
        ...filters,
        limit: pageSize,
        offset: (pageParam as number) ?? 0,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.items.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
    enabled: Boolean(projectId),
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });
}

export function useStorageLocations(projectId: string | null | undefined) {
  return useQuery({
    queryKey: [KEY_LOC, projectId],
    queryFn: () => fetchStorageLocations(projectId as string),
    enabled: Boolean(projectId),
    staleTime: 60_000,
  });
}

export const fileManagerKeys = {
  tree: KEY_TREE,
  list: KEY_LIST,
  locations: KEY_LOC,
  folderPermissionCounts: KEY_FOLDER_PERMS,
  isProjectOwner: KEY_IS_PROJECT_OWNER,
  favorites: KEY_FAVORITES,
};

/* ── Per-user favourites / pins ────────────────────────────────────── */

export interface UseFavoritesResult {
  /** Raw favourite rows (pinned-first, as the backend returns them). */
  rows: FileFavorite[];
  /** Fast membership lookup keyed by ``favoriteKey(kind, id)``. */
  keys: Set<string>;
  /** Subset that is pinned (elevated favourites). */
  pinnedKeys: Set<string>;
  isLoading: boolean;
}

/**
 * The current user's favourites for a project. Returns a memoised
 * ``Set`` of ``kind:id`` keys so a grid of N tiles does an O(1) lookup
 * per tile instead of scanning the row list.
 */
export function useFavorites(
  projectId: string | null | undefined,
): UseFavoritesResult {
  const { data = [], isLoading } = useQuery({
    queryKey: [KEY_FAVORITES, projectId],
    queryFn: () => fetchFavorites(projectId as string),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });

  return useMemo(() => {
    const keys = new Set<string>();
    const pinnedKeys = new Set<string>();
    for (const row of data) {
      const k = favoriteKey(row.file_kind, row.file_id);
      keys.add(k);
      if (row.pinned) pinnedKeys.add(k);
    }
    return { rows: data, keys, pinnedKeys, isLoading };
  }, [data, isLoading]);
}

/**
 * Toggle a file's favourite state with an optimistic cache write so the
 * star fills/empties instantly. Rolls back and rethrows on error so the
 * caller can surface a toast.
 */
export function useToggleFavorite(projectId: string | null | undefined) {
  const qc = useQueryClient();
  const queryKey = [KEY_FAVORITES, projectId];

  return useMutation({
    mutationFn: async (vars: {
      kind: FileKind;
      fileId: string;
      /** Current state — when already a favourite we un-star, else star. */
      isFavorite: boolean;
    }) => {
      if (!projectId) throw new Error('No active project');
      if (vars.isFavorite) {
        await unstarFile(projectId, vars.kind, vars.fileId);
        return null;
      }
      return starFile(projectId, vars.kind, vars.fileId);
    },
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey });
      const previous = qc.getQueryData<FileFavorite[]>(queryKey);
      qc.setQueryData<FileFavorite[]>(queryKey, (old = []) => {
        const k = favoriteKey(vars.kind, vars.fileId);
        if (vars.isFavorite) {
          return old.filter((r) => favoriteKey(r.file_kind, r.file_id) !== k);
        }
        // Optimistic insert — the real row (with id/timestamps) replaces
        // this on settle via invalidation.
        const optimistic: FileFavorite = {
          id: `optimistic-${k}`,
          user_id: '',
          project_id: projectId ?? '',
          file_kind: vars.kind,
          file_id: vars.fileId,
          pinned: false,
          created_at: '',
          updated_at: '',
        };
        return [...old, optimistic];
      });
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) qc.setQueryData(queryKey, context.previous);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey });
    },
  });
}

/* ── Document lifecycle (CDE) state ────────────────────────────────── */

/**
 * Promote / demote a document's CDE lifecycle state via
 * ``PATCH /v1/documents/{id}``. On success we invalidate the file list +
 * tree for the project so the new state badge re-renders everywhere
 * (grid tiles, list rows, preview pane). The caller is responsible for
 * guarding on ``kind === 'document'``. Only that kind is backed by the
 * documents table that owns the ``cde_state`` column.
 */
export function useSetDocumentCdeState(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    // A rejected ISO 19650 CDE transition (forward-only lifecycle, role gate,
    // signature gate, out-of-state suitability) is handled by the caller's
    // onError, which classifies the raw backend string into a clear, localized
    // toast. Suppress the global "Operation failed" toast (main.tsx
    // MutationCache) so the user does not also see the raw, untranslated
    // backend message alongside the friendly one.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: (vars: { documentId: string; cdeState: CdeState }) =>
      setDocumentCdeState(vars.documentId, vars.cdeState),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY_LIST, projectId] });
      qc.invalidateQueries({ queryKey: [KEY_TREE, projectId] });
    },
  });
}

/**
 * Rename a document via ``PATCH /v1/documents/{id}``. On success we
 * invalidate the file list + tree for the project so the new name
 * re-renders everywhere (grid tiles, list rows, tree labels, preview
 * pane). The caller must guard on ``kind === 'document'`` - only that
 * kind is backed by the documents table that owns the ``name`` column.
 */
export function useRenameDocument(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { documentId: string; name: string }) =>
      renameDocument(vars.documentId, vars.name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY_LIST, projectId] });
      qc.invalidateQueries({ queryKey: [KEY_TREE, projectId] });
    },
  });
}

/* ── Per-folder permissions helpers ────────────────────────────────── */

interface ProjectOwnerInfo {
  id: string;
  owner_id: string;
}

/** Decode the JWT ``sub`` claim — the canonical user id. */
function decodeUserIdFromToken(token: string | null): string | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1]!.replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const json = JSON.parse(atob(padded)) as { sub?: string };
    return typeof json.sub === 'string' ? json.sub : null;
  } catch {
    return null;
  }
}

/** True when the current user owns the given project. */
export function useIsProjectOwner(projectId: string | null | undefined): boolean {
  const accessToken = useAuthStore((s) => s.accessToken);
  const role = useAuthStore((s) => s.userRole);
  const me = decodeUserIdFromToken(accessToken);

  const { data } = useQuery<ProjectOwnerInfo>({
    queryKey: [KEY_IS_PROJECT_OWNER, projectId],
    queryFn: () => apiGet<ProjectOwnerInfo>(`/v1/projects/${projectId}`),
    enabled: Boolean(projectId) && Boolean(me),
    staleTime: 60_000,
  });

  if (role === 'admin') return true;
  if (!me || !data) return false;
  return data.owner_id === me;
}

/**
 * Per-folder grant counts so FolderCardGrid can show a lock badge on
 * cards that have any non-revoked grant. Returns ``{}`` for non-owners
 * (the listing endpoint 403s for them) so the lock icon stays
 * owner-only — non-owners only see the folders they're cleared for.
 */
export function useFolderPermissionCounts(
  projectId: string | null | undefined,
  enabled: boolean,
): Record<string, number> {
  const { data = [] } = useQuery<FolderPermissionRow[]>({
    queryKey: [KEY_FOLDER_PERMS, projectId],
    queryFn: () => listFolderPermissions(projectId as string),
    enabled: Boolean(projectId) && enabled,
    staleTime: 10_000,
  });
  const counts: Record<string, number> = {};
  for (const row of data) {
    // Bucket by ``scope_kind`` so the card-level lock badge shows the
    // total members cleared for that FOLDER (across sub-paths).
    counts[row.scope_kind] = (counts[row.scope_kind] || 0) + 1;
  }
  return counts;
}

interface ProjectLite {
  id: string;
  name: string;
}

/**
 * Lightweight id→name lookup over all projects. Shares the React Query
 * cache key (``['projects']``) used by BIMPage so opening a file in a
 * project other than the active one can still label the global project
 * context correctly (avoids a blank project name after the jump).
 */
export function useProjectsLite() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<ProjectLite[]>(),
    staleTime: 5 * 60_000,
  });
}
