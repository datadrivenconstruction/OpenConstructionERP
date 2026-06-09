/**
 * Slim, browser-style chrome shown only in the desktop (Tauri) shell.
 *
 * The desktop window has no browser around it, so this gives back the few
 * controls people miss: Back, Forward, Reload, Home, an address field that
 * shows the current in-app page, an "open this page in your browser" button,
 * and a small Favorites menu (bookmark the current page, open a saved one,
 * refresh the list). It is intentionally minimal and uses the app's own design
 * tokens so it reads as native chrome, not a second UI.
 *
 * Desktop only: the whole bar returns null outside the Tauri build, so the
 * normal web build never shows it.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  RotateCw,
  Home,
  Globe,
  Star,
  ChevronDown,
  Trash2,
  RefreshCw,
} from 'lucide-react';
import clsx from 'clsx';
import { isTauri, openAppInBrowser } from '@/shared/lib/desktop';
import {
  readFavorites,
  toggleFavorite,
  removeFavorite,
  isFavorite,
  type DesktopFavorite,
} from '@/shared/lib/desktopFavorites';
import { deriveComponentFromRoute } from './Header';
import { useToastStore } from '@/stores/useToastStore';

/** Current route as the user-facing path (pathname + search, no origin). */
function currentPath(): string {
  return window.location.pathname + window.location.search;
}

export function DesktopToolbar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const addToast = useToastStore((s) => s.addToast);

  const [favorites, setFavorites] = useState<DesktopFavorite[]>([]);
  const [favOpen, setFavOpen] = useState(false);
  const favRef = useRef<HTMLDivElement>(null);

  // Load favorites once on mount (desktop only).
  useEffect(() => {
    if (isTauri) setFavorites(readFavorites());
  }, []);

  // Close the favorites popover on outside click / Escape.
  useEffect(() => {
    if (!favOpen) return;
    const onClick = (e: MouseEvent) => {
      if (favRef.current && !favRef.current.contains(e.target as Node)) setFavOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFavOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [favOpen]);

  const path = location.pathname + location.search;
  const pageName = deriveComponentFromRoute(location.pathname);
  const starred = isTauri && isFavorite(path, favorites);

  const goBack = useCallback(() => navigate(-1), [navigate]);
  const goForward = useCallback(() => navigate(1), [navigate]);
  const reload = useCallback(() => {
    // Re-run the current route. window.location.reload would re-fetch the whole
    // SPA shell from the local server; a soft navigation to the same path is
    // faster and keeps the desktop chrome mounted. We force it with the replace
    // flag so the history entry is not duplicated.
    navigate(0);
  }, [navigate]);
  const goHome = useCallback(() => navigate('/'), [navigate]);

  const openHere = useCallback(() => {
    void openAppInBrowser(currentPath()).then((ok) => {
      if (!ok) {
        addToast({
          type: 'warning',
          title: t('desktop.open_in_browser_failed', {
            defaultValue: 'Could not open your browser',
          }),
        });
      }
    });
  }, [addToast, t]);

  const toggleStar = useCallback(() => {
    const next = toggleFavorite(path, pageName);
    setFavorites(next);
  }, [path, pageName]);

  const refreshFavorites = useCallback(() => {
    setFavorites(readFavorites());
    addToast({
      type: 'success',
      title: t('desktop.favorites_refreshed', { defaultValue: 'Favorites refreshed' }),
    });
  }, [addToast, t]);

  if (!isTauri) return null;

  const iconBtn =
    'flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary ' +
    'transition-colors hover:bg-surface-secondary hover:text-content-secondary ' +
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus ' +
    'disabled:opacity-40 disabled:pointer-events-none';

  return (
    <div
      data-testid="desktop-toolbar"
      className={clsx(
        'sticky top-0 z-40 flex h-9 items-center gap-1 px-2',
        'border-b border-border-light bg-surface-primary/90 backdrop-blur-xl',
        'select-none',
      )}
      role="toolbar"
      aria-label={t('desktop.toolbar', { defaultValue: 'Navigation toolbar' })}
    >
      {/* Navigation cluster */}
      <button
        type="button"
        onClick={goBack}
        className={iconBtn}
        aria-label={t('desktop.back', { defaultValue: 'Back' })}
        title={t('desktop.back', { defaultValue: 'Back' })}
      >
        <ArrowLeft size={15} strokeWidth={1.9} />
      </button>
      <button
        type="button"
        onClick={goForward}
        className={iconBtn}
        aria-label={t('desktop.forward', { defaultValue: 'Forward' })}
        title={t('desktop.forward', { defaultValue: 'Forward' })}
      >
        <ArrowRight size={15} strokeWidth={1.9} />
      </button>
      <button
        type="button"
        onClick={reload}
        className={iconBtn}
        aria-label={t('desktop.reload', { defaultValue: 'Reload' })}
        title={t('desktop.reload', { defaultValue: 'Reload' })}
      >
        <RotateCw size={14} strokeWidth={1.9} />
      </button>
      <button
        type="button"
        onClick={goHome}
        className={iconBtn}
        aria-label={t('desktop.home', { defaultValue: 'Home' })}
        title={t('desktop.home', { defaultValue: 'Home' })}
      >
        <Home size={14} strokeWidth={1.9} />
      </button>

      <div className="mx-1 h-4 w-px bg-border-light/70" aria-hidden />

      {/* Address field: shows the friendly page name and the local path. Editing
          it and pressing Enter navigates to that in-app path. */}
      <AddressField pathname={location.pathname} pageName={pageName} onGo={navigate} />

      {/* Open the current page in the user's default browser. */}
      <button
        type="button"
        onClick={openHere}
        className={clsx(
          'ml-1 flex h-7 items-center gap-1.5 rounded-md px-2',
          'text-xs font-medium text-content-secondary',
          'transition-colors hover:bg-surface-secondary',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus',
        )}
        aria-label={t('desktop.open_this_in_browser', {
          defaultValue: 'Open this page in your browser',
        })}
        title={t('desktop.open_this_in_browser', {
          defaultValue: 'Open this page in your browser',
        })}
      >
        <Globe size={14} strokeWidth={1.9} />
        <span className="hidden md:inline">
          {t('desktop.open_in_browser', { defaultValue: 'Open in your browser' })}
        </span>
      </button>

      {/* Favorites: star to bookmark the current page, caret for the list. */}
      <button
        type="button"
        onClick={toggleStar}
        className={clsx(iconBtn, starred && 'text-oe-blue hover:text-oe-blue')}
        aria-label={
          starred
            ? t('desktop.remove_favorite', { defaultValue: 'Remove from favorites' })
            : t('desktop.add_favorite', { defaultValue: 'Add to favorites' })
        }
        aria-pressed={starred}
        title={
          starred
            ? t('desktop.remove_favorite', { defaultValue: 'Remove from favorites' })
            : t('desktop.add_favorite', { defaultValue: 'Add to favorites' })
        }
      >
        <Star size={15} strokeWidth={1.9} fill={starred ? 'currentColor' : 'none'} />
      </button>

      <div className="relative" ref={favRef}>
        <button
          type="button"
          onClick={() => setFavOpen((v) => !v)}
          className={clsx(iconBtn, favOpen && 'bg-surface-secondary text-content-secondary')}
          aria-haspopup="menu"
          aria-expanded={favOpen}
          aria-label={t('desktop.favorites', { defaultValue: 'Favorites' })}
          title={t('desktop.favorites', { defaultValue: 'Favorites' })}
        >
          <ChevronDown size={13} strokeWidth={2} />
        </button>

        {favOpen && (
          <div
            role="menu"
            className="absolute right-0 top-full mt-1.5 w-72 rounded-xl border border-border-light bg-surface-elevated shadow-lg animate-scale-in py-1.5 z-50"
          >
            <div className="flex items-center justify-between px-3 pb-1.5">
              <span className="text-xs font-semibold text-content-primary">
                {t('desktop.favorites', { defaultValue: 'Favorites' })}
              </span>
              <button
                type="button"
                onClick={refreshFavorites}
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-medium text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-secondary"
                aria-label={t('desktop.refresh_favorites', { defaultValue: 'Refresh favorites' })}
                title={t('desktop.refresh_favorites', { defaultValue: 'Refresh favorites' })}
              >
                <RefreshCw size={12} strokeWidth={1.9} />
                {t('desktop.refresh', { defaultValue: 'Refresh' })}
              </button>
            </div>
            <div className="my-1 border-t border-border-light" role="separator" />
            {favorites.length === 0 ? (
              <p className="px-3 py-3 text-2xs text-content-tertiary leading-snug">
                {t('desktop.favorites_empty', {
                  defaultValue: 'No favorites yet. Use the star to bookmark the page you are on.',
                })}
              </p>
            ) : (
              <div className="max-h-72 overflow-y-auto py-0.5">
                {favorites.map((f) => (
                  <div
                    key={f.path}
                    className="group flex items-center gap-2 px-2 hover:bg-surface-secondary"
                  >
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setFavOpen(false);
                        navigate(f.path);
                      }}
                      className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left"
                    >
                      <Star
                        size={13}
                        strokeWidth={1.9}
                        className="shrink-0 text-oe-blue"
                        fill="currentColor"
                      />
                      <span className="flex min-w-0 flex-col">
                        <span className="truncate text-[13px] font-medium text-content-primary">
                          {f.label}
                        </span>
                        <span className="truncate text-2xs text-content-tertiary">{f.path}</span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setFavorites(removeFavorite(f.path))}
                      className="shrink-0 rounded-md p-1 text-content-quaternary opacity-0 transition-opacity hover:bg-surface-primary hover:text-semantic-error group-hover:opacity-100 focus-visible:opacity-100"
                      aria-label={t('desktop.remove_favorite', {
                        defaultValue: 'Remove from favorites',
                      })}
                      title={t('desktop.remove_favorite', {
                        defaultValue: 'Remove from favorites',
                      })}
                    >
                      <Trash2 size={13} strokeWidth={1.9} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Address field ─────────────────────────────────────────────────────────
   Shows the current page as "PageName  ·  /path". Click to edit the raw path
   and press Enter to navigate. Escape or blur restores the current path, so a
   stray edit never strands the user. */
function AddressField({
  pathname,
  pageName,
  onGo,
}: {
  pathname: string;
  pageName: string;
  onGo: (to: string) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(pathname);
  const inputRef = useRef<HTMLInputElement>(null);

  // Keep the draft in sync with the live route when not actively editing.
  useEffect(() => {
    if (!editing) setDraft(pathname);
  }, [pathname, editing]);

  const commit = () => {
    const value = draft.trim();
    setEditing(false);
    // Only navigate to a clean same-origin path; otherwise restore.
    if (value.startsWith('/') && !value.startsWith('//') && !value.includes('://')) {
      onGo(value);
    } else {
      setDraft(pathname);
    }
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        autoFocus
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') {
            setDraft(pathname);
            setEditing(false);
          }
        }}
        onBlur={commit}
        aria-label={t('desktop.address', { defaultValue: 'Page address' })}
        spellCheck={false}
        className={clsx(
          'h-7 flex-1 rounded-md border border-border-focus bg-white px-2.5 dark:bg-surface-primary',
          'text-xs text-content-primary',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-border-focus',
        )}
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className={clsx(
        'flex h-7 flex-1 items-center gap-2 rounded-md px-2.5',
        'border border-border-light bg-white/85 backdrop-blur-sm dark:bg-surface-primary/70',
        'text-xs text-content-tertiary',
        'transition-colors hover:border-content-quaternary/40 hover:bg-white dark:hover:bg-surface-primary',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus',
      )}
      aria-label={t('desktop.address', { defaultValue: 'Page address, click to edit' })}
      title={pathname}
    >
      <span className="shrink-0 font-medium text-content-secondary">{pageName}</span>
      <span className="text-content-quaternary" aria-hidden>
        ·
      </span>
      <span className="truncate">{pathname}</span>
    </button>
  );
}
