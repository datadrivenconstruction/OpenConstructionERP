// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Map as MapIcon, MapPin } from 'lucide-react';
import clsx from 'clsx';
import type { MapRef, MarkerProps } from 'react-map-gl/maplibre';
import { buildGeocodeQuery } from '@/shared/ui/ProjectMap/geocode';
import { geocodeSuggest } from '@/features/geo-hub/api';
import {
  TILE_ATTRIBUTION_HTML,
  useStreetBasemapStyleUrl,
} from '@/shared/ui/ProjectMap/basemap';
// maplibre-gl ships its canvas / control styles separately. The static
// import lets Vite hoist the CSS into the dashboard chunk so markers
// have correct positioning the moment the JS module resolves —
// dynamic CSS imports leave the Marker positioned at (0,0) of the
// page until the browser commits the style sheet, which is the second
// half of the "no-pins" bug the user reported.
import 'maplibre-gl/dist/maplibre-gl.css';

const CACHE_PREFIX = 'oe.geocode.';
const CACHE_TTL_MS = 1000 * 60 * 60 * 24 * 30;

// Dynamic-import both Map and Marker together via a single shared state
// in the parent. The previous pattern (``lazy()`` for Map + per-marker
// inline ``import()`` inside each ``MarkerPin``) suffered a React 18 +
// Suspense race: the first render of every MarkerPin returned ``null``
// because its own dynamic import hadn't resolved yet, and although the
// follow-up ``setMarker`` call did trigger a second render, the
// markers never actually showed up in production for some users —
// likely because MapLibre's children registration runs once during the
// first child render and the late-arriving Marker components weren't
// attached to the underlying GL canvas. Fixing the lazy pattern at
// once: the parent waits for the whole module, then renders both the
// Map and all Markers in a single pass with the cached components.
type MapLibreModule = typeof import('react-map-gl/maplibre');

export interface ProjectPin {
  id: string;
  name: string;
  lat?: number | null;
  lng?: number | null;
  city?: string | null;
  country?: string | null;
  address?: string | null;
  region?: string | null;
}

interface DashboardProjectsMapProps {
  projects: ProjectPin[];
  className?: string;
  /** Override the count-scaled default height (e.g. the dashboard
   *  side-by-side layout wants a taller map than a bare full-width row). */
  heightClass?: string;
}

interface ResolvedMarker {
  id: string;
  name: string;
  lat: number;
  lng: number;
  region?: string | null;
}

interface CacheEntry {
  lat: number;
  lng: number;
  at: number;
}

function readCache(q: string): { lat: number; lng: number } | null {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + q.toLowerCase().trim());
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEntry;
    if (Date.now() - parsed.at > CACHE_TTL_MS) return null;
    if (!Number.isFinite(parsed.lat) || !Number.isFinite(parsed.lng)) return null;
    return { lat: parsed.lat, lng: parsed.lng };
  } catch {
    return null;
  }
}

function writeCache(q: string, lat: number, lng: number) {
  try {
    localStorage.setItem(
      CACHE_PREFIX + q.toLowerCase().trim(),
      JSON.stringify({ lat, lng, at: Date.now() } as CacheEntry),
    );
  } catch {
    /* quota full */
  }
}

async function geocodeOne(query: string, signal: AbortSignal): Promise<{ lat: number; lng: number } | null> {
  const cached = readCache(query);
  if (cached) return cached;
  // Goes to GET /api/v1/geo-hub/geocode/suggest, never to a public
  // geocoder from the browser. A browser cannot set a User-Agent, so a
  // direct call is unidentifiable and unthrottled and it fans out over
  // every user's IP, which the Nominatim usage policy forbids. The
  // backend tries Photon first, falls back to Nominatim behind a
  // process-global 1 req/s gate, and sends a contact User-Agent.
  // ``geocodeSuggest`` throws on a non-2xx and rejects on abort; the
  // catch below turns both into the same null a miss already produced.
  try {
    const res = await geocodeSuggest(query, { limit: 1, signal });
    const first = res.suggestions[0];
    if (!first) return null;
    const lat = Number(first.lat);
    const lng = Number(first.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
    writeCache(query, lat, lng);
    return { lat, lng };
  } catch {
    return null;
  }
}

// Region → broad lat/lng fallback so projects without an address still
// land on the right continent. Keys cover both single-country labels
// ("germany") and the higher-level region groupings the project model
// actually uses ("dach", "europe", "middle east", "asia-pacific", …)
// so demo data with `region: "DACH"` doesn't silently drop off the map.
const REGION_FALLBACK: Record<string, { lat: number; lng: number }> = {
  // Country-level
  germany: { lat: 51.165, lng: 10.451 },
  austria: { lat: 47.516, lng: 14.55 },
  switzerland: { lat: 46.818, lng: 8.227 },
  france: { lat: 46.227, lng: 2.213 },
  uk: { lat: 54.0, lng: -2.0 },
  'united kingdom': { lat: 54.0, lng: -2.0 },
  britain: { lat: 54.0, lng: -2.0 },
  spain: { lat: 40.463, lng: -3.749 },
  italy: { lat: 41.871, lng: 12.567 },
  netherlands: { lat: 52.13, lng: 5.291 },
  poland: { lat: 51.919, lng: 19.145 },
  usa: { lat: 39.83, lng: -98.58 },
  us: { lat: 39.83, lng: -98.58 },
  'united states': { lat: 39.83, lng: -98.58 },
  'united states of america': { lat: 39.83, lng: -98.58 },
  america: { lat: 39.83, lng: -98.58 },
  canada: { lat: 56.13, lng: -106.34 },
  brazil: { lat: -14.235, lng: -51.925 },
  mexico: { lat: 23.635, lng: -102.553 },
  russia: { lat: 61.524, lng: 105.318 },
  china: { lat: 35.861, lng: 104.195 },
  india: { lat: 20.594, lng: 78.962 },
  australia: { lat: -25.274, lng: 133.775 },
  japan: { lat: 36.204, lng: 138.252 },
  uae: { lat: 23.424, lng: 53.848 },
  'united arab emirates': { lat: 23.424, lng: 53.848 },
  'saudi arabia': { lat: 23.886, lng: 45.079 },
  // Higher-level region groupings used in the project model
  dach: { lat: 49.5, lng: 10.5 },          // ~middle of DE/AT/CH
  europe: { lat: 50.0, lng: 10.0 },
  eu: { lat: 50.0, lng: 10.0 },
  'middle east': { lat: 27.0, lng: 45.0 }, // ~middle of GCC region
  gcc: { lat: 27.0, lng: 45.0 },
  asia: { lat: 34.047, lng: 100.619 },
  'asia-pacific': { lat: 0.0, lng: 120.0 },
  asiapacific: { lat: 0.0, lng: 120.0 },
  apac: { lat: 0.0, lng: 120.0 },
  'latin america': { lat: -14.235, lng: -60.0 },
  latam: { lat: -14.235, lng: -60.0 },
  'south america': { lat: -14.235, lng: -60.0 },
  'north america': { lat: 45.0, lng: -100.0 },
  africa: { lat: 0.0, lng: 20.0 },
  oceania: { lat: -25.0, lng: 140.0 },
};

function regionFallback(region?: string | null): { lat: number; lng: number } | null {
  if (!region) return null;
  const key = region.toLowerCase().trim();
  return REGION_FALLBACK[key] ?? null;
}

// Synchronous best-effort coordinate resolution shared with the dashboard
// sites panel: explicit lat/lng, then a cached geocode, then the coarse
// region centroid. No network call here - the map component's async
// geocoder fills the shared cache, which this reads on the next render.
export function resolveProjectCoords(p: ProjectPin): { lat: number; lng: number } | null {
  if (Number.isFinite(p.lat) && Number.isFinite(p.lng)) {
    return { lat: p.lat as number, lng: p.lng as number };
  }
  const q = buildGeocodeQuery(p.address, p.city, p.country);
  const cached = q ? readCache(q) : null;
  if (cached) return cached;
  return regionFallback(p.region);
}

export function DashboardProjectsMap({ projects, className, heightClass: heightClassProp }: DashboardProjectsMapProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [resolved, setResolved] = useState<ResolvedMarker[]>([]);
  const [mapLib, setMapLib] = useState<MapLibreModule | null>(null);
  const streetStyleUrl = useStreetBasemapStyleUrl();
  const mapRef = useRef<MapRef | null>(null);

  // Pull the maplibre bundle once. Cached by Vite after first call so
  // subsequent dashboard visits resolve synchronously. CSS for the GL
  // canvas comes via the static side-effect import below the
  // component (kept off the main bundle because this whole module is
  // route-split via DashboardPage).
  useEffect(() => {
    let cancelled = false;
    import('react-map-gl/maplibre').then((mod) => {
      if (!cancelled) setMapLib(mod);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const out: ResolvedMarker[] = [];

    // Seed with explicit lat/lng + cached geocodes + region-fallback so
    // the map populates instantly — slow Nominatim queries fill in over time.
    for (const p of projects) {
      if (Number.isFinite(p.lat) && Number.isFinite(p.lng)) {
        out.push({
          id: p.id,
          name: p.name,
          region: p.region,
          lat: p.lat as number,
          lng: p.lng as number,
        });
        continue;
      }
      const q = buildGeocodeQuery(p.address, p.city, p.country);
      const cached = q ? readCache(q) : null;
      if (cached) {
        out.push({ id: p.id, name: p.name, region: p.region, lat: cached.lat, lng: cached.lng });
        continue;
      }
      const fallback = regionFallback(p.region);
      if (fallback) {
        out.push({ id: p.id, name: p.name, region: p.region, lat: fallback.lat, lng: fallback.lng });
      }
    }
    setResolved(out);

    // Pace the lookups at ~1 req/sec. The backend already enforces the
    // rate limit for the Nominatim fallback, but pacing here keeps a
    // portfolio of thirty projects from queueing thirty requests behind
    // that one-at-a-time gate the moment the dashboard mounts.
    (async () => {
      for (const p of projects) {
        if (controller.signal.aborted) return;
        if (Number.isFinite(p.lat) && Number.isFinite(p.lng)) continue;
        const q = buildGeocodeQuery(p.address, p.city, p.country);
        if (!q) continue;
        const cached = readCache(q);
        if (cached) continue;
        const coords = await geocodeOne(q, controller.signal);
        if (controller.signal.aborted) return;
        if (!coords) continue;
        setResolved((prev) => {
          const idx = prev.findIndex((m) => m.id === p.id);
          if (idx === -1) return [...prev, { id: p.id, name: p.name, region: p.region, ...coords }];
          const next = prev.slice();
          const existing = next[idx]!;
          next[idx] = { ...existing, lat: coords.lat, lng: coords.lng };
          return next;
        });
        await new Promise((r) => setTimeout(r, 1000));
      }
    })();

    return () => controller.abort();
  }, [projects]);

  const initialView = useMemo(() => {
    if (resolved.length === 0) {
      return { longitude: 10, latitude: 30, zoom: 1.4 };
    }
    if (resolved.length === 1) {
      const only = resolved[0]!;
      return { longitude: only.lng, latitude: only.lat, zoom: 5 };
    }
    const lats = resolved.map((m) => m.lat);
    const lngs = resolved.map((m) => m.lng);
    return {
      longitude: (Math.min(...lngs) + Math.max(...lngs)) / 2,
      latitude: (Math.min(...lats) + Math.max(...lats)) / 2,
      zoom: 1.6,
    };
  }, [resolved]);

  // Whenever resolved changes (initial seed + as Nominatim fills in
  // more markers), refit bounds so every project is visible. The
  // initialViewState only handles the very first render — without
  // fitBounds the map stays at zoom 1.6 even after markers arrive.
  useEffect(() => {
    if (resolved.length < 2) return;
    const map = mapRef.current;
    if (!map) return;
    const lats = resolved.map((m) => m.lat);
    const lngs = resolved.map((m) => m.lng);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);
    // Sub-degree spans get a tiny degree-pad so a single-city cluster
    // doesn't zoom to street level. Geographic pad (degrees) is small
    // because the screen-side `padding` below carries most of the
    // breathing room around each marker pin.
    const pad = Math.max(0.2, (maxLat - minLat) * 0.05);
    map.fitBounds(
      [
        [minLng - pad, minLat - pad],
        [maxLng + pad, maxLat + pad],
      ],
      {
        // Asymmetric screen padding: pin glyphs are anchored at the
        // bottom of their wrapper, so a few extra px on top keeps the
        // top-most marker fully on canvas while sides + bottom stay
        // tight to the markers.
        padding: { top: 18, bottom: 8, left: 12, right: 12 },
        duration: 600,
        maxZoom: 7,
      },
    );
  }, [resolved]);

  if (projects.length === 0) {
    return null;
  }

  const Map = mapLib?.default;
  const Marker = mapLib?.Marker;
  // Attribution comes off the same dynamically-imported module as Map and
  // Marker rather than a top-level import, because a static
  // ``import { AttributionControl } from 'react-map-gl/maplibre'`` would
  // pull the whole maplibre chunk eagerly into the dashboard bundle and
  // undo the reason this file resolves the library lazily at all.
  const Attribution = mapLib?.AttributionControl;

  // Map height scales with project count — a 1-2 project workspace doesn't
  // need 256px of map real estate. Saves vertical space on small portfolios.
  const heightClass =
    heightClassProp ??
    (projects.length <= 3 ? 'h-48' : projects.length <= 6 ? 'h-56' : 'h-64');

  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded-xl border border-border-light',
        'bg-gradient-to-br from-slate-100 via-slate-50 to-blue-50/30',
        'dark:from-slate-900 dark:via-slate-900/60 dark:to-slate-800',
        heightClass,
        className,
      )}
    >
      {Map && Marker && Attribution ? (
        <Map
          ref={(instance: MapRef | null) => {
            mapRef.current = instance;
          }}
          initialViewState={initialView}
          mapStyle={streetStyleUrl}
          style={{ width: '100%', height: '100%' }}
          interactive
          dragRotate={false}
          attributionControl={false}
        >
          {/* The built-in control is off so it can be replaced with the
              compact one below. OpenStreetMap data is ODbL and the tiles
              rendered from it are a Produced Work, which owes attribution,
              so this must stay mounted for as long as the map draws OSM
              tiles. The credit is imported, not retyped, so it cannot drift
              from the other surfaces (ProjectMap, MapLibreViewer). */}
          <Attribution
            compact
            customAttribution={TILE_ATTRIBUTION_HTML}
          />
          {resolved.map((m) => (
            <Marker
              key={m.id}
              longitude={m.lng}
              latitude={m.lat}
              anchor="bottom"
              onClick={(e: Parameters<NonNullable<MarkerProps['onClick']>>[0]) => {
                e.originalEvent.stopPropagation();
                navigate(`/projects/${m.id}`);
              }}
            >
              <div
                className="relative flex h-7 w-7 items-center justify-center cursor-pointer group"
                title={m.name}
                aria-label={m.name}
              >
                <span className="absolute inset-0 rounded-full bg-oe-blue/25 opacity-0 group-hover:opacity-100 transition-opacity animate-ping" />
                <span className="relative flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white shadow-md shadow-oe-blue/40 ring-2 ring-white">
                  <MapPin size={11} fill="currentColor" strokeWidth={0} />
                </span>
              </div>
            </Marker>
          ))}
        </Map>
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-content-tertiary">
          <MapIcon size={24} strokeWidth={1.5} />
        </div>
      )}

      {/* Legend chip */}
      <div className="pointer-events-none absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-md bg-surface-elevated/90 backdrop-blur-sm px-2 py-1 shadow-sm">
        <MapIcon size={11} className="text-oe-blue" strokeWidth={2} />
        <span className="text-[11px] font-medium text-content-primary">
          {t('dashboard.map_title', { defaultValue: 'Project locations' })}
        </span>
        <span className="text-[10px] text-content-tertiary tabular-nums">
          {resolved.length}/{projects.length}
        </span>
      </div>
    </div>
  );
}
