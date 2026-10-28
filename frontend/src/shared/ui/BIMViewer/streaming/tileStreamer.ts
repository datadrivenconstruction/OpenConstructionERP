// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Streaming geometry loader.
 *
 * Fetches a model's tile manifest, pulls each content-addressed tile
 * (IndexedDB cache first, network on a miss), parses the tiles in small
 * chunks that yield to the event loop between them, and merges them into one
 * THREE.Group ready to hand to the viewer's existing processLoadedScene().
 *
 * Versus the monolithic path this buys: a persistent, offline-capable cache
 * (immutable tiles); parallel, cache-first downloads; and a parse that no
 * longer freezes the UI in one multi-second GLTFLoader.parse block. Tiles are
 * the same trimesh-exported GLB format as the monolith and preserve glTF node
 * names, so the downstream mesh-to-element matching is unchanged.
 *
 * The whole path is optional: streamModelTiles returns null when the model
 * has no tileset, and the caller falls back to the monolithic GLB.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { GLTF } from 'three/addons/loaders/GLTFLoader.js';

import { useAuthStore } from '@/stores/useAuthStore';

import { getCachedTile, putCachedTile, tileCacheKey } from './tileCache';
import { orderTilesForStreaming, orderTilesByViewport, type CameraPose } from './tilePriority';
import type { TileInfo, TileManifest } from './tileTypes';
import { WorkerTileParser } from './workerTileParser';
import { yieldToEventLoop } from './yieldToEventLoop';

const GLB_MAGIC = 0x46546c67; // 'glTF' little-endian

function tilesBase(modelId: string): string {
  return `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/tiles`;
}

function authHeaders(): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: '*/*' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

/**
 * Extract the model id from a `/models/{id}/geometry/` URL, or null when the
 * URL is not the internal geometry endpoint (e.g. a portal URL or a blob:).
 * Streaming only engages for the internal endpoint; everything else keeps the
 * monolithic path.
 */
export function modelIdFromGeometryUrl(url: string): string | null {
  const match = url.match(/\/models\/([^/?#]+)\/geometry\b/);
  return match && match[1] ? decodeURIComponent(match[1]) : null;
}

/** Fetch the tile manifest, or null when there is no streamable tileset. */
export async function fetchTileManifest(
  modelId: string,
  signal?: AbortSignal,
): Promise<TileManifest | null> {
  try {
    const resp = await fetch(`${tilesBase(modelId)}/manifest/`, {
      headers: authHeaders(),
      signal,
    });
    if (resp.status === 204 || !resp.ok) return null;
    const data = (await resp.json()) as TileManifest;
    if (!data || !Array.isArray(data.tiles) || data.tiles.length === 0) return null;
    return data;
  } catch {
    return null;
  }
}

async function fetchTileBytes(
  modelId: string,
  hash: string,
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  const key = tileCacheKey(modelId, hash);
  const cached = await getCachedTile(key);
  if (cached) return cached;

  const resp = await fetch(`${tilesBase(modelId)}/${encodeURIComponent(hash)}/`, {
    headers: authHeaders(),
    signal,
  });
  if (!resp.ok) throw new Error(`Tile ${hash} fetch failed (HTTP ${resp.status})`);
  const buffer = await resp.arrayBuffer();
  // Content-addressed => immutable => cache forever. Store a copy so the
  // returned buffer stays usable by the caller.
  void putCachedTile(key, buffer.slice(0));
  return buffer;
}

function parseTile(loader: GLTFLoader, buffer: ArrayBuffer): Promise<THREE.Object3D | null> {
  return new Promise((resolve) => {
    if (buffer.byteLength < 12) {
      resolve(null);
      return;
    }
    const magic = new Uint32Array(buffer.slice(0, 4))[0] ?? 0;
    if (magic !== GLB_MAGIC) {
      resolve(null);
      return;
    }
    try {
      loader.parse(
        buffer,
        '',
        (gltf: GLTF) => resolve(gltf?.scene ?? null),
        () => resolve(null),
      );
    } catch {
      resolve(null);
    }
  });
}

/** Run `fn` over `items` with at most `limit` concurrent calls, order-preserving. */
async function mapPool<T, R>(
  items: T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let cursor = 0;
  const worker = async (): Promise<void> => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= items.length) return;
      out[index] = await fn(items[index] as T, index);
    }
  };
  const workers = Math.max(1, Math.min(limit, items.length));
  await Promise.all(Array.from({ length: workers }, () => worker()));
  return out;
}

export interface StreamResult {
  /** Merged geometry, ready for processLoadedScene(). */
  group: THREE.Group;
  /** Tiles that parsed successfully. */
  tileCount: number;
  /** Meshes in the merged group. */
  meshCount: number;
}

export interface StreamOptions {
  onProgress?: (fraction: number) => void;
  /**
   * Called after each tile is parsed and its meshes are added to the shared
   * group, passing that same group. Lets the caller reveal geometry
   * progressively - add the group to the scene on the first call, request a
   * render on every call - instead of waiting for the whole model. It is the
   * same group returned in StreamResult, so attaching it once is enough; it
   * simply fills in over the following calls.
   */
  onTileParsed?: (group: THREE.Group) => void;
  signal?: AbortSignal;
  /** Max concurrent tile downloads (default 6). */
  fetchConcurrency?: number;
  /**
   * Optional probe for the current camera pose in viewer-world space. When it
   * returns a pose, tiles are streamed viewport-first (nearest what the user is
   * looking at), which matters when a deep-link (clash review / element focus)
   * has already pointed the camera at a spot before the geometry finishes. When
   * it returns null - the cold-open case, where the view only fits to the model
   * after geometry arrives - the loader falls back to geometry-mass order. Read
   * once at the start of streaming.
   */
  getCameraPose?: () => CameraPose | null;
  /**
   * Parse each tile's GLB off the main thread in a Web Worker when one is
   * available, falling back to a main-thread parse per tile on any failure.
   * Defaults to on where Workers are supported. Set false to force the
   * main-thread parse (the kill switch until an on-model perf trace confirms
   * the win, and the seam the fallback tests drive).
   */
  parseOffThread?: boolean;
}

/**
 * Stream a model's tiles into one merged group. Returns null when the model
 * has no tileset (204) or nothing parsed - the caller then loads the
 * monolithic GLB.
 */
export async function streamModelTiles(
  modelId: string,
  opts: StreamOptions = {},
): Promise<StreamResult | null> {
  const manifest = await fetchTileManifest(modelId, opts.signal);
  if (!manifest) return null;

  // Order the stream. With a known camera pose (a deep-link already aimed the
  // view), go viewport-first so the region on screen fills in before the far
  // side. Otherwise stream the tiles that carry the most of the building first,
  // so the bulk of the structure shows up while the small trailing tiles arrive.
  const pose = opts.getCameraPose?.() ?? null;
  const tiles = pose
    ? orderTilesByViewport(manifest.tiles, pose)
    : orderTilesForStreaming(manifest.tiles);
  const total = tiles.length;

  const loader = new GLTFLoader();
  const group = new THREE.Group();
  group.name = 'streamed-tiles';
  let parsedTiles = 0;
  let done = 0;

  // Off-thread parse when a Worker is available: the heavy GLTFLoader.parse
  // runs in the worker and the main thread only rebuilds the (three-native)
  // toJSON payload. Any per-tile failure resolves null and we fall back to the
  // main-thread parse below, so the stream never regresses.
  const workerParser =
    opts.parseOffThread !== false && WorkerTileParser.isSupported()
      ? new WorkerTileParser()
      : null;

  try {
    // One pipelined pass with bounded concurrency: each worker downloads a tile
    // (cache-first), parses it, reparents its meshes into the shared group, and
    // reveals it via onTileParsed - so parsing starts as soon as the first bytes
    // land (not after every tile has downloaded) and the model fills in
    // progressively instead of popping in whole at the end. A tile that fails to
    // download or parse is skipped, never fatal. JS is single-threaded, so the
    // shared counters and the group mutations need no locking. A yield keeps
    // input and rendering responsive between parses.
    await mapPool(tiles, opts.fetchConcurrency ?? 6, async (tile) => {
      if (opts.signal?.aborted) return;
      let buffer: ArrayBuffer | null = null;
      try {
        buffer = await fetchTileBytes(modelId, tile.hash, opts.signal);
      } catch {
        buffer = null;
      }
      if (opts.signal?.aborted) return;
      if (buffer) {
        // Off-thread first, then the existing main-thread parse as the fallback.
        let scene: THREE.Object3D | null = null;
        if (workerParser) {
          scene = await workerParser.parse(buffer);
        }
        if (!scene) {
          scene = await parseTile(loader, buffer);
        }
        if (scene) {
          // Reparent the tile's children into the merged group (names preserved).
          for (const child of [...scene.children]) {
            group.add(child);
          }
          parsedTiles += 1;
          opts.onTileParsed?.(group);
        }
      }
      done += 1;
      opts.onProgress?.(done / total);
      await yieldToEventLoop();
    });
  } finally {
    workerParser?.dispose();
  }

  if (parsedTiles === 0) return null;
  return { group, tileCount: parsedTiles, meshCount: group.children.length };
}

export interface PrefetchProgress {
  /** Tiles handled so far (downloaded, already cached, or failed). */
  done: number;
  /** Total tiles in the manifest. */
  total: number;
  /** Tiles present in the cache after handling (downloaded or already there). */
  ok: number;
  /** Tiles that could not be fetched. */
  failed: number;
}

export interface PrefetchOptions {
  onProgress?: (progress: PrefetchProgress) => void;
  signal?: AbortSignal;
  /** Max concurrent tile downloads (default 6). */
  fetchConcurrency?: number;
}

export interface PrefetchResult {
  /** Total tiles in the manifest. */
  total: number;
  /** Tiles present in the cache after the run (downloaded or already there). */
  ok: number;
  /** Tiles that could not be fetched. */
  failed: number;
}

/**
 * Download and cache every tile of a model for offline use, WITHOUT parsing any
 * geometry. This warms the same content-addressed IndexedDB cache that
 * streamModelTiles reads, so once it resolves a later open of the model is
 * served entirely from cache and works with no network - the "take it to site"
 * story where the phone or tablet loses signal in the field.
 *
 * Returns null when the model has no streamable tileset (nothing to save). Never
 * throws for a single bad tile: a tile that will not download is counted in
 * `failed` and the rest continue, so a flaky connection still saves as much as
 * it can. When the signal aborts, in-flight and pending tiles stop being counted
 * and the partial cache stays valid (tiles are immutable), so resuming later
 * simply skips whatever already landed.
 */
export async function prefetchModelTiles(
  modelId: string,
  opts: PrefetchOptions = {},
): Promise<PrefetchResult | null> {
  const manifest = await fetchTileManifest(modelId, opts.signal);
  if (!manifest) return null;

  const tiles: TileInfo[] = manifest.tiles;
  const total = tiles.length;
  let done = 0;
  let ok = 0;
  let failed = 0;

  await mapPool(tiles, opts.fetchConcurrency ?? 6, async (tile) => {
    if (opts.signal?.aborted) return;
    let succeeded = false;
    try {
      // Cache-first: an already-saved tile resolves without a network hit, so a
      // second run over the same model is cheap and only fills the gaps.
      await fetchTileBytes(modelId, tile.hash, opts.signal);
      succeeded = true;
    } catch {
      // Fall through - counted as failed below unless we were aborted.
    }
    // Re-check after the await: a mid-flight abort (fetch rejects) is a user
    // cancellation, not a tile that is genuinely broken, so do not count it.
    if (opts.signal?.aborted) return;
    if (succeeded) ok += 1;
    else failed += 1;
    done += 1;
    opts.onProgress?.({ done, total, ok, failed });
  });

  return { total, ok, failed };
}
