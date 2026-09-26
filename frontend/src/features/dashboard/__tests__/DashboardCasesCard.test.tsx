// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The cases block on the dashboard: the size it comes at, the way back out of
 * it, and the one contract it used to break.
 *
 * WHY A WAY OUT IS TESTED AT ALL. The block was made several times larger on
 * purpose. A block that grows and cannot be put back is worse than the small
 * one it replaced, so the controls that shrink and hide it are part of the
 * feature, not decoration on it - and they are only worth anything if they
 * write the preference the DASHBOARD already keeps. A private flag would look
 * identical on screen and be invisible to Customize, which is where a user who
 * hid the card goes looking for it. So these assert the store, not the click.
 *
 * WHY THE COUNTS ARE TESTED. The block is two rows: eleven cases and the tile
 * that opens the rest of the library, six across on a wide screen. Two rows is
 * a joint property of the count and the column class, and neither half is
 * visible from the other, so both are asserted together. The ladder across the
 * four widths is asserted as well, because the failure a count fixed at full
 * width alone would ship is a card that GROWS when you press "smaller".
 *
 * WHY THE FACES ARE TESTED. `dealCaseFaces` documents that it must be dealt
 * over the WHOLE catalogue: the person a case wears is a property of where the
 * case sits among all cases, so a narrowed or windowed list must not re-cast
 * it. This card dealt over its own ranked window, which is exactly the thing
 * the helper warns against - the ranking reorders, so a case wore one person
 * here and a different one on the hub. The last test pins the fix with the
 * ranking deliberately reordered, because in catalogue order the bug and the
 * fix agree.
 *
 * Run: npx vitest run src/features/dashboard/__tests__/DashboardCasesCard.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { DashboardCasesCard } from '../DashboardCasesCard';
import { useDashboardLayoutStore } from '@/stores/useDashboardLayoutStore';
import { useCasesStore } from '@/features/cases/useCasesStore';
import { PLAYBOOKS } from '@/features/cases/playbooks';
import { dealCaseFaces } from '@/features/cases/caseFaces';
import { startHereVideo } from '@/features/videos/academy';
import { dashboardVideos } from '@/features/videos/DashboardVideosStrip';
import { useVideosStore } from '@/features/videos/useVideosStore';

vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>) => {
    if (typeof opts === 'object' && opts !== null && 'defaultValue' in opts) {
      const template =
        'count' in opts && opts.count !== 1 && typeof opts.defaultValue_other === 'string'
          ? opts.defaultValue_other
          : String(opts.defaultValue);
      return template.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
        name in opts ? String(opts[name]) : `{{${name}}}`,
      );
    }
    return key;
  };
  return {
    useTranslation: () => ({ t, i18n: { language: 'en' } }),
    initReactI18next: { type: '3rdParty', init: () => {} },
  };
});

const navigateSpy = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual =
    await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateSpy };
});

// The layout store PUTs its state back to the server on a debounce. Nothing
// here is about that round trip, and a request fired after the test finished
// would land in whatever ran next.
vi.mock('@/shared/lib/api', async () => {
  const actual =
    await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: vi.fn().mockResolvedValue({}),
    apiPut: vi.fn().mockResolvedValue({}),
  };
});

const WIDGET_ID = 'cases_learn';

/** The gallery grid element. */
function grid(): Element {
  const card = screen.getByTestId('dashboard-cases-card');
  const found = card.querySelector('div.grid');
  if (!found) throw new Error('gallery grid not found');
  return found;
}

/** The tiles in the gallery: the case tiles plus the one that opens the rest
 *  of the library. Counted off the grid itself rather than off `getAllByRole`,
 *  which would also collect the header's own buttons. */
function tileCount(): number {
  return grid().children.length;
}

/** Only the tiles that are a case, told apart from the "all cases" tile by the
 *  one thing that cannot be faked: the tile's title is the title of a playbook
 *  in the catalogue. `tileCount()` alone would keep passing if the last tile
 *  quietly became a twelfth case, and the count the founder asked for is a
 *  count of CASES. */
function caseTileCount(): number {
  const titles = new Set(PLAYBOOKS.map((pb) => pb.titleDefault));
  return Array.from(grid().children).filter((tile) => {
    const title = tile.getAttribute('title');
    return title !== null && titles.has(title);
  }).length;
}

function renderCard() {
  // The video half reads the active project's country through React Query.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <DashboardCasesCard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  navigateSpy.mockClear();
  useDashboardLayoutStore.setState({ order: [], hidden: [], spans: {} });
  useCasesStore.setState({ runs: {}, roles: [], companyTypes: [] });
});

describe('DashboardCasesCard size', () => {
  it('opens as two rows: 17 cases plus the way into the rest', () => {
    renderCard();

    // Seventeen cases and the "all cases" tile is eighteen cells, and eighteen
    // cells nine across is two rows. Both halves are asserted here on purpose:
    // two rows is a JOINT property of the count and the column class, so a test
    // that pinned only the count would stay green if someone dropped the `xl:`
    // column and turned the block back into three rows on a wide screen.
    expect(caseTileCount()).toBe(17);
    expect(tileCount()).toBe(18);
    expect(grid().className).toContain('xl:grid-cols-9');
  });

  it('divides evenly at every breakpoint it declares, not only the widest', () => {
    // A short last row is what "two rows" quietly turns into on the widths
    // nobody looks at. Read the column counts out of the class string the card
    // actually rendered and check the total against each one, so a future
    // breakpoint added to that string is checked by this test on the day it is
    // added rather than on the day someone notices the ragged row.
    renderCard();
    const columns = Array.from(grid().className.matchAll(/grid-cols-(\d+)/g)).map((m) =>
      Number(m[1]),
    );
    expect(columns.length).toBeGreaterThan(1);
    for (const c of columns) {
      expect({ columns: c, remainder: tileCount() % c }).toEqual({ columns: c, remainder: 0 });
    }
  });

  it('draws fewer, and fewer across, at a width the user saved earlier', () => {
    // What a reload looks like: the preference is already in the store before
    // the card mounts.
    useDashboardLayoutStore.setState({ spans: { [WIDGET_ID]: 2 } });
    renderCard();

    expect(tileCount()).toBe(8);
    // The column count has to come off the same number as the tile count: the
    // grid's breakpoints are viewport-wide, so a third-width card asking for
    // nine columns would draw nine microscopic tiles on a wide screen.
    expect(grid().className).toContain('sm:grid-cols-4');
    expect(grid().className).not.toContain('xl:grid-cols-9');
  });

  it('never shows more cases in a narrower card than in a wider one', () => {
    // The failure this guards is the one a count fixed at full width alone
    // would have shipped: press "smaller" and the block GROWS. Read off the
    // rendered card at each of the four widths the grid can draw.
    const seen: number[] = [];
    for (const span of [2, 3, 4, 6]) {
      useDashboardLayoutStore.setState({ spans: { [WIDGET_ID]: span } });
      const view = renderCard();
      seen.push(caseTileCount());
      view.unmount();
    }
    // The whole ladder, so every width is pinned here and not only in the
    // constant it is read from, and the same list sorted, so the property the
    // test is named for survives a deliberate change to the numbers.
    expect(seen).toEqual([7, 11, 11, 17]);
    expect(seen).toEqual([...seen].sort((a, b) => a - b));
  });
});

describe('DashboardCasesCard way out', () => {
  it('shrinks by writing the dashboard own width preference', () => {
    renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Show this block smaller' }));

    // The value Customize shows and persists - not a private flag of this card.
    expect(useDashboardLayoutStore.getState().spans[WIDGET_ID]).toBe(4);
    expect(tileCount()).toBe(12);
  });

  it('grows back the same way', () => {
    useDashboardLayoutStore.setState({ spans: { [WIDGET_ID]: 3 } });
    renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Show this block bigger' }));

    expect(useDashboardLayoutStore.getState().spans[WIDGET_ID]).toBe(4);
  });

  it('offers no control that would write a width the grid cannot draw', () => {
    // At full width there is nothing wider to go to, and the button for it
    // would set a span DashboardPage maps to nothing.
    const full = renderCard();
    expect(screen.queryByRole('button', { name: 'Show this block bigger' })).toBeNull();
    full.unmount();

    // And the mirror of it: at the narrowest width there is nothing narrower.
    useDashboardLayoutStore.setState({ spans: { [WIDGET_ID]: 2 } });
    renderCard();
    expect(screen.queryByRole('button', { name: 'Show this block smaller' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Show this block bigger' })).not.toBeNull();
  });

  it('hides into the dashboard own hidden set, and says where to find it again', () => {
    renderCard();
    const hide = screen.getByRole('button', {
      name: 'Hide this block. You can bring it back from Customize dashboard.',
    });
    // Named BEFORE the click: once hidden, the page stops rendering this card
    // and there is nothing left here to offer the way back.
    expect(hide.getAttribute('title')).toContain('Customize');

    fireEvent.click(hide);
    expect(useDashboardLayoutStore.getState().hidden).toContain(WIDGET_ID);
  });
});

describe('DashboardCasesCard faces', () => {
  it('gives a case the person it wears everywhere else, even when re-ranked', () => {
    // A role pushes matching cases to the front, so the gallery is no longer a
    // prefix of the catalogue. Dealt over the window, these tiles get faces
    // from their position in the WINDOW; dealt over the catalogue - which is
    // what the hub and the case page do - they keep their own.
    useCasesStore.setState({ roles: ['estimator'] });
    renderCard();

    const expected = dealCaseFaces(PLAYBOOKS);
    const byTitle = new Map(PLAYBOOKS.map((p) => [p.titleDefault, p]));

    let checked = 0;
    for (const tile of Array.from(grid().children)) {
      const img = tile.querySelector('img');
      const title = tile.getAttribute('title');
      if (!img || !title) continue;
      const pb = byTitle.get(title);
      if (!pb) continue;
      // `?.src` is the file the tile ASKS for - the country portrait for a
      // case that names a market, the pooled one otherwise. That is the right
      // half of the pair to compare here: this test is about a case wearing
      // the same person everywhere, and the country variant is part of who
      // that person is. The pooled fallback is only reached when a request
      // fails, which jsdom never makes.
      expect(img.getAttribute('src')).toBe(expected.get(pb.id)?.src);
      checked += 1;
    }
    // Without this the loop is satisfied by a gallery that rendered no faces
    // at all, and the assertion above never runs. A FLOOR, not an equality:
    // `caseFaceFor` is allowed to miss, and which cases land in the window is a
    // function of the ranking, so an equality here would fail one day for a
    // reason that has nothing to do with the faces. Scaled down with the
    // gallery when it was cut from four rows to two.
    expect(checked).toBeGreaterThan(8);
  });
});

describe('DashboardCasesCard video guides', () => {
  beforeEach(() => {
    localStorage.clear();
    useVideosStore.setState({ role: 'estimator', market: 'any', started: {}, watched: {} });
  });

  it('shows a row of video guides above the cases, Start here first, then picks for the role', async () => {
    renderCard();
    const strip = await screen.findByTestId('dashboard-videos', {}, { timeout: 30000 });
    const tiles = within(strip).getAllByTestId('dashboard-video');
    const expected = dashboardVideos({ role: 'estimator', market: null, language: 'en' }, 4);
    expect(tiles).toHaveLength(4);
    expect(expected[0]!.id).toBe(startHereVideo()!.id);
    expect(tiles.map((t) => t.getAttribute('aria-label'))).toEqual(expected.map((v) => `Play: ${v.title}`));
    expect(within(tiles[0]!).getByText('Start here')).toBeTruthy();
    // Every one plays now, and every cover comes from the video host.
    for (const v of expected) {
      expect(v.status).toBe('published');
      expect(v.cover).toMatch(/^https:\/\/i\.ytimg\.com\//);
    }
    // Both halves are labelled, and the video half comes first.
    const card = screen.getByTestId('dashboard-cases-card');
    expect(strip.compareDocumentPosition(card.querySelector('div.grid')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(strip).getByText('Video guides')).toBeTruthy();
    expect(within(card).getByText('Use cases')).toBeTruthy();
  });

  it('plays nothing on the dashboard: a tile opens the Videos page at that video', async () => {
    renderCard();
    const strip = await screen.findByTestId('dashboard-videos', {}, { timeout: 30000 });
    expect(document.querySelector('iframe')).toBeNull();
    fireEvent.click(within(strip).getAllByTestId('dashboard-video')[0]!);
    expect(navigateSpy).toHaveBeenCalledWith(`/videos?v=${startHereVideo()!.id}`);
    expect(within(strip).getByRole('link', { name: /All videos/ }).getAttribute('href')).toBe('/videos');
  });

  it('shows fewer videos in a narrower card, and keeps two on a phone', async () => {
    useDashboardLayoutStore.setState({ order: [], hidden: [], spans: { [WIDGET_ID]: 2 } });
    renderCard();
    const strip = await screen.findByTestId('dashboard-videos', {}, { timeout: 30000 });
    expect(within(strip).getAllByTestId('dashboard-video')).toHaveLength(2);
  });

});
