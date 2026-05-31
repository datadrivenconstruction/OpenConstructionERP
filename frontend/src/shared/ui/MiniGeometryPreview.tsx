// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * MiniGeometryPreview — lightweight Three.js component that renders a small
 * auto-rotating 3D preview of specific BIM elements from a model's geometry.
 *
 * Used as a hover tooltip in the BOQ grid when a position is linked to BIM
 * elements (cad_element_ids).  Loads GLB geometry, hides all meshes except
 * those matching the given elementIds, fits the camera, and auto-rotates.
 *
 * The loaded GLB scene is cached by modelId in a module-level Map so that
 * hovering over multiple positions that share the same model does not
 * re-download the geometry file.
 */

import { useRef, useEffect, useCallback } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { ColladaLoader } from 'three/addons/loaders/ColladaLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Props ──────────────────────────────────────────────────────────────── */

export interface MiniGeometryPreviewProps {
  /** BIM model ID to load geometry from. */
  modelId: string;
  /** Element IDs (mesh names) to show; all others are hidden. */
  elementIds: string[];
  /** Container width in pixels.  Default 200. */
  width?: number;
  /** Container height in pixels.  Default 150. */
  height?: number;
  /** Extra CSS class names on the wrapper div. */
  className?: string;
  /** Called when geometry loading fails. ``reason`` carries the underlying
   *  error message (e.g. "geometry HTTP 404") for diagnostics. */
  onError?: (reason?: string) => void;
}

/* ── Module-level geometry-BYTES cache ──────────────────────────────────── */
//
// We cache the raw geometry BYTES (not a parsed THREE scene) and re-parse a
// FRESH scene per preview instance. Caching a parsed scene and handing out
// ``clone(true)`` copies SHARES materials across every instance + renderer;
// once any instance's renderer is disposed (unmount / React StrictMode
// double-invoke) the shared material's compiled WebGLProgram goes stale and
// the next render floods the console with "uniform3f: location is not from
// the associated program" and shows nothing. A fresh parse gives each
// renderer its own materials + geometry, which is what fixes the blank canvas.

const bufferCache = new Map<string, ArrayBuffer>();
const loadingBuffers = new Map<string, Promise<ArrayBuffer>>();

/** Max cached models — evict oldest (insertion order) when exceeded. */
const MAX_CACHE_SIZE = 4;

function evictOldest(): void {
  if (bufferCache.size <= MAX_CACHE_SIZE) return;
  const oldestKey = bufferCache.keys().next().value as string | undefined;
  if (oldestKey) bufferCache.delete(oldestKey);
}

/**
 * Parse a geometry ArrayBuffer into a scene, auto-detecting the format the
 * way the full {@link ElementManager} does: GLB (binary glTF, magic ``glTF``)
 * → GLTFLoader; otherwise COLLADA/DAE (XML) → ColladaLoader.
 *
 * The mini-preview previously used GLTFLoader ONLY, so any model whose
 * ``/geometry/`` endpoint serves a DAE (the GLB-preferred / DAE-fallback
 * default) rendered nothing — even though the main 3D viewer showed it.
 */
function parseGeometryScene(buffer: ArrayBuffer): Promise<THREE.Object3D> {
  const head = new Uint8Array(buffer.slice(0, 4));
  const magic = String.fromCharCode(head[0] ?? 0, head[1] ?? 0, head[2] ?? 0, head[3] ?? 0);

  if (magic === 'glTF') {
    return new Promise((resolve, reject) => {
      const loader = new GLTFLoader();
      loader.parse(
        buffer,
        '',
        (gltf) => (gltf?.scene ? resolve(gltf.scene) : reject(new Error('Empty GLB'))),
        (err) => reject(err instanceof Error ? err : new Error('GLB parse failed')),
      );
    });
  }

  // Assume COLLADA/DAE (XML). ColladaLoader.parse is synchronous.
  const text = new TextDecoder('utf-8').decode(new Uint8Array(buffer));
  const collada = new ColladaLoader().parse(text, '');
  if (collada?.scene) return Promise.resolve(collada.scene as unknown as THREE.Object3D);
  return Promise.reject(new Error('Empty DAE'));
}

/** Fetch (and cache) the raw geometry bytes for a model, deduped. */
function fetchGeometryBuffer(modelId: string): Promise<ArrayBuffer> {
  const cached = bufferCache.get(modelId);
  if (cached) return Promise.resolve(cached);

  let loadPromise = loadingBuffers.get(modelId);
  if (!loadPromise) {
    loadPromise = (async () => {
      const token = useAuthStore.getState().accessToken;
      const url =
        `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/geometry/?_t=${Date.now()}`;
      const resp = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error(`geometry HTTP ${resp.status}`);
      const buffer = await resp.arrayBuffer();
      bufferCache.set(modelId, buffer);
      evictOldest();
      return buffer;
    })();
    loadingBuffers.set(modelId, loadPromise);
    // Drop the in-flight entry once settled (so a failed load can be retried).
    loadPromise.catch(() => {}).finally(() => loadingBuffers.delete(modelId));
  }

  return loadPromise;
}

/**
 * Load a model's geometry as a FRESH, independent scene (GLB or DAE). Each
 * call parses its own copy so materials + geometry are never shared across the
 * separate WebGL renderers the previews spin up.
 */
async function loadModelScene(modelId: string): Promise<THREE.Group> {
  const buffer = await fetchGeometryBuffer(modelId);
  return (await parseGeometryScene(buffer)) as THREE.Group;
}

/* ── Component ──────────────────────────────────────────────────────────── */

export function MiniGeometryPreview({
  modelId,
  elementIds,
  width = 200,
  height = 150,
  className,
  onError,
}: MiniGeometryPreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const rafRef = useRef<number>(0);
  const loadingRef = useRef(true);
  const errorRef = useRef(false);

  const dispose = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    controlsRef.current?.dispose();
    controlsRef.current = null;
    if (rendererRef.current) {
      // Release the GL context slot before dispose(); many mini-previews can
      // mount per page (one per card), so a leaked context here is the fastest
      // way to exhaust the browser's WebGL context cap.
      try {
        rendererRef.current.forceContextLoss();
      } catch {
        /* context already lost */
      }
      rendererRef.current.dispose();
      rendererRef.current = null;
    }
    sceneRef.current = null;
    cameraRef.current = null;
  }, []);

  useEffect(() => {
    // Per-effect-run cancellation flag. A module-shared ref (mountedRef) was
    // wrong: StrictMode flips it back to true on remount, so the FIRST run's
    // async ``.then`` would resume and render with its already-disposed
    // renderer. A local ``let`` is captured per run.
    let cancelled = false;
    loadingRef.current = true;
    errorRef.current = false;

    const container = containerRef.current;
    if (!container || !modelId || elementIds.length === 0) return;

    // Create a FRESH <canvas> per effect run (StrictMode mounts twice). A
    // React-managed canvas ref is reused across mounts, so two renderers end
    // up on one canvas/context → "location is not from the associated
    // program" flood (and forceContextLoss on a reused canvas then nukes the
    // context entirely → "reading 'precision'" crash). An owned canvas per
    // run gives each renderer its own context, cleanly removed on teardown.
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    canvas.style.display = 'block';
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    container.appendChild(canvas);

    // --- Init Three.js ---
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
    });
    renderer.setPixelRatio(1);
    renderer.setSize(width, height);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    rendererRef.current = renderer;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf8f9fa);
    sceneRef.current = scene;

    const aspect = width / height;
    const camera = new THREE.PerspectiveCamera(45, aspect, 0.01, 100_000);
    cameraRef.current = camera;

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);
    const directional = new THREE.DirectionalLight(0xffffff, 0.8);
    directional.position.set(10, 20, 15);
    scene.add(directional);
    const backLight = new THREE.DirectionalLight(0xffffff, 0.3);
    backLight.position.set(-10, -5, -10);
    scene.add(backLight);

    // Load element data to get mesh_ref values for matching GLB nodes

    // Fetch element details (mesh_ref, stable_id) so we can match GLB node names
    const resolveMatchSet = async (): Promise<Set<string>> => {
      const matchSet = new Set(elementIds); // start with raw IDs
      try {
        const token = useAuthStore.getState().accessToken;
        const resp = await fetch(`/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/elements/by-ids/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ element_ids: elementIds }),
        });
        if (resp.ok) {
          const data = await resp.json();
          for (const el of data.items ?? []) {
            if (el.mesh_ref) matchSet.add(String(el.mesh_ref));
            if (el.stable_id) {
              matchSet.add(el.stable_id);
              // DAE nodes are named by the bare Revit ElementId, which is
              // often embedded in a compound stable_id (e.g. the "459717" in
              // "Sol:DP15:459717"). Add the numeric segments so a node named
              // "459717" still matches even when mesh_ref is absent.
              for (const seg of String(el.stable_id).split(/[^0-9]+/)) {
                if (seg.length >= 3) matchSet.add(seg);
              }
            }
            if (el.id) matchSet.add(el.id);
          }
        }
      } catch { /* continue with raw IDs */ }
      return matchSet;
    };

    Promise.all([loadModelScene(modelId), resolveMatchSet()])
      .then(([group, matchSet]) => {
        if (cancelled) return;

        // Build a lowercase version of matchSet for case-insensitive matching
        const matchSetLower = new Set<string>();
        for (const id of matchSet) matchSetLower.add(id.toLowerCase());
        const inSet = (n: string) =>
          !!n && (matchSet.has(n) || matchSetLower.has(n.toLowerCase()));

        // ── Pass 1: flag which meshes belong to the linked elements ──
        // In COLLADA/DAE the Revit ElementId (== mesh_ref) sits on an ANCESTOR
        // <node>, not the mesh itself, so we walk every ancestor's name +
        // userData ids (like the full ElementManager does).
        let meshCount = 0;
        let matchedCount = 0;
        const sampleChains: string[] = [];

        group.traverse((child) => {
          if (!(child instanceof THREE.Mesh)) return;
          meshCount++;

          const names: string[] = [];
          let cursor: THREE.Object3D | null = child;
          while (cursor && cursor !== group) {
            if (cursor.name) names.push(cursor.name);
            const ud = cursor.userData as
              | { name?: unknown; elementId?: unknown; stableId?: unknown }
              | undefined;
            if (ud?.name) names.push(String(ud.name));
            if (ud?.elementId) names.push(String(ud.elementId));
            if (ud?.stableId) names.push(String(ud.stableId));
            cursor = cursor.parent;
          }
          if (sampleChains.length < 10) sampleChains.push(names.join('  <  ') || '(unnamed mesh)');

          let isTarget = names.some(inSet);
          if (!isTarget) {
            for (const n of names) {
              const parts = n.split(/[-_:.\s]+/);
              if (parts.some((p) => p.length >= 3 && inSet(p))) {
                isTarget = true;
                break;
              }
            }
          }
          child.visible = isTarget;
          if (isTarget) matchedCount++;
        });

        scene.add(group);
        // World matrices MUST be refreshed before measuring: the loader leaves
        // them stale, and the DAE Z-UP→Y-UP correction is a rotation on the
        // root. Measuring earlier framed the wrong place → slabs off-screen
        // (visible canvas, nothing in view) even though meshes matched.
        scene.updateMatrixWorld(true);

        if (matchedCount === 0) {
          // No matching meshes — log a sample so the node-naming scheme can be
          // compared against the ids we matched on.
          // eslint-disable-next-line no-console
          console.warn(
            `[MiniGeometryPreview] no mesh matched for model ${modelId}.\n` +
              `meshes traversed: ${meshCount}\n` +
              `match ids (sample): ${Array.from(matchSet).slice(0, 12).join(', ')}\n` +
              `mesh ancestor-chains (sample):\n  ${sampleChains.join('\n  ')}`,
          );
          loadingRef.current = false;
          renderer.render(scene, camera);
          return;
        }

        // ── Pass 2: bounding box of the visible (matched) meshes, now that
        // world matrices are current ──
        const visibleBox = new THREE.Box3();
        group.traverse((child) => {
          if (child instanceof THREE.Mesh && child.visible) {
            visibleBox.expandByObject(child);
          }
        });

        if (visibleBox.isEmpty()) {
          // eslint-disable-next-line no-console
          console.warn(
            `[MiniGeometryPreview] matched ${matchedCount} mesh(es) but their ` +
              `bounding box is empty for model ${modelId} (degenerate geometry?).`,
          );
          loadingRef.current = false;
          errorRef.current = true;
          renderer.render(scene, camera);
          onError?.();
          return;
        }

        // Fit camera to visible bounding box
        const center = new THREE.Vector3();
        visibleBox.getCenter(center);
        const size = new THREE.Vector3();
        visibleBox.getSize(size);
        const maxDim = Math.max(size.x, size.y, size.z) || 1;

        const fov = camera.fov * (Math.PI / 180);
        let cameraZ = maxDim / (2 * Math.tan(fov / 2));
        cameraZ *= 1.8; // padding

        camera.position.set(
          center.x + cameraZ * 0.6,
          center.y + cameraZ * 0.4,
          center.z + cameraZ,
        );
        camera.lookAt(center);
        camera.updateProjectionMatrix();

        // OrbitControls — user can rotate, zoom, pan
        const controls = new OrbitControls(camera, canvas);
        controls.target.copy(center);
        controls.enableDamping = true;
        controls.dampingFactor = 0.12;
        controls.minDistance = maxDim * 0.2;
        controls.maxDistance = maxDim * 10;
        controls.autoRotate = true;
        controls.autoRotateSpeed = 2;
        controlsRef.current = controls;

        loadingRef.current = false;

        // Animation loop — OrbitControls drives camera
        const animate = () => {
          if (cancelled) return;
          controls.update();
          renderer.render(scene, camera);
          rafRef.current = requestAnimationFrame(animate);
        };
        animate();
      })
      .catch((err) => {
        if (cancelled) return;
        errorRef.current = true;
        loadingRef.current = false;
        const reason = err instanceof Error ? err.message : String(err);
        // eslint-disable-next-line no-console
        console.warn('[MiniGeometryPreview] geometry load failed:', err);
        onError?.(reason);
      });

    return () => {
      cancelled = true;
      dispose();
      canvas.remove();
    };
  }, [modelId, elementIds.join(','), width, height, dispose]);

  // The <canvas> is created imperatively inside the effect (one per mount) and
  // appended here, so StrictMode's double mount never shares a canvas/context.
  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width, height, borderRadius: 6, overflow: 'hidden', position: 'relative' }}
    />
  );
}
