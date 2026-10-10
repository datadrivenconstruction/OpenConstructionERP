// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A country can have its plain pack and a specialised variant built on it.
// Türkiye is the first: turkey-tr, and turkey-tr-mep for one trade. The two
// name the same country, and everything that picked "the country's pack" used
// to assume one pack per country or lean on the order of the list:
//
//   - the offer took the first pack of the country, and the list is ordered by
//     slug, so the variant's slug had been chosen to sort second;
//   - the preselection wanted exactly one pack for the country, found two, and
//     selected nothing for a Turkish first run.
//
// The plain pack is the country's offer whatever the order, and the variant is
// a tile that says what it is. Its optional module switch-offs, which the
// one-click setup leaves on, are said on the screen instead of being skipped
// in silence.
//
// Run:  npx vitest run src/features/onboarding/__tests__/countryPackVariant.test.tsx --maxWorkers=1
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const { fetchInstalledPacks } = vi.hoisted(() => ({ fetchInstalledPacks: vi.fn() }));

vi.mock('../partnerPacksApi', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, fetchInstalledPacks };
});

import {
  isCountrysOwnPack,
  modulesLeftOnByOneClick,
  packSetupHref,
  packToPreselect,
  packVariantOf,
  resolveCountryOffer,
} from '../countryOffer';
import { ReadyPackPicker } from '../OnboardingWizard';

function pack(slug: string, country: string, partnerName: string, extra: Record<string, unknown> = {}) {
  const { metadata, ...rest } = extra;
  return {
    slug,
    partner_name: partnerName,
    partner_url: null,
    pack_version: '1.0.0',
    description: '',
    default_locale: 'en',
    additional_locales: [],
    cwicr_regions: [],
    default_currency: 'USD',
    default_tax_template: null,
    validation_rule_packs: [],
    default_modules: [],
    hidden_modules: [],
    branding: {},
    has_onboarding_script: false,
    metadata: { country, ...(metadata as object) },
    ...rest,
  };
}

const HIDDEN = ['oe_formwork', 'oe_rebar_schedule', 'oe_cost_plan'];

const PLAIN = pack('turkey-tr', 'TR', 'Turkey Construction Pack', { type: 'country' });
const VARIANT = pack('turkey-tr-mep', 'TR', 'Turkey MEP Contractor Pack', {
  type: 'industry',
  hidden_modules: HIDDEN,
  metadata: { derived_from: 'turkey-tr' },
});
const OTHERS = [
  pack('aus', 'AU', 'Australia Construction Pack'),
  pack('us-california', 'US', 'California Construction Pack'),
  pack('us-costdata', 'US', 'US Construction Pack'),
  pack('us-texas', 'US', 'Texas Construction Pack'),
];

// Both orders, because the order was the old rule. The server lists by slug,
// which puts the plain pack first; the second list is what a variant with an
// earlier slug, or a client-side sort by name, would produce.
const ORDERS: Array<[string, unknown[]]> = [
  ['plain pack listed first', [...OTHERS, PLAIN, VARIANT]],
  ['variant listed first', [VARIANT, ...OTHERS, PLAIN]],
];

describe('which Turkish pack stands for the country', () => {
  it.each(ORDERS)('offers the plain country pack: %s', (_label, packs) => {
    expect(resolveCountryOffer('tr', packs)).toEqual({
      kind: 'pack',
      pack: expect.objectContaining({ slug: 'turkey-tr' }),
    });
  });

  it.each(ORDERS)('preselects the plain country pack: %s', (_label, packs) => {
    expect(packToPreselect('tr', packs)).toBe('turkey-tr');
  });

  it('never offers the variant as the country pack, even alone', () => {
    // It cannot be installed without its parent, so this list does not occur.
    // The assertion is that the rule is "not a variant", not "first match".
    expect(resolveCountryOffer('tr', [VARIANT])?.kind).not.toBe('pack');
    expect(packToPreselect('tr', [VARIANT])).toBeNull();
  });

  it('still leaves a country with several plain packs to the reader', () => {
    expect(packToPreselect('us', [...OTHERS, PLAIN, VARIANT])).toBeNull();
  });

  it('reads the variant from the metadata key, and an older backend without a type still preselects', () => {
    expect(packVariantOf(VARIANT)).toBe('turkey-tr');
    expect(packVariantOf(PLAIN)).toBeNull();
    expect(isCountrysOwnPack(PLAIN)).toBe(true);
    expect(isCountrysOwnPack(VARIANT)).toBe(false);
    const untyped = pack('brazil-sinapi', 'BR', 'Brazil Construction Pack');
    expect(untyped.type).toBeUndefined();
    expect(isCountrysOwnPack(untyped)).toBe(true);
    expect(packToPreselect('br', [untyped])).toBe('brazil-sinapi');
  });

  it('counts what the one-click setup leaves on, and names where to change it', () => {
    expect(modulesLeftOnByOneClick(VARIANT)).toBe(HIDDEN.length);
    expect(modulesLeftOnByOneClick(PLAIN)).toBe(0);
    expect(packSetupHref('turkey-tr-mep')).toBe('/modules?tab=packs&pack=turkey-tr-mep');
  });
});

const REAL_LANGUAGE = navigator.language;
const REAL_LANGUAGES = navigator.languages;

function browser(language: string): void {
  Object.defineProperty(window.navigator, 'language', { value: language, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: [language], configurable: true });
}

afterEach(() => {
  Object.defineProperty(window.navigator, 'language', { value: REAL_LANGUAGE, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: REAL_LANGUAGES, configurable: true });
});

async function renderPicker(packs: unknown[]) {
  fetchInstalledPacks.mockResolvedValue({ installed: packs });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ReadyPackPicker
          onActivateLocale={() => undefined}
          onInstalled={() => undefined}
          onFallback={() => undefined}
          onBack={() => undefined}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findAllByRole('button', { pressed: false });
}

describe('the ready-made grid for a Turkish first run', () => {
  it.each(ORDERS)('opens on the plain pack and marks the variant: %s', async (_label, packs) => {
    browser('tr-TR');
    await renderPicker(packs);

    const pressed = screen.queryAllByRole('button', { pressed: true });
    expect(pressed).toHaveLength(1);
    expect(pressed[0]?.textContent).toMatch(/Turkey Construction Pack/);
    expect(pressed[0]?.textContent).not.toMatch(/Specialised variant/);

    // Exactly one tile carries the badge, and it is the variant's.
    expect(screen.getByTestId('pack-variant-turkey-tr-mep').textContent).toBe('Specialised variant');
    expect(screen.queryByTestId('pack-variant-turkey-tr')).toBeNull();

    // The plain pack is neither a variant nor a pack that switches modules
    // off, so the notes block has nothing true to say and is not drawn.
    expect(screen.queryByTestId('pack-one-click-notes')).toBeNull();
  });

  it('says what the variant is and what one-click setup will not do, once it is chosen', async () => {
    browser('tr-TR');
    await renderPicker([...OTHERS, PLAIN, VARIANT]);

    fireEvent.click(screen.getByTestId('pack-variant-turkey-tr-mep').closest('button')!);

    const notes = screen.getByTestId('pack-one-click-notes').textContent ?? '';
    expect(notes).toMatch(/Turkey MEP Contractor Pack is built on Turkey Construction Pack/);
    expect(notes).toMatch(/If you are not sure, choose Turkey Construction Pack/);
    // The count is the pack's own, not a number written into the sentence.
    expect(notes).toContain(`(${HIDDEN.length} in total)`);
    expect(notes).toMatch(/One-click setup leaves all of them on/);
  });
});
