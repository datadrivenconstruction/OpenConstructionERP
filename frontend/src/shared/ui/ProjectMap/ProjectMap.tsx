// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ProjectMap — modern vector-tile map for a project's location.
 *
 * Two sizes:
 *   variant="card"     → a still image (an <img>), never a live map. Fits
 *                        in the project list card. The grid renders ~12
 *                        cards at once, so mounting a live GL map per card
 *                        would spin up 12 WebGL contexts streaming vector
 *                        tiles forever (the network never goes idle). The
 *                        thumbnail has zero ongoing work.
 *   variant="detail"   → full interactive MapLibre map — pan, zoom, pin,
 *                        address overlay. Lives on the project detail page.
 *
 * Engine: the detail variant uses MapLibre GL JS (open-source, no Leaflet
 * branding) with OpenFreeMap vector tiles served through our backend (see
 * ./basemap), so it shows real street cartography - named roads, junctions,
 * building footprints.
 *
 * The card shows the SAME cartography, as a snapshot. ./streetThumbnail
 * renders that vector style once into an offscreen MapLibre instance, reads
 * the canvas as a data URL and destroys the context; the renders are
 * serialised, so there is one transient GL context at a time and nothing
 * streaming afterwards. The result is cached per location, so a re-render
 * or a revisit costs nothing.
 *
 * When the snapshot cannot be produced - no WebGL, a blocked or failing
 * style, a render that misses its timeout - the card keeps the picture it
 * has always had: one static raster tile of public-domain shaded relief,
 * proxied verbatim by our backend and capped at z6, which is a regional
 * terrain patch rather than streets. The fallback is the reason the card
 * never shows an empty box, and it is the reason the relief source is still
 * here. The card renders the relief tile FIRST and swaps in the snapshot
 * when it arrives, so nothing is ever waiting on a blank frame.
 *
 * This block twice carried a claim that was false when read. It first said
 * the backend rendered the card PNG from vector data (it does not, it
 * proxies relief). It then said the card could not show streets at all,
 * stated as a property of an <img>, and that is what a reader believed. An
 * image tag shows whatever bytes it is handed; the constraint was the tile
 * SOURCE, and the bytes can be rendered on this side.
 *
 * Routing every tile through our own origin keeps maps working even when a
 * browser blocks public tile CDNs.
 *
 * The geocoding pipeline:
 *   1. Accept lat/lng directly (fastest path — stored in project metadata).
 *   2. Otherwise concat (address, city, country), look the string up
 *      through our own backend geocoder, and cache the result in
 *      localStorage under `oe.geocode.<query>` so repeat renders don't
 *      hit the API.
 *
 * Geocoding never leaves the browser for a public geocoder directly. A
 * browser cannot set a User-Agent, so a direct call is unidentifiable and
 * unthrottled and it fans out over every user's IP, which the Nominatim
 * usage policy forbids. The backend geocoder tries Photon first, falls
 * back to Nominatim behind a process-global 1 req/s gate, sends a contact
 * User-Agent, and lets an operator point at their own mirror via
 * OE_GEOCODER_BASE_URL.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MapPin, Loader2 } from 'lucide-react';
import Map, { Marker, Popup, NavigationControl, AttributionControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import clsx from 'clsx';

import { geocodeSuggest } from '@/features/geo-hub/api';

import {
  PROXY_TILE_BASE,
  RELIEF_ATTRIBUTION,
  RELIEF_MAX_ZOOM,
  TILE_ATTRIBUTION_HTML,
  TILE_ATTRIBUTION_TEXT,
  VECTOR_BASEMAP_STYLE_URL,
} from './basemap';
import { renderStreetThumbnail } from './streetThumbnail';

// Every map byte comes from our own backend; see ./basemap for the style,
// the credit strings and the rationale (browser tile-CDN blocking, and the
// CARTO upstream that started watermarking without changing its status
// code). The card variant is a still image because a live GL map per card
// is what the card variant exists to avoid, not because vector data was
// rejected: its picture is a snapshot of the same vector style the detail
// map draws, with the relief tile as the fallback underneath.

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

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

// ── Card thumbnail ──────────────────────────────────────────────────────
//
// The list grid renders ~12 cards at once. Mounting a live MapLibre GL
// instance per card spins up 12 WebGL contexts that stream tiles forever
// (the reason the page never reaches network-idle). So the card is an
// <img>, never a live map, and the interactive MapLibre map only mounts on
// the detail page.
//
// The image itself has two possible sources, in this order:
//   1. a street snapshot of the vector style, rendered once offscreen by
//      ./streetThumbnail and handed over as a data URL. This is the normal
//      case and the one a construction user is looking for: roads,
//      junctions, building footprints.
//   2. the relief tile below, painted immediately and left in place until
//      (and unless) the snapshot arrives.
// Both come from our same-origin proxy (see ./basemap), so the card
// renders even when a browser blocks public tile CDNs.
//
// The relief basemap stops at z6. Requesting z11 would return a blank
// tile, so the fallback asks for the deepest zoom that actually exists
// and shows a regional relief patch containing the site.
const STATIC_TILE_ZOOM = RELIEF_MAX_ZOOM;

// Zoom for the street snapshot.
//
// 15 is a neighbourhood: about 3 m per pixel, so a ~480 px wide card spans
// roughly 1.5 km. Both named roads and building footprints are drawn at
// that zoom in the vendored style, which is the whole point of the
// snapshot.
//
// Measured rather than assumed, by rendering this style through a real GL
// context and asking the map what it had drawn. At 15, six European cities
// returned 95 to 235 road segments and 12 to 46 building footprints each.
// At the retired z6 the same places returned zero buildings, zero street
// names and a dozen motorway lines - which is the founder's complaint
// stated as a number, and the reason this constant is not simply "deeper
// than 6".
//
// Deliberately not tighter. A card's coordinates often come from geocoding
// (city, country) - which is literally what the card's own label is built
// from - and a geocoder answers that with a city centroid, not a site. At
// z16 or beyond the frame would be an arbitrary downtown block with no
// context and no way for a reader to tell that the pin is approximate. At
// 15 a city-level coordinate still reads as "that city's streets", which
// is honest about what is known. When a project carries real coordinates
// the same zoom frames the site and its surrounding blocks.
const CARD_STREET_ZOOM = 15;

// Fallback size for the snapshot when the card has not been measured yet
// (first paint, or an environment with no layout such as a test runner).
// Matches the card's own ``h-28`` and a typical three-column grid width.
// Without a fallback a zero measurement would mean "never render", which
// looks identical to a working fallback and hides the difference.
const DEFAULT_CARD_THUMB_WIDTH = 480;
const DEFAULT_CARD_THUMB_HEIGHT = 112;

// Measured sizes are snapped to a step so that cards which differ by a few
// pixels of grid gutter share one cached snapshot instead of each
// rendering their own.
const THUMB_WIDTH_STEP = 32;
const THUMB_HEIGHT_STEP = 16;

function snapSize(value: number, step: number, fallback: number): number {
  if (!Number.isFinite(value) || value <= 0) return fallback;
  return Math.max(step, Math.round(value / step) * step);
}

/**
 * Whether a caller-supplied class string sets ``height`` itself, in which case
 * this component must not also emit its default. See ``heightClass``.
 *
 * ``min-h-`` and ``max-h-`` are deliberately NOT matches. They bound a height
 * rather than setting one, and the detail variant pairs ``h-full`` with
 * ``min-h-[20rem]`` on purpose, so treating those as a stated height would put
 * the collapse back for the case that works today.
 *
 * A prefixed utility such as ``md:h-96`` is not a match either, and that is
 * the safe direction: it sets a height only above its breakpoint, so standing
 * the default down for it would leave the element with no height at all below
 * one. Better to keep a default that a breakpoint utility then overrides.
 */
function hasOwnHeight(classes: string | undefined): boolean {
  if (!classes) return false;
  return classes.split(/\s+/).some((name) => /^h-\S/.test(name));
}

/** Web-Mercator lon → fractional tile X at the given zoom. */
function lngToTileX(lng: number, z: number): number {
  return ((lng + 180) / 360) * 2 ** z;
}

/** Web-Mercator lat → fractional tile Y at the given zoom. */
function latToTileY(lat: number, z: number): number {
  const rad = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * 2 ** z;
}

/** URL for the raster tile that contains the given coordinate. */
function staticTileUrl(coords: LatLng): string {
  const z = STATIC_TILE_ZOOM;
  const max = 2 ** z;
  const x = Math.min(max - 1, Math.max(0, Math.floor(lngToTileX(coords.lng, z))));
  const y = Math.min(max - 1, Math.max(0, Math.floor(latToTileY(coords.lat, z))));
  return `${PROXY_TILE_BASE}/${z}/${x}/${y}.png`;
}

function readCache(q: string): LatLng | null {
  try {
    const raw = localStorage.getItem(cacheKey(q));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as GeocodeCacheEntry;
    if (Date.now() - parsed.at > CACHE_TTL_MS) return null;
    if (!isFiniteNumber(parsed.lat) || !isFiniteNumber(parsed.lng)) {
      localStorage.removeItem(cacheKey(q));
      return null;
    }
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

  // Goes to GET /api/v1/geo-hub/geocode/suggest, never to a public
  // geocoder from the browser. ``geocodeSuggest`` throws ApiError on a
  // non-2xx and rejects on abort; the catch below turns both into the
  // same null a miss already produced, so the caller's loading and error
  // states are unchanged.
  try {
    const res = await geocodeSuggest(query, { limit: 1, signal });
    const first = res.suggestions[0];
    if (!first) return null;
    const lat = Number(first.lat);
    const lng = Number(first.lon);
    if (!isFiniteNumber(lat) || !isFiniteNumber(lng)) return null;
    const coords: LatLng = { lat, lng };
    writeCache(query, coords);
    return coords;
  } catch {
    return null;
  }
}

// ``buildGeocodeQuery`` lives in ``./geocode`` so consumers that only
// need to build an address string don't pull in the full maplibre +
// react-map-gl chunk (and its 220 KB CSS) via this module.
export { buildGeocodeQuery } from './geocode';
import { buildGeocodeQuery } from './geocode';

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
  const hasExplicitCoords = isFiniteNumber(lat) && isFiniteNumber(lng);

  const [resolved, setResolved] = useState<LatLng | null>(
    hasExplicitCoords ? { lat: lat as number, lng: lng as number } : null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [popupOpen, setPopupOpen] = useState(false);
  // The street snapshot, once it exists. Null means "still showing relief",
  // which is also the permanent answer wherever a snapshot cannot be made.
  const [streetThumb, setStreetThumb] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

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
    // callback; re-running the fetch on every render would hammer the geocoder.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasExplicitCoords, lat, lng, query]);

  const isCard = variant === 'card';
  // detail variant defaults to ``h-full`` so the parent grid (e.g. the
  // project-detail Map+Weather panel) can stretch the map to match the
  // height of its sibling.
  //
  // The default stands down when the caller states a height of its own, and
  // that is load-bearing rather than tidy. This comment used to claim a
  // custom ``className`` "still wins because tailwind's JIT utilities cascade
  // after the default class", which is false: ``className`` is appended after
  // ``heightClass`` on the element, but both names survive into the emitted
  // stylesheet and the one Tailwind wrote LAST there decides, whatever order
  // they sit in on the element. ``.h-full`` lands after ``.h-[32rem]``, so the
  // project detail page asked for 32rem, got ``h-full`` against an
  // auto-height grid parent, collapsed to 2px, and the ``overflow-hidden``
  // above cropped a live 300px map canvas to a hairline. The map was mounted,
  // painted and correct the whole time, and nobody could see it.
  const heightClass = hasOwnHeight(className) ? undefined : isCard ? 'h-28' : 'h-full';

  // Ask for the street snapshot. Card variant only: the detail variant has
  // a live map already, and rendering a picture of one for it would be
  // work with no reader.
  //
  // Nothing here touches what is on screen until the snapshot resolves, so
  // the relief tile is what the user sees in the meantime and what they
  // keep if it never resolves. The abort matters: the list filters and
  // paginates, and a queued render whose card is gone must neither open a
  // GL context nor set state on an unmounted component.
  const thumbLat = resolved?.lat;
  const thumbLng = resolved?.lng;
  useEffect(() => {
    if (!isCard || !isFiniteNumber(thumbLat) || !isFiniteNumber(thumbLng)) return;
    const box = cardRef.current;
    const width = snapSize(box?.clientWidth ?? 0, THUMB_WIDTH_STEP, DEFAULT_CARD_THUMB_WIDTH);
    const height = snapSize(box?.clientHeight ?? 0, THUMB_HEIGHT_STEP, DEFAULT_CARD_THUMB_HEIGHT);
    const controller = new AbortController();
    let live = true;
    renderStreetThumbnail({
      lat: thumbLat,
      lng: thumbLng,
      zoom: CARD_STREET_ZOOM,
      width,
      height,
      signal: controller.signal,
    }).then((dataUrl) => {
      if (live && dataUrl) setStreetThumb(dataUrl);
    });
    return () => {
      live = false;
      controller.abort();
    };
  }, [isCard, thumbLat, thumbLng]);

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

  // Card variant: a still image, never a live map. Normally a street
  // snapshot of the vector style; the relief tile until that arrives, and
  // for good wherever it cannot be made.
  if (isCard) {
    const showingStreets = streetThumb !== null;
    // The snapshot is centred on the coordinate, so its pin is dead-centre.
    // The relief tile is a whole z6 tile that merely CONTAINS the site, so
    // its pin sits at the coordinate's fractional offset inside that tile.
    // Using one rule for both would put the pin in the wrong place on
    // whichever image was not the one it was written for.
    const z = STATIC_TILE_ZOOM;
    const markerLeft = showingStreets ? 0.5 : lngToTileX(resolved.lng, z) % 1;
    const markerTop = showingStreets ? 0.5 : latToTileY(resolved.lat, z) % 1;
    // Credit what is actually in the picture. The vector snapshot is a
    // Produced Work over ODbL data and OWES this credit; the relief tile is
    // public-domain Natural Earth and is credited by courtesy. Crediting
    // either one while showing the other is a false licence statement, and
    // the ODbL direction is the one that is also a breach.
    const credit = showingStreets ? TILE_ATTRIBUTION_TEXT : RELIEF_ATTRIBUTION;
    return (
      <div
        ref={cardRef}
        className={clsx(
          'relative overflow-hidden rounded-xl border border-border-light bg-slate-100 dark:bg-slate-800',
          heightClass,
          className,
        )}
      >
        <img
          src={streetThumb ?? staticTileUrl(resolved)}
          alt={label || query || t('projects.map_thumbnail_alt', { defaultValue: 'Project location map' })}
          loading="lazy"
          decoding="async"
          draggable={false}
          className="absolute inset-0 h-full w-full select-none object-cover"
          // A snapshot that will not decode drops back to the relief tile
          // rather than blanking the card. Only a relief tile that also
          // fails is a real dead end, and that is the case the error state
          // was written for.
          onError={() => (showingStreets ? setStreetThumb(null) : setError(true))}
        />
        {/* Marker, placed by the rule above for whichever image is shown. */}
        <div
          className="pointer-events-none absolute z-[1] flex h-6 w-6 -translate-x-1/2 -translate-y-full items-center justify-center"
          style={{ left: `${markerLeft * 100}%`, top: `${markerTop * 100}%` }}
          aria-hidden="true"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white shadow-md shadow-oe-blue/40 ring-2 ring-white">
            <MapPin size={11} fill="currentColor" strokeWidth={0} />
          </span>
        </div>
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />
        <div
          data-testid="project-map-card-credit"
          title={credit}
          className="pointer-events-none absolute left-1 top-1 z-[2] max-w-[calc(100%-0.5rem)] truncate rounded bg-surface-elevated/85 px-1 py-px text-[9px] leading-tight text-content-tertiary"
        >
          {credit}
        </div>
        {(label || query) && (
          <div className="pointer-events-none absolute inset-x-2 bottom-2 flex items-center gap-1 rounded-md bg-surface-elevated/90 backdrop-blur-sm px-2 py-1 shadow-sm">
            <MapPin size={11} className="shrink-0 text-oe-blue" />
            <span className="truncate text-[11px] font-medium text-content-primary">
              {label || query}
            </span>
          </div>
        )}
      </div>
    );
  }

  const zoom = 13;

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
        mapStyle={VECTOR_BASEMAP_STYLE_URL}
        style={{ width: '100%', height: '100%' }}
        dragRotate={false}
        attributionControl={false}
      >
        <NavigationControl position="top-right" showCompass={false} />
        <AttributionControl
          compact
          customAttribution={TILE_ATTRIBUTION_HTML}
        />

        <Marker
          longitude={resolved.lng}
          latitude={resolved.lat}
          anchor="bottom"
          onClick={(e) => {
            e.originalEvent.stopPropagation();
            if (label) setPopupOpen(true);
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

        {popupOpen && label && (
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
    </div>
  );
}
