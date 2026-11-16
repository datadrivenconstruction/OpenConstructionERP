// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// The card must stay quiet on a single-company install (one line, no table)
// and show the table only once a second company exists.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

import * as api from '@/shared/lib/api';
import { CompaniesCard } from './CompaniesCard';
import type { LegalEntity } from './api';

const apiGetMock = vi.mocked(api.apiGet);

function company(over: Partial<LegalEntity>): LegalEntity {
  return {
    id: 'e1',
    code: 'HB',
    name: 'Muster Hochbau',
    country_code: 'DE',
    subdivision_code: null,
    functional_currency: 'EUR',
    registration_number: null,
    tax_id: null,
    legal_name: 'Muster Hochbau GmbH',
    address: null,
    tax_ids: [{ scheme: 'vat', value: 'DE123456789' }],
    invoice_prefix: null,
    is_default: true,
    is_active: true,
    metadata: {},
    branches: [],
    created_at: '',
    updated_at: '',
    primary_tax_id: 'DE123456789',
    project_count: 4,
    member_count: 0,
    has_own_einvoice_settings: false,
    warnings: [],
    ...over,
  };
}

function renderCard(items: LegalEntity[]) {
  apiGetMock.mockImplementation(async () => ({ items, total: items.length }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CompaniesCard canEdit />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CompaniesCard', () => {
  beforeEach(() => apiGetMock.mockReset());

  it('shows one calm line and no table for a single company', async () => {
    renderCard([company({})]);
    expect(await screen.findByTestId('companies-only-one')).toBeInTheDocument();
    expect(screen.queryByTestId('companies-table')).not.toBeInTheDocument();
  });

  it('lists every company with its tax id once a second one exists', async () => {
    renderCard([
      company({}),
      company({
        id: 'e2',
        code: 'TB',
        legal_name: 'Muster Tiefbau GmbH',
        is_default: false,
        primary_tax_id: 'DE987654321',
        project_count: 1,
      }),
    ]);
    const table = await screen.findByTestId('companies-table');
    expect(table).toHaveTextContent('Muster Tiefbau GmbH');
    expect(table).toHaveTextContent('DE987654321');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(2);
  });

  it('offers to add the first company when there is none', async () => {
    renderCard([]);
    expect(await screen.findByRole('button', { name: /add company/i })).toBeInTheDocument();
  });
});
