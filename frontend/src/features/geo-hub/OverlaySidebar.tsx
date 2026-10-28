// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Left-docked sidebar — unified list of raster overlays + 3D tilesets
 * attached to the current project.
 *
 * Why this exists: the global Geo Hub already renders raster overlays
 * and tilesets on the globe but the user has no way to enumerate them.
 * They can't tell which overlays exist, which project they belong to,
 * or where to fly the camera to see one. This sidebar fixes that:
 *
 * * Two sections — "Overlays" (PDF / raster / DWG) and "3D Tilesets"
 *   (Cesium 3D Tiles).
 * * Each row surfaces the name, a type icon, and the bounding centroid
 *   (lat/lon) when computable.
 * * Click a row → ``onFly()`` callback so the parent can move the camera
 *   to that overlay's centroid or the tileset's bounding sphere.
 * * Collapsible to a slim pill that just shows the total count, persisted
 *   to localStorage so the user's preferred density survives reloads.
 * * Empty state with a hint about uploading PDF/DWG/3D tiles.
 *
 * Scope: this is a *list view*. It does NOT take over upload, edit-mode
 * or delete responsibilities — those still live in ``OverlayPanel`` (right
 * rail) which handles raster-overlay mutations. This component is read-only
 * + fly-to, on purpose, to keep the surface tiny and predictable.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  ChevronLeft,
  ChevronRight,
  Cuboid,
  FileText,
  Image as ImageIcon,
  Layers,
  Loader2,
  MapPin,
  PencilRuler,
  type LucideIcon,
} from 'lucide-react';

import { listRasterOverlays, listTilesets } from './api';
import type { GeoRasterOverlay, RasterOverlayKind, Tileset } from './types';

/**
 * One unified "thing on the map" — overlay or tileset. Computed in the
 * component so callers can pass a simple ``onFly(point)`` handler.
 */
export interface OverlaySidebarFlyTarget {
  kind: 'overlay' | 'tileset';
  id: string;
  lat: number;
  lon: number;
}

interface OverlaySidebarProps {
  /** Project whose overlays + tilesets to list. */
  projectId: string;
  /** Currently focused row id (overlay or tileset). */
  focusedId?: string | null;
  /** Click handler — parent flies the camera to ``point.lat`` / ``point.lon``. */
  onFly?: (target: OverlaySidebarFlyTarget) => void;
}

// Persisted across reloads so users who collapse the panel stay
// uncovered on next visit. Versioned (`v1`) so a future incompatible
// rename never resurrects with stale boolean semantics.
const COLLAPSED_LS_KEY = 'oe.geo_hub.overlay_sidebar_collapsed.v1';

function readCollapsed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(COLLAPSED_LS_KEY) === '1';
  } catch {
    return false;
  }
}

/** Map a raster-overlay kind to a lucide icon. */
const OVERLAY_ICON: Record<RasterOverlayKind, LucideIcon> = {
  pdf: FileText,
  dwg: PencilRuler,
  image: ImageIcon,
};

/**
 * Compute the centroid of a raster overlay from its corner polygon.
 * Returns null when the corners are missing / degenerate.
 *
 * ``corners_geojson`` is ``[NW, NE, SE, SW]`` as ``[lon, lat]`` pairs —
 * a simple average is fine for non-antimeridian-crossing quads (which
 * is the common case; antimeridian crossings would need geodesic math
 * we're not worth carrying for a "fly close enough" hint).
 */
export function overlayCentroid(
  o: GeoRasterOverlay,
): { lat: number; lon: number } | null {
  const corners = o.corners_geojson;
  if (!Array.isArray(corners) || corners.length !== 4) return null;
  let sumLon = 0;
  let sumLat = 0;
  for (const pair of corners) {
    if (!Array.isArray(pair) || pair.length !== 2) return null;
    const lon = Number(pair[0]);
    const lat = Number(pair[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
    sumLon += lon;
    sumLat += lat;
  }
  return { lat: sumLat / 4, lon: sumLon / 4 };
}

/**
 * Extract a lat/lon centroid from a Cesium ``bounding_volume`` blob when
 * possible. Cesium 3D Tiles ship bounding volumes in a few shapes; we
 * handle ``region`` (radians) and ``sphere`` (ECEF metres) — the two
 * the canonical tileset packager actually produces. Returns null when
 * the bounding volume is missing or in an unknown shape.
 */
export function tilesetCentroid(
  t: Tileset,
): { lat: number; lon: number } | null {
  const bv = t.bounding_volume;
  if (!bv || typeof bv !== 'object') return null;
  // ``region`` = [west, south, east, north, minH, maxH] in radians.
  const region = (bv as Record<string, unknown>)['region'];
  if (Array.isArray(region) && region.length >= 4) {
    const west = Number(region[0]);
    const south = Number(region[1]);
    const east = Number(region[2]);
    const north = Number(region[3]);
    if (
      Number.isFinite(west) &&
      Number.isFinite(south) &&
      Number.isFinite(east) &&
      Number.isFinite(north)
    ) {
      const lonRad = (west + east) / 2;
      const latRad = (south + north) / 2;
      return {
        lat: (latRad * 180) / Math.PI,
        lon: (lonRad * 180) / Math.PI,
      };
    }
  }
  // ``sphere`` = [centerX, centerY, centerZ, radius] in ECEF metres.
  // We convert the centre to geodetic lat/lon via the standard WGS-84
  // approximation. Good enough for "fly there" framing.
  const sphere = (bv as Record<string, unknown>)['sphere'];
  if (Array.isArray(sphere) && sphere.length >= 3) {
    const x = Number(sphere[0]);
    const y = Number(sphere[1]);
    const z = Number(sphere[2]);
    if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)) {
      const lon = (Math.atan2(y, x) * 180) / Math.PI;
      const hyp = Math.sqrt(x * x + y * y);
      const lat = (Math.atan2(z, hyp) * 180) / Math.PI;
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        return { lat, lon };
      }
    }
  }
  return null;
}

/** Format a lat/lon centroid for the row's secondary line. */
function formatCoords(c: { lat: number; lon: number } | null): string | null {
  if (!c) return null;
  return `${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}`;
}

function SectionHeader({
  icon: Icon,
  label,
  count,
}: {
  icon: LucideIcon;
  label: string;
  count: number;
}) {
  return (
    <div className="mt-1 flex items-center gap-1.5 px-2 pt-2 pb-1">
      <Icon size={12} className="text-content-tertiary" strokeWidth={2} />
      <h3 className="text-2xs font-semibold uppercase tracking-[0.14em] text-content-secondary">
        {label}
      </h3>
      <span className="ml-auto text-2xs font-medium tabular-nums text-content-tertiary">
        {count}
      </span>
    </div>
  );
}

function Row({
  id,
  name,
  icon: Icon,
  badge,
  coords,
  focused,
  onClick,
  disabled,
  testId,
}: {
  id: string;
  name: string;
  icon: LucideIcon;
  badge: string;
  coords: string | null;
  focused: boolean;
  onClick: () => void;
  disabled: boolean;
  testId: string;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      data-row-id={id}
      data-focused={focused ? 'true' : 'false'}
      className={[
        'group flex w-full items-start gap-2 rounded-md border px-2 py-2 text-left',
        'transition-colors',
        focused
          ? 'border-emerald-400/60 bg-emerald-50 dark:bg-emerald-950/30'
          : 'border-transparent hover:border-border hover:bg-surface-secondary',
        disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400',
      ].join(' ')}
      title={
        disabled
          ? t('geo_hub.overlay_sidebar.fly_disabled', {
              defaultValue: 'No location info - can\'t fly the camera here.',
            })
          : t('geo_hub.overlay_sidebar.fly_to', {
              defaultValue: 'Fly camera to {{name}}',
              name,
            })
      }
    >
      <span
        className={[
          'mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center',
          'rounded-sm bg-surface-secondary text-content-secondary',
        ].join(' ')}
      >
        <Icon size={13} strokeWidth={2} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-xs font-medium text-content-primary">
            {name}
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-1.5">
          <span className="rounded bg-surface-tertiary px-1 py-px text-2xs uppercase tracking-wider text-content-tertiary">
            {badge}
          </span>
          {coords ? (
            <span className="truncate font-mono text-2xs tabular-nums text-content-tertiary">
              {coords}
            </span>
          ) : (
            <span className="truncate text-2xs italic text-content-tertiary">
              {t('geo_hub.overlay_sidebar.no_coords', {
                defaultValue: 'no location',
              })}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

export function OverlaySidebar({
  projectId,
  focusedId,
  onFly,
}: OverlaySidebarProps) {
  const { t } = useTranslation();

  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(
        COLLAPSED_LS_KEY,
        collapsed ? '1' : '0',
      );
    } catch {
      /* localStorage disabled / quota full — UX still works in-memory */
    }
  }, [collapsed]);

  // Both queries are guarded by ``projectId`` so the page can mount us
  // before a project is picked without us triggering 400s. Same query
  // keys as ``OverlayPanel`` / ``ProjectGeoPage`` so refetches stay
  // coherent across panels.
  const overlaysQuery = useQuery({
    queryKey: ['geo-hub', 'raster-overlays', projectId],
    queryFn: () => listRasterOverlays(projectId, { includeHidden: true }),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });
  const tilesetsQuery = useQuery({
    queryKey: ['geo-hub', 'tilesets', projectId],
    queryFn: () => listTilesets(projectId),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });

  const overlays = overlaysQuery.data ?? [];
  const tilesets = tilesetsQuery.data ?? [];
  const totalCount = overlays.length + tilesets.length;

  const isLoading = overlaysQuery.isLoading || tilesetsQuery.isLoading;

  // Memo the centroid map so re-clicks don't repeat the math + we keep
  // referential identity for the consumer's flyTo dep array.
  const overlayCentroids = useMemo(() => {
    const map = new Map<string, { lat: number; lon: number } | null>();
    for (const o of overlays) map.set(o.id, overlayCentroid(o));
    return map;
  }, [overlays]);
  const tilesetCentroids = useMemo(() => {
    const map = new Map<string, { lat: number; lon: number } | null>();
    for (const t of tilesets) map.set(t.id, tilesetCentroid(t));
    return map;
  }, [tilesets]);

  // Collapsed → slim pill. Same chrome family as the other Geo Hub pills
  // so the user reads them as "the same kind of thing".
  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        data-testid="geo-overlay-sidebar-toggle"
        className={[
          'absolute bottom-3 left-3 z-20 inline-flex items-center gap-2',
          'rounded-full border border-white/15 bg-slate-900/85 px-3 py-1.5',
          'text-xs font-medium text-white shadow-lg shadow-black/20 backdrop-blur-md',
          'ring-1 ring-white/5 transition hover:bg-slate-800/90',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400',
        ].join(' ')}
        aria-expanded={false}
        aria-label={t('geo_hub.overlay_sidebar.expand', {
          defaultValue: 'Show overlays + tilesets',
        })}
        title={t('geo_hub.overlay_sidebar.expand', {
          defaultValue: 'Show overlays + tilesets',
        })}
      >
        <Layers size={13} strokeWidth={2} className="text-emerald-300" />
        <span className="tabular-nums">{isLoading ? '…' : totalCount}</span>
        <ChevronRight size={13} strokeWidth={2.25} className="text-white/70" />
      </button>
    );
  }

  return (
    <aside
      data-testid="geo-overlay-sidebar"
      className={[
        // Left-docked, sits below the anchored-projects rail so it never
        // covers the top-left "what projects exist" panel. ``70px`` matches
        // a comfortable gap below a fully-collapsed AnchoredProjectsOverlay
        // pill (~32 px tall) on small screens; on larger screens both panels
        // can be open simultaneously since the canvas is tall enough for a
        // 60vh top panel + a 50vh bottom panel.
        'absolute bottom-3 left-3 z-20 flex w-72 max-w-[calc(100vw-1.5rem)] flex-col',
        'rounded-xl border border-white/15 bg-white/95 dark:bg-slate-900/90',
        'shadow-lg shadow-black/20 ring-1 ring-black/5 backdrop-blur-md',
        // Hide on phone-width so it doesn't cover the whole map; users
        // get the collapsed pill instead (rendered when toggled).
        'hidden md:flex',
      ].join(' ')}
      aria-label={t('geo_hub.overlay_sidebar.aria', {
        defaultValue: 'Overlays and tilesets',
      })}
    >
      <div className="flex items-center justify-between gap-2 border-b border-black/5 px-3 py-2.5 dark:border-white/10">
        <div className="min-w-0">
          <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-content-secondary">
            {t('geo_hub.overlay_sidebar.title', {
              defaultValue: 'Layers on this project',
            })}
          </h2>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {isLoading
              ? t('geo_hub.overlay_sidebar.loading', {
                  defaultValue: 'Loading…',
                })
              : t('geo_hub.overlay_sidebar.counter', {
                  defaultValue: '{{count}} item(s)',
                  count: totalCount,
                })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className={[
            'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
            'text-content-tertiary hover:bg-surface-secondary hover:text-content-primary',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400',
          ].join(' ')}
          aria-expanded
          aria-label={t('geo_hub.overlay_sidebar.collapse', {
            defaultValue: 'Hide overlays + tilesets',
          })}
          title={t('geo_hub.overlay_sidebar.collapse', {
            defaultValue: 'Hide overlays + tilesets',
          })}
        >
          <ChevronLeft size={14} strokeWidth={2} />
        </button>
      </div>

      {/* Body. Capped at 50vh so the bottom-left panel never grows tall
          enough to collide with a fully-expanded top-left rail. */}
      <div className="max-h-[50vh] overflow-y-auto pb-2">
        {isLoading && (
          <div className="flex items-center justify-center gap-2 px-4 py-6 text-2xs text-content-tertiary">
            <Loader2 size={14} className="animate-spin" />
            <span>
              {t('geo_hub.overlay_sidebar.loading_long', {
                defaultValue: 'Fetching overlays and tilesets…',
              })}
            </span>
          </div>
        )}

        {!isLoading && totalCount === 0 && (
          <div
            data-testid="geo-overlay-sidebar-empty"
            className="m-3 rounded-md border border-dashed border-border px-3 py-4 text-center text-2xs text-content-tertiary"
          >
            <Layers
              size={18}
              className="mx-auto mb-1.5 text-content-quaternary"
              aria-hidden
            />
            <p>
              {t('geo_hub.overlay_sidebar.empty', {
                defaultValue:
                  'No overlays yet. Upload a PDF/DWG or import 3D tiles to see them here.',
              })}
            </p>
          </div>
        )}

        {!isLoading && totalCount > 0 && (
          <>
            {overlays.length > 0 && (
              <>
                <SectionHeader
                  icon={MapPin}
                  label={t('geo_hub.overlay_sidebar.section_overlays', {
                    defaultValue: 'Overlays',
                  })}
                  count={overlays.length}
                />
                <ul className="space-y-1 px-2">
                  {overlays.map((o) => {
                    const centroid = overlayCentroids.get(o.id) ?? null;
                    const Icon = OVERLAY_ICON[o.source_kind] ?? ImageIcon;
                    return (
                      <li key={o.id}>
                        <Row
                          id={o.id}
                          name={
                            o.name ||
                            t('geo_hub.overlay_sidebar.untitled', {
                              defaultValue: 'Untitled overlay',
                            })
                          }
                          icon={Icon}
                          badge={o.source_kind.toUpperCase()}
                          coords={formatCoords(centroid)}
                          focused={focusedId === o.id}
                          disabled={!centroid}
                          onClick={() => {
                            if (!centroid) return;
                            onFly?.({
                              kind: 'overlay',
                              id: o.id,
                              lat: centroid.lat,
                              lon: centroid.lon,
                            });
                          }}
                          testId="geo-overlay-sidebar-row-overlay"
                        />
                      </li>
                    );
                  })}
                </ul>
              </>
            )}

            {tilesets.length > 0 && (
              <>
                <SectionHeader
                  icon={Cuboid}
                  label={t('geo_hub.overlay_sidebar.section_tilesets', {
                    defaultValue: '3D Tilesets',
                  })}
                  count={tilesets.length}
                />
                <ul className="space-y-1 px-2">
                  {tilesets.map((ts) => {
                    const centroid = tilesetCentroids.get(ts.id) ?? null;
                    return (
                      <li key={ts.id}>
                        <Row
                          id={ts.id}
                          name={
                            ts.name ||
                            t('geo_hub.overlay_sidebar.untitled_tileset', {
                              defaultValue: 'Untitled tileset',
                            })
                          }
                          icon={Cuboid}
                          badge={ts.tile_format.toUpperCase()}
                          coords={formatCoords(centroid)}
                          focused={focusedId === ts.id}
                          disabled={!centroid}
                          onClick={() => {
                            if (!centroid) return;
                            onFly?.({
                              kind: 'tileset',
                              id: ts.id,
                              lat: centroid.lat,
                              lon: centroid.lon,
                            });
                          }}
                          testId="geo-overlay-sidebar-row-tileset"
                        />
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

export default OverlaySidebar;
