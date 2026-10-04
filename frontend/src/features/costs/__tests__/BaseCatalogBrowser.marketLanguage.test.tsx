// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A national base's market card promises a market and a language. On a surface
// that cannot run the market load it used to fall back to a plain Load button
// that installed the home base in the home language (a French card on the
// Turkish base loaded Turkish). These tests pin that such a card is not offered
// there, that it is offered where the market load is wired, and that a card
// whose language no published file holds says which language it really loads.

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { BaseCatalogBrowser } from '../BaseCatalogBrowser';

function variant(over = {}) {
  return {
    region: 'TR_NATIONAL',
    variant_id: 'TR_NATIONAL',
    base_region: 'TR_NATIONAL',
    market_catalog: '',
    active: false,
    market: 'Turkiye',
    city: 'National',
    language: 'Turkce',
    lang_code: 'tr',
    text_lang_code: 'tr',
    currency: 'TRY',
    flag: 'tr',
    positions: 22494,
    bundled: true,
    coefficient: false,
    loaded: false,
    loaded_positions: 0,
    ...over,
  };
}

const HOME = variant();
const PARIS = variant({
  variant_id: 'TR_NATIONAL:FR_PARIS_fr',
  market_catalog: 'FR_PARIS_fr',
  market: 'France',
  city: 'Paris',
  language: 'Francais',
  lang_code: 'fr',
  text_lang_code: 'fr',
  currency: 'EUR',
  flag: 'fr',
});
const LONDON = variant({
  variant_id: 'TR_NATIONAL:GB_LONDON_en',
  market_catalog: 'GB_LONDON_en',
  market: 'United Kingdom',
  city: 'London',
  language: 'English',
  lang_code: 'en',
  text_lang_code: 'tr',
  currency: 'GBP',
  flag: 'gb',
});

// Keyed "china" so the family starts expanded.
const CATALOG = {
  repo: 'x',
  total_bases: 3,
  total_families: 1,
  loaded_regions: [],
  families: [
    {
      key: 'china',
      name: 'Turkiye (Birim Fiyat)',
      norm_system: 'Birim Fiyat',
      origin: 'Turkiye',
      origin_flag: 'tr',
      description: '',
      market_count: 3,
      repriceable_markets: 49,
      positions: 22494,
      loaded_count: 0,
      variants: [HOME, PARIS, LONDON],
    },
  ],
};

const cardCount = (container) => container.querySelectorAll('[data-testid="base-variant-card"]').length;

describe('BaseCatalogBrowser market cards', () => {
  it('does not offer a market card where only a plain load is wired', () => {
    const onLoad = vi.fn();
    const { container } = render(<BaseCatalogBrowser catalog={CATALOG} onLoad={onLoad} />);
    expect(cardCount(container)).toBe(1);
    // The one Load button is the home base, never the French card.
    fireEvent.click(screen.getAllByRole('button').find((b) => /load/i.test(b.textContent ?? '')));
    expect(onLoad).toHaveBeenCalledWith(HOME);
  });

  it('offers the market cards and routes them to the market load when wired', () => {
    const onLoad = vi.fn();
    const onReprice = vi.fn();
    const { container } = render(<BaseCatalogBrowser catalog={CATALOG} onLoad={onLoad} onReprice={onReprice} />);
    expect(cardCount(container)).toBe(3);
    const priceButtons = screen.getAllByRole('button').filter((b) => /France/.test(b.textContent ?? ''));
    expect(priceButtons).toHaveLength(1);
    fireEvent.click(priceButtons[0]);
    expect(onReprice).toHaveBeenCalledWith(PARIS);
    expect(onLoad).not.toHaveBeenCalled();
  });

  it('marks the one card whose language no file holds', () => {
    render(<BaseCatalogBrowser catalog={CATALOG} onReprice={vi.fn()} />);
    const notes = screen.getAllByTestId('base-text-lang-note');
    expect(notes).toHaveLength(1);
    expect(notes[0].textContent).toMatch(/Turkish/);
  });

  it('marks the market the server stores, not the one this browser cached', () => {
    const loaded = new Set(['TR_NATIONAL']);
    const catalog = {
      ...CATALOG,
      base_states: {
        TR_NATIONAL: {
          market_state: 'market',
          active_market: 'GB_LONDON_en',
          switching_to: null,
          text_language: 'tr',
          updated_at: null,
        },
      },
    };
    render(
      <BaseCatalogBrowser
        catalog={catalog}
        loadedRegions={loaded}
        onReprice={vi.fn()}
        activeMarkets={{ TR_NATIONAL: 'FR_PARIS_fr' }}
      />,
    );
    // Paris is offered as a switch; London is the active one.
    expect(screen.getAllByRole('button').some((b) => /Switch to France/.test(b.textContent ?? ''))).toBe(true);
    expect(screen.getAllByRole('button').some((b) => /Switch to United Kingdom/.test(b.textContent ?? ''))).toBe(
      false,
    );
    expect(screen.getAllByText('Active market')).toHaveLength(1);
  });

  it('offers the way home on the home card of a base in a market, and nowhere else', () => {
    const onRestoreHome = vi.fn();
    const loaded = new Set(['TR_NATIONAL']);
    const inMarket = {
      ...CATALOG,
      base_states: {
        TR_NATIONAL: {
          market_state: 'market',
          active_market: 'GB_LONDON_en',
          switching_to: null,
          text_language: 'tr',
          updated_at: null,
        },
      },
    };
    const { unmount } = render(
      <BaseCatalogBrowser catalog={inMarket} loadedRegions={loaded} onReprice={vi.fn()} onRestoreHome={onRestoreHome} />,
    );
    const buttons = screen.getAllByTestId('base-restore-home');
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(onRestoreHome).toHaveBeenCalledWith(HOME);
    unmount();

    const atHome = {
      ...CATALOG,
      base_states: { TR_NATIONAL: { ...inMarket.base_states.TR_NATIONAL, market_state: 'home', active_market: null } },
    };
    render(
      <BaseCatalogBrowser
        catalog={atHome}
        loadedRegions={loaded}
        onReprice={vi.fn()}
        onRestoreHome={onRestoreHome}
        activeMarkets={{ TR_NATIONAL: 'FR_PARIS_fr' }}
      />,
    );
    expect(screen.queryByTestId('base-restore-home')).toBeNull();
  });

  it('says so on the home card when a switch did not finish', () => {
    const loaded = new Set(['TR_NATIONAL']);
    const switching = {
      ...CATALOG,
      base_states: {
        TR_NATIONAL: {
          market_state: 'switching',
          active_market: 'GB_LONDON_en',
          switching_to: 'FR_PARIS_fr',
          text_language: null,
          updated_at: null,
        },
      },
    };
    render(
      <BaseCatalogBrowser catalog={switching} loadedRegions={loaded} onReprice={vi.fn()} onRestoreHome={vi.fn()} />,
    );
    expect(screen.getAllByTestId('base-switch-unfinished')).toHaveLength(1);
    // Neither market reads as active while the rows may be half in one of them.
    expect(screen.queryByText('Active market')).toBeNull();
    expect(screen.getAllByTestId('base-restore-home')).toHaveLength(1);
  });

  it('keeps market cards selectable in the onboarding picker', () => {
    const onSelect = vi.fn();
    const { container } = render(
      <BaseCatalogBrowser catalog={CATALOG} mode="select" onSelect={onSelect} selectedRegion={PARIS.variant_id} />,
    );
    expect(cardCount(container)).toBe(3);
  });
});
