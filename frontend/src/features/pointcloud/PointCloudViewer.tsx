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
 * size, density (re-requests with a different ``max_points`` cap) and re-fit.
 * The scan may still be processing server-side: 409 / 404 / 501 / 422 map to
 * friendly status panels instead of crashing the page.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { AlertCircle, Clock, Loader2, Maximize2, RefreshCw } from 'lucide-react';
import { useThemeStore } from '@/stores/useThemeStore';
import { fetchScanPoints, ScanPointsError } from './api';
import { parseOepc, OepcParseError, type OepcCloud } from './oepc';

export type ColorMode = 'rgb' | 'height' | 'intensity' | 'single';

type LoadPhase = 'loading' | 'ready' | 'error';
type ErrorKind = 'processing' | 'notfound' | 'reader' | 'decode' | 'generic';

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

/** Build the per-vertex color buffer for the requested mode. */
function buildColors(cloud: OepcCloud, mode: ColorMode): Float32Array {
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
    // converted into the centre-relative frame the positions live in.
    const zMin = cloud.bboxMin[2] - cloud.center[2];
    const zMax = cloud.bboxMax[2] - cloud.center[2];
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
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface PointCloudViewerProps {
  scanId: string;
  /** Display label for the header, e.g. the scan source / format. */
  scanLabel?: string;
}

export function PointCloudViewer({ scanId, scanLabel }: PointCloudViewerProps) {
  const { t } = useTranslation();
  const resolvedTheme = useThemeStore((s) => s.resolved);

  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const pointsRef = useRef<THREE.Points | null>(null);
  /** Base point size derived from the cloud extent; the slider scales it. */
  const baseSizeRef = useRef(0.01);

  const [phase, setPhase] = useState<LoadPhase>('loading');
  const [errorKind, setErrorKind] = useState<ErrorKind>('generic');
  const [errorDetail, setErrorDetail] = useState('');
  const [progressBytes, setProgressBytes] = useState(0);
  const [cloud, setCloud] = useState<OepcCloud | null>(null);
  const [maxPoints, setMaxPoints] = useState<number>(1_500_000);
  const [colorMode, setColorMode] = useState<ColorMode>('single');
  const [sizeFactor, setSizeFactor] = useState(10);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [webglFailed, setWebglFailed] = useState(false);

  // ── Scene lifecycle: one renderer per mount, disposed on unmount ─────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    } catch {
      setWebglFailed(true);
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth || 1, container.clientHeight || 1);
    renderer.domElement.style.display = 'block';
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

  // ── Theme: keep the scene background in sync with the app theme ──────────
  useEffect(() => {
    const scene = sceneRef.current;
    if (scene) scene.background = new THREE.Color(resolvedTheme === 'dark' ? BG_DARK : BG_LIGHT);
  }, [resolvedTheme, webglFailed]);

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

    const material = new THREE.PointsMaterial({
      size: baseSizeRef.current * (sizeFactor / 10),
      vertexColors: true,
      sizeAttenuation: true,
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
    (attr.array as Float32Array).set(buildColors(cloud, colorMode));
    attr.needsUpdate = true;
  }, [cloud, colorMode]);

  // ── In-place point-size update ────────────────────────────────────────────
  useEffect(() => {
    const points = pointsRef.current;
    if (!points) return;
    (points.material as THREE.PointsMaterial).size = baseSizeRef.current * (sizeFactor / 10);
  }, [sizeFactor, cloud]);

  const handleRefit = useCallback(() => {
    // Cheapest reliable re-fit: replay the data effect by cloning the cloud
    // reference (the typed arrays are shared, so this allocates nothing big).
    setCloud((prev) => (prev ? { ...prev } : prev));
  }, []);

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
            "This deployment is missing the server-side reader for the scan's format. Install the pointcloud extra on the server to enable viewing.",
        });
      case 'decode':
        return t('pointcloud.viewer_decode_desc', {
          defaultValue: 'The file could not be decoded into points. Re-export the scan and upload again.',
        });
      default:
        return errorDetail;
    }
  }, [errorKind, errorDetail, t]);

  return (
    <div className="space-y-3">
      {/* ── Toolbar ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
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
            disabled={phase === 'loading'}
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

        <button
          type="button"
          onClick={handleRefit}
          disabled={phase !== 'ready' || !cloud || cloud.pointCount === 0}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-secondary px-3 py-1.5 text-sm text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-40"
          title={t('pointcloud.viewer_refit', { defaultValue: 'Fit view' })}
        >
          <Maximize2 size={14} />
          {t('pointcloud.viewer_refit', { defaultValue: 'Fit view' })}
        </button>

        <div className="ml-auto self-center text-xs tabular-nums text-content-tertiary">
          {phase === 'ready' && cloud
            ? t('pointcloud.viewer_points_shown', {
                defaultValue: '{{points}} points shown',
                points: formatPoints(cloud.pointCount),
              })
            : null}
        </div>
      </div>

      {/* ── Canvas + status overlays ─────────────────────────────────────── */}
      <div
        ref={containerRef}
        className="relative h-[480px] w-full overflow-hidden rounded-xl border border-border-light bg-surface-secondary"
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
        {webglFailed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center">
            <AlertCircle size={22} className="text-danger" />
            <p className="text-sm font-medium text-content-primary">
              {t('pointcloud.viewer_webgl_title', { defaultValue: '3D rendering unavailable' })}
            </p>
            <p className="max-w-md text-xs text-content-tertiary">
              {t('pointcloud.viewer_webgl_desc', {
                defaultValue: 'WebGL could not start in this browser. Update your browser or enable hardware acceleration.',
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
      </div>

      <p className="text-2xs text-content-quaternary">
        {t('pointcloud.viewer_hint', {
          defaultValue: 'Drag to orbit, right-drag to pan, scroll to zoom. Density re-requests a finer or coarser server-side decimation.',
        })}
      </p>
    </div>
  );
}

export default PointCloudViewer;
