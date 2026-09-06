// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko
//
// The strip lives on a card that is itself one big click target, and it has to
// tell three states apart on one line. Two mistakes are worth guarding against
// and neither shows up in a screenshot:
//
//   1. The card swallows the press. A control that opens the case instead of
//      the pack reads as "the install button does nothing", which is exactly
//      the report this work came from. So the click is asserted against a
//      parent handler, not just against its own.
//   2. Two states render the same. The deployment this was written on has
//      twenty servable packs on disk and `active_slug` null, so everything on
//      it is "install" and a suite that checked each state against a fixed
//      string would pass on a build where installed and available look
//      identical. Every state below is asserted against another state's
//      rendering.
//   3. The fixture installs a pack no release ships. A checkout holds packs
//      the community wheel force-includes deliberately incomplete, so a
//      market can pass every test here and still resolve to nothing for
//      every user. `INSTALLED` below is the wheel's list, not the tree's.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ComponentProps } from 'react';
import { render, renderHook, screen, cleanup, fireEvent } from '@testing-library/react';

const hookMock = vi.hoisted(() => ({
  usePartnerPack: vi.fn(),
  useInstalledPacks: vi.fn(),
  partnerLogoUrl: vi.fn(() => '/api/v1/partner-pack/logo'),
}));
vi.mock('@/shared/hooks/usePartnerPack', () => hookMock);

import { CasePackStrip, useMarketPackOffers, type CasePackOffer } from './CasePackStrip';

function packOf(slug: string, country: string, name = slug) {
  return {
    slug,
    partner_name: name,
    type: 'country',
    description: `Pre-configured for ${country}: standards, tax and currency`,
    default_locale: 'en-US',
    default_currency: 'EUR',
    default_tax_template: 'de_vat_19',
    pack_version: '0.2.0',
    validation_rule_packs: ['din276'],
    validation_rule_sets: [],
    metadata: { country },
    branding: { primary_color: '#123456', accent_color: null },
  };
}

/**
 * The packs the community wheel force-includes, NOT the packs a checkout of
 * this repository holds. backend/pyproject.toml names seventeen of the twenty
 * servable ones, and the three it leaves out are held back for licensing:
 * batimatech-ca and bimhessen-de under partnership agreements, doker-formwork
 * for a named third party's logo.
 *
 * bimhessen-de stood in this list until the fixture was corrected, which made
 * Germany the best covered market in the suite while being one of the two the
 * shipped product cannot offer at all.
 */
const INSTALLED = [
  packOf('uk-jct', 'GB', 'UK JCT'),
  packOf('us-california', 'US', 'California'),
  packOf('us-texas', 'US', 'Texas'),
];

/** The regions the shipped catalogue actually carries, ES included. */
const REGIONS = ['CA', 'CN', 'DE', 'ES', 'GB', 'IN', 'US'];

function offers(activeSlug: string | null = null) {
  hookMock.useInstalledPacks.mockReturnValue({
    isLoading: false,
    data: { active_slug: activeSlug, installed: INSTALLED },
  });
  return renderHook(() => useMarketPackOffers(REGIONS)).result.current;
}

const OFFER: CasePackOffer = {
  slug: 'uk-jct',
  name: 'UK JCT',
  applied: false,
};

/** The strip inside a stand-in for the card: one element, one click handler,
 *  the whole surface. Returns the spy so a test can prove the press stopped. */
function mountInCard(props: Partial<ComponentProps<typeof CasePackStrip>> = {}) {
  const onOpen = vi.fn();
  const onActivate = vi.fn();
  render(
    <div role="button" tabIndex={0} onClick={onOpen}>
      <CasePackStrip pack={OFFER} canInstall onActivate={onActivate} {...props} />
    </div>,
  );
  return { onOpen, onActivate };
}

beforeEach(() => {
  cleanup();
  hookMock.useInstalledPacks.mockReset();
});

describe('useMarketPackOffers', () => {
  it('names the pack that serves each market the catalogue carries', () => {
    const map = offers();
    expect(map.get('GB')?.slug).toBe('uk-jct');
    expect(map.get('US')?.slug).toBe('us-california');
    // Cases spell the market upper case and packs spell it lower case. Both
    // files are right; the lookup has to be done in the cases' spelling
    // because that is the value a card holds.
    expect(map.get('GB')?.name).toBe('UK JCT');
  });

  it('offers nothing for a market with no pack rather than the nearest one', () => {
    // Ten shipped cases carry ES and no Spanish pack exists. A fallback to a
    // plausible neighbour would put German standards and a German VAT
    // template under a Spanish case.
    const map = offers();
    expect(map.has('ES')).toBe(false);
    expect(map.has('CN')).toBe(false);
    // Three packs, two markets: us-california and us-texas both declare US
    // and a market is offered ONE pack, not a list. Seven markets go in.
    expect(map.size).toBe(2);
  });

  it('offers nothing for DE and CA, whose packs are in no release', () => {
    // Thirteen German and ten Canadian cases name standards that bimhessen-de
    // and batimatech-ca carry, and the wheel force-includes neither, so on
    // every released install both markets resolve to nothing. This is not the
    // same absence as ES: a Spanish pack does not exist, whereas these two
    // exist and are withheld, and a fixture that installs them hides the
    // difference behind a green test.
    const map = offers();
    // Asserted beside a market that DOES resolve in the same call. An empty
    // map from a hook that never answered satisfies an absence on its own,
    // so the absence is only evidence next to a presence.
    expect(map.get('GB')?.slug).toBe('uk-jct');
    expect(map.has('DE')).toBe(false);
    expect(map.has('CA')).toBe(false);
  });

  it('says nothing at all until the list of packs has arrived', () => {
    // "No pack" is wrong for every market that has one, and it would flip a
    // moment later. Silence is the only honest answer in flight.
    hookMock.useInstalledPacks.mockReturnValue({ isLoading: true, data: undefined });
    const map = renderHook(() => useMarketPackOffers(REGIONS)).result.current;
    expect(map.size).toBe(0);
  });

  it('leads with the applied pack when one pack of a market is on', () => {
    // Three packs declare US. Which one the card names is not arbitrary: the
    // applied one is the answer to "what am I looking at".
    const off = offers('us-texas');
    expect(off.get('US')?.slug).toBe('us-texas');
    expect(off.get('US')?.applied).toBe(true);
    expect(offers(null).get('US')?.applied).toBe(false);
  });
});

describe('<CasePackStrip />', () => {
  it('offers the install without letting the card underneath take the press', () => {
    // The whole card is one click target. A control that opened the case
    // instead of the pack is the defect this file exists to catch, and it
    // looks identical to a working one in a screenshot.
    const { onOpen, onActivate } = mountInCard();
    fireEvent.click(screen.getByTestId('case-pack-strip'));
    expect(onActivate).toHaveBeenCalledWith(OFFER);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('names the pack it would install rather than only the action', () => {
    mountInCard();
    const strip = screen.getByTestId('case-pack-strip');
    expect(strip.getAttribute('data-pack-state')).toBe('install');
    expect(strip.getAttribute('data-pack-slug')).toBe('uk-jct');
    expect(strip.tagName).toBe('BUTTON');
    // "Set up" alone does not say what would be installed, and a card that
    // installs something unnamed is worse than one that installs nothing.
    expect(strip.textContent).toContain('UK JCT');
  });

  it('renders an applied pack differently from the same pack switched off', () => {
    mountInCard();
    const availableHtml = screen.getByTestId('case-pack-strip').outerHTML;
    cleanup();
    mountInCard({ pack: { ...OFFER, applied: true } });

    const strip = screen.getByTestId('case-pack-strip');
    expect(strip.getAttribute('data-pack-state')).toBe('installed');
    // Not just a different attribute: an applied pack must not still be
    // offering to install what is already on, so it is not a control at all.
    // `queryByRole` would find the card stand-in this is mounted inside, which
    // is itself a button; the element under test is the one to ask.
    expect(strip.tagName).toBe('P');
    expect(strip.outerHTML).not.toBe(availableHtml);
  });

  it('says who may install rather than greying the control silently', () => {
    // Self-registration on a live deployment hands out `viewer`, and the
    // backend guards the apply with RequireRole("admin"). A disabled button
    // whose only reason lives in a tooltip reads as a broken button.
    const { onActivate } = mountInCard({ canInstall: false });
    const strip = screen.getByTestId('case-pack-strip');
    expect(strip.getAttribute('data-pack-state')).toBe('unavailable');
    expect(strip).toBeDisabled();
    fireEvent.click(strip);
    expect(onActivate).not.toHaveBeenCalled();
  });

  it('draws nothing for a case whose market has no pack', () => {
    const { container } = render(
      <CasePackStrip pack={null} canInstall onActivate={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
