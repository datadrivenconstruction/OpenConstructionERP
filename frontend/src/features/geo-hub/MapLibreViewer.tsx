// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * MapLibreViewer - the lightweight 2D Geo Hub renderer.
 *
 * The fast, "like paper" alternative to the Cesium 3D globe. No multi-MB
 * runtime download: MapLibre GL is already bundled (it backs the project
 * location maps), so this paints instantly. Renders:
 *
 *   * project pins (clickable - deep-link into a project) ;
 *   * in project mode, the project's own pin, its safety / punch / site
 *     photo pins, and a click-to-place mode for setting its location. That
 *     mode also opens on the site, tilted, so the style's extruded
 *     buildings stand up ;
 *   * the transient address-search pin ;
 *   * georeferenced drawing overlays (PDF / DWG / image rasters) placed by
 *     their four corner coordinates - the same overlays the 3D view shows ;
 *   * a live cursor lat/lon feed for the shared HUD ;
 *   * the page's floating ``overlay`` chrome (anchored-projects rail,
 *     search box, empty state) on top of the canvas.
 *
 * Basemap (streets / minimal / paper / blueprint) is owned by the page and
 * passed in; see ./mapStyles. The tile-free paper + blueprint styles make
 * the whole map work fully offline.
 *
 * Mirrors the slice of {@link CesiumViewer}'s prop surface the Geo Hub page
 * uses, so the page can swap engines without re-plumbing its state.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { MapPin } from 'lucide-react';
import Map, {
  Marker,
  Source,
  Layer,
  NavigationControl,
  ScaleControl,
  AttributionControl,
  type MapRef,
  type MapLayerMouseEvent,
  type ViewStateChangeEvent,
} from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';

import { colorForProjectStatus, pinTooltipLabel } from './projectPinUtils';
import { geoAuthHeaders, listRasterOverlays, rasterOverlayImageUrl } from './api';
import type {
  GeoCameraState,
  GeoCursorCoords,
  GeoSearchPin,
} from './CesiumViewer';
import type { AnchoredProject, GeoPinBundle, GeoRasterOverlay } from './types';
import { TILE_ATTRIBUTION_HTML } from '@/shared/ui/ProjectMap/basemap';

import {
  BASEMAP_BACKDROP,
  basemapMeta,
  buildBasemapStyle,
  type BasemapId,
} from './mapStyles';

type ViewerMode = 'global' | 'project' | 'development';

interface MapLibreViewerProps {
  mode: ViewerMode;
  /** Cross-module + project pin bundle (only ``projects`` is drawn here). */
  pins?: GeoPinBundle;
  /** Active basemap - owned + persisted by the page. */
  basemap: BasemapId;
  /** Fly the camera to this project's anchor (re-fires when id changes). */
  focusedProject?: AnchoredProject | null;
  /** Generic "fly here" handle; ``key`` is a nonce so re-clicks re-fly. */
  flyToTarget?: { key: string; lat: number; lon: number } | null;
  /** Transient address-search pin. */
  searchPin?: GeoSearchPin | null;
  /** Project whose drawing overlays should paint on the map (or null). */
  overlayProjectId?: string | null;
  /** Floating chrome rendered above the canvas (rail, search, HUD). */
  overlay?: ReactNode;
  onPinSelect?: (sel: { tag: string; clusterProjectIds?: string[] }) => void;
  onMouseMove?: (coords: GeoCursorCoords | null) => void;
  onCameraChange?: (state: GeoCameraState) => void;
  /**
   * Project mode only: the project's own location. The map opens on it,
   * draws its pin, and flies to it again whenever it moves (a pin placed
   * by hand, or one geocoded from the address after mount).
   */
  anchor?: { lat: number; lon: number; label?: string } | null;
  /** While true a click on the map is handed to ``onMapClick``. */
  pickMode?: boolean;
  onMapClick?: (coords: { lat: number; lon: number }) => void;
}

// Initial camera: whole-world for the global view, tighter once we have a
// focus. The page flies to projects/search results after mount.
const WORLD_VIEW = { longitude: 12, latitude: 30, zoom: 1.4 };
const FOCUS_ZOOM = 15;

// A project map opens on the site itself, close enough that the streets
// style draws building footprints and named roads (both appear from about
// z14), and tilted so the style's extruded buildings read as houses rather
// than as flat outlines. The globe engine cannot show either: its imagery is
// shaded relief, see ./CesiumViewer.
const PROJECT_ZOOM = 16;
const PROJECT_PITCH = 45;

// Pin colours match the ones the globe engine uses for the same layers.
const PIN_COLOURS = { hse: '#dc2626', punch: '#f97316', diary: '#1e90ff' } as const;

/**
 * Rough eye-altitude estimate from the map zoom so the shared HUD (built
 * for the 3D camera) still shows a sensible altitude readout in 2D.
 */
function altitudeFromZoom(zoom: number, lat: number): number {
  return (591657550.5 / 2 ** zoom) * Math.cos((lat * Math.PI) / 180);
}

/** Validate an overlay's four corners for a MapLibre image source. */
function overlayCoordinates(
  o: GeoRasterOverlay,
): [[number, number], [number, number], [number, number], [number, number]] | null {
  const c = o.corners_geojson;
  if (!Array.isArray(c) || c.length !== 4) return null;
  const [nw, ne, se, sw] = c;
  if (!nw || !ne || !se || !sw) return null;
  for (const p of [nw, ne, se, sw]) {
    if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) return null;
  }
  // MapLibre image source wants [top-left, top-right, bottom-right,
  // bottom-left] = [NW, NE, SE, SW], which is exactly corners_geojson.
  return [
    [nw[0], nw[1]],
    [ne[0], ne[1]],
    [se[0], se[1]],
    [sw[0], sw[1]],
  ];
}

export function MapLibreViewer({
  mode,
  pins,
  basemap,
  focusedProject,
  flyToTarget,
  searchPin,
  overlayProjectId,
  overlay,
  onPinSelect,
  onMouseMove,
  onCameraChange,
  anchor,
  pickMode = false,
  onMapClick,
}: MapLibreViewerProps) {
  const { t } = useTranslation();
  const mapRef = useRef<MapRef>(null);
  const rafRef = useRef<number | null>(null);
  const meta = basemapMeta(basemap);

  const projects = pins?.projects ?? [];
  const isProject = mode === 'project';
  const anchorLat = isProject && anchor ? Number(anchor.lat) : NaN;
  const anchorLon = isProject && anchor ? Number(anchor.lon) : NaN;
  const hasAnchor = Number.isFinite(anchorLat) && Number.isFinite(anchorLon);

  // Read once, on mount: react-map-gl takes ``initialViewState`` a single
  // time, and a later anchor is reached by the fly-to effect below.
  const [initialView] = useState(() =>
    hasAnchor
      ? { longitude: anchorLon, latitude: anchorLat, zoom: PROJECT_ZOOM, pitch: PROJECT_PITCH }
      : WORLD_VIEW,
  );

  // The anchor moved after mount, a pin placed by hand or a location
  // geocoded from the address. Skips the position the map opened on, so
  // the first paint does not animate from the site to the site.
  const flownToRef = useRef<string | null>(hasAnchor ? `${anchorLat},${anchorLon}` : null);
  useEffect(() => {
    if (!hasAnchor) return;
    const key = `${anchorLat},${anchorLon}`;
    if (flownToRef.current === key) return;
    flownToRef.current = key;
    mapRef.current?.flyTo({
      center: [anchorLon, anchorLat],
      zoom: PROJECT_ZOOM,
      pitch: PROJECT_PITCH,
      duration: 1200,
    });
  }, [hasAnchor, anchorLat, anchorLon]);

  const crossModulePins = useMemo(() => {
    if (!isProject || !pins) return [];
    const out: { tag: string; lat: number; lon: number; colour: string; title: string }[] = [];
    const push = (tag: string, lat: unknown, lon: unknown, colour: string, title: string) => {
      const la = Number(lat);
      const lo = Number(lon);
      if (Number.isFinite(la) && Number.isFinite(lo)) out.push({ tag, lat: la, lon: lo, colour, title });
    };
    const hseLabel = t('geo_hub.legend.hse', { defaultValue: 'Safety incidents' });
    const punchLabel = t('geo_hub.legend.punchlist', { defaultValue: 'Punch list' });
    const diaryLabel = t('geo_hub.legend.diary', { defaultValue: 'Site photos' });
    for (const p of pins.hse ?? []) {
      push(`hse:${p.incident_id}`, p.lat, p.lon, PIN_COLOURS.hse, `${hseLabel}: ${p.title || p.incident_number}`);
    }
    for (const p of pins.punchlist ?? []) {
      push(`punch:${p.item_id}`, p.lat, p.lon, PIN_COLOURS.punch, `${punchLabel}: ${p.title}`);
    }
    for (const p of pins.diary ?? []) {
      push(`diary:${p.photo_id}`, p.lat, p.lon, PIN_COLOURS.diary, diaryLabel);
    }
    return out;
  }, [isProject, pins, t]);

  // Drawing overlays (raster PDFs / DWGs / images) for the project in
  // context. Only visible overlays - hidden ones never paint here.
  const overlaysQuery = useQuery({
    queryKey: ['geo-hub', 'raster-overlays', overlayProjectId],
    queryFn: () => listRasterOverlays(overlayProjectId as string),
    enabled: Boolean(overlayProjectId),
    staleTime: 15_000,
  });
  const overlays = useMemo(
    () =>
      (overlaysQuery.data ?? [])
        .filter((o) => o.visible)
        .map((o) => ({ overlay: o, coords: overlayCoordinates(o) }))
        .filter((x): x is { overlay: GeoRasterOverlay; coords: NonNullable<ReturnType<typeof overlayCoordinates>> } => x.coords !== null)
        // z_order ascending - later layers paint on top.
        .sort((a, b) => (a.overlay.z_order ?? 0) - (b.overlay.z_order ?? 0)),
    [overlaysQuery.data],
  );

  // MapLibre fetches tiles + overlay images itself, so it cannot use the
  // app's axios auth interceptor. The raster-overlay PNG endpoint is
  // tenant-scoped and 401s without a bearer, so inject it here for any
  // same-origin /api request. (The tile proxy is public, so the header is
  // simply ignored there.)
  const transformRequest = useCallback((url: string) => {
    if (url.startsWith('/api') || url.includes('/api/v1/geo-hub/')) {
      const headers = geoAuthHeaders();
      if (headers.Authorization) return { url, headers };
    }
    return { url };
  }, []);

  // Fly to a focused project when it changes.
  useEffect(() => {
    if (!focusedProject) return;
    const lat = Number(focusedProject.lat);
    const lon = Number(focusedProject.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    mapRef.current?.flyTo({ center: [lon, lat], zoom: FOCUS_ZOOM, duration: 1200 });
  }, [focusedProject]);

  // Generic fly-to (overlay rows, clusters, search). Keyed by nonce.
  useEffect(() => {
    if (!flyToTarget) return;
    if (!Number.isFinite(flyToTarget.lat) || !Number.isFinite(flyToTarget.lon)) {
      return;
    }
    mapRef.current?.flyTo({
      center: [flyToTarget.lon, flyToTarget.lat],
      zoom: FOCUS_ZOOM,
      duration: 1200,
    });
  }, [flyToTarget]);

  // Fly to the search pin when it appears.
  useEffect(() => {
    if (!searchPin) return;
    if (!Number.isFinite(searchPin.lat) || !Number.isFinite(searchPin.lon)) return;
    mapRef.current?.flyTo({
      center: [searchPin.lon, searchPin.lat],
      zoom: Math.max(FOCUS_ZOOM - 2, 12),
      duration: 1200,
    });
  }, [searchPin]);

  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  const handleMouseMove = useCallback(
    (e: MapLayerMouseEvent) => {
      if (!onMouseMove) return;
      const { lng, lat } = e.lngLat;
      // Throttle to one update per frame so React state doesn't thrash.
      if (rafRef.current !== null) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        onMouseMove({ lat, lon: lng, altitudeM: 0 });
      });
    },
    [onMouseMove],
  );

  const handleMove = useCallback(
    (e: ViewStateChangeEvent) => {
      if (!onCameraChange) return;
      const { zoom, latitude, bearing } = e.viewState;
      onCameraChange({
        headingDeg: ((bearing % 360) + 360) % 360,
        cameraAltitudeM: altitudeFromZoom(zoom, latitude),
      });
    },
    [onCameraChange],
  );

  const handleClick = useCallback(
    (e: MapLayerMouseEvent) => {
      if (!pickMode || !onMapClick) return;
      onMapClick({ lat: e.lngLat.lat, lon: e.lngLat.lng });
    },
    [pickMode, onMapClick],
  );

  return (
    <div
      className="relative h-full w-full"
      style={{ backgroundColor: BASEMAP_BACKDROP[basemap] }}
      data-testid="geo-maplibre-viewer"
      data-basemap={basemap}
      data-mode={mode}
      data-pick-mode={pickMode ? 'on' : 'off'}
    >
      <Map
        ref={mapRef}
        initialViewState={initialView}
        mapStyle={buildBasemapStyle(basemap)}
        style={{ width: '100%', height: '100%' }}
        cursor={pickMode ? 'crosshair' : undefined}
        // The global view stays flat "like paper". A project map may tilt
        // and turn, which is what makes the extruded buildings useful.
        dragRotate={isProject}
        pitchWithRotate={isProject}
        touchZoomRotate={isProject}
        attributionControl={false}
        transformRequest={transformRequest}
        onMouseMove={handleMouseMove}
        onMouseOut={() => onMouseMove?.(null)}
        onMove={handleMove}
        onClick={handleClick}
      >
        <NavigationControl position="top-right" showCompass={isProject} visualizePitch={isProject} />
        <ScaleControl position="bottom-right" />
        {!meta.offline && (
          <AttributionControl
            compact
            customAttribution={TILE_ATTRIBUTION_HTML}
          />
        )}

        {/* Drawing overlays - one image source + raster layer each. */}
        {overlays.map(({ overlay: o, coords }) => (
          <Source
            key={o.id}
            id={`oe-overlay-${o.id}`}
            type="image"
            url={rasterOverlayImageUrl(o.id)}
            coordinates={coords}
          >
            <Layer
              id={`oe-overlay-layer-${o.id}`}
              type="raster"
              paint={{ 'raster-opacity': Number(o.opacity) || 1 }}
            />
          </Source>
        ))}

        {/* Project pins. */}
        {mode === 'global' &&
          projects.map((p) => {
            const lat = Number(p.lat);
            const lon = Number(p.lon);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
            const color = colorForProjectStatus(p.status ?? null);
            return (
              <Marker
                key={p.project_id}
                longitude={lon}
                latitude={lat}
                anchor="bottom"
                onClick={(e) => {
                  e.originalEvent.stopPropagation();
                  onPinSelect?.({ tag: `project:${p.project_id}` });
                }}
              >
                <button
                  type="button"
                  className="relative flex h-7 w-7 items-center justify-center focus:outline-none"
                  title={pinTooltipLabel(p)}
                  aria-label={pinTooltipLabel(p)}
                >
                  <span
                    className="flex h-5 w-5 items-center justify-center rounded-full text-white shadow-md ring-2 ring-white"
                    style={{ backgroundColor: color }}
                  >
                    <MapPin size={11} fill="currentColor" strokeWidth={0} />
                  </span>
                </button>
              </Marker>
            );
          })}

        {/* Safety, punch and site-photo pins. Tags use the ``kind:id`` form
            the page's pin handler splits, the same as the globe's. */}
        {crossModulePins.map((p) => (
          <Marker
            key={p.tag}
            longitude={p.lon}
            latitude={p.lat}
            anchor="center"
            onClick={(e) => {
              e.originalEvent.stopPropagation();
              if (!pickMode) onPinSelect?.({ tag: p.tag });
            }}
          >
            <button
              type="button"
              className="block h-3.5 w-3.5 rounded-full shadow ring-2 ring-white focus:outline-none focus-visible:ring-oe-blue"
              style={{ backgroundColor: p.colour }}
              title={p.title}
              aria-label={p.title}
              data-testid={`geo-2d-pin-${p.tag.split(':')[0]}`}
            />
          </Marker>
        ))}

        {/* The project's own location. */}
        {hasAnchor && (
          <Marker longitude={anchorLon} latitude={anchorLat} anchor="bottom">
            <div
              className="relative flex h-8 w-8 items-center justify-center"
              title={anchor?.label}
              aria-label={anchor?.label}
              data-testid="geo-2d-project-pin"
            >
              <span className="absolute inset-0 rounded-full bg-oe-blue/25 animate-ping" />
              <span className="relative flex h-6 w-6 items-center justify-center rounded-full bg-oe-blue text-white shadow-lg shadow-oe-blue/40 ring-2 ring-white">
                <MapPin size={14} fill="currentColor" strokeWidth={0} />
              </span>
            </div>
          </Marker>
        )}

        {/* Transient address-search pin. */}
        {searchPin &&
          Number.isFinite(searchPin.lat) &&
          Number.isFinite(searchPin.lon) && (
            <Marker
              longitude={searchPin.lon}
              latitude={searchPin.lat}
              anchor="bottom"
            >
              <div
                className="relative flex h-8 w-8 items-center justify-center"
                aria-label={searchPin.name}
                title={searchPin.name}
              >
                <span className="absolute inset-0 rounded-full bg-sky-500/25 animate-ping" />
                <span className="relative flex h-6 w-6 items-center justify-center rounded-full bg-sky-500 text-white shadow-lg ring-2 ring-white">
                  <MapPin size={14} fill="currentColor" strokeWidth={0} />
                </span>
              </div>
            </Marker>
          )}
      </Map>

      {/* Floating chrome (rail / search / HUD / empty state) over the map. */}
      {overlay}
    </div>
  );
}

export default MapLibreViewer;
