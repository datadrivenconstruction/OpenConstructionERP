// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render as rtlRender, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement } from 'react';

const apiMocks = vi.hoisted(() => ({ getCodeList: vi.fn() }));
vi.mock('@/features/costmodel/structureApi', () => ({
  costStructureApi: { getCodeList: apiMocks.getCodeList },
}));

import { ClassificationPicker, buildClassificationTree } from './ClassificationPicker';

const LISTS: Record<string, { code: string; title: string; parent: string | null; level: number }[]> = {
  din276: [
    { code: '100', title: 'Grundstück / Land', parent: null, level: 1 },
    { code: '110', title: 'Grundstückswert / Land value', parent: '100', level: 2 },
    { code: '300', title: 'Bauwerk - Baukonstruktionen / Building construction', parent: null, level: 1 },
    { code: '330', title: 'Außenwände / External walls', parent: '300', level: 2 },
    { code: '340', title: 'Innenwände / Internal walls', parent: '300', level: 2 },
    { code: '400', title: 'Bauwerk - Technische Anlagen / Building services', parent: null, level: 1 },
    { code: '700', title: 'Baunebenkosten / Incidental building costs', parent: null, level: 1 },
  ],
  nrm: [
    { code: '1', title: 'Substructure', parent: null, level: 1 },
    { code: '2', title: 'Superstructure', parent: null, level: 1 },
  ],
};

beforeEach(() => {
  apiMocks.getCodeList.mockReset();
  apiMocks.getCodeList.mockImplementation(async (key: string) => ({
    key,
    name: key.toUpperCase(),
    standard: key,
    source: 'builtin',
    pack_slug: null,
    entry_count: LISTS[key]?.length ?? 0,
    depth: 2,
    entries: LISTS[key] ?? [],
  }));
});

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('buildClassificationTree', () => {
  it('nests entries under their parents and keeps orphans as roots', () => {
    const tree = buildClassificationTree([
      { code: '300', title: 'A', parent: null, level: 1 },
      { code: '330', title: 'B', parent: '300', level: 2 },
      { code: '999', title: 'C', parent: 'gone', level: 2 },
    ]);
    expect(tree.map((n) => n.code)).toEqual(['300', '999']);
    expect(tree[0]!.children!.map((n) => n.code)).toEqual(['330']);
  });
});

describe('ClassificationPicker', () => {
  it('should render dropdown trigger with placeholder when no value', async () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    expect(screen.getByText(/^Classification\.\.\./)).toBeInTheDocument();
  });

  it('should render selected code when value is provided', async () => {
    render(
      <ClassificationPicker
        standard="din276"
        value="330"
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    expect(screen.getByText('330')).toBeInTheDocument();
    // The label comes from the list once it has loaded, cut at the first slash.
    expect(await screen.findByText(/Außenwände/)).toBeInTheDocument();
  });

  it('should open dropdown on click', async () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText(/^Classification\.\.\./));
    // Should show the search input and DIN 276 label
    expect(screen.getByText('DIN276')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/^Search\.\.\./)).toBeInTheDocument();
  });

  it('should show DIN 276 tree root nodes', async () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText(/^Classification\.\.\./));

    // Top-level DIN 276 codes
    expect(await screen.findByText('100')).toBeInTheDocument();
    expect(screen.getByText('300')).toBeInTheDocument();
    expect(screen.getByText('400')).toBeInTheDocument();
    expect(screen.getByText('700')).toBeInTheDocument();
  });

  it('should show NRM tree when standard is nrm', async () => {
    render(
      <ClassificationPicker
        standard="nrm"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText(/^Classification\.\.\./));

    expect(screen.getByText('NRM')).toBeInTheDocument();
    expect(await screen.findByText('Substructure')).toBeInTheDocument();
    expect(screen.getByText('Superstructure')).toBeInTheDocument();
  });

  it('should call onSelect when a node is clicked', async () => {
    const onSelect = vi.fn();
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={onSelect}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText(/^Classification\.\.\./));

    // Click on the "100" code node
    const node100 = await screen.findByText('100');
    fireEvent.click(node100);

    expect(onSelect).toHaveBeenCalledWith('100', expect.any(String));
  });

  it('should filter items by search query', async () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText(/^Classification\.\.\./));

    const searchInput = screen.getByPlaceholderText(/^Search\.\.\./);
    fireEvent.change(searchInput, { target: { value: 'wall' } });

    // Should find wall-related items (multiple matches expected)
    const wallItems = await screen.findAllByText(/wall/i);
    expect(wallItems.length).toBeGreaterThan(0);
  });

  it('should render inline mode without trigger button', async () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="inline"
      />,
    );
    // Should immediately show tree content
    expect(await screen.findByText('100')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/^Search\.\.\./)).toBeInTheDocument();
  });

  it('should highlight selected value', async () => {
    render(
      <ClassificationPicker
        standard="din276"
        value="300"
        onSelect={vi.fn()}
        mode="inline"
      />,
    );
    // The selected node should have the oe-blue color class
    const selected = await screen.findByText('300');
    expect(selected.closest('button')).toHaveClass('bg-oe-blue/10');
  });

  it('should clear search on X button click', async () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="inline"
      />,
    );
    const searchInput = screen.getByPlaceholderText(/^Search\.\.\./);
    fireEvent.change(searchInput, { target: { value: 'concrete' } });

    // Find and click the X button
    const clearButton = searchInput.parentElement?.querySelector('button');
    if (clearButton) {
      fireEvent.click(clearButton);
      expect(searchInput).toHaveValue('');
    }
  });

  it('asks the API for the list named by the standard prop', async () => {
    render(<ClassificationPicker standard="nrm" projectId="p1" value={null} onSelect={vi.fn()} mode="inline" />);
    await screen.findByText('Superstructure');
    expect(apiMocks.getCodeList).toHaveBeenCalledWith('nrm', 'p1');
  });

  it('says so when the list cannot be loaded', async () => {
    apiMocks.getCodeList.mockRejectedValueOnce(new Error('boom'));
    render(<ClassificationPicker standard="din276" value={null} onSelect={vi.fn()} mode="inline" />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/could not be loaded/));
  });
});
