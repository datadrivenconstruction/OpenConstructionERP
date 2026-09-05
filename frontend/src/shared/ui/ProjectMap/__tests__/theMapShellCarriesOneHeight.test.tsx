// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The map shell must carry exactly one height utility.
//
// WHY THIS SHAPE. The defect this guards was invisible to every check we
// had, including the eye. ProjectMap emitted its own height and then
// appended the caller's ``className`` after it, so the project detail page
// went out as ``... h-full h-[32rem]``. Both names survive into the emitted
// stylesheet, and the one Tailwind wrote LAST there decides, whatever order
// they sit in on the element. ``.h-full`` lands after ``.h-[32rem]``, so the
// page asked for 32rem and got ``h-full`` against an auto-height grid
// parent. That computes to 2px, and the shell's own ``overflow-hidden``
// cropped a live 300px map canvas down to a hairline.
//
// Everything about that state looks healthy. The map mounted, MapLibre
// initialised, the canvas painted, attribution was correct, no request
// failed and no console error appeared. Two code comments asserted the
// opposite of the truth and are why it survived a long time: one claimed a
// custom className "still wins because tailwind's JIT utilities cascade
// after the default class", and the other said the fixed height was there
// "so it doesn't collapse to zero" while being defeated by the first.
//
// So this file asserts the INVARIANT on the rendered class list rather than
// the helper that currently implements it. A unit test on ``hasOwnHeight``
// would stay green if somebody changed how the shell composes its classes,
// which is exactly the edit that would put the bug back. The invariant is
// "never two heights on one element", and it is checked by counting, so it
// fails in both directions: adding a second height fails it, and dropping
// the height entirely fails it too.
//
// Run: npx vitest run src/shared/ui/ProjectMap/__tests__/theMapShellCarriesOneHeight.test.tsx

import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ProjectMap } from '../ProjectMap';

vi.mock('../streetThumbnail', () => ({ renderStreetThumbnail: vi.fn() }));

// The detail variant mounts these for real, and MapLibre's entry point does
// not survive jsdom.
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

const SITE = { lat: 52.52, lng: 13.405 };

/**
 * The height utilities on an element, counted the way the browser resolves
 * them.
 *
 * Unprefixed only. ``md:h-96`` sets a height above its breakpoint and not
 * below one, so it neither conflicts with a default nor replaces it, and
 * counting it would make the invariant lie about a class list that is fine.
 * ``min-h-`` and ``max-h-`` bound a height rather than setting one and are
 * not counted either, which is what lets the weather layout pair ``h-full``
 * with ``min-h-[20rem]`` legitimately.
 */
function heightUtilities(el: Element): string[] {
  return (el.getAttribute('class') ?? '').split(/\s+/).filter((name) => /^h-\S/.test(name));
}

function shellOf(container: HTMLElement): Element {
  const shell = container.firstElementChild;
  expect(shell, 'ProjectMap rendered nothing to hang the assertion on').not.toBeNull();
  return shell!;
}

describe('the map shell carries exactly one height', () => {
  it('honours a caller height and does not also emit its own', () => {
    // The project detail page's real class string when weather is hidden.
    const { container } = render(
      <ProjectMap variant="detail" lat={SITE.lat} lng={SITE.lng} label="Berlin" className="h-[32rem]" />,
    );

    const heights = heightUtilities(shellOf(container));
    // Counting, not membership. `toContain('h-[32rem]')` alone would pass on
    // the broken output too, because the broken output contained it.
    expect(heights).toEqual(['h-[32rem]']);
    expect(heights).not.toContain('h-full');
  });

  it('keeps its default when the caller states no height', () => {
    const { container } = render(<ProjectMap variant="detail" lat={SITE.lat} lng={SITE.lng} label="Berlin" />);

    // The other direction. A fix that simply stopped emitting a height would
    // satisfy the first case and leave every detail map with no height at all.
    expect(heightUtilities(shellOf(container))).toEqual(['h-full']);
  });

  it('does not treat a min-height as a stated height', () => {
    // The project detail page's real class string when weather is shown. The
    // caller states h-full itself here, so the default must stand down and
    // the min-h must survive untouched.
    const { container } = render(
      <ProjectMap
        variant="detail"
        lat={SITE.lat}
        lng={SITE.lng}
        label="Berlin"
        className="h-full min-h-[20rem]"
      />,
    );

    const shell = shellOf(container);
    expect(heightUtilities(shell)).toEqual(['h-full']);
    expect(shell.getAttribute('class')).toContain('min-h-[20rem]');
  });

  it('keeps a default alongside a breakpoint-only height', () => {
    // Standing the default down for `md:h-96` would leave the element with no
    // height below the breakpoint, which is a worse bug than the one being
    // fixed and an easy one to introduce while tightening the matcher.
    const { container } = render(
      <ProjectMap variant="detail" lat={SITE.lat} lng={SITE.lng} label="Berlin" className="md:h-96" />,
    );

    const shell = shellOf(container);
    expect(heightUtilities(shell)).toEqual(['h-full']);
    expect(shell.getAttribute('class')).toContain('md:h-96');
  });

  it('gives the card variant its own single height', () => {
    const { container } = render(<ProjectMap variant="card" lat={SITE.lat} lng={SITE.lng} label="Berlin" />);

    expect(heightUtilities(shellOf(container))).toEqual(['h-28']);
  });
});
