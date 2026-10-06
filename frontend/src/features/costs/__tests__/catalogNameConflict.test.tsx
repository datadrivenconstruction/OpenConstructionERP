// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18next from 'i18next';
import { CatalogsSection } from '../CatalogsSection';
import { useToastStore } from '@/stores/useToastStore';

const clients: QueryClient[] = [];
afterEach(async () => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  useToastStore.getState().toasts.forEach((toast) => useToastStore.getState().removeToast(toast.id));
  useToastStore.getState().clearHistory();
  vi.unstubAllGlobals();
  await i18next.changeLanguage('en');
});

it('shows the localized structured 409, retains the form and lets the user choose a new name', async () => {
  await i18next.init({ lng: 'de', fallbackLng: 'en', resources: {}, initAsync: false });
  const german = 'Dieser Name kann nicht für einen neuen Katalog verwendet werden. Wählen Sie einen anderen Namen.';
  const secret = 'Private <customer> PRICEBOOK';
  const attempts: { body: unknown; language: string | null }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    // The API client also reports failures to its local diagnostic endpoint;
    // that POST is not a retry of catalog creation.
    if (init?.method !== 'POST' || !String(input).includes('/v1/costs/catalogs/')) {
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    attempts.push({ body: JSON.parse(String(init.body)), language: new Headers(init.headers).get('Accept-Language') });
    if (attempts.length === 1) {
      return new Response(JSON.stringify({ detail: { code: 'catalog_name_unavailable', message: german } }), {
        status: 409, headers: { 'Content-Type': 'application/json' },
      });
    }
    return new Response(JSON.stringify({
      id: 'catalog-created', name: 'New catalogue', currency: 'EUR', description: null,
      source: 'manual', created_by: 'owner', item_count: 0, created_at: '', updated_at: '',
    }), { status: 201, headers: { 'Content-Type': 'application/json' } });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
  clients.push(client);
  const onSelect = vi.fn();
  render(<QueryClientProvider client={client}><CatalogsSection selectedId="" onSelect={onSelect} /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole('button', { name: /New catalog/ }));
  const dialog = screen.getByRole('dialog');
  const name = within(dialog).getByPlaceholderText('e.g. My price book 2026');
  fireEvent.change(name, { target: { value: secret } });
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'EUR' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Create catalog' }));
  await waitFor(() => expect(useToastStore.getState().toasts.some((toast) => toast.message === german)).toBe(true));
  expect(useToastStore.getState().toasts.some((toast) => toast.message?.includes(secret))).toBe(false);
  expect(attempts).toHaveLength(1);
  expect(attempts[0]?.language).toBe('de');
  expect(name).toHaveValue(secret);
  expect(dialog).toBeVisible();

  fireEvent.change(name, { target: { value: 'New catalogue' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Create catalog' }));
  await waitFor(() => expect(onSelect).toHaveBeenCalledWith('catalog-created'));
  expect(attempts).toHaveLength(2);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
