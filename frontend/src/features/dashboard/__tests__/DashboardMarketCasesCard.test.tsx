// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The market card on the dashboard: which market it leads with, what it says
 * about why, and what it hands over when the reader leaves it.
 *
 * WHY THE TILES ARE ASSERTED AND NOT THE HEADING. The card's whole claim is
 * that a reader working in one country meets that country's cases without
 * looking for them. A heading that says "Germany" over a grid of cases written
 * for anywhere would satisfy every obvious assertion and would be the exact
 * defect this card exists to fix, so every test here reads the `data-region`
 * off the tiles that were actually drawn and refuses an empty grid.
 *
 * WHY THE SOURCE IS ASSERTED WITH THE MARKET. Three things can name a market -
 * the applied pack, the language, and the nearest-market table - and only the
 * first two earn the words "your market". A card that answered Spain for a
 * Chilean reader under the title "Cases for your market" would be telling them
 * that Spanish payment law is theirs, which is worse than saying nothing. The
 * market and the sentence about it are therefore never checked apart.
 *
 * WHY THE HAND-OVER IS TESTED. Browsing markets here must not narrow the
 * catalogue the reader opens next: the chip is view state, and only the
 * explicit "All cases for ..." button writes the hub's persisted market. Both
 * halves of that are asserted, because each is invisible from the other.
 *
 * Run: npx vitest run src/features/dashboard/__tests__/DashboardMarketCasesCard.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { DashboardMarketCasesCard } from '../DashboardMarketCasesCard';
import { useDashboardLayoutStore } from '@/stores/useDashboardLayoutStore';
import { useCasesStore } from '@/features/cases/useCasesStore';
import { PLAYBOOKS } from '@/features/cases/playbooks';
import { regionDisplayName } from '@/features/cases/regions';

// The interpolating stand-in the sibling card's test uses: these assertions
// read finished sentences, and a `t` that returned the key would hide the
// difference between "your market" and "by market", which is the point here.
const { language } = vi.hoisted(() => ({ language: { tag: 'en' } }));

vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>) => {
    if (typeof opts === 'object' && opts !== null && 'defaultValue' in opts) {
      return String(opts.defaultValue).replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
        name in opts ? String(opts[name]) : `{{${name}}}`,
      );
    }
    return key;
  };
  return {
    useTranslation: () => ({ t, i18n: { language: language.tag } }),
    initReactI18next: { type: '3rdParty', init: () => {} },
  };
});

const navigateSpy = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateSpy };
});

// The transport is mocked rather than the two hooks, so the card is exercised
// through the same query keys and the same manifest shape the product serves.
const { packs } = vi.hoisted(() => ({
  packs: {
    current: { active: false } as Record<string, unknown>,
    installed: { installed: [] as Record<string, unknown>[], active_slug: null as string | null },
  },
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: vi.fn(async (url: string) => {
      if (url.includes('/partner-pack/current')) return packs.current;
      if (url.includes('/partner-pack/installed')) return packs.installed;
      return {};
    }),
    apiPut: vi.fn().mockResolvedValue({}),
    apiPost: vi.fn().mockResolvedValue({}),
  };
});

/** A pack as `/partner-pack/installed` lists it, for one country. */
function pack(slug: string, country: string, name: string) {
  return {
    slug,
    partner_name: name,
    default_locale: 'en-US',
    metadata: { country },
    branding: { powered_by_text: name },
  };
}

/** The manifest `/partner-pack/current` returns for an applied pack. */
function applied(slug: string, country: string, name: string) {
  return { active: true, manifest: pack(slug, country, name) };
}

async function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <DashboardMarketCasesCard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByTestId('dashboard-market-cases-card')).toBeTruthy());
  return view;
}

function card(): HTMLElement {
  return screen.getByTestId('dashboard-market-cases-card');
}

/** The markets of the case tiles the card actually drew. Empty is a failure
 *  every caller asserts against, never a pass. */
function tileMarkets(): string[] {
  return screen.getAllByTestId('market-case').map((el) => el.getAttribute('data-region') ?? '');
}

/** How many cases the catalogue holds for one market, read from the catalogue
 *  rather than written down, so the numbers move with the product. */
function catalogueCount(market: string): number {
  return PLAYBOOKS.filter((pb) => pb.region === market).length;
}

/** The label of the way out, built the way the card builds it: the market's
 *  name in the reader's own language, and the catalogue's own count. */
function allCasesLabel(market: string): string {
  return `All cases for ${regionDisplayName(market, language.tag)} (${catalogueCount(market)})`;
}

beforeEach(() => {
  navigateSpy.mockClear();
  language.tag = 'en';
  packs.current = { active: false };
  packs.installed = { installed: [], active_slug: null };
  useDashboardLayoutStore.setState({ order: [], hidden: [], spans: {} });
  useCasesStore.setState({ region: 'all' });
});

describe('DashboardMarketCasesCard, the market it leads with', () => {
  it('leads with the market the reader language speaks for, and draws only its cases', async () => {
    language.tag = 'de';
    await renderCard();

    expect(card().getAttribute('data-market')).toBe('DE');
    expect(card().getAttribute('data-source')).toBe('language');

    const markets = tileMarkets();
    expect(markets.length).toBeGreaterThan(0);
    expect(new Set(markets)).toEqual(new Set(['DE']));
    // The card is a window on a bigger shelf: the way out names the whole
    // count, so a reader can see there is more than the tiles show. The name
    // comes from the same helper the card uses, which is also the assertion
    // that a German reader is offered "Deutschland" and not "Germany".
    expect(regionDisplayName('DE', 'de')).not.toBe('Germany');
    expect(screen.getByRole('button', { name: allCasesLabel('DE') })).toBeTruthy();
  });

  it('lets the pack a reader applied outrank the language they read in', async () => {
    // The shape this is for: a German-speaking estimator working on a US job.
    // Switching a pack on is a plainer statement about where someone works
    // than the language their software is in.
    language.tag = 'de';
    packs.current = applied('us-texas', 'us', 'Texas');
    await renderCard();

    expect(card().getAttribute('data-market')).toBe('US');
    expect(card().getAttribute('data-source')).toBe('pack');
    expect(new Set(tileMarkets())).toEqual(new Set(['US']));
  });

  it('offers a Chilean reader the closest market without calling it theirs', async () => {
    // Chile has no cases. Spain is the closest in language, and the card is
    // allowed to open there - but the title that claims the market is not.
    language.tag = 'es-CL';
    await renderCard();

    expect(card().getAttribute('data-market')).toBe('ES');
    expect(card().getAttribute('data-source')).toBe('nearest');
    expect(screen.getByText('Cases by market')).toBeTruthy();
    expect(screen.queryByText('Cases for your market')).toBeNull();
    expect(screen.getByText('The closest market to your language')).toBeTruthy();
  });

  it('says which market a case needs a pack for, in the catalogue own words', async () => {
    // A German pack on disk and switched off is the state the strip on the
    // hub calls out, and the same sentence is used here.
    language.tag = 'de';
    packs.installed = { installed: [pack('bau-de', 'de', 'Bau DE')], active_slug: null };
    await renderCard();

    const badges = screen.getAllByTestId('market-case-pack');
    expect(badges.length).toBe(tileMarkets().length);
    expect(badges[0]?.getAttribute('data-pack-state')).toBe('install');
    expect(badges[0]?.textContent).toContain('Bau DE');
  });
});

describe('DashboardMarketCasesCard, the other markets', () => {
  it('switches the list in place and stops speaking for the market it left', async () => {
    language.tag = 'de';
    await renderCard();

    const gb = screen
      .getAllByTestId('market-chip')
      .find((el) => el.getAttribute('data-market') === 'GB');
    expect(gb).toBeTruthy();
    fireEvent.click(gb as HTMLElement);

    expect(card().getAttribute('data-market')).toBe('GB');
    expect(new Set(tileMarkets())).toEqual(new Set(['GB']));
    // "Matched to the language you use" was true of Germany and is not true of
    // Britain, so the card stops saying it rather than saying it about the
    // market the reader just pressed.
    expect(card().getAttribute('data-source')).toBe('pick');
    expect(screen.queryByText('Matched to the language you use')).toBeNull();
  });

  it('leaves the hub filter alone while the reader browses here', async () => {
    language.tag = 'de';
    await renderCard();

    const gb = screen
      .getAllByTestId('market-chip')
      .find((el) => el.getAttribute('data-market') === 'GB');
    fireEvent.click(gb as HTMLElement);

    // Pressing a chip is looking, not choosing: a reader who opens the
    // catalogue next must find all 220 cases, not the ones they glanced at.
    expect(useCasesStore.getState().region).toBe('all');
    expect(navigateSpy).not.toHaveBeenCalled();
  });

  it('hands the market over only through the link that names it', async () => {
    language.tag = 'de';
    await renderCard();

    fireEvent.click(screen.getByRole('button', { name: allCasesLabel('DE') }));

    expect(useCasesStore.getState().region).toBe('DE');
    expect(navigateSpy).toHaveBeenCalledWith('/cases');
  });

  it('shows every market with cases, the home market first', async () => {
    language.tag = 'de';
    await renderCard();

    const chips = screen.getAllByTestId('market-chip');
    const markets = chips.map((el) => el.getAttribute('data-market'));
    const withCases = new Set(PLAYBOOKS.map((pb) => pb.region).filter(Boolean));

    expect(markets[0]).toBe('DE');
    expect(new Set(markets)).toEqual(withCases);
  });
});
