import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type { PartnerPackResponse } from '@/shared/hooks/usePartnerPack';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { LoginPage } from './LoginPage';

const partnerHook = vi.hoisted(() => vi.fn());
vi.mock('@/shared/hooks/usePartnerPack', () => ({
  usePartnerPack: partnerHook,
  partnerLogoUrl: (slug: string) => `/api/v1/partner-pack/logo/${slug}`,
}));

const MULLETS: PartnerPackResponse = {
  active: true,
  manifest: {
    slug: 'mullets-aluminum',
    partner_name: 'Mullets Aluminum Products, Inc.',
    partner_url: null,
    pack_version: '0.1.0',
    description: '',
    default_locale: 'en-US',
    additional_locales: [],
    cwicr_regions: [],
    default_currency: 'USD',
    default_tax_template: null,
    validation_rule_packs: [],
    default_modules: [],
    hidden_modules: [],
    branding: {
      primary_color: '#0055A6',
      accent_color: null,
      has_logo: true,
      has_favicon: false,
      powered_by_text:
        'Powered by OpenConstructionERP · In partnership with Mullets Aluminum Products, Inc.',
    },
    has_onboarding_script: false,
    metadata: {},
  },
};

beforeEach(() => {
  useBrandingStore.setState({
    mode: 'default',
    logoDataUrl: null,
    companyName: '',
    hydrateFromServer: vi.fn().mockResolvedValue(undefined),
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it('uses active partner branding and leaves the no-partner login brand unchanged', () => {
  partnerHook.mockReturnValue({ data: { active: false } });
  render(<MemoryRouter><LoginPage /></MemoryRouter>);

  expect(screen.getByTestId('login-default-brand')).toBeInTheDocument();
  expect(screen.queryByTestId('login-partner-brand')).not.toBeInTheDocument();

  cleanup();
  partnerHook.mockReturnValue({ data: MULLETS });
  render(<MemoryRouter><LoginPage /></MemoryRouter>);

  const partnerBrand = screen.getByTestId('login-partner-brand');
  expect(partnerBrand).toHaveStyle({ borderLeftColor: '#0055A6' });
  expect(screen.getByText('Mullets Aluminum Products, Inc.')).toBeInTheDocument();
  expect(screen.getByAltText('Mullets Aluminum Products, Inc. logo')).toHaveAttribute(
    'src',
    '/api/v1/partner-pack/logo/mullets-aluminum',
  );
  expect(screen.getByText(/Powered by OpenConstructionERP/)).toBeInTheDocument();
  expect(screen.queryByTestId('login-default-brand')).not.toBeInTheDocument();
});
