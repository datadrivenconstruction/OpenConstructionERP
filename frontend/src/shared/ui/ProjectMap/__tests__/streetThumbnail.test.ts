// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The offscreen snapshot renderer.
//
// WHAT IS WORTH ASSERTING HERE. Not "it returns a string" - the caller
// already tolerates null, so a module that always failed would look fine
// from the outside and the card would quietly go back to showing terrain
// forever. What matters is the set of properties that make this safe to
// call twelve times from a list:
//
//   * exactly one GL context is alive at any moment, even transiently;
//   * the context and its container are always destroyed;
//   * a second request for the same picture renders nothing;
//   * every failure is a null and never a throw;
//   * a broken environment stops being retried after a couple of tries,
//     rather than spending the full timeout once per card.
//
// The MapLibre constructor options are asserted too, because two of them
// are silent when wrong. Without preserveDrawingBuffer the browser may
// clear the buffer after compositing and toDataURL returns a blank image
// that is still a valid data URL, so it would be cached and shown. And a
// pixelRatio left to the display would render nine times the pixels on a
// 3x screen, which is a quota failure rather than a visible one.
//
// Everything here runs against a fake map, so it proves the wiring and
// nothing about pixels. What it cannot see is a style that loads while its
// tiles do not: the map still reaches idle, still returns a valid data URL,
// and the card swaps a flat background-coloured square in over a terrain
// tile that was at least a map. That case was closed separately by driving
// this module's exact options through a real GL context and asking the map
// what it had drawn - 95 to 235 road segments and 12 to 46 building
// footprints across six cities at this zoom, against zero buildings and
// zero street names at the retired z6 - which is evidence a mocked suite
// cannot produce and should not pretend to.
//
// Run: npx vitest run src/shared/ui/ProjectMap/__tests__/streetThumbnail.test.ts

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { VECTOR_BASEMAP_STYLE_URL } from '../basemap';
import {
  effectivePixelRatio,
  renderStreetThumbnail,
  resetStreetThumbnailCache,
  thumbnailCacheKey,
} from '../streetThumbnail';

/** Long enough to clear the module's "did we get real pixels" floor. */
const FAKE_PNG = `data:image/png;base64,${'A'.repeat(240)}`;

type Handler = () => void;

/**
 * Stand-in for maplibregl.Map.
 *
 * Counts concurrent instances rather than total ones. Twelve contexts
 * opened and closed within a single tick is still twelve contexts, and a
 * browser that caps them drops the excess without saying so, so the
 * serialisation claim has to be measured as a high-water mark.
 */
class FakeMap {
  static live = 0;
  static peakLive = 0;
  static built: Record<string, any>[] = [];
  /** Counted before the failure branch, so a refused context still shows. */
  static attempts = 0;
  /** Whether the container was in the document when MapLibre got it. */
  static containerWasConnected: boolean[] = [];
  /** When set, the constructor throws - the no-WebGL shape. */
  static failToConstruct = false;
  /** When set, the map never reaches idle. */
  static neverIdle = false;
  static canvasDataUrl: string = FAKE_PNG;

  static reset() {
    FakeMap.live = 0;
    FakeMap.peakLive = 0;
    FakeMap.built = [];
    FakeMap.attempts = 0;
    FakeMap.containerWasConnected = [];
    FakeMap.failToConstruct = false;
    FakeMap.neverIdle = false;
    FakeMap.canvasDataUrl = FAKE_PNG;
  }

  private handlers = new Map<string, Set<Handler>>();
  removed = false;

  constructor(options: Record<string, any>) {
    FakeMap.attempts += 1;
    if (FakeMap.failToConstruct) throw new Error('WebGL context could not be created');
    FakeMap.built.push(options);
    FakeMap.containerWasConnected.push(
      Boolean((options.container as HTMLElement | undefined)?.isConnected),
    );
    FakeMap.live += 1;
    FakeMap.peakLive = Math.max(FakeMap.peakLive, FakeMap.live);
    if (!FakeMap.neverIdle) {
      setTimeout(() => this.emit('idle'), 0);
    }
  }

  on(event: string, fn: Handler) {
    const set = this.handlers.get(event) ?? new Set<Handler>();
    set.add(fn);
    this.handlers.set(event, set);
  }

  off(event: string, fn: Handler) {
    this.handlers.get(event)?.delete(fn);
  }

  emit(event: string) {
    for (const fn of [...(this.handlers.get(event) ?? [])]) fn();
  }

  getCanvas() {
    return { toDataURL: () => FakeMap.canvasDataUrl } as unknown as HTMLCanvasElement;
  }

  remove() {
    if (this.removed) return;
    this.removed = true;
    FakeMap.live -= 1;
  }
}

vi.mock('maplibre-gl', () => ({
  default: { Map: FakeMap },
  Map: FakeMap,
}));

const BASE = { zoom: 15, width: 480, height: 112 };

/**
 * The options the nth map was built with.
 *
 * A helper rather than `FakeMap.built[n]!` at every call site: with
 * noUncheckedIndexedAccess a missing entry is a compile error there and a
 * bare `!` would turn it into "cannot read property of undefined" at
 * runtime, which says nothing. This fails on the real claim instead - no
 * map was constructed at all.
 */
function builtAt(index: number): Record<string, any> {
  const opts = FakeMap.built[index];
  expect(opts, `no map was constructed at index ${index}`).toBeDefined();
  return opts as Record<string, any>;
}

beforeEach(() => {
  FakeMap.reset();
  resetStreetThumbnailCache();
});

afterEach(() => {
  resetStreetThumbnailCache();
});

describe('renderStreetThumbnail', () => {
  it('renders the vendored vector style and returns its canvas', async () => {
    const url = await renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE });

    expect(url).toBe(FAKE_PNG);
    expect(FakeMap.built).toHaveLength(1);
    const opts = builtAt(0);
    expect(opts.style).toBe(VECTOR_BASEMAP_STYLE_URL);
    expect(opts.center).toEqual([13.405, 52.52]);
    expect(opts.zoom).toBe(15);
    expect(opts.interactive).toBe(false);
    // The credit is drawn in the DOM beside the image. A control baked
    // into the bitmap would be unreadable text and a duplicate.
    expect(opts.attributionControl).toBe(false);
  });

  it('preserves the drawing buffer, or the snapshot comes back blank', async () => {
    await renderStreetThumbnail({ lat: 48.86, lng: 2.35, ...BASE });

    // maplibre-gl 5 moved this out of the top level, and being ignored
    // there is not a guess: the same render driven twice through a real GL
    // context reported
    // ``gl.getContextAttributes().preserveDrawingBuffer`` as false when the
    // flag was passed at the top level and true when passed here.
    //
    // Both renders nonetheless produced identical pixels on that driver,
    // which is precisely why this is asserted on the options rather than on
    // the output. A test that rendered and compared images would pass with
    // the flag in the wrong place, and the failure would surface later on
    // somebody else's hardware as a blank square that is still a valid
    // data URL.
    expect(builtAt(0).canvasContextAttributes).toMatchObject({
      preserveDrawingBuffer: true,
    });
    expect(builtAt(0).preserveDrawingBuffer).toBeUndefined();
  });

  it('caps the render scale instead of following the display', async () => {
    await renderStreetThumbnail({ lat: 48.86, lng: 2.35, ...BASE });

    expect(builtAt(0).pixelRatio).toBe(effectivePixelRatio());
    expect(builtAt(0).pixelRatio).toBeLessThanOrEqual(2);
  });

  it('destroys the context and its container every time', async () => {
    const before = document.body.childElementCount;

    await renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE });

    expect(FakeMap.live).toBe(0);
    expect(document.body.childElementCount).toBe(before);
  });

  it('mounts the container in the document, because a detached one measures zero', async () => {
    // MapLibre sizes its canvas to container.clientWidth * pixelRatio. An
    // element that was never appended - or one hidden with display:none -
    // measures zero and the snapshot comes back blank however correct the
    // rest of this module is. So assert the state at the moment MapLibre
    // was handed the element, not afterwards: by then it is detached
    // either way and the assertion would hold on the broken version too.
    await renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE });

    expect(FakeMap.containerWasConnected).toEqual([true]);
    const container = builtAt(0).container as HTMLElement;
    expect(container.style.display).not.toBe('none');
    expect(container.style.visibility).not.toBe('hidden');
    expect(container.style.width).toBe('480px');
    expect(container.style.height).toBe('112px');
    expect(container.isConnected).toBe(false); // and cleaned up afterwards
  });

  it('never holds two contexts at once, even for a burst of cards', async () => {
    const cities: Array<[number, number]> = [
      [52.52, 13.405],
      [48.86, 2.35],
      [51.5, -0.13],
      [40.42, -3.7],
      [41.9, 12.5],
      [59.33, 18.07],
    ];

    const urls = await Promise.all(
      cities.map(([lat, lng]) => renderStreetThumbnail({ lat, lng, ...BASE })),
    );

    expect(urls.every((u) => u === FAKE_PNG)).toBe(true);
    expect(FakeMap.built).toHaveLength(cities.length);
    expect(FakeMap.peakLive).toBe(1);
    expect(FakeMap.live).toBe(0);
  });

  it('serves a repeat request from cache without opening a context', async () => {
    const req = { lat: 52.52, lng: 13.405, ...BASE };

    const first = await renderStreetThumbnail(req);
    const second = await renderStreetThumbnail(req);

    expect(second).toBe(first);
    expect(FakeMap.built).toHaveLength(1);
    expect(sessionStorage.getItem(`oe.streetmap.${thumbnailCacheKey(req)}`)).toBe(FAKE_PNG);
  });

  it('keys the cache on the frame, not just the point', async () => {
    await renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE });
    await renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE, zoom: 12 });
    await renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE, width: 320 });

    expect(FakeMap.built).toHaveLength(3);
  });

  it('survives storage that throws on read and on write', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('site data blocked');
    });
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });

    try {
      const url = await renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE });
      // Unreachable storage costs the cache, never the picture.
      expect(url).toBe(FAKE_PNG);
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it('returns null rather than throwing when there is no WebGL', async () => {
    FakeMap.failToConstruct = true;

    await expect(
      renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE }),
    ).resolves.toBeNull();
    expect(FakeMap.live).toBe(0);
  });

  it('returns null when the canvas hands back nothing usable', async () => {
    FakeMap.canvasDataUrl = 'data:,';

    await expect(
      renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE }),
    ).resolves.toBeNull();
    // A blank canvas must not be cached, or the card is stuck with it.
    expect(sessionStorage.length).toBe(0);
  });

  it('gives up when the map never finishes drawing', async () => {
    FakeMap.neverIdle = true;
    const controller = new AbortController();

    const pending = renderStreetThumbnail({
      lat: 52.52,
      lng: 13.405,
      ...BASE,
      signal: controller.signal,
    });
    // Abort rather than winding the 12 s timer forward: both settle
    // through the same give-up path, and this one keeps the test honest
    // about real timers, which the shared setup wraps.
    await Promise.resolve();
    controller.abort();

    await expect(pending).resolves.toBeNull();
    expect(FakeMap.live).toBe(0);
  });

  it('does not open a context for a card that was already dropped', async () => {
    const controller = new AbortController();
    controller.abort();

    await expect(
      renderStreetThumbnail({ lat: 52.52, lng: 13.405, ...BASE, signal: controller.signal }),
    ).resolves.toBeNull();
    expect(FakeMap.built).toHaveLength(0);
  });

  it('stops retrying a broken environment instead of timing out once per card', async () => {
    FakeMap.failToConstruct = true;

    for (const lng of [13.405, 2.35, -0.13, 12.5, 18.07]) {
      await expect(renderStreetThumbnail({ lat: 50, lng, ...BASE })).resolves.toBeNull();
    }

    // Two attempts, then the brake. One is too eager - a single cold-cache
    // timeout is not proof the environment cannot render.
    expect(FakeMap.attempts).toBe(2);
    FakeMap.failToConstruct = false;
    await expect(renderStreetThumbnail({ lat: 50, lng: 30, ...BASE })).resolves.toBeNull();
    expect(FakeMap.attempts).toBe(2);
  });

  it('does not count a cancelled card against the brake', async () => {
    // One filter click cancelling several queued renders must not disable
    // thumbnails for the rest of the session.
    for (let i = 0; i < 4; i += 1) {
      const controller = new AbortController();
      controller.abort();
      await renderStreetThumbnail({
        lat: 50,
        lng: i,
        ...BASE,
        signal: controller.signal,
      });
    }

    await expect(renderStreetThumbnail({ lat: 50, lng: 30, ...BASE })).resolves.toBe(FAKE_PNG);
  });
});
