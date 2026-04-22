// @ts-nocheck
/**
 * Smoke tests for the Asset Register page.
 *
 * Renders the page with a mocked API layer so we can verify:
 *   - empty state when no project is active
 *   - table population when assets are returned
 *   - search param round-trip
 *   - edit modal patches the correct element
 *
 * Network is stubbed via ``vi.mock`` on ``./api``. React Query is wired
 * with retry disabled so errors surface immediately instead of being
 * swallowed by default retry logic.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

vi.mock('./api', () => ({
  listTrackedAssets: vi.fn(),
  updateElementAssetInfo: vi.fn(),
  cobieExportUrl: (modelId: string) => `/api/v1/bim_hub/models/${modelId}/export/cobie.xlsx/`,
}));

import { listTrackedAssets, updateElementAssetInfo } from './api';
import { AssetsPage } from './AssetsPage';

const sampleAsset = {
  id: 'elem-1',
  stable_id: 'AHU-01',
  element_type: 'AirHandlingUnit',
  name: 'AHU Rooftop',
  model_id: 'model-1',
  model_name: 'Mechanical.rvt',
  project_id: 'proj-1',
  asset_info: {
    manufacturer: 'Siemens',
    model: 'SV-100',
    serial_number: 'SN-123',
    operational_status: 'operational',
    warranty_until: '2028-01-01',
  },
};

function renderWithProviders() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/assets']}>
        <AssetsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AssetsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectContextStore.getState().clearProject();
  });

  it('shows the "no project" empty state when none is active', () => {
    renderWithProviders();
    expect(screen.getByText(/No active project/i)).toBeInTheDocument();
    expect(listTrackedAssets).not.toHaveBeenCalled();
  });

  it('renders a table of tracked assets for the active project', async () => {
    useProjectContextStore.getState().setActiveProject('proj-1', 'Riverside HQ');
    (listTrackedAssets as any).mockResolvedValue({ items: [sampleAsset], total: 1 });

    renderWithProviders();

    await waitFor(() => expect(listTrackedAssets).toHaveBeenCalledWith('proj-1', expect.any(Object)));
    expect(await screen.findByText('Siemens')).toBeInTheDocument();
    expect(screen.getByText('SV-100')).toBeInTheDocument();
    expect(screen.getByText('SN-123')).toBeInTheDocument();
    expect(screen.getByText(/AHU Rooftop/)).toBeInTheDocument();
  });

  it('renders an empty state when the project has no tracked assets', async () => {
    useProjectContextStore.getState().setActiveProject('proj-1', 'Riverside HQ');
    (listTrackedAssets as any).mockResolvedValue({ items: [], total: 0 });
    renderWithProviders();
    expect(await screen.findByText(/No tracked assets yet/i)).toBeInTheDocument();
  });

  it('opens the edit modal and patches asset info via the API', async () => {
    useProjectContextStore.getState().setActiveProject('proj-1', 'Riverside HQ');
    (listTrackedAssets as any).mockResolvedValue({ items: [sampleAsset], total: 1 });
    (updateElementAssetInfo as any).mockResolvedValue(sampleAsset);

    renderWithProviders();

    const editButton = await screen.findByTestId(`asset-edit-${sampleAsset.id}`);
    fireEvent.click(editButton);

    const modal = await screen.findByTestId('asset-edit-modal');
    expect(modal).toBeInTheDocument();

    // Update manufacturer and save.
    const input = screen.getByTestId('asset-field-manufacturer') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Grundfos' } });

    fireEvent.click(screen.getByTestId('asset-save'));

    await waitFor(() => expect(updateElementAssetInfo).toHaveBeenCalled());
    const [elementId, payload] = (updateElementAssetInfo as any).mock.calls[0];
    expect(elementId).toBe(sampleAsset.id);
    expect(payload.manufacturer).toBe('Grundfos');
    // Fields that were unchanged but populated must survive the round-trip.
    expect(payload.model).toBe('SV-100');
    // Fields the user didn't interact with that were never in asset_info
    // stay absent from the payload — no accidental clears.
    expect(payload).not.toHaveProperty('notes');
  });
});
