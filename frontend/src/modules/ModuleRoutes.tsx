// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Dynamic route renderer for modules.
 *
 * Renders `<Route>` elements for every enabled module.  Each module page is
 * loaded via React.lazy — so it only downloads when the user navigates there.
 */

import { Suspense } from 'react';
import { Route } from 'react-router-dom';
import { MODULE_REGISTRY } from './_registry';
import { useModuleStore } from '@/stores/useModuleStore';
import { useAuthStore } from '@/stores/useAuthStore';
import type { ModuleManifest, ModuleRoute } from './_types';
import { Loader2 } from 'lucide-react';

/* ── Fallback spinner shown while a module chunk loads ─────────────── */

function ModuleLoading() {
  return (
    <div className="flex h-64 items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-oe-blue" />
    </div>
  );
}

/* ── Props — we receive the page-wrapper component from App.tsx ────── */

interface ModuleRoutesProps {
  /** The `P` wrapper from App.tsx that adds RequireAuth + AppLayout */
  Wrapper: React.ComponentType<{ title: string; children: React.ReactNode }>;
}

/**
 * Returns an array of `<Route>` elements for all enabled module routes.
 * Must be spread inside a `<Routes>` block.
 */
/**
 * The routes to mount: an enabled module's own, a disabled one's `offRoutes`.
 * While the account's module state is still on its way (`pending`), a module
 * that is off only locally may be on for the account, so its real routes are
 * mounted behind a spinner instead of answering 404 or the setup page; the
 * list is rebuilt the moment the answer lands.
 */
export function selectModuleRoutes(
  modules: readonly ModuleManifest[],
  isModuleEnabled: (id: string) => boolean,
  pending: boolean,
): { route: ModuleRoute; waiting: boolean }[] {
  return modules.flatMap((m) => {
    if (isModuleEnabled(m.id)) return m.routes.map((route) => ({ route, waiting: false }));
    if (pending) return m.routes.map((route) => ({ route, waiting: true }));
    return (m.offRoutes ?? []).map((route) => ({ route, waiting: false }));
  });
}

export function useModuleRouteElements({ Wrapper }: ModuleRoutesProps) {
  const { isModuleEnabled } = useModuleStore();
  const serverLoaded = useModuleStore((s) => s.serverLoaded);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  return selectModuleRoutes(MODULE_REGISTRY, isModuleEnabled, isAuthenticated && !serverLoaded)
    .map(({ route, waiting }) => (
      <Route
        key={route.path}
        path={route.path}
        element={
          <Wrapper title={route.title}>
            {waiting ? (
              <ModuleLoading />
            ) : (
              <Suspense fallback={<ModuleLoading />}>
                <route.component />
              </Suspense>
            )}
          </Wrapper>
        }
      />
    ));
}
