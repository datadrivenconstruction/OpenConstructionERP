// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Import is the arrow into the tray, export the arrow out of it (the pair every
// spreadsheet and CAD tool uses). The hub's tabs and its two action buttons
// carry that pair, so a swap here shows up as a test failure, not as a bug report.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const apiGet = vi.fn();

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return {
    ...actual,
    apiGet: (path: string) => apiGet(path),
    downloadWithAuth: vi.fn(async () => undefined),
    getAuthToken: () => 'test-token',
  };
});

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector?: (s: { addToast: unknown }) => unknown) => {
    const state = { addToast: vi.fn() };
    return selector ? selector(state) : state.addToast;
  },
}));

vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (selector?: (s: { activeProjectId: string | null }) => unknown) => {
    const state = { activeProjectId: null };
    return selector ? selector(state) : state;
  },
}));

import RegionalExchangeHubPage from './RegionalExchangeHubPage';

const FORMAT = {
  format_id: 'excel',
  name: 'Spreadsheet workbook',
  countries: [],
  extensions: ['.xlsx', '.csv'],
  summary: 'Any workbook with a row per item.',
  standard: '',
  rule_packs: [],
  header_language: null,
  import_support: 'native',
  export_support: 'native',
  export_route: 'export/excel',
  export_extension: '.xlsx',
  export_media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
};

function iconOf(el: HTMLElement): string | null {
  const svg = el.querySelector('svg');
  return svg ? svg.getAttribute('class') : null;
}

beforeEach(() => {
  apiGet.mockReset();
  apiGet.mockImplementation(async (path: string) =>
    path.includes('exchange-formats')
      ? { formats: [FORMAT], country: null, default_format_id: 'excel', header_languages: ['en'] }
      : [],
  );
});

describe('the hub import and export arrows', () => {
  it('draws import as the arrow into the tray and export as the arrow out of it', async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/regional-exchange']}>
          <RegionalExchangeHubPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const importTab = await screen.findByTestId('exchange-tab-import');
    const exportTab = screen.getByTestId('exchange-tab-export');
    expect(iconOf(importTab)).toContain('lucide-download');
    expect(iconOf(exportTab)).toContain('lucide-upload');

    await waitFor(() => expect(screen.getByTestId('exchange-import')).toBeInTheDocument());
    expect(iconOf(screen.getByTestId('exchange-import'))).toContain('lucide-download');
    await user.click(exportTab);
    const exportButton = await screen.findByTestId('exchange-export');
    expect(iconOf(exportButton)).toContain('lucide-upload');
  });
});
