// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { Volume } from './volumesApi';
import { formatM3, netSide } from './volumesApi';
import { parseBoundary } from './VolumeDialogs';

const toast = vi.hoisted(() => ({ addToast: vi.fn() }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign((sel: (s: typeof toast) => unknown) => sel(toast), { getState: () => toast }),
}));
const ctx = vi.hoisted(() => ({ activeProjectId: 'p1' as string | null, setActiveProject: vi.fn() }));
vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (sel: (s: typeof ctx) => unknown) => sel(ctx),
}));
vi.mock('./SurveyPlan', () => ({ SurveyPlan: () => <div data-testid="plan" /> }));
vi.mock('./api', () => ({
  getProjectCrs: vi.fn(() => Promise.resolve({ crs: { epsg: 32633, name: 'WGS 84 / UTM zone 33N' } })),
  listPointSets: vi.fn(() => Promise.resolve([])),
}));

const v001: Volume = {
  id: 'v1', project_id: 'p1', code: 'V-001', name: 'Platform earthworks',
  base_surface_id: 's1', compare_surface_id: 's2', base_name: 'Existing ground', compare_name: 'Pad',
  method: 'grid', cell_size_m: 10, cell_auto: true, boundary: null, material: '', swell_factor: 1, shrink_factor: 1,
  cut_m3: 1470, fill_m3: 270, net_m3: 1200, loose_cut_m3: 1470, calc_area_m2: 10000, coverage_pct: 100,
  confidence: 1, crs_epsg: 32633, crs_name: '', accuracy_tier: 'survey', status: 'draft',
  confirmed_by_name: '', confirmed_at: null, override_reason: '', duplicated_from_id: null, boq_position_id: null,
  findings: [{ rule_id: 'VOL-004', severity: 'info', message: 'Bank volume.' }],
};

const api = vi.hoisted(() => ({
  listVolumes: vi.fn(),
  confirmVolume: vi.fn(),
}));
vi.mock('./volumesApi', async (orig) => ({
  ...(await orig<typeof import('./volumesApi')>()),
  listVolumes: api.listVolumes,
  confirmVolume: api.confirmVolume,
  listSurfaces: vi.fn(() => Promise.resolve([])),
  getVolumeSummary: vi.fn(() =>
    Promise.resolve({ cut_m3: 1470, fill_m3: 270, net_m3: 1200, coverage_pct: 100, calculations: 1, confirmed: 0 }),
  ),
  getVolumesPlan: vi.fn(() => Promise.resolve({ type: 'FeatureCollection', features: [] })),
  volumeHistory: vi.fn(() => Promise.resolve([])),
}));

import VolumesPage from './VolumesPage';

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <VolumesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('VolumesPage', () => {
  beforeEach(() => {
    ctx.activeProjectId = 'p1';
    api.listVolumes.mockResolvedValue([v001]);
    api.confirmVolume.mockResolvedValue({ ...v001, status: 'confirmed' });
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('lists V-001 with lesson 3 numbers and confirms it', async () => {
    mount();
    expect(await screen.findByText('V-001')).toBeTruthy();
    expect(screen.getAllByText(formatM3(1470, 'en')).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText('Platform earthworks'));
    const confirm = await screen.findByTestId('volume-confirm');
    expect((screen.getByTestId('volume-send') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(confirm);
    await waitFor(() => expect(api.confirmVolume).toHaveBeenCalledWith('v1', [], expect.any(String)));
  });

  it('holds Confirm until a warning is acknowledged', async () => {
    api.listVolumes.mockResolvedValue([
      { ...v001, coverage_pct: 50, findings: [{ rule_id: 'VOL-002', severity: 'warning', message: 'Low coverage.' }] },
    ]);
    mount();
    fireEvent.click(await screen.findByText('Platform earthworks'));
    const confirm = (await screen.findByTestId('volume-confirm')) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    await waitFor(() => expect(confirm.disabled).toBe(false));
    fireEvent.click(confirm);
    await waitFor(() => expect(api.confirmVolume).toHaveBeenCalledWith('v1', ['VOL-002'], expect.any(String)));
  });

  it('offers the demo when the project has no volumes', async () => {
    api.listVolumes.mockResolvedValue([]);
    mount();
    expect(await screen.findByTestId('volumes-open-demo')).toBeTruthy();
  });
});

describe('volume helpers', () => {
  it('reads the side of the net volume', () => {
    expect(netSide(1200)).toBe('cut');
    expect(netSide(-30)).toBe('fill');
    expect(netSide(0.01)).toBe('balanced');
  });
  it('parses a boundary ring and refuses fewer than three corners', () => {
    expect(parseBoundary('0 0\n50 0\n50 100\n0 100')).toEqual([[0, 0], [50, 0], [50, 100], [0, 100]]);
    expect(parseBoundary('0 0; 1 1')).toBeNull();
    expect(parseBoundary('0 0\n1 x\n2 2')).toBeNull();
  });
});
