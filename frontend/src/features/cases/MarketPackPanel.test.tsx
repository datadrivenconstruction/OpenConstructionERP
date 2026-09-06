// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko
//
// The panel has to separate applied, available and absent, and the deployment
// it was written on can only produce two of those by itself: every pack on
// disk and `active_slug` null, so everything is "available". A suite that
// checked each state alone would pass on a build where applied and available
// render identically, which is the mistake worth guarding here. Every state
// test below is written against another state's rendering rather than against
// a fixed string.
//
// `INSTALLED` mirrors the wheel and not the repository, which is the whole
// reason the absent state was missed. A source checkout carries twenty packs
// and the wheel force-includes seventeen: `bimhessen-de` and `batimatech-ca`
// are in the tree and in no build a user installs. A fixture built from
// `packs/` therefore proves the German case works on a machine nobody ships,
// and the thirteen German cards that render nothing in production have no test
// that can fail. DE is in this file only as a market with no pack.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const hookMock = vi.hoisted(() => ({
  usePartnerPack: vi.fn(),
  useInstalledPacks: vi.fn(),
  partnerLogoUrl: vi.fn(() => '/api/v1/partner-pack/logo'),
}));
vi.mock('@/shared/hooks/usePartnerPack', () => hookMock);

const authMock = vi.hoisted(() => ({ role: 'admin' as string }));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (sel: (s: { userRole: string }) => unknown) => sel({ userRole: authMock.role }),
}));

// The dialog is the modules feature's own component and drags the pack apply
// API in with it. What this file is about is which pack the panel points the
// button at, so the dialog is reduced to a marker that prints the slug it was
// handed.
vi.mock('@/features/modules/PartnerPackApplyDialog', () => ({
  PartnerPackApplyDialog: ({ open, slug }: { open: boolean; slug: string }) =>
    open ? <div data-testid="apply-dialog" data-slug={slug} /> : null,
}));

import { MarketPackPanel } from './MarketPackPanel';

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
    metadata: { country },
    branding: { primary_color: '#123456', accent_color: null },
  };
}

const INSTALLED = [
  packOf('india-cpwd', 'IN'),
  packOf('uk-jct', 'GB'),
  packOf('us-california', 'US'),
  packOf('us-texas', 'US'),
];

function mount(region: string | null | undefined, activeSlug: string | null = null) {
  hookMock.useInstalledPacks.mockReturnValue({
    isLoading: false,
    data: { active_slug: activeSlug, installed: INSTALLED },
  });
  return render(
    <MemoryRouter>
      <MarketPackPanel region={region} />
    </MemoryRouter>,
  );
}

/** The request has not answered yet, which is not the same as an empty answer. */
function mountInFlight(region: string | null | undefined) {
  hookMock.useInstalledPacks.mockReturnValue({ isLoading: true, data: undefined });
  return render(
    <MemoryRouter>
      <MarketPackPanel region={region} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  cleanup();
  hookMock.useInstalledPacks.mockReset();
  authMock.role = 'admin';
});

describe('<MarketPackPanel />', () => {
  it('names the market pack and offers the action that switches it on', () => {
    // The founder's report was that the case said a regional pack was needed
    // and gave the reader nothing to press. The button is the assertion.
    mount('IN');
    const panel = screen.getByTestId('market-pack-panel');
    expect(panel.getAttribute('data-pack-state')).toBe('available');
    expect(panel.getAttribute('data-pack-slug')).toBe('india-cpwd');
    expect(screen.getByRole('button', { name: /activate/i })).toBeEnabled();
  });

  it('renders the applied market differently from the same market unapplied', () => {
    const availableHtml = mount('GB').container.innerHTML;
    cleanup();
    mount('GB', 'uk-jct');

    const panel = screen.getByTestId('market-pack-panel');
    expect(panel.getAttribute('data-pack-state')).toBe('applied');
    // Not just a different attribute: the applied state must not still be
    // offering to activate what is already active.
    expect(screen.queryByRole('button', { name: /activate/i })).toBeNull();
    expect(panel.outerHTML).not.toBe(availableHtml);
  });

  it('states the absence for a market with no pack, and offers no other one', () => {
    // Thirty-three of the eighty cases that name a market resolve nothing on a
    // released install: ten carry ES, which no pack declares at all, and
    // twenty-three carry DE or CA, whose packs are in the tree and in no
    // build. Both used to render nothing, so a reader filtering the catalogue
    // to Germany saw thirteen cards announcing German standards and no control
    // anywhere. The two directions are asserted together: the panel must reach
    // the absent state AND must not have fallen back to a plausible
    // neighbour, which would put Indian standards under a Spanish case.
    for (const market of ['ES', 'DE']) {
      cleanup();
      mount(market);
      const panel = screen.getByTestId('market-pack-panel');
      expect(panel.getAttribute('data-pack-state')).toBe('none');
      expect(panel.getAttribute('data-market')).toBe(market.toLowerCase());
      expect(panel.getAttribute('data-pack-slug')).toBeNull();
      expect(screen.queryByRole('button', { name: /activate/i })).toBeNull();
    }
  });

  it('renders the absent state and the offer as different things', () => {
    // The pair that keeps the test above honest. A panel that reported 'none'
    // for every market would satisfy it, and a panel that reported
    // 'available' for every market would satisfy the offer tests; only
    // asserting that one market gets each answer catches a constant.
    const absent = mount('ES').getByTestId('market-pack-panel');
    expect(absent.getAttribute('data-pack-state')).toBe('none');
    cleanup();

    const offered = mount('IN').getByTestId('market-pack-panel');
    expect(offered.getAttribute('data-pack-state')).toBe('available');
    expect(offered.getAttribute('data-market')).toBeNull();
  });

  it('says nothing at all for a case that names no market', () => {
    // Most of the catalogue is universal on purpose: 140 of 220 cases carry no
    // region. A line about regional packs on every one of them would be noise,
    // and `xx` is a pack's own word for cross-region, never a market.
    for (const region of [undefined, null, '', 'xx', 'ALL']) {
      cleanup();
      expect(mount(region).container.firstChild).toBeNull();
    }
  });

  it('does not claim an absence before the server has answered', () => {
    // While the installed list is in flight every market resolves to nothing,
    // so a panel keyed on the empty result alone would tell a reader on a
    // British case that no British pack exists, then replace it with the
    // offer a moment later.
    expect(mountInFlight('GB').container.firstChild).toBeNull();
  });

  it('does not send a reader who cannot install to the screen that installs', () => {
    // Upload and rescan on /modules are RequirePermission("admin") and render
    // nothing for a viewer, so the link is an offer only an admin can take.
    // The statement itself stays: knowing no pack covers your market is the
    // answer to the question, whoever is asking.
    mount('ES');
    expect(screen.getByRole('link')).toBeInTheDocument();
    cleanup();

    authMock.role = 'viewer';
    mount('ES');
    expect(screen.getByTestId('market-pack-panel').getAttribute('data-pack-state')).toBe('none');
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('points the button at the applied pack when several serve one market', () => {
    // us-california and us-texas both declare US. Unapplied the panel leads
    // with the first; applied it must lead with the one in force, or a Texan
    // workspace reading a US case is offered California.
    const unapplied = mount('US');
    expect(unapplied.getByTestId('market-pack-panel').getAttribute('data-pack-slug')).toBe(
      'us-california',
    );
    cleanup();

    mount('US', 'us-texas');
    expect(screen.getByTestId('market-pack-panel').getAttribute('data-pack-slug')).toBe('us-texas');
  });

  it('matches the case spelling of a market against the pack spelling', () => {
    // Cases write DE, packs write de. Both are right in their own file, and a
    // case-sensitive comparison would blank the panel on every case.
    const upper = mount('IN').container.innerHTML;
    cleanup();
    const lower = mount('in').container.innerHTML;
    expect(lower).toBe(upper);
    expect(lower).not.toBe('');
  });

  it('lets a non-admin see the pack but not apply it', () => {
    // Applying is admin-only server side. Hiding the panel from everyone else
    // would hide the ANSWER too, and a reader who cannot apply still needs to
    // know which pack the numbers on this page assume.
    const adminHtml = mount('IN').container.innerHTML;
    cleanup();

    authMock.role = 'viewer';
    mount('IN');
    expect(screen.getByTestId('market-pack-panel')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /activate/i })).toBeDisabled();
    expect(screen.getByTestId('market-pack-panel').outerHTML).not.toBe(adminHtml);
  });

  it('keeps the registry reachable in both states', () => {
    // The other packs for a market, and what an applied pack configures, live
    // one click away. The deep link has to carry the slug or the reader lands
    // on a list of eighteen and matches by eye.
    mount('IN');
    const link = screen.getByRole('link');
    expect(link.getAttribute('href')).toBe('/modules?tab=packs&pack=india-cpwd');
    cleanup();

    mount('IN', 'india-cpwd');
    expect(screen.getByRole('link').getAttribute('href')).toBe(
      '/modules?tab=packs&pack=india-cpwd',
    );
  });
});
