// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * bimMemberGeometry - parse a single BIM model's geometry blob (GLB or
 * DAE/COLLADA) into an upright THREE.Group for the federated viewer.
 *
 * Why this exists
 * ---------------
 * The federation geometry endpoint (GET /bim-hub/models/{id}/geometry/)
 * serves whatever the converter stored - DAE by preference, GLB when the
 * newer cad2data pipeline produced one. The per-model BIM viewer has always
 * coped with both via ElementManager (which imports BOTH loaders and content-
 * negotiates). The earlier federated scene only spoke GLB, so on the common
 * DAE case GLTFLoader.parse() failed for every member and the scene came up
 * empty - which is why the federated viewer was shelved. This helper restores
 * format parity: it sniffs the bytes, tries the right loader first, falls back
 * to the other, and applies the same up-axis correction the single-model
 * viewer uses so a Z-up source is not left lying on its side.
 *
 * Kept deliberately small and free of element-matching / BatchedMesh logic:
 * the federated scene only needs to DISPLAY geometry coloured by discipline,
 * not bind meshes to element records.
 *
 * GLTFLoader is imported from ``three/examples/jsm`` (the path the scene test
 * already mocks) so existing tests keep their hold on the loader.
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { ColladaLoader } from 'three/examples/jsm/loaders/ColladaLoader.js';

/**
 * Sniff the geometry kind from the leading bytes. Mirrors the detector in
 * BIMViewer/ElementManager so the two surfaces agree on what a blob is.
 *
 *  - GLB starts with the ASCII magic ``glTF`` (0x67 0x6c 0x54 0x46).
 *  - DAE/COLLADA is XML carrying a ``<COLLADA`` root within the first 4 KiB.
 *    Accepts a namespace prefix (``<ns0:COLLADA``), which is what Python
 *    ElementTree emits when register_namespace() was not called.
 *
 * Returns ``null`` when neither signature is present (too short, or some
 * other payload), letting the caller fall back to a best-effort parse order.
 */
export function detectGeometryKind(buffer: ArrayBuffer): 'glb' | 'dae' | null {
  if (buffer.byteLength < 12) return null;
  const view = new Uint8Array(buffer);
  if (view[0] === 0x67 && view[1] === 0x6c && view[2] === 0x54 && view[3] === 0x46) {
    return 'glb';
  }
  // Decode only the head (large DAEs can be tens of MB).
  const head = new TextDecoder('utf-8', { fatal: false }).decode(
    view.subarray(0, Math.min(4096, view.byteLength)),
  );
  const stripped = head.charCodeAt(0) === 0xfeff ? head.slice(1) : head;
  if (/<(?:[\w-]+:)?COLLADA[\s>]/i.test(stripped)) return 'dae';
  return null;
}

/** Parse GLB bytes into a scene Object3D (no network). Rejects on a bad blob
 *  so the caller can try the other format. */
function parseGlbScene(buffer: ArrayBuffer): Promise<THREE.Object3D> {
  return new Promise((resolve, reject) => {
    const loader = new GLTFLoader();
    try {
      loader.parse(
        buffer,
        '',
        (gltf) => {
          if (!gltf || !gltf.scene) {
            reject(new Error('GLTFLoader returned empty result'));
            return;
          }
          resolve(gltf.scene);
        },
        (err) => reject(err instanceof Error ? err : new Error(String(err))),
      );
    } catch (err) {
      // A corrupt header can throw synchronously before any callback fires.
      reject(err instanceof Error ? err : new Error(String(err)));
    }
  });
}

/** Parse DAE/COLLADA bytes into a scene Object3D (no network). Strips a UTF-8
 *  BOM (some exports prepend one) and pre-checks for the COLLADA root so a
 *  non-COLLADA payload fails with a clear message instead of a cryptic throw
 *  from deep inside the XML walker. */
function parseDaeScene(buffer: ArrayBuffer): Promise<THREE.Object3D> {
  return new Promise((resolve, reject) => {
    try {
      let text = new TextDecoder('utf-8').decode(new Uint8Array(buffer));
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
      if (!/<(?:[\w-]+:)?COLLADA[\s>]/i.test(text.slice(0, 4096))) {
        reject(new Error('Not a COLLADA document - <COLLADA> root tag not found'));
        return;
      }
      const loader = new ColladaLoader();
      const collada = loader.parse(text, '');
      if (!collada || !collada.scene) {
        reject(new Error('ColladaLoader returned empty result'));
        return;
      }
      resolve(collada.scene);
    } catch (err) {
      reject(err instanceof Error ? err : new Error(String(err)));
    }
  });
}

/**
 * Up-axis correction, branched by loader so the model is not left upside
 * down or on its side (mirrors the single-model viewer's logic):
 *
 *  - GLB: GLTFLoader does no auto-rotation and our GLBs come from a Z-up DAE
 *    source, so always rotate -90 deg about X.
 *  - DAE: ColladaLoader reads ``<up_axis>`` and pre-rotates Z-up scenes to
 *    Y-up itself, so rotating again would flip it back. Only rotate when the
 *    bbox is taller in Z than Y (some writers omit ``<up_axis>``, leaving the
 *    loader's default and an un-rotated, lying-down model).
 */
function applyUpAxis(scene: THREE.Object3D, isGlb: boolean): void {
  if (isGlb) {
    scene.rotation.x = -Math.PI / 2;
    return;
  }
  const bbox = new THREE.Box3().setFromObject(scene);
  const sizeY = Math.max(0, bbox.max.y - bbox.min.y);
  const sizeZ = Math.max(0, bbox.max.z - bbox.min.z);
  if (Number.isFinite(sizeY) && Number.isFinite(sizeZ) && sizeZ > sizeY) {
    scene.rotation.x = -Math.PI / 2;
  }
}

/**
 * Parse a member's geometry blob (GLB or DAE) into an upright wrapper Group.
 *
 * The wrapper isolates the federated scene from loader-specific root types
 * (GLTFLoader yields a Group, ColladaLoader a Scene) and gives addMember a
 * single object to position at the federation origin offset. Tries the format
 * the bytes look like first, then the other, so a mislabelled Content-Type
 * never strands a member.
 */
export async function parseMemberGeometry(buffer: ArrayBuffer): Promise<THREE.Group> {
  if (buffer.byteLength === 0) {
    throw new Error('Geometry buffer is empty (0 bytes)');
  }
  const detected = detectGeometryKind(buffer);
  const order: Array<'glb' | 'dae'> =
    detected === 'glb'
      ? ['glb', 'dae']
      : detected === 'dae'
        ? ['dae', 'glb']
        : ['glb', 'dae'];

  const errors: string[] = [];
  for (const kind of order) {
    try {
      const scene =
        kind === 'glb' ? await parseGlbScene(buffer) : await parseDaeScene(buffer);
      applyUpAxis(scene, kind === 'glb');
      const wrapper = new THREE.Group();
      wrapper.add(scene);
      return wrapper;
    } catch (err) {
      errors.push(
        `${kind.toUpperCase()}: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }
  throw new Error(`Federated member geometry parse failed: ${errors.join(' | ')}`);
}

export default parseMemberGeometry;
