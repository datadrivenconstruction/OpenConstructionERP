// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Shared basemap configuration.
 *
 * Every map in the app - the Cesium globe, the MapLibre 2D maps, and the
 * static card thumbnails - reaches its basemap through our own backend at
 * ``/api/v1/geo-hub/``, never through a public tile host. Browser ad and
 * privacy blockers routinely block tile hosts by name, which leaves maps
 * showing a blank square. A same-origin ``/api`` request is never blocked.
 *
 * WHY THE UPSTREAM CHANGED. The tiles used to come from CARTO's keyless
 * "Voyager" raster. It stopped being keyless without a release, a notice or
 * a single failing check: it still answers 200 with a valid PNG of the
 * correct geography, now with "API KEY REQUIRED" printed across it. The
 * refusal was in the pixels, so every status, byte-length and decode check
 * stayed green and the founder found it by looking at the screen.
 *
 * The replacement is OpenFreeMap: keyless, quota-free, ODbL, and - the part
 * that actually matters - self-hostable, so an operator who outgrows the
 * public endpoint points the backend at their own copy. Raw OpenStreetMap
 * tiles remain off the table whatever they return: the OSMF Tile Usage
 * Policy forbids proxying and app use, and they enforce by User-Agent.
 *
 * THREE SHAPES. First, interactive maps read vector tiles through the
 * vendored style below and draw the streets themselves, in the browser, on
 * the GPU. That covers every map a user pans and zooms.
 *
 * Second, the card thumbnail. It cannot consume vector data - it is a plain
 * ``<img>`` - but it no longer has to: ``./streetThumbnail`` renders this
 * same vector style once into an offscreen MapLibre instance, reads the
 * canvas as a data URL and destroys the context, so the card shows real
 * street cartography from a still image with nothing left streaming. The
 * card therefore normally shows streets and building footprints, and falls
 * back to the relief tile below when the snapshot cannot be produced (no
 * WebGL, a blocked style, a render that times out). Which of the two it is
 * showing decides which credit it must carry, and both are exported from
 * this file.
 *
 * Third, one surface still cannot consume vector data at all: the Cesium
 * globe's imagery provider, which wants raster XYZ. It reads shaded relief -
 * Natural Earth, public domain, proxied straight through - and so shows
 * terrain rather than streets. That is a deliberate downgrade in detail,
 * taken because every keyless raster street basemap has stopped being
 * keyless, and a coarse honest tile beats a detailed one with "API KEY
 * REQUIRED" printed across it. It is also what the card falls back to, so
 * the relief source stays load-bearing rather than legacy.
 *
 * This paragraph used to state, as settled fact, that the card could not
 * show streets and that this was a permanent property of an ``<img>``. It
 * was read that way and believed. The claim was about the tile SOURCE, not
 * about the tag: an image tag shows whatever bytes it is given, and the
 * bytes can be rendered on this side.
 */

/**
 * XYZ template for the raster relief basemap the backend proxies.
 *
 * Note the path: this deliberately is NOT the old ``/tiles/`` one. Those
 * responses were sent with ``Cache-Control: immutable`` for a week, and an
 * immutable entry is never revalidated - a browser holding a watermarked
 * CARTO tile would keep painting it no matter what the server now returns.
 * A new path is the only way to retire it. The backend still answers the
 * old path for external XYZ clients such as QGIS.
 */
export const PROXY_TILE_URL = '/api/v1/geo-hub/basemap/{z}/{x}/{y}.png';

/** Base path (without ``/{z}/{x}/{y}.png``) for static single-tile thumbnails. */
export const PROXY_TILE_BASE = '/api/v1/geo-hub/basemap';

/**
 * Deepest zoom the relief source has. Asking past it returns a blank tile,
 * so raster consumers must clamp: Cesium via ``maximumLevel``, the card
 * thumbnail's relief FALLBACK by requesting this zoom directly. The card's
 * normal picture is a vector snapshot and is not bound by this ceiling.
 */
export const RELIEF_MAX_ZOOM = 6;

/**
 * MapLibre style served by the backend from a vendored copy whose every
 * URL - vector source, low-zoom relief raster, glyphs and sprite - points
 * back at our own origin. Fetching the upstream style and rewriting it at
 * runtime would leave any field we forgot pointing at the tile host, and
 * the map would still render, so the leak would be invisible.
 */
export function basemapStyleUrl(name: 'liberty' | 'positron'): string {
  return `/api/v1/geo-hub/basemap-style/${name}.json`;
}

/** Full-colour street cartography. The default for every interactive map. */
export const VECTOR_BASEMAP_STYLE_URL = basemapStyleUrl('liberty');

/**
 * Plain-text credit for the raster relief tiles, for consumers that render
 * their own attribution chrome (the Cesium globe passes this straight to
 * ``UrlTemplateImageryProvider``; the project card shows it whenever it is
 * displaying the relief fallback rather than a vector snapshot).
 *
 * Natural Earth is public domain and asks for no attribution at all, so this
 * is a courtesy credit, not a licence obligation. It deliberately does NOT
 * name OpenStreetMap: these tiles carry no OSM data, and crediting a source
 * that is not in the picture is its own kind of wrong.
 */
export const RELIEF_ATTRIBUTION = 'Natural Earth · public domain';

/**
 * The same credit as linked HTML, for MapLibre's ``AttributionControl``.
 *
 * Exported as ONE constant on purpose. This string used to be pasted
 * literally into three components; a migration that updated two of them
 * would have left the third crediting the wrong provider, and nothing in
 * the build would have said so. Import it, never retype it.
 *
 * OpenStreetMap is credited because the data is ODbL and a rendered map is
 * a Produced Work, which owes attribution. OpenMapTiles and OpenFreeMap are
 * credited as the tile schema and the tile provider.
 *
 * This is the credit for the VECTOR surfaces. The raster relief surfaces
 * carry ``RELIEF_ATTRIBUTION`` instead, because they show different data.
 */
export const TILE_ATTRIBUTION_HTML =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors ' +
  '&copy; <a href="https://openmaptiles.org/">OpenMapTiles</a> ' +
  '&copy; <a href="https://openfreemap.org/">OpenFreeMap</a>';

/**
 * The vector credit as plain text, for surfaces that render it as text
 * rather than as markup.
 *
 * The project card is one: it shows a rendered snapshot inside a card that
 * navigates on click, where an anchor is either a click target competing
 * with the card or a link that looks like one and is not. Plain text in a
 * small chip is the honest shape there, and the interactive map the card
 * leads to carries the linked credit in full.
 *
 * DERIVED, not retyped, and derived from the VALUE rather than from this
 * file's source text. Retyping is the exact defect the constant above
 * exists to prevent, and slicing a constant out of module source is the
 * defect the attribution test documents in its own history: a checkout
 * with CRLF terminators broke the slice and the assertion silently began
 * reading a different constant. Reading the value through the module
 * system cannot drift from the value.
 */
export const TILE_ATTRIBUTION_TEXT = TILE_ATTRIBUTION_HTML.replace(/<[^>]*>/g, '')
  .replace(/&copy;/g, '©')
  .replace(/\s+/g, ' ')
  .trim();
