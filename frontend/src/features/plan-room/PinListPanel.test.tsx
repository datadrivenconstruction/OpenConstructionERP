// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** The pin list filters by record kind and status through the API and links each row to its record. */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

import { apiGet } from '@/shared/lib/api';
import { PinListPanel } from './PinListPanel';
import type { RegistryPin } from './api';

function pin(over: Partial<RegistryPin>): RegistryPin {
  return {
    id: 'p1',
    project_id: 'proj-1',
    document_id: 'doc-1',
    page: 2,
    x: 0.2,
    y: 0.4,
    note: null,
    target_kind: 'rfi',
    target_id: 'r1',
    target_label: 'RFI-001 Slab edge',
    sheet_id: null,
    bim_model_id: null,
    bim_element_id: null,
    bim_xyz: null,
    status: 'open',
    revision_state: 'current',
    client_op_id: null,
    created_at: '2026-11-16T10:00:00Z',
    ...over,
  };
}

const ALL = [
  pin({}),
  pin({ id: 'p2', target_kind: 'ncr', target_id: 'n1', target_label: 'NCR-004 Honeycombing', status: 'closed' }),
  pin({ id: 'p3', target_kind: 'punch', target_id: 'u1', target_label: 'Crack at door', revision_state: 'needs_review' }),
];

function stub() {
  (apiGet as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    const params = new URL(url, 'http://x').searchParams;
    const kind = params.get('target_kind');
    const items = kind ? ALL.filter((p) => p.target_kind === kind) : ALL;
    return Promise.resolve({ items, total: items.length, offset: 0, limit: 200 });
  });
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PinListPanel projectId="proj-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('PinListPanel', () => {
  beforeEach(() => {
    (apiGet as ReturnType<typeof vi.fn>).mockReset();
    stub();
  });

  it('lists every pin with its record label and links to the record', async () => {
    renderPanel();
    expect(await screen.findByText('RFI-001 Slab edge')).toBeTruthy();
    expect(screen.getByText('NCR-004 Honeycombing')).toBeTruthy();
    const links = screen.getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual(
      expect.arrayContaining(['/rfi/r1', '/ncr?highlight=n1', '/punchlist?highlight=u1']),
    );
  });

  it('asks the API for one record kind when the kind filter changes', async () => {
    renderPanel();
    await screen.findByText('RFI-001 Slab edge');
    fireEvent.change(screen.getByLabelText('Record kind'), { target: { value: 'ncr' } });
    expect(await screen.findByText('NCR-004 Honeycombing')).toBeTruthy();
    expect(screen.queryByText('RFI-001 Slab edge')).toBeNull();
    const urls = (apiGet as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes('target_kind=ncr'))).toBe(true);
  });

  it('flags a pin that still needs review against the newer sheet', async () => {
    renderPanel();
    await screen.findByText('Crack at door');
    expect(screen.getAllByText(/needs review/i).length).toBeGreaterThan(0);
  });
});
