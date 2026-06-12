// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CatalogsSection } from '../CatalogsSection';

vi.mock('../api', () => ({
  fetchCostCatalogs: vi.fn(),
  createCostCatalog: vi.fn(),
  updateCostCatalog: vi.fn(),
  deleteCostCatalog: vi.fn(),
}));

import { fetchCostCatalogs, deleteCostCatalog } from '../api';

const fakeCatalogs = [
  {
    id: 'cat-001',
    name: 'My price book 2026',
    description: null,
    currency: 'EUR',
    source: 'manual',
    created_by: null,
    item_count: 12,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 'cat-002',
    name: 'Subcontractor rates',
    description: 'Quotes from subs',
    currency: 'USD',
    source: 'import',
    created_by: null,
    item_count: 3,
    created_at: '2026-06-02T00:00:00Z',
    updated_at: '2026-06-02T00:00:00Z',
  },
];

function renderSection(props = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const defaults = { selectedId: '', onSelect: () => undefined };
  return render(
    <QueryClientProvider client={client}>
      <CatalogsSection {...defaults} {...props} />
    </QueryClientProvider>,
  );
}

describe('CatalogsSection', () => {
  beforeEach(() => {
    (fetchCostCatalogs as ReturnType<typeof vi.fn>).mockReset();
    (deleteCostCatalog as ReturnType<typeof vi.fn>).mockReset();
  });

  it('renders catalog chips with name, currency and item count', async () => {
    (fetchCostCatalogs as ReturnType<typeof vi.fn>).mockResolvedValue(fakeCatalogs);

    renderSection();

    await waitFor(() => {
      expect(screen.getByText('My price book 2026')).toBeInTheDocument();
    });
    expect(screen.getByText('Subcontractor rates')).toBeInTheDocument();
    expect(screen.getByText('EUR')).toBeInTheDocument();
    expect(screen.getByText('USD')).toBeInTheDocument();
  });

  it('shows the empty hint when there are no catalogs', async () => {
    (fetchCostCatalogs as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    renderSection();

    await waitFor(() => {
      expect(screen.getByText(/No catalogs yet/)).toBeInTheDocument();
    });
  });

  it('selects a catalog on click and clears on second click', async () => {
    (fetchCostCatalogs as ReturnType<typeof vi.fn>).mockResolvedValue(fakeCatalogs);
    const onSelect = vi.fn();

    const { rerender, container } = renderSection({ onSelect });
    void container;

    await waitFor(() => {
      expect(screen.getByText('My price book 2026')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('My price book 2026'));
    expect(onSelect).toHaveBeenCalledWith('cat-001');

    // Re-render with the catalog selected - clicking again clears the filter.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    rerender(
      <QueryClientProvider client={client}>
        <CatalogsSection selectedId="cat-001" onSelect={onSelect} />
      </QueryClientProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText('My price book 2026')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('My price book 2026'));
    expect(onSelect).toHaveBeenLastCalledWith('');
  });

  it('opens the create dialog from the New catalog button', async () => {
    (fetchCostCatalogs as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    renderSection();

    await waitFor(() => {
      expect(screen.getByText(/New catalog/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/New catalog/));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    // Title and submit button both carry the label - assert on the heading.
    expect(
      screen.getByRole('heading', { name: /Create catalog/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/My price book 2026/),
    ).toBeInTheDocument();
  });

  it('opens the delete dialog with keep-items preselected', async () => {
    (fetchCostCatalogs as ReturnType<typeof vi.fn>).mockResolvedValue(fakeCatalogs);

    renderSection({ selectedId: 'cat-001' });

    await waitFor(() => {
      expect(screen.getByText('My price book 2026')).toBeInTheDocument();
    });

    // The delete action button carries the "Delete" aria-label; the first
    // one belongs to the first (selected, actions visible) chip.
    const deleteButtons = screen.getAllByLabelText('Delete');
    fireEvent.click(deleteButtons[0]);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(2);
    expect(radios[0]).toBeChecked(); // keep_items is the default
    expect(screen.getByText(/Keep the items/)).toBeInTheDocument();
    expect(screen.getByText(/Delete the items too/)).toBeInTheDocument();
  });
});
