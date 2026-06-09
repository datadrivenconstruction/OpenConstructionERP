// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * CesiumJS viewer wrapper.
 *
 * Lazy-loaded — the dynamic import that lands this module also pulls
 * the Cesium runtime. Keeping the bundle isolated is enforced by the
 * Vite ``manualChunks`` rule in ``vite.config.ts`` which routes
 * ``node_modules/cesium*`` to its own ``vendor-cesium`` chunk.
 *
 * Defensive guards:
 *
 * * Cesium is imported via ``import('cesium')`` so a missing optional
 *   dependency (the community installer does not auto-install Cesium)
 *   never crashes the rest of the app. When Cesium is absent we render
 *   a friendly install hint instead.
 * * ``viewer.destroy()`` is wired to the effect cleanup — no DOM leak
 *   on route change.
 * * Tileset loading falls back silently when ``tileset_json_uri`` is
 *   absent so a freshly-anchored project doesn't error out.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Globe2, Download, AlertTriangle, RefreshCw, Locate } from 'lucide-react';

import {
  clusterProjects,
  clusterThresholdForAltitude,
  colorForProjectStatus,
  iconFamilyForProjectType,
  pinTooltipLabel,
  type PinCluster,
} from './projectPinUtils';
import { geoAuthHeaders, tilesetArtifactUrl } from './api';
import type { AnchoredProject, GeoPinBundle, MapConfig } from './types';
import type { TilesetOverlayState } from './hooks/useTilesetOverlayState';

type ViewerMode = 'global' | 'project' | 'development';

/**
 * Cesium scene-mode toggle — controls the projection used to render the
 * globe. Mapped 1:1 to Cesium's ``SceneMode`` enum values at runtime by
 * the viewer effect. Exposed as a string union so the page can persist
 * the user's choice to localStorage without leaking Cesium constants.
 */
export type GeoSceneMode = '2d' | '3d' | 'columbus';

/** Live cursor coordinates lifted from a ScreenSpaceEventHandler pick. */
export interface GeoCursorCoords {
  /** Latitude in degrees (-90..90). */
  lat: number;
  /** Longitude in degrees (-180..180). */
  lon: number;
  /** Surface elevation in metres above the WGS-84 ellipsoid at the pick. */
  altitudeM: number;
}

/** Live camera state lifted from ``viewer.camera.changed``. */
export interface GeoCameraState {
  /** Heading clockwise from north in degrees (0..360). */
  headingDeg: number;
  /** Camera eye altitude above the ellipsoid in metres. */
  cameraAltitudeM: number;
}

/** Transient pin dropped by the address-search overlay. */
export interface GeoSearchPin {
  /** Latitude in degrees (-90..90). */
  lat: number;
  /** Longitude in degrees (-180..180). */
  lon: number;
  /** Human-readable label rendered next to the pin. */
  name: string;
}

interface CesiumViewerProps {
  mode: ViewerMode;
  mapConfig?: MapConfig;
  /**
   * Cross-module geo pin layers (HSE incidents / punch-list items /
   * Daily Diary geo-tagged photos). Rendered as point entities in a
   * dedicated effect so refetches don't tear down the Cesium viewer.
   */
  pins?: GeoPinBundle;
  /**
   * If set, after the matching tileset finishes loading the camera
   * flies to its bounding sphere. This is how deep-links from BIM
   * ("View on map" with ``?model=…``) and PropDev focus the user on
   * a specific model instead of leaving them at the project anchor.
   *
   * Best-effort — silently no-ops when the tileset has no resolvable
   * ``boundingSphere`` or fails to load.
   */
  focusedTilesetId?: string | null;
  /**
   * Global Geo Hub only — when set, the viewer flies the camera to
   * this project's anchor. Page state owns the focus so clicking the
   * same project twice still re-flies (callers can null + reset).
   *
   * No-op in project / development modes (those already focus on their
   * own anchor at init time).
   */
  focusedProject?: AnchoredProject | null;
  /**
   * Generic "fly camera here" handle for rows the OverlaySidebar exposes
   * (raster overlays + tilesets) that aren't projects. Distinct from
   * ``focusedProject`` so the existing focus effect's deps (which key on
   * ``project_id``) don't fight with this layer.
   *
   * ``key`` is the consumer's nonce — bumping it forces a re-fly to the
   * same destination, the same way ``focusedProject`` works when the
   * caller nulls + re-sets between clicks. Centroid is in degrees; ``alt``
   * is optional (defaults to a friendly rooftop altitude in the effect).
   */
  flyToTarget?: {
    key: string;
    lat: number;
    lon: number;
    alt?: number;
  } | null;
  /**
   * Transient pin from the top-of-page address search. When set we
   * fly the camera to the coordinates and render a single accent-blue
   * pin with the address as its label. Distinct visual treatment from
   * project / HSE / punch / diary pins so the user can always tell
   * "this is my search result, not a project anchor". Passing ``null``
   * removes the pin without flying the camera.
   */
  searchPin?: GeoSearchPin | null;
  /**
   * Optional overlay rendered above the Cesium canvas (HUD, empty
   * states, custom badges). Rendered inside the same relative wrapper
   * so absolute-positioned children compose naturally.
   *
   * Purely a chrome hook — does not touch viewer lifecycle.
   */
  overlay?: ReactNode;
  /**
   * Called when the pointer moves over the globe. Receives the picked
   * surface coordinates, or ``null`` when the pointer is off-globe or
   * pick fails. Throttled with ``requestAnimationFrame`` so React state
   * doesn't thrash on every MOUSE_MOVE event.
   */
  onMouseMove?: (coords: GeoCursorCoords | null) => void;
  /**
   * Called when the camera changes. Receives the current heading
   * (degrees clockwise from north) and the eye altitude over the
   * ellipsoid. Cesium debounces the underlying event itself.
   */
  onCameraChange?: (state: GeoCameraState) => void;
  /**
   * Lifecycle hook for parents that need direct access to the Cesium
   * runtime (raster overlay placement, custom primitives, etc.).
   * ``null`` is forwarded on teardown so the parent can clear any
   * primitives it added before the viewer is destroyed.
   */
  onViewerReady?: (
    payload: { cesium: unknown; viewer: unknown } | null,
  ) => void;
  /**
   * Per-tileset show/hide + opacity. Applied via ``tileset.show`` and
   * ``tileset.style = new Cesium3DTileStyle({ color: 'color("white", N)' })``
   * on each load + whenever this map changes. Tilesets missing from the
   * map render with the implicit default ``{ visible: true, opacity: 1 }``
   * so unaware callers see the legacy behaviour.
   */
  tilesetOverlayState?: TilesetOverlayState;
  /**
   * Scene projection — ``'3d'`` (globe), ``'2d'`` (flat top-down map) or
   * ``'columbus'`` (2.5-D oblique). Applied at viewer construction so
   * the initial paint matches the user's saved preference (no jarring
   * morph on mount), and re-applied via ``scene.morphTo*`` whenever the
   * prop value changes after mount. Undefined falls back to ``'3d'``.
   */
  sceneMode?: GeoSceneMode;
  /**
   * Called when the user LEFT-clicks a pin we rendered. Receives the
   * decoded pin tag stored in ``properties._oeGeoHubPinTag``:
   *
   *   * ``project:<id>``       — a single anchored-project pin
   *   * ``cluster:<n>:<lat,lon>`` — a cluster bubble; ``clusterProjectIds``
   *     carries the member project ids so the page can expand it
   *   * ``hse:<id>`` / ``punch:<id>`` / ``diary:<id>`` — cross-module pins
   *   * ``search``             — the transient address-search pin
   *
   * The viewer deliberately does NOT import react-router; the page wires
   * navigation. When ``anchorDragMode`` is active a click is consumed by
   * the anchor flow instead and this callback is not invoked.
   */
  onPinSelect?: (sel: {
    tag: string;
    clusterProjectIds?: string[];
  }) => void;
  /**
   * When true the next LEFT-click on the globe is interpreted as "set the
   * anchor here" — the viewer resolves the surface coordinate and calls
   * ``onMapClick`` instead of selecting a pin. The page owns the toggle
   * and the PATCH; the viewer only reports the picked lat/lon.
   */
  anchorDragMode?: boolean;
  /**
   * Called with the picked globe surface coordinate when the user clicks
   * the map while ``anchorDragMode`` is true. The page PATCHes the anchor
   * and exits drag mode.
   */
  onMapClick?: (coords: { lat: number; lon: number }) => void;
}

/** Stable signature for the viewer effect: rebuild only when the
 * inputs that actually matter for the Cesium scene change. Without
 * this, React Query produces a fresh ``mapConfig`` reference every
 * refetch (every 30 s on stale revalidation) which would tear down
 * the entire Cesium viewer — wiping camera state and forcing the
 * ~3 MB runtime to reinitialise.
 */
function _viewerSignature(
  mode: ViewerMode,
  mapConfig?: MapConfig,
): string {
  if (!mapConfig) return `${mode}|nil`;
  const anchor = mapConfig.anchor
    ? `${mapConfig.anchor.lat},${mapConfig.anchor.lon},${mapConfig.anchor.alt}`
    : 'nil';
  const tilesets = (mapConfig.tilesets ?? [])
    .filter((t) => t.status === 'ready' && t.tileset_json_uri)
    .map((t) => `${t.id}:${t.tileset_json_uri}`)
    .sort()
    .join(';');
  return `${mode}|${mapConfig.project_id ?? ''}|${anchor}|${tilesets}`;
}

interface CesiumEntityLike {
  id: unknown;
}

interface CesiumEntityCollectionLike {
  add: (entity: Record<string, unknown>) => CesiumEntityLike;
  remove: (entity: CesiumEntityLike) => boolean;
  removeAll: () => void;
  values: CesiumEntityLike[];
}

interface CesiumCartesian2Like {
  x: number;
  y: number;
}

interface CesiumCartesian3Like {
  x: number;
  y: number;
  z: number;
}

interface CesiumCartographicLike {
  longitude: number;
  latitude: number;
  height: number;
}

interface CesiumEventLike {
  addEventListener: (cb: () => void) => () => void;
  removeEventListener: (cb: () => void) => void;
}

interface CesiumScreenSpaceEventHandlerLike {
  setInputAction: (
    cb: (movement: { endPosition?: CesiumCartesian2Like; position?: CesiumCartesian2Like }) => void,
    eventType: number,
  ) => void;
  removeInputAction: (eventType: number) => void;
  destroy: () => void;
}

/** Picked entity returned by ``scene.pick`` / ``scene.drillPick``. */
interface CesiumPickedFeatureLike {
  /**
   * The entity (when the pick hit a labelled point we added). Carries
   * the ``properties`` bag where our ``_oeGeoHubPinTag`` lives. May be
   * absent for non-entity picks (3D Tiles features, terrain).
   */
  id?: {
    properties?: {
      getValue?: (time?: unknown) => Record<string, unknown> | undefined;
      // Some Cesium builds expose property bags as plain objects too.
      [key: string]: unknown;
    };
  };
}

type CesiumViewerInstance = {
  destroy: () => void;
  camera: {
    flyTo: (options: { destination: unknown }) => void;
    /**
     * Instantly position the camera with no animation. Used for the
     * initial project/development framing so the very first painted frame
     * is already at the anchor instead of animating in from the default
     * whole-globe view out in deep space. Optional in the shim so a build
     * without it falls back to a short flyTo.
     */
    setView?: (options: { destination: unknown; orientation?: unknown }) => void;
    /**
     * Optional in our type-shim — exists in all Cesium versions we ship
     * but we guard the call at runtime so the focus effect degrades to
     * a no-op on hypothetical builds where it's absent.
     */
    flyToBoundingSphere?: (
      sphere: unknown,
      options?: { duration?: number; offset?: unknown },
    ) => void;
    changed: CesiumEventLike;
    heading: number;
    positionCartographic: CesiumCartographicLike;
    /**
     * Resolve a window pixel to a point on the WGS-84 ellipsoid surface.
     * Used by the "Drag to adjust" anchor flow to turn a map click into
     * lat/lon. Optional in the shim so a stripped build degrades to a
     * no-op rather than throwing.
     */
    pickEllipsoid?: (
      windowPosition: CesiumCartesian2Like,
      ellipsoid?: unknown,
    ) => CesiumCartesian3Like | undefined;
  };
  scene: {
    primitives: { add: (p: unknown) => unknown };
    canvas: HTMLCanvasElement;
    pickPosition?: (windowPosition: CesiumCartesian2Like) => CesiumCartesian3Like | undefined;
    /** Topmost feature under the cursor — used to resolve a clicked pin. */
    pick?: (windowPosition: CesiumCartesian2Like) => CesiumPickedFeatureLike | undefined;
    /**
     * All features under the cursor (front-to-back). We prefer this over
     * ``pick`` so a pin partially occluded by a 3D tile is still selectable.
     */
    drillPick?: (
      windowPosition: CesiumCartesian2Like,
      limit?: number,
    ) => CesiumPickedFeatureLike[];
    globe?: {
      pick?: (ray: unknown, scene: unknown) => CesiumCartesian3Like | undefined;
      ellipsoid?: unknown;
      /**
       * Sun-driven day/night shading. MUST stay ``false`` for the Geo Hub:
       * with it on (or with ``viewer.shadows``), the hemisphere facing away
       * from the sun renders almost black, which reads to users as "the map
       * is broken / showing only space". A flat, fully-lit base map is the
       * correct look for a project locator.
       */
      enableLighting?: boolean;
      /**
       * Fill colour shown on the globe before/while imagery tiles stream in.
       * A light ocean-blue avoids the jarring black flash on first paint and
       * a permanently black globe if the imagery provider is ever blocked.
       */
      baseColor?: unknown;
      /** Atmosphere halo around the limb — kept on for a polished look. */
      showGroundAtmosphere?: boolean;
    };
    /** Current scene projection — one of the ``SceneMode`` enum values. */
    mode?: number;
    /** Animate transition to top-down 2D scene over ``duration`` seconds. */
    morphTo2D?: (duration?: number) => void;
    /** Animate transition to globe 3D scene over ``duration`` seconds. */
    morphTo3D?: (duration?: number) => void;
    /** Animate transition to 2.5-D oblique Columbus View scene. */
    morphToColumbusView?: (duration?: number) => void;
  };
  camera_changedFrustum?: unknown;
  entities: CesiumEntityCollectionLike;
  shadows: boolean;
};

interface CesiumLike {
  Viewer: new (
    container: HTMLElement,
    options?: Record<string, unknown>,
  ) => CesiumViewerInstance;
  Cartesian3: {
    fromDegrees: (lon: number, lat: number, alt: number) => unknown;
  };
  Cartographic: {
    fromCartesian: (cartesian: CesiumCartesian3Like) => CesiumCartographicLike;
  };
  Color: {
    RED: unknown;
    ORANGE: unknown;
    DODGERBLUE: unknown;
    WHITE: unknown;
    LIMEGREEN?: unknown;
    fromCssColorString?: (css: string) => unknown;
  };
  EllipsoidTerrainProvider: new () => unknown;
  UrlTemplateImageryProvider: new (options: Record<string, unknown>) => unknown;
  ImageryLayer: new (provider: unknown) => unknown;
  Cesium3DTileset: {
    fromUrl: (url: string | object) => Promise<unknown>;
  };
  /**
   * Constructor for a Cesium ``Resource`` - a URL plus request options.
   * We pass the bearer ``headers`` through it so Cesium's own fetches of
   * ``tileset.json`` and the derived child tiles carry our auth; the
   * tileset artifacts are tenant-scoped and served behind a real route.
   */
  Resource: new (options: Record<string, unknown>) => object;
  /**
   * Constructor for the styling expression that controls per-tile colour
   * (and thus opacity via the alpha channel). Optional in the shim so
   * older Cesium builds without the symbol degrade to a no-op rather
   * than throwing — we feature-detect before instantiating.
   */
  Cesium3DTileStyle?: new (options: Record<string, unknown>) => unknown;
  /**
   * Sphere math used by the "Fit to data" auto-zoom. Built-in to every
   * Cesium build we ship; we still guard the call sites at runtime so a
   * stripped vendor build degrades to a no-op rather than crashing.
   */
  BoundingSphere?: {
    fromPoints: (points: unknown[]) => unknown;
    fromBoundingSpheres: (spheres: unknown[]) => unknown;
  };
  ScreenSpaceEventHandler: new (canvas: HTMLCanvasElement) => CesiumScreenSpaceEventHandlerLike;
  ScreenSpaceEventType: {
    MOUSE_MOVE: number;
    LEFT_CLICK: number;
  };
  Math: {
    toDegrees: (radians: number) => number;
    TWO_PI: number;
  };
  /**
   * Cesium's ``SceneMode`` enum — used both to bootstrap the viewer's
   * initial projection (so restoring a saved ``'2d'`` from localStorage
   * doesn't morph from 3D on every page load) and to compare against
   * ``scene.mode`` before issuing a redundant morph.
   */
  SceneMode?: {
    MORPHING?: number;
    COLUMBUS_VIEW: number;
    SCENE2D: number;
    SCENE3D: number;
  };
}

async function loadCesium(): Promise<CesiumLike | null> {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mod = (await import('cesium')) as any;
    // Cesium ships the runtime constructors on the module namespace itself
    // when imported via ESM. If the bundler resolved something that does not
    // expose ``Viewer``, the viewer init will throw — degrade gracefully and
    // log a diagnostic so we don't silently fall into "CesiumJS is not
    // installed" mode while the package is actually present.
    if (mod && typeof mod.Viewer !== 'function') {
      // eslint-disable-next-line no-console
      console.warn('[geo_hub] cesium import resolved but Viewer constructor is missing', Object.keys(mod || {}).slice(0, 10));
      return null;
    }
    // Silence the "Cesium ion default access token" warning + watermark.
    // We don't use any Ion-hosted services (base imagery is OSM, terrain is
    // ellipsoid). Cesium >= 1.107 treats a falsy token (including ``''``) as
    // "still on the bundled default" and keeps logging the nag and showing
    // the credit popup. Setting a non-empty sentinel passes the "is set"
    // check so the warning stays quiet; any code path that *does* request
    // an Ion asset will still fail loudly with a 401 rather than silently
    // borrowing our anonymous quota.
    // Enterprise tenants who *do* want Ion assets override this via the
    // Terrain admin page after viewer boot.
    try {
      if (mod.Ion) mod.Ion.defaultAccessToken = 'disabled-by-openconstructionerp';
    } catch {
      // Ion namespace shape changed between major versions — never block boot.
    }
    return mod as CesiumLike;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[geo_hub] cesium dynamic import failed', err);
    return null;
  }
}

/**
 * Read ``viewer.scene`` without ever throwing.
 *
 * Cesium's ``Viewer.scene`` is a getter that returns ``this._cesiumWidget.scene``.
 * ``Viewer.destroy()`` sets ``_cesiumWidget = undefined`` synchronously, so any
 * access AFTER teardown throws "Cannot read properties of undefined (reading
 * 'scene')" rather than returning undefined — which blows past optional-chain
 * guards (``v.scene?.x`` still evaluates ``v.scene`` first). A deferred Cesium
 * event, a rAF, or an effect that runs during the post-navigation teardown
 * race can all hit a half-destroyed viewer. Route every scene access through
 * this so the React ErrorBoundary never sees the throw.
 */
function safeScene(viewer: CesiumViewerInstance | null | undefined): CesiumViewerInstance['scene'] | null {
  try {
    return viewer?.scene ?? null;
  } catch {
    return null;
  }
}

/**
 * Resolve a {@link GeoSceneMode} string to the matching Cesium
 * ``SceneMode`` enum value. Falls back to ``SCENE3D`` when the runtime
 * doesn't expose the enum (defensive — every shipped Cesium does).
 */
function _sceneModeEnum(cesium: CesiumLike, mode: GeoSceneMode): number {
  const sm = cesium.SceneMode;
  if (!sm) return 3; // SCENE3D
  switch (mode) {
    case '2d':
      return sm.SCENE2D;
    case 'columbus':
      return sm.COLUMBUS_VIEW;
    case '3d':
    default:
      return sm.SCENE3D;
  }
}

/**
 * True when a {@link Tileset} row describes a point cloud rather than the
 * default b3dm / glTF box path. Point clouds are tiled out-of-core by the
 * converter into a ``pnts`` octree or a range-readable ``copc`` keystone and
 * referenced by ``tile_pipeline.build_point_cloud_tileset_json`` - they need
 * point-cloud shading + Eye-Dome Lighting, which we MUST NOT apply to the
 * mesh tilesets (it would silently no-op there, but the guard keeps the
 * intent explicit and avoids touching the proven mesh render path).
 */
function _isPointCloudTileset(ts: {
  source_kind?: string;
  tile_format?: string;
}): boolean {
  return (
    ts.source_kind === 'point_cloud' ||
    ts.tile_format === 'pnts' ||
    ts.tile_format === 'copc'
  );
}

/** Minimal shape of the runtime ``Cesium3DTileset.pointCloudShading`` bag. */
interface CesiumPointCloudShadingLike {
  /** Size-attenuate points by distance so far points don't vanish. */
  attenuation?: boolean;
  /** Eye-Dome Lighting - depth-based shading that reads structure in a
   *  flat cloud (edges/contours) without per-point normals. */
  eyeDomeLighting?: boolean;
  /** EDL strength multiplier. Cesium default 1.0; a touch higher reads
   *  construction scans (façades, terrain breaks) more clearly. */
  eyeDomeLightingStrength?: number;
  /** EDL sampling radius in pixels. */
  eyeDomeLightingRadius?: number;
  /** Upper bound on per-point screen size when attenuating (pixels). */
  maximumAttenuation?: number;
}

/**
 * Enable point-cloud shading + Eye-Dome Lighting on a loaded tileset.
 *
 * Cesium exposes ``Cesium3DTileset.pointCloudShading`` (a ``PointCloudShading``
 * instance) on every tileset, but the flags only take effect when the tileset
 * actually contains ``pnts`` content - so this is a no-op on mesh tilesets and
 * we still gate the call to point clouds to keep the mesh path untouched.
 *
 * Best-effort: a stripped Cesium build without the bag, or a disposed
 * primitive, degrades to plain points rather than throwing.
 */
function _applyPointCloudShading(tileset: unknown): void {
  try {
    const pcs = (tileset as { pointCloudShading?: CesiumPointCloudShadingLike })
      .pointCloudShading;
    if (!pcs) return;
    pcs.attenuation = true;
    pcs.eyeDomeLighting = true;
    pcs.eyeDomeLightingStrength = 1.2;
    pcs.eyeDomeLightingRadius = 1.0;
    pcs.maximumAttenuation = 4.0;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[geo_hub] point-cloud shading setup failed', err);
  }
}

export function CesiumViewer({
  mode,
  mapConfig,
  pins,
  focusedTilesetId,
  focusedProject,
  flyToTarget,
  searchPin,
  overlay,
  onMouseMove,
  onCameraChange,
  onViewerReady,
  tilesetOverlayState,
  sceneMode,
  onPinSelect,
  anchorDragMode,
  onMapClick,
}: CesiumViewerProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<CesiumViewerInstance | null>(null);
  const cesiumRef = useRef<CesiumLike | null>(null);
  // Track every entity we created for pin layers so the dedicated pins
  // effect can incrementally remove/re-add without tearing down user
  // entities created by other future code paths.
  const pinEntitiesRef = useRef<CesiumEntityLike[]>([]);
  // Map of Tileset.id -> the loaded Cesium3DTileset primitive, populated
  // as the viewer effect resolves each tileset. The focus effect reads
  // from this map to flyTo() the bounding sphere of the user-selected
  // tileset (via deep-link). Keyed by our DB id, not the cesium uuid.
  const loadedTilesetsRef = useRef<Map<string, unknown>>(new Map());
  // Single entity for the address-search pin so the dedicated effect can
  // swap / clear it without disturbing project / HSE / punch / diary pins.
  const searchPinEntityRef = useRef<CesiumEntityLike | null>(null);
  // True once the auto-zoom on first mount has run. Subsequent overlay /
  // tileset arrivals must NOT re-trigger the camera fly so a user who has
  // manually navigated stays where they are. The "Fit to data" button
  // bypasses this flag — it always re-runs the zoom on demand.
  const hasAutoZoomedRef = useRef<boolean>(false);
  // Latest callback refs so the viewer effect doesn't have to re-run
  // when only the parent's handler identity changes.
  const onMouseMoveRef = useRef(onMouseMove);
  const onCameraChangeRef = useRef(onCameraChange);
  onMouseMoveRef.current = onMouseMove;
  onCameraChangeRef.current = onCameraChange;
  // Latest click-handling refs so the single LEFT_CLICK input action
  // (registered once in the viewer effect) always reads the current
  // callbacks + drag-mode flag without rebuilding the Cesium runtime.
  const onPinSelectRef = useRef(onPinSelect);
  const onMapClickRef = useRef(onMapClick);
  const anchorDragModeRef = useRef<boolean>(anchorDragMode ?? false);
  onPinSelectRef.current = onPinSelect;
  onMapClickRef.current = onMapClick;
  anchorDragModeRef.current = anchorDragMode ?? false;
  // Latest overlay-state ref — used during the *initial* tileset load
  // loop so the first frame respects saved user prefs. The dedicated
  // ``tilesetOverlayState`` effect re-applies on every change, so this
  // ref only matters for the boot-time snapshot.
  const tilesetOverlayStateRef = useRef(tilesetOverlayState);
  tilesetOverlayStateRef.current = tilesetOverlayState;
  // Latest scene-mode ref so the viewer effect can read the user's
  // restored preference at construction time WITHOUT being added to the
  // dependency array (changing scene mode must morph in place, not
  // rebuild the entire 3 MB Cesium runtime).
  const sceneModeRef = useRef<GeoSceneMode>(sceneMode ?? '3d');
  sceneModeRef.current = sceneMode ?? '3d';
  // ``absent`` = ``import('cesium')`` itself failed (community build w/o
  //   the optional dep — actionable hint: ``npm install cesium``).
  // ``init_failed`` = module loaded but ``new Viewer()`` threw — most
  //   commonly WebGL blocked / disabled / hardware-accel off, but also
  //   covers transient init bugs. Distinct UI so we don't mislead users
  //   into running ``npm install`` when the real fix is WebGL.
  const [cesiumStatus, setCesiumStatus] = useState<
    'pending' | 'loaded' | 'absent' | 'init_failed'
  >('pending');
  // Bumped to force a fresh viewer-init attempt after a transient failure
  // (e.g. user enabled hardware acceleration → clicks Retry). Resets the
  // status back to 'pending' first so the loading spinner replaces the
  // error card while the retry is in flight.
  const [reloadKey, setReloadKey] = useState<number>(0);
  const retryViewer = useCallback(() => {
    setCesiumStatus('pending');
    setReloadKey((k) => k + 1);
  }, []);

  // Stable string signature of the viewer-relevant inputs. Re-running
  // the effect on every parent re-render (React Query returns a new
  // ``mapConfig`` object reference on each refetch) would destroy and
  // re-create the entire Cesium viewer — wiping camera state and
  // re-downloading the 3 MB runtime.
  const signature = useMemo(
    () => _viewerSignature(mode, mapConfig),
    [mode, mapConfig],
  );

  useEffect(() => {
    let disposed = false;
    let viewer: CesiumViewerInstance | null = null;
    let inputHandler: CesiumScreenSpaceEventHandlerLike | null = null;
    let removeCameraListener: (() => void) | null = null;
    let rafHandle: number | null = null;
    let pendingMouse: CesiumCartesian2Like | null = null;
    let lastMouseEmitWasNull = false;

    (async () => {
      const cesium = await loadCesium();
      if (!cesium || disposed) {
        setCesiumStatus(cesium ? 'loaded' : 'absent');
        return;
      }
      const container = containerRef.current;
      if (!container) {
        setCesiumStatus('absent');
        return;
      }
      try {
        // Default to the ellipsoid terrain provider — zero-cost, no
        // ion key required. Enterprise customers wire their own ion
        // token via the Terrain admin page; we surface it through
        // the map-config bundle for them.
        //
        // Base imagery: keyless CARTO Voyager raster (rendered from OSM
        // data) via UrlTemplateImageryProvider. Cesium >= 1.107 falls back
        // to Ion-backed Bing Maps when ``imageryProvider`` is unset, which
        // silently 401s without an ion token. The raw OpenStreetMap tile
        // servers are not an option either: their usage policy forbids app
        // and bulk use and returns an "Access blocked" tile. CARTO is
        // keyless and already used by the 2D maps, so /geo-hub matches them
        // out of the box with no vendor lock-in.
        //
        // ``homeButton`` and ``navigationHelpButton`` are disabled here
        // because we don't ship Cesium's ``widgets.css`` in the bundle,
        // which would leave them as unstyled (invisible) toolbar pills.
        // The lat/lon HUD + altitude readout + our overlay panel cover
        // every interaction the home button traditionally provides.
        // Hidden credit container. Cesium's built-in CreditDisplay always
        // injects an "Ion default-token" credit whenever Ion.defaultAccessToken
        // is unset OR matches the bundled default; clicking that credit opens
        // a modal nagging the user to sign up. Setting the token to empty
        // string did NOT suppress this (Cesium treats falsy as default).
        // The robust fix is to redirect all viewer-managed credits into a
        // detached <div>; we then render our own OSM attribution as an HTML
        // overlay so we still honour the OSM tile-usage policy.
        const hiddenCreditContainer = document.createElement('div');
        hiddenCreditContainer.style.display = 'none';
        hiddenCreditContainer.setAttribute('aria-hidden', 'true');

        // Resolve the user's saved scene-mode preference BEFORE viewer
        // construction. Passing ``sceneMode`` into the Viewer options means
        // the very first frame already paints in 2D/Columbus when the
        // user previously chose that — no jarring globe→2D morph on
        // every page reload.
        const initialSceneMode = _sceneModeEnum(cesium, sceneModeRef.current);
        const v = new cesium.Viewer(container, {
          terrainProvider: new cesium.EllipsoidTerrainProvider(),
          // Tiles are fetched through our own same-origin backend proxy, not
          // straight from a public CDN. A direct CARTO/OSM URL is routinely
          // blocked by browser ad/privacy blockers (shows up as a blank blue
          // globe), and the raw OSM servers refuse app use outright. The proxy
          // pulls CARTO server-side with a proper User-Agent and caches, so the
          // map renders in any browser.
          baseLayer: new cesium.ImageryLayer(
            new cesium.UrlTemplateImageryProvider({
              url: '/api/v1/geo-hub/tiles/{z}/{x}/{y}.png',
              credit: '© OpenStreetMap contributors © CARTO',
              maximumLevel: 20,
            }),
          ),
          baseLayerPicker: false,
          // Timeline + animation widgets are disabled in EVERY mode. They
          // depend on Cesium's ``widgets.css`` (intentionally not bundled —
          // see the scoped <style> block + the v5.4.1 canvas fix) and add
          // no value here: ``shouldAnimate`` is false and nothing is clock-
          // driven. Previously project/development mode switched them on,
          // which is the one viewer-construction divergence from the proven
          // global hub; unstyled widget containers also disturbed the flex
          // layout the canvas relies on. Keeping all modes identical means
          // the project map boots exactly like the working /geo hub.
          timeline: false,
          animation: false,
          shouldAnimate: false,
          fullscreenButton: false,
          geocoder: false,
          // Cesium's built-in widgets are useful but used to be invisible
          // because we didn't ship ``widgets.css``. We now inline the
          // minimum CSS for them (see ``<style>`` block below), so the
          // remaining toolbar buttons ("go home", "navigation help") can
          // be turned back on. The scene-mode picker is intentionally
          // disabled here because the Geo Hub toolbar renders its own
          // 2D / 3D / Columbus segmented control with localStorage
          // persistence — leaving Cesium's built-in picker on would
          // produce two competing controls.
          homeButton: true,
          navigationHelpButton: true,
          navigationInstructionsInitiallyVisible: false,
          sceneModePicker: false,
          sceneMode: initialSceneMode,
          creditContainer: hiddenCreditContainer,
        });
        viewer = v;
        viewerRef.current = v;
        cesiumRef.current = cesium;
        // ── Base-map appearance ─────────────────────────────────────────
        //
        // ROOT CAUSE of the "shows only space" report: with shadows +
        // sun-driven globe lighting enabled, the hemisphere facing away
        // from the sun renders almost black, so the OSM imagery is there
        // but invisible — the user just sees a dark sphere with floating
        // labels. A project locator wants a flat, evenly-lit map, so we
        // force lighting + shadows OFF and give the globe a light base
        // colour that shows immediately while OSM tiles stream in (and
        // prevents a permanently black globe if imagery is ever blocked).
        //
        // We only re-enable shadows in project / development modes where a
        // real 3D building tileset is on the globe and self-shadowing adds
        // value; the global hub never has tilesets.
        try {
          const globe = safeScene(v)?.globe;
          if (globe) {
            globe.enableLighting = false;
            globe.showGroundAtmosphere = true;
            if (cesium.Color.fromCssColorString) {
              // Light ocean blue — matches the OSM water palette so the
              // un-tiled gaps blend in rather than flashing black.
              globe.baseColor = cesium.Color.fromCssColorString('#aadaff');
            }
          }
        } catch (lightErr) {
          // eslint-disable-next-line no-console
          console.warn('[geo_hub] globe lighting setup failed', lightErr);
        }
        v.shadows = mode !== 'global';
        // Surface the runtime to overlay children (raster overlays draw
        // imagery layers directly into the viewer). Best-effort try-catch
        // because a misbehaving callback must never block viewer boot.
        try {
          onViewerReady?.({ cesium, viewer: v });
        } catch (cbErr) {
          // eslint-disable-next-line no-console
          console.warn('[geo_hub] onViewerReady callback threw', cbErr);
        }

        if (mapConfig?.anchor) {
          const lat = Number(mapConfig.anchor.lat);
          const lon = Number(mapConfig.anchor.lon);
          const alt = Number(mapConfig.anchor.alt || 200);
          // Place the camera AT the project on the very first frame.
          //
          // ROOT CAUSE of the "why am I in space, and why is the earth
          // loading forever" report: ``flyTo`` animates FROM Cesium's
          // default view (the whole globe seen from deep space) TO the
          // anchor, and its duration scales with distance — so the user
          // watched a multi-second descent from orbit. Worse, while the
          // camera is up in space Cesium needs the entire low-zoom tile
          // pyramid for the whole planet, and every one of those tiles is
          // a round-trip through our same-origin proxy, so the globe took
          // a long time to even texture.
          //
          // ``setView`` is instant: the first painted frame is already
          // over the site at a rooftop altitude, so Cesium only streams
          // the handful of high-zoom tiles around the project. No orbital
          // fly-in, and first meaningful paint is near-immediate.
          const destination = cesium.Cartesian3.fromDegrees(
            lon, lat, Math.max(alt + 500, 1500),
          );
          if (typeof v.camera.setView === 'function') {
            v.camera.setView({ destination });
          } else {
            // Older Cesium build without setView — fall back to flyTo.
            v.camera.flyTo({ destination });
          }
        }
        if (mapConfig?.tilesets) {
          for (const ts of mapConfig.tilesets) {
            if (ts.status !== 'ready' || !ts.tileset_json_uri) continue;
            try {
              // Cesium fetches tileset.json and its child tiles itself, so it
              // must carry our bearer token (the artifacts are tenant-scoped)
              // and hit a real serving route. ``tileset_json_uri`` is only a
              // storage key in the DB; the backend artifact route streams the
              // bytes, and the Resource header propagates to derived child
              // tile requests.
              const resource = new cesium.Resource({
                url: tilesetArtifactUrl(ts.id, 'tileset.json'),
                headers: geoAuthHeaders(),
              });
              const tileset = await cesium.Cesium3DTileset.fromUrl(resource);
              if (disposed) break;
              v.scene.primitives.add(tileset);
              // Record so the focus effect can flyTo() its boundingSphere
              // when ``focusedTilesetId`` matches. Cleared on cleanup
              // along with the rest of the viewer state.
              loadedTilesetsRef.current.set(ts.id, tileset);
              // Point clouds (pnts octree / copc keystone) render flat and
              // hard to read without depth shading. Turn on attenuation +
              // Eye-Dome Lighting for them only - gated so the proven
              // b3dm / glTF mesh render path is never touched.
              if (_isPointCloudTileset(ts)) {
                _applyPointCloudShading(tileset);
              }
              // Apply any pre-existing show/opacity prefs immediately so
              // the user doesn't briefly see a hidden tileset flash in
              // before the dedicated state-effect catches up. Reads the
              // *current* prop via closure — fine because the dedicated
              // effect re-applies on every state change so any updates
              // between init and now will be reconciled.
              try {
                const entry = tilesetOverlayStateRef.current?.[ts.id];
                const tile = tileset as {
                  show?: boolean;
                  style?: unknown;
                };
                if (entry?.visible === false) tile.show = false;
                if (
                  entry &&
                  typeof entry.opacity === 'number' &&
                  entry.opacity < 1 &&
                  cesium.Cesium3DTileStyle
                ) {
                  const clamped = Math.max(0, Math.min(1, entry.opacity));
                  tile.style = new cesium.Cesium3DTileStyle({
                    color: `color("white", ${clamped})`,
                  });
                }
              } catch {
                /* style/show assignment failed — defer to the dedicated effect */
              }
            } catch (err) {
              // One bad tileset must not kill the viewer.
              // eslint-disable-next-line no-console
              console.warn('[geo_hub] Tileset load failed', ts.id, err);
            }
          }
        }

        // ───── Live HUD wiring ──────────────────────────────────────
        // MOUSE_MOVE fires on every pixel of pointer motion. We batch
        // through a single rAF so React only sees ~60 fps updates even
        // when the browser pumps 1000 Hz mice. The latest endPosition
        // wins; intermediate moves are coalesced.
        try {
          if (
            typeof cesium.ScreenSpaceEventHandler === 'function' &&
            cesium.ScreenSpaceEventType &&
            v.scene?.canvas
          ) {
            inputHandler = new cesium.ScreenSpaceEventHandler(v.scene.canvas);

            const flushMouse = () => {
              rafHandle = null;
              const cb = onMouseMoveRef.current;
              const pos = pendingMouse;
              pendingMouse = null;
              if (!cb || !viewer) return;
              if (!pos) {
                if (!lastMouseEmitWasNull) {
                  lastMouseEmitWasNull = true;
                  cb(null);
                }
                return;
              }
              // Cesium nulls ``viewer.scene`` synchronously inside
              // ``viewer.destroy()`` — and the getter THROWS afterwards
              // rather than returning undefined, so optional chaining on
              // ``viewer.scene?.x`` is not enough (it evaluates ``.scene``
              // first). A rAF can still fire after navigation tore the
              // viewer down; ``safeScene`` swallows the getter throw.
              const picked = safeScene(viewer)?.pickPosition?.(pos);
              if (!picked) {
                if (!lastMouseEmitWasNull) {
                  lastMouseEmitWasNull = true;
                  cb(null);
                }
                return;
              }
              try {
                const carto = cesium.Cartographic.fromCartesian(picked);
                const lat = cesium.Math.toDegrees(carto.latitude);
                const lon = cesium.Math.toDegrees(carto.longitude);
                if (
                  !Number.isFinite(lat) ||
                  !Number.isFinite(lon) ||
                  !Number.isFinite(carto.height)
                ) {
                  if (!lastMouseEmitWasNull) {
                    lastMouseEmitWasNull = true;
                    cb(null);
                  }
                  return;
                }
                lastMouseEmitWasNull = false;
                cb({ lat, lon, altitudeM: carto.height });
              } catch {
                if (!lastMouseEmitWasNull) {
                  lastMouseEmitWasNull = true;
                  cb(null);
                }
              }
            };

            const scheduleFlush = () => {
              if (rafHandle !== null) return;
              rafHandle = window.requestAnimationFrame(flushMouse);
            };

            inputHandler.setInputAction((movement) => {
              if (movement?.endPosition) {
                pendingMouse = movement.endPosition;
                scheduleFlush();
              }
            }, cesium.ScreenSpaceEventType.MOUSE_MOVE);

            // ── LEFT_CLICK → pin select / anchor placement ──────────────
            //
            // Two responsibilities, decided by the latest ``anchorDragMode``
            // ref so the single registered action handles both without the
            // viewer rebuilding when the page toggles drag mode:
            //
            //   * drag-mode ON  → resolve the globe surface coord and emit
            //     ``onMapClick`` so the page PATCHes the anchor.
            //   * drag-mode OFF → drillPick the entity under the cursor,
            //     read ``_oeGeoHubPinTag``, and emit ``onPinSelect`` so the
            //     page navigates / expands the cluster / opens the record.
            if (
              typeof cesium.ScreenSpaceEventType.LEFT_CLICK === 'number'
            ) {
              inputHandler.setInputAction((movement) => {
                const pos = movement?.position;
                if (!pos || !viewer) return;
                // Anchor-placement flow takes precedence over pin select.
                if (anchorDragModeRef.current) {
                  const onMapClickCb = onMapClickRef.current;
                  if (!onMapClickCb) return;
                  try {
                    const ellipsoid = safeScene(viewer)?.globe?.ellipsoid;
                    const cart = viewer.camera?.pickEllipsoid?.(pos, ellipsoid);
                    if (!cart) return;
                    const carto = cesium.Cartographic.fromCartesian(cart);
                    const lat = cesium.Math.toDegrees(carto.latitude);
                    const lon = cesium.Math.toDegrees(carto.longitude);
                    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
                    onMapClickCb({ lat, lon });
                  } catch (clickErr) {
                    // eslint-disable-next-line no-console
                    console.warn('[geo_hub] anchor map-click pick failed', clickErr);
                  }
                  return;
                }
                // Pin-select flow.
                const onPinSelectCb = onPinSelectRef.current;
                if (!onPinSelectCb) return;
                try {
                  // ``viewer.scene`` throws on a destroyed viewer — a click
                  // can land in the same tick navigation tears it down.
                  const scene = safeScene(viewer);
                  if (!scene) return;
                  let picks: CesiumPickedFeatureLike[] = [];
                  if (typeof scene?.drillPick === 'function') {
                    picks = scene.drillPick(pos, 8) ?? [];
                  } else if (typeof scene?.pick === 'function') {
                    const single = scene.pick(pos);
                    if (single) picks = [single];
                  }
                  for (const picked of picks) {
                    const props = picked?.id?.properties;
                    if (!props) continue;
                    // Cesium ``PropertyBag`` exposes values via getValue(),
                    // but our static properties are also readable directly.
                    let bag: Record<string, unknown> | undefined;
                    if (typeof props.getValue === 'function') {
                      try {
                        bag = props.getValue();
                      } catch {
                        bag = undefined;
                      }
                    }
                    const tagFromBag =
                      bag && typeof bag._oeGeoHubPinTag === 'string'
                        ? bag._oeGeoHubPinTag
                        : undefined;
                    const tagDirect =
                      typeof props._oeGeoHubPinTag === 'string'
                        ? props._oeGeoHubPinTag
                        : undefined;
                    const tag = tagFromBag ?? tagDirect;
                    if (!tag) continue;
                    // Cluster pins carry their member project ids so the
                    // page can fit-to-bounds on expand.
                    const rawClusterIds =
                      (bag && bag._oeGeoHubClusterProjects) ??
                      props._oeGeoHubClusterProjects;
                    const clusterProjectIds = Array.isArray(rawClusterIds)
                      ? rawClusterIds.filter(
                          (x): x is string => typeof x === 'string',
                        )
                      : undefined;
                    onPinSelectCb({ tag, clusterProjectIds });
                    return;
                  }
                } catch (pickErr) {
                  // eslint-disable-next-line no-console
                  console.warn('[geo_hub] pin pick failed', pickErr);
                }
              }, cesium.ScreenSpaceEventType.LEFT_CLICK);
            }

            // Pointer leaving the canvas should reset the HUD to "—".
            const canvas = v.scene.canvas;
            const handlePointerLeave = () => {
              pendingMouse = null;
              scheduleFlush();
            };
            canvas.addEventListener('pointerleave', handlePointerLeave);
            canvas.addEventListener('pointerout', handlePointerLeave);
            // Wrap destroy() so cleanup also removes the DOM listeners
            // we attached above.
            const originalDestroy = inputHandler.destroy.bind(inputHandler);
            inputHandler.destroy = () => {
              try {
                canvas.removeEventListener('pointerleave', handlePointerLeave);
                canvas.removeEventListener('pointerout', handlePointerLeave);
              } catch {
                /* canvas already detached — ignore */
              }
              originalDestroy();
            };
          }
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn('[geo_hub] mouse-move HUD wiring failed', err);
        }

        // Camera change → heading + altitude. The underlying Cesium
        // event already debounces (only fires when camera state
        // actually changed past a threshold), so no rAF needed here.
        try {
          if (v.camera?.changed?.addEventListener) {
            const emitCamera = () => {
              const cb = onCameraChangeRef.current;
              if (!cb || !viewer) return;
              try {
                const headingRad = viewer.camera.heading;
                let headingDeg = cesium.Math.toDegrees(headingRad);
                // Normalise to [0, 360).
                headingDeg = ((headingDeg % 360) + 360) % 360;
                const cameraAltitudeM = viewer.camera.positionCartographic.height;
                if (
                  Number.isFinite(headingDeg) &&
                  Number.isFinite(cameraAltitudeM)
                ) {
                  cb({ headingDeg, cameraAltitudeM });
                }
              } catch {
                /* camera not yet ready — skip this tick */
              }
            };
            removeCameraListener = v.camera.changed.addEventListener(emitCamera);
            // Emit once immediately so the HUD doesn't read "—" until
            // the user nudges the camera.
            emitCamera();
          }
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn('[geo_hub] camera-change HUD wiring failed', err);
        }

        setCesiumStatus('loaded');
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error('[geo_hub] Cesium viewer init failed', err);
        // The module imported fine — this is a runtime init failure
        // (WebGL blocked, GPU disabled, transient bug). Distinct status
        // so the UI offers a retry button rather than an install hint.
        setCesiumStatus('init_failed');
      }
    })();

    return () => {
      disposed = true;
      if (rafHandle !== null) {
        try {
          window.cancelAnimationFrame(rafHandle);
        } catch {
          /* already cancelled — ignore */
        }
        rafHandle = null;
      }
      if (removeCameraListener) {
        try {
          removeCameraListener();
        } catch {
          /* listener already gone — ignore */
        }
        removeCameraListener = null;
      }
      if (inputHandler) {
        try {
          inputHandler.destroy();
        } catch {
          /* already destroyed — ignore */
        }
        inputHandler = null;
      }
      if (viewer) {
        try {
          viewer.destroy();
        } catch {
          /* viewer already gone — ignore */
        }
      }
      viewerRef.current = null;
      cesiumRef.current = null;
      pinEntitiesRef.current = [];
      searchPinEntityRef.current = null;
      loadedTilesetsRef.current = new Map();
      // A freshly-mounted viewer always gets a chance to auto-zoom again.
      hasAutoZoomedRef.current = false;
      try {
        onViewerReady?.(null);
      } catch (cbErr) {
        // eslint-disable-next-line no-console
        console.warn('[geo_hub] onViewerReady teardown threw', cbErr);
      }
    };
    // ``signature`` collapses ``mapConfig`` into a stable string that
    // only changes when something the viewer actually renders changes.
    // ``reloadKey`` is bumped by the retry button so a user-initiated
    // retry after init_failed forces a fresh attempt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, reloadKey]);

  // Stable signature for the pin layers — derived from the ids of each
  // pin so a refetch with identical content does not re-run the effect.
  const pinSignature = useMemo(() => {
    if (!pins) return 'nil';
    const hse = pins.hse.map((p) => p.incident_id).join(',');
    const punch = pins.punchlist.map((p) => p.item_id).join(',');
    const diary = pins.diary.map((p) => p.photo_id).join(',');
    const projects = (pins.projects ?? [])
      .map((p) => p.project_id)
      .join(',');
    return `hse:${hse}|pl:${punch}|dp:${diary}|pj:${projects}`;
  }, [pins]);

  // Incremental pin rendering — runs AFTER the viewer effect (and
  // whenever ``pins`` or the viewer status flip). We remove only the
  // entities we added ourselves so the viewer's other entities (added
  // by other future code paths) are not impacted.
  useEffect(() => {
    const v = viewerRef.current;
    const cesium = cesiumRef.current;
    if (!v || !cesium || cesiumStatus !== 'loaded') return;

    // Remove previously-added pin entities.
    for (const ent of pinEntitiesRef.current) {
      try {
        v.entities.remove(ent);
      } catch {
        /* entity may have been swept by viewer destroy — ignore */
      }
    }
    pinEntitiesRef.current = [];

    if (!pins) return;

    const addPin = (
      lon: number,
      lat: number,
      color: unknown,
      label: string,
      tag: string,
    ): void => {
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
      try {
        const ent = v.entities.add({
          position: cesium.Cartesian3.fromDegrees(lon, lat, 0),
          point: {
            pixelSize: 12,
            color,
            outlineColor: cesium.Color.WHITE,
            outlineWidth: 2,
            // Heights above the terrain surface so points are visible
            // even where the model dips below the ellipsoid.
            heightReference: 1, // Cesium.HeightReference.CLAMP_TO_GROUND
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: label,
            font: '12px sans-serif',
            pixelOffset: { x: 0, y: -18 },
            fillColor: cesium.Color.WHITE,
            outlineColor: cesium.Color.fromCssColorString?.('#000') ?? cesium.Color.WHITE,
            outlineWidth: 2,
            style: 2, // Cesium.LabelStyle.FILL_AND_OUTLINE
            showBackground: true,
            backgroundColor: cesium.Color.fromCssColorString?.('rgba(15,23,42,0.75)'),
            scale: 0.85,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          properties: { _oeGeoHubPinTag: tag },
        });
        pinEntitiesRef.current.push(ent);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[geo_hub] pin add failed', tag, err);
      }
    };

    for (const p of pins.hse) {
      addPin(
        p.lon,
        p.lat,
        cesium.Color.RED,
        p.title ? `HSE: ${p.title}` : `HSE ${p.incident_number}`,
        `hse:${p.incident_id}`,
      );
    }
    for (const p of pins.punchlist) {
      addPin(
        p.lon,
        p.lat,
        cesium.Color.ORANGE,
        `Punch: ${p.title}`,
        `punch:${p.item_id}`,
      );
    }
    for (const p of pins.diary) {
      addPin(
        p.lon,
        p.lat,
        cesium.Color.DODGERBLUE,
        p.is_drone ? 'Drone photo' : p.is_360 ? '360° photo' : 'Diary photo',
        `diary:${p.photo_id}`,
      );
    }
    // Global Geo Hub project pins — clustered + per-project-type
    // iconography. We bucket nearby pins into clusters whose tightness
    // depends on the camera altitude; clusters with size > 1 render as
    // a single labelled circle ("5 projects") and individual pins use
    // the project_type/status palette.
    const projects = pins.projects ?? [];
    if (projects.length > 0) {
      // Approximate the camera altitude to size the cluster threshold.
      // Falls back to a permissive threshold if camera state is unread.
      let altitudeM = 1_000_000;
      try {
        const carto = v.camera?.positionCartographic;
        if (carto && Number.isFinite(carto.height)) {
          altitudeM = carto.height;
        }
      } catch {
        /* camera not yet ready */
      }
      const threshold = clusterThresholdForAltitude(altitudeM);
      const clusters: PinCluster[] =
        threshold > 0
          ? clusterProjects(projects, threshold)
          : projects.map((p) => ({
              lat: Number(p.lat),
              lon: Number(p.lon),
              projects: [p],
            }));

      const addCluster = (cluster: PinCluster): void => {
        const { lat, lon, projects: members } = cluster;
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        if (members.length > 1) {
          // Cluster pin — circle with a count badge in the label.
          try {
            const ent = v.entities.add({
              position: cesium.Cartesian3.fromDegrees(lon, lat, 0),
              point: {
                pixelSize: 18,
                color:
                  cesium.Color.fromCssColorString?.('rgba(37,99,235,0.85)') ??
                  cesium.Color.DODGERBLUE,
                outlineColor: cesium.Color.WHITE,
                outlineWidth: 3,
                heightReference: 1,
                disableDepthTestDistance: Number.POSITIVE_INFINITY,
              },
              label: {
                text: String(members.length),
                font: 'bold 12px sans-serif',
                pixelOffset: { x: 0, y: 0 },
                fillColor: cesium.Color.WHITE,
                outlineColor:
                  cesium.Color.fromCssColorString?.('rgba(0,0,0,0.65)') ??
                  cesium.Color.WHITE,
                outlineWidth: 1,
                style: 2, // FILL_AND_OUTLINE
                showBackground: false,
                scale: 0.9,
                disableDepthTestDistance: Number.POSITIVE_INFINITY,
              },
              properties: {
                _oeGeoHubPinTag: `cluster:${members.length}:${lat.toFixed(3)},${lon.toFixed(3)}`,
                _oeGeoHubClusterSize: members.length,
                _oeGeoHubClusterProjects: members.map((m) => m.project_id),
              },
            });
            pinEntitiesRef.current.push(ent);
          } catch (err) {
            // eslint-disable-next-line no-console
            console.warn('[geo_hub] cluster add failed', err);
          }
          return;
        }
        // Single-project cluster → render as a typed project pin.
        const p = members[0];
        if (!p) return;
        const family = iconFamilyForProjectType(p.project_type ?? null);
        const css = colorForProjectStatus(p.status ?? null);
        const color =
          cesium.Color.fromCssColorString?.(css) ??
          cesium.Color.LIMEGREEN ??
          cesium.Color.WHITE;
        // Icon-family hint encoded in the entity properties so click
        // handlers (future) can render the appropriate sidebar card.
        // Cesium ``point`` doesn't natively render a glyph; we encode
        // family via the outline width + colour so residential is
        // visually distinct from commercial / civil at a glance.
        const familyOutlineWidth =
          family === 'residential'
            ? 2
            : family === 'commercial'
              ? 3
              : family === 'civil'
                ? 4
                : 2;
        try {
          const ent = v.entities.add({
            position: cesium.Cartesian3.fromDegrees(lon, lat, 0),
            point: {
              pixelSize: 12,
              color,
              outlineColor: cesium.Color.WHITE,
              outlineWidth: familyOutlineWidth,
              heightReference: 1,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            label: {
              text: pinTooltipLabel(p),
              font: '11px sans-serif',
              pixelOffset: { x: 0, y: -20 },
              fillColor: cesium.Color.WHITE,
              outlineColor:
                cesium.Color.fromCssColorString?.('#000') ?? cesium.Color.WHITE,
              outlineWidth: 2,
              style: 2,
              showBackground: true,
              backgroundColor: cesium.Color.fromCssColorString?.(
                'rgba(15,23,42,0.75)',
              ),
              scale: 0.85,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            properties: {
              _oeGeoHubPinTag: `project:${p.project_id}`,
              _oeGeoHubProjectType: p.project_type ?? 'unknown',
              _oeGeoHubIconFamily: family,
              _oeGeoHubStatus: p.status ?? 'unknown',
            },
          });
          pinEntitiesRef.current.push(ent);
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn('[geo_hub] project pin add failed', err);
        }
      };

      for (const cluster of clusters) addCluster(cluster);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pinSignature, cesiumStatus]);

  // ── Focused-tileset flyTo ──────────────────────────────────────────────
  //
  // When the page deep-links into the geo viewer with a ``?model=`` query
  // param, the host page maps that to a Tileset.id and passes it here.
  // We fly to the matching tileset's bounding sphere once it has loaded —
  // ``Cesium3DTileset.fromUrl`` resolves before the root tile is ready,
  // so we await ``readyPromise`` (when present) before flying.
  useEffect(() => {
    if (!focusedTilesetId) return;
    if (cesiumStatus !== 'loaded') return;
    const v = viewerRef.current;
    if (!v) return;
    let cancelled = false;
    (async () => {
      // Poll for the tileset to appear in the loaded map — the viewer
      // effect adds entries as ``fromUrl()`` resolves. Cap the wait so
      // a stale focus id never holds the camera hostage.
      const deadline = Date.now() + 8000;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let tileset: any = loadedTilesetsRef.current.get(focusedTilesetId);
      while (!tileset && Date.now() < deadline && !cancelled) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        tileset = loadedTilesetsRef.current.get(focusedTilesetId);
      }
      if (cancelled || !tileset) return;
      // Wait for the root tile to be ready so ``boundingSphere`` is
      // populated. ``readyPromise`` was renamed in Cesium 1.107 — handle
      // both ``ready`` boolean and the legacy ``readyPromise``.
      try {
        if (tileset.readyPromise && typeof tileset.readyPromise.then === 'function') {
          await tileset.readyPromise;
        }
      } catch {
        /* tileset never became ready — degrade silently */
      }
      if (cancelled) return;
      const sphere = tileset.boundingSphere;
      if (!sphere) return;
      try {
        if (typeof v.camera.flyToBoundingSphere === 'function') {
          v.camera.flyToBoundingSphere(sphere, { duration: 1.5 });
        } else {
          // Fallback: aim the camera at the sphere centre. Less ideal —
          // no automatic zoom to fit — but still better than leaving the
          // user at the project anchor.
          v.camera.flyTo({ destination: sphere.center ?? sphere });
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[geo_hub] flyToBoundingSphere failed', err);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusedTilesetId, cesiumStatus, signature]);

  // ── Scene-mode morph ─────────────────────────────────────────────────
  //
  // Runtime toggle between 3D globe / 2D top-down / Columbus 2.5-D. The
  // initial mode is wired through the Viewer constructor (above) so the
  // first paint already matches the user's saved preference; this effect
  // handles every subsequent change without rebuilding the viewer.
  //
  // ``scene.mode`` is compared against the target enum before issuing a
  // morph so rapidly toggling back to the current mode doesn't trigger a
  // 1.5-second redundant animation.
  useEffect(() => {
    if (cesiumStatus !== 'loaded') return;
    const v = viewerRef.current;
    const cesium = cesiumRef.current;
    if (!v || !cesium) return;
    const target = sceneMode ?? '3d';
    const targetEnum = _sceneModeEnum(cesium, target);
    try {
      // ``v.scene`` is a getter that THROWS on a destroyed viewer, so read
      // it once through ``safeScene`` rather than dereferencing it five
      // times below (each of which would throw during a teardown race).
      const scene = safeScene(v);
      if (!scene) return;
      if (scene.mode === targetEnum) return;
      if (target === '2d' && typeof scene.morphTo2D === 'function') {
        scene.morphTo2D(1.5);
      } else if (
        target === 'columbus' &&
        typeof scene.morphToColumbusView === 'function'
      ) {
        scene.morphToColumbusView(1.5);
      } else if (typeof scene.morphTo3D === 'function') {
        scene.morphTo3D(1.5);
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[geo_hub] sceneMode morph failed', target, err);
    }
  }, [sceneMode, cesiumStatus]);

  // ── Focused-project flyTo (global view only) ─────────────────────────
  //
  // When a user clicks an anchored-project entry in the left rail we fly
  // the camera to that anchor at a friendly altitude. Independent of the
  // tileset focus effect — global mode never has tilesets — and idempotent
  // for the same project (the effect deps reset on null/reselect).
  useEffect(() => {
    if (!focusedProject) return;
    if (cesiumStatus !== 'loaded') return;
    const v = viewerRef.current;
    const cesium = cesiumRef.current;
    if (!v || !cesium) return;
    try {
      const lat = Number(focusedProject.lat);
      const lon = Number(focusedProject.lon);
      const alt = Number(focusedProject.alt || 0);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      v.camera.flyTo({
        destination: cesium.Cartesian3.fromDegrees(
          lon,
          lat,
          Math.max(alt + 800, 2500),
        ),
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[geo_hub] focusedProject flyTo failed', err);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusedProject?.project_id, cesiumStatus]);

  // ── Generic flyToTarget (used by OverlaySidebar rows) ────────────────
  //
  // Fires whenever the caller's ``flyToTarget.key`` changes — distinct
  // nonce per click so re-clicking the same row re-flies. Independent of
  // ``focusedProject`` so the two layers never stomp each other.
  useEffect(() => {
    if (!flyToTarget) return;
    if (cesiumStatus !== 'loaded') return;
    const v = viewerRef.current;
    const cesium = cesiumRef.current;
    if (!v || !cesium) return;
    try {
      const { lat, lon } = flyToTarget;
      const baseAlt = Number(flyToTarget.alt ?? 0);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      v.camera.flyTo({
        destination: cesium.Cartesian3.fromDegrees(
          lon,
          lat,
          Math.max(baseAlt + 800, 2500),
        ),
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[geo_hub] flyToTarget failed', err);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flyToTarget?.key, cesiumStatus]);

  // ── Address-search pin (global view) ────────────────────────────────
  //
  // Renders a single visually-distinct accent-blue point with a label
  // callout for the latest hit from the address-search overlay. We fly
  // the camera to the coordinates with a friendlier rooftop-altitude
  // (~2 km) so the user lands close enough to recognise the place but
  // still sees surrounding context.
  //
  // Reliability invariants:
  //
  //   * If ``searchPin`` is set BEFORE Cesium finishes loading we MUST
  //     replay the add + fly once status flips to 'loaded'. The effect
  //     re-runs on ``cesiumStatus`` change so the closure picks up the
  //     latest searchPin then.
  //   * Pre-load attempts emit a single ``console.warn`` so developers
  //     debugging "I selected an address but nothing happened" can see
  //     why immediately in DevTools.
  //   * Changes to ``cesiumStatus`` away from 'loaded' (rare — the
  //     viewer doesn't downgrade) are skipped before the early return
  //     so the existing pin never gets wiped by a status flicker.
  useEffect(() => {
    if (cesiumStatus !== 'loaded') {
      if (searchPin) {
        // eslint-disable-next-line no-console
        console.warn(
          '[geo_hub] searchPin set before Cesium loaded - will replay once cesiumStatus="loaded".',
          { cesiumStatus, searchPin },
        );
      }
      return;
    }
    const v = viewerRef.current;
    const cesium = cesiumRef.current;
    if (!v || !cesium) return;

    // Always clear the previous pin first — switching addresses must
    // not leave a stale marker on the globe.
    if (searchPinEntityRef.current) {
      try {
        v.entities.remove(searchPinEntityRef.current);
      } catch {
        /* entity already gone — ignore */
      }
      searchPinEntityRef.current = null;
    }

    if (!searchPin) return;
    const lat = Number(searchPin.lat);
    const lon = Number(searchPin.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      // eslint-disable-next-line no-console
      console.warn(
        '[geo_hub] searchPin rejected - lat/lon non-finite after Number()',
        { lat, lon, original: searchPin },
      );
      return;
    }

    try {
      const accent =
        cesium.Color.fromCssColorString?.('#0ea5e9') ??
        cesium.Color.DODGERBLUE;
      // Note: Cartesian3.fromDegrees is (longitude, latitude, height).
      // Mixing the order silently places the pin in the wrong hemisphere.
      const ent = v.entities.add({
        position: cesium.Cartesian3.fromDegrees(lon, lat, 0),
        point: {
          pixelSize: 16,
          color: accent,
          outlineColor: cesium.Color.WHITE,
          outlineWidth: 3,
          heightReference: 1, // CLAMP_TO_GROUND
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          text: searchPin.name.length > 80
            ? `${searchPin.name.slice(0, 77)}…`
            : searchPin.name,
          font: '12px sans-serif',
          pixelOffset: { x: 0, y: -22 },
          fillColor: cesium.Color.WHITE,
          outlineColor:
            cesium.Color.fromCssColorString?.('#000') ?? cesium.Color.WHITE,
          outlineWidth: 2,
          style: 2, // FILL_AND_OUTLINE
          showBackground: true,
          backgroundColor:
            cesium.Color.fromCssColorString?.('rgba(14,165,233,0.92)') ??
            cesium.Color.DODGERBLUE,
          scale: 0.9,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        properties: { _oeGeoHubPinTag: 'search' },
      });
      searchPinEntityRef.current = ent;

      v.camera.flyTo({
        destination: cesium.Cartesian3.fromDegrees(lon, lat, 2000),
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[geo_hub] searchPin add/fly failed', err);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchPin?.lat, searchPin?.lon, searchPin?.name, cesiumStatus]);

  // ── Per-tileset visibility + opacity ────────────────────────────────
  //
  // Applies the parent-owned ``tilesetOverlayState`` to every loaded
  // ``Cesium3DTileset`` in ``loadedTilesetsRef``. Visibility is a simple
  // ``tileset.show = boolean``; opacity in 3D Tiles is exposed only via
  // the styling pipeline (``tileset.style``) using a ``color()`` literal
  // whose alpha channel is the desired opacity. We always assign a fresh
  // style — Cesium's style evaluator caches by reference, so mutating the
  // existing one in place silently no-ops on most builds.
  //
  // Tilesets missing from the state map fall back to the defaults
  // (``visible: true`` / ``opacity: 1``) so callers who don't pass the
  // prop get the legacy "everything rendered, no dimming" behaviour.
  //
  // Re-runs on:
  //   * cesiumStatus flip ('pending' → 'loaded') — the loaded map starts
  //     populating as tilesets resolve, so we have to re-apply once the
  //     viewer is ready.
  //   * signature change — destroys + re-creates the viewer, so the
  //     loaded map is rebuilt with new ids; effect re-applies the saved
  //     prefs to the freshly-loaded primitives.
  //   * tilesetOverlayState change — user toggled visibility or moved
  //     a slider; cheap update path that does NOT touch the viewer.
  useEffect(() => {
    if (cesiumStatus !== 'loaded') return;
    const cesium = cesiumRef.current;
    if (!cesium) return;
    const state = tilesetOverlayState ?? {};
    const StyleCtor = cesium.Cesium3DTileStyle;
    // Snapshot once per effect so async tileset resolution doesn't race
    // against the next render.
    const entries = Array.from(loadedTilesetsRef.current.entries());
    for (const [id, ts] of entries) {
      const tile = ts as {
        show?: boolean;
        style?: unknown;
      } | null;
      if (!tile) continue;
      const entry = state[id];
      const visible = entry?.visible !== false;
      // Clamp defensively even though the hook does it too — the prop
      // could be set externally / via tests with out-of-range numbers.
      const opacityRaw = entry?.opacity;
      const opacity =
        typeof opacityRaw === 'number' && Number.isFinite(opacityRaw)
          ? Math.min(1, Math.max(0, opacityRaw))
          : 1;
      try {
        tile.show = visible;
      } catch {
        /* primitive already disposed — ignore */
      }
      // Skip the style assignment when opacity is fully opaque AND no
      // style was previously assigned — keeps the default rendering path
      // (textured tiles unmodified) which is the most natural look.
      // Once we've dimmed once we always keep the style around so going
      // back to 1.0 just sets alpha to 1 in the existing color literal.
      if (!StyleCtor) {
        // Older Cesium build without the styling API — show/hide still
        // works, opacity degrades silently. Logged once per session
        // would be ideal but a quiet no-op avoids console noise.
        continue;
      }
      try {
        // ``color("white", N)`` multiplies each tile's natural colour by
        // white (no tint) and sets alpha to ``N``. Cesium parses the
        // expression once and reuses it; assigning a fresh instance is
        // the documented way to update.
        tile.style = new StyleCtor({
          color: `color("white", ${opacity})`,
        });
      } catch {
        /* malformed style or primitive disposed — degrade silently */
      }
    }
    // ``signature`` is included so the effect re-applies after the viewer
    // is rebuilt (which empties + re-fills loadedTilesetsRef).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tilesetOverlayState, cesiumStatus, signature]);

  // ── Fit-to-data ────────────────────────────────────────────────────
  //
  // Computes the aggregate bounding sphere over every visible piece of
  // data (loaded 3D Tilesets + pin layers + search pin + map anchor) and
  // flies the camera to it. Used by:
  //
  //   * The auto-zoom effect on first mount once at least one piece of
  //     data has arrived. ``hasAutoZoomedRef`` guards against re-runs.
  //   * The floating "Fit to data" button that lets the user re-trigger
  //     the same zoom after manual navigation.
  //
  // Best-effort throughout — silently no-ops when there is nothing to
  // zoom to (keeps the default world view) or when Cesium's BoundingSphere
  // helpers aren't available in the bundled build.
  const fitToData = useCallback((): boolean => {
    const v = viewerRef.current;
    const cesium = cesiumRef.current;
    if (!v || !cesium) return false;
    if (!cesium.BoundingSphere || typeof cesium.BoundingSphere.fromPoints !== 'function') {
      return false;
    }
    const points: unknown[] = [];
    const spheres: unknown[] = [];

    // 1. Tileset bounding spheres — these are the most spatially-
    //    meaningful, so prefer them when present.
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      for (const tileset of loadedTilesetsRef.current.values() as Iterable<any>) {
        const sphere = tileset?.boundingSphere;
        if (sphere) spheres.push(sphere);
      }
    } catch {
      /* iterating a swept map — ignore */
    }

    // 2. Pin layers (HSE / punch / diary / projects).
    const pushPoint = (lonRaw: unknown, latRaw: unknown): void => {
      const lon = Number(lonRaw);
      const lat = Number(latRaw);
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
      try {
        points.push(cesium.Cartesian3.fromDegrees(lon, lat, 0));
      } catch {
        /* fromDegrees defensive — skip bad coord */
      }
    };
    if (pins) {
      for (const p of pins.hse) pushPoint(p.lon, p.lat);
      for (const p of pins.punchlist) pushPoint(p.lon, p.lat);
      for (const p of pins.diary) pushPoint(p.lon, p.lat);
      for (const p of pins.projects ?? []) pushPoint(p.lon, p.lat);
    }

    // 3. Search pin + map anchor.
    if (searchPin) pushPoint(searchPin.lon, searchPin.lat);
    if (mapConfig?.anchor) pushPoint(mapConfig.anchor.lon, mapConfig.anchor.lat);

    // Nothing to zoom to — keep the default view.
    if (points.length === 0 && spheres.length === 0) return false;

    try {
      // Choose what to frame. A loaded 3D model is the primary content the
      // user came to see, so when any tileset bounding sphere is present we
      // frame the tileset(s) ALONE and ignore the project anchor and pins.
      //
      // Why: the b3dm models can be georeferenced with a large vertical
      // offset (hundreds of metres to several km above the ellipsoid). The
      // project anchor sits at altitude 0, so unioning it with a high model
      // gave a bounding sphere whose radius spanned that whole vertical gap,
      // and flyToBoundingSphere then parked the eye kilometres out with the
      // building a distant speck (the "3D model not visible" report). Framing
      // the tileset sphere on its own puts the camera a few hundred metres
      // from the model regardless of its absolute height.
      let aggregate: unknown = null;
      if (spheres.length > 0) {
        if (spheres.length === 1) {
          aggregate = spheres[0];
        } else if (typeof cesium.BoundingSphere.fromBoundingSpheres === 'function') {
          aggregate = cesium.BoundingSphere.fromBoundingSpheres(spheres);
        } else {
          aggregate = spheres[0];
        }
      } else if (points.length > 0) {
        aggregate = cesium.BoundingSphere.fromPoints(points);
      }
      if (!aggregate) return false;
      if (typeof v.camera.flyToBoundingSphere === 'function') {
        v.camera.flyToBoundingSphere(aggregate, { duration: 1.5 });
        return true;
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[geo_hub] fitToData failed', err);
    }
    return false;
  }, [pins, searchPin, mapConfig]);

  // Manual "Fit to data" button handler — bypasses the auto-zoom guard
  // so the user can always re-run the fit even after panning the camera.
  const handleFitToDataClick = useCallback(() => {
    fitToData();
  }, [fitToData]);

  // Initial-mount auto-zoom. Runs whenever the viewer becomes loaded OR
  // any data the fit depends on changes; the ``hasAutoZoomedRef`` flag
  // means it only actually flies the camera ONCE per viewer lifetime,
  // satisfying "don't re-zoom when user manually navigates and a new
  // overlay loads later". A small timeout gives 3D Tilesets a chance to
  // populate their boundingSphere after fromUrl() resolves.
  const pinDataLen = (pins?.hse.length ?? 0)
    + (pins?.punchlist.length ?? 0)
    + (pins?.diary.length ?? 0)
    + (pins?.projects?.length ?? 0);
  const tilesetCount = mapConfig?.tilesets?.filter(
    (t) => t.status === 'ready' && t.tileset_json_uri,
  ).length ?? 0;
  useEffect(() => {
    if (cesiumStatus !== 'loaded') return;
    if (hasAutoZoomedRef.current) return;
    // When the only thing to frame is the project anchor itself (no
    // tilesets, no pins, no address-search hit), the instant ``setView``
    // run at viewer init has already framed it. Calling fitToData here
    // would build a bounding sphere from a single point (radius 0), which
    // Cesium's flyToBoundingSphere reads as "drop the camera onto that
    // exact spot", a jarring second camera move right after first paint,
    // sometimes ending at ground level. Mark auto-zoom done and bail.
    if (tilesetCount === 0 && pinDataLen === 0 && !searchPin) {
      hasAutoZoomedRef.current = true;
      return;
    }

    // With no tilesets to wait on, pins and address-search hits are already
    // in hand, so a short settle delay is all the fit needs.
    if (tilesetCount === 0) {
      const handle = window.setTimeout(() => {
        if (hasAutoZoomedRef.current) return;
        const flew = fitToData();
        if (flew) hasAutoZoomedRef.current = true;
      }, 200);
      return () => window.clearTimeout(handle);
    }

    // Tilesets present: a fixed timeout races the b3dm fetch and parse. A
    // large model whose ``boundingSphere`` has not populated yet would leave
    // the camera parked over the anchor with the building a distant speck
    // (the recurring "3D model not visible" report). Instead wait for the
    // loaded tilesets to register and their root tile to become ready, the
    // same approach the focused-tileset flyTo uses, then fit. The deadline
    // stops a tileset that never loads from holding the camera hostage.
    let cancelled = false;
    (async () => {
      const deadline = Date.now() + 8000;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const loaded = (): any[] => [...loadedTilesetsRef.current.values()];
      while (loaded().length === 0 && Date.now() < deadline && !cancelled) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      for (const tileset of loaded()) {
        if (cancelled) return;
        try {
          if (tileset?.readyPromise && typeof tileset.readyPromise.then === 'function') {
            await tileset.readyPromise;
          }
        } catch {
          /* tileset never became ready - degrade silently */
        }
      }
      if (cancelled || hasAutoZoomedRef.current) return;
      const flew = fitToData();
      if (flew) hasAutoZoomedRef.current = true;
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cesiumStatus, pinDataLen, tilesetCount, searchPin?.lat, searchPin?.lon]);

  return (
    <div className="relative h-full w-full">
      {/* Scoped style overrides for Cesium widget chrome.
          The project ships without ``cesium/Build/Cesium/Widgets/widgets.css``
          in the global CSS pipeline, so any widget that does render
          (timeline + animation in project/development modes, plus the
          attribution credit) inherits raw browser defaults — low
          contrast, often invisible against the dark globe. These rules
          give every visible Cesium widget a translucent dark plate with
          light text + a subtle outline so the user can actually see and
          click them. Constraints kept narrow so we never collide with
          unrelated app chrome. */}
      <style>{`
        /* Cesium's widgets.css is intentionally NOT bundled (see note above)
           - but without it, .cesium-viewer / .cesium-widget / canvas all
           fall back to browser defaults (300x150 canvas), so the globe
           renders into a tiny postage-stamp in the top-left corner.
           These five rules are the minimum from widgets.css needed for
           the canvas to fill its parent. */
        .cesium-viewer,
        .cesium-viewer-cesiumWidgetContainer,
        .cesium-widget {
          display: block;
          position: relative;
          width: 100%;
          height: 100%;
          margin: 0;
          padding: 0;
          overflow: hidden;
        }
        .cesium-widget canvas {
          width: 100%;
          height: 100%;
          touch-action: none;
        }
        .cesium-viewer .cesium-widget-credits {
          color: rgb(226 232 240 / 0.85);
          font-size: 10px;
          background: rgba(15, 23, 42, 0.55);
          padding: 2px 6px;
          border-radius: 4px;
          backdrop-filter: blur(4px);
        }
        .cesium-viewer .cesium-widget-credits a,
        .cesium-viewer .cesium-widget-credits a:visited {
          color: rgb(165 243 252 / 0.95);
        }
        .cesium-viewer .cesium-viewer-toolbar {
          top: 96px;
          right: 12px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .cesium-viewer .cesium-viewer-toolbar > * {
          background: rgba(15, 23, 42, 0.78);
          color: #f1f5f9;
          border: 1px solid rgba(255, 255, 255, 0.12);
          border-radius: 6px;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
        }
        .cesium-viewer .cesium-viewer-toolbar svg {
          fill: #f1f5f9;
        }
        .cesium-viewer .cesium-viewer-timelineContainer,
        .cesium-viewer .cesium-viewer-animationContainer {
          background: rgba(15, 23, 42, 0.78);
          border-radius: 6px;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
        }
      `}</style>
      <div
        ref={containerRef}
        data-testid="geo-hub-cesium-container"
        className="h-full w-full bg-slate-900"
      />
      {/* Open-data attribution overlay — required by the OpenStreetMap
          tile usage policy AND a visible legal-clarity signal for
          self-hosting users. Cesium's own credit container is hidden
          (to suppress the Ion default-token nag) so this owner-rendered
          disclosure keeps us compliant. Collapsed it's a tiny pill;
          clicked it lists every third-party component + its license so
          there's zero ambiguity about what the user can use commercially. */}
      <details
        className="group absolute bottom-1 left-1 z-10"
        data-testid="geo-hub-licenses"
      >
        <summary
          className={[
            'inline-flex cursor-pointer list-none items-center gap-1 rounded',
            'bg-black/40 px-1.5 py-0.5 text-[10px] leading-tight text-white/80',
            'backdrop-blur-sm hover:text-white',
            'marker:hidden [&::-webkit-details-marker]:hidden',
          ].join(' ')}
          title={t('geo_hub.licenses_title', {
            defaultValue: 'Open-data stack: click to view licenses',
          })}
        >
          <span aria-hidden>ⓘ</span>
          <span>
            {t('geo_hub.licenses_pill', {
              defaultValue: 'Open Data',
            })}
          </span>
        </summary>
        <div
          className={[
            'absolute bottom-full left-0 mb-1 w-72 rounded-md border border-white/15',
            'bg-slate-900/95 px-3 py-2 text-[11px] leading-relaxed text-slate-100',
            'shadow-lg backdrop-blur-md',
          ].join(' ')}
        >
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-300/90">
            {t('geo_hub.licenses_heading', {
              defaultValue: 'Open Data & Open Source',
            })}
          </div>
          <ul className="space-y-1">
            <li>
              <a
                href="https://github.com/CesiumGS/cesium/blob/main/LICENSE.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-300 hover:text-sky-200"
              >
                Cesium
              </a>{' '}
              <span className="text-slate-400">Apache 2.0 · 3D globe runtime</span>
            </li>
            <li>
              <a
                href="https://www.openstreetmap.org/copyright"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-300 hover:text-sky-200"
              >
                OpenStreetMap
              </a>{' '}
              <span className="text-slate-400">ODbL · map data and geocoding</span>
            </li>
            <li>
              <a
                href="https://carto.com/basemaps/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-300 hover:text-sky-200"
              >
                CARTO Basemaps
              </a>{' '}
              <span className="text-slate-400">CC BY 3.0 · keyless base imagery tiles</span>
            </li>
            <li>
              <a
                href="https://nominatim.org/release-docs/latest/api/Search/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-300 hover:text-sky-200"
              >
                Nominatim
              </a>{' '}
              <span className="text-slate-400">ODbL · structured geocoding</span>
            </li>
            <li>
              <a
                href="https://photon.komoot.io"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-300 hover:text-sky-200"
              >
                Photon
              </a>{' '}
              <span className="text-slate-400">Apache 2.0 · autocomplete geocoder</span>
            </li>
          </ul>
          <div className="mt-2 text-[10px] text-slate-400">
            {t('geo_hub.licenses_footer', {
              defaultValue:
                'No vendor lock-in. Self-host the entire stack. Cesium Ion + commercial imagery providers are intentionally not used.',
            })}
          </div>
        </div>
      </details>
      {cesiumStatus === 'pending' && (
        <div className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-slate-950/40 text-sm text-slate-200 backdrop-blur-sm">
          <div className="relative">
            <Globe2
              size={28}
              strokeWidth={1.5}
              className="text-emerald-300/80 animate-pulse"
            />
            <span
              aria-hidden
              className="absolute -inset-2 rounded-full bg-emerald-400/10 blur-xl"
            />
          </div>
          <span className="font-medium tracking-wide">
            {t('geo_hub.cesium_loading', {
              defaultValue: 'Loading Cesium...',
            })}
          </span>
          <span className="text-xs text-slate-400">
            {t('geo_hub.cesium_loading_hint', {
              defaultValue: 'Streaming the 3D globe runtime (~3 MB).',
            })}
          </span>
        </div>
      )}
      {cesiumStatus === 'absent' && (
        <div className="absolute inset-0 z-20 flex items-center justify-center p-6">
          <div
            role="alert"
            className="relative w-full max-w-md overflow-hidden rounded-xl border border-white/10 bg-slate-900/70 p-6 text-center text-slate-100 shadow-xl backdrop-blur-md ring-1 ring-white/5"
          >
            <div
              aria-hidden
              className="pointer-events-none absolute -inset-px rounded-xl bg-gradient-to-br from-amber-500/30 to-orange-500/20 opacity-60 blur-2xl ring-1 ring-amber-400/20"
            />
            <div className="relative">
              <div className="mx-auto mb-4 inline-flex h-10 w-10 items-center justify-center rounded-md bg-amber-500/15 text-amber-300 ring-1 ring-amber-400/30">
                <Download size={18} strokeWidth={2} />
              </div>
              <h3 className="text-base font-semibold text-white">
                {t('geo_hub.cesium_not_installed_title', {
                  defaultValue: 'CesiumJS is not installed',
                })}
              </h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-300">
                {t('geo_hub.cesium_not_installed', {
                  defaultValue:
                    'CesiumJS is not installed in this build. Geo viewer is in degraded mode.',
                })}
              </p>
              <code className="mt-4 inline-block rounded-sm bg-slate-800/80 px-2 py-1 font-mono text-xs text-slate-200 ring-1 ring-white/10">
                npm install cesium
              </code>
            </div>
          </div>
        </div>
      )}
      {cesiumStatus === 'init_failed' && (
        <div className="absolute inset-0 z-20 flex items-center justify-center p-6">
          <div
            role="alert"
            className="relative w-full max-w-md overflow-hidden rounded-xl border border-white/10 bg-slate-900/70 p-6 text-center text-slate-100 shadow-xl backdrop-blur-md ring-1 ring-white/5"
          >
            <div
              aria-hidden
              className="pointer-events-none absolute -inset-px rounded-xl bg-gradient-to-br from-red-500/30 to-rose-500/20 opacity-60 blur-2xl ring-1 ring-red-400/20"
            />
            <div className="relative">
              <div className="mx-auto mb-4 inline-flex h-10 w-10 items-center justify-center rounded-md bg-red-500/15 text-red-300 ring-1 ring-red-400/30">
                <AlertTriangle size={18} strokeWidth={2} />
              </div>
              <h3 className="text-base font-semibold text-white">
                {t('geo_hub.cesium_init_failed_title', {
                  defaultValue: 'Could not start the 3D globe',
                })}
              </h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-300">
                {t('geo_hub.cesium_init_failed_hint', {
                  defaultValue:
                    'The 3D globe runtime loaded but failed to initialise. This usually means WebGL is blocked or hardware acceleration is disabled in your browser.',
                })}
              </p>
              <button
                type="button"
                onClick={retryViewer}
                data-testid="geo-hub-cesium-retry"
                className={[
                  'mt-5 inline-flex items-center gap-1.5 rounded-md',
                  'bg-white px-3 py-1.5 text-xs font-semibold text-slate-900',
                  'shadow-sm transition hover:bg-slate-100',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60',
                ].join(' ')}
              >
                <RefreshCw size={13} strokeWidth={2.25} />
                {t('common.retry', { defaultValue: 'Retry' })}
              </button>
              <p className="mt-3 text-2xs text-slate-400">
                {t('geo_hub.cesium_init_failed_check', {
                  defaultValue:
                    'Tip: enable hardware acceleration in your browser settings, then click Retry.',
                })}
              </p>
            </div>
          </div>
        </div>
      )}
      {/* Floating "Fit to data" button — re-runs the auto-zoom that
          centred the camera on first mount. Useful after the user pans
          off into empty space or wants to re-frame after toggling
          overlays. Bottom-right keeps it clear of the left-rail
          anchored-projects panel and the bottom-left licenses pill.
          Only rendered once Cesium is up — hidden during 'pending' /
          'absent' / 'init_failed' because the action would no-op. */}
      {cesiumStatus === 'loaded' && (
        <button
          type="button"
          onClick={handleFitToDataClick}
          data-testid="geo-hub-fit-to-data"
          className={[
            'absolute bottom-3 right-3 z-10',
            'inline-flex items-center gap-1.5 rounded-md',
            'border border-white/15 bg-slate-900/75 px-2.5 py-1.5',
            'text-xs font-medium text-slate-100 shadow-lg backdrop-blur-md',
            'transition hover:bg-slate-800/85 hover:text-white',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/60',
          ].join(' ')}
          title={t('geo_hub.fit_to_data_hint', {
            defaultValue: 'Zoom the camera to fit all visible data',
          })}
          aria-label={t('geo_hub.fit_to_data_label', {
            defaultValue: 'Fit camera to data',
          })}
        >
          <Locate size={13} strokeWidth={2.25} />
          <span>
            {t('geo_hub.fit_to_data', {
              defaultValue: 'Fit to data',
            })}
          </span>
        </button>
      )}
      {/* Overlay slot — HUD, empty states, badges. Mounted last so it
          paints over the canvas; ``cesium`` canvas listens for input
          via its own event handlers and is therefore unaffected by
          ``pointer-events-none`` placement of HUD chrome above it. */}
      {overlay}
    </div>
  );
}

export default CesiumViewer;
