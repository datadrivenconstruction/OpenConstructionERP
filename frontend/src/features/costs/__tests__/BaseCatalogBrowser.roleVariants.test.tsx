// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The listing of market variants does not depend on the role; only the install
// action does. A viewer sees every variant with its market, currency and count,
// and the install control is disabled with a caption. An editor's stays live.

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
const installButtons = () => screen.getAllByRole('button').filter((b) => /France|United Kingdom/.test(b.textContent ?? ''));

describe('BaseCatalogBrowser market variants by role', () => {
  it('lists every variant for a viewer and disables the install control', () => {
    const onReprice = vi.fn();
    const { container } = render(<BaseCatalogBrowser catalog={CATALOG} onReprice={onReprice} canReprice={false} />);
    expect(cardCount(container)).toBe(3);
    expect(screen.getByText('EUR')).toBeTruthy();
    expect(screen.getByText('GBP')).toBeTruthy();
    const buttons = installButtons();
    expect(buttons).toHaveLength(2);
    for (const b of buttons) {
      expect(b.disabled).toBe(true);
      expect(b.getAttribute('title')).toMatch(/Only editors/);
      fireEvent.click(b);
    }
    expect(onReprice).not.toHaveBeenCalled();
    expect(screen.getAllByTestId('base-market-locked-note')).toHaveLength(2);
  });

  it('keeps the install control live for an editor', () => {
    const onReprice = vi.fn();
    const { container } = render(<BaseCatalogBrowser catalog={CATALOG} onReprice={onReprice} canReprice />);
    expect(cardCount(container)).toBe(3);
    const buttons = installButtons();
    expect(buttons.every((b) => !b.disabled)).toBe(true);
    fireEvent.click(buttons[0]);
    expect(onReprice).toHaveBeenCalledWith(PARIS);
    expect(screen.queryAllByTestId('base-market-locked-note')).toHaveLength(0);
  });
});
