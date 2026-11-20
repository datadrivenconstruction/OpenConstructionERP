// Design module (ERP side of the design editor link).
/**
 * Opening view for a design model: the whole building in a 3/4 isometric view with margin. The viewer's own fit
 * keeps the vertical field of view only, so in a tall, narrow box the model filled the view as a wall seen from
 * too close. Re-framed on load and on resize until the person moves the camera.
 */
import { useCallback, useEffect, useRef } from 'react';
import * as THREE from 'three';
import type { SceneManager } from '@/shared/ui/BIMViewer/SceneManager';

/** 3/4 view: 40° round from the front, 30° above the horizon. */
const AZIMUTH = (40 * Math.PI) / 180;
const ELEVATION = (30 * Math.PI) / 180;
const MARGIN = 1.12;

export interface Pose { position: THREE.Vector3; target: THREE.Vector3; near: number; far: number }

/** Camera pose that keeps the bounding sphere of `box` inside both the vertical and horizontal field of view. */
export function isoPose(box: THREE.Box3, fovDeg: number, aspect: number, margin = MARGIN): Pose | null {
  if (box.isEmpty()) return null;
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  if (!Number.isFinite(sphere.radius) || sphere.radius <= 0) return null;
  const vHalf = (fovDeg * Math.PI) / 360;
  const hHalf = Math.atan(Math.tan(vHalf) * Math.max(aspect, 0.05));
  const dist = (sphere.radius * margin) / Math.sin(Math.min(vHalf, hHalf));
  const dir = new THREE.Vector3(
    Math.cos(ELEVATION) * Math.sin(AZIMUTH), Math.sin(ELEVATION), Math.cos(ELEVATION) * Math.cos(AZIMUTH),
  );
  return {
    position: sphere.center.clone().add(dir.multiplyScalar(dist)),
    target: sphere.center.clone(),
    near: Math.max(dist / 1000, 0.01),
    far: dist * 20,
  };
}

function contentBox(sm: SceneManager): THREE.Box3 {
  sm.scene.updateMatrixWorld(true);
  const box = new THREE.Box3();
  const tmp = new THREE.Box3();
  sm.scene.traverse((o) => {
    if (o instanceof THREE.Mesh && o.visible && o.geometry) {
      tmp.setFromObject(o);
      if (!tmp.isEmpty() && Number.isFinite(tmp.min.x)) box.union(tmp);
    }
  });
  return box;
}

export function frameIso(sm: SceneManager): boolean {
  const el = sm.renderer.domElement;
  const aspect = el.clientWidth > 0 && el.clientHeight > 0 ? el.clientWidth / el.clientHeight : sm.camera.aspect;
  const pose = isoPose(contentBox(sm), sm.camera.fov, aspect);
  if (!pose) return false;
  sm.camera.near = pose.near;
  sm.camera.far = pose.far;
  sm.camera.updateProjectionMatrix();
  sm.controls.target.copy(pose.target);
  sm.camera.position.copy(pose.position);
  sm.camera.lookAt(pose.target);
  sm.controls.update();
  sm.requestRender();
  return true;
}

/**
 * Props for a BIMViewer and a ref for the box around it. The frame runs after the viewer's own post-load fit
 * (two animation frames), again when the box changes size, and stops once the person orbits or zooms.
 */
export function useIsoFrame() {
  const sm = useRef<SceneManager | null>(null);
  const auto = useRef(true);
  const loaded = useRef(false);
  const observer = useRef<ResizeObserver | null>(null);
  const timers = useRef<number[]>([]);

  const frame = useCallback(() => {
    if (sm.current && auto.current && loaded.current) frameIso(sm.current);
  }, []);
  const later = useCallback(() => {
    requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(frame)));
    timers.current = [...timers.current.slice(-4), window.setTimeout(frame, 400)];
  }, [frame]);

  const onSceneReady = useCallback((s: SceneManager | null) => {
    sm.current = s;
    auto.current = true;
    loaded.current = false;
    if (!s) return;
    s.controls.addEventListener('start', () => { auto.current = false; });
  }, []);
  const onGeometryLoaded = useCallback(() => { auto.current = true; loaded.current = true; later(); }, [later]);
  // A callback ref: the box may mount after the first render (loading states).
  const box = useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el || typeof ResizeObserver === 'undefined') return;
    observer.current = new ResizeObserver(() => later());
    observer.current.observe(el);
  }, [later]);

  useEffect(() => () => {
    observer.current?.disconnect();
    timers.current.forEach((id) => clearTimeout(id));
  }, []);

  return { box, onSceneReady, onGeometryLoaded };
}
