// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project card's two pictures, and the credit each one owes.
//
// WHY THIS SHAPE. The failure this guards against is not a crash, it is
// silent degradation. The card used to paint a z6 shaded-relief tile - a
// country-scale terrain patch with no streets at any zoom - and it looked
// exactly like a map. The founder found that by looking at the screen,
// because nothing else could: the request was a 200, the PNG decoded, the
// pixels were the correct geography, and every check was green.
//
// A test that only asserts the happy path would go green again the moment
// the snapshot stopped being requested, because the fallback would take
// over and the card would still show an image. So this file asserts BOTH
// directions, and asserts the negative in each:
//
//   * snapshot available  -> the card shows the snapshot AND NOT the
//     relief tile, and credits OpenStreetMap AND NOT Natural Earth;
//   * snapshot unavailable -> the card shows the relief tile AND NOT a
//     rendered image, credits Natural Earth AND NOT OpenStreetMap, and
//     the snapshot was still ASKED FOR.
//
// That last clause is what makes the fallback direction more than a
// tautology. Delete the call and direction two still passes on its
// pictures; it fails on the ask.
//
// The credit halves matter independently of the picture. The vector
// snapshot is a Produced Work over ODbL data and owes its credit; the
// relief tile is public-domain Natural Earth and is credited by courtesy.
// A card that renders both credits unconditionally would satisfy every
// positive assertion here and be wrong on both surfaces, which is why
// each direction denies the other's credit.
//
// Run: npx vitest run src/shared/ui/ProjectMap/__tests__/projectCardShowsStreetsOrSaysItIsTerrain.test.tsx

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RELIEF_ATTRIBUTION, TILE_ATTRIBUTION_TEXT } from '../basemap';
import { ProjectMap } from '../ProjectMap';

// vi.hoisted rather than a plain const. The mock factory is hoisted above
// the imports and runs while ProjectMap is being loaded, so a const
// declared here would still be in its temporal dead zone when the factory
// reads it.
const { renderStreetThumbnail } = vi.hoisted(() => ({
  renderStreetThumbnail: vi.fn(),
}));

vi.mock('../streetThumbnail', () => ({ renderStreetThumbnail }));

// The card variant never mounts these, but the module imports them at the
// top and MapLibre's entry point does not survive jsdom.
vi.mock('react-map-gl/maplibre', () => ({
  default: () => null,
  Marker: () => null,
  Popup: () => null,
  NavigationControl: () => null,
  AttributionControl: () => null,
}));

vi.mock('@/features/geo-hub/api', () => ({
  geocodeSuggest: vi.fn().mockResolvedValue({ suggestions: [] }),
}));

const SNAPSHOT = `data:image/png;base64,${'A'.repeat(240)}`;

/** Berlin. Any point does; the assertions are about which image, not where. */
const SITE = { lat: 52.52, lng: 13.405 };

/** The relief fallback: one tile at the relief source's deepest zoom, z6. */
const RELIEF_TILE = /^\/api\/v1\/geo-hub\/basemap\/6\/\d+\/\d+\.png$/;

function cardImage(): HTMLImageElement {
  return screen.getByRole('img') as HTMLImageElement;
}

function creditText(): string {
  return screen.getByTestId('project-map-card-credit').textContent ?? '';
}

beforeEach(() => {
  renderStreetThumbnail.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('the project card shows streets when it can', () => {
  it('swaps the rendered snapshot in and credits the vector source', async () => {
    renderStreetThumbnail.mockResolvedValue(SNAPSHOT);

    render(<ProjectMap variant="card" lat={SITE.lat} lng={SITE.lng} label="Berlin, Germany" />);

    await waitFor(() => expect(cardImage().getAttribute('src')).toBe(SNAPSHOT));
    // Not merely "a snapshot is present": the terrain tile must be gone.
    expect(cardImage().getAttribute('src')).not.toMatch(RELIEF_TILE);

    expect(creditText()).toBe(TILE_ATTRIBUTION_TEXT);
    expect(creditText()).toContain('OpenStreetMap');
    // Crediting a source that is not in the picture is its own defect, and
    // this is the direction that would go unnoticed: the picture is right.
    expect(creditText()).not.toContain('Natural Earth');
  });

  it('asks for a zoom that frames streets rather than a region', async () => {
    renderStreetThumbnail.mockResolvedValue(SNAPSHOT);

    render(<ProjectMap variant="card" lat={SITE.lat} lng={SITE.lng} label="Berlin, Germany" />);

    await waitFor(() => expect(renderStreetThumbnail).toHaveBeenCalled());
    const call = renderStreetThumbnail.mock.calls[0];
    expect(call, 'the card never asked for a snapshot').toBeDefined();
    const req = call![0] as { lat: number; lng: number; zoom: number; width: number; height: number };
    expect(req).toMatchObject({ lat: SITE.lat, lng: SITE.lng });
    // The relief source stops at z6 and has no streets at any zoom. A
    // snapshot asked for at that zoom would be a vector picture of the
    // same country-scale nothing, which is the defect wearing the fix.
    expect(req.zoom).toBeGreaterThanOrEqual(14);
    expect(req.zoom).toBeLessThanOrEqual(17);
    // Never zero: a card that has not been laid out yet must still get a
    // real frame, or the snapshot silently never happens.
    expect(req.width).toBeGreaterThan(0);
    expect(req.height).toBeGreaterThan(0);
  });
});

describe('the project card falls back to terrain rather than to nothing', () => {
  it('keeps the relief tile and credits the relief source when no snapshot arrives', async () => {
    renderStreetThumbnail.mockResolvedValue(null);

    render(<ProjectMap variant="card" lat={SITE.lat} lng={SITE.lng} label="Berlin, Germany" />);

    // It must still have ASKED. Without this the whole file passes on a
    // card that never renders a snapshot at all, which is exactly the
    // regression being guarded.
    await waitFor(() => expect(renderStreetThumbnail).toHaveBeenCalledTimes(1));

    // A picture, not an empty box: the point of keeping the raster path.
    expect(cardImage().getAttribute('src')).toMatch(RELIEF_TILE);
    expect(cardImage().getAttribute('src')).not.toContain('data:image');

    expect(creditText()).toBe(RELIEF_ATTRIBUTION);
    expect(creditText()).toContain('Natural Earth');
    expect(creditText()).not.toContain('OpenStreetMap');
  });

  it('drops back to the relief tile if a snapshot fails to decode', async () => {
    renderStreetThumbnail.mockResolvedValue(SNAPSHOT);

    render(<ProjectMap variant="card" lat={SITE.lat} lng={SITE.lng} label="Berlin, Germany" />);
    await waitFor(() => expect(cardImage().getAttribute('src')).toBe(SNAPSHOT));

    fireEvent.error(cardImage());

    await waitFor(() => expect(cardImage().getAttribute('src')).toMatch(RELIEF_TILE));
    // And the credit follows the picture back, rather than leaving an ODbL
    // credit standing over an image with no OSM data in it.
    expect(creditText()).toBe(RELIEF_ATTRIBUTION);
  });

  it('does not ask for a snapshot on the interactive variant', async () => {
    // The detail page mounts a live map. Rendering a picture of one for it
    // would be a GL context opened for nobody.
    render(<ProjectMap variant="detail" lat={SITE.lat} lng={SITE.lng} label="Berlin, Germany" />);

    await Promise.resolve();
    expect(renderStreetThumbnail).not.toHaveBeenCalled();
  });
});

describe('the two credits are actually different statements', () => {
  it('names different sources, or neither direction above proves anything', () => {
    // Both assertions in each direction above are "contains X and not Y".
    // If the two credits ever converged on one string, every one of them
    // would still pass while saying nothing.
    expect(TILE_ATTRIBUTION_TEXT).not.toBe(RELIEF_ATTRIBUTION);
    expect(TILE_ATTRIBUTION_TEXT).toContain('OpenStreetMap');
    expect(TILE_ATTRIBUTION_TEXT).not.toContain('Natural Earth');
    expect(RELIEF_ATTRIBUTION).toContain('Natural Earth');
    expect(RELIEF_ATTRIBUTION).not.toContain('OpenStreetMap');
  });
});
