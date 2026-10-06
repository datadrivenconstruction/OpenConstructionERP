// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Exercise the editor's actual file input and confirmation, not the preview dialog.
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ImportToastResult } from '../importToastText';

vi.mock('react-i18next', () => {
  const labels: Record<string, string> = { 'common.import': 'Import', 'common.cancel': 'Cancel' };
  const t = (key: string, options?: Record<string, unknown>) => {
    const text = labels[key] ?? (typeof options?.defaultValue === 'string' ? options.defaultValue : key);
    return text.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? name));
  };
  const value = { t, i18n: { language: 'en', changeLanguage: () => {} } };
  return {
    useTranslation: () => value,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

vi.mock('../BOQGrid', () => ({
  default: React.forwardRef(function Grid(_props, _ref) {
    return <div data-testid="toolbar-import-grid" />;
  }),
}));
vi.mock('@/features/bim/api', () => ({ fetchBIMModels: vi.fn().mockResolvedValue({ items: [], total: 0 }) }));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    boqApi: {
      ...actual.boqApi,
      get: vi.fn(async () => ({
        id: 'boq-toolbar', project_id: 'project-toolbar', name: 'Import test bill',
        status: 'draft', is_locked: false,
        positions: [{
          id: 'position-toolbar', boq_id: 'boq-toolbar', parent_id: null, ordinal: '1',
          description: 'Concrete wall', unit: 'm2', quantity: 10, unit_rate: 50, total: 500,
          classification: {}, source: 'manual', confidence: null, validation_status: 'pending',
          sort_order: 0, metadata: {},
        }],
      })),
      getMarkups: vi.fn(async () => ({ markups: [] })),
      getCostBreakdown: vi.fn(async () => ({
        boq_id: 'boq-toolbar', grand_total: 500, direct_cost: 500,
        categories: [], markups: [], top_resources: [],
      })),
      getLimits: vi.fn(async () => ({ max_nesting_depth: 5 })),
      getActivity: vi.fn(async () => []),
    },
  };
});
vi.mock('@/features/projects/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/projects/api')>();
  return { ...actual, projectsApi: { ...actual.projectsApi,
    get: vi.fn(async () => ({ id: 'project-toolbar', name: 'Import test project', currency: 'EUR', fx_rates: [] })),
  } };
});

import { BOQEditorPage } from '../BOQEditorPage';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

const clients: QueryClient[] = [];
const posts: { url: string; form: FormData }[] = [];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function duplicate() {
  return json({ detail: { code: 'import_already_done', params: {
    imported_at: '2026-10-01T09:30:00+00:00', job_id: 'earlier-job',
  } } }, 409);
}

function respondWith(...responses: Response[]) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes('/import/auto/')) {
      posts.push({ url, form: init?.body as FormData });
      const response = responses.shift();
      if (!response) throw new Error('Unexpected additional import');
      return response;
    }
    if (url.includes('/v1/modules/')) return json([]);
    return json({ items: [], total: 0 });
  });
}

async function chooseFile() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } } });
  clients.push(client);
  render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={['/boq/boq-toolbar']}>
      <Routes><Route path="/boq/:boqId" element={<BOQEditorPage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
  await screen.findByTestId('toolbar-import-grid', {}, { timeout: 15_000 });
  const file = new File(['<PweDocument />'], 'computo.xpwe', { type: 'application/xml' });
  const input = screen.getByLabelText('Import', { selector: 'input' });
  fireEvent.change(input, { target: { files: [file] } });
  await waitFor(() => expect(posts).toHaveLength(1));
  return file;
}

beforeEach(() => {
  posts.length = 0;
  useAuthStore.setState({ userRole: 'editor' });
  useToastStore.setState({ toasts: [] });
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.restoreAllMocks();
  useToastStore.setState({ toasts: [] });
});

describe('importing the same file again from the editor toolbar', () => {
  it('waits for confirmation, then posts the same file with an explicit force flag', async () => {
    respondWith(duplicate(), json({ imported: 2, errors: [], warnings: [] } satisfies ImportToastResult));
    const file = await chooseFile();
    const confirm = await screen.findByRole('button', { name: 'Import again' });
    expect(posts).toHaveLength(1);
    expect(posts[0]?.url).toBe('/api/v1/boq/boqs/boq-toolbar/import/auto/?background=true');
    expect(useToastStore.getState().toasts.some((toast) => toast.type === 'success')).toBe(false);
    fireEvent.click(confirm);
    await waitFor(() => expect(useToastStore.getState().toasts.some((toast) => toast.type === 'success')).toBe(true));
    expect(posts).toHaveLength(2);
    expect(posts[1]?.url).toBe('/api/v1/boq/boqs/boq-toolbar/import/auto/?background=true&force=true');
    expect(posts[0]?.form.get('file')).toBe(file);
    expect(posts[1]?.form.get('file')).toBe(file);
  });

  it('cancels without forcing another import or reporting success', async () => {
    respondWith(duplicate());
    await chooseFile();
    await screen.findByRole('button', { name: 'Import again' });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Import again' })).toBeNull());
    expect(posts).toHaveLength(1);
    expect(useToastStore.getState().toasts.some((toast) => ['success', 'error'].includes(toast.type))).toBe(false);
  });

  it('does not treat a different 409 as permission to repeat the import', async () => {
    respondWith(json({ detail: 'This bill is locked.' }, 409));
    await chooseFile();
    await waitFor(() => expect(useToastStore.getState().toasts.some((toast) => toast.type === 'error')).toBe(true));
    expect(screen.queryByRole('button', { name: 'Import again' })).toBeNull();
    expect(posts).toHaveLength(1);
  });

  it('reports a failed forced import without retrying it automatically', async () => {
    respondWith(duplicate(), json({ detail: 'Import storage unavailable.' }, 500));
    await chooseFile();
    fireEvent.click(await screen.findByRole('button', { name: 'Import again' }));
    await waitFor(() => expect(useToastStore.getState().toasts.some((toast) => toast.type === 'error')).toBe(true));
    expect(posts).toHaveLength(2);
    expect(useToastStore.getState().toasts.some((toast) => toast.type === 'success')).toBe(false);
  });
});
