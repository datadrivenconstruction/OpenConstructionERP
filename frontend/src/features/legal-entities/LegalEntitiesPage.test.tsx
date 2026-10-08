// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The legal entities page lists the group's companies to everyone and offers
// its forms only to an administrator, because the server refuses the writes
// from anyone else.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useAuthStore } from '@/stores/useAuthStore';

import type { LegalEntity } from './api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children?: unknown }) => children ?? null,
  initReactI18next: { type: '3rdParty', init: () => undefined },
}));

const list = vi.fn();

vi.mock('./api', async (importOriginal) => {
  const real = await importOriginal<typeof import('./api')>();
  return { ...real, legalEntitiesApi: { ...real.legalEntitiesApi, list: (...a: unknown[]) => list(...a) } };
});

const { LegalEntitiesPage } = await import('./LegalEntitiesPage');

const ENTITY: LegalEntity = {
  id: 'e1',
  code: 'DDC-DE',
  name: 'Example GmbH',
  country_code: 'DE',
  subdivision_code: null,
  functional_currency: 'EUR',
  registration_number: null,
  tax_id: 'DE123456789',
  is_default: true,
  is_active: true,
  metadata: {},
  branches: [
    {
      id: 'b1',
      legal_entity_id: 'e1',
      code: 'WAW',
      name: 'Warsaw',
      country_code: 'PL',
      subdivision_code: null,
      is_active: true,
      warnings: [],
    },
  ],
  created_at: '2026-10-08T00:00:00Z',
  updated_at: '2026-10-08T00:00:00Z',
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LegalEntitiesPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  list.mockReset();
  list.mockResolvedValue({ items: [ENTITY], total: 1 });
});

afterEach(() => cleanup());

describe('LegalEntitiesPage', () => {
  it('lists the entities with their branches and default mark', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderPage();
    expect(await screen.findByText('DDC-DE')).toBeTruthy();
    expect(screen.getByText('Warsaw')).toBeTruthy();
    expect(screen.getByText('Default')).toBeTruthy();
  });

  it('offers no write controls to someone who is not an administrator', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderPage();
    await screen.findByText('DDC-DE');
    expect(screen.queryByText('Add legal entity')).toBeNull();
    expect(screen.queryByText('Add branch')).toBeNull();
  });

  it('offers the forms to an administrator', async () => {
    useAuthStore.setState({ userRole: 'admin' });
    renderPage();
    await screen.findByText('DDC-DE');
    expect(screen.getByText('Add legal entity')).toBeTruthy();
    expect(screen.getByText('Add branch')).toBeTruthy();
  });

  it('says so when there are no entities', async () => {
    list.mockResolvedValue({ items: [], total: 0 });
    useAuthStore.setState({ userRole: 'viewer' });
    renderPage();
    expect(await screen.findByText(/No legal entities yet/)).toBeTruthy();
  });
});
