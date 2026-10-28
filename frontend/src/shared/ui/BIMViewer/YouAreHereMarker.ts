// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * A "you are here" pin for the model: a short pole with a dot on top plus a
 * flat ground ring whose radius reflects the GPS accuracy. Drawn on top of the
 * model (depth test off) so a site engineer can always spot it, even behind a
 * wall.
 *
 * This is deliberately a thin, self-contained helper: it owns exactly the three
 * meshes it creates and disposes them on hide/dispose, so it never leaks into
 * the surrounding scene graph. It draws through geometry on purpose - a locator
 * you cannot see because a slab is in front of it is useless on site.
 *
 * Known limitation: because ClipManager re-applies clipping planes across the
 * whole scene, the marker can be hidden while a section box is active. That is
 * acceptable for v1 - "locate me" is used to orient, not to section.
 */

import * as THREE from 'three';
import type { SceneManager } from './SceneManager';
import type { Vec3Like } from './geoLocate';

export interface YouAreHereOptions {
  /** Pole height in model units (defaults to a fraction of the ring radius). */
  poleHeight?: number;
  /** Pin colour (defaults to a GPS blue). */
  color?: number;
}

const DEFAULT_COLOR = 0x2563eb;

export class YouAreHereMarker {
  private readonly sceneManager: SceneManager;
  private group: THREE.Group | null = null;

  constructor(sceneManager: SceneManager) {
    this.sceneManager = sceneManager;
  }

  /** Whether a marker is currently in the scene. */
  get isVisible(): boolean {
    return this.group !== null;
  }

  /**
   * Place (or replace) the marker at a scene point. `accuracyRadius` is the GPS
   * accuracy expressed in model units; the ground ring is drawn at that radius.
   */
  show(point: Vec3Like, accuracyRadius: number, opts: YouAreHereOptions = {}): void {
    this.hide();

    const color = opts.color ?? DEFAULT_COLOR;
    const radius = Number.isFinite(accuracyRadius) && accuracyRadius > 0 ? accuracyRadius : 1;
    const poleHeight =
      Number.isFinite(opts.poleHeight ?? NaN) && (opts.poleHeight ?? 0) > 0
        ? (opts.poleHeight as number)
        : Math.max(radius * 0.5, 0.5);
    const dotRadius = Math.max(poleHeight * 0.1, radius * 0.04);

    const group = new THREE.Group();
    group.name = 'oe-you-are-here';
    // Tag so future clipping logic can opt this helper out if desired.
    group.userData.oeHelper = 'you-are-here';

    const overlay = (material: THREE.Material): THREE.Material => {
      material.depthTest = false;
      material.transparent = true;
      return material;
    };

    // Pole from the ground up to the dot.
    const poleGeom = new THREE.CylinderGeometry(dotRadius * 0.3, dotRadius * 0.3, poleHeight, 12);
    const pole = new THREE.Mesh(
      poleGeom,
      overlay(new THREE.MeshBasicMaterial({ color, opacity: 0.9 })),
    );
    pole.position.set(point.x, point.y + poleHeight / 2, point.z);
    pole.renderOrder = 9998;

    // Dot on top of the pole.
    const dotGeom = new THREE.SphereGeometry(dotRadius, 20, 16);
    const dot = new THREE.Mesh(
      dotGeom,
      overlay(new THREE.MeshBasicMaterial({ color, opacity: 1 })),
    );
    dot.position.set(point.x, point.y + poleHeight, point.z);
    dot.renderOrder = 9999;

    // Flat accuracy ring on the ground.
    const ringGeom = new THREE.RingGeometry(radius * 0.9, radius, 48);
    const ring = new THREE.Mesh(
      ringGeom,
      overlay(new THREE.MeshBasicMaterial({ color, opacity: 0.85, side: THREE.DoubleSide })),
    );
    ring.position.set(point.x, point.y + 0.01, point.z);
    ring.rotation.x = -Math.PI / 2;
    ring.renderOrder = 9997;

    // Translucent accuracy disc so the covered area reads at a glance.
    const discGeom = new THREE.CircleGeometry(radius, 48);
    const disc = new THREE.Mesh(
      discGeom,
      overlay(new THREE.MeshBasicMaterial({ color, opacity: 0.12, side: THREE.DoubleSide })),
    );
    disc.position.set(point.x, point.y + 0.005, point.z);
    disc.rotation.x = -Math.PI / 2;
    disc.renderOrder = 9996;

    group.add(pole, dot, ring, disc);
    this.sceneManager.scene.add(group);
    this.group = group;
    this.sceneManager.requestRender();
  }

  /** Remove the marker and dispose its geometries and materials. */
  hide(): void {
    if (!this.group) return;
    this.sceneManager.scene.remove(this.group);
    this.group.traverse((obj) => {
      if (obj instanceof THREE.Mesh) {
        obj.geometry.dispose();
        const mat = obj.material;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat.dispose();
      }
    });
    this.group = null;
    this.sceneManager.requestRender();
  }

  dispose(): void {
    this.hide();
  }
}
