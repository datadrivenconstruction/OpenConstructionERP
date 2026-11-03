import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const uploadOrthophoto = vi.fn();
vi.mock('../api', () => ({
  listSurveys: vi.fn(async () => []),
  listRasterOverlays: vi.fn(async () => []),
  getSurveyProgress: vi.fn(async () => []),
  uploadOrthophoto: (...args: unknown[]) => uploadOrthophoto(...args),
  surveyFromScan: vi.fn(),
  deleteSurvey: vi.fn(),
  putSurveyObservation: vi.fn(),
  updateRasterOverlay: vi.fn(),
}));
vi.mock('@/features/pointcloud/api', () => ({
  listScans: vi.fn(async () => ({ items: [], total: 0, offset: 0, limit: 50 })),
}));

import { SurveysPanel } from '../SurveysPanel';

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SurveysPanel projectId="p1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  uploadOrthophoto.mockReset();
});

describe('SurveysPanel', () => {
  it('explains what to do when there are no surveys', async () => {
    renderPanel();
    expect(await screen.findByTestId('geo-surveys-empty')).toHaveTextContent(
      'Upload a drone orthophoto, then record real progress per activity.',
    );
  });

  it('refuses to submit without a file or scan and shows why', async () => {
    renderPanel();
    await userEvent.click(screen.getByTestId('geo-surveys-submit'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a GeoTIFF or an existing scan.');
    expect(uploadOrthophoto).not.toHaveBeenCalled();
  });

  it('refuses a file that is not a tiff', async () => {
    renderPanel();
    const input = screen.getByTestId('geo-surveys-file') as HTMLInputElement;
    await userEvent.upload(input, new File(['x'], 'photo.png', { type: 'image/png' }), { applyAccept: false });
    await userEvent.click(screen.getByTestId('geo-surveys-submit'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Only .tif or .tiff files are accepted.');
    expect(uploadOrthophoto).not.toHaveBeenCalled();
  });

  it('uploads a tiff with the chosen date and platform', async () => {
    uploadOrthophoto.mockResolvedValue({
      id: 's1',
      project_id: 'p1',
      kind: 'orthophoto',
      platform: 'aircraft',
      captured_on: '2026-03-11',
      name: 'a',
      overlay_id: 'o1',
      scan_id: null,
      gsd_cm: '3.20',
      crs_epsg: 4326,
      bbox_min_lat: null,
      bbox_min_lon: null,
      bbox_max_lat: null,
      bbox_max_lon: null,
      sensor: null,
      width_px: 40,
      height_px: 20,
      metadata: {},
      created_at: '2026-03-12T00:00:00Z',
      updated_at: '2026-03-12T00:00:00Z',
      warnings: [],
      findings: [],
    });
    renderPanel();
    await userEvent.upload(screen.getByTestId('geo-surveys-file'), new File(['x'], 'site.tif', { type: 'image/tiff' }));
    await userEvent.selectOptions(screen.getByTestId('geo-surveys-platform'), 'aircraft');
    const date = screen.getByTestId('geo-surveys-date') as HTMLInputElement;
    await userEvent.clear(date);
    await userEvent.type(date, '2026-03-11');
    await userEvent.click(screen.getByTestId('geo-surveys-submit'));
    await waitFor(() => expect(uploadOrthophoto).toHaveBeenCalledTimes(1));
    const [projectId, file, options] = uploadOrthophoto.mock.calls[0] ?? [];
    expect(projectId).toBe('p1');
    expect((file as File).name).toBe('site.tif');
    expect(options).toMatchObject({ capturedOn: '2026-03-11', platform: 'aircraft' });
    expect(await screen.findByTestId('geo-surveys-result')).toHaveTextContent('EPSG:4326');
  });
});
