// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Streaming tile ordering.
 *
 * The streamer downloads and reveals tiles in whatever order the manifest lists
 * them, which is spatial-octree order, not importance order. On the initial load
 * there is no meaningful camera yet (the view fits to the model only after it
 * arrives), so we cannot sort by what the user is looking at. We order by
 * geometry density instead: meshes carried per byte transferred, richest first.
 *
 * Why density and not raw geometry mass. Ranking by node_count alone maximises
 * how much of the building each *tile* carries, but a tile is only on screen
 * once it has finished downloading, so what the user actually experiences is
 * geometry per second, i.e. geometry per byte. Those are very different orders
 * on a real building, because tile payloads are wildly skewed: on the reference
 * tileset in `__fixtures__/largeTileset.ts` (25 516 meshes, 80 tiles, 204 MB)
 * they run from 1.5 KB to 17 MB. Measured on that tileset, with the streamer's
 * default concurrency of 6:
 *
 *                    bytes before      share of the model drawn after
 *                    the first tile    10 MB    50 MB    100 MB
 *   node_count desc      5.2 MB          3.9%    27.6%    47.1%
 *   density desc         1.5 KB         11.1%    40.2%    67.5%
 *
 * Density dominates at every point on the curve, which is not luck: ordering by
 * value per unit cost is the greedy optimum for "most geometry for the bytes
 * spent so far". Ranking by mass instead put ~37.9 MB of tiles in flight before
 * anything at all could appear.
 *
 * Ties fall back to geometry mass, then ground-up, then manifest order.
 *
 * NOTE that this changes how the load *looks*, not only how fast it is. Under
 * the previous mass ordering the ground-up rule broke ties often enough that a
 * building visibly rose from its base. Density ties are rare (two tiles must
 * carry the same meshes per byte), so ground-up now almost never fires and the
 * character is closer to "simple elements land first, intricate ones last".
 * That is a deliberate trade of a nice-looking assembly for a much earlier
 * first paint, and it is the thing to watch on the next on-device pass.
 *
 * Pure and deterministic (no camera, no THREE, no DOM): input tiles in, a new
 * ordered array out. The manifest already carries the per-tile node_count /
 * byte_size / center the backend tiler bakes, so this reads for free.
 */

import type { TileInfo } from './tileTypes';

/** Finite number or a fallback - guards against malformed manifest entries. */
function num(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/**
 * Vertical position of a tile in tile-local coordinates. Tiles are baked in the
 * source's Z-up frame (the viewer rotates -90 deg X on display), so the vertical
 * axis here is Z = center[2]. Lower means closer to the ground.
 */
function tileHeight(tile: TileInfo): number {
  return Array.isArray(tile.center) ? num(tile.center[2]) : 0;
}

/**
 * Meshes carried per byte of payload - how much of the building this tile buys
 * for the bandwidth it costs. Higher is better.
 *
 * A tile with geometry but no recorded size is treated as infinitely cheap
 * rather than as a division by zero, so a malformed manifest entry sorts to the
 * front (it costs nothing to try) instead of poisoning the comparator with NaN.
 */
function tileDensity(tile: TileInfo): number {
  const nodes = num(tile.node_count);
  if (nodes <= 0) return 0;
  const bytes = num(tile.byte_size);
  return bytes > 0 ? nodes / bytes : Number.POSITIVE_INFINITY;
}

/**
 * The ordering used before density: most meshes per tile first, then largest
 * payload, then ground-up, then manifest order.
 *
 * Kept exported and tested rather than deleted, because it is the alternative
 * this module's choice is measured against. `tilePriority.test.ts` asserts that
 * density beats it on both ends of the curve, so if someone later argues for
 * geometry mass they can run the comparison instead of re-deriving it. It is
 * not wired into the streamer.
 */
export function orderTilesByGeometryMass(tiles: TileInfo[]): TileInfo[] {
  return tiles
    .map((tile, index) => ({ tile, index }))
    .sort((a, b) => {
      const nodeDelta = num(b.tile.node_count) - num(a.tile.node_count);
      if (nodeDelta !== 0) return nodeDelta;
      const sizeDelta = num(b.tile.byte_size) - num(a.tile.byte_size);
      if (sizeDelta !== 0) return sizeDelta;
      const heightDelta = tileHeight(a.tile) - tileHeight(b.tile);
      if (heightDelta !== 0) return heightDelta;
      return a.index - b.index;
    })
    .map((entry) => entry.tile);
}

/**
 * Return a NEW array of the tiles ordered for streaming: densest geometry per
 * byte first, then geometry mass, then ground-up, with the original manifest
 * order as the final deterministic tie-break. Does not mutate the input.
 *
 * The superseded strategy is kept alongside as {@link orderTilesByGeometryMass}.
 */
export function orderTilesForStreaming(tiles: TileInfo[]): TileInfo[] {
  return tiles
    .map((tile, index) => ({ tile, index, density: tileDensity(tile) }))
    .sort((a, b) => {
      // 1. Most geometry per byte = the model fills in fastest per second spent.
      if (a.density !== b.density) return b.density - a.density;
      // 2. Equal value for money: prefer the tile carrying more of the building.
      const nodeDelta = num(b.tile.node_count) - num(a.tile.node_count);
      if (nodeDelta !== 0) return nodeDelta;
      // 3. Ground-up so the structure rises from its base.
      const heightDelta = tileHeight(a.tile) - tileHeight(b.tile);
      if (heightDelta !== 0) return heightDelta;
      // 4. Stable, deterministic fallback: keep the original manifest order.
      return a.index - b.index;
    })
    .map((entry) => entry.tile);
}

/** A camera pose in viewer-world space, enough to rank tiles by what the
 *  user is looking at. Positions are in metres in the viewer's Y-up frame. */
export interface CameraPose {
  /** Camera eye position [x, y, z]. */
  position: [number, number, number];
  /** Look-at / orbit target [x, y, z]. Optional; when absent only the eye
   *  distance is used. */
  target?: [number, number, number];
}

/**
 * Tile bounding-sphere centre expressed in the viewer's world frame.
 *
 * Tiles are baked in the source's Z-up frame and the viewer displays them
 * under a single -90 deg rotation about X (no translation, no scale - see the
 * streaming reveal in ElementManager). That rotation maps a source point
 * (x, y, z) to (x, z, -y), so a tile whose source centre is `center` sits at
 * [x, z, -y] on screen. We rank against that so "near the camera" means near
 * where the geometry actually appears, not where it was authored.
 *
 * Pure and allocation-light; guards malformed centres to the origin.
 */
export function tileCenterInViewerSpace(tile: TileInfo): [number, number, number] {
  const c = tile.center;
  if (!Array.isArray(c)) return [0, 0, 0];
  const x = num(c[0]);
  const y = num(c[1]);
  const z = num(c[2]);
  return [x, z, -y];
}

/** Squared distance from a tile (in viewer space) to the more relevant of the
 *  camera target or eye. Squared to avoid a sqrt in the hot ranking loop. */
function tileCameraDistanceSq(tile: TileInfo, pose: CameraPose): number {
  const [tx, ty, tz] = tileCenterInViewerSpace(tile);
  const ref = pose.target ?? pose.position;
  const dx = tx - num(ref[0]);
  const dy = ty - num(ref[1]);
  const dz = tz - num(ref[2]);
  return dx * dx + dy * dy + dz * dz;
}

/**
 * Return a NEW array of the tiles ordered by what the camera is looking at:
 * nearest to the camera target (or eye) first, so the region on screen fills
 * in before the far side of the building. This is the "viewport-priority"
 * order used once the camera is meaningfully placed - most importantly when a
 * deep-link (clash review, element focus) has already pointed the camera at a
 * specific spot while the geometry is still streaming in.
 *
 * Ties (equidistant tiles) fall back to the geometry-mass order so the meatier
 * tile of two at the same distance still wins, then to manifest order for full
 * determinism. Pure: no THREE, no camera object, no mutation of the input.
 */
export function orderTilesByViewport(tiles: TileInfo[], pose: CameraPose): TileInfo[] {
  return tiles
    .map((tile, index) => ({ tile, index, dist: tileCameraDistanceSq(tile, pose) }))
    .sort((a, b) => {
      // 1. Nearer the camera = show first (the whole point of viewport order).
      if (a.dist !== b.dist) return a.dist - b.dist;
      // 2. Equidistant: prefer the tile carrying more of the building.
      const nodeDelta = num(b.tile.node_count) - num(a.tile.node_count);
      if (nodeDelta !== 0) return nodeDelta;
      const sizeDelta = num(b.tile.byte_size) - num(a.tile.byte_size);
      if (sizeDelta !== 0) return sizeDelta;
      // 3. Stable, deterministic fallback: original manifest order.
      return a.index - b.index;
    })
    .map((entry) => entry.tile);
}
