// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure, dependency-free mesh-format helpers.
 *
 * Split out of ``loaders.ts`` so lightweight callers (e.g. the file manager
 * upload router) can recognise a 3D mesh file by name WITHOUT importing
 * three.js and its ~nine addon loaders. ``loaders.ts`` re-exports these so
 * existing ``./loaders`` imports keep working unchanged.
 *
 * Keep this list in sync with the backend ``bim_hub/mesh_formats.py``
 * MESH_GEOMETRY_EXTENSIONS set.
 */

export type MeshFormat =
  | 'obj'
  | '3ds'
  | 'dae'
  | 'fbx'
  | 'lwo'
  | 'stl'
  | 'ply'
  | 'gltf'
  | 'glb'
  | 'usd'
  | 'usdz';

/** Every extension the mesh importer accepts, lower-case with the leading dot. */
export const MESH_IMPORT_EXTENSIONS = [
  '.obj',
  '.3ds',
  '.dae',
  '.fbx',
  '.lwo',
  '.stl',
  '.ply',
  '.gltf',
  '.glb',
  '.usd',
  '.usdz',
] as const;

/** Lower-case file extension including the dot, or '' when there is none. */
function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot >= 0 ? filename.slice(dot).toLowerCase() : '';
}

/** Resolve a filename to a supported mesh format, or null. */
export function meshFormatFromName(filename: string): MeshFormat | null {
  const ext = extensionOf(filename);
  if (!ext) return null;
  const candidate = ext.slice(1) as MeshFormat;
  return (MESH_IMPORT_EXTENSIONS as readonly string[]).includes(ext) ? candidate : null;
}

/** True when the file is one the mesh importer can handle. */
export function isMeshImportFile(filename: string): boolean {
  return meshFormatFromName(filename) !== null;
}

/* ── Source-unit plausibility ──────────────────────────────────────────────
 *
 * Mesh formats rarely record their unit, so the importer has to ask. The live
 * preview cannot answer the question: the grid rescales with the model, so a
 * millimetre model and a metre model are the same picture and only the legend
 * differs. Scale has to be checked against a fixed outside reference instead,
 * and the one available is how big buildings actually are.
 *
 * These live here rather than in the dialog so they can be tested without
 * mounting a component or pulling in three.js.
 */

/**
 * The band a real building's largest dimension falls into, in metres. Wide on
 * purpose: it has to clear a site plan at the top and a single fitting at the
 * bottom, so it fires only when the unit is off by a whole factor, which is
 * the mistake worth catching. Both bounds are inclusive.
 */
export const PLAUSIBLE_MIN_M = 0.3;
export const PLAUSIBLE_MAX_M = 500;

/** True when a model's largest dimension is not a believable building size. */
export function isImplausibleBuildingSize(maxDimM: number): boolean {
  if (!Number.isFinite(maxDimM) || maxDimM <= 0) return false;
  return maxDimM < PLAUSIBLE_MIN_M || maxDimM > PLAUSIBLE_MAX_M;
}

/**
 * Find a unit that would put the model back inside the plausible band, or null
 * when none does (which usually means the file is not a building at all).
 *
 * Generic over the unit code so this module keeps its no-dependency promise:
 * the caller supplies the candidate order and the metres-per-unit table.
 *
 * @param sourceExtent Largest dimension in the file's own numbers, unscaled.
 * @param current The unit already selected, never suggested back.
 */
export function suggestUnitForExtent<U extends string>(
  sourceExtent: number,
  current: U,
  candidates: readonly U[],
  toMetres: Readonly<Record<U, number>>,
): U | null {
  if (!Number.isFinite(sourceExtent) || sourceExtent <= 0) return null;
  for (const unit of candidates) {
    if (unit === current) continue;
    const metres = sourceExtent * toMetres[unit];
    if (metres >= PLAUSIBLE_MIN_M && metres <= PLAUSIBLE_MAX_M) return unit;
  }
  return null;
}
