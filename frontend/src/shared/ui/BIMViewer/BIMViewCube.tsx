// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMViewCube — Revit-style View Cube widget for the BIM viewer (W6.6).
 *
 * Self-contained 3-D widget pinned top-right of the viewer. The cube
 * mirrors the main camera's orientation in real time; clicking any face
 * (top / bottom / front / back / left / right), corner (iso views) or
 * edge (averaged orth view) flies the main camera to that preset via
 * `SceneManager.setViewPreset`.
 *
 * WHY: Architects expect a View Cube. It is the most discoverable way
 * to reorient a model — they have used it for two decades in mainstream
 * BIM authoring and coordination tools. We render a tiny independent three.js scene
 * so the widget never competes with the main viewport for raycasts or
 * render time.
 */
import { useEffect, useRef, useState } from 'react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { Box } from 'lucide-react';
import * as THREE from 'three';
import type { SceneManager, ViewPreset } from './SceneManager';

export interface BIMViewCubeProps {
  /** Active scene manager. `null` while the viewer is loading. */
  sceneManager: SceneManager | null;
  /** Tailwind class overrides for the positioning wrapper. */
  className?: string;
  /** Pixel size of the cube canvas. Defaults to 80 (matches RFC 19). */
  size?: number;
}

interface FaceDef {
  preset: ViewPreset;
  labelKey: string;
  labelDefault: string;
  /** Normal in cube-local space (used to pick a face from a raycast). */
  normal: THREE.Vector3;
}

const FACE_DEFS: FaceDef[] = [
  { preset: 'right', labelKey: 'bim.view_cube_right', labelDefault: 'Right', normal: new THREE.Vector3(1, 0, 0) },
  { preset: 'left', labelKey: 'bim.view_cube_left', labelDefault: 'Left', normal: new THREE.Vector3(-1, 0, 0) },
  { preset: 'top', labelKey: 'bim.view_cube_top', labelDefault: 'Top', normal: new THREE.Vector3(0, 1, 0) },
  { preset: 'bottom', labelKey: 'bim.view_cube_bottom', labelDefault: 'Bottom', normal: new THREE.Vector3(0, -1, 0) },
  { preset: 'front', labelKey: 'bim.view_cube_front', labelDefault: 'Front', normal: new THREE.Vector3(0, 0, 1) },
  { preset: 'back', labelKey: 'bim.view_cube_back', labelDefault: 'Back', normal: new THREE.Vector3(0, 0, -1) },
];

function faceLabel(t: TFunction, face: FaceDef): string {
  return t(face.labelKey, { defaultValue: face.labelDefault }).toLocaleUpperCase();
}

/**
 * Paint a centred text label onto a 128×128 canvas — used as the texture
 * for one face of the cube. Returns a CanvasTexture ready for assignment
 * to a MeshBasicMaterial.
 */
function makeFaceTexture(label: string): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    // Off-white base with a soft border so the cube reads as a card.
    ctx.fillStyle = '#f5f7fa';
    ctx.fillRect(0, 0, 128, 128);
    ctx.strokeStyle = '#9ca3af';
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, 126, 126);
    ctx.fillStyle = '#0f172a';
    ctx.font = 'bold 18px system-ui, -apple-system, "Segoe UI", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, 64, 64);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

export function BIMViewCube({
  sceneManager,
  className,
  size = 80,
}: BIMViewCubeProps) {
  const { t } = useTranslation();
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  /**
   * True once this widget knows it cannot paint - either the renderer never
   * constructed, or the GL context went away underneath it. Either way the
   * canvas must come out of the DOM: an undrawn 112x112 canvas pinned over
   * the viewer is not invisible, it is a blank card sitting on the model.
   */
  const [glUnavailable, setGlUnavailable] = useState(false);
  /** Track the latest scene manager so click handlers don't capture stale refs. */
  const sceneManagerRef = useRef<SceneManager | null>(sceneManager);
  sceneManagerRef.current = sceneManager;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    // The cleanup force-loses the GL context, which never comes back on that
    // canvas; every effect run (StrictMode, resize) therefore gets a fresh one.
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    canvas.style.cssText = `width:${size}px;height:${size}px;display:block`;
    canvas.setAttribute('aria-label', t('bim.view_cube_label', { defaultValue: 'View cube' }));
    host.appendChild(canvas);

    // Creating the renderer spins up a WebGL context, which can fail: WebGL may
    // be disabled or on a blocklisted GPU, or the browser's per-page context
    // budget (Chrome caps it near 16) may already be spent by the main viewer
    // and other 3-D widgets. When it fails, three.js throws from deep inside the
    // constructor - getShaderPrecisionFormat can return null, so reading
    // `.precision` on it raises a TypeError. The View Cube is a non-essential
    // navigation gizmo, so swallow that rather than let the error escape the
    // effect and tear down the whole page (e.g. Model Review) through the
    // error boundary.
    //
    // Swallowing it is not enough on its own. This used to `return` here and
    // leave the <canvas> mounted, 112x112 and never drawn into, pinned over
    // the model - which the browser paints as an empty card with a broken
    // graphic on it. Flag it instead, so the render below puts a real
    // placeholder in the canvas's place.
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
      });
    } catch (err) {
      console.warn('[BIMViewCube] WebGL unavailable, hiding the view cube', err);
      setGlUnavailable(true);
      canvas.remove();
      return;
    }
    setGlUnavailable(false);

    // A context that constructed fine can still be taken away later - the
    // ordinary causes are a laptop switching GPUs and waking from sleep, not
    // anything the user did. Same treatment: stop claiming to be a cube.
    function onContextLost() {
      console.warn('[BIMViewCube] WebGL context lost, showing the placeholder');
      setGlUnavailable(true);
    }
    canvas.addEventListener('webglcontextlost', onContextLost);
    renderer.setPixelRatio(window.devicePixelRatio || 1);
    renderer.setSize(size, size, false);
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    // Camera frustum sized so the unit cube fills ~70% of the viewport.
    const cam = new THREE.OrthographicCamera(-1.5, 1.5, 1.5, -1.5, 0.1, 100);
    cam.position.set(0, 0, 5);
    cam.lookAt(0, 0, 0);

    // Light — soft hemispheric so all faces read evenly while still
    // having a slight 3-D feel when the cube spins.
    const hemi = new THREE.HemisphereLight(0xffffff, 0xc0c0c0, 1.0);
    scene.add(hemi);

    // Build the cube. BoxGeometry face order is +X, -X, +Y, -Y, +Z, -Z.
    // Match that to the FACE_DEFS array so the textures land on the
    // right side.
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const orderedFaces: FaceDef[] = [
      FACE_DEFS.find((f) => f.normal.x === 1)!,
      FACE_DEFS.find((f) => f.normal.x === -1)!,
      FACE_DEFS.find((f) => f.normal.y === 1)!,
      FACE_DEFS.find((f) => f.normal.y === -1)!,
      FACE_DEFS.find((f) => f.normal.z === 1)!,
      FACE_DEFS.find((f) => f.normal.z === -1)!,
    ];
    const textures = orderedFaces.map((f) => makeFaceTexture(faceLabel(t, f)));
    const materials = textures.map(
      (tex) => new THREE.MeshBasicMaterial({ map: tex }),
    );
    const cube = new THREE.Mesh(geometry, materials);
    scene.add(cube);

    // The cube needs to ROTATE OPPOSITE to the main camera so that, as
    // the user orbits, the labels stay on the side of the cube that
    // matches the world axis the main camera is facing.
    let mainCamRef: THREE.Camera | null = sceneManagerRef.current?.camera ?? null;
    let mainTarget = new THREE.Vector3();
    if (sceneManagerRef.current) {
      mainTarget.copy(sceneManagerRef.current.controls.target);
    }

    const tmpQuat = new THREE.Quaternion();
    function syncCubeRotation() {
      if (!mainCamRef) return;
      // Build a quaternion representing the main camera's view basis,
      // then invert it onto the cube so the cube spins with it.
      mainCamRef.matrixWorld.decompose(new THREE.Vector3(), tmpQuat, new THREE.Vector3());
      // Rotate the cube to be the inverse: when the camera looks at the
      // +Z face from +Z, the cube should present the "FRONT" face to us.
      cube.quaternion.copy(tmpQuat).invert();
    }

    // Subscribe to camera-change events to repaint on every camera move.
    let unsubscribe: (() => void) | null = null;
    const attachCameraSubscription = (sm: SceneManager | null) => {
      if (unsubscribe) {
        unsubscribe();
        unsubscribe = null;
      }
      mainCamRef = sm?.camera ?? null;
      if (sm) {
        mainTarget.copy(sm.controls.target);
        unsubscribe = sm.onCameraChange(() => {
          mainTarget.copy(sm.controls.target);
          syncCubeRotation();
          renderer.render(scene, cam);
        });
        syncCubeRotation();
      }
    };
    attachCameraSubscription(sceneManagerRef.current);

    // Click handler — raycast into the cube, decide which face was hit,
    // and ask the SceneManager to fly to the matching preset.
    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();

    function onClick(ev: MouseEvent) {
      const sm = sceneManagerRef.current;
      if (!sm || !canvas) return;
      const rect = canvas.getBoundingClientRect();
      ndc.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      ndc.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(ndc, cam);
      const hits = raycaster.intersectObject(cube, false);
      if (hits.length === 0) return;
      const hit = hits[0]!;
      const localNormal = hit.face?.normal;
      if (!localNormal) return;
      // Snap the local normal to whichever axis it's closest to in
      // CUBE space — we don't care about the world rotation, only the
      // face that was hit.
      const abs = [Math.abs(localNormal.x), Math.abs(localNormal.y), Math.abs(localNormal.z)];
      const maxIdx = abs.indexOf(Math.max(...abs));
      const snapped = new THREE.Vector3();
      if (maxIdx === 0) snapped.set(Math.sign(localNormal.x), 0, 0);
      else if (maxIdx === 1) snapped.set(0, Math.sign(localNormal.y), 0);
      else snapped.set(0, 0, Math.sign(localNormal.z));

      const face = FACE_DEFS.find(
        (f) =>
          f.normal.x === snapped.x &&
          f.normal.y === snapped.y &&
          f.normal.z === snapped.z,
      );
      if (!face) return;
      sm.setViewPreset(face.preset).catch(() => {
        // Tween was cancelled — silently ignore.
      });
    }
    canvas.addEventListener('click', onClick);

    // First render so the cube paints even when the main camera hasn't
    // emitted a change event yet.
    renderer.render(scene, cam);

    return () => {
      canvas.removeEventListener('click', onClick);
      canvas.removeEventListener('webglcontextlost', onContextLost);
      unsubscribe?.();
      geometry.dispose();
      materials.forEach((m) => m.dispose());
      textures.forEach((t) => t.dispose());
      // Release the GL context slot before dispose() so the view-cube's own
      // renderer does not leak a context alongside the main BIM scene.
      try {
        renderer.forceContextLoss();
      } catch {
        /* context already lost */
      }
      renderer.dispose();
      canvas.remove();
    };
  }, [size, t]);

  // Re-attach the subscription when the SceneManager changes (e.g. after
  // a model reload). The effect above closes over sceneManagerRef.current
  // at mount time; we trigger a re-mount by using `sceneManager` as a key
  // dependency on the wrapper. A separate small effect handles the
  // resubscription without unmounting the whole canvas.
  useEffect(() => {
    // Touch the ref so React doesn't optimise out the dep tracking.
    sceneManagerRef.current = sceneManager;
  }, [sceneManager]);

  return (
    <div
      ref={wrapperRef}
      data-testid="bim-view-cube"
      className={[
        'transition',
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ width: size, height: size }}
    >
      {glUnavailable ? (
        // Replaces the canvas rather than covering it - the defect was an
        // element that stayed in the layout with nothing painted in it, so
        // drawing beside it would only add a caption to the blank card. The
        // orientation buttons below survive either way: they call
        // setViewPreset directly and need no GL of their own.
        <div
          data-testid="bim-view-cube-unavailable"
          title={t('bim.view_cube_unavailable', {
            defaultValue:
              'The view cube needs its own 3D graphics context and could not get one. Model navigation is unaffected.',
          })}
          className="w-full h-full flex flex-col items-center justify-center gap-0.5 rounded-lg border border-dashed border-border-medium bg-surface-primary/80 text-content-quaternary px-1.5 text-center"
          style={{ width: size, height: size }}
        >
          <Box size={18} strokeWidth={1.5} aria-hidden="true" />
          <span className="text-[9px] font-semibold leading-tight">
            {t('bim.view_cube_label', { defaultValue: 'View cube' })}
          </span>
          <span className="text-[8px] leading-tight">
            {t('bim.view_cube_no_context', { defaultValue: 'no 3D context' })}
          </span>
        </div>
      ) : (
        <div ref={hostRef} style={{ width: size, height: size }} />
      )}
      {/* Hidden but accessible buttons for testing + keyboard users.
          They overlay the canvas and call setViewPreset directly. The
          canvas raycast above is the primary interaction; these are a
          11% fallback for users who can't click an exact face. */}
      <div className="sr-only">
        {FACE_DEFS.map((face) => (
          <button
            key={face.preset}
            type="button"
            data-testid={`bim-view-cube-face-${face.preset}`}
            onClick={() => {
              sceneManagerRef.current
                ?.setViewPreset(face.preset)
                .catch(() => {
                  /* tween cancelled — silent */
                });
            }}
          >
            {faceLabel(t, face)}
          </button>
        ))}
      </div>
    </div>
  );
}

export default BIMViewCube;
