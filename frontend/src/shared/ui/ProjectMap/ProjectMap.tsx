/**
 * ProjectMap — lightweight OSM map for a project's location.
 *
 * Two sizes:
 *   variant="card"     → static thumbnail, no zoom / pan — fits in the
 *                        project list card and loads instantly.
 *   variant="detail"   → full interactive map — pan, zoom, pin, address
 *                        overlay.  Lives on the project detail page.
 *
 * The geocoding pipeline:
 *   1. Accept lat/lng directly (fastest path — stored in project metadata).
 *   2. Otherwise concat (address, city, country), look up via the free
 *      OpenStreetMap Nominatim endpoint, and cache the result in
 *      localStorage under `oe.geocode.<query>` so repeat renders don't
 *      hit the API.
 *
 * Why no Google Maps / Mapbox?  The app ships as self-hosted open-source;
 * shipping an API key (or forcing users to provision one) would break the
 * "download → run" story.  Nominatim + OSM tiles are CC-BY attributed,
 * require no key, and stay within reasonable usage limits for demo /
 * project use.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MapPin, Loader2 } from 'lucide-react';
import L from 'leaflet';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import clsx from 'clsx';

// Leaflet's default marker icon ships as a relative path that breaks with
// Vite — bundlers see `url(marker-icon.png)` inside leaflet.css but the
// runtime JS calls `Icon.Default.prototype._getIconUrl()` which tries to
// auto-derive the path from the bundle URL and fails.  Fix by (1) deleting
// the broken prototype method so `mergeOptions` actually wins, (2) using
// Vite's `?url` suffix to force the PNG imports to return final asset URLs.
import markerIcon from 'leaflet/dist/images/marker-icon.png?url';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png?url';
import markerShadow from 'leaflet/dist/images/marker-shadow.png?url';

// Prototype pollution: remove the url-deriving method so our mergeOptions
// below takes effect (standard Leaflet-with-Vite workaround).
delete (L.Icon.Default.prototype as unknown as { _getIconUrl?: unknown })._getIconUrl;

L.Icon.Default.mergeOptions({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
});

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

  // Empty / loading / error states share the same shell so the card height
  // stays stable as the async geocode resolves.
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

  // We have coordinates.  Card variant: non-interactive snapshot.
  // Detail variant: full Leaflet map.
  const zoom = isCard ? 12 : 14;

  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded-xl border border-border-light',
        heightClass,
        className,
      )}
    >
      <MapContainer
        center={[resolved.lat, resolved.lng]}
        zoom={zoom}
        zoomControl={!isCard}
        scrollWheelZoom={!isCard}
        dragging={!isCard}
        doubleClickZoom={!isCard}
        touchZoom={!isCard}
        boxZoom={!isCard}
        keyboard={!isCard}
        attributionControl={!isCard}
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Marker position={[resolved.lat, resolved.lng]}>
          {!isCard && label && <Popup>{label}</Popup>}
        </Marker>
      </MapContainer>

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
