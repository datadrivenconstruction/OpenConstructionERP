/**
 * ProjectMap — modern vector-tile map for a project's location.
 *
 * Two sizes:
 *   variant="card"     → static thumbnail, no zoom / pan — fits in the
 *                        project list card and loads instantly.
 *   variant="detail"   → full interactive map — pan, zoom, pin, address
 *                        overlay.  Lives on the project detail page.
 *
 * Engine: MapLibre GL JS (open-source vector-tile renderer, no Leaflet
 * branding). Tiles come from OpenFreeMap (free, key-less, community-funded),
 * with CartoDB Voyager raster as a fallback if the vector style fails.
 *
 * The geocoding pipeline:
 *   1. Accept lat/lng directly (fastest path — stored in project metadata).
 *   2. Otherwise concat (address, city, country), look up via the free
 *      OpenStreetMap Nominatim endpoint, and cache the result in
 *      localStorage under `oe.geocode.<query>` so repeat renders don't
 *      hit the API.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MapPin, Loader2 } from 'lucide-react';
import Map, { Marker, Popup, NavigationControl, AttributionControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import clsx from 'clsx';

// OpenFreeMap — free, no API key, OSM-community-funded vector tiles.
// "Liberty" style = colorful, highway-emphasis; "Positron" = minimal light;
// "Bright" = high-contrast. Liberty fits a construction/infra use case best.
const MAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';

export interface LatLng {
  lat: number;
  lng: number;
}

interface ProjectMapProps {
  /** Direct coordinates — skips geocoding.  Stored in project metadata. */
  lat?: number | null;
  lng?: number | null;
  /** Components of an address to feed Nominatim when lat/lng are absent. */
  address?: string | null;
  city?: string | null;
  country?: string | null;
  /** Display variant.  `card` = static thumbnail, `detail` = interactive. */
  variant?: 'card' | 'detail';
  /** Optional extra classes (height / border overrides). */
  className?: string;
  /** Human-readable label shown in the marker popup and overlay chip. */
  label?: string;
  /** Called once lat/lng are known.  Let the parent persist the result
   *  back to the project so subsequent renders skip geocoding. */
  onResolved?: (coords: LatLng) => void;
}

interface GeocodeCacheEntry {
  lat: number;
  lng: number;
  at: number;
}

const CACHE_PREFIX = 'oe.geocode.';
const CACHE_TTL_MS = 1000 * 60 * 60 * 24 * 30; // 30 days — addresses rarely move

function cacheKey(q: string) {
  return CACHE_PREFIX + q.toLowerCase().trim();
}

function readCache(q: string): LatLng | null {
  try {
    const raw = localStorage.getItem(cacheKey(q));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as GeocodeCacheEntry;
    if (Date.now() - parsed.at > CACHE_TTL_MS) return null;
    return { lat: parsed.lat, lng: parsed.lng };
  } catch {
    return null;
  }
}

function writeCache(q: string, coords: LatLng) {
  try {
    const entry: GeocodeCacheEntry = { ...coords, at: Date.now() };
    localStorage.setItem(cacheKey(q), JSON.stringify(entry));
  } catch {
    /* quota full, ignore */
  }
}

async function geocode(query: string, signal?: AbortSignal): Promise<LatLng | null> {
  const cached = readCache(query);
  if (cached) return cached;

  const url =
    'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' +
    encodeURIComponent(query);
  try {
    const res = await fetch(url, {
      signal,
      headers: { 'Accept': 'application/json' },
    });
    if (!res.ok) return null;
    const rows = (await res.json()) as Array<{ lat: string; lon: string }>;
    const first = rows[0];
    if (!first) return null;
    const coords: LatLng = { lat: parseFloat(first.lat), lng: parseFloat(first.lon) };
    writeCache(query, coords);
    return coords;
  } catch {
    return null;
  }
}

/**
 * Build the query string we feed to Nominatim from a project's fields.
 * Returns null if there's nothing worth geocoding.
 */
export function buildGeocodeQuery(
  address?: string | null,
  city?: string | null,
  country?: string | null,
): string | null {
  const parts = [address, city, country].filter(
    (p): p is string => !!p && p.trim().length > 0,
  );
  if (parts.length === 0) return null;
  return parts.join(', ');
}

export function ProjectMap({
  lat,
  lng,
  address,
  city,
  country,
  variant = 'detail',
  className,
  label,
  onResolved,
}: ProjectMapProps) {
  const { t } = useTranslation();
  const hasExplicitCoords =
    typeof lat === 'number' && typeof lng === 'number' && !Number.isNaN(lat) && !Number.isNaN(lng);

  const [resolved, setResolved] = useState<LatLng | null>(
    hasExplicitCoords ? { lat: lat as number, lng: lng as number } : null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [popupOpen, setPopupOpen] = useState(false);

  const query = useMemo(
    () => (hasExplicitCoords ? null : buildGeocodeQuery(address, city, country)),
    [hasExplicitCoords, address, city, country],
  );

  useEffect(() => {
    if (hasExplicitCoords) {
      setResolved({ lat: lat as number, lng: lng as number });
      return;
    }
    if (!query) {
      setResolved(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    geocode(query, controller.signal)
      .then((coords) => {
        if (controller.signal.aborted) return;
        if (coords) {
          setResolved(coords);
          onResolved?.(coords);
        } else {
          setError(true);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // onResolved intentionally omitted — parents often pass an inline
    // callback; re-running the fetch on every render would hammer Nominatim.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasExplicitCoords, lat, lng, query]);

  const isCard = variant === 'card';
  const heightClass = isCard ? 'h-28' : 'h-80';

  const shell = (content: React.ReactNode) => (
    <div
      className={clsx(
        'relative overflow-hidden rounded-xl border border-border-light bg-gradient-to-br from-slate-100 via-slate-50 to-blue-50/30 dark:from-slate-900 dark:via-slate-900/60 dark:to-slate-800',
        heightClass,
        className,
      )}
    >
      {content}
    </div>
  );

  if (!resolved && !loading && !query) {
    return shell(
      <div className="absolute inset-0 flex items-center justify-center text-content-quaternary">
        <MapPin size={isCard ? 20 : 28} strokeWidth={1.5} />
      </div>,
    );
  }

  if (loading) {
    return shell(
      <div className="absolute inset-0 flex items-center justify-center gap-2 text-content-tertiary">
        <Loader2 size={14} className="animate-spin" />
        <span className="text-[11px] font-medium">
          {t('projects.map_locating', { defaultValue: 'Locating…' })}
        </span>
      </div>,
    );
  }

  if (error || !resolved) {
    return shell(
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-content-quaternary">
        <MapPin size={isCard ? 18 : 24} strokeWidth={1.5} />
        <span className="text-[10px] font-medium">
          {query || t('projects.map_no_location', { defaultValue: 'No location set' })}
        </span>
      </div>,
    );
  }

  const zoom = isCard ? 10 : 13;

  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded-xl border border-border-light',
        heightClass,
        className,
      )}
    >
      <Map
        initialViewState={{
          longitude: resolved.lng,
          latitude: resolved.lat,
          zoom,
        }}
        mapStyle={MAP_STYLE_URL}
        style={{ width: '100%', height: '100%' }}
        interactive={!isCard}
        dragPan={!isCard}
        dragRotate={false}
        scrollZoom={!isCard}
        doubleClickZoom={!isCard}
        touchZoomRotate={!isCard}
        keyboard={!isCard}
        attributionControl={false}
      >
        {!isCard && <NavigationControl position="top-right" showCompass={false} />}
        {!isCard && (
          <AttributionControl
            compact
            customAttribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · <a href="https://openfreemap.org">OpenFreeMap</a>'
          />
        )}

        <Marker
          longitude={resolved.lng}
          latitude={resolved.lat}
          anchor="bottom"
          onClick={(e) => {
            e.originalEvent.stopPropagation();
            if (!isCard && label) setPopupOpen(true);
          }}
        >
          <div
            className="relative flex h-8 w-8 items-center justify-center"
            aria-label={label || 'Project location'}
          >
            <span className="absolute inset-0 rounded-full bg-oe-blue/25 animate-ping" />
            <span className="relative flex h-6 w-6 items-center justify-center rounded-full bg-oe-blue text-white shadow-lg shadow-oe-blue/40 ring-2 ring-white">
              <MapPin size={14} fill="currentColor" strokeWidth={0} />
            </span>
          </div>
        </Marker>

        {popupOpen && !isCard && label && (
          <Popup
            longitude={resolved.lng}
            latitude={resolved.lat}
            anchor="bottom"
            onClose={() => setPopupOpen(false)}
            closeButton
            closeOnClick={false}
            offset={28}
          >
            <div className="text-xs font-medium text-content-primary">{label}</div>
          </Popup>
        )}
      </Map>

      {/* Card variant: subtle gradient + address chip so it reads as a
          "location thumbnail" rather than a random tile. */}
      {isCard && (
        <>
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />
          {(label || query) && (
            <div className="pointer-events-none absolute inset-x-2 bottom-2 flex items-center gap-1 rounded-md bg-surface-elevated/90 backdrop-blur-sm px-2 py-1 shadow-sm">
              <MapPin size={11} className="shrink-0 text-oe-blue" />
              <span className="truncate text-[11px] font-medium text-content-primary">
                {label || query}
              </span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
