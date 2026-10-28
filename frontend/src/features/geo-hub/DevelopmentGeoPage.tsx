// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Per-development Geo Hub page — /property-dev/developments/:devId/geo.
 *
 * Same chrome as ``ProjectGeoPage`` but scoped to a single property_dev
 * development. The backing event ``property_dev.development.created``
 * subscriber already places the development on the project map, so this
 * page is mostly a convenience entry point inside the property_dev UX.
 */

import { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Boxes, AlertTriangle, ServerCrash, Loader2 } from 'lucide-react';

import { ApiError, apiGet } from '@/shared/lib/api';

import { getMapConfig } from './api';
import type { GeoCameraState, GeoCursorCoords } from './CesiumViewer';
import { GeoEmptyState, type GeoEmptyKind } from './GeoEmptyState';
import { GeoModePicker } from './GeoModePicker';
import { GeoOverlayHud } from './GeoOverlayHud';
import { TilesetSidebar } from './TilesetSidebar';
import { useTilesetOverlayState } from './hooks/useTilesetOverlayState';
import type { Tileset } from './types';

interface DevelopmentSummary {
  id: string;
  project_id: string;
  name: string;
}

const CesiumViewer = lazy(() =>
  import('./CesiumViewer').then((m) => ({ default: m.CesiumViewer })),
);

// Shared with ``ProjectGeoPage`` so a single user preference covers
// both surfaces — collapsing the panel in one stays collapsed in the
// other. Versioned (`v1`) so a future incompatible rename never
// resurrects with stale boolean semantics.
const TILESETS_COLLAPSED_LS_KEY = 'oe.geo_hub.tilesets_collapsed.v1';

function readTilesetsCollapsed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(TILESETS_COLLAPSED_LS_KEY) === '1';
  } catch {
    return false;
  }
}

function emptyStateFor(
  hasAnchor: boolean,
  tilesets: Tileset[] | undefined,
): GeoEmptyKind | null {
  if (!hasAnchor) return 'no_anchor';
  const list = tilesets ?? [];
  if (list.length === 0) return 'no_tilesets';
  const allFailed = list.every((t) => t.status === 'failed' || t.status === 'obsolete');
  if (allFailed) return 'all_failed';
  return null;
}

export function DevelopmentGeoPage() {
  const { t } = useTranslation();
  const { devId } = useParams<{ devId: string }>();
  // ``?phase=`` / ``?block=`` narrow the visible tilesets further —
  // matched against ``Tileset.metadata.phase_id`` / ``block_id`` so the
  // dev-scoped map can paint a single phase or block on demand.
  // ``?plot=`` is honored when PropDev links a specific plot to the
  // dev map — we resolve it to a focused tileset further down so the
  // camera flies to that plot's bounding sphere on arrival.
  const [searchParams] = useSearchParams();
  const phaseFilter = searchParams.get('phase');
  const blockFilter = searchParams.get('block');
  const focusedPlotId = searchParams.get('plot');

  const development = useQuery({
    queryKey: ['property-dev', 'development', devId],
    queryFn: () =>
      apiGet<DevelopmentSummary>(`/v1/property-dev/developments/${devId}`),
    enabled: Boolean(devId),
    staleTime: 60_000,
  });

  const mapConfig = useQuery({
    queryKey: ['geo-hub', 'map-config', development.data?.project_id, devId],
    // Forward ``development_id`` so the backend trims tilesets + overlays
    // to those linked to this development. The query-key is keyed on
    // both ids so switching developments invalidates the cache.
    queryFn: () =>
      getMapConfig(development.data!.project_id, { developmentId: devId }),
    enabled: Boolean(development.data?.project_id),
    staleTime: 30_000,
  });

  // Per-tileset visibility + opacity, keyed by the dev id so the dev-scoped
  // view's preferences are independent of the project-scoped view's. Both
  // surfaces share the same hook + storage prefix; only the key differs.
  const tilesetOverlay = useTilesetOverlayState(devId ?? null);
  const hiddenIds = useMemo(() => {
    const s = new Set<string>();
    for (const [id, entry] of Object.entries(tilesetOverlay.state)) {
      if (entry.visible === false) s.add(id);
    }
    return s;
  }, [tilesetOverlay.state]);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [panelCollapsed, setPanelCollapsed] = useState<boolean>(
    readTilesetsCollapsed,
  );
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(
        TILESETS_COLLAPSED_LS_KEY,
        panelCollapsed ? '1' : '0',
      );
    } catch {
      /* localStorage disabled / quota full — UX still works in-memory */
    }
  }, [panelCollapsed]);
  const [cursorCoords, setCursorCoords] = useState<GeoCursorCoords | null>(
    null,
  );
  const [cameraState, setCameraState] = useState<GeoCameraState | null>(null);

  // Phase / block client-side filter. The backend already trims to the
  // development; here we narrow further when the user deep-linked with
  // ``?phase=`` / ``?block=``. Matched against ``metadata.phase_id`` /
  // ``block_id`` — falls through to no filter when fields are absent.
  const filteredTilesets = useMemo(() => {
    const src = mapConfig.data?.tilesets;
    if (!src) return src;
    if (!phaseFilter && !blockFilter) return src;
    return src.filter((ts) => {
      const meta = ts.metadata as Record<string, unknown> | undefined;
      if (!meta || typeof meta !== 'object') return false;
      if (phaseFilter && meta['phase_id'] !== phaseFilter) return false;
      if (blockFilter && meta['block_id'] !== blockFilter) return false;
      return true;
    });
  }, [mapConfig.data?.tilesets, phaseFilter, blockFilter]);

  // Compose the viewer's map config with the filtered tileset list so
  // the Cesium scene only loads what the deep-link asked for. Cheap —
  // we only override one field on the existing bundle.
  const viewerMapConfig = useMemo(() => {
    if (!mapConfig.data) return mapConfig.data;
    if (filteredTilesets === mapConfig.data.tilesets) return mapConfig.data;
    return { ...mapConfig.data, tilesets: filteredTilesets ?? [] };
  }, [mapConfig.data, filteredTilesets]);

  const tilesets = filteredTilesets;
  const emptyKind = useMemo(
    () => emptyStateFor(Boolean(mapConfig.data?.anchor), tilesets),
    [mapConfig.data?.anchor, tilesets],
  );

  // Resolve ``?plot=...`` to a Tileset.id by matching
  // ``metadata.plot_id`` so the camera flies to the plot's bounding
  // sphere instead of leaving the user at the development centroid.
  const focusedTilesetId = useMemo<string | null>(() => {
    if (!focusedPlotId || !tilesets || tilesets.length === 0) return null;
    const hit = tilesets.find((ts) => {
      const meta = ts.metadata as Record<string, unknown> | undefined;
      if (!meta || typeof meta !== 'object') return false;
      return meta['plot_id'] === focusedPlotId;
    });
    return hit?.id ?? null;
  }, [focusedPlotId, tilesets]);

  const projectId = development.data?.project_id ?? null;
  const loading = development.isLoading || mapConfig.isLoading;
  const error = development.error || mapConfig.error;
  // 404 on either dependency = stale backend / unknown dev → friendlier
  // hint than the generic load-failed banner.
  const isStaleBackend =
    error instanceof ApiError && error.status === 404;

  return (
    // Full-bleed layout — negate AppLayout's <main> padding so the map fills the
    // viewport, claim exactly viewport-minus-header so it never overflows.
    <div className="-mx-4 -mt-6 -mb-4 flex h-[calc(100vh-var(--oe-header-height,52px))] w-[calc(100%+2rem)] flex-col sm:-mx-7 sm:w-[calc(100%+3.5rem)]">
      <header
        className={[
          'flex items-center gap-4 border-b border-border bg-surface-primary',
          'px-5 py-3',
        ].join(' ')}
      >
        <div className="flex items-center gap-2.5">
          <span
            className={[
              'inline-flex h-8 w-8 items-center justify-center rounded-md',
              'bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-300',
            ].join(' ')}
          >
            <Boxes size={16} strokeWidth={2} />
          </span>
          <div>
            <h1 className="text-base font-semibold leading-tight text-content-primary">
              {t('geo_hub.development_title', {
                defaultValue: 'Development map',
              })}
            </h1>
            {development.data && (
              <p className="text-2xs uppercase tracking-[0.14em] text-content-tertiary">
                {development.data.name}
              </p>
            )}
          </div>
        </div>
        <div className="ml-auto">
          <GeoModePicker
            current="development"
            projectId={projectId}
            developmentId={devId ?? null}
          />
        </div>
      </header>
      {/* Full-width canvas — the tileset rail is overlay-mounted on top
          (via CesiumViewer's ``overlay`` slot) so the map gets the full
          viewport width on every viewport size. */}
      <main className="relative flex-1 overflow-hidden bg-slate-900">
        {error && (
          <div className="absolute inset-0 z-30 flex items-center justify-center p-6">
            {isStaleBackend ? (
              <div className="inline-flex max-w-md items-start gap-3 rounded-lg border border-amber-300/40 bg-amber-950/60 px-4 py-3 text-sm text-amber-100 shadow-md backdrop-blur-md">
                <ServerCrash size={16} className="mt-0.5 shrink-0 text-amber-300" />
                <span>
                  {t('geo_hub.project_stale_backend', {
                    defaultValue:
                      'The geo service is starting up or out of date. Reload in a moment, or contact your admin to restart the backend.',
                  })}
                </span>
              </div>
            ) : (
              <div className="inline-flex max-w-md items-start gap-3 rounded-lg border border-red-300/40 bg-red-950/60 px-4 py-3 text-sm text-red-100 shadow-md backdrop-blur-md">
                <AlertTriangle size={16} className="mt-0.5 shrink-0 text-red-300" />
                <span>
                  {t('geo_hub.load_failed', {
                    defaultValue: 'Could not load geo data for this project.',
                  })}
                </span>
              </div>
            )}
          </div>
        )}
        {!error && loading && (
          <div
            className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 text-xs text-slate-300"
            role="status"
            aria-live="polite"
          >
            {/* Skeleton placeholder so the user sees the panel chrome
                they're about to interact with, not just a blank globe. */}
            <div
              aria-hidden
              className="absolute top-3 left-3 hidden w-72 flex-col gap-2 rounded-xl border border-white/10 bg-slate-900/40 p-3 backdrop-blur-md md:flex"
            >
              <div className="h-3 w-1/2 rounded bg-slate-700/60 animate-pulse" />
              <div className="h-2 w-2/3 rounded bg-slate-700/50 animate-pulse" />
              <div className="mt-2 space-y-1.5">
                <div className="h-8 rounded bg-slate-800/60 animate-pulse" />
                <div className="h-8 rounded bg-slate-800/60 animate-pulse" />
                <div className="h-8 rounded bg-slate-800/60 animate-pulse" />
              </div>
            </div>
            <Loader2 size={20} className="animate-spin text-emerald-300" />
            <span className="font-medium">
              {t('geo_hub.loading_config', {
                defaultValue: 'Loading geo configuration...',
              })}
            </span>
          </div>
        )}
        {!error && mapConfig.data && (
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center text-sm text-slate-300">
                {t('geo_hub.loading_viewer', {
                  defaultValue: 'Loading Cesium viewer (~3 MB)...',
                })}
              </div>
            }
          >
            <CesiumViewer
              mode="development"
              mapConfig={viewerMapConfig}
              focusedTilesetId={focusedTilesetId}
              tilesetOverlayState={tilesetOverlay.state}
              onMouseMove={setCursorCoords}
              onCameraChange={setCameraState}
              overlay={
                <>
                  <GeoOverlayHud
                    cursorLat={cursorCoords?.lat ?? null}
                    cursorLon={cursorCoords?.lon ?? null}
                    altitudeM={cameraState?.cameraAltitudeM ?? null}
                    headingDeg={cameraState?.headingDeg ?? null}
                    active
                  />
                  <TilesetSidebar
                    variant="overlay"
                    collapsed={panelCollapsed}
                    onToggleCollapsed={() => setPanelCollapsed((v) => !v)}
                    tilesets={tilesets}
                    isLoading={loading}
                    hiddenIds={hiddenIds}
                    focusedId={focusedId}
                    onToggleVisibility={tilesetOverlay.toggleVisible}
                    onFocus={(ts) => setFocusedId(ts.id)}
                    getOpacity={tilesetOverlay.getOpacity}
                    onChangeOpacity={tilesetOverlay.setOpacity}
                  />
                  {emptyKind && (
                    <GeoEmptyState kind={emptyKind} projectId={projectId} />
                  )}
                </>
              }
            />
          </Suspense>
        )}
      </main>
    </div>
  );
}

export default DevelopmentGeoPage;
