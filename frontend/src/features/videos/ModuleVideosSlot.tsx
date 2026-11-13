// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Mounted once in the app shell. On a screen the catalogue links videos,
// courses or guides to, and unless the reader hid the hint, it draws the chip
// in the same render as the page, from the route counts alone. Only the
// popover (the catalogues, the player) is a lazy chunk, loaded on first open;
// everywhere else this renders nothing and loads nothing.

import { lazy, Suspense, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ChevronDown, GraduationCap, MonitorPlay } from 'lucide-react';
import { usePageHeaderSlot } from '@/shared/ui/pageHeaderSlot';
import { itemCountForRoute, useVideoHintsStore, videoCountForRoute, videoRouteFor } from './videoRoutes';

const loadPanel = () => import('./ModuleVideosPanel');
const ModuleVideosPanel = lazy(loadPanel);

function Chip({ route, inRow }: { route: string; inRow: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const items = itemCountForRoute(route);
  const count = videoCountForRoute(route) + items;
  const label =
    items > 0
      ? t('learn.for_this_step', { defaultValue: 'Learn this step' })
      : t('videos.for_this_step', { defaultValue: 'Videos for this step' });
  const Icon = items > 0 ? GraduationCap : MonitorPlay;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={boxRef} className={clsx('relative', inRow ? 'z-30' : 'z-30 ms-auto w-fit')} data-testid="module-videos">
      <button
        type="button"
        onClick={() => {
          setLoaded(true);
          setOpen((o) => !o);
        }}
        onPointerEnter={() => void loadPanel()}
        onFocus={() => void loadPanel()}
        aria-expanded={open}
        aria-controls={panelId}
        data-testid="module-videos-toggle"
        data-oe-button="secondary"
        className={clsx(
          // Same geometry as a secondary `Button` md: it shares the header row.
          'inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-lg border px-3 text-sm font-medium shadow-xs transition-colors',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60 focus-visible:ring-offset-1 active:scale-[0.98]',
          open
            ? 'border-oe-blue/50 bg-oe-blue/10 text-oe-blue-text'
            : 'border-border bg-surface-primary text-content-primary hover:bg-surface-secondary',
        )}
      >
        <Icon size={16} className="text-oe-blue-text" aria-hidden />
        {label}
        <span className="rounded-full bg-oe-blue/10 px-1.5 text-2xs font-semibold tabular-nums text-oe-blue-text">{count}</span>
        <ChevronDown size={14} className={clsx('text-content-tertiary transition-transform motion-reduce:transition-none', open && 'rotate-180')} aria-hidden />
      </button>
      {loaded && (
        <Suspense fallback={null}>
          <ModuleVideosPanel route={route} open={open} panelId={panelId} onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </div>
  );
}

export function ModuleVideosSlot() {
  const { pathname } = useLocation();
  const route = videoRouteFor(pathname);
  const hidden = useVideoHintsStore((s) => (route ? s.off || s.hidden.includes(route) : true));
  const slot = usePageHeaderSlot((s) => s.el);
  // Pages without a PageHeader get the chip on its own line, but only once it
  // is clear none is coming, so header pages never flash the old row.
  const [fallback, setFallback] = useState(false);
  useEffect(() => {
    setFallback(false);
    const id = window.setTimeout(() => setFallback(true), 800);
    return () => window.clearTimeout(id);
  }, [pathname]);
  if (!route || hidden) return null;
  if (slot) return createPortal(<Chip key={route} route={route} inRow />, slot);
  return fallback ? <div className="mb-3"><Chip key={route} route={route} inRow={false} /></div> : null;
}
