import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import { isoPose } from './frameView';

const building = new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(34, 15, 12));

/** Every corner of the box projects inside the view with the given camera. */
function allInside(box: THREE.Box3, fov: number, aspect: number): boolean {
  const pose = isoPose(box, fov, aspect)!;
  const cam = new THREE.PerspectiveCamera(fov, aspect, pose.near, pose.far);
  cam.position.copy(pose.position);
  cam.lookAt(pose.target);
  cam.updateMatrixWorld(true);
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
    const p = new THREE.Vector3(x, y, z).project(cam);
    if (Math.abs(p.x) > 0.95 || Math.abs(p.y) > 0.95) return false;
  }
  return true;
}

describe('isoPose', () => {
  it('keeps the whole building in view with margin, wide and tall boxes alike', () => {
    expect(allInside(building, 45, 16 / 9)).toBe(true);
    expect(allInside(building, 45, 0.6)).toBe(true);
  });

  it('looks from above and from a 3/4 side, at the centre', () => {
    const pose = isoPose(building, 45, 1)!;
    const c = building.getCenter(new THREE.Vector3());
    expect(pose.target.distanceTo(c)).toBeLessThan(1e-9);
    const d = pose.position.clone().sub(c);
    expect(d.y).toBeGreaterThan(0);
    expect(d.x).toBeGreaterThan(0);
    expect(d.z).toBeGreaterThan(0);
    expect(pose.far).toBeGreaterThan(pose.position.distanceTo(c));
  });

  it('gives nothing for an empty scene', () => {
    expect(isoPose(new THREE.Box3(), 45, 1)).toBeNull();
  });
});
