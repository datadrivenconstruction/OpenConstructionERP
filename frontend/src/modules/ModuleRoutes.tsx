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
export function useModuleRouteElements({ Wrapper }: ModuleRoutesProps) {
  const { isModuleEnabled } = useModuleStore();

  return MODULE_REGISTRY
    .filter((m) => isModuleEnabled(m.id))
    .flatMap((m) => m.routes)
    .map((route) => (
      <Route
        key={route.path}
        path={route.path}
        element={
          <Wrapper title={route.title}>
            <Suspense fallback={<ModuleLoading />}>
              <route.component />
            </Suspense>
          </Wrapper>
        }
      />
    ));
}
