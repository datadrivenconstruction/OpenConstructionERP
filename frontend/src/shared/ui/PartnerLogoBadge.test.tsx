// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for <PartnerLogoBadge /> — co-branding strip shown when a partner
// pack is active.
//
// Coverage:
//   1. Renders nothing while usePartnerPack is loading.
//   2. Renders nothing when `active: false` (no partner pack installed).
//   3. Dashboard variant: shows powered-by text + partner name + emblem,
//      links to the in-app Partner Packs page.
//   4. Nav variant: renders the partner name chip with its emblem.
//   5. Dismiss button hides the badge and persists to sessionStorage.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import type { PartnerPackResponse } from '@/shared/hooks/usePartnerPack';

/* ── Hook mock ─────────────────────────────────────────────────────── */

const hookMock = vi.hoisted(() => ({
  usePartnerPack: vi.fn(),
  partnerLogoUrl: vi.fn(() => '/api/v1/partner-pack/logo'),
}));
vi.mock('@/shared/hooks/usePartnerPack', () => hookMock);
vi.mock('@/shared/hooks/useDemoPack', () => ({ useDemoPack: () => ({ inDemo: false, manifest: null }) }));

/* ── Helpers ───────────────────────────────────────────────────────── */

const ACTIVE_PACK: PartnerPackResponse = {
  active: true,
  manifest: {
    slug: 'acme',
    partner_name: 'ACME Corp',
    partner_url: 'https://acme.example.com',
    pack_version: '1.0.0',
    description: 'Industry-tuned ERP for ACME.',
    default_locale: 'en',
    additional_locales: [],
    cwicr_regions: [],
    default_currency: 'EUR',
    default_tax_template: null,
    validation_rule_packs: [],
    validation_rule_sets: [],
    default_modules: [],
    hidden_modules: [],
    branding: {
      primary_color: '#0284c7',
      accent_color: null,
      has_logo: true,
      has_favicon: false,
      powered_by_text: 'Powered by OpenConstructionERP',
    },
    has_onboarding_script: false,
    metadata: {},
  },
};

async function importBadge() {
  const mod = await import('./PartnerLogoBadge');
  return mod.PartnerLogoBadge;
}

/**
 * The badge wraps its content in a react-router ``<Link>`` to the in-app
 * Partner Packs page, so every render needs a router in context.
 * ``MemoryRouter`` adds no DOM node of its own, so ``container.firstChild``
 * still reflects the component's own output (e.g. ``null`` when hidden).
 */
function renderBadge(ui: JSX.Element) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

beforeEach(() => {
  cleanup();
  hookMock.usePartnerPack.mockReset();
  hookMock.partnerLogoUrl.mockClear();
  try {
    sessionStorage.clear();
  } catch {
    /* ignore */
  }
});

afterEach(() => {
  cleanup();
});

/* ── Tests ─────────────────────────────────────────────────────────── */

describe('<PartnerLogoBadge />', () => {
  it('renders nothing while the partner-pack query is loading', async () => {
    hookMock.usePartnerPack.mockReturnValue({ isLoading: true, data: undefined });
    const PartnerLogoBadge = await importBadge();

    const { container } = renderBadge(<PartnerLogoBadge variant="dashboard" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when no partner pack is active', async () => {
    hookMock.usePartnerPack.mockReturnValue({
      isLoading: false,
      data: { active: false },
    });
    const PartnerLogoBadge = await importBadge();

    const { container } = renderBadge(<PartnerLogoBadge variant="dashboard" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the powered-by line, partner name and emblem on the dashboard variant', async () => {
    hookMock.usePartnerPack.mockReturnValue({
      isLoading: false,
      data: ACTIVE_PACK,
    });
    const PartnerLogoBadge = await importBadge();

    renderBadge(<PartnerLogoBadge variant="dashboard" />);

    // Powered-by text is the manifest's powered_by_text.
    expect(screen.getByText('Powered by OpenConstructionERP')).toBeTruthy();
    // Description rendered.
    expect(screen.getByText('Industry-tuned ERP for ACME.')).toBeTruthy();
    // The pack declares ``has_logo: true`` and the badge still does not draw
    // one. That is the point of the change rather than an omission: a pack's
    // own mark told the reader only that the pack existed, so the badge now
    // carries the pack's emblem - a flag when the pack serves one country, a
    // monogram otherwise. This pack claims no country, so a monogram is the
    // correct mark, and the endpoint that would serve the logo is never asked.
    expect(screen.getByTestId('pack-emblem-acme').getAttribute('data-pack-emblem')).toBe(
      'monogram',
    );
    expect(screen.queryByAltText('ACME Corp logo')).toBeNull();
    expect(hookMock.partnerLogoUrl).not.toHaveBeenCalled();
    // The badge links to the in-app Partner Packs page (not the partner's
    // external site); react-router renders the <Link> as an internal <a>.
    const links = screen.getAllByRole('link');
    expect(links[0]?.getAttribute('href')).toBe('/modules?tab=partner-packs');
  });

  it('renders the nav variant chip with the partner name', async () => {
    hookMock.usePartnerPack.mockReturnValue({
      isLoading: false,
      data: ACTIVE_PACK,
    });
    const PartnerLogoBadge = await importBadge();

    renderBadge(<PartnerLogoBadge variant="nav" />);

    expect(screen.getByTestId('partner-logo-nav')).toBeTruthy();
    expect(screen.getByText('ACME Corp')).toBeTruthy();
  });

  it('hides the badge when the dismiss button is clicked and persists to sessionStorage', async () => {
    hookMock.usePartnerPack.mockReturnValue({
      isLoading: false,
      data: ACTIVE_PACK,
    });
    const PartnerLogoBadge = await importBadge();

    const { container } = renderBadge(<PartnerLogoBadge variant="dashboard" />);
    expect(container.firstChild).not.toBeNull();

    const dismissBtn = screen.getByRole('button', { name: /Hide partner badge/i });
    fireEvent.click(dismissBtn);

    // Component returns null after dismissal.
    expect(container.firstChild).toBeNull();
    // Dismissal persisted to sessionStorage.
    expect(sessionStorage.getItem('partner-pack:dismissed')).toBe('1');
  });
});
