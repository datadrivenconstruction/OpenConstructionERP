// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DataPathsButton: the "Data paths" pill in a module header, sitting with the
// learning buttons (Cases, How it works). It is route-derived like
// ModuleCasesButton: it finds the backend module that owns the current page and
// renders nothing on a page no module owns. Undeclared modules still get the
// button; their drawer shows the links derived from the code.
//
// Light on purpose: the route map and the drawer load only when needed, so
// the button costs nothing in the entry chunk and nothing in unit tests that
// render a header without a router or a query client.

import { lazy, Suspense, useEffect, useState } from 'react';
import { useInRouterContext, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Waypoints } from 'lucide-react';

import { Button } from '../Button';

const DataPathsDrawer = lazy(() =>
  import('@/features/data-paths/DataPathsDrawer').then((m) => ({ default: m.DataPathsDrawer })),
);

type Resolver = (pathname: string) => string | null;
let resolverPromise: Promise<Resolver> | null = null;

function loadResolver(): Promise<Resolver> {
  resolverPromise ??= import('@/features/data-paths/moduleMeta').then((m) => m.moduleForPath);
  return resolverPromise;
}

export interface DataPathsButtonProps {
  /** Backend module name; derived from the route when omitted. */
  module?: string;
  className?: string;
}

export function DataPathsButton(props: DataPathsButtonProps) {
  // Outside a router (isolated component tests) there is no page to describe.
  if (!useInRouterContext()) return null;
  return <RoutedDataPathsButton {...props} />;
}

function RoutedDataPathsButton({ module, className }: DataPathsButtonProps) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [derived, setDerived] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (module) return undefined;
    let alive = true;
    loadResolver()
      .then((resolve) => {
        if (alive) setDerived(resolve(pathname));
      })
      .catch(() => {
        if (alive) setDerived(null);
      });
    return () => {
      alive = false;
    };
  }, [module, pathname]);

  const target = module ?? derived;
  if (!target || pathname.startsWith('/data-paths')) return null;

  const label = t('data_paths.button', { defaultValue: 'Data paths' });
  const aria = t('data_paths.button_aria', { defaultValue: "Where this module's data comes from and where it goes" });

  return (
    <>
      <Button
        variant="secondary"
        onClick={() => setOpen(true)}
        data-testid="data-paths-button"
        aria-label={aria}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={aria}
        className={className}
        icon={<Waypoints size={16} strokeWidth={2} className="text-oe-blue" />}
      >
        <span className="hidden sm:inline">{label}</span>
      </Button>
      {open && (
        <Suspense fallback={null}>
          <DataPathsDrawer module={target} open={open} onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  );
}
