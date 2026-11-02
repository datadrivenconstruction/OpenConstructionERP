// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Component tests: Add-market preview modal, market settings states, onboarding summary, admin-only toggle.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const previewMarketProfile = vi.fn();
const saveMarketProfile = vi.fn();
let scopeState: { data?: unknown; isLoading?: boolean; isError?: boolean } = {};
const refetch = vi.fn();

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  previewMarketProfile: (...a: unknown[]) => previewMarketProfile(...a),
  saveMarketProfile: (...a: unknown[]) => saveMarketProfile(...a),
  useMarketScope: () => ({ isLoading: false, isError: false, refetch, ...scopeState }),
}));

const apiGet = vi.fn();
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  apiGet: (...a: unknown[]) => apiGet(...a),
}));

let role = 'admin';
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (sel: (s: { userRole: string }) => unknown) => sel({ userRole: role }),
}));

vi.mock('@/features/einvoice-clearance/EInvoiceSetupCard', () => ({
  EInvoiceSetupCard: ({ canEdit }) => <div data-testid="einvoice-setup-card" data-can-edit={String(canEdit)} />,
}));

import { MarketPreviewModal } from '../MarketPreviewModal';
import { MarketSettings } from '../MarketSettings';
import { MarketSummary } from '../MarketSummary';
import { ModulesSettings } from '@/features/settings/ModulesSettings';

const profile = (extra: string[] = []) => ({
  primary: { country: 'DE', subdivision: '' },
  extra_markets: extra.map((country) => ({ country, subdivision: '' })),
  company_type: 'general_contractor',
  standards: { classification: '', measurement: '', contract_family: '', tax_profile: '', units: '' },
  keep_modules: [],
});

const scope = (over = {}) => ({
  profile: profile(),
  derived: false,
  markets: ['DE'],
  expanded_markets: ['DE', 'EU'],
  all_markets: false,
  hidden_modules: ['middle_east_pack', 'sa_pack', 'us_pack'],
  module_markets: { dach_pack: ['DE'], middle_east_pack: ['SA'], sa_pack: ['SA'], us_pack: ['US'], uk_pack: ['GB'] },
  packs: ['germany-de'],
  units_system: 'metric',
  standards: { classification: 'din276' },
  options: { standards: ['din276'], contract_forms: ['VOB_B'] },
  rule_sets: ['boq_quality', 'din276'],
  can_edit: true,
  ...over,
});

function wrap(ui) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  scopeState = { data: scope() };
  role = 'admin';
});

describe('MarketPreviewModal', () => {
  const next = profile(['SA']);
  const props = (over = {}) => ({
    open: true,
    current: scope(),
    next,
    title: 'Add Saudi Arabia',
    confirmLabel: 'Add Saudi Arabia',
    onConfirm: vi.fn(),
    onClose: vi.fn(),
    ...over,
  });

  it('shows what appears, disappears and stays, and saves nothing until confirmed', async () => {
    previewMarketProfile.mockResolvedValue({
      ...scope(),
      hidden_modules: ['us_pack'],
      packs: ['germany-de', 'saudi-vision2030'],
      suggested_packages: ['real_estate_gcc'],
    });
    const p = props();
    wrap(<MarketPreviewModal {...p} />);
    expect(await screen.findByTestId('market-preview-appear')).toBeTruthy();
    expect(previewMarketProfile).toHaveBeenCalledWith(next);
    expect(screen.getByTestId('focus-module-middle_east_pack')).toBeTruthy();
    expect(screen.getByTestId('focus-module-sa_pack')).toBeTruthy();
    expect(screen.getByTestId('market-preview-suggested').textContent).toMatch(/real_estate_gcc|real estate gcc|Real estate/i);
    expect(screen.getByText(/market\.data_safe|never deleted/i)).toBeTruthy();
    expect(p.onConfirm).not.toHaveBeenCalled();
    expect(saveMarketProfile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('market-preview-confirm'));
    await waitFor(() => expect(p.onConfirm).toHaveBeenCalledTimes(1));
  });

  it('leads with what disappears when a market is removed', async () => {
    previewMarketProfile.mockResolvedValue({ ...scope(), hidden_modules: ['middle_east_pack', 'sa_pack', 'us_pack', 'dach_pack'], suggested_packages: [] });
    wrap(<MarketPreviewModal {...props({ current: scope({ hidden_modules: ['us_pack'] }), next: profile() })} />);
    const disappear = await screen.findByTestId('market-preview-disappear');
    const appear = screen.getByTestId('market-preview-appear');
    expect(disappear.compareDocumentPosition(appear) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('disables confirm while the preview loads and shows a busy skeleton', () => {
    previewMarketProfile.mockReturnValue(new Promise(() => undefined));
    wrap(<MarketPreviewModal {...props()} />);
    expect(screen.getByTestId('market-preview-confirm').disabled).toBe(true);
    expect(document.querySelector('[aria-busy="true"]')).toBeTruthy();
  });

  it('does not request a preview while closed', () => {
    wrap(<MarketPreviewModal {...props({ open: false })} />);
    expect(previewMarketProfile).not.toHaveBeenCalled();
  });

  it('cancel closes without confirming', async () => {
    previewMarketProfile.mockResolvedValue({ ...scope(), suggested_packages: [] });
    const p = props();
    wrap(<MarketPreviewModal {...p} />);
    await screen.findByTestId('market-preview-appear');
    fireEvent.click(screen.getByRole('button', { name: /common\.cancel|Cancel/ }));
    expect(p.onClose).toHaveBeenCalled();
    expect(p.onConfirm).not.toHaveBeenCalled();
  });

  it('handles an empty diff without crashing', async () => {
    previewMarketProfile.mockResolvedValue({ ...scope(), suggested_packages: [] });
    wrap(<MarketPreviewModal {...props({ next: profile() })} />);
    expect(await screen.findByTestId('market-preview-appear')).toBeTruthy();
  });
});

describe('MarketSettings', () => {
  it('shows an error banner with Retry and no editable fields', () => {
    scopeState = { data: undefined, isError: true };
    wrap(<MarketSettings />);
    expect(screen.getByRole('alert').textContent).toMatch(/market\.load_error|Could not load/);
    fireEvent.click(screen.getByRole('button', { name: /common\.retry|Retry/ }));
    expect(refetch).toHaveBeenCalled();
    expect(screen.queryByTestId('market-primary')).toBeNull();
  });

  it('shows a busy skeleton while loading', () => {
    scopeState = { data: undefined, isLoading: true };
    wrap(<MarketSettings />);
    expect(document.querySelector('[aria-busy="true"]')).toBeTruthy();
    expect(screen.queryByTestId('market-primary')).toBeNull();
  });

  it('is read-only for a non-admin: no add control, disabled fields and Save', () => {
    scopeState = { data: scope({ can_edit: false }) };
    wrap(<MarketSettings />);
    expect(screen.getByTestId('market-primary').disabled).toBe(true);
    expect(screen.getByTestId('market-units').disabled).toBe(true);
    expect(screen.queryByTestId('market-add-select')).toBeNull();
    expect(screen.getByRole('button', { name: /common\.save|Save/ }).disabled).toBe(true);
  });

  it('empty state offers adding a market; picking one opens the preview, saving only after confirm', async () => {
    previewMarketProfile.mockResolvedValue({ ...scope(), hidden_modules: ['us_pack'], suggested_packages: [] });
    saveMarketProfile.mockResolvedValue(scope({ profile: profile(['SA']) }));
    wrap(<MarketSettings />);
    expect(screen.getByText(/market\.add_empty|Working abroad/)).toBeTruthy();
    fireEvent.change(screen.getByTestId('market-add-select'), { target: { value: 'SA' } });
    fireEvent.click(screen.getByRole('button', { name: /market\.add_confirm|Add /, hidden: false }));
    expect(await screen.findByTestId('market-preview-modal')).toBeTruthy();
    expect(saveMarketProfile).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId('market-preview-confirm'));
    await waitFor(() => expect(saveMarketProfile).toHaveBeenCalledTimes(1));
    expect(saveMarketProfile.mock.calls[0][0].extra_markets).toEqual([{ country: 'SA', subdivision: '' }]);
  });

  it('marks the market default inside the option text', () => {
    wrap(<MarketSettings />);
    const units = screen.getByTestId('market-units');
    expect(units.options[0].textContent).toMatch(/market\.default_for|default for/);
  });

  it('shows the empty regional hint when no pack matches', () => {
    scopeState = { data: scope({ packs: [] }) };
    wrap(<MarketSettings />);
    expect(screen.getByText(/market\.regional_empty|No regional pack/)).toBeTruthy();
  });
});

describe('MarketSummary (onboarding)', () => {
  it('renders nothing before the scope loads', () => {
    scopeState = { data: undefined };
    const { container } = wrap(<MarketSummary />);
    expect(container.querySelector('[data-testid="market-onboarding-summary"]')).toBeNull();
  });

  it('lists the standards, units and tax profile the market sets up', () => {
    scopeState = {
      data: scope({
        units_system: 'metric',
        standards: { classification: 'din276', measurement: 'vob_c', contract_family: 'vob_b', tax_profile: 'xrechnung' },
      }),
    };
    wrap(<MarketSummary />);
    const text = screen.getByTestId('market-onboarding-summary').textContent;
    for (const part of ['DIN276', 'VOB C', 'VOB B', 'METRIC', 'XRECHNUNG']) expect(text).toContain(part);
  });

  it('omits the "both" units placeholder and hides entirely with nothing to say', () => {
    scopeState = { data: scope({ units_system: 'both', standards: {} }) };
    const { container } = wrap(<MarketSummary />);
    expect(container.querySelector('[data-testid="market-onboarding-summary"]')).toBeNull();
  });
});

describe('ModulesSettings other markets', () => {
  const mods = [
    ['dach_pack', true],
    ['sa_pack', false],
    ['takeoff', true],
  ].map(([name, enabled]) => ({
    name: `oe_${name}`,
    version: '1.0.0',
    display_name: name,
    description: '',
    author: '',
    category: 'regional',
    depends: [],
    optional_depends: [],
    has_router: true,
    loaded: true,
    enabled,
    is_core: false,
  }));

  beforeEach(() => apiGet.mockResolvedValue(mods));

  it('hides other-market rows and offers no toggle to a non-admin', async () => {
    role = 'viewer';
    wrap(<ModulesSettings />);
    await screen.findByText('dach_pack');
    expect(screen.queryByText('sa_pack')).toBeNull();
    expect(screen.queryByTestId('modules-show-other-markets')).toBeNull();
  });

  it('lets an admin reveal them greyed, with an Add this market action', async () => {
    wrap(<ModulesSettings />);
    await screen.findByText('dach_pack');
    expect(screen.queryByTestId('module-other-market-oe_sa_pack')).toBeNull();
    const toggle = screen.getByTestId('modules-show-other-markets');
    expect(toggle.getAttribute('role')).toBe('switch');
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    fireEvent.click(toggle);
    const row = await screen.findByTestId('module-other-market-oe_sa_pack');
    expect(row.textContent).toMatch(/market\.other_badge|Other market/);
    expect(row.textContent).toMatch(/market\.add_this|Add this market/);
    expect(screen.getByTestId('modules-show-other-markets').getAttribute('aria-checked')).toBe('true');
  });

  it('opens the Add-market preview prefilled and saves only on confirm', async () => {
    previewMarketProfile.mockResolvedValue({ ...scope(), hidden_modules: ['us_pack'], suggested_packages: [] });
    saveMarketProfile.mockResolvedValue(scope());
    wrap(<ModulesSettings />);
    await screen.findByText('dach_pack');
    fireEvent.click(screen.getByTestId('modules-show-other-markets'));
    const row = await screen.findByTestId('module-other-market-oe_sa_pack');
    fireEvent.click(row.querySelector('button:not([role="switch"])') as HTMLElement);
    expect(await screen.findByTestId('market-preview-modal')).toBeTruthy();
    const expected = profile(['SA']);
    await waitFor(() => expect(previewMarketProfile).toHaveBeenCalledWith(expected));
    expect(saveMarketProfile).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId('market-preview-confirm'));
    await waitFor(() => expect(saveMarketProfile).toHaveBeenCalledWith(expected));
  });

  it('shows no toggle when nothing is hidden', async () => {
    scopeState = { data: scope({ hidden_modules: [] }) };
    wrap(<ModulesSettings />);
    await screen.findByText('dach_pack');
    expect(screen.queryByTestId('modules-show-other-markets')).toBeNull();
  });
});

describe('MarketSettings e-invoicing card', () => {
  const einvoice = { einvoice_clearance: ['DE', 'IT', 'SA'] };

  it('shows the setup card for a DE tenant (a mandate market)', () => {
    scopeState = { data: scope({ module_markets: { ...scope().module_markets, ...einvoice } }) };
    wrap(<MarketSettings />);
    expect(screen.getByTestId('einvoice-setup-card').getAttribute('data-can-edit')).toBe('true');
  });

  it('hides the setup card for a US-only tenant', () => {
    scopeState = {
      data: scope({
        markets: ['US'],
        expanded_markets: ['US'],
        hidden_modules: ['einvoice_clearance'],
        module_markets: { ...scope().module_markets, ...einvoice },
      }),
    };
    wrap(<MarketSettings />);
    expect(screen.queryByTestId('einvoice-setup-card')).toBeNull();
  });

  it('hides the setup card when the tenant market has no mandate', () => {
    scopeState = { data: scope({ markets: ['US'], expanded_markets: ['US'], module_markets: einvoice }) };
    wrap(<MarketSettings />);
    expect(screen.queryByTestId('einvoice-setup-card')).toBeNull();
  });
});
