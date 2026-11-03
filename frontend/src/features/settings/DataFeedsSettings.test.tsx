// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for <DataFeedsSettings>: the copied URL carries the chosen
// project, a new key's secret is shown once and never again, the SQL card
// appears only when the server says it is enabled, and a person with no
// project is told to create one instead of seeing an empty table.
//
// The i18n mock in src/test/setup.ts returns the defaultValue when a call
// passes one, so the English strings below are what the component renders.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn() };
});
vi.mock('@/shared/lib/browser', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/browser')>('@/shared/lib/browser');
  return { ...actual, copyToClipboard: vi.fn().mockResolvedValue(true) };
});
vi.mock('@/features/projects/api', () => ({ projectsApi: { list: vi.fn() } }));

import * as api from '@/shared/lib/api';
import * as browser from '@/shared/lib/browser';
import { projectsApi } from '@/features/projects/api';
import { DataFeedsSettings, feedPath, feedUrl, powerQuerySnippet } from './DataFeedsSettings';

const apiGet = vi.mocked(api.apiGet);
const apiPost = vi.mocked(api.apiPost);
const copyToClipboard = vi.mocked(browser.copyToClipboard);
const listProjects = vi.mocked(projectsApi.list);

const PROJECT = { id: 'p-1', name: 'Harbour Office' };
const FEEDS = [
  {
    id: 'invoices',
    title_key: 'bi_feed.feed.invoices',
    columns: [
      { name: 'id', kind: 'uuid' },
      { name: 'amount_total', kind: 'money' },
      { name: 'currency', kind: 'text' },
    ],
    row_count: 12,
  },
  { id: 'projects', title_key: 'bi_feed.feed.projects', columns: [{ name: 'id', kind: 'uuid' }], row_count: 1 },
];
const KEY = { id: 'k-1', name: 'Existing', key_prefix: 'oe_abcdef', is_active: true, permissions: ['bi:read'] };

function serve(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    '/v1/bi-feed/feeds': FEEDS,
    '/v1/bi-feed/sql-status': { enabled: false, schema_name: 'oe_bi', role: 'oe_bi_reader', views: [] },
    '/v1/users/me/api-keys/': [KEY],
    '/v1/bi-feed/feeds/invoices.json?project_id=p-1&limit=20': { columns: [], total: 0, rows: [] },
    '/v1/bi-feed/feeds/invoices.json?limit=20': {
      columns: FEEDS[0]!.columns,
      total: 1,
      rows: [{ id: 'i-1', amount_total: '1005.000000', currency: 'EUR' }],
    },
    ...overrides,
  };
  apiGet.mockImplementation(async (path: string) => {
    if (!(path in routes)) throw new Error(`unexpected GET ${path}`);
    return routes[path] as never;
  });
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DataFeedsSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  copyToClipboard.mockResolvedValue(true);
  listProjects.mockResolvedValue([PROJECT] as never);
  serve();
});

describe('url helpers', () => {
  it('scopes the path to a project and limit', () => {
    expect(feedPath('invoices', 'csv', '')).toBe('/v1/bi-feed/feeds/invoices.csv');
    expect(feedPath('invoices', 'json', 'p-1', 20)).toBe('/v1/bi-feed/feeds/invoices.json?project_id=p-1&limit=20');
    expect(feedUrl('invoices', 'parquet', 'p-1')).toMatch(/\/api\/v1\/bi-feed\/feeds\/invoices\.parquet\?project_id=p-1$/);
  });

  it('puts the key in the X-API-Key header of the Power Query snippet', () => {
    const m = powerQuerySnippet('https://x/api/v1/bi-feed/feeds/invoices.csv', 'oe_secret');
    expect(m).toContain('[#"X-API-Key" = "oe_secret"]');
    expect(m).toContain('Web.Contents("https://x/api/v1/bi-feed/feeds/invoices.csv"');
  });
});

describe('<DataFeedsSettings>', () => {
  it('lists the feeds with their column and row counts', async () => {
    renderPanel();
    const row = (await screen.findByTestId('bi-feed-copy-csv-invoices')).closest('tr')!;
    expect(row.textContent).toContain('3');
    expect(row.textContent).toContain('12');
  });

  it('copies a CSV URL that carries the chosen project', async () => {
    renderPanel();
    const select = await screen.findByTestId('bi-feed-project');
    await screen.findByRole('option', { name: 'Harbour Office' });
    fireEvent.change(select, { target: { value: 'p-1' } });
    fireEvent.click(await screen.findByTestId('bi-feed-copy-csv-invoices'));
    await waitFor(() => expect(copyToClipboard).toHaveBeenCalledTimes(1));
    expect(copyToClipboard.mock.calls[0]![0]).toMatch(/\/api\/v1\/bi-feed\/feeds\/invoices\.csv\?project_id=p-1$/);
  });

  it('copies a Parquet URL without a project filter by default', async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId('bi-feed-copy-parquet-projects'));
    await waitFor(() => expect(copyToClipboard).toHaveBeenCalledTimes(1));
    expect(copyToClipboard.mock.calls[0]![0]).toMatch(/\/api\/v1\/bi-feed\/feeds\/projects\.parquet$/);
  });

  it('previews 20 rows of the selected feed', async () => {
    renderPanel();
    const table = await screen.findByTestId('bi-feed-preview');
    expect(table.textContent).toContain('1005.000000');
    expect(apiGet).toHaveBeenCalledWith('/v1/bi-feed/feeds/invoices.json?limit=20');
  });

  it('creates a key with only the bi:read scope and shows the secret once', async () => {
    apiPost.mockResolvedValue({ ...KEY, id: 'k-2', name: 'Data feeds', key: 'oe_full_secret_value' } as never);
    renderPanel();
    fireEvent.click(await screen.findByTestId('bi-feed-create-key'));
    const box = await screen.findByTestId('bi-feed-new-key');
    expect(box.textContent).toContain('oe_full_secret_value');
    expect(apiPost).toHaveBeenCalledWith(
      '/v1/users/me/api-keys/',
      expect.objectContaining({ permissions: ['bi:read'] }),
    );
    // The snippet carries the new key while it is on screen.
    expect(screen.getByTestId('bi-feed-powerquery').textContent).toContain('oe_full_secret_value');

    fireEvent.click(screen.getByTestId('bi-feed-dismiss-key'));
    expect(screen.queryByTestId('bi-feed-new-key')).toBeNull();
    expect(screen.getByTestId('bi-feed-powerquery').textContent).not.toContain('oe_full_secret_value');
  });

  it('shows the Excel hint and no SQL card while SQL access is off', async () => {
    renderPanel();
    expect(await screen.findByTestId('bi-feed-excel-hint')).toBeTruthy();
    expect(screen.queryByTestId('bi-feed-sql')).toBeNull();
  });

  it('shows the SQL card, without any password, when SQL access is enabled', async () => {
    serve({
      '/v1/bi-feed/sql-status': { enabled: true, schema_name: 'oe_bi', role: 'oe_bi_reader', views: ['invoices'] },
    });
    renderPanel();
    const card = await screen.findByTestId('bi-feed-sql');
    expect(card.textContent).toContain('oe_bi_reader');
    expect(card.textContent).toContain('oe_bi.invoices');
    expect(card.textContent?.toLowerCase()).not.toContain('password');
  });

  it('tells a person with no project to create one', async () => {
    listProjects.mockResolvedValue([] as never);
    renderPanel();
    const empty = await screen.findByTestId('bi-feed-empty');
    expect(empty.textContent).toContain('Create a project first');
    expect(screen.queryByTestId('bi-feed-table')).toBeNull();
  });
});
