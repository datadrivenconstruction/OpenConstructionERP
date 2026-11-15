// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which menu rows the open demo covers. The demo session store owns the data
 * (`useDemoSessionStore.modules`, from `demoModuleRoutes`); the sidebar only
 * asks this hook and filters.
 */

import { useQuery } from '@tanstack/react-query';
import { apiGet } from './api';
import { ASSISTANT_GROUP_ID, LEARN_GROUP_ID, navGroups } from '@/app/layout/navCatalog';
import { demoModuleRoutes, type DemoProfile } from './demoProfiles';
import { useDemoSessionStore } from '@/stores/useDemoSessionStore';

/** Rows every demo keeps, whatever its cards cover: the way home, the project
 *  list, the assistant and the Learn card. */
export const DEMO_ALWAYS_ROUTES: ReadonlySet<string> = new Set([
  '/',
  '/projects',
  ...navGroups
    .filter((group) => group.id === LEARN_GROUP_ID || group.id === ASSISTANT_GROUP_ID)
    .flatMap((group) => group.items.map((item) => item.to)),
]);

/** The module list of a demo, or null for "the whole menu". */
export function demoModulesFor(profile: DemoProfile | null | undefined): readonly string[] | null {
  if (!profile?.groups) return null;
  return demoModuleRoutes(profile, navGroups);
}

/** The menu groups a demo opens with at least one row, and how many the
 *  whole menu has; Learn and the assistant are not counted. */
export function demoSectionCount(profile: DemoProfile): { shown: number; total: number } {
  const groups = navGroups.filter((group) => group.id !== LEARN_GROUP_ID && group.id !== ASSISTANT_GROUP_ID);
  const modules = demoModulesFor(profile);
  if (!modules) return { shown: groups.length, total: groups.length };
  const set = new Set(modules);
  const shown = groups.filter((group) =>
    group.items.some((item) => !DEMO_ALWAYS_ROUTES.has(item.to.split('?')[0]!) && isRowInDemo(item, set)),
  ).length;
  return { shown, total: groups.length };
}

/** Whether a menu row belongs to the demo: its route, its path without the
 *  query, or its module key is on the list. */
export function isRowInDemo(
  item: { to: string; moduleKey?: string },
  modules: ReadonlySet<string>,
): boolean {
  const path = item.to.split('?')[0]!;
  return (
    DEMO_ALWAYS_ROUTES.has(path) ||
    modules.has(item.to) ||
    modules.has(path) ||
    (item.moduleKey !== undefined && modules.has(item.moduleKey))
  );
}

/** Whether this server runs the public demo. */
export function useDemoServer(): boolean {
  const { data: sys } = useQuery<{ demo_mode?: boolean }>({
    queryKey: ['system-status'],
    queryFn: () => apiGet<{ demo_mode?: boolean }>('/system/status'),
    retry: false,
    staleTime: Infinity,
  });
  return sys?.demo_mode === true;
}

/** The open demo's module list, or null outside a demo and for a demo that
 *  shows the whole platform. */
export function useDemoModules(): readonly string[] | null {
  const { data: sys } = useQuery<{ demo_mode?: boolean }>({
    queryKey: ['system-status'],
    queryFn: () => apiGet<{ demo_mode?: boolean }>('/system/status'),
    retry: false,
    staleTime: Infinity,
  });
  const groups = useDemoSessionStore((s) => s.groups);
  const modules = useDemoSessionStore((s) => s.modules);
  const lifted = useDemoSessionStore((s) => s.restoreMode !== null);
  return sys?.demo_mode === true && groups && !lifted ? modules : null;
}
