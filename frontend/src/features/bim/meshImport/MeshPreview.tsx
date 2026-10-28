// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * MeshPreview - live viewport for the mesh import dialog.
 *
 * The import asks for two things the file itself cannot be trusted to state:
 * the source unit and which axis points up. Both were previously chosen from
 * numbers alone. Getting the axis wrong lays the model on its side; getting
 * the unit wrong scales every quantity by a factor of a thousand, and a
 * thousand-fold error in an area or a volume is a priced error downstream.
 *
 * So this renders the parsed scene under exactly the transform the import will
 * bake in (``scale * upAxisCorrection``), so the orientation and the proportions
 * a user approves here are the ones that get stored.
 *
 * On the grid: its spacing adapts to the model and is labelled in metres, which
 * makes it a readable ruler but NOT a scale check. Because the step is derived
 * from the already-scaled bounding box, a model covers roughly the same number
 * of squares whether the unit is right or wrong - only the label changes. The
 * actual wrong-unit check is the absolute-size warning in the dialog, which
 * compares the largest dimension against a plausible building range. Do not
 * reintroduce "count the squares" as a scale test; it cannot work here.
 *
 * IMPORTANT: nothing from the parsed tree is ever reparented into this scene.
 * ``extractSceneMetrics`` calls ``root.updateMatrixWorld(true)`` and measures
 * from each mesh's ``matrixWorld``, so hanging the real object under a scaled
 * group would silently multiply every quantity the dialog reports. Instead the
 * preview builds proxy meshes that share the source geometry buffers and carry
 * the source world matrix - the same construction ``buildNormalizedGlb`` uses
 * for the export, so the preview and the stored model agree by construction
 * (including for skinned meshes, which both flatten to their bind pose). The
 * geometry is shared, so this component must never dispose it.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RotateCcw } from 'lucide-react';
import { upAxisMatrix, type UpAxis } from './geometry';
import { getNumberLocale } from '@/stores/usePreferencesStore';

export interface MeshPreviewProps {
  /** The parsed scene, in its own native coordinates. Never mutated. */
  object: THREE.Object3D;
  /** Which axis of the source file points up. */
  upAxis: UpAxis;
  /** Metres per source unit (e.g. 0.001 for millimetres). */
  unitScale: number;
}

/** Camera framing margin around the model's bounding sphere. */
const FIT_MARGIN = 1.35;
const FOV = 45;

/**
 * Round a raw spacing up to the nearest 1 / 2 / 5 x 10^n, so the grid is
 * always labelled with a number a person reads without decoding it.
 */
function niceStep(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const exp = Math.floor(Math.log10(raw));
  const pow = Math.pow(10, exp);
  const mantissa = raw / pow;
  const stepMantissa = mantissa <= 1 ? 1 : mantissa <= 2 ? 2 : mantissa <= 5 ? 5 : 10;
  return stepMantissa * pow;
}

/** Format a grid step in metres, dropping the noise digits. */
function formatStep(step: number): string {
  if (step >= 1) return `${step.toLocaleString(getNumberLocale(), { maximumFractionDigits: 0 })} m`;
  if (step >= 0.01) return `${(step * 100).toLocaleString(getNumberLocale(), { maximumFractionDigits: 0 })} cm`;
  return `${(step * 1000).toLocaleString(getNumberLocale(), { maximumFractionDigits: 0 })} mm`;
}

export function MeshPreview({ object, upAxis, unitScale }: MeshPreviewProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);

  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const contentRef = useRef<THREE.Group | null>(null);
  const gridRef = useRef<THREE.GridHelper | null>(null);
  const materialRef = useRef<THREE.Material | null>(null);

  const [webglFailed, setWebglFailed] = useState(false);
  const [gridStep, setGridStep] = useState(1);

  /* ── Renderer lifecycle: one per mount, fully disposed on unmount ───────── */
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setWebglFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth, container.clientHeight, false);
    container.appendChild(renderer.domElement);
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.display = 'block';
    rendererRef.current = renderer;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    // The import's canonical space is Z-up (``upAxisMatrix`` rotates a Y-up
    // source onto Z), so the camera and the grid are set up Z-up to match.
    const camera = new THREE.PerspectiveCamera(
      FOV,
      Math.max(container.clientWidth, 1) / Math.max(container.clientHeight, 1),
      0.01,
      10_000,
    );
    camera.up.set(0, 0, 1);
    cameraRef.current = camera;

    scene.add(new THREE.HemisphereLight(0xffffff, 0x4a5262, 2.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.set(1, -1.4, 2);
    scene.add(key);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controls.screenSpacePanning = true;
    controlsRef.current = controls;

    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      controls.update();
      renderer.render(scene, camera);
    };
    tick();

    const ro = new ResizeObserver(() => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    });
    ro.observe(container);

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      controls.dispose();
      // Geometry and materials on the cloned content are shared with the
      // parsed scene the dialog still measures from - disposing them here
      // would empty the model out from under the extraction. Only the objects
      // this component created are disposed.
      gridRef.current?.geometry.dispose();
      (gridRef.current?.material as THREE.Material | undefined)?.dispose();
      materialRef.current?.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
      contentRef.current = null;
      gridRef.current = null;
      materialRef.current = null;
    };
  }, []);

  /* ── Content: a clone of the parsed scene, under the import's transform ── */
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    const material = new THREE.MeshStandardMaterial({
      color: 0xbfc4cc,
      side: THREE.DoubleSide,
      flatShading: false,
      roughness: 0.85,
      metalness: 0.0,
    });
    materialRef.current?.dispose();
    materialRef.current = material;

    // Flatten to proxy meshes exactly the way ``buildNormalizedGlb`` does:
    // one plain Mesh per source mesh, sharing the source geometry buffer and
    // carrying the source world matrix. Three reasons this beats clone():
    // the parsed tree is never reparented (so the dialog's measurements stay
    // untouched), geometry is shared rather than copied (so a large model
    // costs nothing), and a SkinnedMesh becomes the same plain bind-pose Mesh
    // the exporter writes - clone() does not rebind skeletons, so a cloned
    // skinned model can render collapsed even though it imports correctly.
    object.updateMatrixWorld(true);
    const group = new THREE.Group();
    object.traverse((o) => {
      if (!(o instanceof THREE.Mesh)) return;
      const proxy = new THREE.Mesh(o.geometry, material);
      proxy.matrixAutoUpdate = false;
      proxy.matrix.copy(o.matrixWorld);
      group.add(proxy);
    });
    scene.add(group);
    contentRef.current = group;

    return () => {
      scene.remove(group);
      contentRef.current = null;
    };
  }, [object]);

  /* ── Transform + framing: re-applied whenever unit or up-axis changes ──── */
  const fitView = useCallback(() => {
    const group = contentRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    const scene = sceneRef.current;
    if (!group || !camera || !controls || !scene) return;

    // Exactly the transform ``buildNormalizedGlb`` bakes into the export, so
    // what the user approves here is what the import stores.
    const m = new THREE.Matrix4()
      .makeScale(unitScale, unitScale, unitScale)
      .multiply(upAxisMatrix(upAxis));
    group.matrixAutoUpdate = false;
    group.matrix.copy(m);
    group.updateMatrixWorld(true);

    const box = new THREE.Box3().setFromObject(group);
    if (box.isEmpty()) return;
    const centre = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const radius = Math.max(size.length() / 2, 1e-4);

    // Ground grid on the XY plane (Z-up), sized to the model and stepped to a
    // round number of metres so it reads as a ruler rather than decoration.
    const step = niceStep(Math.max(size.x, size.y, 1e-4) / 12);
    const divisions = Math.max(4, Math.ceil((Math.max(size.x, size.y) * 2) / step));
    const extent = step * divisions;
    if (gridRef.current) {
      scene.remove(gridRef.current);
      gridRef.current.geometry.dispose();
      (gridRef.current.material as THREE.Material).dispose();
    }
    const grid = new THREE.GridHelper(extent, divisions, 0x8b93a1, 0xd4d8e0);
    // GridHelper lies in XZ; rotate it into XY so it is the ground under a
    // Z-up model, and drop it to the model's base.
    grid.rotation.x = Math.PI / 2;
    grid.position.set(centre.x, centre.y, box.min.z);
    scene.add(grid);
    gridRef.current = grid;
    setGridStep(step);

    const distance = (radius / Math.sin((FOV * Math.PI) / 360)) * FIT_MARGIN;
    camera.near = Math.max(distance / 1000, 1e-4);
    camera.far = distance * 100;
    camera.position.set(
      centre.x + distance * 0.62,
      centre.y - distance * 0.62,
      centre.z + distance * 0.48,
    );
    camera.updateProjectionMatrix();
    controls.target.copy(centre);
    controls.update();
  }, [unitScale, upAxis]);

  useEffect(() => {
    fitView();
  }, [fitView, object]);

  if (webglFailed) {
    return (
      <div className="rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-4 text-[11px] text-content-tertiary text-center">
        {t('bim.mesh_import.preview_unavailable', {
          defaultValue:
            '3D preview is unavailable in this browser. The measured quantities below are unaffected.',
        })}
      </div>
    );
  }

  return (
    <div className="relative rounded-lg border border-border-light bg-surface-secondary/40 overflow-hidden">
      <div ref={containerRef} className="w-full h-52" />

      {/* Scale legend: the fastest way to catch a wrong source unit. */}
      <div className="absolute bottom-1.5 left-2 flex items-center gap-1.5 text-[10px] text-content-tertiary bg-surface-primary/75 rounded px-1.5 py-0.5 pointer-events-none">
        <span className="inline-block w-3 h-px bg-content-tertiary" />
        {t('bim.mesh_import.preview_grid', {
          defaultValue: 'Grid {{step}}',
          step: formatStep(gridStep),
        })}
      </div>

      {/* Up-axis indicator: confirms which way the model will stand. */}
      <div className="absolute top-1.5 left-2 text-[10px] font-mono text-content-tertiary bg-surface-primary/75 rounded px-1.5 py-0.5 pointer-events-none">
        {upAxis === 'z' ? 'Z' : 'Y'} &uarr;
      </div>

      <button
        type="button"
        onClick={fitView}
        className="absolute top-1.5 right-1.5 p-1 rounded bg-surface-primary/75 text-content-tertiary hover:text-content-primary"
        aria-label={t('bim.mesh_import.preview_reset', { defaultValue: 'Reset view' })}
        title={t('bim.mesh_import.preview_reset', { defaultValue: 'Reset view' })}
      >
        <RotateCcw size={12} />
      </button>
    </div>
  );
}
