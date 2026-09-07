// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pins our one use of Cesium clipping polygons against the CesiumJS 1.145
 * breaking change.
 *
 * CHANGES.md, 1.145 (2026-09-02), Breaking Changes, PR #13665:
 *
 *   "The positions of `ClippingPolygons` in a `ClippingPolygonCollection`
 *    are now considered immutable (via `Object.freeze`) and will throw if
 *    changed."
 *
 * The single call site is `applyCrop` in OverlayLayer.tsx: it builds a
 * fresh Cartesian3 array from the overlay's crop polygon, hands it to a
 * `ClippingPolygon`, wraps that in a `ClippingPolygonCollection` and
 * assigns the collection to the imagery layer. Nothing may touch that
 * array afterwards, from any frame.
 *
 * Two things make an unpinned regression here hard to see:
 *
 *   · `applyCrop` wraps the whole body in try/catch and degrades to a
 *     `console.warn`. Under 1.145 a mutation would not crash the map, it
 *     would silently drop the crop and leave the raster uncropped. So the
 *     assertions below check the OUTCOME (the layer carries the
 *     collection) and the absence of that warn, not merely "did not
 *     throw".
 *
 *   · The freeze is what the shipped library does, so the stub applies it
 *     at exactly the moment Cesium does, when the polygon enters a
 *     collection. Freezing earlier would be stricter than the library and
 *     would redden patterns Cesium still allows.
 *
 * The last test builds the red from outside our intention: it makes the
 * collection mutate the positions and proves the assertions above go red
 * through the real component path rather than only in a synthetic array.
 *
 * Run:  npx vitest run src/features/geo-hub/__tests__/cropPolygonPositionsAreNeverMutatedAfterConstruction.test.tsx
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

import { act, cleanup, render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { OverlayLayer } from '../OverlayLayer';
import type { CropPolygon, GeoRasterOverlay } from '../types';

const PROJECT_ID = 'p-geo';
const OVERLAY_ID = 'o-crop';
const OVERLAYS_KEY = ['geo-hub', 'raster-overlays', PROJECT_ID];

/* ── Fixtures ─────────────────────────────────────────────────────────── */

const fixtures = vi.hoisted(() => ({
  overlays: [] as unknown[],
}));

vi.mock('../api', () => ({
  geoAuthHeaders: () => ({ Authorization: 'Bearer test-token' }),
  listAnchors: vi.fn(async () => []),
  listRasterOverlays: vi.fn(async () => fixtures.overlays),
  rasterOverlayImageUrl: (id: string) => `https://example.test/overlays/${id}/raster.png`,
  updateRasterOverlay: vi.fn(async () => ({})),
}));

function makeCropPolygon(offset: number): CropPolygon {
  return {
    type: 'Polygon',
    coordinates: [
      [
        [13.40 + offset, 52.51],
        [13.41 + offset, 52.51],
        [13.41 + offset, 52.52],
        [13.40 + offset, 52.51],
      ],
    ],
  };
}

function makeOverlay(crop: CropPolygon): GeoRasterOverlay {
  return {
    id: OVERLAY_ID,
    project_id: PROJECT_ID,
    name: 'site plan',
    source_kind: 'pdf',
    source_blob_url: null,
    source_page: 1,
    raster_blob_url: 'https://example.test/raster.png',
    raster_width_px: 1000,
    raster_height_px: 800,
    // Four distinct corners spanning 0.01 deg, comfortably above the
    // degenerate-bbox floor so the layer is really created.
    corners_geojson: [
      [13.40, 52.52],
      [13.41, 52.52],
      [13.41, 52.51],
      [13.40, 52.51],
    ],
    rotation_deg: '0',
    opacity: '1',
    crop_polygon_geojson: crop,
    z_order: 0,
    visible: true,
    created_by: null,
    metadata: {},
    created_at: '',
    updated_at: '',
  } as GeoRasterOverlay;
}

/* ── Cesium stub carrying the 1.145 rule ──────────────────────────────── */

interface StubHarness {
  /** Every positions array a ClippingPolygon was constructed with. */
  handedOver: any[][];
  /** Every ClippingPolygonCollection the component built. */
  collections: any[];
  /** Every ImageryLayer the component added. */
  layers: any[];
  /** Set by the last test to make the collection misbehave. */
  mutateOnAdd: boolean;
}

function makeCesiumStub(harness: StubHarness) {
  function ClippingPolygon(this: any, opts: { positions: any[] }) {
    this.positions = opts.positions;
    harness.handedOver.push(opts.positions);
  }

  function ClippingPolygonCollection(this: any, opts: { polygons: any[] }) {
    this.polygons = opts.polygons ?? [];
    for (const p of this.polygons) {
      // The 1.145 rule, applied where the library applies it.
      Object.freeze(p.positions);
      if (harness.mutateOnAdd) {
        // What a caller would be doing wrong: normalising the ring in
        // place after handing it over. Freezing first is what makes this
        // a TypeError rather than a quiet edit, and that TypeError is the
        // whole behaviour this file exists to catch.
        p.positions.push(p.positions[0]);
      }
    }
    harness.collections.push(this);
  }

  function Resource(this: any, opts: { url?: string; headers?: unknown }) {
    this.url = opts?.url;
    this.headers = opts?.headers;
  }

  function SingleTileImageryProvider(this: any, opts: Record<string, unknown>) {
    Object.assign(this, opts);
  }

  return {
    Rectangle: {
      fromDegrees: (west: number, south: number, east: number, north: number) => ({
        west,
        south,
        east,
        north,
      }),
    },
    Cartesian3: {
      // A fresh array every call, exactly like the real one. If production
      // ever starts caching or reusing this array the identity assertions
      // below stop holding.
      fromDegreesArray: (flat: number[]) => {
        const out: any[] = [];
        for (let i = 0; i < flat.length; i += 2) {
          out.push({ x: flat[i], y: flat[i + 1], z: 0 });
        }
        return out;
      },
    },
    ClippingPolygon,
    ClippingPolygonCollection,
    Resource,
    SingleTileImageryProvider,
    Color: { ORANGE: {}, fromCssColorString: () => ({}) },
    Math: { toDegrees: (r: number) => (r * 180) / Math.PI },
    Cartographic: { fromCartesian: () => ({ longitude: 0, latitude: 0 }) },
    ScreenSpaceEventType: { LEFT_CLICK: 0, LEFT_DOWN: 1, LEFT_UP: 2, MOUSE_MOVE: 3 },
    ScreenSpaceEventHandler: function (this: any) {
      this.setInputAction = () => {};
      this.removeInputAction = () => {};
      this.destroy = () => {};
    },
  };
}

function makeViewerStub(harness: StubHarness) {
  const imageryLayers = {
    addImageryProvider: (provider: unknown) => {
      const layer: any = { provider, alpha: 1 };
      harness.layers.push(layer);
      return layer;
    },
    remove: (layer: any) => {
      const at = harness.layers.indexOf(layer);
      if (at >= 0) harness.layers.splice(at, 1);
    },
  };
  return {
    scene: { imageryLayers, canvas: document.createElement('canvas'), globe: {} },
    imageryLayers,
    entities: { add: () => ({}), remove: () => {} },
    camera: { getPickRay: () => null },
  };
}

/* ── Harness ──────────────────────────────────────────────────────────── */

let harness: StubHarness;
let warn: any;
let queryClient: QueryClient;

function renderLayer() {
  const cesium = makeCesiumStub(harness);
  const viewer = makeViewerStub(harness);
  return render(
    <QueryClientProvider client={queryClient}>
      <OverlayLayer
        projectId={PROJECT_ID}
        cesium={cesium}
        viewer={viewer}
        activeOverlayId={null}
        editMode="idle"
        onSelectOverlay={() => {}}
        onChangeEditMode={() => {}}
      />
    </QueryClientProvider>,
  );
}

/** Every warn argument list flattened to one string, for substring checks. */
function warnedLines(): string[] {
  return warn.mock.calls.map((args: unknown[]) => args.map(String).join(' '));
}

function clipWarnings(): string[] {
  return warnedLines().filter((line) => line.includes('crop polygon clip failed'));
}

beforeEach(() => {
  harness = { handedOver: [], collections: [], layers: [], mutateOnAdd: false };
  fixtures.overlays = [makeOverlay(makeCropPolygon(0))];
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  queryClient.clear();
  warn.mockRestore();
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe('crop polygon positions under the Cesium 1.145 freeze', () => {
  it('applies the crop and leaves the frozen positions untouched for the layer lifetime', async () => {
    renderLayer();

    await waitFor(() => expect(harness.collections).toHaveLength(1));

    // The crop really landed. Under a frozen-positions violation this is
    // where the silent degradation would show: applyCrop catches, warns,
    // and never reaches the assignment.
    expect(harness.layers).toHaveLength(1);
    expect(harness.layers[0].clippingPolygons).toBe(harness.collections[0]);
    expect(clipWarnings()).toEqual([]);

    // The stub applied the 1.145 rule to the array production handed over.
    const positions = harness.handedOver[0]!;
    expect(harness.collections[0].polygons[0].positions).toBe(positions);
    expect(Object.isFrozen(positions)).toBe(true);

    // Four ring vertices in, four Cartesian3 out, in ring order.
    expect(positions).toHaveLength(4);
    const snapshot = positions.map((p: any) => `${p.x},${p.y}`);
    expect(snapshot[0]).toBe('13.4,52.51');

    // Drive the re-render that swaps the crop. layerSignature includes the
    // crop, so the old layer is removed and a second collection is built.
    // A caller that recycled the first array instead of allocating a new
    // one would throw here, and applyCrop would swallow it into a warn.
    act(() => {
      queryClient.setQueryData(OVERLAYS_KEY, [makeOverlay(makeCropPolygon(1))]);
    });
    await waitFor(() => expect(harness.collections).toHaveLength(2));

    expect(clipWarnings()).toEqual([]);
    expect(harness.layers).toHaveLength(1);
    expect(harness.layers[0].clippingPolygons).toBe(harness.collections[1]);

    // Fresh allocation, not the frozen one handed over the first time.
    expect(harness.handedOver[1]).not.toBe(positions);

    // And the first array is byte for byte what it was, so nothing
    // anywhere reached back into it between the two renders.
    expect(positions.map((p: any) => `${p.x},${p.y}`)).toEqual(snapshot);
  });

  it('leaves the frozen positions intact through unmount', async () => {
    const view = renderLayer();
    await waitFor(() => expect(harness.collections).toHaveLength(1));

    const positions = harness.handedOver[0]!;
    const snapshot = positions.map((p: any) => `${p.x},${p.y}`);

    view.unmount();

    expect(clipWarnings()).toEqual([]);
    expect(positions.map((p: any) => `${p.x},${p.y}`)).toEqual(snapshot);
    expect(positions).toHaveLength(4);
  });

  it('goes red when the positions are mutated after they were handed over', async () => {
    // The control. Without it a green run above proves only that the test
    // ran, not that it can refuse anything: applyCrop swallows throws, so
    // the guard has to be shown reddening through the real component path.
    harness.mutateOnAdd = true;
    renderLayer();

    await waitFor(() => expect(clipWarnings()).toHaveLength(1));

    // This is the shape the 1.145 regression takes in production: a warn
    // on the console, no crop on the layer, and a raster that quietly
    // renders uncropped.
    expect(harness.layers).toHaveLength(1);
    expect(harness.layers[0].clippingPolygons).toBeUndefined();
    expect(clipWarnings()[0]).toContain('[geo_hub] crop polygon clip failed');
  });
});
