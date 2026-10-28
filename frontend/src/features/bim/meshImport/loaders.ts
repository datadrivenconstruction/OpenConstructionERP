// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Mesh-format loader registry for the in-app 3D geometry import.
 *
 * Maps a file extension to the matching Three.js addon loader and returns a
 * plain ``THREE.Object3D`` regardless of the source format. Everything runs in
 * the browser - no backend conversion, no extra dependency (three@0.184 already
 * ships every loader used here).
 *
 * Fully wired: glTF, GLB, OBJ, DAE/Collada, 3DS, FBX, LWO, STL, PLY.
 * Best-effort: USD / USDZ (parsed with USDLoader inside a try/catch; a failure
 * surfaces a friendly note instead of crashing the import).
 */

import * as THREE from 'three';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { TDSLoader } from 'three/addons/loaders/TDSLoader.js';
import { ColladaLoader } from 'three/addons/loaders/ColladaLoader.js';
import { FBXLoader } from 'three/addons/loaders/FBXLoader.js';
import { LWOLoader } from 'three/addons/loaders/LWOLoader.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { PLYLoader } from 'three/addons/loaders/PLYLoader.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { USDLoader } from 'three/addons/loaders/USDLoader.js';
import type { UpAxis } from './geometry';
import { MESH_IMPORT_EXTENSIONS, isMeshImportFile, meshFormatFromName, type MeshFormat } from './formats';

// Re-export the pure format helpers so existing ``./loaders`` imports keep
// working. The name-only classification lives in ``formats.ts`` (no three.js)
// so lightweight callers can import it without pulling the loader graph.
export { MESH_IMPORT_EXTENSIONS, isMeshImportFile, meshFormatFromName };
export type { MeshFormat };

/** Formats parsed only experimentally (may fail on complex files). */
const EXPERIMENTAL_FORMATS: ReadonlySet<MeshFormat> = new Set<MeshFormat>(['usd', 'usdz']);

/** Supported unit codes and their conversion factor to metres. */
export type UnitCode = 'mm' | 'cm' | 'm' | 'in' | 'ft';

export const UNIT_TO_METERS: Record<UnitCode, number> = {
  mm: 0.001,
  cm: 0.01,
  m: 1,
  in: 0.0254,
  ft: 0.3048,
};

export const UNIT_CODES: readonly UnitCode[] = ['mm', 'cm', 'm', 'in', 'ft'];

export interface LoadResult {
  /** The loaded scene/object tree in the loader's native coordinates. */
  object: THREE.Object3D;
  format: MeshFormat;
  /** True for formats we support only experimentally (USD / USDZ). */
  experimental: boolean;
}

/**
 * Sensible default source unit per format. glTF/GLB are defined in metres by
 * the spec; the others carry no reliable unit, so we default to millimetres
 * (common for CAD / 3D-print exports) and let the user confirm or change it.
 */
export function defaultUnitFor(format: MeshFormat): UnitCode {
  return format === 'gltf' || format === 'glb' ? 'm' : 'mm';
}

/**
 * Sensible default up-axis per format. glTF, OBJ, DAE (ColladaLoader
 * pre-rotates to Y-up), FBX and USD are conventionally Y-up; STL, PLY and 3DS
 * coming out of CAD are usually Z-up. The user can override.
 */
export function defaultUpAxisFor(format: MeshFormat): UpAxis {
  return format === 'stl' || format === 'ply' || format === '3ds' ? 'z' : 'y';
}

function asError(err: unknown): Error {
  if (err instanceof Error) return err;
  return new Error(typeof err === 'string' ? err : 'Unknown parsing error');
}

/** Parse glTF/GLB data and return its scene. parseAsync rejects on error,
 *  which the caller's try/catch turns into a friendly message. */
async function parseGltf(data: ArrayBuffer | string): Promise<THREE.Object3D> {
  const gltf = await new GLTFLoader().parseAsync(data, '');
  return gltf.scene;
}

/** Wrap a bare BufferGeometry (STL / PLY) into a Mesh so the rest of the
 *  pipeline can treat every format uniformly. */
function wrapGeometry(geometry: THREE.BufferGeometry): THREE.Object3D {
  if (!geometry.getAttribute('normal')) {
    try {
      geometry.computeVertexNormals();
    } catch {
      // Normals are only needed for shading, not for measurement - ignore.
    }
  }
  const material = new THREE.MeshStandardMaterial({
    color: 0x9ca3af,
    side: THREE.DoubleSide,
    flatShading: true,
  });
  return new THREE.Mesh(geometry, material);
}

/**
 * Load a mesh file entirely in the browser and return its object tree.
 *
 * Throws an ``Error`` with a human-readable message on failure (the dialog
 * shows it verbatim). USD failures are labelled experimental rather than fatal.
 */
export async function loadMeshFile(file: File): Promise<LoadResult> {
  const format = meshFormatFromName(file.name);
  if (!format) {
    throw new Error(`Unsupported mesh format: ${file.name}`);
  }
  const experimental = EXPERIMENTAL_FORMATS.has(format);

  try {
    switch (format) {
      case 'obj': {
        const text = await file.text();
        return { object: new OBJLoader().parse(text), format, experimental };
      }
      case 'dae': {
        const text = await file.text();
        const collada = new ColladaLoader().parse(text, '');
        if (!collada || !collada.scene) {
          throw new Error('The COLLADA file contained no scene.');
        }
        return { object: collada.scene, format, experimental };
      }
      case 'gltf': {
        const text = await file.text();
        return { object: await parseGltf(text), format, experimental };
      }
      case 'glb': {
        const buffer = await file.arrayBuffer();
        return { object: await parseGltf(buffer), format, experimental };
      }
      case 'fbx': {
        const buffer = await file.arrayBuffer();
        return { object: new FBXLoader().parse(buffer, ''), format, experimental };
      }
      case 'lwo': {
        // LWOLoader returns { meshes, materials } rather than a scene, so wrap
        // the parsed meshes in a Group to match the shape the pipeline expects.
        const buffer = await file.arrayBuffer();
        const { meshes } = new LWOLoader().parse(buffer, '', '');
        if (!meshes || meshes.length === 0) {
          throw new Error('The LWO file contained no meshes.');
        }
        const group = new THREE.Group();
        for (const mesh of meshes) group.add(mesh);
        return { object: group, format, experimental };
      }
      case '3ds': {
        const buffer = await file.arrayBuffer();
        return { object: new TDSLoader().parse(buffer, ''), format, experimental };
      }
      case 'stl': {
        const buffer = await file.arrayBuffer();
        return { object: wrapGeometry(new STLLoader().parse(buffer)), format, experimental };
      }
      case 'ply': {
        const buffer = await file.arrayBuffer();
        return { object: wrapGeometry(new PLYLoader().parse(buffer)), format, experimental };
      }
      case 'usd':
      case 'usdz': {
        // USD is experimental: parse defensively and surface a clear note
        // rather than letting a parser exception escape.
        const buffer = await file.arrayBuffer();
        const object = new USDLoader().parse(buffer);
        return { object, format, experimental };
      }
    }
  } catch (err) {
    const base = asError(err).message;
    if (experimental) {
      throw new Error(`USD is experimental and this file could not be parsed. ${base}`);
    }
    throw new Error(`Could not parse ${format.toUpperCase()} file. ${base}`);
  }
}
