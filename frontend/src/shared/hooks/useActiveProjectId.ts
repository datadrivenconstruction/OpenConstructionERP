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
