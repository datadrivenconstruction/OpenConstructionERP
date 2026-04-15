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
  /** Called when GLB loading fails (e.g. 404). */
  onError?: () => void;
}

/* ── Module-level GLB scene cache ───────────────────────────────────────── */

interface CachedScene {
  group: THREE.Group;
  /** Timestamp of last access — for potential LRU eviction. */
  accessedAt: number;
}

const sceneCache = new Map<string, CachedScene>();
const loadingPromises = new Map<string, Promise<THREE.Group>>();

/** Max cached models — evict oldest when exceeded. */
const MAX_CACHE_SIZE = 4;

function evictOldest(): void {
  if (sceneCache.size <= MAX_CACHE_SIZE) return;
  let oldestKey: string | null = null;
  let oldestTime = Infinity;
  for (const [key, entry] of sceneCache) {
    if (entry.accessedAt < oldestTime) {
      oldestTime = entry.accessedAt;
      oldestKey = key;
    }
  }
  if (oldestKey) {
    sceneCache.delete(oldestKey);
  }
}

/**
 * Load a GLB scene for a given model, returning a deep clone so each
 * preview instance can independently show/hide meshes.
 */
function loadModelScene(modelId: string): Promise<THREE.Group> {
  // Return cached clone
  const cached = sceneCache.get(modelId);
  if (cached) {
    cached.accessedAt = Date.now();
    return Promise.resolve(cached.group.clone(true));
  }

  // Deduplicate concurrent loads
  const existing = loadingPromises.get(modelId);
  if (existing) {
    return existing.then((group) => group.clone(true));
  }

  const token = useAuthStore.getState().accessToken;
  const base = `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/geometry/`;
  const params = new URLSearchParams();
  if (token) params.set('token', token);
  params.set('_t', String(Date.now()));
  const url = `${base}?${params.toString()}`;

  const promise = new Promise<THREE.Group>((resolve, reject) => {
    const loader = new GLTFLoader();
    loader.load(
      url,
      (gltf) => {
        if (!gltf?.scene) {
          reject(new Error('GLTFLoader returned empty result'));
          return;
        }
        // Store the original scene in cache
        sceneCache.set(modelId, {
          group: gltf.scene,
          accessedAt: Date.now(),
        });
        evictOldest();
        loadingPromises.delete(modelId);
        resolve(gltf.scene.clone(true));
      },
      undefined,
      (error) => {
        loadingPromises.delete(modelId);
        reject(error);
      },
    );
  });

  loadingPromises.set(modelId, promise);
  return promise;
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
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const rafRef = useRef<number>(0);
  const mountedRef = useRef(true);
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
      rendererRef.current.dispose();
      rendererRef.current = null;
    }
    sceneRef.current = null;
    cameraRef.current = null;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    loadingRef.current = true;
    errorRef.current = false;

    const canvas = canvasRef.current;
    if (!canvas || !modelId || elementIds.length === 0) return;

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
            if (el.stable_id) matchSet.add(el.stable_id);
            if (el.id) matchSet.add(el.id);
          }
        }
      } catch { /* continue with raw IDs */ }
      return matchSet;
    };

    Promise.all([loadModelScene(modelId), resolveMatchSet()])
      .then(([group, matchSet]) => {
        if (!mountedRef.current) return;

        // Traverse: show meshes matching any known ID (db uuid, stable_id, mesh_ref)
        const visibleBox = new THREE.Box3();
        let hasVisibleMesh = false;

        group.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            const isTarget = matchSet.has(child.name);
            child.visible = isTarget;
            if (isTarget) {
              child.geometry.computeBoundingBox();
              visibleBox.expandByObject(child);
              hasVisibleMesh = true;
            }
          }
        });

        // Hide parent groups that have no visible children
        group.traverse((obj) => {
          if (!(obj instanceof THREE.Mesh) && obj.children.length > 0) {
            // Keep groups visible so child meshes render
          }
        });

        scene.add(group);

        if (!hasVisibleMesh) {
          // No matching meshes found — show empty
          loadingRef.current = false;
          renderer.render(scene, camera);
          return;
        }

        // Fit camera to visible bounding box
        const center = new THREE.Vector3();
        visibleBox.getCenter(center);
        const size = new THREE.Vector3();
        visibleBox.getSize(size);

        const maxDim = Math.max(size.x, size.y, size.z);
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
          if (!mountedRef.current) return;
          controls.update();
          renderer.render(scene, camera);
          rafRef.current = requestAnimationFrame(animate);
        };
        animate();
      })
      .catch(() => {
        if (!mountedRef.current) return;
        errorRef.current = true;
        loadingRef.current = false;
        onError?.();
      });

    return () => {
      mountedRef.current = false;
      dispose();
    };
  }, [modelId, elementIds.join(','), width, height, dispose]);

  return (
    <div
      className={className}
      style={{ width, height, borderRadius: 6, overflow: 'hidden', position: 'relative' }}
    >
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        style={{ display: 'block', width, height }}
      />
    </div>
  );
}
