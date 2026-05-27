// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FederatedViewer — React wrapper around FederatedViewerScene. Slice 3
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

import { Button } from '@/shared/ui';

import {
  FederatedViewerScene,
  type FederatedMemberAdd,
} from './FederatedViewerScene';
import {
  useFederatedGeometryLoader,
  type LoadedMember,
} from './useFederatedGeometryLoader';
import {
  FederatedViewerLegend,
  type LegendDiscipline,
} from './FederatedViewerLegend';

/* ── Imperative handle ─────────────────────────────────────────────── */

export interface FederatedViewerHandle {
  isolateClass: (ifcClass: string | null) => void;
  frameAll: () => void;
  resetView: () => void;
}

interface Props {
  federationId: string;
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
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const containerRef = useRef<HTMLDivElement | null>(null);
    const sceneRef = useRef<FederatedViewerScene | null>(null);
    /** Members we've already pushed into the scene — keyed by modelId so
     * a re-render with the same data is a no-op. */
    const loadedMemberIds = useRef<Set<string>>(new Set());

    const [colorByDiscipline, setColorByDiscipline] = useState(false);
    const [memberVisibility, setMemberVisibility] = useState<
      Record<string, boolean>
    >({});

    const { detail, members, errors, isLoading, detailError } =
      useFederatedGeometryLoader(federationId);

    /* ── Scene lifecycle ──────────────────────────────────────────── */
    useEffect(() => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const scene = _sceneFactory(canvas);
      sceneRef.current = scene;
      return () => {
        scene.dispose();
        sceneRef.current = null;
        loadedMemberIds.current.clear();
      };
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
    // intentional here — the MutationObserver keeps it live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    /* ── Push newly-loaded GLBs into the scene ────────────────────── */
    useEffect(() => {
      const scene = sceneRef.current;
      if (!scene) return;
      let cancelled = false;
      (async () => {
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
            setMemberVisibility((prev) =>
              m.modelId in prev ? prev : { ...prev, [m.modelId]: true },
            );
          } catch (err) {
            // Swallowed — the member is reported via the errors[] surface
            // upstream and we don't want one bad GLB to break the loop.
            // eslint-disable-next-line no-console
            console.warn('FederatedViewer: addMember failed', m.modelId, err);
          }
        }
        if (!cancelled && members.length > 0) {
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
            defaultValue: 'Federated BIM viewer — use mouse to orbit, zoom, and pan',
          })}
        />

        {/* Toolbar — top-left */}
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
        </div>

        {/* Legend — top-right */}
        <FederatedViewerLegend
          disciplines={legendRows}
          onToggleVisible={onToggleMemberVisible}
        />

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

        {/* Detail error overlay — fatal, blocks the viewer */}
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

        {/* Per-member error toasts — non-fatal */}
        {errors.length > 0 ? (
          <div
            data-testid="federated-viewer-member-errors"
            role="alert"
            className="absolute inset-x-3 bottom-3 z-20 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800"
          >
            <div className="mb-1 font-semibold">
              {t('bim.federation.viewer.member_errors', {
                defaultValue: 'Some models failed to load',
              })}
            </div>
            <ul className="list-inside list-disc">
              {errors.map((e) => (
                <li
                  key={e.modelId}
                  data-testid={`federated-viewer-member-error-${e.modelId}`}
                >
                  {e.modelId.slice(0, 8)}: {e.error.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    );
  },
);

export default FederatedViewer;
