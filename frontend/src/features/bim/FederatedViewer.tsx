// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FederatedViewer - React wrapper around FederatedViewerScene. Slice 3
 * of BIM Federations.
 *
 * Mounts a <canvas>, instantiates one FederatedViewerScene, loads the
 * federation's member GLBs in parallel, and pushes each one into the
 * scene as it resolves. Exposes an imperative ``isolateClass`` handle
 * so the parent page can drive isolation from the federation type tree
 * without prop-thrashing the viewer (which would re-mount Three.js on
 * every selection).
 */
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Maximize2, Minimize2, Ruler, X } from 'lucide-react';

import { Button } from '@/shared/ui';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { DeferredTeardown } from '@/shared/ui/BIMViewer/deferredTeardown';

import {
  FederatedViewerScene,
  WebGLUnavailableError,
  type FederatedMemberAdd,
  type FederatedPickResult,
  type FederatedMeasurement,
} from './FederatedViewerScene';
import {
  useFederatedGeometryLoader,
  type LoadedMember,
} from './useFederatedGeometryLoader';
import {
  FederatedViewerLegend,
  type LegendDiscipline,
} from './FederatedViewerLegend';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/* ── Imperative handle ─────────────────────────────────────────────── */

export interface FederatedViewerHandle {
  isolateClass: (ifcClass: string | null) => void;
  frameAll: () => void;
  resetView: () => void;
}

interface Props {
  federationId: string;
}

/** What the scene-setup effect builds and later needs to dispose. Held in a
 *  ref so a deferred teardown can dispose it after the fact, or a fast remount
 *  (React StrictMode) can cancel that teardown and reuse it. */
interface BuiltFederatedViewer {
  canvas: HTMLCanvasElement;
  scene: FederatedViewerScene;
  disposeNow: () => void;
}

/* ── Test seam ─────────────────────────────────────────────────────── */
// Tests need to mock the Three.js scene without monkey-patching the
// class export (vitest's vi.mock on the same module hits circular-import
// edge cases under vite). We resolve the scene constructor via a small
// factory that tests can override before mounting.
type SceneFactory = (canvas: HTMLCanvasElement) => FederatedViewerScene;
let _sceneFactory: SceneFactory = (canvas) => new FederatedViewerScene(canvas);
export function __setFederatedSceneFactoryForTests(factory: SceneFactory | null): void {
  _sceneFactory = factory ?? ((canvas) => new FederatedViewerScene(canvas));
}

/* ── Component ─────────────────────────────────────────────────────── */

export const FederatedViewer = forwardRef<FederatedViewerHandle, Props>(
  function FederatedViewer({ federationId }, ref) {
    const { t } = useTranslation();
    // Measured distances are reported in the federation's scene units
    // (metric-canonical when shared_units is "m"); convert at the display
    // boundary so an imperial user reads feet (issue #270).
    const displayQty = useDisplayQuantity();
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const containerRef = useRef<HTMLDivElement | null>(null);
    const sceneRef = useRef<FederatedViewerScene | null>(null);
    /** Members we've already pushed into the scene - keyed by modelId so
     * a re-render with the same data is a no-op. */
    const loadedMemberIds = useRef<Set<string>>(new Set());
    // React StrictMode (and any unmount-then-immediately-remount) would
    // otherwise dispose the live scene in the cleanup and rebuild it on the
    // next mount, on a just-force-lost GL context (black canvas / "WebGL
    // unavailable"). We defer the teardown by one task and, if the effect
    // re-runs first, cancel it and reuse the live scene. See the scene
    // lifecycle effect below.
    const teardownRef = useRef<DeferredTeardown | null>(null);
    teardownRef.current ??= new DeferredTeardown();
    const viewerTeardown = teardownRef.current;
    const builtRef = useRef<BuiltFederatedViewer | null>(null);

    const [colorByDiscipline, setColorByDiscipline] = useState(false);
    const [memberVisibility, setMemberVisibility] = useState<
      Record<string, boolean>
    >({});
    /** Set when the Three.js scene cannot start because WebGL2 is unavailable
     *  (headless / no-GPU environments). We render a friendly notice instead of
     *  letting the constructor throw crash the page. */
    const [webglUnavailable, setWebglUnavailable] = useState(false);
    /** B1 - full interactive viewer state. */
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [measureMode, setMeasureMode] = useState(false);
    const [pick, setPick] = useState<FederatedPickResult | null>(null);
    const [measurement, setMeasurement] = useState<FederatedMeasurement | null>(
      null,
    );

    const { detail, members, errors, isLoading, detailError } =
      useFederatedGeometryLoader(federationId);

    /* ── Scene lifecycle ──────────────────────────────────────────── */
    useEffect(() => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      // If a deferred teardown is still pending on THIS canvas, React
      // re-mounted us faster than it could run (StrictMode's double-mount).
      // Nothing was torn down yet, so cancel it and reuse the live scene -
      // already-pushed members stay tracked in loadedMemberIds, so the loader
      // effect below re-runs to a no-op instead of rebuilding on a force-lost
      // context. Re-arm the same teardown for the next unmount and return.
      const pendingBuilt = builtRef.current;
      if (viewerTeardown.pending && pendingBuilt && pendingBuilt.canvas === canvas) {
        viewerTeardown.cancel();
        return () => viewerTeardown.schedule(pendingBuilt.disposeNow);
      }
      // The scene constructor throws WebGLUnavailableError when WebGL2 is not
      // available (or three.js fails to acquire a context). Fail soft: surface
      // a friendly notice rather than letting the throw escape and trip the
      // page error boundary. Any other error is genuinely unexpected, so it is
      // re-thrown for the error boundary to report.
      let scene: FederatedViewerScene;
      try {
        scene = _sceneFactory(canvas);
      } catch (err) {
        if (err instanceof WebGLUnavailableError) {
          // eslint-disable-next-line no-console
          console.warn('FederatedViewer: WebGL unavailable, viewer disabled', err);
          setWebglUnavailable(true);
          return;
        }
        throw err;
      }
      setWebglUnavailable(false);
      sceneRef.current = scene;
      // B1 - surface picks + measurements from the scene into React state so
      // the overlays can render element info / distances.
      scene.setOnPick((r) => setPick(r));
      scene.setOnMeasure((m) => setMeasurement(m));
      const disposeNow = () => {
        // A fast re-mount may already have installed a new scene; only clear
        // the shared refs while they still point at THIS one. The dispose
        // itself always runs so the old scene's GPU memory is freed.
        const isActive = sceneRef.current === scene;
        scene.dispose();
        if (isActive) {
          sceneRef.current = null;
          loadedMemberIds.current.clear();
          builtRef.current = null;
        }
      };
      builtRef.current = { canvas, scene, disposeNow };
      // Defer the teardown by one task so a synchronous re-mount (StrictMode)
      // can cancel it via the reuse guard above; a genuine unmount has no
      // matching re-mount, so the timer fires and disposes for real.
      return () => viewerTeardown.schedule(disposeNow);
    }, []);

    /* ── Dark-mode sync ──────────────────────────────────────────── */
    useEffect(() => {
      const scene = sceneRef.current;
      if (!scene) return;
      const html = document.documentElement;
      const sync = (): void => scene.setDarkMode(html.classList.contains('dark'));
      sync(); // initial
      const observer = new MutationObserver(sync);
      observer.observe(html, { attributes: true, attributeFilter: ['class'] });
      return () => observer.disconnect();
    // sceneRef.current is a stable object; we only need to re-run when the
    // scene itself changes (i.e., never after mount). Empty dep array is
    // intentional here - the MutationObserver keeps it live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    /* ── Push newly-loaded GLBs into the scene ────────────────────── */
    useEffect(() => {
      const scene = sceneRef.current;
      if (!scene) return;
      let cancelled = false;
      (async () => {
        // Track whether this pass actually loaded any NEW member. `members` is
        // a fresh array reference on every render of the loader hook, so this
        // effect re-runs on unrelated parent re-renders; framing only on a real
        // membership growth keeps frameAll() from snapping the camera back to
        // fit-all and discarding the user's current orbit/zoom.
        let addedAny = false;
        for (const m of members) {
          if (cancelled) break;
          if (loadedMemberIds.current.has(m.modelId)) continue;
          const payload: FederatedMemberAdd = {
            modelId: m.modelId,
            discipline: m.discipline,
            glbBuffer: m.buffer,
            originOffset: m.originOffset,
          };
          try {
            await scene.addMember(payload);
            loadedMemberIds.current.add(m.modelId);
            addedAny = true;
            setMemberVisibility((prev) =>
              m.modelId in prev ? prev : { ...prev, [m.modelId]: true },
            );
          } catch (err) {
            // Swallowed - the member is reported via the errors[] surface
            // upstream and we don't want one bad GLB to break the loop.
            // eslint-disable-next-line no-console
            console.warn('FederatedViewer: addMember failed', m.modelId, err);
          }
        }
        if (!cancelled && addedAny) {
          scene.frameAll();
        }
      })();
      return () => {
        cancelled = true;
      };
    }, [members]);

    /* ── Drop scene members that the loader no longer reports ─────── */
    useEffect(() => {
      const scene = sceneRef.current;
      if (!scene || !detail) return;
      const stillKnown = new Set(detail.members.map((m) => m.bim_model_id));
      for (const id of Array.from(loadedMemberIds.current)) {
        if (!stillKnown.has(id)) {
          scene.removeMember(id);
          loadedMemberIds.current.delete(id);
        }
      }
    }, [detail]);

    /* ── Imperative handle ────────────────────────────────────────── */
    useImperativeHandle(
      ref,
      () => ({
        isolateClass: (ifcClass: string | null) => {
          sceneRef.current?.isolateClass(ifcClass);
        },
        frameAll: () => {
          sceneRef.current?.frameAll();
        },
        resetView: () => {
          sceneRef.current?.resetView();
        },
      }),
      [],
    );

    /* ── Toolbar handlers ────────────────────────────────────────── */
    const onFrameAll = useCallback(() => {
      sceneRef.current?.frameAll();
    }, []);
    const onResetView = useCallback(() => {
      sceneRef.current?.resetView();
    }, []);
    const onToggleColorByDiscipline = useCallback(() => {
      setColorByDiscipline((prev) => {
        const next = !prev;
        sceneRef.current?.setDisciplineColoringEnabled(next);
        return next;
      });
    }, []);
    const onToggleMemberVisible = useCallback(
      (modelId: string, visible: boolean) => {
        sceneRef.current?.setMemberVisible(modelId, visible);
        setMemberVisibility((prev) => ({ ...prev, [modelId]: visible }));
      },
      [],
    );

    /* ── B1 interaction handlers ─────────────────────────────────── */
    const onToggleFullscreen = useCallback(() => {
      const el = containerRef.current;
      if (!el) return;
      if (document.fullscreenElement) {
        void document.exitFullscreen?.();
      } else {
        void el.requestFullscreen?.();
      }
    }, []);

    // Keep the fullscreen icon in sync whether the user toggled via our button
    // or the Esc key / browser chrome. The ResizeObserver inside the scene
    // already handles the canvas resize, so there is nothing to do here but
    // track the flag for the button state.
    useEffect(() => {
      const onChange = (): void => {
        setIsFullscreen(document.fullscreenElement === containerRef.current);
      };
      document.addEventListener('fullscreenchange', onChange);
      return () => document.removeEventListener('fullscreenchange', onChange);
    }, []);

    const onToggleMeasure = useCallback(() => {
      setMeasureMode((prev) => {
        const next = !prev;
        sceneRef.current?.setMeasureMode(next);
        // Entering measure mode clears the current selection (in the scene
        // too); leaving it drops the in-progress measurement.
        if (next) setPick(null);
        else setMeasurement(null);
        return next;
      });
    }, []);

    const onClearPick = useCallback(() => {
      sceneRef.current?.clearSelection();
      setPick(null);
    }, []);

    const onClearMeasurement = useCallback(() => {
      sceneRef.current?.clearMeasurements();
      setMeasurement(null);
    }, []);

    /* ── Legend derivation ───────────────────────────────────────── */
    const legendRows = useMemo<LegendDiscipline[]>(() => {
      // Prefer the order from ``detail`` (which carries z_order from the
      // backend) over the ``members`` array (which is keyed by load
      // completion order and therefore non-deterministic).
      const sourceOrder: LoadedMember[] =
        detail
          ? detail.members
              .map((m) =>
                members.find((lm) => lm.modelId === m.bim_model_id),
              )
              .filter((x): x is LoadedMember => !!x)
          : members;
      return sourceOrder.map((m) => ({
        modelId: m.modelId,
        discipline: m.discipline,
        modelName: m.modelName,
        visible: memberVisibility[m.modelId] ?? true,
      }));
    }, [detail, members, memberVisibility]);

    /** modelId -> human model name, for the pick info overlay. */
    const memberNameById = useMemo<Record<string, string>>(() => {
      const map: Record<string, string> = {};
      for (const m of members) map[m.modelId] = m.modelName;
      return map;
    }, [members]);

    /** Federation shared units, used to label measured distances. */
    const unitLabel = detail?.shared_units || 'm';

    /* ── Render ─────────────────────────────────────────────────── */
    return (
      <div
        ref={containerRef}
        data-testid="federated-viewer"
        className="relative h-[60vh] min-h-[400px] w-full overflow-hidden rounded-lg border border-slate-200 bg-slate-50"
      >
        <canvas
          ref={canvasRef}
          data-testid="federated-viewer-canvas"
          className="block h-full w-full"
          role="img"
          aria-label={t('bim.federation.viewer.canvas_aria_label', {
            defaultValue: 'Federated BIM viewer - use mouse to orbit, zoom, and pan',
          })}
        />

        {/* Toolbar - top-left */}
        <div
          data-testid="federated-viewer-toolbar"
          className="absolute left-3 top-3 z-10 flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-200 bg-white/95 px-2 py-1.5 shadow-md backdrop-blur"
        >
          <Button
            size="sm"
            variant="ghost"
            onClick={onFrameAll}
            data-testid="federated-viewer-frame-all"
          >
            {t('bim.federation.viewer.frame_all', { defaultValue: 'Frame all' })}
          </Button>
          <Button
            size="sm"
            variant={colorByDiscipline ? 'primary' : 'ghost'}
            onClick={onToggleColorByDiscipline}
            data-testid="federated-viewer-color-toggle"
            aria-pressed={colorByDiscipline}
          >
            {t('bim.federation.viewer.discipline_color', {
              defaultValue: 'Discipline color',
            })}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onResetView}
            data-testid="federated-viewer-reset"
          >
            {t('bim.federation.viewer.reset_view', {
              defaultValue: 'Reset view',
            })}
          </Button>
          <Button
            size="sm"
            variant={measureMode ? 'primary' : 'ghost'}
            onClick={onToggleMeasure}
            data-testid="federated-viewer-measure-toggle"
            aria-pressed={measureMode}
            title={t('bim.federation.viewer.measure_hint', {
              defaultValue: 'Measure the distance between two points',
            })}
          >
            <Ruler size={14} className="me-1.5" />
            {t('bim.federation.viewer.measure', { defaultValue: 'Measure' })}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onToggleFullscreen}
            data-testid="federated-viewer-fullscreen"
            aria-pressed={isFullscreen}
            title={
              isFullscreen
                ? t('bim.federation.viewer.exit_fullscreen', {
                    defaultValue: 'Exit full screen',
                  })
                : t('bim.federation.viewer.fullscreen', {
                    defaultValue: 'Full screen',
                  })
            }
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </Button>
        </div>

        {/* Legend - top-right */}
        <FederatedViewerLegend
          disciplines={legendRows}
          onToggleVisible={onToggleMemberVisible}
        />

        {/* Measure readout - top-center, shown while measuring (B1) */}
        {measureMode ? (
          <div
            data-testid="federated-viewer-measure-readout"
            className="absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-lg border border-slate-200 bg-white/95 px-3 py-1.5 text-xs text-slate-700 shadow-md backdrop-blur"
          >
            {measurement && measurement.pointCount === 2 ? (
              <span className="flex items-center gap-2">
                <span className="font-semibold tabular-nums">
                  {(() => {
                    // Convert from the federation's scene units to the user's
                    // system. `convert` only scales units it recognises, so a
                    // non-metric (or custom) shared_units value passes through
                    // unchanged - never double-converted.
                    const d = displayQty.convert(measurement.distance, unitLabel);
                    return `${d.value.toLocaleString(getNumberLocale(), {
                      maximumFractionDigits: 3,
                    })} ${d.unit}`;
                  })()}
                </span>
                <button
                  type="button"
                  onClick={onClearMeasurement}
                  className="text-slate-400 hover:text-slate-700"
                  data-testid="federated-viewer-measure-clear"
                  aria-label={t('bim.federation.viewer.measure_clear', {
                    defaultValue: 'Clear measurement',
                  })}
                >
                  <X size={13} />
                </button>
              </span>
            ) : (
              <span>
                {measurement && measurement.pointCount === 1
                  ? t('bim.federation.viewer.measure_second', {
                      defaultValue: 'Click the second point',
                    })
                  : t('bim.federation.viewer.measure_first', {
                      defaultValue: 'Click two points to measure',
                    })}
              </span>
            )}
          </div>
        ) : null}

        {/* Selected element info - bottom-left (B1) */}
        {pick && !measureMode ? (
          <div
            data-testid="federated-viewer-pick-info"
            className="absolute bottom-3 left-3 z-10 max-w-xs rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow-md backdrop-blur"
          >
            <div className="mb-1 flex items-center justify-between gap-3">
              <span className="font-semibold text-slate-800">
                {t('bim.federation.viewer.selected', {
                  defaultValue: 'Selected element',
                })}
              </span>
              <button
                type="button"
                onClick={onClearPick}
                className="text-slate-400 hover:text-slate-700"
                data-testid="federated-viewer-pick-clear"
                aria-label={t('bim.federation.viewer.pick_clear', {
                  defaultValue: 'Clear selection',
                })}
              >
                <X size={13} />
              </button>
            </div>
            <dl className="space-y-0.5 text-slate-600">
              {pick.ifcClass ? (
                <div className="flex gap-2">
                  <dt className="text-slate-400">
                    {t('bim.federation.viewer.pick_class', {
                      defaultValue: 'Type',
                    })}
                  </dt>
                  <dd className="font-medium text-slate-700">{pick.ifcClass}</dd>
                </div>
              ) : null}
              <div className="flex gap-2">
                <dt className="text-slate-400">
                  {t('bim.federation.viewer.pick_model', {
                    defaultValue: 'Model',
                  })}
                </dt>
                <dd className="font-medium text-slate-700">
                  {memberNameById[pick.modelId] ||
                    (pick.modelId
                      ? pick.modelId.slice(0, 8)
                      : t('bim.federation.viewer.pick_unknown_model', {
                          defaultValue: 'Unknown',
                        }))}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt className="text-slate-400">
                  {t('bim.federation.viewer.pick_discipline', {
                    defaultValue: 'Discipline',
                  })}
                </dt>
                <dd className="font-medium capitalize text-slate-700">
                  {pick.discipline}
                </dd>
              </div>
              {pick.objectName ? (
                <div className="flex gap-2">
                  <dt className="text-slate-400">
                    {t('bim.federation.viewer.pick_node', {
                      defaultValue: 'Node',
                    })}
                  </dt>
                  <dd
                    className="truncate font-mono text-[10px] text-slate-500"
                    title={pick.objectName}
                  >
                    {pick.objectName}
                  </dd>
                </div>
              ) : null}
            </dl>
          </div>
        ) : null}

        {/* Loading overlay */}
        {isLoading ? (
          <div
            data-testid="federated-viewer-loading"
            className="absolute inset-0 z-20 flex items-center justify-center bg-white/70 text-sm text-slate-600 backdrop-blur"
          >
            {t('bim.federation.viewer.loading', {
              defaultValue: 'Loading federation geometry…',
            })}
          </div>
        ) : null}

        {/* WebGL-unavailable overlay - non-fatal. The 3D scene could not start
            (no WebGL2 / no GPU), so we show a friendly notice instead of a
            blank canvas or a crashed page. */}
        {webglUnavailable ? (
          <div
            data-testid="federated-viewer-webgl-unavailable"
            role="status"
            className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-1 bg-slate-50 px-6 text-center"
          >
            <div className="text-sm font-semibold text-slate-700">
              {t('bim.federation.viewer.webgl_unavailable_title', {
                defaultValue: '3D viewer not available',
              })}
            </div>
            <div className="max-w-md text-xs text-slate-500">
              {t('bim.federation.viewer.webgl_unavailable_body', {
                defaultValue:
                  'This browser or device does not support WebGL2, which is required to display the federated 3D model. Try a hardware-accelerated browser or update your graphics drivers.',
              })}
            </div>
          </div>
        ) : null}

        {/* Detail error overlay - fatal, blocks the viewer */}
        {detailError ? (
          <div
            data-testid="federated-viewer-detail-error"
            role="alert"
            className="absolute inset-x-3 top-16 z-20 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {t('bim.federation.viewer.detail_error', {
              defaultValue: 'Failed to load federation:',
            })}{' '}
            {detailError.message}
          </div>
        ) : null}

        {/* Per-member state - non-fatal. We split genuine load failures
            (red) from "no geometry yet" members (neutral/informational) so
            a model that simply hasn't been converted doesn't look broken.
            One member's problem never blocks the others from rendering. */}
        {errors.length > 0 ? (
          <div
            data-testid="federated-viewer-member-errors"
            role="status"
            className="absolute inset-x-3 bottom-3 z-20 space-y-2"
          >
            {errors.some((e) => !e.noGeometry) ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                <div className="mb-1 font-semibold">
                  {t('bim.federation.viewer.member_errors', {
                    defaultValue: 'Some models failed to load',
                  })}
                </div>
                <ul className="list-inside list-disc">
                  {errors
                    .filter((e) => !e.noGeometry)
                    .map((e) => (
                      <li
                        key={e.modelId}
                        data-testid={`federated-viewer-member-error-${e.modelId}`}
                      >
                        {e.modelName || e.modelId.slice(0, 8)}: {e.error.message}
                      </li>
                    ))}
                </ul>
              </div>
            ) : null}
            {errors.some((e) => e.noGeometry) ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                <div className="mb-1 font-semibold">
                  {t('bim.federation.viewer.member_no_geometry_title', {
                    defaultValue: 'No 3D geometry yet',
                  })}
                </div>
                <ul className="list-inside list-disc">
                  {errors
                    .filter((e) => e.noGeometry)
                    .map((e) => (
                      <li
                        key={e.modelId}
                        data-testid={`federated-viewer-member-error-${e.modelId}`}
                      >
                        {t('bim.federation.viewer.member_no_geometry_item', {
                          defaultValue: '{{model}}: no 3D geometry yet',
                          model: e.modelName || e.modelId.slice(0, 8),
                        })
                          .toString()
                          .replace('{{model}}', e.modelName || e.modelId.slice(0, 8))}
                      </li>
                    ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  },
);

export default FederatedViewer;
