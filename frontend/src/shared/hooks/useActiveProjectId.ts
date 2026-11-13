// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Single source of truth for "which project is the user looking at".
 *
 * The app has two route families - flat (`/finance`) and project-nested
 * (`/projects/:projectId/finance`) - plus a global project switcher in the top
 * bar backed by `useProjectContextStore`. Pages used to each re-derive the
 * active project their own way, and a few captured it once at mount, so
 * switching the top-bar picker changed some tabs but not others.
 *
 * This hook makes the rule uniform and reactive: a `:projectId` in the URL
 * wins (an explicit deep-link), otherwise the global switcher decides. Because
 * it subscribes to the store, every component that uses it re-renders the
 * moment the user switches project - on every tab, not just one.
 *
 * It does NOT apply a "first project" fallback: that needs the projects list,
 * which not every caller has. Pages that want it keep doing
 * `useActiveProjectId() || projects[0]?.id` at the call site.
 */

import { useParams } from 'react-router-dom';

import { useProjectContextStore } from '@/stores/useProjectContextStore';

export function useActiveProjectId(): string {
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  return routeProjectId || activeProjectId || '';
}

/**
 * `useActiveProjectId` for pages that fall back to the first project: a stored
 * selection the loaded project list no longer contains (deleted or archived in
 * another session) is skipped, so the page never queries an id the server
 * answers with "Project not found". Until the list has loaded the stored id is
 * trusted, as before.
 */
export function useResolvedProjectId(projects: ReadonlyArray<{ id: string }>, loaded: boolean): string {
  const id = useActiveProjectId();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const stale = !routeProjectId && !!id && loaded && !projects.some((p) => p.id === id);
  return (stale ? '' : id) || projects[0]?.id || '';
}
