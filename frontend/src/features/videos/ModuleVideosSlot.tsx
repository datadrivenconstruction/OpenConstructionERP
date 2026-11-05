// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Mounted once in the app shell. On a screen the catalogue links videos,
// courses or guides to, and unless the reader hid the hint, it draws the chip
// in the same render as the page, from the route counts alone. Only the
// popover (the catalogues, the player) is a lazy chunk, loaded on first open;
// everywhere else this renders nothing and loads nothing.

import { lazy, Suspense, useEffect, useId, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ChevronDown, GraduationCap, MonitorPlay } from 'lucide-react';
import { itemCountForRoute, useVideoHintsStore, videoCountForRoute, videoRouteFor } from './videoRoutes';

const loadPanel = () => import('./ModuleVideosPanel');
const ModuleVideosPanel = lazy(loadPanel);

function Chip({ route }: { route: string }) {
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
    <div className="relative z-30 mb-2 flex justify-end" data-testid="module-videos">
      <div ref={boxRef} className="relative">
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
          className={clsx(
            'inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium shadow-sm transition-colors',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
            open
              ? 'border-oe-blue/50 bg-oe-blue/10 text-oe-blue'
              : 'border-border-light bg-surface-primary/90 text-content-secondary backdrop-blur hover:border-oe-blue/40 hover:text-oe-blue',
          )}
        >
          <Icon size={13} aria-hidden />
          {label}
          <span className="rounded-full bg-oe-blue/10 px-1.5 text-2xs font-semibold tabular-nums text-oe-blue">{count}</span>
          <ChevronDown size={12} className={clsx('transition-transform motion-reduce:transition-none', open && 'rotate-180')} aria-hidden />
        </button>
        {loaded && (
          <Suspense fallback={null}>
            <ModuleVideosPanel route={route} open={open} panelId={panelId} onClose={() => setOpen(false)} />
          </Suspense>
        )}
      </div>
    </div>
  );
}

export function ModuleVideosSlot() {
  const { pathname } = useLocation();
  const route = videoRouteFor(pathname);
  const hidden = useVideoHintsStore((s) => (route ? s.off || s.hidden.includes(route) : true));
  if (!route || hidden) return null;
  return <Chip key={route} route={route} />;
}
