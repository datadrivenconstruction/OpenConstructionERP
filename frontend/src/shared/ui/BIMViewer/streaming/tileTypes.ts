// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Types for the streaming geometry tileset served by the backend tiler
 * (GET /api/v1/bim_hub/models/{id}/tiles/manifest/). A model's monolithic GLB
 * is baked once into spatially partitioned, content-addressed sub-GLBs so the
 * viewer can stream and cache geometry instead of downloading and parsing the
 * whole building on every open. See backend/app/modules/bim_hub/tiler.py.
 */

/** One spatial tile: a small GLB addressed by the sha256 of its bytes. */
export interface TileInfo {
  /** Stable per-manifest id, e.g. "t3". */
  id: string;
  /** Content hash (immutable): the tile's URL segment and cache key. */
  hash: string;
  /** Axis-aligned bounds [minX, minY, minZ, maxX, maxY, maxZ]. */
  bbox: number[];
  /** Bounding-sphere centre [x, y, z]. */
  center: number[];
  /** Bounding-sphere radius (metres). */
  radius: number;
  /** Number of meshes packed into the tile. */
  node_count: number;
  /** Tile GLB size in bytes. */
  byte_size: number;
  /** glTF node names in the tile - the ids the viewer matches to elements. */
  nodes: string[];
}

/** The tileset manifest for one model. */
export interface TileManifest {
  tiler_version: string;
  /** Up axis of the tile GLBs ("Y" for standard glTF, as trimesh exports). */
  up_axis: string;
  /** Whole-model bounds [minX, minY, minZ, maxX, maxY, maxZ]. */
  bounds: number[];
  mesh_count: number;
  tile_count: number;
  total_bytes: number;
  tiles: TileInfo[];
  /** Fingerprint of the source geometry the tiles were baked from. */
  source_fingerprint?: string;
  model_id?: string;
}
