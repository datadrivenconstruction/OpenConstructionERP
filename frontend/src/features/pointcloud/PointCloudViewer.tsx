// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Interactive point-cloud viewer for the /pointcloud page.
 *
 * Downloads the server-decimated OEPC binary for one scan (see ./oepc.ts and
 * backend/app/modules/pointcloud/wire.py), drops the positions straight into a
 * THREE.Points geometry and renders with OrbitControls. Positions arrive
 * centre-relative so georeferenced clouds stay float32-precision-safe; the
 * world origin lives in the wire ``center``.
 *
 * Controls: color mode (RGB / height ramp / intensity / single color), point
 * size, on-screen draw density, server density (re-requests with a different
 * ``max_points`` cap), depth cue and re-fit. The scan may still be processing
 * server-side: 409 / 404 / 501 / 422 map to friendly status panels instead of
 * crashing the page.
 *
 * Inspection tools (all client-side, operating on the already-loaded
 * THREE.Points - see ./pointcloudTools.ts for the pure math behind each):
 *  - Cross-section: a world-Y height band rendered via clipping planes, plus
 *    a one-click top/plan view.
 *  - Measure: click points to trace a multi-segment path with a running total,
 *    plus straight-line / horizontal / vertical spread of the final segment.
 *  - Area & volume: draw a polygon on the ground for its plan area, then
 *    estimate cut / fill volume against a reference elevation (grid method).
 *  - Inspect: click a point to read its absolute scan/CRS coordinate.
 *  - Annotate: drop labelled pins with a note, listed in a side panel.
 *  - Clip box: an adjustable axis-aligned crop, also via clipping planes.
 *  - Preset views: top / front / side / iso plus fit-to-cloud.
 *  - Elevation legend: a height-ramp gradient key shown in "height" color
 *    mode, with an optional pinned custom range.
 *  - Snapshot: exports the current canvas view as a PNG.
 *  - Export: measurement paths, polygons and annotations to CSV.
 * Cross-section and clip-box planes compose (a point must satisfy both) via
 * ``renderer.localClippingEnabled`` + ``material.clippingPlanes`` - no
 * geometry is rebuilt or CPU-filtered per point, so this stays smooth at
 * millions of points. The measure / area / inspect / annotate tools share a
 * single pick pipeline (only one owns clicks at a time via ``pickMode``).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  AlertCircle,
  ArrowDownToLine,
  Boxes,
  Camera,
  Clock,
  CloudFog,
  Copy,
  Crop,
  Crosshair,
  Download,
  Eye,
  EyeOff,
  Gauge,
  Grid3x3,
  Layers,
  ListPlus,
  Loader2,
  MapPin,
  Maximize,
  Maximize2,
  Minimize2,
  Minus,
  Mountain,
  Move3d,
  Palette,
  PanelRight,
  PanelRightClose,
  Pentagon,
  Pin,
  PinOff,
  Plus,
  RefreshCw,
  RotateCcw,
  Ruler,
  Trash2,
  Triangle,
  Undo2,
  X,
} from 'lucide-react';
import { useThemeStore } from '@/stores/useThemeStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { boqApi } from '@/features/boq/api';
import { fetchScanPoints, ScanPointsError } from './api';
import { parseOepc, OepcParseError, type OepcCloud } from './oepc';
import {
  angleAtVertex,
  annotationsToCsv,
  boxMetrics,
  boxPlanes,
  chooseScaleBar,
  computePolylineMetrics,
  countPointsInBox,
  decimationStride,
  deriveCloudBounds,
  estimateVolumeVsPlane,
  formatAngle,
  formatAreaM2,
  formatLengthMm,
  formatMetersLabel,
  formatVolumeM3,
  heightSlicePlanes,
  isWithinPlanes,
  polygonAreaXZ,
  polylineToCsv,
  presetViewOffset,
  scaleClipBox,
  slugifyForFilename,
  worldToScanCoords,
  type BoxExtent,
  type PlaneEq,
  type PolylineMetrics,
  type PresetView,
  type Vec3,
  type VolumeEstimate,
} from './pointcloudTools';
import { fmtFixed } from '@/shared/lib/formatters';

export type ColorMode = 'rgb' | 'height' | 'intensity' | 'single';

type LoadPhase = 'loading' | 'ready' | 'error';
type ErrorKind = 'processing' | 'notfound' | 'reader' | 'decode' | 'generic';

/** The single pick tool that currently owns canvas clicks. Only one at a time
 *  so the tools never fight each other (or OrbitControls). */
type PickMode = 'none' | 'measure' | 'angle' | 'area' | 'inspect' | 'annotate';

/** An in-session labelled pin dropped on the cloud. Not persisted server-side
 *  yet; lives for the life of the viewer mount. */
interface Annotation {
  id: string;
  /** Viewer-frame (rotated, centre-relative) coordinate. */
  world: Vec3;
  /** Absolute scan/CRS coordinate. */
  scan: Vec3;
  note: string;
}

/** A named, colored segment of the cloud: an axis-aligned world-space region
 *  (captured from the clip box) plus the count of cloud points inside it.
 *  In-session only, like annotations - it feeds the BOQ hand-off and the
 *  isolate/hide visibility toggle. */
interface PointGroup {
  id: string;
  name: string;
  /** CSS hex, e.g. '#22c55e' - drives the swatch and the scene box wireframe. */
  color: string;
  /** Bounds in the rotated WORLD frame (same frame the clip box uses). */
  box: BoxExtent;
  /** Cloud points inside `box`, counted once at capture. */
  pointCount: number;
}

/** Distinct, high-contrast swatches cycled as groups are captured. */
const GROUP_COLORS = [
  '#22c55e',
  '#3b82f6',
  '#f97316',
  '#ec4899',
  '#a855f7',
  '#eab308',
  '#06b6d4',
  '#ef4444',
];

/** Density presets: the server evenly decimates to at most this many points. */
const DENSITY_OPTIONS = [
  { value: 250_000, labelKey: 'pointcloud.density_fast', fallback: 'Fast (250K)' },
  { value: 1_500_000, labelKey: 'pointcloud.density_balanced', fallback: 'Balanced (1.5M)' },
  { value: 3_000_000, labelKey: 'pointcloud.density_high', fallback: 'High (3M)' },
  { value: 6_000_000, labelKey: 'pointcloud.density_max', fallback: 'Maximum (6M)' },
] as const;

/** Scene backgrounds matching the BIM viewer's light / dark pair. */
const BG_LIGHT = 0xf0f2f5;
const BG_DARK = 0x1a1a2e;
/** Extra backdrop choices - a neutral slate and pure black give high-contrast
 *  studio looks that pros often switch to when reading fine surface detail. */
const BG_SLATE = 0x334155;
const BG_BLACK = 0x000000;

/** The viewer's backdrop can follow the app theme or be pinned to a fixed
 *  studio backdrop, independent of light/dark mode. */
type BgMode = 'theme' | 'light' | 'slate' | 'dark' | 'black';

/** Resolve a background mode to a concrete scene-clear colour. `theme` tracks
 *  the app's light/dark setting; the rest are fixed studio backdrops. */
function effectiveBgHex(mode: BgMode, resolvedTheme: string): number {
  switch (mode) {
    case 'light':
      return BG_LIGHT;
    case 'slate':
      return BG_SLATE;
    case 'dark':
      return BG_DARK;
    case 'black':
      return BG_BLACK;
    case 'theme':
    default:
      return resolvedTheme === 'dark' ? BG_DARK : BG_LIGHT;
  }
}

/** Fallback single color: the oe-blue accent. */
const SINGLE_COLOR = new THREE.Color(0x3b82f6);

/** Height-ramp stops, bottom to top (deep blue, cyan, green, yellow, red). */
const RAMP_STOPS: [number, number, number][] = [
  [0.19, 0.32, 0.93],
  [0.1, 0.74, 0.85],
  [0.18, 0.8, 0.35],
  [0.98, 0.83, 0.14],
  [0.94, 0.27, 0.18],
];

/** Sample the height ramp at t in [0, 1] into (r, g, b) 0-1 floats. */
function sampleRamp(t: number): [number, number, number] {
  const clamped = Math.min(1, Math.max(0, t));
  const scaled = clamped * (RAMP_STOPS.length - 1);
  const i = Math.min(RAMP_STOPS.length - 2, Math.floor(scaled));
  const f = scaled - i;
  const a = RAMP_STOPS[i] as [number, number, number];
  const b = RAMP_STOPS[i + 1] as [number, number, number];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

/** CSS gradient for the elevation legend, bottom (low/blue) to top
 *  (high/red) - built once from RAMP_STOPS so it stays in lockstep with
 *  `sampleRamp` above. */
const RAMP_GRADIENT_CSS = `linear-gradient(to top, ${RAMP_STOPS.map(
  ([r, g, b], i) =>
    `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}) ${
      (i / (RAMP_STOPS.length - 1)) * 100
    }%`,
).join(', ')})`;

/** High-visibility accent for the measure tool's line/markers/label -
 *  distinct from the oe-blue UI accent so it reads clearly against every
 *  color mode (RGB / height ramp / intensity / single color). */
const MEASURE_COLOR = 0xffd400;

/** Clip-box wireframe color - the oe-blue brand accent. */
const CLIP_BOX_COLOR = 0x3b82f6;

/** Area-polygon color (emerald) - reads as a distinct footprint outline. */
const AREA_COLOR = 0x22c55e;

/** Point-inspector marker color (cyan). */
const INSPECT_COLOR = 0x06b6d4;

/** Annotation pin color (orange). */
const ANNOTATION_COLOR = 0xf97316;

/** Angle-tool color (magenta) - distinct from the yellow measure path so the
 *  two picking tools never read as the same overlay. */
const ANGLE_COLOR = 0xec4899;

/** A soft round sprite for the points, built once and shared. Turning the
 *  default hard squares into feathered discs is the single biggest "reads like
 *  a real surface" upgrade, at no per-point cost (one texture lookup + an
 *  alpha test). Returns null in non-DOM/edge environments so the material
 *  falls back to square points instead of throwing. */
let discTexture: THREE.Texture | null = null;
let discTextureTried = false;
function getDiscTexture(): THREE.Texture | null {
  if (discTextureTried) return discTexture;
  discTextureTried = true;
  if (typeof document === 'undefined') return null;
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const r = size / 2;
  const gradient = ctx.createRadialGradient(r, r, 0, r, r, r);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.75, 'rgba(255,255,255,1)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(r, r, r, 0, Math.PI * 2);
  ctx.fill();
  discTexture = new THREE.CanvasTexture(canvas);
  discTexture.needsUpdate = true;
  return discTexture;
}

/** Upper bound on cloud samples fed to the grid volume estimate; keeps the
 *  synchronous compute responsive on multi-million-point clouds. */
const VOLUME_SAMPLE_BUDGET = 300_000;

/** Build the per-vertex color buffer for the requested mode. `heightRange`
 *  optionally overrides the auto (bbox-derived) min/max used by the
 *  'height' ramp, letting the elevation legend's "pin range" control
 *  narrow or shift the ramp for extra contrast. */
function buildColors(
  cloud: OepcCloud,
  mode: ColorMode,
  heightRange?: { min: number; max: number } | null,
): Float32Array {
  const n = cloud.pointCount;
  const colors = new Float32Array(n * 3);

  if (mode === 'rgb' && cloud.rgb) {
    for (let i = 0; i < n * 3; i++) colors[i] = (cloud.rgb[i] ?? 0) / 255;
    return colors;
  }

  if (mode === 'intensity' && cloud.intensity) {
    for (let i = 0; i < n; i++) {
      const v = Math.min(1, Math.max(0, cloud.intensity[i] ?? 0));
      // Slight lift so the darkest points stay visible on both themes.
      const g = 0.08 + v * 0.92;
      colors[i * 3] = g;
      colors[i * 3 + 1] = g;
      colors[i * 3 + 2] = g;
    }
    return colors;
  }

  if (mode === 'height') {
    // Ramp on the data's vertical axis (z in scan space), using the wire bbox
    // converted into the centre-relative frame the positions live in, unless
    // the caller pinned a custom range.
    const zMin = heightRange ? heightRange.min : cloud.bboxMin[2] - cloud.center[2];
    const zMax = heightRange ? heightRange.max : cloud.bboxMax[2] - cloud.center[2];
    const span = zMax - zMin || 1;
    for (let i = 0; i < n; i++) {
      const t = ((cloud.positions[i * 3 + 2] ?? 0) - zMin) / span;
      const [r, g, b] = sampleRamp(t);
      colors[i * 3] = r;
      colors[i * 3 + 1] = g;
      colors[i * 3 + 2] = b;
    }
    return colors;
  }

  // Single-color fallback.
  for (let i = 0; i < n; i++) {
    colors[i * 3] = SINGLE_COLOR.r;
    colors[i * 3 + 1] = SINGLE_COLOR.g;
    colors[i * 3 + 2] = SINGLE_COLOR.b;
  }
  return colors;
}

function formatPoints(n: number): string {
  if (n >= 1_000_000) return `${fmtFixed(n / 1_000_000, 1)}M`;
  if (n >= 1_000) return `${fmtFixed(n / 1_000, 0)}K`;
  return String(n);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 0)} KB`;
  return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
}

interface ToolbarButtonProps {
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  icon: typeof Layers;
  /** Accessible name + tooltip text. */
  label: string;
  /** Single-key shortcut shown in the tooltip and as a small kbd hint. */
  shortcut?: string;
  testId?: string;
  /** Optional count pill (e.g. captured groups) on the top-right corner. */
  badge?: number;
}

/** Icon-only button for the floating viewport toolbar. Square target, clear
 *  filled active state, a corner count badge, and a hover tooltip that also
 *  surfaces the keyboard shortcut - the professional-tool look the founder
 *  asked for. Theme-aware via semantic tokens; the tooltip inverts against the
 *  content colour so it reads on light and dark backdrops alike. */
function ToolbarButton({
  active,
  disabled,
  onClick,
  icon: Icon,
  label,
  shortcut,
  testId,
  badge,
}: ToolbarButtonProps) {
  return (
    <div className="group relative">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-pressed={active}
        aria-label={label}
        data-testid={testId}
        className={`relative inline-flex h-9 w-9 items-center justify-center rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
          active
            ? 'bg-oe-blue text-white shadow-sm'
            : 'text-content-secondary hover:bg-surface-tertiary hover:text-content-primary'
        }`}
      >
        <Icon size={17} />
        {badge != null && badge > 0 && (
          <span className="absolute -right-1 -top-1 inline-flex min-w-[1rem] items-center justify-center rounded-full bg-oe-blue px-1 text-[10px] font-semibold leading-none text-white ring-2 ring-surface-primary">
            {badge}
          </span>
        )}
      </button>
      <span className="pointer-events-none absolute left-1/2 top-full z-40 mt-2 hidden -translate-x-1/2 items-center gap-1.5 whitespace-nowrap rounded-md bg-content-primary px-2 py-1 text-2xs font-medium text-surface-primary shadow-lg group-hover:flex">
        {label}
        {shortcut && (
          <kbd className="rounded border border-surface-primary/30 px-1 font-sans text-[10px] font-semibold uppercase leading-tight">
            {shortcut}
          </kbd>
        )}
      </span>
    </div>
  );
}

/** Thin vertical rule separating tool groups on the floating toolbar. */
function ToolbarDivider() {
  return <span className="mx-0.5 h-6 w-px shrink-0 self-center bg-border-light" aria-hidden="true" />;
}

interface PointCloudViewerProps {
  scanId: string;
  /** Display label for the header, e.g. the scan source / format. */
  scanLabel?: string;
}

export function PointCloudViewer({ scanId, scanLabel }: PointCloudViewerProps) {
  const { t } = useTranslation();
  const resolvedTheme = useThemeStore((s) => s.resolved);
  // Quantity hand-off targets the active project's BOQ (mirrors the DWG
  // Takeoff flow); toasts confirm the add or the clipboard fallback.
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);

  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const pointsRef = useRef<THREE.Points | null>(null);
  /** Base point size derived from the cloud extent; the slider scales it. */
  const baseSizeRef = useRef(0.01);

  // ── Inspection-tools refs ────────────────────────────────────────────────
  /** Identity of the last `cloud.positions` buffer we reset tool state for -
   *  lets the reset effect tell "genuinely new/refetched data" apart from
   *  the refit-clone `{...prev}` trick in handleRefit (same typed array). */
  const lastPositionsRef = useRef<Float32Array | null>(null);
  const boxHelperRef = useRef<THREE.Box3Helper | null>(null);
  // Measure (multi-segment path): the vertices in world space + their scene
  // line / markers. Points live in a ref so extending the path never triggers
  // a per-vertex React re-render (only the derived metrics are state).
  const measurePointsRef = useRef<THREE.Vector3[]>([]);
  const measureLineRef = useRef<THREE.Line | null>(null);
  const measureMarkersRef = useRef<THREE.Mesh[]>([]);
  const measureLabelRef = useRef<HTMLDivElement | null>(null);
  // Area / volume polygon: world-space vertices + their boundary line/markers.
  const areaPointsRef = useRef<THREE.Vector3[]>([]);
  const areaLineRef = useRef<THREE.Line | null>(null);
  const areaMarkersRef = useRef<THREE.Mesh[]>([]);
  // Point inspector: a single highlighted marker.
  const inspectMarkerRef = useRef<THREE.Mesh | null>(null);
  // Annotation pins: id -> marker mesh, reconciled against the annotations
  // state by an effect below.
  const annotationMarkersRef = useRef<Map<string, THREE.Mesh>>(new Map());
  // Point groups: id -> colored box wireframe, reconciled against the groups
  // state by an effect below. Ever-increasing counter for auto-numbered names
  // so a name stays unique even after earlier groups are deleted.
  const groupHelpersRef = useRef<Map<string, THREE.Box3Helper>>(new Map());
  const groupCounterRef = useRef(0);
  // Angle tool (three-point): the picked vertices + their line / markers.
  const anglePointsRef = useRef<THREE.Vector3[]>([]);
  const angleLineRef = useRef<THREE.Line | null>(null);
  const angleMarkersRef = useRef<THREE.Mesh[]>([]);
  // Ground grid + orientation axes: a spatial reference frame under the cloud.
  const gridHelperRef = useRef<THREE.GridHelper | null>(null);
  const axesHelperRef = useRef<THREE.AxesHelper | null>(null);
  // Scale-bar overlay: the bar element (width set each frame) + its label. The
  // animation loop keeps both in sync with the camera without a re-render.
  const scaleBarRef = useRef<HTMLDivElement | null>(null);
  const scaleBarLabelRef = useRef<HTMLDivElement | null>(null);

  const [phase, setPhase] = useState<LoadPhase>('loading');
  const [errorKind, setErrorKind] = useState<ErrorKind>('generic');
  const [errorDetail, setErrorDetail] = useState('');
  const [progressBytes, setProgressBytes] = useState(0);
  const [cloud, setCloud] = useState<OepcCloud | null>(null);
  const [maxPoints, setMaxPoints] = useState<number>(1_500_000);
  const [colorMode, setColorMode] = useState<ColorMode>('single');
  const [sizeFactor, setSizeFactor] = useState(10);
  const [drawFraction, setDrawFraction] = useState(1);
  const [depthCue, setDepthCue] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [webglFailed, setWebglFailed] = useState(false);
  // A ground grid + orientation axes gives every scan an immediate sense of
  // scale and which way is up; on by default because it reads clearer.
  const [showGrid, setShowGrid] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [bgMode, setBgMode] = useState<BgMode>('theme');
  // The collapsible right-hand inspector panel (display settings + active-tool
  // readouts + layers/groups). Open by default; the toolbar toggles it.
  const [panelOpen, setPanelOpen] = useState(true);

  // ── Inspection-tools state ────────────────────────────────────────────
  const [sliceEnabled, setSliceEnabled] = useState(false);
  /** Both in metres ABOVE the cloud's lowest point (0 = bottom), not raw
   *  scan-frame coordinates - friendlier for "slice storey 2, 3m to 6m up". */
  const [sliceMin, setSliceMin] = useState(0);
  const [sliceMax, setSliceMax] = useState(0);
  const [clipEnabled, setClipEnabled] = useState(false);
  const [clipBox, setClipBox] = useState<BoxExtent | null>(null);
  const [heightRangeOverride, setHeightRangeOverride] = useState<{ min: number; max: number } | null>(
    null,
  );
  const [legendPinned, setLegendPinned] = useState(false);

  // The active pick tool + each pick tool's derived readout state.
  const [pickMode, setPickMode] = useState<PickMode>('none');
  const [pathMetrics, setPathMetrics] = useState<PolylineMetrics | null>(null);
  const [areaVertexCount, setAreaVertexCount] = useState(0);
  const [areaPlanArea, setAreaPlanArea] = useState(0);
  /** Lowest world-Y among the polygon vertices - the default cut/fill datum. */
  const [areaMinY, setAreaMinY] = useState(0);
  /** Explicit overrides for the volume estimate; null = use the derived
   *  default (lowest boundary point / bounds-scaled cell size). */
  const [volumeRefY, setVolumeRefY] = useState<number | null>(null);
  const [volumeCell, setVolumeCell] = useState<number | null>(null);
  const [volumeResult, setVolumeResult] = useState<VolumeEstimate | null>(null);
  const [inspectResult, setInspectResult] = useState<{ world: Vec3; scan: Vec3 } | null>(null);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  // Groups tool: the captured groups, whether the tool panel is open, and which
  // group (if any) is currently isolated (only its points shown). Plus a flag
  // so the BOQ hand-off can disable its buttons while a request is in flight.
  const [groups, setGroups] = useState<PointGroup[]>([]);
  const [groupsEnabled, setGroupsEnabled] = useState(false);
  const [isolatedGroupId, setIsolatedGroupId] = useState<string | null>(null);
  const [boqSending, setBoqSending] = useState(false);
  // Angle tool readout: the picked-vertex count (0-3) + the measured interior
  // angle at the middle vertex once all three are down.
  const [angleVertexCount, setAngleVertexCount] = useState(0);
  const [angleValue, setAngleValue] = useState<number | null>(null);

  // ── Scene lifecycle: one renderer per mount, disposed on unmount ─────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    // three.js (r163+) requires WebGL2 and throws when a context cannot be
    // created (e.g. headless Firefox / WebKit). Feature-detect first, then
    // guard the construction itself, so the page degrades to the notice below
    // instead of letting the throw reach the React error boundary.
    let renderer: THREE.WebGLRenderer;
    try {
      const probe = document.createElement('canvas').getContext('webgl2');
      if (probe == null) {
        setWebglFailed(true);
        return undefined;
      }
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    } catch {
      setWebglFailed(true);
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth || 1, container.clientHeight || 1);
    renderer.domElement.style.display = 'block';
    // Cross-section + clip-box both work by assigning per-material
    // `clippingPlanes`, which the renderer ignores unless this is on.
    renderer.localClippingEnabled = true;
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(
      document.documentElement.classList.contains('dark') ? BG_DARK : BG_LIGHT,
    );

    const camera = new THREE.PerspectiveCamera(
      55,
      (container.clientWidth || 1) / (container.clientHeight || 1),
      0.01,
      10_000,
    );
    camera.position.set(8, 6, 8);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    rendererRef.current = renderer;
    sceneRef.current = scene;
    cameraRef.current = camera;
    controlsRef.current = controls;

    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);

      // Keep the measure-tool label glued to the final segment's midpoint.
      // Reads refs only (no React state) so this costs one projection + a
      // style write per frame, never a re-render.
      const label = measureLabelRef.current;
      if (label) {
        const pts = measurePointsRef.current;
        const p0 = pts[pts.length - 2];
        const p1 = pts[pts.length - 1];
        const cont = containerRef.current;
        if (p0 && p1 && cont) {
          const mid = p0.clone().add(p1).multiplyScalar(0.5);
          mid.project(camera);
          if (mid.z < 1) {
            const x = (mid.x * 0.5 + 0.5) * cont.clientWidth;
            const y = (-mid.y * 0.5 + 0.5) * cont.clientHeight;
            label.style.transform = `translate(${x}px, ${y}px)`;
            label.style.visibility = 'visible';
          } else {
            label.style.visibility = 'hidden';
          }
        } else {
          label.style.visibility = 'hidden';
        }
      }

      // Scale bar: size a "nice" round ruler from the metres-per-pixel at the
      // orbit-pivot depth (2 * tan(fov/2) * dist / viewport height). Written
      // imperatively so the ruler tracks every zoom without a React re-render.
      const bar = scaleBarRef.current;
      const barLabel = scaleBarLabelRef.current;
      const barCont = containerRef.current;
      if (bar && barLabel && barCont && barCont.clientHeight > 0) {
        const dist = camera.position.distanceTo(controls.target);
        const worldHeight = 2 * Math.tan((camera.fov * Math.PI) / 360) * dist;
        const worldPerPixel = worldHeight / barCont.clientHeight;
        const sb = chooseScaleBar(worldPerPixel, Math.min(barCont.clientWidth * 0.25, 160));
        if (sb.pixels > 0) {
          bar.style.width = `${sb.pixels}px`;
          barLabel.textContent = sb.label;
          bar.style.visibility = 'visible';
        } else {
          bar.style.visibility = 'hidden';
        }
      }
    });

    const observer = new ResizeObserver(() => {
      const w = container.clientWidth || 1;
      const h = container.clientHeight || 1;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      const points = pointsRef.current;
      if (points) {
        points.geometry.dispose();
        (points.material as THREE.Material).dispose();
        scene.remove(points);
        pointsRef.current = null;
      }
      // Inspection-tools scene objects. Everything else the tools touch
      // (clipping planes, React state) needs no GPU disposal.
      if (boxHelperRef.current) {
        scene.remove(boxHelperRef.current);
        boxHelperRef.current.dispose();
        boxHelperRef.current = null;
      }
      const disposeMesh = (mesh: THREE.Mesh | THREE.Line) => {
        scene.remove(mesh);
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
      };
      if (measureLineRef.current) {
        disposeMesh(measureLineRef.current);
        measureLineRef.current = null;
      }
      for (const marker of measureMarkersRef.current) disposeMesh(marker);
      measureMarkersRef.current = [];
      measurePointsRef.current = [];
      if (areaLineRef.current) {
        disposeMesh(areaLineRef.current);
        areaLineRef.current = null;
      }
      for (const marker of areaMarkersRef.current) disposeMesh(marker);
      areaMarkersRef.current = [];
      areaPointsRef.current = [];
      if (angleLineRef.current) {
        disposeMesh(angleLineRef.current);
        angleLineRef.current = null;
      }
      for (const marker of angleMarkersRef.current) disposeMesh(marker);
      angleMarkersRef.current = [];
      anglePointsRef.current = [];
      if (inspectMarkerRef.current) {
        disposeMesh(inspectMarkerRef.current);
        inspectMarkerRef.current = null;
      }
      for (const marker of annotationMarkersRef.current.values()) disposeMesh(marker);
      annotationMarkersRef.current.clear();
      for (const helper of groupHelpersRef.current.values()) {
        scene.remove(helper);
        helper.dispose();
      }
      groupHelpersRef.current.clear();
      // forceContextLoss() before dispose() so the browser reclaims the GL
      // context slot immediately; dispose() alone leaks the live context and
      // the ~8-16 context cap is hit after a few mounts (3D view unavailable).
      try {
        renderer.forceContextLoss();
      } catch {
        /* context already lost */
      }
      renderer.dispose();
      if (renderer.domElement.parentElement === container) {
        container.removeChild(renderer.domElement);
      }
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
    };
  }, []);

  // ── Keep the scene background in sync with the app theme / chosen backdrop ─
  useEffect(() => {
    const scene = sceneRef.current;
    if (scene) scene.background = new THREE.Color(effectiveBgHex(bgMode, resolvedTheme));
  }, [resolvedTheme, webglFailed, bgMode]);

  // ── Fetch + parse the OEPC buffer, cancellable ────────────────────────────
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    setPhase('loading');
    setProgressBytes(0);

    fetchScanPoints(scanId, {
      maxPoints,
      signal: controller.signal,
      onProgress: (loaded) => {
        if (!cancelled) setProgressBytes(loaded);
      },
    })
      .then((buffer) => {
        if (cancelled) return;
        const parsed = parseOepc(buffer);
        setCloud(parsed);
        setColorMode((prev) => {
          // Keep a still-valid user choice; otherwise pick the richest channel.
          if (prev === 'rgb' && parsed.rgb) return prev;
          if (prev === 'intensity' && parsed.intensity) return prev;
          if (prev === 'height' || prev === 'single') return prev;
          return parsed.rgb ? 'rgb' : 'height';
        });
        setPhase('ready');
      })
      .catch((err: unknown) => {
        if (cancelled || (err instanceof DOMException && err.name === 'AbortError')) return;
        if (err instanceof ScanPointsError) {
          if (err.status === 409) setErrorKind('processing');
          else if (err.status === 404) setErrorKind('notfound');
          else if (err.status === 501) setErrorKind('reader');
          else if (err.status === 422) setErrorKind('decode');
          else setErrorKind('generic');
          setErrorDetail(err.message);
        } else if (err instanceof OepcParseError) {
          setErrorKind('decode');
          setErrorDetail(err.message);
        } else {
          setErrorKind('generic');
          setErrorDetail(err instanceof Error ? err.message : String(err));
        }
        setPhase('error');
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [scanId, maxPoints, reloadNonce]);

  // ── Rebuild the Points object when a new cloud lands ─────────────────────
  useEffect(() => {
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!scene || !camera || !controls || !cloud) return;

    const previous = pointsRef.current;
    if (previous) {
      previous.geometry.dispose();
      (previous.material as THREE.Material).dispose();
      scene.remove(previous);
      pointsRef.current = null;
    }
    if (cloud.pointCount === 0) return;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(cloud.positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(buildColors(cloud, colorMode), 3));

    // Local-frame bbox (wire bbox is in the world frame; positions are
    // centre-relative), used for sizing, camera fit and the controls target.
    const min = new THREE.Vector3(
      cloud.bboxMin[0] - cloud.center[0],
      cloud.bboxMin[1] - cloud.center[1],
      cloud.bboxMin[2] - cloud.center[2],
    );
    const max = new THREE.Vector3(
      cloud.bboxMax[0] - cloud.center[0],
      cloud.bboxMax[1] - cloud.center[1],
      cloud.bboxMax[2] - cloud.center[2],
    );
    const diagonal = max.clone().sub(min).length() || 1;
    baseSizeRef.current = diagonal / 1000;

    // A soft round sprite (alpha-tested, so no blending / depth-sort cost)
    // turns the default hard squares into feathered discs - the cloud reads
    // like a surface rather than confetti. Falls back to squares if the
    // sprite could not be built.
    const disc = getDiscTexture();
    const material = new THREE.PointsMaterial({
      size: baseSizeRef.current * (sizeFactor / 10),
      vertexColors: true,
      sizeAttenuation: true,
      map: disc ?? undefined,
      alphaTest: disc ? 0.5 : 0,
      transparent: false,
    });

    const points = new THREE.Points(geometry, material);
    // Scans are z-up; THREE is y-up. Rotate the object, not the data.
    points.rotation.x = -Math.PI / 2;
    scene.add(points);
    pointsRef.current = points;

    // Auto-fit: aim at the rotated bbox centre, back off along a 3/4 view.
    const centerLocal = min.clone().add(max).multiplyScalar(0.5);
    const target = centerLocal.clone().applyAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2);
    const distance = Math.max(diagonal * 0.9, 0.5);
    camera.position.set(
      target.x + distance * 0.7,
      target.y + distance * 0.55,
      target.z + distance * 0.7,
    );
    camera.near = Math.max(diagonal / 10_000, 0.001);
    camera.far = Math.max(diagonal * 20, 100);
    camera.updateProjectionMatrix();
    controls.target.copy(target);
    controls.update();
    // The data effect intentionally omits colorMode / sizeFactor: those are
    // applied in-place by the two effects below without a geometry rebuild.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cloud]);

  // ── In-place color recompute on mode change ───────────────────────────────
  useEffect(() => {
    const points = pointsRef.current;
    if (!points || !cloud || cloud.pointCount === 0) return;
    const attr = points.geometry.getAttribute('color') as THREE.BufferAttribute | undefined;
    if (!attr) return;
    (attr.array as Float32Array).set(buildColors(cloud, colorMode, heightRangeOverride));
    attr.needsUpdate = true;
  }, [cloud, colorMode, heightRangeOverride]);

  // ── In-place point-size update ────────────────────────────────────────────
  useEffect(() => {
    const points = pointsRef.current;
    if (!points) return;
    (points.material as THREE.PointsMaterial).size = baseSizeRef.current * (sizeFactor / 10);
  }, [sizeFactor, cloud]);

  // ── On-screen draw decimation: thin the loaded cloud via a stride index so
  //    navigation stays smooth without re-downloading a coarser cloud. Runs
  //    after the data effect (declaration order) so a rebuilt geometry gets
  //    the index re-applied. ────────────────────────────────────────────────
  useEffect(() => {
    const points = pointsRef.current;
    if (!points || !cloud || cloud.pointCount === 0) return;
    const geometry = points.geometry;
    const stride = decimationStride(cloud.pointCount, drawFraction);
    if (stride <= 1) {
      if (geometry.index) geometry.setIndex(null);
      return;
    }
    const n = cloud.pointCount;
    const kept = Math.floor((n - 1) / stride) + 1;
    const idx = new Uint32Array(kept);
    let w = 0;
    for (let i = 0; i < n; i += stride) idx[w++] = i;
    geometry.setIndex(new THREE.BufferAttribute(idx, 1));
  }, [cloud, drawFraction]);

  // ── Depth cue: fade distant points into the background with scene fog for
  //    cheap depth perception on flat, single-color clouds. ─────────────────
  useEffect(() => {
    const scene = sceneRef.current;
    const points = pointsRef.current;
    if (!scene) return;
    const bounds = cloud
      ? deriveCloudBounds({ bboxMin: cloud.bboxMin, bboxMax: cloud.bboxMax, center: cloud.center })
      : null;
    if (depthCue && bounds) {
      // Fade into whatever backdrop is showing so distant points dissolve
      // cleanly rather than into a mismatched colour.
      const bg = effectiveBgHex(bgMode, resolvedTheme);
      scene.fog = new THREE.Fog(bg, bounds.diagonal * 0.35, bounds.diagonal * 2.2);
    } else {
      scene.fog = null;
    }
    // PointsMaterial bakes fog on/off into the compiled shader; force a
    // recompile so toggling takes effect on the already-built material.
    if (points) (points.material as THREE.PointsMaterial).needsUpdate = true;
  }, [depthCue, cloud, resolvedTheme, bgMode]);

  const handleRefit = useCallback(() => {
    // Cheapest reliable re-fit: replay the data effect by cloning the cloud
    // reference (the typed arrays are shared, so this allocates nothing big).
    setCloud((prev) => (prev ? { ...prev } : prev));
  }, []);

  // ══════════════════════════════════════════════════════════════════════
  // Inspection tools. Everything below operates on the already-loaded
  // THREE.Points in-place (clipping planes / raycasts / a canvas capture) -
  // no backend calls, no geometry rebuilds.
  // ══════════════════════════════════════════════════════════════════════

  // Bounds derive from `cloud` alone, so this stays referentially stable
  // across renders that don't touch the cloud (e.g. dragging the size
  // slider), which in turn keeps `activePlaneEqs` below from recomputing
  // needlessly.
  const bounds = useMemo(() => {
    if (!cloud) return null;
    return deriveCloudBounds({ bboxMin: cloud.bboxMin, bboxMax: cloud.bboxMax, center: cloud.center });
  }, [cloud]);

  const heightSpan = bounds ? bounds.zMax - bounds.zMin : 0;
  const sliceStep = heightSpan > 0 ? Math.max(heightSpan / 500, 0.001) : 0.01;
  const legendRange = heightRangeOverride ?? (bounds ? { min: bounds.zMin, max: bounds.zMax } : null);

  /** Default grid cell size for the volume estimate, scaled off the cloud
   *  extent so a big site and a small pile both start with a sane value. */
  const defaultCell = useMemo(() => {
    if (!bounds) return 0.5;
    const c = bounds.diagonal / 100;
    return Math.min(100, Math.max(0.05, Math.round(c * 100) / 100));
  }, [bounds]);

  const effectiveRefY = volumeRefY ?? areaMinY;
  const effectiveCell = volumeCell ?? defaultCell;

  // Every clip-plane equation currently in effect (slice + box, composed as
  // an intersection - a point must clear both to stay visible). Shared by
  // the GPU clipping-planes effect AND the pick tools' raycast filter, so
  // "what you can click" always matches "what you can see".
  const activePlaneEqs = useMemo<PlaneEq[]>(() => {
    if (!bounds) return [];
    const eqs: PlaneEq[] = [];
    if (sliceEnabled) {
      const lo = bounds.zMin + Math.min(sliceMin, sliceMax);
      const hi = bounds.zMin + Math.max(sliceMin, sliceMax);
      eqs.push(...heightSlicePlanes(lo, hi));
    }
    if (clipEnabled && clipBox) {
      eqs.push(...boxPlanes(clipBox));
    }
    // Isolating a group crops the cloud to that group's box, reusing the exact
    // same clip-plane path so "isolate" composes with any active slice / clip.
    if (isolatedGroupId) {
      const iso = groups.find((g) => g.id === isolatedGroupId);
      if (iso) eqs.push(...boxPlanes(iso.box));
    }
    return eqs;
  }, [bounds, sliceEnabled, sliceMin, sliceMax, clipEnabled, clipBox, isolatedGroupId, groups]);

  // Points currently surviving the active slice / clip / isolation, estimated
  // by sampling so it stays instant on multi-million-point clouds. With no
  // crop active this is just the full count. Feeds the toolbar readout so the
  // effect of a slice / clip box / group isolation is visible at a glance.
  const visiblePointCount = useMemo(() => {
    if (!cloud || cloud.pointCount === 0) return 0;
    if (activePlaneEqs.length === 0) return cloud.pointCount;
    const n = cloud.pointCount;
    const step = Math.max(1, Math.ceil(n / 200_000));
    const pos = cloud.positions;
    let seen = 0;
    let inside = 0;
    for (let i = 0; i < n; i += step) {
      const lx = pos[i * 3] ?? 0;
      const ly = pos[i * 3 + 1] ?? 0;
      const lz = pos[i * 3 + 2] ?? 0;
      // local (x, y, z) -> world (x, z, -y).
      seen += 1;
      if (isWithinPlanes({ x: lx, y: lz, z: -ly }, activePlaneEqs)) inside += 1;
    }
    return seen === 0 ? 0 : Math.round((inside / seen) * n);
  }, [cloud, activePlaneEqs]);

  // ── Shared scene-object builders ─────────────────────────────────────────
  const makeMarker = useCallback(
    (p: THREE.Vector3, colorHex: number): THREE.Mesh => {
      const radius = Math.max((bounds?.diagonal ?? 1) / 250, 0.004);
      const geometry = new THREE.SphereGeometry(radius, 12, 8);
      const material = new THREE.MeshBasicMaterial({
        color: colorHex,
        depthTest: false,
        transparent: true,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.copy(p);
      mesh.renderOrder = 998;
      return mesh;
    },
    [bounds],
  );

  const buildLine = useCallback(
    (pts: THREE.Vector3[], colorHex: number, dashed: boolean): THREE.Line => {
      const diagonal = bounds?.diagonal ?? 1;
      const geometry = new THREE.BufferGeometry().setFromPoints(pts);
      const material = dashed
        ? new THREE.LineDashedMaterial({
            color: colorHex,
            dashSize: Math.max(diagonal / 120, 0.01),
            gapSize: Math.max(diagonal / 240, 0.006),
            depthTest: false,
            transparent: true,
          })
        : new THREE.LineBasicMaterial({ color: colorHex, depthTest: false, transparent: true });
      const line = new THREE.Line(geometry, material);
      if (dashed) line.computeLineDistances();
      line.renderOrder = 997;
      return line;
    },
    [bounds],
  );

  // ── Per-tool scene disposers (ref-only, so stable) ───────────────────────
  const disposeMeasureScene = useCallback(() => {
    const scene = sceneRef.current;
    if (measureLineRef.current) {
      scene?.remove(measureLineRef.current);
      measureLineRef.current.geometry.dispose();
      (measureLineRef.current.material as THREE.Material).dispose();
      measureLineRef.current = null;
    }
    for (const marker of measureMarkersRef.current) {
      scene?.remove(marker);
      marker.geometry.dispose();
      (marker.material as THREE.Material).dispose();
    }
    measureMarkersRef.current = [];
  }, []);

  const disposeAreaScene = useCallback(() => {
    const scene = sceneRef.current;
    if (areaLineRef.current) {
      scene?.remove(areaLineRef.current);
      areaLineRef.current.geometry.dispose();
      (areaLineRef.current.material as THREE.Material).dispose();
      areaLineRef.current = null;
    }
    for (const marker of areaMarkersRef.current) {
      scene?.remove(marker);
      marker.geometry.dispose();
      (marker.material as THREE.Material).dispose();
    }
    areaMarkersRef.current = [];
  }, []);

  const disposeAngleScene = useCallback(() => {
    const scene = sceneRef.current;
    if (angleLineRef.current) {
      scene?.remove(angleLineRef.current);
      angleLineRef.current.geometry.dispose();
      (angleLineRef.current.material as THREE.Material).dispose();
      angleLineRef.current = null;
    }
    for (const marker of angleMarkersRef.current) {
      scene?.remove(marker);
      marker.geometry.dispose();
      (marker.material as THREE.Material).dispose();
    }
    angleMarkersRef.current = [];
  }, []);

  const disposeInspectMarker = useCallback(() => {
    const scene = sceneRef.current;
    if (inspectMarkerRef.current) {
      scene?.remove(inspectMarkerRef.current);
      inspectMarkerRef.current.geometry.dispose();
      (inspectMarkerRef.current.material as THREE.Material).dispose();
      inspectMarkerRef.current = null;
    }
  }, []);

  // ── Rebuild a tool's line + markers from its ref-held vertices ───────────
  const redrawPath = useCallback(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    disposeMeasureScene();
    const pts = measurePointsRef.current;
    for (const p of pts) {
      const m = makeMarker(p, MEASURE_COLOR);
      scene.add(m);
      measureMarkersRef.current.push(m);
    }
    if (pts.length >= 2) {
      const line = buildLine(pts, MEASURE_COLOR, true);
      scene.add(line);
      measureLineRef.current = line;
    }
  }, [disposeMeasureScene, makeMarker, buildLine]);

  const redrawArea = useCallback(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    disposeAreaScene();
    const pts = areaPointsRef.current;
    for (const p of pts) {
      const m = makeMarker(p, AREA_COLOR);
      scene.add(m);
      areaMarkersRef.current.push(m);
    }
    if (pts.length >= 2) {
      // Close the loop once it is a real polygon so it reads as a footprint.
      const linePts = pts.length >= 3 ? [...pts, pts[0] as THREE.Vector3] : pts;
      const line = buildLine(linePts, AREA_COLOR, false);
      scene.add(line);
      areaLineRef.current = line;
    }
  }, [disposeAreaScene, makeMarker, buildLine]);

  const redrawAngle = useCallback(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    disposeAngleScene();
    const pts = anglePointsRef.current;
    for (const p of pts) {
      const m = makeMarker(p, ANGLE_COLOR);
      scene.add(m);
      angleMarkersRef.current.push(m);
    }
    // An open two-leg polyline (a->b->c) - the corner being measured, not a
    // closed shape.
    if (pts.length >= 2) {
      const line = buildLine(pts, ANGLE_COLOR, false);
      scene.add(line);
      angleLineRef.current = line;
    }
  }, [disposeAngleScene, makeMarker, buildLine]);

  // ── Shared raycast: the visible cloud point under a click, or null ───────
  const raycastVisiblePoint = useCallback(
    (ev: PointerEvent): THREE.Vector3 | null => {
      const container = containerRef.current;
      const camera = cameraRef.current;
      const points = pointsRef.current;
      if (!container || !camera || !points) return null;

      const rect = container.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return null;
      const ndc = new THREE.Vector2(
        ((ev.clientX - rect.left) / rect.width) * 2 - 1,
        -((ev.clientY - rect.top) / rect.height) * 2 + 1,
      );

      const material = points.material as THREE.PointsMaterial;
      const raycaster = new THREE.Raycaster();
      // Sized off the current rendered point size so picking stays easy at
      // any point-size / density setting.
      raycaster.params.Points = { threshold: Math.max(material.size * 1.5, 1e-5) };
      raycaster.setFromCamera(ndc, camera);
      const hits = raycaster.intersectObject(points);
      // THREE.Raycaster has no notion of GPU clipping planes, so a hit here
      // can land on a point the slice/clip box currently hides. Skip those -
      // otherwise you could pick a point that is not visibly there.
      const visible = hits.find(
        (h) => activePlaneEqs.length === 0 || isWithinPlanes(h.point, activePlaneEqs),
      );
      return visible ? visible.point.clone() : null;
    },
    [activePlaneEqs],
  );

  // ── Dispatch a pick to the active tool ───────────────────────────────────
  const handlePickClick = useCallback(
    (ev: PointerEvent) => {
      const scene = sceneRef.current;
      if (!scene || !cloud) return;
      const p = raycastVisiblePoint(ev);
      if (!p) return;

      if (pickMode === 'measure') {
        measurePointsRef.current.push(p);
        redrawPath();
        setPathMetrics(computePolylineMetrics(measurePointsRef.current));
      } else if (pickMode === 'angle') {
        const apts = anglePointsRef.current;
        // Three vertices define one corner; a fourth click starts a fresh pick.
        if (apts.length >= 3) apts.length = 0;
        apts.push(p);
        redrawAngle();
        setAngleVertexCount(apts.length);
        setAngleValue(
          apts.length === 3 ? angleAtVertex(apts[0] as Vec3, apts[1] as Vec3, apts[2] as Vec3) : null,
        );
      } else if (pickMode === 'area') {
        areaPointsRef.current.push(p);
        redrawArea();
        const pts = areaPointsRef.current;
        setAreaVertexCount(pts.length);
        setAreaPlanArea(polygonAreaXZ(pts));
        setAreaMinY(Math.min(...pts.map((v) => v.y)));
        // Polygon changed - the last volume estimate no longer applies.
        setVolumeResult(null);
      } else if (pickMode === 'inspect') {
        disposeInspectMarker();
        const m = makeMarker(p, INSPECT_COLOR);
        scene.add(m);
        inspectMarkerRef.current = m;
        setInspectResult({
          world: { x: p.x, y: p.y, z: p.z },
          scan: worldToScanCoords(p, cloud.center),
        });
      } else if (pickMode === 'annotate') {
        const id = `${Date.now()}-${Math.round(Math.random() * 1e6)}`;
        setAnnotations((prev) => [
          ...prev,
          { id, world: { x: p.x, y: p.y, z: p.z }, scan: worldToScanCoords(p, cloud.center), note: '' },
        ]);
      }
    },
    [
      pickMode,
      cloud,
      raycastVisiblePoint,
      redrawPath,
      redrawAngle,
      redrawArea,
      disposeInspectMarker,
      makeMarker,
    ],
  );

  /** DOM pointer listeners live outside React's render cycle, so they call
   *  through this ref rather than closing over a stale `handlePickClick`. */
  const pickClickRef = useRef(handlePickClick);
  useEffect(() => {
    pickClickRef.current = handlePickClick;
  });

  // ── Reset tool state when genuinely new/refetched data lands. Skips the
  //    handleRefit `{...prev}` clone (same `positions` buffer) so re-fitting
  //    the view never wipes an in-progress slice / measurement. ─────────────
  useEffect(() => {
    if (!cloud || !bounds) return;
    if (lastPositionsRef.current === cloud.positions) return;
    lastPositionsRef.current = cloud.positions;

    setSliceEnabled(false);
    setSliceMin(0);
    setSliceMax(bounds.zMax - bounds.zMin);
    setClipEnabled(false);
    setClipBox(null);
    setHeightRangeOverride(null);
    setLegendPinned(false);

    setPickMode('none');
    disposeMeasureScene();
    measurePointsRef.current = [];
    setPathMetrics(null);
    disposeAreaScene();
    areaPointsRef.current = [];
    setAreaVertexCount(0);
    setAreaPlanArea(0);
    setAreaMinY(0);
    setVolumeRefY(null);
    setVolumeCell(null);
    setVolumeResult(null);
    disposeAngleScene();
    anglePointsRef.current = [];
    setAngleVertexCount(0);
    setAngleValue(null);
    disposeInspectMarker();
    setInspectResult(null);
    setAnnotations([]);
    setGroups([]);
    setGroupsEnabled(false);
    setIsolatedGroupId(null);
    groupCounterRef.current = 0;
  }, [cloud, bounds, disposeMeasureScene, disposeAreaScene, disposeAngleScene, disposeInspectMarker]);

  // ── Sync annotation pin markers to the annotations state ─────────────────
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const map = annotationMarkersRef.current;
    const liveIds = new Set(annotations.map((a) => a.id));
    for (const [id, mesh] of map) {
      if (!liveIds.has(id)) {
        scene.remove(mesh);
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
        map.delete(id);
      }
    }
    for (const a of annotations) {
      if (!map.has(a.id)) {
        const m = makeMarker(new THREE.Vector3(a.world.x, a.world.y, a.world.z), ANNOTATION_COLOR);
        scene.add(m);
        map.set(a.id, m);
      }
    }
  }, [annotations, makeMarker]);

  // ── Sync group box wireframes to the groups state ────────────────────────
  // One colored Box3Helper per captured group, so every group is visible in
  // the scene at once. Reconciled like the annotation markers: drop helpers
  // for removed groups, add helpers for new ones, and re-point every live
  // helper at its (possibly edited) box + color. The isolated group is drawn
  // a touch bolder so it stands out while its points are cropped in.
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const map = groupHelpersRef.current;
    const liveIds = new Set(groups.map((g) => g.id));
    for (const [id, helper] of map) {
      if (!liveIds.has(id)) {
        scene.remove(helper);
        helper.dispose();
        map.delete(id);
      }
    }
    for (const g of groups) {
      let helper = map.get(g.id);
      if (!helper) {
        helper = new THREE.Box3Helper(new THREE.Box3(), new THREE.Color(g.color));
        const material = helper.material as THREE.LineBasicMaterial;
        material.transparent = true;
        material.depthTest = false;
        helper.renderOrder = 995;
        scene.add(helper);
        map.set(g.id, helper);
      }
      helper.box.min.set(g.box.min.x, g.box.min.y, g.box.min.z);
      helper.box.max.set(g.box.max.x, g.box.max.y, g.box.max.z);
      const material = helper.material as THREE.LineBasicMaterial;
      material.color.set(g.color);
      material.opacity = isolatedGroupId === g.id ? 1 : 0.7;
    }
  }, [groups, isolatedGroupId]);

  // ── Default the clip box to the full cloud bounds the first time it's
  //    enabled; later toggles keep whatever region the user set. ───────────
  useEffect(() => {
    if (clipEnabled && !clipBox && bounds) {
      setClipBox({ min: bounds.worldMin, max: bounds.worldMax });
    }
  }, [clipEnabled, clipBox, bounds]);

  // ── Apply the combined clip planes to the point material. Plane math is
  //    a handful of tiny objects, not a per-point loop - cheap even while a
  //    slider is being dragged. ─────────────────────────────────────────────
  useEffect(() => {
    const points = pointsRef.current;
    if (!points) return;
    const material = points.material as THREE.PointsMaterial;
    const planes = activePlaneEqs.map(
      (eq) => new THREE.Plane(new THREE.Vector3(eq.normal.x, eq.normal.y, eq.normal.z), eq.constant),
    );
    const previousCount = material.clippingPlanes?.length ?? 0;
    material.clippingPlanes = planes;
    // clippingPlanes count is baked into the compiled shader in some
    // three.js versions - force a recompile whenever it changes so a plane
    // being added/removed (not just moved) always takes effect.
    if (previousCount !== planes.length) material.needsUpdate = true;
  }, [cloud, activePlaneEqs]);

  // ── Clip-box wireframe: lazily built, then just re-pointed at the new
  //    Box3 extents (Box3Helper redraws itself from `.box` every frame). ───
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    if (!clipEnabled || !clipBox) {
      if (boxHelperRef.current) boxHelperRef.current.visible = false;
      return;
    }
    let helper = boxHelperRef.current;
    if (!helper) {
      helper = new THREE.Box3Helper(new THREE.Box3(), CLIP_BOX_COLOR);
      const material = helper.material as THREE.LineBasicMaterial;
      material.transparent = true;
      material.depthTest = false;
      material.opacity = 0.9;
      helper.renderOrder = 999;
      scene.add(helper);
      boxHelperRef.current = helper;
    }
    helper.box.min.set(clipBox.min.x, clipBox.min.y, clipBox.min.z);
    helper.box.max.set(clipBox.max.x, clipBox.max.y, clipBox.max.z);
    helper.visible = true;
  }, [clipEnabled, clipBox]);

  // ── Ground grid + orientation axes: a spatial reference under the cloud so
  //    scale and "which way is up" read at a glance. Rebuilt when the bounds
  //    change; toggled and theme-tinted in place. GridHelper lies in the XZ
  //    plane, which is the ground here (Y is up after the -90 deg rotation). ─
  useEffect(() => {
    const scene = sceneRef.current;
    const disposeFrame = () => {
      if (gridHelperRef.current) {
        scene?.remove(gridHelperRef.current);
        gridHelperRef.current.geometry.dispose();
        (gridHelperRef.current.material as THREE.Material).dispose();
        gridHelperRef.current = null;
      }
      if (axesHelperRef.current) {
        scene?.remove(axesHelperRef.current);
        axesHelperRef.current.geometry.dispose();
        (axesHelperRef.current.material as THREE.Material).dispose();
        axesHelperRef.current = null;
      }
    };
    if (!scene) return undefined;
    disposeFrame();
    if (!showGrid || !bounds) return disposeFrame;

    const wx = bounds.worldMax.x - bounds.worldMin.x;
    const wz = bounds.worldMax.z - bounds.worldMin.z;
    const span = Math.max(wx, wz, 1);
    const dark =
      resolvedTheme === 'dark' || bgMode === 'dark' || bgMode === 'black' || bgMode === 'slate';
    const gridColor = dark ? 0x475569 : 0xcbd5e1;
    const centerColor = dark ? 0x64748b : 0x94a3b8;
    const grid = new THREE.GridHelper(span * 1.3, 20, centerColor, gridColor);
    // Sit the grid just under the lowest point, centred on the footprint.
    grid.position.set(
      bounds.worldCenter.x,
      bounds.worldMin.y - Math.max(bounds.diagonal * 0.002, 1e-4),
      bounds.worldCenter.z,
    );
    const gridMat = grid.material as THREE.Material;
    gridMat.transparent = true;
    gridMat.opacity = 0.55;
    gridMat.depthWrite = false;
    scene.add(grid);
    gridHelperRef.current = grid;

    // A small triad at the ground corner shows the axis directions (X/Z ground,
    // Y up), always drawn on top so it stays legible against the cloud.
    const axes = new THREE.AxesHelper(Math.max(span * 0.12, 0.2));
    axes.position.set(bounds.worldMin.x, bounds.worldMin.y, bounds.worldMin.z);
    (axes.material as THREE.Material).depthTest = false;
    axes.renderOrder = 996;
    scene.add(axes);
    axesHelperRef.current = axes;

    return disposeFrame;
  }, [bounds, showGrid, resolvedTheme, bgMode]);

  // ── Pick-tool pointer listeners: a plain click (down+up within a few px,
  //    no drag) picks a point; a real orbit-drag is ignored so picking never
  //    fights OrbitControls, which stays enabled throughout. ───────────────
  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer || pickMode === 'none') return undefined;
    const dom = renderer.domElement;
    let downX = 0;
    let downY = 0;
    let dragging = false;

    const onPointerDown = (ev: PointerEvent) => {
      if (ev.button !== 0) return;
      downX = ev.clientX;
      downY = ev.clientY;
      dragging = false;
    };
    const onPointerMove = (ev: PointerEvent) => {
      if ((ev.buttons & 1) === 0) return;
      if (Math.hypot(ev.clientX - downX, ev.clientY - downY) > 5) dragging = true;
    };
    const onPointerUp = (ev: PointerEvent) => {
      if (ev.button !== 0 || dragging) return;
      pickClickRef.current(ev);
    };

    dom.addEventListener('pointerdown', onPointerDown);
    dom.addEventListener('pointermove', onPointerMove);
    dom.addEventListener('pointerup', onPointerUp);
    return () => {
      dom.removeEventListener('pointerdown', onPointerDown);
      dom.removeEventListener('pointermove', onPointerMove);
      dom.removeEventListener('pointerup', onPointerUp);
    };
  }, [pickMode]);

  /** Switch the active pick tool, toggling off if it is already selected. */
  const togglePick = useCallback((mode: Exclude<PickMode, 'none'>) => {
    setPickMode((prev) => (prev === mode ? 'none' : mode));
  }, []);

  const applyPreset = useCallback(
    (view: PresetView) => {
      const camera = cameraRef.current;
      const controls = controlsRef.current;
      if (!camera || !controls || !bounds) return;
      const { worldCenter, diagonal } = bounds;
      const distance = Math.max(diagonal * 0.9, 0.5);
      const off = presetViewOffset(view, distance);
      camera.position.set(worldCenter.x + off.x, worldCenter.y + off.y, worldCenter.z + off.z);
      camera.near = Math.max(diagonal / 10_000, 0.001);
      camera.far = Math.max(diagonal * 20, 100);
      camera.updateProjectionMatrix();
      controls.target.set(worldCenter.x, worldCenter.y, worldCenter.z);
      controls.update();
    },
    [bounds],
  );

  // ── Measure-path handlers ────────────────────────────────────────────────
  const undoLastPathPoint = useCallback(() => {
    measurePointsRef.current.pop();
    redrawPath();
    const pts = measurePointsRef.current;
    setPathMetrics(pts.length >= 1 ? computePolylineMetrics(pts) : null);
  }, [redrawPath]);

  const clearPath = useCallback(() => {
    disposeMeasureScene();
    measurePointsRef.current = [];
    setPathMetrics(null);
  }, [disposeMeasureScene]);

  // ── Area / volume handlers ───────────────────────────────────────────────
  const clearArea = useCallback(() => {
    disposeAreaScene();
    areaPointsRef.current = [];
    setAreaVertexCount(0);
    setAreaPlanArea(0);
    setAreaMinY(0);
    setVolumeResult(null);
  }, [disposeAreaScene]);

  const clearAngle = useCallback(() => {
    disposeAngleScene();
    anglePointsRef.current = [];
    setAngleVertexCount(0);
    setAngleValue(null);
  }, [disposeAngleScene]);

  const computeVolume = useCallback(() => {
    const poly = areaPointsRef.current;
    if (!cloud || poly.length < 3) return;
    // Build decimated world-space samples: local (lx, ly, lz) -> world
    // (lx, lz, -ly), matching the viewer's -90 deg X rotation.
    const n = cloud.pointCount;
    const step = Math.max(1, Math.ceil(n / VOLUME_SAMPLE_BUDGET));
    const pos = cloud.positions;
    const samples: Vec3[] = [];
    for (let i = 0; i < n; i += step) {
      const lx = pos[i * 3] ?? 0;
      const ly = pos[i * 3 + 1] ?? 0;
      const lz = pos[i * 3 + 2] ?? 0;
      samples.push({ x: lx, y: lz, z: -ly });
    }
    const polyVecs: Vec3[] = poly.map((v) => ({ x: v.x, y: v.y, z: v.z }));
    setVolumeResult(estimateVolumeVsPlane(samples, polyVecs, effectiveRefY, effectiveCell));
  }, [cloud, effectiveRefY, effectiveCell]);

  // ── Inspect handlers ─────────────────────────────────────────────────────
  const clearInspect = useCallback(() => {
    disposeInspectMarker();
    setInspectResult(null);
  }, [disposeInspectMarker]);

  // ── Annotation handlers ──────────────────────────────────────────────────
  const updateAnnotationNote = useCallback((id: string, note: string) => {
    setAnnotations((prev) => prev.map((a) => (a.id === id ? { ...a, note } : a)));
  }, []);

  const removeAnnotation = useCallback((id: string) => {
    setAnnotations((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const clearAnnotations = useCallback(() => {
    setAnnotations([]);
  }, []);

  // ── Groups handlers ──────────────────────────────────────────────────────
  // Opening the Groups tool turns on the adjustable clip box so the user has a
  // region to size and capture; closing it leaves the box as-is (they may be
  // using it as its own tool).
  const toggleGroups = useCallback(() => {
    setGroupsEnabled((prev) => {
      const next = !prev;
      if (next) setClipEnabled(true);
      return next;
    });
  }, []);

  /** Snapshot the current clip-box bounds into a new named, colored group,
   *  counting the cloud points inside it. No-op when nothing is loaded or no
   *  box is defined yet. */
  const captureGroup = useCallback(() => {
    if (!cloud || !clipBox) return;
    const box: BoxExtent = {
      min: { ...clipBox.min },
      max: { ...clipBox.max },
    };
    const pointCount = countPointsInBox(cloud, box);
    groupCounterRef.current += 1;
    const n = groupCounterRef.current;
    const color = GROUP_COLORS[(n - 1) % GROUP_COLORS.length] as string;
    const id = `${Date.now()}-${Math.round(Math.random() * 1e6)}`;
    setGroups((prev) => [
      ...prev,
      {
        id,
        name: t('pointcloud.group_default_name', { defaultValue: 'Group {{n}}', n }),
        color,
        box,
        pointCount,
      },
    ]);
  }, [cloud, clipBox, t]);

  const renameGroup = useCallback((id: string, name: string) => {
    setGroups((prev) => prev.map((g) => (g.id === id ? { ...g, name } : g)));
  }, []);

  const removeGroup = useCallback((id: string) => {
    setGroups((prev) => prev.filter((g) => g.id !== id));
    setIsolatedGroupId((cur) => (cur === id ? null : cur));
  }, []);

  const toggleIsolateGroup = useCallback((id: string) => {
    setIsolatedGroupId((cur) => (cur === id ? null : id));
  }, []);

  const clearGroups = useCallback(() => {
    setGroups([]);
    setIsolatedGroupId(null);
  }, []);

  // ── Quantity hand-off to the estimate (BOQ) ──────────────────────────────
  /** Copy a tab-separated quantity summary to the clipboard - the graceful
   *  fallback when there is no active project to add a BOQ position to. */
  const copyQuantitySummary = useCallback(
    async (description: string, unit: string, quantity: number) => {
      const summary = `${description}\t${quantity} ${unit}`;
      try {
        await navigator.clipboard.writeText(summary);
        addToast({
          type: 'success',
          title: t('pointcloud.qty_copied_title', { defaultValue: 'Quantity copied' }),
          message: summary,
        });
      } catch {
        addToast({
          type: 'error',
          title: t('pointcloud.qty_copy_failed_title', { defaultValue: 'Could not copy' }),
          message: t('pointcloud.qty_copy_failed_msg', {
            defaultValue: 'Clipboard access was blocked by the browser.',
          }),
        });
      }
    },
    [addToast, t],
  );

  /** Add a measured quantity to the active project's BOQ as a new position,
   *  reusing the same resolve-or-create-BOQ + addPosition path as DWG Takeoff
   *  (boqApi). Falls back to the clipboard when no project is active. */
  const addQuantityToBoq = useCallback(
    async (description: string, unit: 'm2' | 'm3', quantity: number) => {
      const roundedQty = Math.round(quantity * 1000) / 1000;
      if (!Number.isFinite(roundedQty) || roundedQty <= 0) {
        addToast({
          type: 'error',
          title: t('pointcloud.boq_nothing_title', { defaultValue: 'Nothing to add' }),
          message: t('pointcloud.boq_nothing_msg', {
            defaultValue: 'Measure or capture a non-zero quantity first.',
          }),
        });
        return;
      }
      if (!activeProjectId) {
        // No project context - degrade to the clipboard instead of guessing.
        await copyQuantitySummary(description, unit, roundedQty);
        return;
      }
      setBoqSending(true);
      try {
        // Resolve a destination BOQ without a picker: first existing, else a
        // fresh "Point cloud takeoff" BOQ for this project.
        const boqs = await boqApi.list(activeProjectId);
        let boqId = boqs[0]?.id ?? '';
        if (!boqId) {
          const created = await boqApi.create({
            project_id: activeProjectId,
            name: t('pointcloud.boq_default_name', { defaultValue: 'Point cloud takeoff' }),
          });
          boqId = created.id;
        }
        const boqData = await boqApi.get(boqId);
        const positions = boqData.positions || [];
        // Auto-number a PC.### ordinal so successive adds do not collide.
        const pcNums = positions
          .map((p) => {
            const m = /^PC\.(\d+)$/.exec(p.ordinal || '');
            return m ? parseInt(m[1] as string, 10) : 0;
          })
          .filter((v) => v > 0);
        const nextNum = (pcNums.length ? Math.max(...pcNums) : 0) + 1;
        const ordinal = `PC.${String(nextNum).padStart(3, '0')}`;
        const newPos = await boqApi.addPosition({
          boq_id: boqId,
          ordinal,
          description,
          unit,
          quantity: roundedQty,
          unit_rate: 0,
        });
        try {
          await boqApi.updatePosition(newPos.id, {
            metadata: {
              source: 'pointcloud',
              source_scan_id: scanId,
              pointcloud_quantity: roundedQty,
              pointcloud_unit: unit,
            },
          });
        } catch {
          /* metadata is non-critical */
        }
        addToast({
          type: 'success',
          title: t('pointcloud.boq_added_title', { defaultValue: 'Added to BOQ' }),
          message: `${boqData.name || 'BOQ'} · ${ordinal} - ${roundedQty} ${unit}`,
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        addToast({
          type: 'error',
          title: t('pointcloud.boq_failed_title', { defaultValue: 'Could not add to BOQ' }),
          message: msg,
        });
      } finally {
        setBoqSending(false);
      }
    },
    [activeProjectId, scanId, addToast, copyQuantitySummary, t],
  );

  const handleClipReset = useCallback(() => {
    if (!bounds) return;
    setClipBox({ min: bounds.worldMin, max: bounds.worldMax });
  }, [bounds]);

  const handleClipScale = useCallback(
    (factor: number) => {
      setClipBox((prev) => {
        if (!prev || !bounds) return prev;
        const minHalfExtent = Math.max(bounds.diagonal * 0.01, 1e-4);
        return scaleClipBox(prev, factor, { min: bounds.worldMin, max: bounds.worldMax }, minHalfExtent);
      });
    },
    [bounds],
  );

  // ── Fullscreen: mirror the browser state so the button/layout stay correct
  //    even when the user leaves fullscreen with Esc. ────────────────────────
  useEffect(() => {
    const onChange = () => setIsFullscreen(document.fullscreenElement === containerRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const toggleFullscreen = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen?.();
    } else {
      void container.requestFullscreen?.();
    }
  }, []);

  const handleSnapshot = useCallback(() => {
    const renderer = rendererRef.current;
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    if (!renderer || !scene || !camera) return;
    // Render synchronously right before capture instead of keeping
    // `preserveDrawingBuffer` on for the whole session (that flag has a real
    // perf cost on some GPUs); a render-then-read in the same tick is
    // guaranteed to see the fresh frame before the browser presents/clears it.
    renderer.render(scene, camera);
    const url = renderer.domElement.toDataURL('image/png');
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const link = document.createElement('a');
    link.href = url;
    link.download = `pointcloud-${slugifyForFilename(scanLabel || scanId)}-${stamp}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [scanLabel, scanId]);

  /** Trigger a client-side CSV download with a scan-tagged filename. */
  const downloadCsv = useCallback(
    (suffix: string, csv: string) => {
      const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `pointcloud-${slugifyForFilename(scanLabel || scanId)}-${suffix}-${stamp}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    },
    [scanLabel, scanId],
  );

  const exportPath = useCallback(() => {
    const pts = measurePointsRef.current;
    if (pts.length < 2 || !cloud) return;
    downloadCsv('path', polylineToCsv(pts, cloud.center));
  }, [cloud, downloadCsv]);

  const exportArea = useCallback(() => {
    const pts = areaPointsRef.current;
    if (pts.length < 3 || !cloud) return;
    downloadCsv('polygon', polylineToCsv(pts, cloud.center));
  }, [cloud, downloadCsv]);

  const exportAnnotations = useCallback(() => {
    if (annotations.length === 0) return;
    const rows = annotations.map((a, i) => ({
      index: i + 1,
      note: a.note,
      scan: a.scan,
      world: a.world,
    }));
    downloadCsv('annotations', annotationsToCsv(rows));
  }, [annotations, downloadCsv]);

  const handleToggleLegendPin = useCallback(() => {
    setLegendPinned((prev) => {
      const next = !prev;
      setHeightRangeOverride(next && bounds ? { min: bounds.zMin, max: bounds.zMax } : null);
      return next;
    });
  }, [bounds]);

  const colorOptions = useMemo(
    () => [
      {
        value: 'rgb' as const,
        label: t('pointcloud.color_rgb', { defaultValue: 'True color (RGB)' }),
        disabled: !cloud?.rgb,
      },
      {
        value: 'height' as const,
        label: t('pointcloud.color_height', { defaultValue: 'Height ramp' }),
        disabled: false,
      },
      {
        value: 'intensity' as const,
        label: t('pointcloud.color_intensity', { defaultValue: 'Intensity' }),
        disabled: !cloud?.intensity,
      },
      {
        value: 'single' as const,
        label: t('pointcloud.color_single', { defaultValue: 'Single color' }),
        disabled: false,
      },
    ],
    [cloud, t],
  );

  const presetButtons = useMemo(
    () =>
      [
        { view: 'top' as const, label: t('pointcloud.view_top', { defaultValue: 'Top' }) },
        { view: 'front' as const, label: t('pointcloud.view_front', { defaultValue: 'Front' }) },
        { view: 'side' as const, label: t('pointcloud.view_side', { defaultValue: 'Side' }) },
        { view: 'iso' as const, label: t('pointcloud.view_iso', { defaultValue: 'Iso' }) },
      ] as const,
    [t],
  );

  /** Overall cloud footprint W x D x H in metres, for the header readout. */
  const dimensionsLabel = useMemo(() => {
    if (!bounds) return null;
    const w = bounds.worldMax.x - bounds.worldMin.x;
    const d = bounds.worldMax.z - bounds.worldMin.z;
    const h = bounds.worldMax.y - bounds.worldMin.y;
    return `${fmtFixed(w, 1)} × ${fmtFixed(d, 1)} × ${fmtFixed(h, 1)} m`;
  }, [bounds]);

  const bgModeOptions = useMemo(
    () => [
      { value: 'theme' as const, label: t('pointcloud.bg_theme', { defaultValue: 'Theme' }) },
      { value: 'light' as const, label: t('pointcloud.bg_light', { defaultValue: 'Light' }) },
      { value: 'slate' as const, label: t('pointcloud.bg_slate', { defaultValue: 'Slate' }) },
      { value: 'dark' as const, label: t('pointcloud.bg_dark', { defaultValue: 'Dark' }) },
      { value: 'black' as const, label: t('pointcloud.bg_black', { defaultValue: 'Black' }) },
    ],
    [t],
  );

  const errorTitle = useMemo(() => {
    switch (errorKind) {
      case 'processing':
        return t('pointcloud.viewer_processing_title', { defaultValue: 'Scan is still processing' });
      case 'notfound':
        return t('pointcloud.viewer_notfound_title', { defaultValue: 'Scan not available' });
      case 'reader':
        return t('pointcloud.viewer_reader_title', { defaultValue: 'Point-cloud reader not installed' });
      case 'decode':
        return t('pointcloud.viewer_decode_title', { defaultValue: 'Could not decode this scan' });
      default:
        return t('pointcloud.viewer_error_title', { defaultValue: 'Could not load points' });
    }
  }, [errorKind, t]);

  const errorDescription = useMemo(() => {
    switch (errorKind) {
      case 'processing':
        return t('pointcloud.viewer_processing_desc', {
          defaultValue:
            'The upload has not finished yet. The viewer opens as soon as the scan reaches the uploaded state.',
        });
      case 'notfound':
        return t('pointcloud.viewer_notfound_desc', {
          defaultValue: 'The scan was removed or you no longer have access to it.',
        });
      case 'reader':
        return t('pointcloud.viewer_reader_desc', {
          defaultValue:
            "This scan's format needs an optional server-side reader that is not installed. LAS, LAZ and COPC work out of the box; E57 needs the 'pointcloud' extra installed on the server.",
        });
      case 'decode':
        return t('pointcloud.viewer_decode_desc', {
          defaultValue: 'The file could not be decoded into points. Re-export the scan and upload again.',
        });
      default:
        return errorDetail;
    }
  }, [errorKind, errorDetail, t]);

  const toolsDisabled = phase !== 'ready' || !cloud || cloud.pointCount === 0;

  // ── Keyboard shortcuts ───────────────────────────────────────────────────
  // Single-key accelerators for the toolbar, surfaced in each button's
  // tooltip. Ignored while typing in a field or with a modifier held, and
  // only active once a cloud is loaded. Activating a tool also reveals the
  // inspector panel so its readout is visible.
  useEffect(() => {
    if (toolsDisabled) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
      const reveal = () => setPanelOpen(true);
      switch (e.key.toLowerCase()) {
        case 'f': handleRefit(); break;
        case 'g': setShowGrid((v) => !v); break;
        case 'd': setDepthCue((v) => !v); break;
        case 's': handleSnapshot(); break;
        case 'x': setSliceEnabled((v) => !v); reveal(); break;
        case 'c': setClipEnabled((v) => !v); reveal(); break;
        case 'b': toggleGroups(); reveal(); break;
        case 'm': togglePick('measure'); reveal(); break;
        case 'n': togglePick('angle'); reveal(); break;
        case 'p': togglePick('area'); reveal(); break;
        case 'i': togglePick('inspect'); reveal(); break;
        case 'k': togglePick('annotate'); reveal(); break;
        case 'escape': setPickMode('none'); break;
        default: return;
      }
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toolsDisabled, handleRefit, handleSnapshot, toggleGroups, togglePick]);

  return (
    <div className="space-y-3">
      <div className="flex flex-col-reverse gap-3 lg:flex-row-reverse lg:items-start">
        {/* ── Inspector: display settings · active tool · layers/groups ──── */}
        {!toolsDisabled && panelOpen && (
          <aside
            className="flex max-h-[560px] w-full shrink-0 flex-col overflow-hidden rounded-xl border border-border-light bg-surface-secondary/40 lg:w-[320px]"
            data-testid="pointcloud-inspector"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-border-light px-3 py-2">
              <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('pointcloud.inspector_title', { defaultValue: 'Inspector' })}
              </span>
              <button
                type="button"
                onClick={() => setPanelOpen(false)}
                aria-label={t('pointcloud.panel_hide', { defaultValue: 'Hide panel' })}
                title={t('pointcloud.panel_hide', { defaultValue: 'Hide panel' })}
                className="inline-flex h-6 w-6 items-center justify-center rounded-md text-content-tertiary transition-colors hover:bg-surface-tertiary hover:text-content-primary"
                data-testid="pointcloud-panel-close"
              >
                <PanelRightClose size={15} />
              </button>
            </div>
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
              {/* ── Display settings ─────────────────────────────────────── */}
              <section className="space-y-3" data-testid="pointcloud-display-section">
                <h4 className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                  <Palette size={12} />
                  {t('pointcloud.group_display', { defaultValue: 'Display' })}
                </h4>
                <div className="flex flex-col gap-3">
          <div>
            <label
              htmlFor="pointcloud-color-mode"
            className="mb-1 block text-2xs font-semibold uppercase tracking-wider text-content-tertiary"
          >
            {t('pointcloud.viewer_color_mode', { defaultValue: 'Color by' })}
          </label>
          <select
            id="pointcloud-color-mode"
            className="rounded-lg border border-border-light bg-surface-secondary px-2.5 py-1.5 text-sm text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            value={colorMode}
            onChange={(e) => setColorMode(e.target.value as ColorMode)}
            disabled={phase !== 'ready'}
            data-testid="pointcloud-color-mode"
          >
            {colorOptions.map((o) => (
              <option key={o.value} value={o.value} disabled={o.disabled}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="pointcloud-density"
            className="mb-1 block text-2xs font-semibold uppercase tracking-wider text-content-tertiary"
          >
            {t('pointcloud.viewer_density', { defaultValue: 'Density' })}
          </label>
          <select
            id="pointcloud-density"
            className="rounded-lg border border-border-light bg-surface-secondary px-2.5 py-1.5 text-sm text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            value={maxPoints}
            onChange={(e) => setMaxPoints(Number(e.target.value))}
            disabled={phase !== 'ready'}
            data-testid="pointcloud-density"
          >
            {DENSITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {t(o.labelKey, { defaultValue: o.fallback })}
              </option>
            ))}
          </select>
        </div>

        <div className="min-w-[150px]">
          <label
            htmlFor="pointcloud-point-size"
            className="mb-1 block text-2xs font-semibold uppercase tracking-wider text-content-tertiary"
          >
            {t('pointcloud.viewer_point_size', { defaultValue: 'Point size' })}
          </label>
          <input
            id="pointcloud-point-size"
            type="range"
            min={2}
            max={60}
            step={1}
            value={sizeFactor}
            onChange={(e) => setSizeFactor(Number(e.target.value))}
            disabled={phase !== 'ready'}
            className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-tertiary accent-oe-blue"
            data-testid="pointcloud-point-size"
          />
        </div>

        <div className="min-w-[140px]">
          <label
            htmlFor="pointcloud-draw-density"
            className="mb-1 flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-content-tertiary"
          >
            <Gauge size={11} />
            {t('pointcloud.viewer_draw_density', { defaultValue: 'Draw density' })}
            <span className="font-normal normal-case text-content-quaternary">
              {Math.round(drawFraction * 100)}%
            </span>
          </label>
          <input
            id="pointcloud-draw-density"
            type="range"
            min={10}
            max={100}
            step={5}
            value={Math.round(drawFraction * 100)}
            onChange={(e) => setDrawFraction(Number(e.target.value) / 100)}
            disabled={toolsDisabled}
            className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-tertiary accent-oe-blue"
            data-testid="pointcloud-draw-density"
            title={t('pointcloud.draw_density_hint', {
              defaultValue: 'Thin the loaded cloud on screen for smoother navigation - no re-download.',
            })}
          />
        </div>

        <div>
          <label
            htmlFor="pointcloud-bg-mode"
            className="mb-1 flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-content-tertiary"
          >
            <Palette size={11} />
            {t('pointcloud.viewer_background', { defaultValue: 'Background' })}
          </label>
          <select
            id="pointcloud-bg-mode"
            className="rounded-lg border border-border-light bg-surface-secondary px-2.5 py-1.5 text-sm text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            value={bgMode}
            onChange={(e) => setBgMode(e.target.value as BgMode)}
            disabled={toolsDisabled}
            data-testid="pointcloud-bg-mode"
          >
            {bgModeOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div className="ml-auto flex flex-col items-end justify-end gap-0.5 self-end pb-1 text-xs tabular-nums text-content-tertiary">
          {phase === 'ready' && cloud ? (
            <>
              <span>
                {t('pointcloud.viewer_points_shown', {
                  defaultValue: '{{points}} points shown',
                  points: formatPoints(cloud.pointCount),
                })}
              </span>
              {dimensionsLabel && (
                <span className="text-content-quaternary" data-testid="pointcloud-dimensions">
                  {t('pointcloud.viewer_dimensions', {
                    defaultValue: 'Extent {{dims}}',
                    dims: dimensionsLabel,
                  })}
                </span>
              )}
            </>
          ) : null}
        </div>
                </div>

                {activePlaneEqs.length > 0 && (
                  <p
                    className="text-2xs tabular-nums text-content-quaternary"
                    data-testid="pointcloud-visible-readout"
                  >
                    {t('pointcloud.readout_points_visible', {
                      defaultValue: '{{visible}} / {{total}} pts visible',
                      visible: formatPoints(visiblePointCount),
                      total: formatPoints(cloud?.pointCount ?? 0),
                    })}
                  </p>
                )}

                <div className="space-y-1.5 border-t border-border-light pt-3">
                  <span className="flex items-center gap-1.5 text-2xs font-medium text-content-tertiary">
                    <Move3d size={12} />
                    {t('pointcloud.views_label', { defaultValue: 'Views' })}
                  </span>
                  <div className="grid grid-cols-4 gap-1">
                    {presetButtons.map((p) => (
                      <button
                        key={p.view}
                        type="button"
                        onClick={() => applyPreset(p.view)}
                        disabled={toolsDisabled}
                        className="inline-flex items-center justify-center rounded-lg border border-border-light bg-surface-secondary px-2 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-40"
                        data-testid={`pointcloud-view-${p.view}`}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
              </section>

              {sliceEnabled && bounds && (
        <div
          className="flex flex-wrap items-end gap-x-4 gap-y-2 rounded-lg border border-border-light bg-surface-secondary/60 p-3"
          data-testid="pointcloud-slice-panel"
        >
          <div className="min-w-[160px] flex-1">
            <label
              htmlFor="pointcloud-slice-min"
              className="mb-1 block text-2xs font-semibold uppercase tracking-wider text-content-tertiary"
            >
              {t('pointcloud.slice_min_height', { defaultValue: 'Min height' })}
              <span className="ml-1 font-normal normal-case text-content-quaternary">
                {formatMetersLabel(sliceMin)}
              </span>
            </label>
            <input
              id="pointcloud-slice-min"
              type="range"
              min={0}
              max={heightSpan}
              step={sliceStep}
              value={sliceMin}
              onChange={(e) => setSliceMin(Math.min(Number(e.target.value), sliceMax))}
              className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-tertiary accent-oe-blue"
              data-testid="pointcloud-slice-min"
            />
          </div>
          <div className="min-w-[160px] flex-1">
            <label
              htmlFor="pointcloud-slice-max"
              className="mb-1 block text-2xs font-semibold uppercase tracking-wider text-content-tertiary"
            >
              {t('pointcloud.slice_max_height', { defaultValue: 'Max height' })}
              <span className="ml-1 font-normal normal-case text-content-quaternary">
                {formatMetersLabel(sliceMax)}
              </span>
            </label>
            <input
              id="pointcloud-slice-max"
              type="range"
              min={0}
              max={heightSpan}
              step={sliceStep}
              value={sliceMax}
              onChange={(e) => setSliceMax(Math.max(Number(e.target.value), sliceMin))}
              className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-tertiary accent-oe-blue"
              data-testid="pointcloud-slice-max"
            />
          </div>
          <button
            type="button"
            onClick={() => applyPreset('top')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-secondary px-3 py-1.5 text-sm text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary"
            title={t('pointcloud.slice_top_view', { defaultValue: 'Top / plan view' })}
            data-testid="pointcloud-top-view"
          >
            <ArrowDownToLine size={14} />
            {t('pointcloud.slice_top_view', { defaultValue: 'Top / plan view' })}
          </button>
          <p className="w-full text-2xs text-content-quaternary">
            {t('pointcloud.slice_hint', {
              defaultValue: 'Show only points between the two heights - useful to read one storey at a time.',
            })}
          </p>
        </div>
      )}

      {(pickMode === 'measure' || pathMetrics) && (
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border-light bg-surface-secondary/60 p-3"
          data-testid="pointcloud-measure-panel"
        >
          {pathMetrics && pathMetrics.segmentCount >= 1 ? (
            <>
              <span className="text-sm font-medium text-content-primary">
                {t('pointcloud.measure_total', { defaultValue: 'Path' })}:{' '}
                {formatLengthMm(pathMetrics.totalLength)}
              </span>
              <span className="text-xs text-content-tertiary">
                {t('pointcloud.measure_path_readout', {
                  defaultValue: '{{count}} segments · straight line {{straight}}',
                  count: pathMetrics.segmentCount,
                  straight: formatLengthMm(pathMetrics.straightLine),
                })}
              </span>
              {pathMetrics.lastSegment && (
                <span className="text-xs text-content-tertiary">
                  {t('pointcloud.measure_last_segment', {
                    defaultValue: 'Last segment {{d}} (H {{h}} · V {{v}})',
                    d: formatLengthMm(pathMetrics.lastSegment.distance),
                    h: formatLengthMm(pathMetrics.lastSegment.horizontal),
                    v: formatLengthMm(pathMetrics.lastSegment.vertical),
                  })}
                </span>
              )}
            </>
          ) : (
            <span className="text-xs text-content-tertiary">
              {t('pointcloud.measure_hint_path', {
                defaultValue:
                  'Click points on the cloud to trace a path; each click adds a vertex and extends the running total.',
              })}
            </span>
          )}
          {pathMetrics && (
            <div className="ml-auto flex items-center gap-3">
              <button
                type="button"
                onClick={undoLastPathPoint}
                className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-content-primary"
                data-testid="pointcloud-measure-undo"
              >
                <Undo2 size={12} />
                {t('pointcloud.measure_undo', { defaultValue: 'Undo point' })}
              </button>
              <button
                type="button"
                onClick={exportPath}
                disabled={pathMetrics.segmentCount < 1}
                className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-40"
                data-testid="pointcloud-measure-export"
              >
                <Download size={12} />
                {t('pointcloud.export_csv', { defaultValue: 'Export CSV' })}
              </button>
              <button
                type="button"
                onClick={clearPath}
                className="inline-flex items-center gap-1 text-xs text-content-tertiary underline hover:text-danger"
                data-testid="pointcloud-measure-clear"
              >
                <X size={12} />
                {t('pointcloud.measure_clear', { defaultValue: 'Clear' })}
              </button>
            </div>
          )}
        </div>
      )}

      {(pickMode === 'angle' || angleVertexCount > 0) && (
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border-light bg-surface-secondary/60 p-3"
          data-testid="pointcloud-angle-panel"
        >
          {angleValue != null ? (
            <span
              className="text-sm font-medium text-content-primary"
              data-testid="pointcloud-angle-value"
            >
              {t('pointcloud.angle_value', { defaultValue: 'Angle' })}: {formatAngle(angleValue)}
            </span>
          ) : (
            <span className="text-xs text-content-tertiary">
              {t('pointcloud.angle_hint', {
                defaultValue:
                  'Click three points - two arms and the corner between them; the angle at the middle point is measured.',
              })}
            </span>
          )}
          <span className="text-xs text-content-tertiary">
            {t('pointcloud.angle_vertices', {
              defaultValue: '{{count}} / 3 points',
              count: angleVertexCount,
            })}
          </span>
          {angleVertexCount > 0 && (
            <button
              type="button"
              onClick={clearAngle}
              className="ml-auto inline-flex items-center gap-1 text-xs text-content-tertiary underline hover:text-danger"
              data-testid="pointcloud-angle-clear"
            >
              <X size={12} />
              {t('pointcloud.measure_clear', { defaultValue: 'Clear' })}
            </button>
          )}
        </div>
      )}

      {(pickMode === 'area' || areaVertexCount > 0) && (
        <div
          className="space-y-3 rounded-lg border border-border-light bg-surface-secondary/60 p-3"
          data-testid="pointcloud-area-panel"
        >
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {areaVertexCount >= 3 ? (
              <span className="text-sm font-medium text-content-primary">
                {t('pointcloud.area_plan', { defaultValue: 'Plan area' })}: {formatAreaM2(areaPlanArea)}
              </span>
            ) : (
              <span className="text-xs text-content-tertiary">
                {t('pointcloud.area_hint', {
                  defaultValue:
                    'Click at least three points on the ground to outline a footprint; the plan area updates as you go.',
                })}
              </span>
            )}
            <span className="text-xs text-content-tertiary">
              {t('pointcloud.area_vertices', {
                defaultValue: '{{count}} vertices',
                count: areaVertexCount,
              })}
            </span>
            {areaVertexCount > 0 && (
              <div className="ml-auto flex items-center gap-3">
                <button
                  type="button"
                  onClick={() =>
                    addQuantityToBoq(
                      t('pointcloud.boq_desc_area', { defaultValue: 'Point cloud plan area' }),
                      'm2',
                      areaPlanArea,
                    )
                  }
                  disabled={areaVertexCount < 3 || boqSending}
                  className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:text-oe-blue-dark disabled:cursor-not-allowed disabled:opacity-40"
                  data-testid="pointcloud-area-add-boq"
                >
                  <ListPlus size={12} />
                  {t('pointcloud.add_area_boq', { defaultValue: 'Add area to BOQ' })}
                </button>
                <button
                  type="button"
                  onClick={exportArea}
                  disabled={areaVertexCount < 3}
                  className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-40"
                  data-testid="pointcloud-area-export"
                >
                  <Download size={12} />
                  {t('pointcloud.export_csv', { defaultValue: 'Export CSV' })}
                </button>
                <button
                  type="button"
                  onClick={clearArea}
                  className="inline-flex items-center gap-1 text-xs text-content-tertiary underline hover:text-danger"
                  data-testid="pointcloud-area-clear"
                >
                  <X size={12} />
                  {t('pointcloud.measure_clear', { defaultValue: 'Clear' })}
                </button>
              </div>
            )}
          </div>

          {areaVertexCount >= 3 && (
            <div className="space-y-2 border-t border-border-light pt-2">
              <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
                <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                  <Mountain size={12} />
                  {t('pointcloud.volume_title', { defaultValue: 'Cut / fill volume' })}
                </span>
                <div>
                  <label
                    htmlFor="pointcloud-volume-ref"
                    className="mb-1 block text-2xs font-medium text-content-tertiary"
                  >
                    {t('pointcloud.volume_ref', { defaultValue: 'Reference height (m)' })}
                  </label>
                  <input
                    id="pointcloud-volume-ref"
                    type="number"
                    step={0.1}
                    value={Number(effectiveRefY.toFixed(2))}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (Number.isFinite(v)) setVolumeRefY(v);
                    }}
                    className="w-24 rounded border border-border-light bg-surface-secondary px-2 py-1 text-xs tabular-nums text-content-primary"
                    data-testid="pointcloud-volume-ref"
                  />
                </div>
                <div>
                  <label
                    htmlFor="pointcloud-volume-cell"
                    className="mb-1 block text-2xs font-medium text-content-tertiary"
                  >
                    {t('pointcloud.volume_cell', { defaultValue: 'Cell size (m)' })}
                  </label>
                  <input
                    id="pointcloud-volume-cell"
                    type="number"
                    min={0.05}
                    step={0.05}
                    value={Number(effectiveCell.toFixed(2))}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (Number.isFinite(v) && v > 0) setVolumeCell(v);
                    }}
                    className="w-24 rounded border border-border-light bg-surface-secondary px-2 py-1 text-xs tabular-nums text-content-primary"
                    data-testid="pointcloud-volume-cell"
                  />
                </div>
                <button
                  type="button"
                  onClick={computeVolume}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-oe-blue/40 bg-oe-blue/10 px-3 py-1.5 text-sm font-medium text-oe-blue transition-colors hover:bg-oe-blue/20"
                  data-testid="pointcloud-volume-compute"
                >
                  <Mountain size={14} />
                  {t('pointcloud.volume_compute', { defaultValue: 'Estimate volume' })}
                </button>
              </div>

              {volumeResult && (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" data-testid="pointcloud-volume-result">
                  <span className="font-medium text-content-primary">
                    {t('pointcloud.volume_net', { defaultValue: 'Net' })}:{' '}
                    {formatVolumeM3(volumeResult.net)}
                  </span>
                  <span className="text-content-tertiary">
                    {t('pointcloud.volume_fill', { defaultValue: 'Fill' })}{' '}
                    {formatVolumeM3(volumeResult.fill)} · {t('pointcloud.volume_cut', { defaultValue: 'Cut' })}{' '}
                    {formatVolumeM3(volumeResult.cut)}
                  </span>
                  <span className="text-content-quaternary">
                    {t('pointcloud.volume_grid', {
                      defaultValue: 'over {{area}} in {{cells}} cells @ {{cell}} m',
                      area: formatAreaM2(volumeResult.area),
                      cells: volumeResult.cellCount,
                      cell: fmtFixed(volumeResult.cellSize, 2),
                    })}
                  </span>
                  <div className="ml-auto flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() =>
                        addQuantityToBoq(
                          t('pointcloud.boq_desc_fill', { defaultValue: 'Point cloud fill volume' }),
                          'm3',
                          volumeResult.fill,
                        )
                      }
                      disabled={volumeResult.fill <= 0 || boqSending}
                      className="inline-flex items-center gap-1 font-medium text-oe-blue hover:text-oe-blue-dark disabled:cursor-not-allowed disabled:opacity-40"
                      data-testid="pointcloud-volume-add-fill-boq"
                    >
                      <ListPlus size={12} />
                      {t('pointcloud.add_fill_boq', { defaultValue: 'Add fill to BOQ' })}
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        addQuantityToBoq(
                          t('pointcloud.boq_desc_cut', { defaultValue: 'Point cloud cut volume' }),
                          'm3',
                          volumeResult.cut,
                        )
                      }
                      disabled={volumeResult.cut <= 0 || boqSending}
                      className="inline-flex items-center gap-1 font-medium text-oe-blue hover:text-oe-blue-dark disabled:cursor-not-allowed disabled:opacity-40"
                      data-testid="pointcloud-volume-add-cut-boq"
                    >
                      <ListPlus size={12} />
                      {t('pointcloud.add_cut_boq', { defaultValue: 'Add cut to BOQ' })}
                    </button>
                  </div>
                </div>
              )}
              <p className="text-2xs text-content-quaternary">
                {t('pointcloud.volume_hint', {
                  defaultValue:
                    'Estimated by the grid method over the loaded points against the reference height. Lower the cell size or raise draw density for more detail.',
                })}
              </p>
            </div>
          )}
        </div>
      )}

      {(pickMode === 'inspect' || inspectResult) && (
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border-light bg-surface-secondary/60 p-3"
          data-testid="pointcloud-inspect-panel"
        >
          {inspectResult ? (
            <>
              <span className="text-sm font-medium text-content-primary">
                {t('pointcloud.inspect_coords', { defaultValue: 'Scan coordinate' })}
              </span>
              <span className="text-xs tabular-nums text-content-tertiary">
                X {formatMetersLabel(inspectResult.scan.x)} · Y {formatMetersLabel(inspectResult.scan.y)}{' '}
                · Z {formatMetersLabel(inspectResult.scan.z)}
              </span>
              <button
                type="button"
                onClick={clearInspect}
                className="ml-auto inline-flex items-center gap-1 text-xs text-content-tertiary underline hover:text-danger"
                data-testid="pointcloud-inspect-clear"
              >
                <X size={12} />
                {t('pointcloud.measure_clear', { defaultValue: 'Clear' })}
              </button>
            </>
          ) : (
            <span className="text-xs text-content-tertiary">
              {t('pointcloud.inspect_hint', {
                defaultValue: 'Click any point to read its coordinate in the scan / project reference system.',
              })}
            </span>
          )}
        </div>
      )}

      {(pickMode === 'annotate' || annotations.length > 0) && (
        <div
          className="space-y-2 rounded-lg border border-border-light bg-surface-secondary/60 p-3"
          data-testid="pointcloud-annotate-panel"
        >
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="text-xs text-content-tertiary">
              {t('pointcloud.annotate_hint', {
                defaultValue: 'Click a point to drop a pin, then add a short note below.',
              })}
            </span>
            {annotations.length > 0 && (
              <div className="ml-auto flex items-center gap-3">
                <button
                  type="button"
                  onClick={exportAnnotations}
                  className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-oe-blue"
                  data-testid="pointcloud-annotate-export"
                >
                  <Download size={12} />
                  {t('pointcloud.export_csv', { defaultValue: 'Export CSV' })}
                </button>
                <button
                  type="button"
                  onClick={clearAnnotations}
                  className="inline-flex items-center gap-1 text-xs text-content-tertiary underline hover:text-danger"
                  data-testid="pointcloud-annotate-clear"
                >
                  <X size={12} />
                  {t('pointcloud.annotate_clear_all', { defaultValue: 'Clear all' })}
                </button>
              </div>
            )}
          </div>
          {annotations.length > 0 && (
            <ul className="space-y-1.5">
              {annotations.map((a, i) => (
                <li key={a.id} className="flex items-center gap-2" data-testid="pointcloud-annotation-row">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-orange-500/15 text-2xs font-semibold text-orange-600 dark:text-orange-400">
                    {i + 1}
                  </span>
                  <input
                    type="text"
                    value={a.note}
                    onChange={(e) => updateAnnotationNote(a.id, e.target.value)}
                    placeholder={t('pointcloud.annotate_note_placeholder', {
                      defaultValue: 'Add a note (e.g. crack, spall, RFI)',
                    })}
                    className="min-w-0 flex-1 rounded border border-border-light bg-surface-secondary px-2 py-1 text-xs text-content-primary placeholder-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                    data-testid="pointcloud-annotation-note"
                  />
                  <span className="hidden shrink-0 text-2xs tabular-nums text-content-quaternary sm:inline">
                    X {fmtFixed(a.scan.x, 2)} · Y {fmtFixed(a.scan.y, 2)} · Z {fmtFixed(a.scan.z, 2)}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeAnnotation(a.id)}
                    aria-label={t('pointcloud.annotate_remove', { defaultValue: 'Remove pin' })}
                    title={t('pointcloud.annotate_remove', { defaultValue: 'Remove pin' })}
                    className="shrink-0 rounded p-1 text-content-tertiary transition-colors hover:bg-danger/10 hover:text-danger"
                    data-testid="pointcloud-annotation-remove"
                  >
                    <Trash2 size={12} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {clipEnabled && (
        <div
          className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border-light bg-surface-secondary/60 p-3"
          data-testid="pointcloud-clip-panel"
        >
          <span className="text-xs text-content-tertiary">
            {t('pointcloud.clip_hint', {
              defaultValue: 'Adjust the box to isolate one room or zone; points outside are hidden.',
            })}
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => handleClipScale(1 / 1.15)}
              disabled={!clipBox}
              aria-label={t('pointcloud.clip_shrink', { defaultValue: 'Shrink' })}
              title={t('pointcloud.clip_shrink', { defaultValue: 'Shrink' })}
              className="inline-flex items-center justify-center rounded-lg border border-border-light bg-surface-secondary p-1.5 text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-40"
              data-testid="pointcloud-clip-shrink"
            >
              <Minus size={14} />
            </button>
            <button
              type="button"
              onClick={() => handleClipScale(1.15)}
              disabled={!clipBox}
              aria-label={t('pointcloud.clip_grow', { defaultValue: 'Grow' })}
              title={t('pointcloud.clip_grow', { defaultValue: 'Grow' })}
              className="inline-flex items-center justify-center rounded-lg border border-border-light bg-surface-secondary p-1.5 text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-40"
              data-testid="pointcloud-clip-grow"
            >
              <Plus size={14} />
            </button>
            <button
              type="button"
              onClick={handleClipReset}
              disabled={!bounds}
              aria-label={t('pointcloud.clip_reset', { defaultValue: 'Reset' })}
              title={t('pointcloud.clip_reset', { defaultValue: 'Reset' })}
              className="inline-flex items-center justify-center rounded-lg border border-border-light bg-surface-secondary p-1.5 text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-40"
              data-testid="pointcloud-clip-reset"
            >
              <RotateCcw size={14} />
            </button>
          </div>
        </div>
      )}

      {groupsEnabled && (
        <div
          className="space-y-3 rounded-lg border border-border-light bg-surface-secondary/60 p-3"
          data-testid="pointcloud-groups-panel"
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              <Boxes size={12} />
              {t('pointcloud.groups_title', { defaultValue: 'Point groups' })}
            </span>
            <span className="text-xs text-content-tertiary">
              {t('pointcloud.groups_hint', {
                defaultValue:
                  'Size the box over a room, storey or stockpile, then capture it as a named group.',
              })}
            </span>
            {/* Reuse the clip-box sizing so groups need no second control. */}
            <div className="ml-auto flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => handleClipScale(1 / 1.15)}
                disabled={!clipBox}
                aria-label={t('pointcloud.clip_shrink', { defaultValue: 'Shrink' })}
                title={t('pointcloud.clip_shrink', { defaultValue: 'Shrink' })}
                className="inline-flex items-center justify-center rounded-lg border border-border-light bg-surface-secondary p-1.5 text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-40"
                data-testid="pointcloud-groups-shrink"
              >
                <Minus size={14} />
              </button>
              <button
                type="button"
                onClick={() => handleClipScale(1.15)}
                disabled={!clipBox}
                aria-label={t('pointcloud.clip_grow', { defaultValue: 'Grow' })}
                title={t('pointcloud.clip_grow', { defaultValue: 'Grow' })}
                className="inline-flex items-center justify-center rounded-lg border border-border-light bg-surface-secondary p-1.5 text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-40"
                data-testid="pointcloud-groups-grow"
              >
                <Plus size={14} />
              </button>
              <button
                type="button"
                onClick={handleClipReset}
                disabled={!bounds}
                aria-label={t('pointcloud.clip_reset', { defaultValue: 'Reset' })}
                title={t('pointcloud.clip_reset', { defaultValue: 'Reset' })}
                className="inline-flex items-center justify-center rounded-lg border border-border-light bg-surface-secondary p-1.5 text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-40"
                data-testid="pointcloud-groups-box-reset"
              >
                <RotateCcw size={14} />
              </button>
              <button
                type="button"
                onClick={captureGroup}
                disabled={!clipBox}
                className="inline-flex items-center gap-1.5 rounded-lg border border-oe-blue/40 bg-oe-blue/10 px-3 py-1.5 text-sm font-medium text-oe-blue transition-colors hover:bg-oe-blue/20 disabled:cursor-not-allowed disabled:opacity-40"
                data-testid="pointcloud-groups-capture"
              >
                <Plus size={14} />
                {t('pointcloud.groups_capture', { defaultValue: 'Capture as group' })}
              </button>
            </div>
          </div>

          {clipBox && (
            <p className="text-2xs text-content-quaternary" data-testid="pointcloud-groups-box-extent">
              {(() => {
                const m = boxMetrics(clipBox);
                return t('pointcloud.groups_box_extent', {
                  defaultValue: 'Current box {{w}} × {{d}} × {{h}} m · {{vol}} · {{area}}',
                  w: fmtFixed(m.width, 2),
                  d: fmtFixed(m.depth, 2),
                  h: fmtFixed(m.height, 2),
                  vol: formatVolumeM3(m.volume),
                  area: formatAreaM2(m.planArea),
                });
              })()}
            </p>
          )}

          {groups.length > 0 ? (
            <ul className="space-y-1.5 border-t border-border-light pt-2">
              {groups.map((g) => {
                const m = boxMetrics(g.box);
                const isolated = isolatedGroupId === g.id;
                return (
                  <li
                    key={g.id}
                    className="flex flex-wrap items-center gap-2"
                    data-testid="pointcloud-group-row"
                  >
                    <span
                      className="h-4 w-4 shrink-0 rounded border border-black/10 dark:border-white/20"
                      style={{ backgroundColor: g.color }}
                      aria-hidden="true"
                    />
                    <input
                      type="text"
                      value={g.name}
                      onChange={(e) => renameGroup(g.id, e.target.value)}
                      aria-label={t('pointcloud.group_name_label', { defaultValue: 'Group name' })}
                      className="min-w-[7rem] max-w-[12rem] flex-1 rounded border border-border-light bg-surface-secondary px-2 py-1 text-xs text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                      data-testid="pointcloud-group-name"
                    />
                    <span className="shrink-0 text-2xs tabular-nums text-content-tertiary">
                      {t('pointcloud.group_points', {
                        defaultValue: '{{pts}} pts',
                        pts: formatPoints(g.pointCount),
                      })}
                    </span>
                    <span className="hidden shrink-0 text-2xs tabular-nums text-content-quaternary md:inline">
                      {formatVolumeM3(m.volume)} · {formatAreaM2(m.planArea)}
                    </span>
                    <div className="ml-auto flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => toggleIsolateGroup(g.id)}
                        aria-pressed={isolated}
                        title={
                          isolated
                            ? t('pointcloud.group_show_all', { defaultValue: 'Show whole cloud' })
                            : t('pointcloud.group_isolate', { defaultValue: 'Isolate this group' })
                        }
                        className={`inline-flex items-center justify-center rounded-lg border p-1.5 transition-colors ${
                          isolated
                            ? 'border-oe-blue/40 bg-oe-blue/10 text-oe-blue'
                            : 'border-border-light bg-surface-secondary text-content-tertiary hover:bg-surface-tertiary hover:text-content-primary'
                        }`}
                        data-testid="pointcloud-group-isolate"
                      >
                        {isolated ? <EyeOff size={13} /> : <Eye size={13} />}
                      </button>
                      <button
                        type="button"
                        onClick={() => addQuantityToBoq(g.name, 'm3', m.volume)}
                        disabled={boqSending || m.volume <= 0}
                        title={t('pointcloud.group_add_boq', {
                          defaultValue: 'Add volume (m3) to BOQ',
                        })}
                        className="inline-flex items-center justify-center rounded-lg border border-border-light bg-surface-secondary p-1.5 text-content-tertiary transition-colors hover:border-oe-blue/40 hover:bg-oe-blue/10 hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-40"
                        data-testid="pointcloud-group-add-boq"
                      >
                        <ListPlus size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => copyQuantitySummary(g.name, 'm3', Math.round(m.volume * 1000) / 1000)}
                        title={t('pointcloud.group_copy', { defaultValue: 'Copy quantity' })}
                        className="inline-flex items-center justify-center rounded-lg border border-border-light bg-surface-secondary p-1.5 text-content-tertiary transition-colors hover:bg-surface-tertiary hover:text-content-primary"
                        data-testid="pointcloud-group-copy"
                      >
                        <Copy size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => removeGroup(g.id)}
                        aria-label={t('pointcloud.group_remove', { defaultValue: 'Delete group' })}
                        title={t('pointcloud.group_remove', { defaultValue: 'Delete group' })}
                        className="inline-flex items-center justify-center rounded-lg p-1.5 text-content-tertiary transition-colors hover:bg-danger/10 hover:text-danger"
                        data-testid="pointcloud-group-remove"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </li>
                );
              })}
              <li className="flex items-center justify-end pt-0.5">
                <button
                  type="button"
                  onClick={clearGroups}
                  className="inline-flex items-center gap-1 text-2xs text-content-tertiary underline hover:text-danger"
                  data-testid="pointcloud-groups-clear"
                >
                  <X size={11} />
                  {t('pointcloud.groups_clear_all', { defaultValue: 'Clear all groups' })}
                </button>
              </li>
            </ul>
          ) : (
            <p className="border-t border-border-light pt-2 text-2xs text-content-quaternary">
              {t('pointcloud.groups_empty', {
                defaultValue:
                  'No groups yet. Position the box and press Capture as group to record a named region with its point count and volume.',
              })}
            </p>
          )}
        </div>
      )}

            </div>
          </aside>
        )}

        {/* ── Canvas column with the floating tool menu ──────────────────── */}
        <div className="relative min-w-0 flex-1">
          {!toolsDisabled && !panelOpen && (
            <button
              type="button"
              onClick={() => setPanelOpen(true)}
              aria-label={t('pointcloud.panel_show', { defaultValue: 'Show panel' })}
              title={t('pointcloud.panel_show', { defaultValue: 'Show panel' })}
              className="absolute right-3 top-3 z-30 inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border-light bg-surface-primary/85 text-content-secondary shadow-lg backdrop-blur-md transition-colors hover:bg-surface-tertiary hover:text-content-primary"
              data-testid="pointcloud-panel-reopen"
            >
              <PanelRight size={17} />
            </button>
          )}
      {/* ── Canvas + status overlays ─────────────────────────────────────── */}
      <div
        ref={containerRef}
        className={`relative w-full overflow-hidden border border-border-light bg-surface-secondary ${
          isFullscreen ? 'h-full rounded-none' : 'h-[560px] rounded-xl'
        }`}
        style={{ cursor: pickMode === 'none' ? undefined : 'crosshair' }}
        data-testid="pointcloud-viewer-canvas"
        aria-label={
          scanLabel
            ? t('pointcloud.viewer_canvas_aria_named', {
                defaultValue: '3D point cloud viewer for {{name}}',
                name: scanLabel,
              })
            : t('pointcloud.viewer_canvas_aria', { defaultValue: '3D point cloud viewer' })
        }
      >
        {/* ── Floating grouped tool menu, overlaid on the viewport ──────── */}
        {!webglFailed && phase === 'ready' && cloud && cloud.pointCount > 0 && (
          <div
            className="absolute left-1/2 top-3 z-20 flex max-w-[calc(100%-1.5rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-0.5 rounded-xl border border-border-light bg-surface-primary/85 p-1 shadow-lg ring-1 ring-black/5 backdrop-blur-md"
            data-testid="pointcloud-toolbar"
          >
            {/* Navigate */}
            <ToolbarButton
              icon={Maximize2}
              label={t('pointcloud.viewer_refit', { defaultValue: 'Fit view' })}
              shortcut="F"
              onClick={handleRefit}
              testId="pointcloud-fit"
            />
            <ToolbarButton
              icon={isFullscreen ? Minimize2 : Maximize}
              label={
                isFullscreen
                  ? t('pointcloud.fullscreen_exit', { defaultValue: 'Exit fullscreen' })
                  : t('pointcloud.fullscreen', { defaultValue: 'Fullscreen' })
              }
              active={isFullscreen}
              onClick={toggleFullscreen}
              testId="pointcloud-fullscreen"
            />
            <ToolbarDivider />
            {/* Section / segment the cloud */}
            <ToolbarButton
              icon={Layers}
              label={t('pointcloud.tool_slice', { defaultValue: 'Cross-section' })}
              shortcut="X"
              active={sliceEnabled}
              onClick={() => {
                setSliceEnabled((v) => !v);
                setPanelOpen(true);
              }}
              testId="pointcloud-tool-slice"
            />
            <ToolbarButton
              icon={Crop}
              label={t('pointcloud.tool_clip', { defaultValue: 'Clip box' })}
              shortcut="C"
              active={clipEnabled}
              onClick={() => {
                setClipEnabled((v) => !v);
                setPanelOpen(true);
              }}
              testId="pointcloud-tool-clip"
            />
            <ToolbarButton
              icon={Boxes}
              label={t('pointcloud.tool_groups', { defaultValue: 'Groups' })}
              shortcut="B"
              active={groupsEnabled}
              badge={groups.length}
              onClick={() => {
                toggleGroups();
                setPanelOpen(true);
              }}
              testId="pointcloud-tool-groups"
            />
            <ToolbarDivider />
            {/* Measure / select */}
            <ToolbarButton
              icon={Ruler}
              label={t('pointcloud.tool_measure', { defaultValue: 'Measure' })}
              shortcut="M"
              active={pickMode === 'measure'}
              onClick={() => {
                togglePick('measure');
                setPanelOpen(true);
              }}
              testId="pointcloud-tool-measure"
            />
            <ToolbarButton
              icon={Triangle}
              label={t('pointcloud.tool_angle', { defaultValue: 'Angle' })}
              shortcut="N"
              active={pickMode === 'angle'}
              onClick={() => {
                togglePick('angle');
                setPanelOpen(true);
              }}
              testId="pointcloud-tool-angle"
            />
            <ToolbarButton
              icon={Pentagon}
              label={t('pointcloud.tool_area', { defaultValue: 'Area & volume' })}
              shortcut="P"
              active={pickMode === 'area'}
              onClick={() => {
                togglePick('area');
                setPanelOpen(true);
              }}
              testId="pointcloud-tool-area"
            />
            <ToolbarButton
              icon={Crosshair}
              label={t('pointcloud.tool_inspect', { defaultValue: 'Inspect' })}
              shortcut="I"
              active={pickMode === 'inspect'}
              onClick={() => {
                togglePick('inspect');
                setPanelOpen(true);
              }}
              testId="pointcloud-tool-inspect"
            />
            <ToolbarButton
              icon={MapPin}
              label={t('pointcloud.tool_annotate', { defaultValue: 'Annotate' })}
              shortcut="K"
              active={pickMode === 'annotate'}
              onClick={() => {
                togglePick('annotate');
                setPanelOpen(true);
              }}
              testId="pointcloud-tool-annotate"
            />
            <ToolbarDivider />
            {/* Display */}
            <ToolbarButton
              icon={Grid3x3}
              label={t('pointcloud.grid_axes', { defaultValue: 'Grid & axes' })}
              shortcut="G"
              active={showGrid}
              onClick={() => setShowGrid((v) => !v)}
              testId="pointcloud-grid-toggle"
            />
            <ToolbarButton
              icon={CloudFog}
              label={t('pointcloud.depth_cue', { defaultValue: 'Depth cue' })}
              shortcut="D"
              active={depthCue}
              onClick={() => setDepthCue((v) => !v)}
              testId="pointcloud-depth-cue"
            />
            <ToolbarButton
              icon={Camera}
              label={t('pointcloud.snapshot', { defaultValue: 'Snapshot' })}
              shortcut="S"
              onClick={handleSnapshot}
              testId="pointcloud-snapshot"
            />
            <ToolbarDivider />
            <ToolbarButton
              icon={panelOpen ? PanelRightClose : PanelRight}
              label={
                panelOpen
                  ? t('pointcloud.panel_hide', { defaultValue: 'Hide panel' })
                  : t('pointcloud.panel_show', { defaultValue: 'Show panel' })
              }
              active={panelOpen}
              onClick={() => setPanelOpen((v) => !v)}
              testId="pointcloud-panel-toggle"
            />
          </div>
        )}

        {webglFailed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center">
            <AlertCircle size={22} className="text-danger" />
            <p className="text-sm font-medium text-content-primary">
              {t('pointcloud.viewer_webgl_title', { defaultValue: '3D rendering unavailable' })}
            </p>
            <p className="max-w-md text-xs text-content-tertiary">
              {t('pointcloud.viewer_webgl_desc', {
                defaultValue: 'Point Cloud viewer requires a WebGL2-capable browser. Update your browser or enable hardware acceleration.',
              })}
            </p>
          </div>
        )}

        {!webglFailed && phase === 'loading' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-surface-primary/40 backdrop-blur-[2px]">
            <Loader2 size={22} className="animate-spin text-oe-blue" />
            <p className="text-sm text-content-secondary">
              {t('pointcloud.viewer_loading', { defaultValue: 'Streaming points...' })}
            </p>
            {progressBytes > 0 && (
              <p className="text-2xs tabular-nums text-content-quaternary">
                {formatBytes(progressBytes)}
              </p>
            )}
          </div>
        )}

        {!webglFailed && phase === 'error' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center">
            {errorKind === 'processing' ? (
              <Clock size={22} className="text-oe-blue" />
            ) : (
              <AlertCircle size={22} className="text-danger" />
            )}
            <p className="text-sm font-medium text-content-primary">{errorTitle}</p>
            <p className="max-w-md text-xs text-content-tertiary">{errorDescription}</p>
            <button
              type="button"
              onClick={() => setReloadNonce((n) => n + 1)}
              className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-secondary px-3 py-1.5 text-sm text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary"
            >
              <RefreshCw size={13} />
              {t('pointcloud.viewer_retry', { defaultValue: 'Try again' })}
            </button>
          </div>
        )}

        {!webglFailed && phase === 'ready' && cloud && cloud.pointCount === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center">
            <AlertCircle size={22} className="text-content-quaternary" />
            <p className="text-sm text-content-secondary">
              {t('pointcloud.viewer_empty', { defaultValue: 'The scan decoded to zero points.' })}
            </p>
          </div>
        )}

        {/* ── Scale bar: a live ruler whose width/label the animation loop
             keeps sized to a round distance at the current zoom. ─────────── */}
        {!webglFailed && phase === 'ready' && cloud && cloud.pointCount > 0 && (
          <div className="pointer-events-none absolute bottom-3 right-3 z-10 flex flex-col items-center gap-0.5">
            <div
              ref={scaleBarLabelRef}
              className="rounded bg-surface-primary/80 px-1.5 py-0.5 text-2xs font-medium tabular-nums text-content-secondary shadow-sm backdrop-blur-sm"
            />
            <div
              ref={scaleBarRef}
              className="h-2 border-x-2 border-b-2 border-content-secondary/80"
              style={{ width: 0, visibility: 'hidden' }}
              data-testid="pointcloud-scale-bar"
            />
          </div>
        )}

        {/* ── Elevation legend: only meaningful in the height-ramp mode ──── */}
        {!webglFailed && phase === 'ready' && cloud && cloud.pointCount > 0 && colorMode === 'height' && legendRange && (
          <div
            className="absolute bottom-3 left-3 z-10 flex items-start gap-2 rounded-lg border border-border-light bg-surface-primary/90 p-2 shadow-md backdrop-blur-sm"
            data-testid="pointcloud-elevation-legend"
          >
            <div className="flex flex-col items-center gap-1">
              <span className="text-2xs tabular-nums text-content-secondary">
                {formatMetersLabel(legendRange.max)}
              </span>
              <div className="h-24 w-3 rounded-full" style={{ background: RAMP_GRADIENT_CSS }} />
              <span className="text-2xs tabular-nums text-content-secondary">
                {formatMetersLabel(legendRange.min)}
              </span>
            </div>
            <div className="flex flex-col items-start gap-1">
              <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('pointcloud.legend_title', { defaultValue: 'Elevation' })}
              </span>
              <button
                type="button"
                onClick={handleToggleLegendPin}
                aria-pressed={legendPinned}
                className="inline-flex items-center gap-1 text-2xs text-content-tertiary hover:text-oe-blue"
                data-testid="pointcloud-legend-pin"
              >
                {legendPinned ? <Pin size={11} /> : <PinOff size={11} />}
                {t('pointcloud.legend_pin', { defaultValue: 'Pin range' })}
              </button>
              {legendPinned && (
                <div className="flex flex-col gap-1">
                  <input
                    type="number"
                    step={0.1}
                    value={Number(legendRange.max.toFixed(2))}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (Number.isFinite(v)) {
                        setHeightRangeOverride((prev) => ({ min: prev?.min ?? legendRange.min, max: v }));
                      }
                    }}
                    aria-label={t('pointcloud.legend_max_label', { defaultValue: 'Ramp maximum height in metres' })}
                    className="w-16 rounded border border-border-light bg-surface-secondary px-1 py-0.5 text-2xs tabular-nums text-content-primary"
                  />
                  <input
                    type="number"
                    step={0.1}
                    value={Number(legendRange.min.toFixed(2))}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (Number.isFinite(v)) {
                        setHeightRangeOverride((prev) => ({ min: v, max: prev?.max ?? legendRange.max }));
                      }
                    }}
                    aria-label={t('pointcloud.legend_min_label', { defaultValue: 'Ramp minimum height in metres' })}
                    className="w-16 rounded border border-border-light bg-surface-secondary px-1 py-0.5 text-2xs tabular-nums text-content-primary"
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Measure-tool floating label: position updated imperatively
             every frame (see the animation loop) so it stays glued to the
             final segment's midpoint without a per-frame React re-render. ─ */}
        {pathMetrics && pathMetrics.segmentCount >= 1 && (
          <div
            ref={measureLabelRef}
            className="pointer-events-none absolute left-0 top-0 z-10 -translate-x-1/2 -translate-y-[130%] whitespace-nowrap rounded-md bg-black/80 px-2 py-1 text-2xs font-medium text-white shadow-lg"
            data-testid="pointcloud-measure-label"
          >
            <div>{formatLengthMm(pathMetrics.totalLength)}</div>
            <div className="text-[10px] font-normal text-white/75">
              {t('pointcloud.measure_path_segments', {
                defaultValue: '{{count}} segments',
                count: pathMetrics.segmentCount,
              })}
            </div>
          </div>
        )}
      </div>
        </div>
      </div>

      <p className="text-2xs text-content-quaternary">
        {t('pointcloud.viewer_hint', {
          defaultValue: 'Drag to orbit, right-drag to pan, scroll to zoom. Pick a tool, then click points on the cloud. Density re-requests a finer or coarser server-side decimation.',
        })}
      </p>
    </div>
  );
}

export default PointCloudViewer;
