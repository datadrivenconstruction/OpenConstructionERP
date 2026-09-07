// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Geo Hub — all-projects global map.
 *
 * Lazy-loaded; this is the first module page so Suspense is the only
 * boundary needed.
 *
 * Chrome layout:
 *
 * * Top toolbar with title + scope segmented control + live counter.
 * * Full-width Cesium canvas — no fixed side rail.
 * * Floating overlay panel (top-left) listing anchored projects,
 *   self-sized to its content (caps at 60vh) and collapsible to a slim
 *   pill so the user can reveal the full globe with one click.
 * * HUD overlay (cursor lat/lon, altitude, scale bar, north arrow).
 * * Glass-panel empty state when no projects are anchored anywhere — so
 *   the user is never left staring at a blank globe wondering what to
 *   do next.
 * * Visible error banner when the anchored-projects endpoint fails so
 *   the user understands the page isn't broken — only the data fetch.
 *
 * No tileset sidebar in global mode — there is no project-scoped
 * map config to load.
 */

import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import {
  Globe2,
  MapPin,
  ArrowUpRight,
  AlertTriangle,
  RefreshCw,
  Loader2,
  Info,
  ServerCrash,
  ChevronLeft,
  ChevronRight,
  Layers,
  X,
} from 'lucide-react';

import { ApiError } from '@/shared/lib/api';
import {
  BetaBanner,
  DismissibleInfo,
  ModuleGuideButton,
  ModuleHelpButton,
} from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import { AddressAutocomplete } from './AddressAutocomplete';
import { bulkAutoAnchorFromAddress, fetchAnchoredProjects } from './api';
import type {
  GeoCameraState,
  GeoCursorCoords,
  GeoSceneMode,
  GeoSearchPin,
} from './CesiumViewer';
import { geoHubGuide } from './geoHubGuide';
import { GeoModePicker } from './GeoModePicker';
import { GeoOverlayHud } from './GeoOverlayHud';
import { GeoSceneModePicker } from './GeoSceneModePicker';
import { OverlayLayer } from './OverlayLayer';
import { OverlayPanel, type OverlayEditMode } from './OverlayPanel';
import { OverlaySidebar } from './OverlaySidebar';
import type { AnchoredProject, GeoPinBundle } from './types';
import { BasemapPicker } from './BasemapPicker';
import { EngineModePicker, type GeoEngine } from './EngineModePicker';
import { readBasemap, BASEMAP_LS_KEY, type BasemapId } from './mapStyles';

// Persisted scene-mode preference — restored synchronously at mount so
// the initial Cesium paint already matches the user's choice (no
// flash-of-3D when they previously selected 2D).
const SCENE_MODE_LS_KEY = 'geoHub.sceneMode';

function readSceneMode(): GeoSceneMode {
  if (typeof window === 'undefined') return '3d';
  try {
    const v = window.localStorage.getItem(SCENE_MODE_LS_KEY);
    if (v === '2d' || v === '3d' || v === 'columbus') return v;
  } catch {
    /* localStorage disabled / quota — fall through to default */
  }
  return '3d';
}

// Persisted engine preference - which renderer backs the canvas. Defaults
// to the light, instant 2D map so the page opens fast (and works offline);
// the user can switch to the 3D globe and that choice is remembered.
const ENGINE_LS_KEY = 'geoHub.engine';

function readEngine(): GeoEngine {
  if (typeof window === 'undefined') return '2d';
  try {
    const v = window.localStorage.getItem(ENGINE_LS_KEY);
    if (v === '2d' || v === '3d') return v;
  } catch {
    /* localStorage disabled / quota — fall through to default */
  }
  return '2d';
}

const CesiumViewer = lazy(() =>
  import('./CesiumViewer').then((m) => ({ default: m.CesiumViewer })),
);

// MapLibre is lazy-loaded too: keeping it off the page chunk means the
// ~800 KB MapLibre runtime only streams in when the 2D engine is active.
const MapLibreViewer = lazy(() =>
  import('./MapLibreViewer').then((m) => ({ default: m.MapLibreViewer })),
);

/**
 * Glass-panel empty state for "no anchored projects anywhere".
 *
 * Distinct from ``GeoEmptyState`` (which is project-scoped). Lives in
 * this file because it's only used by the global view and needs to
 * compose with the left rail of the global layout.
 */
function GlobalNoProjectsEmpty({
  onAnchored,
}: {
  onAnchored?: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [isBulking, setIsBulking] = useState(false);

  async function bulkAnchor() {
    if (isBulking) return;
    setIsBulking(true);
    try {
      const summary = await bulkAutoAnchorFromAddress();
      if (summary.succeeded === 0 && summary.skipped === 0 && summary.failed === 0) {
        addToast({
          type: 'info',
          title: t('geo_hub.empty.bulk_no_projects', {
            defaultValue: 'No projects with addresses to anchor',
          }),
          message: t('geo_hub.empty.bulk_no_projects_hint', {
            defaultValue:
              'Add an address (country required) to a project, then try again.',
          }),
        });
      } else if (summary.succeeded > 0) {
        addToast({
          type: 'success',
          title: t('geo_hub.empty.bulk_success_title', {
            defaultValue: '{{count}} projects anchored',
            count: summary.succeeded,
          }),
          message: t('geo_hub.empty.bulk_success_message', {
            defaultValue:
              'Skipped {{skipped}}, failed {{failed}}. Refreshing the map.',
            skipped: summary.skipped,
            failed: summary.failed,
          }),
        });
      } else {
        addToast({
          type: 'warning',
          title: t('geo_hub.empty.bulk_no_success_title', {
            defaultValue: 'No projects could be auto-anchored',
          }),
          message: t('geo_hub.empty.bulk_no_success_message', {
            defaultValue:
              'Skipped {{skipped}}, failed {{failed}}. Add a country to your project addresses and try again.',
            skipped: summary.skipped,
            failed: summary.failed,
          }),
        });
      }
      onAnchored?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        addToast({
          type: 'error',
          title: t('geo_hub.empty.bulk_auth_required', {
            defaultValue: 'Please log in to auto-anchor your projects',
          }),
        });
      } else {
        addToast({
          type: 'error',
          title: t('geo_hub.empty.bulk_error', {
            defaultValue: 'Bulk auto-anchor failed',
          }),
        });
      }
    } finally {
      setIsBulking(false);
    }
  }

  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-6">
      <div
        className={[
          'pointer-events-auto relative w-full max-w-md overflow-hidden',
          'rounded-xl border border-white/10 bg-slate-900/70 p-6 text-slate-100',
          'shadow-xl backdrop-blur-md ring-1 ring-white/5',
        ].join(' ')}
        role="status"
      >
        <div
          aria-hidden
          className={[
            'pointer-events-none absolute -inset-px rounded-xl bg-gradient-to-br',
            'from-emerald-500/30 to-teal-500/20 opacity-60 blur-2xl',
            'ring-1 ring-emerald-400/20',
          ].join(' ')}
        />
        <div className="relative">
          <div
            className={[
              'mb-4 inline-flex h-10 w-10 items-center justify-center rounded-md',
              'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-400/30',
            ].join(' ')}
          >
            <MapPin size={18} strokeWidth={2} />
          </div>
          <h3 className="text-base font-semibold text-white">
            {t('geo_hub.empty.global_no_projects_title', {
              defaultValue: 'No anchored projects yet',
            })}
          </h3>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-300">
            {t('geo_hub.empty.global_no_projects_description_v2', {
              defaultValue:
                'If your projects have addresses we can place them on the globe automatically. Otherwise open a project and anchor it manually.',
            })}
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={bulkAnchor}
              disabled={isBulking}
              data-testid="geo-empty-bulk-anchor"
              className={[
                'inline-flex items-center gap-1.5 rounded-md',
                'bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-white',
                'shadow-sm transition hover:bg-emerald-400',
                'disabled:cursor-wait disabled:opacity-70',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/70',
              ].join(' ')}
            >
              {isBulking ? (
                <Loader2 size={13} strokeWidth={2.25} className="animate-spin" />
              ) : (
                <MapPin size={13} strokeWidth={2.25} />
              )}
              {t('geo_hub.empty.bulk_cta', {
                defaultValue: 'Auto-anchor all my projects',
              })}
            </button>
            <Link
              to="/projects"
              className={[
                'inline-flex items-center gap-1.5 rounded-md',
                'border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-semibold text-white',
                'shadow-sm transition hover:bg-white/10',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60',
              ].join(' ')}
            >
              {t('geo_hub.empty.global_no_projects_manual_cta', {
                defaultValue: 'Anchor a project manually',
              })}
              <ArrowUpRight size={13} strokeWidth={2.25} />
            </Link>
            {/* Secondary path for users who live in PropDev — anchoring
                a development surfaces it here too via the same map config. */}
            <Link
              to="/property-dev"
              className={[
                'inline-flex items-center gap-1.5 rounded-md',
                'border border-white/10 px-3 py-1.5 text-xs font-medium text-slate-200',
                'transition hover:bg-white/5',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60',
              ].join(' ')}
            >
              {t('geo_hub.empty.global_no_projects_propdev_cta', {
                defaultValue: 'Anchor from Property Developments',
              })}
              <ArrowUpRight size={13} strokeWidth={2.25} />
            </Link>
          </div>
          <p className="mt-3 text-2xs text-slate-400">
            {t('geo_hub.empty.bulk_attribution', {
              defaultValue:
                'Auto-anchor uses OpenStreetMap Nominatim (1 req/sec, cached 30 days).',
            })}
          </p>
        </div>
      </div>
    </div>
  );
}

// Persisted across reloads so users who collapse the panel stay
// uncovered on next visit. Versioned (`v1`) so a future incompatible
// rename never resurrects with stale boolean semantics.
const PANEL_COLLAPSED_LS_KEY = 'oe.geo_hub.global_panel_collapsed.v1';

function readPanelCollapsed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(PANEL_COLLAPSED_LS_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * Floating overlay panel — lists every anchored project with coords.
 * Self-sized vertical height (caps inner scroller at 60vh) so it never
 * spans the full canvas. Collapses to a slim pill on click, persisted
 * to localStorage. Click ``Focus`` to fly the viewer's camera;
 * ``Open`` deep links into the project-scoped map.
 *
 * Anchored to ``top-3 left-3`` over the Cesium canvas; the page
 * promotes the canvas to full width when this panel is overlay-mounted.
 *
 * Status rendering covers loading, error and empty cases so the user
 * always knows why the panel is showing what it is.
 */
function AnchoredProjectsOverlay({
  projects,
  isLoading,
  isError,
  onRetry,
  focusedProjectId,
  onFocus,
  collapsed,
  onToggleCollapsed,
}: {
  projects: AnchoredProject[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  focusedProjectId: string | null;
  onFocus: (project: AnchoredProject) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const { t } = useTranslation();

  // Collapsed → slim pill that shows just the count + an expand chevron.
  // Drops the panel chrome entirely so the map below is fully visible.
  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggleCollapsed}
        className={[
          'absolute top-3 left-3 z-20 inline-flex items-center gap-2',
          'rounded-full border border-white/15 bg-slate-900/85 px-3 py-1.5',
          'text-xs font-medium text-white shadow-lg shadow-black/20 backdrop-blur-md',
          'ring-1 ring-white/5 transition hover:bg-slate-800/90',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400',
        ].join(' ')}
        aria-expanded={false}
        aria-label={t('geo_hub.rail.expand', {
          defaultValue: 'Show anchored projects',
        })}
        title={t('geo_hub.rail.expand', {
          defaultValue: 'Show anchored projects',
        })}
      >
        <Layers size={13} strokeWidth={2} className="text-emerald-300" />
        <span className="tabular-nums">
          {isLoading ? '…' : isError ? '!' : projects.length}
        </span>
        <ChevronRight size={13} strokeWidth={2.25} className="text-white/70" />
      </button>
    );
  }

  return (
    <aside
      className={[
        // Floating overlay — never claims the full map height.
        'absolute top-3 left-3 z-20 flex w-72 max-w-[calc(100vw-1.5rem)] flex-col',
        'rounded-xl border border-white/15 bg-white/95 dark:bg-slate-900/90',
        'shadow-lg shadow-black/20 ring-1 ring-black/5 backdrop-blur-md',
        // Hide on phone-width so it doesn't cover the whole map; users
        // get the collapsed pill instead (rendered when toggled).
        'hidden md:flex',
      ].join(' ')}
      aria-label={t('geo_hub.rail.aria', {
        defaultValue: 'Anchored projects',
      })}
      data-testid="geo-tour-anchored-rail"
    >
      <div className="flex items-center justify-between gap-2 border-b border-black/5 px-3 py-2.5 dark:border-white/10">
        <div className="min-w-0">
          <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-content-secondary">
            {t('geo_hub.rail.title', { defaultValue: 'Anchored projects' })}
          </h2>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {isLoading
              ? t('geo_hub.rail.counter_loading', { defaultValue: 'Loading…' })
              : isError
                ? t('geo_hub.rail.counter_error', {
                    defaultValue: 'Failed to load',
                  })
                : t('geo_hub.rail.counter', {
                    defaultValue: '{{count}} on the map',
                    count: projects.length,
                  })}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {isError && (
            <button
              type="button"
              onClick={onRetry}
              className={[
                'inline-flex items-center gap-1 rounded-md border border-border px-2 py-1',
                'text-2xs font-medium text-content-secondary',
                'hover:bg-surface-secondary hover:text-content-primary',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
              ].join(' ')}
              aria-label={t('common.retry', { defaultValue: 'Retry' })}
            >
              <RefreshCw size={12} strokeWidth={2} />
              {t('common.retry', { defaultValue: 'Retry' })}
            </button>
          )}
          <button
            type="button"
            onClick={onToggleCollapsed}
            className={[
              'inline-flex h-7 w-7 items-center justify-center rounded-md',
              'text-content-tertiary hover:bg-surface-secondary hover:text-content-primary',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
            ].join(' ')}
            aria-expanded={true}
            aria-label={t('geo_hub.rail.collapse', {
              defaultValue: 'Hide anchored projects',
            })}
            title={t('geo_hub.rail.collapse', {
              defaultValue: 'Hide anchored projects',
            })}
          >
            <ChevronLeft size={14} strokeWidth={2} />
          </button>
        </div>
      </div>

      {/* Self-sized — caps at 60vh, never spans the full canvas. */}
      <div className="max-h-[60vh] overflow-y-auto">
        {isLoading && (
          <div className="flex items-center justify-center gap-2 px-4 py-6 text-2xs text-content-tertiary">
            <Loader2 size={14} className="animate-spin" />
            <span>
              {t('geo_hub.rail.loading_long', {
                defaultValue: 'Fetching anchored projects…',
              })}
            </span>
          </div>
        )}
        {!isLoading && isError && (
          <div className="m-3 rounded-md border border-red-300/40 bg-red-50 px-3 py-3 text-2xs text-red-900 dark:bg-red-950/40 dark:text-red-100">
            <div className="flex items-start gap-2">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <div className="space-y-1">
                <div className="font-semibold">
                  {t('geo_hub.rail.error_title', {
                    defaultValue: 'Could not load projects',
                  })}
                </div>
                <div className="opacity-80">
                  {t('geo_hub.rail.error_hint', {
                    defaultValue:
                      'Globe is still navigable. The project list will repopulate once the backend responds.',
                  })}
                </div>
              </div>
            </div>
          </div>
        )}
        {!isLoading && !isError && projects.length === 0 && (
          <div className="px-4 py-6 text-center text-2xs text-content-tertiary">
            {t('geo_hub.rail.empty_inline', {
              defaultValue:
                'No anchored projects yet. The empty-state card on the globe explains how to add one.',
            })}
          </div>
        )}
        {!isLoading && !isError && projects.length > 0 && (
          <ul className="m-2 space-y-1">
            {projects.map((p) => {
              const isFocused = focusedProjectId === p.project_id;
              return (
                <li key={p.project_id}>
                  <div
                    className={[
                      'group rounded-md border px-3 py-2 transition-colors',
                      isFocused
                        ? 'border-emerald-400/60 bg-emerald-50 dark:bg-emerald-950/30'
                        : 'border-transparent hover:border-border hover:bg-surface-secondary',
                    ].join(' ')}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        aria-hidden
                        className={[
                          'inline-block h-2 w-2 shrink-0 rounded-full',
                          isFocused
                            ? 'bg-emerald-500 ring-2 ring-emerald-300/50'
                            : 'bg-emerald-500/80',
                        ].join(' ')}
                      />
                      <button
                        type="button"
                        onClick={() => onFocus(p)}
                        className={[
                          'min-w-0 flex-1 truncate text-left text-xs font-medium',
                          'text-content-primary hover:text-oe-blue',
                          'focus:outline-none focus-visible:underline',
                        ].join(' ')}
                        title={t('geo_hub.rail.focus_hint', {
                          defaultValue: 'Fly camera to this project',
                        })}
                      >
                        {p.project_name}
                      </button>
                      <Link
                        to={`/projects/${p.project_id}/geo`}
                        className={[
                          'inline-flex shrink-0 items-center gap-0.5 rounded',
                          'px-1.5 py-0.5 text-2xs font-medium text-oe-blue',
                          // Reveal on hover OR focus so keyboard users
                          // can reach the deep-link without a mouse.
                          'opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100',
                          'hover:bg-oe-blue/10',
                          'focus:outline-none focus:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-oe-blue',
                        ].join(' ')}
                        title={t('geo_hub.rail.open_hint', {
                          defaultValue: 'Open project map',
                        })}
                      >
                        {t('common.open', { defaultValue: 'Open' })}
                        <ArrowUpRight size={11} strokeWidth={2.25} />
                      </Link>
                    </div>
                    <div className="ml-4 mt-1 flex items-center gap-2 font-mono text-2xs text-content-tertiary">
                      <span className="tabular-nums">
                        {Number(p.lat).toFixed(4)},{' '}
                        {Number(p.lon).toFixed(4)}
                      </span>
                      {p.region_code && (
                        <span className="rounded bg-surface-tertiary px-1 py-px uppercase tracking-wider">
                          {p.region_code}
                        </span>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

/**
 * Top-center address search overlay — Nominatim-backed, debounced.
 *
 * Drops a single transient pin on the globe and flies the camera there.
 * Renders the active search hit as a slim chip beneath the input with a
 * dismiss button so the user always has an obvious way to clear the
 * marker. Glass-card chrome matches the anchored-projects overlay so
 * the two read as parts of the same control surface.
 */
function GeoSearchOverlay({
  pin,
  onSelect,
  onClear,
}: {
  pin: GeoSearchPin | null;
  onSelect: (sel: GeoSearchPin) => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState<string>('');

  // Escape clears both the typed query and the active pin even when the
  // input doesn't have focus — Esc-from-anywhere is the WAI-ARIA combobox
  // expectation and lets keyboard users dismiss the marker without
  // tabbing back to the X button.
  useEffect(() => {
    if (!pin) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setQuery('');
        onClear();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [pin, onClear]);

  return (
    <div
      className={[
        // Phones: full-bleed under the top bar.
        // md/lg: nudged right of the 288 px anchored-projects rail so the
        //   two overlays never overlap.
        // xl+: pinned to true center for the showcase aesthetic.
        // The width formula caps at the smaller of 520 px (showcase size)
        // and the viewport minus our left offset and a 1 rem right gutter,
        // so the overlay never overflows the canvas at md/lg breakpoints.
        'pointer-events-none absolute top-3 z-20',
        'left-3 w-[calc(100vw-1.5rem)] max-w-[520px]',
        'md:left-[19.5rem] md:w-[calc(100vw-20.5rem)]',
        'xl:left-1/2 xl:w-[calc(100vw-1.5rem)] xl:-translate-x-1/2',
      ].join(' ')}
      data-testid="geo-search-overlay"
    >
      <div
        className={[
          'pointer-events-auto rounded-xl border border-white/15 bg-white/95',
          'p-2 shadow-lg shadow-black/20 ring-1 ring-black/5 backdrop-blur-md',
          'dark:bg-slate-900/90',
        ].join(' ')}
      >
        <AddressAutocomplete
          value={query}
          onChange={setQuery}
          placeholder={t('geo.search_placeholder', {
            defaultValue: 'Search any address worldwide…',
          })}
          ariaLabel={t('geo.search_placeholder', {
            defaultValue: 'Search any address worldwide…',
          })}
          onSelect={(sel) => {
            setQuery(sel.display_name);
            onSelect({
              lat: sel.lat,
              lon: sel.lon,
              name: sel.display_name,
            });
          }}
        />
        {pin && (
          <div
            className={[
              'mt-2 flex items-center gap-2 rounded-md',
              'border border-sky-300/40 bg-sky-50/90 px-2.5 py-1.5',
              'text-2xs text-sky-900 dark:bg-sky-950/40 dark:text-sky-100',
            ].join(' ')}
            role="status"
          >
            <MapPin
              size={12}
              strokeWidth={2.25}
              className="shrink-0 text-sky-600 dark:text-sky-300"
              aria-hidden
            />
            <span className="min-w-0 flex-1 truncate font-medium">
              {t('geo.search_pin_label', {
                defaultValue: 'Pinned: {{name}}',
                name: pin.name,
              })}
            </span>
            <button
              type="button"
              onClick={() => {
                setQuery('');
                onClear();
              }}
              className={[
                'inline-flex h-5 w-5 shrink-0 items-center justify-center rounded',
                'text-sky-700 hover:bg-sky-100 dark:text-sky-200 dark:hover:bg-sky-900/50',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400',
              ].join(' ')}
              aria-label={t('geo.search_pin_dismiss', {
                defaultValue: 'Clear search pin',
              })}
              title={t('geo.search_pin_dismiss', {
                defaultValue: 'Clear search pin',
              })}
              data-testid="geo-search-pin-dismiss"
            >
              <X size={12} strokeWidth={2.25} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function GeoHubPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [cursorCoords, setCursorCoords] = useState<GeoCursorCoords | null>(
    null,
  );
  const [cameraState, setCameraState] = useState<GeoCameraState | null>(null);
  // When the user clicks a project in the rail we ask the viewer to fly
  // to it. This is the same mechanism used by ``focusedTilesetId`` in
  // the project view — the viewer reacts to the prop, the page owns it.
  const [focusedProjectId, setFocusedProjectId] = useState<string | null>(
    null,
  );
  // Read lazily so SSR + tests don't blow up on `window`. Persisted to
  // localStorage so the user's preferred chrome density survives reloads.
  const [panelCollapsed, setPanelCollapsed] = useState<boolean>(
    readPanelCollapsed,
  );
  // Raster overlay state — scoped to the focused or active project so a
  // user on the global view can pin overlays onto their primary project
  // without leaving the page.
  const [activeOverlayId, setActiveOverlayId] = useState<string | null>(
    null,
  );
  const [overlayEditMode, setOverlayEditMode] =
    useState<OverlayEditMode>('idle');
  const [cesiumRuntime, setCesiumRuntime] = useState<
    { cesium: unknown; viewer: unknown } | null
  >(null);
  // Transient address-search pin. Replaced wholesale on each search and
  // cleared via the inline dismiss button in the overlay.
  const [searchPin, setSearchPin] = useState<GeoSearchPin | null>(null);
  // Scene-mode (2D / 3D / Columbus) — read lazily so SSR + tests don't
  // blow up on ``window``. Persisted under ``geoHub.sceneMode`` so the
  // user's projection choice survives reloads.
  const [sceneMode, setSceneMode] = useState<GeoSceneMode>(readSceneMode);
  // Renderer (2D MapLibre map vs 3D Cesium globe) + the 2D basemap choice.
  // Both persisted so the user's preferred view survives reloads.
  const [engine, setEngine] = useState<GeoEngine>(readEngine);
  const [basemap, setBasemap] = useState<BasemapId>(readBasemap);
  // OverlaySidebar fly-to handle. ``focusedLayerId`` highlights the row
  // the user last clicked; ``flyToTarget`` carries the nonce + centroid
  // that CesiumViewer's flyToTarget effect reads. Nonced via a click
  // counter so re-clicking the same row re-flies (vs. dedup-by-id).
  const [focusedLayerId, setFocusedLayerId] = useState<string | null>(null);
  const [flyToTarget, setFlyToTarget] = useState<{
    key: string;
    lat: number;
    lon: number;
  } | null>(null);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(
        PANEL_COLLAPSED_LS_KEY,
        panelCollapsed ? '1' : '0',
      );
    } catch {
      /* localStorage disabled / quota full — UX still works in-memory */
    }
  }, [panelCollapsed]);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(SCENE_MODE_LS_KEY, sceneMode);
    } catch {
      /* localStorage disabled / quota full — UX still works in-memory */
    }
  }, [sceneMode]);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(ENGINE_LS_KEY, engine);
    } catch {
      /* localStorage disabled / quota full — UX still works in-memory */
    }
  }, [engine]);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(BASEMAP_LS_KEY, basemap);
    } catch {
      /* localStorage disabled / quota full — UX still works in-memory */
    }
  }, [basemap]);

  // One pin per anchored project the user can access — degrades to an
  // empty list on backend failure so the globe still renders. The
  // visible failure banner / rail status keeps the user informed.
  const projectsQuery = useQuery({
    queryKey: ['geo-hub', 'anchored-projects'],
    queryFn: () => fetchAnchoredProjects(),
    staleTime: 60_000,
    retry: 1,
  });

  const projects = projectsQuery.data ?? [];
  const pins = useMemo<GeoPinBundle>(
    () => ({
      hse: [],
      punchlist: [],
      diary: [],
      projects,
    }),
    [projects],
  );

  // Pin clicks: a single project pin deep-links into its project map; a
  // cluster bubble flies the camera to the cluster centroid (closer
  // altitude) so it visually expands into its members. Cross-module /
  // search pins are a no-op on the global view (no source records here).
  const handlePinSelect = useCallback(
    (sel: { tag: string; clusterProjectIds?: string[] }) => {
      const { tag, clusterProjectIds } = sel;
      if (tag.startsWith('project:')) {
        const projectId = tag.slice('project:'.length);
        if (projectId) navigate(`/projects/${projectId}/geo`);
        return;
      }
      if (tag.startsWith('cluster:')) {
        // Compute the centroid of the cluster members and fly closer so
        // the bubble breaks apart into individual pins.
        const memberIds = new Set(clusterProjectIds ?? []);
        const members = projects.filter((p) => memberIds.has(p.project_id));
        if (members.length === 0) return;
        let sumLat = 0;
        let sumLon = 0;
        let n = 0;
        for (const m of members) {
          const lat = Number(m.lat);
          const lon = Number(m.lon);
          if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
          sumLat += lat;
          sumLon += lon;
          n += 1;
        }
        if (n === 0) return;
        setFlyToTarget({
          key: `cluster:${tag}:${Date.now()}`,
          lat: sumLat / n,
          lon: sumLon / n,
        });
      }
    },
    [navigate, projects],
  );

  // 404 from /api/v1/geo-hub/projects means the running backend is older
  // than this frontend bundle (or the module didn't load). Surface a
  // separate, dev-friendly hint instead of the generic fetch-failed
  // banner so the user (or dev) knows to restart / update the backend.
  const isStaleBackend =
    projectsQuery.error instanceof ApiError &&
    projectsQuery.error.status === 404;

  // Resolve the focused project + the project whose drawing overlays
  // should paint on the map (the focused row, else the active project).
  const focusedProjectObj = focusedProjectId
    ? projects.find((p) => p.project_id === focusedProjectId) ?? null
    : null;
  const overlayProjectId = focusedProjectId ?? activeProjectId ?? null;

  // Floating chrome shared by BOTH engines: address search, the cursor
  // HUD, the anchored-projects rail, the overlay fly-to list, and the
  // empty state. Built once and handed to whichever viewer is mounted.
  const sharedChrome = (
    <>
      <GeoSearchOverlay
        pin={searchPin}
        onSelect={setSearchPin}
        onClear={() => setSearchPin(null)}
      />
      <GeoOverlayHud
        cursorLat={cursorCoords?.lat ?? null}
        cursorLon={cursorCoords?.lon ?? null}
        altitudeM={cameraState?.cameraAltitudeM ?? null}
        headingDeg={cameraState?.headingDeg ?? null}
        active
      />
      <AnchoredProjectsOverlay
        projects={projects}
        isLoading={projectsQuery.isLoading}
        isError={projectsQuery.isError}
        onRetry={() => projectsQuery.refetch()}
        focusedProjectId={focusedProjectId}
        onFocus={(p) => setFocusedProjectId(p.project_id)}
        collapsed={panelCollapsed}
        onToggleCollapsed={() => setPanelCollapsed((v) => !v)}
      />
      {overlayProjectId && (
        <OverlaySidebar
          projectId={overlayProjectId}
          focusedId={focusedLayerId}
          onFly={(target) => {
            setFocusedLayerId(target.id);
            // Nonce every click so re-clicking the same row re-flies.
            setFlyToTarget({
              key: `${target.kind}:${target.id}:${Date.now()}`,
              lat: target.lat,
              lon: target.lon,
            });
          }}
        />
      )}
      {!projectsQuery.isLoading &&
        !projectsQuery.isError &&
        projects.length === 0 && (
          <GlobalNoProjectsEmpty onAnchored={() => projectsQuery.refetch()} />
        )}
    </>
  );

  // Cesium-only raster overlay plumbing: the OverlayPanel mutation UI and
  // the OverlayLayer that paints rasters into the globe and hosts the
  // corner / crop editing. The 2D map paints rasters itself (via
  // MapLibreViewer's overlayProjectId), so these only mount in 3D.
  const cesiumOverlayChrome = overlayProjectId ? (
    <>
      <OverlayPanel
        projectId={overlayProjectId}
        activeOverlayId={activeOverlayId}
        editMode={overlayEditMode}
        onSelectOverlay={(id) => {
          setActiveOverlayId(id);
          if (id === null) setOverlayEditMode('idle');
        }}
        onChangeEditMode={setOverlayEditMode}
      />
      <OverlayLayer
        projectId={overlayProjectId}
        cesium={cesiumRuntime?.cesium ?? null}
        viewer={cesiumRuntime?.viewer ?? null}
        activeOverlayId={activeOverlayId}
        editMode={overlayEditMode}
        onSelectOverlay={setActiveOverlayId}
        onChangeEditMode={setOverlayEditMode}
      />
    </>
  ) : null;

  return (
    // Full-bleed layout — negate AppLayout's <main> padding (px-4 pt-6 pb-4 sm:px-7)
    // so the globe fills the viewport, then claim exactly viewport-minus-header
    // height so the Cesium canvas never spills past the visible browser area.
    <div className="-mx-4 -mt-6 -mb-4 flex h-[calc(100dvh-var(--oe-header-height,52px))] w-[calc(100%+2rem)] flex-col sm:-mx-7 sm:w-[calc(100%+3.5rem)]">
      <BetaBanner moduleKey="geo-hub" className="mt-3" />
      <header
        className={[
          // flex-wrap: the picker cluster on the right is 811px wide, so on a
          // phone this single nowrap row scrolled the page to 949px. Wrapping
          // only engages when the row cannot fit, so the desktop single-line
          // header is untouched.
          'flex flex-wrap items-center gap-4 border-b border-border bg-surface-primary',
          'px-5 py-3',
        ].join(' ')}
      >
        <div className="flex items-center gap-2.5">
          <span
            className={[
              'inline-flex h-8 w-8 items-center justify-center rounded-md',
              'bg-emerald-500/10 text-emerald-600 dark:text-emerald-300',
            ].join(' ')}
          >
            <Globe2 size={16} strokeWidth={2} />
          </span>
          <div>
            <h1 className="text-base font-semibold text-content-primary leading-tight">
              {t('geo_hub.global_title', {
                defaultValue: 'Geo Hub - Global view',
              })}
            </h1>
            <p className="text-2xs uppercase tracking-[0.14em] text-content-tertiary">
              {t('geo_hub.global_eyebrow', {
                defaultValue: 'All your projects on a 3D globe',
              })}
            </p>
          </div>
        </div>
        <p className="hidden flex-1 truncate text-xs text-content-secondary md:block">
          {t('geo_hub.global_subtitle_v2', {
            defaultValue:
              'Drag to rotate · scroll to zoom · click a project pin to open. Click a project in the left list to fly the camera.',
          })}
        </p>
        {/* max-w-full + flex-wrap so the four pickers stack onto extra rows on
            a narrow screen instead of running off the side of the page. */}
        <div className="ml-auto flex max-w-full flex-wrap items-center gap-2">
          <EngineModePicker current={engine} onChange={setEngine} />
          {/* The 3D globe carries Cesium's projection picker; the 2D map
              carries the basemap picker (streets / minimal / paper). */}
          {engine === '3d' ? (
            <GeoSceneModePicker current={sceneMode} onChange={setSceneMode} />
          ) : (
            <BasemapPicker current={basemap} onChange={setBasemap} />
          )}
          <GeoModePicker current="global" projectId={activeProjectId} />
          {/* "How it works" explainer, a concept-level companion to the Tour. */}
          <ModuleGuideButton content={geoHubGuide} />
          {/* Per-module Tour CTA — launches the Geo Hub-specific tour. */}
          <ModuleHelpButton tourId="geo" />
        </div>
      </header>

      <DismissibleInfo
        storageKey="geo"
        className="mx-5 mt-3"
        title={t('info.geo.title', { defaultValue: 'Geo Hub' })}
      >
        {t('info.geo.body', {
          defaultValue:
            'See all your projects pinned on a shared 3D globe. Anchor a project by address or coordinates, then jump from its map location into its BOQ, BIM models, and the rest of the canonical project data.',
        })}
      </DismissibleInfo>

      {/* Stale-backend banner — distinct from the generic fetch-failed
          banner because the user fix is different: restart / update the
          backend (or wait for it to come back up). */}
      {projectsQuery.isError && isStaleBackend && (
        <div className="border-b border-amber-300/40 bg-amber-50 px-5 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          <div className="flex items-center gap-2">
            <ServerCrash size={13} className="shrink-0" />
            <span className="flex-1">
              {t('geo_hub.global_stale_backend', {
                defaultValue:
                  'The geo service is starting up or out of date. Reload in a moment, or contact your admin to restart the backend.',
              })}
            </span>
            <button
              type="button"
              onClick={() => projectsQuery.refetch()}
              className={[
                'inline-flex items-center gap-1 rounded-md border border-amber-300/50 px-2 py-0.5',
                'font-medium hover:bg-amber-100 dark:hover:bg-amber-900/40',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400',
              ].join(' ')}
            >
              <RefreshCw size={11} strokeWidth={2} />
              {t('common.retry', { defaultValue: 'Retry' })}
            </button>
          </div>
        </div>
      )}

      {/* Generic failure banner — visible up top so the user understands the rail
          status before scanning the canvas. Inline-dismissable retry. */}
      {projectsQuery.isError && !isStaleBackend && (
        <div className="border-b border-red-300/40 bg-red-50 px-5 py-2 text-xs text-red-900 dark:bg-red-950/40 dark:text-red-100">
          <div className="flex items-center gap-2">
            <AlertTriangle size={13} className="shrink-0" />
            <span className="flex-1">
              {t('geo_hub.global_fetch_failed', {
                defaultValue:
                  'Could not load anchored projects from the server. The globe is fully navigable; reload to retry.',
              })}
            </span>
            <button
              type="button"
              onClick={() => projectsQuery.refetch()}
              className={[
                'inline-flex items-center gap-1 rounded-md border border-red-300/50 px-2 py-0.5',
                'font-medium hover:bg-red-100 dark:hover:bg-red-900/40',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400',
              ].join(' ')}
            >
              <RefreshCw size={11} strokeWidth={2} />
              {t('common.retry', { defaultValue: 'Retry' })}
            </button>
          </div>
        </div>
      )}

      {/* First-load help banner — appears while the anchored-projects
          query is still in flight so the user is never staring at a blank
          slate wondering what's going on. Disappears as soon as we
          either resolve pins or hit an error state (which renders its
          own banner above). */}
      {projectsQuery.isLoading && !projectsQuery.isError && (
        <div className="border-b border-emerald-300/40 bg-emerald-50/70 px-5 py-2 text-xs text-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100">
          <div className="flex items-center gap-2">
            <Info size={13} className="shrink-0" />
            <span className="flex-1">
              {t('geo_hub.global_first_load_hint', {
                defaultValue:
                  'Looking for your projects on the globe... If nothing appears, anchor a project from its settings page → Geo anchor.',
              })}
            </span>
          </div>
        </div>
      )}

      {/* Full-width canvas — the project list is overlay-mounted on top
          (via CesiumViewer's ``overlay`` slot) so the globe always gets
          the full viewport width. */}
      <main className="relative flex-1 overflow-hidden bg-slate-900">
        {engine === '2d' ? (
          <Suspense
            fallback={
              <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-slate-300">
                <Loader2 size={20} className="animate-spin text-emerald-300" />
                <span className="font-medium">
                  {t('geo_hub.loading_map_title', { defaultValue: 'Loading map' })}
                </span>
              </div>
            }
          >
            <MapLibreViewer
              mode="global"
              pins={pins}
              basemap={basemap}
              focusedProject={focusedProjectObj}
              flyToTarget={flyToTarget}
              searchPin={searchPin}
              overlayProjectId={overlayProjectId}
              onPinSelect={handlePinSelect}
              onMouseMove={setCursorCoords}
              onCameraChange={setCameraState}
              overlay={sharedChrome}
            />
          </Suspense>
        ) : (
          <Suspense
            fallback={
              <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-slate-300">
                <Loader2 size={20} className="animate-spin text-emerald-300" />
                <span className="font-medium">
                  {t('geo_hub.loading_viewer_title', {
                    defaultValue: 'Loading 3D globe runtime',
                  })}
                </span>
                <span className="text-xs text-slate-400">
                  {t('geo_hub.loading_viewer_hint', {
                    defaultValue: 'Streaming Cesium chunks (~3 MB) - first load only.',
                  })}
                </span>
              </div>
            }
          >
            <CesiumViewer
              mode="global"
              pins={pins}
              sceneMode={sceneMode}
              focusedProject={focusedProjectObj}
              flyToTarget={flyToTarget}
              searchPin={searchPin}
              onPinSelect={handlePinSelect}
              onMouseMove={setCursorCoords}
              onCameraChange={setCameraState}
              onViewerReady={setCesiumRuntime}
              overlay={
                <>
                  {sharedChrome}
                  {cesiumOverlayChrome}
                </>
              }
            />
          </Suspense>
        )}
      </main>
    </div>
  );
}

export default GeoHubPage;
