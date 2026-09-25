// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Send to tender" packaged the whole bill unless sections had been selected
// in the grid first, which nothing on the dialog said how to do. The dialog
// now lists the bill's top-level rows with every one ticked, so the default is
// still the whole bill and one section is two clicks away.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiPost: (url: string, body: unknown) => api.post(url, body) };
});

import { SendToTenderDialog, scopeToSend } from '../SendToTenderDialog';

const ROWS = [
  { id: 's1', ordinal: '01', description: 'Earthworks' },
  { id: 's2', ordinal: '02', description: 'Concrete' },
  { id: 's3', ordinal: '03', description: 'Roofing' },
];

function renderDialog(sectionIds: string[] = []) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SendToTenderDialog
        boqId="boq-1"
        projectId="proj-1"
        baseName="Tower"
        sectionIds={sectionIds}
        scopeRows={ROWS}
        isOpen
        onClose={() => {}}
        onCreated={() => {}}
      />
    </QueryClientProvider>,
  );
}

function create() {
  fireEvent.click(screen.getByRole('button', { name: /create package/i }));
}

beforeEach(() => {
  api.post.mockResolvedValue({ id: 'pkg-1', name: 'Tender - Tower' });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('scopeToSend', () => {
  it('sends an empty list for the whole bill, else the ticked rows in bill order', () => {
    expect(scopeToSend(ROWS, new Set(['s3', 's1', 's2']))).toEqual([]);
    expect(scopeToSend(ROWS, new Set(['s3', 's1']))).toEqual(['s1', 's3']);
  });
});

describe('SendToTenderDialog', () => {
  it('offers every top-level row, all ticked, and packages the whole bill by default', async () => {
    renderDialog();
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes).toHaveLength(3);
    boxes.forEach((b) => expect(b).toBeChecked());

    create();
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post.mock.calls[0]![1]).toMatchObject({ section_ids: [] });
  });

  it('packages one section when the others are unticked', async () => {
    renderDialog();
    fireEvent.click(screen.getByRole('checkbox', { name: /earthworks/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /roofing/i }));

    create();
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post.mock.calls[0]![1]).toMatchObject({ section_ids: ['s2'] });
  });

  it('starts from the grid selection when there is one', () => {
    renderDialog(['s2']);
    expect(screen.getByRole('checkbox', { name: /concrete/i })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /earthworks/i })).not.toBeChecked();
  });

  it('refuses to create a package with nothing ticked', () => {
    renderDialog(['s2']);
    fireEvent.click(screen.getByRole('checkbox', { name: /concrete/i }));
    expect(screen.getByRole('button', { name: /create package/i })).toBeDisabled();
  });
});
