// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The project map opens on streets, not on relief.
 *
 * /projects/:id/geo used to mount only the Cesium globe, whose imagery is
 * Natural Earth shaded relief with no streets at any zoom. A user opening
 * a project's map saw landform where they expected the site. The page now
 * opens on the 2D street map and keeps the globe one click away.
 *
 * Pinned here, each against the case that would break it:
 *   1. An anchored project with no 3D models opens the street map, and the
 *      "no 3D models" card, which describes the globe's content, does not
 *      cover it.
 *   2. Choosing the globe still works, still shows that card, and is
 *      remembered for the next visit.
 *   3. A 3D model deep link opens the globe without overwriting the
 *      remembered choice.
 *   4. A project with no location can be placed by clicking the street map,
 *      the flow that used to exist only on the globe.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

const PROJECT = '11111111-2222-3333-4444-555555555555';
const ANCHOR = {
  id: 'anchor-1',
  project_id: PROJECT,
  lat: '52.52000000',
  lon: '13.40500000',
  alt: '34',
  epsg_code: 4326,
  metadata: {},
};

const mapConfig = vi.hoisted(() => ({ current: null as unknown }));
const created = vi.hoisted(() => [] as unknown[]);
type ViewerProps = { overlay?: ReactNode; [key: string]: unknown };
const lastStreetProps = vi.hoisted(() => ({ current: null as ViewerProps | null }));

vi.mock('../api', () => ({
  getMapConfig: vi.fn(async () => mapConfig.current),
  fetchHsePins: vi.fn(async () => []),
  fetchPunchlistPins: vi.fn(async () => []),
  fetchDiaryPhotoPins: vi.fn(async () => []),
  autoAnchorFromAddress: vi.fn(async () => {
    throw new Error('not in this test');
  }),
  createAnchor: vi.fn(async (body: unknown) => {
    created.push(body);
    return { id: 'anchor-new' };
  }),
  updateAnchor: vi.fn(async () => ({})),
}));

vi.mock('@/features/projects/api', () => ({
  projectsApi: { get: vi.fn(async () => ({ id: PROJECT, name: 'Site A', address: null })) },
}));

vi.mock('../MapLibreViewer', () => ({
  MapLibreViewer: (props: ViewerProps) => {
    lastStreetProps.current = props;
    return <div data-testid="viewer-streets">{props.overlay}</div>;
  },
}));
vi.mock('../CesiumViewer', () => ({
  CesiumViewer: (props: ViewerProps) => <div data-testid="viewer-globe">{props.overlay}</div>,
}));

vi.mock('../GeoEmptyState', () => ({
  GeoEmptyState: (props: { kind: string; onPlaceManually?: () => void }) => (
    <div data-testid={`empty-${props.kind}`}>
      {props.onPlaceManually && (
        <button type="button" onClick={props.onPlaceManually} data-testid="place-manually">
          place
        </button>
      )}
    </div>
  ),
}));
vi.mock('../TilesetSidebar', () => ({ TilesetSidebar: () => <div data-testid="tileset-rail" /> }));
vi.mock('../OverlayPanel', () => ({ OverlayPanel: () => null }));
vi.mock('../OverlayLayer', () => ({ OverlayLayer: () => null }));
vi.mock('../MapLayerLegend', () => ({ MapLayerLegend: () => null }));
vi.mock('../AnchorAdjustPanel', () => ({ AnchorAdjustPanel: () => <div data-testid="anchor-panel" /> }));
vi.mock('../PlaceOnMapPicker', () => ({ PlaceOnMapPicker: () => null }));
vi.mock('../GeoOverlayHud', () => ({ GeoOverlayHud: () => null }));
vi.mock('../GeoModePicker', () => ({ GeoModePicker: () => null }));

import { ProjectGeoPage } from '../ProjectGeoPage';

function renderPage(path = `/projects/${PROJECT}/geo`) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/projects/:projectId/geo" element={<ProjectGeoPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The page loads both viewers through React.lazy. The first dynamic import of a module is
// transformed on demand and can outlast findBy's default wait on a busy machine, which failed
// only whichever test ran first. Warming both here keeps every test about the page itself.
beforeAll(async () => {
  await import('../MapLibreViewer');
  await import('../CesiumViewer');
});

beforeEach(() => {
  localStorage.clear();
  created.length = 0;
  lastStreetProps.current = null;
  mapConfig.current = { anchor: ANCHOR, tilesets: [], viewpoints: [], imagery: [] };
});

afterEach(() => {
  cleanup();
});

describe('project map engine', () => {
  it('opens an anchored project without 3D models on the street map, uncovered', async () => {
    renderPage();
    expect(await screen.findByTestId('viewer-streets')).toBeInTheDocument();
    expect(screen.queryByTestId('viewer-globe')).toBeNull();
    expect(screen.queryByTestId('empty-no_tilesets')).toBeNull();
    expect(screen.getByTestId('anchor-panel')).toBeInTheDocument();
    expect(lastStreetProps.current?.mode).toBe('project');
    expect(lastStreetProps.current?.anchor).toMatchObject({ lat: 52.52, lon: 13.405 });
  });

  it('switches to the globe on request and remembers it', async () => {
    renderPage();
    await screen.findByTestId('viewer-streets');
    await userEvent.click(screen.getByTestId('geo-engine-tab-3d'));
    expect(await screen.findByTestId('viewer-globe')).toBeInTheDocument();
    expect(screen.queryByTestId('viewer-streets')).toBeNull();
    expect(screen.getByTestId('empty-no_tilesets')).toBeInTheDocument();
    expect(screen.getByTestId('tileset-rail')).toBeInTheDocument();
    expect(localStorage.getItem('geoHub.project.engine')).toBe('3d');
  });

  it('opens a 3D model deep link on the globe without overwriting the choice', async () => {
    localStorage.setItem('geoHub.project.engine', '2d');
    renderPage(`/projects/${PROJECT}/geo?model=bim-1`);
    expect(await screen.findByTestId('viewer-globe')).toBeInTheDocument();
    expect(screen.queryByTestId('viewer-streets')).toBeNull();
    expect(localStorage.getItem('geoHub.project.engine')).toBe('2d');
  });

  it('places a project with no location by clicking the street map', async () => {
    mapConfig.current = { anchor: null, tilesets: [], viewpoints: [], imagery: [] };
    renderPage();
    await screen.findByTestId('viewer-streets');
    expect(lastStreetProps.current?.pickMode).toBe(false);
    await userEvent.click(await screen.findByTestId('place-manually'));
    await waitFor(() => expect(lastStreetProps.current?.pickMode).toBe(true));
    const onMapClick = lastStreetProps.current?.onMapClick as (c: { lat: number; lon: number }) => Promise<void>;
    await onMapClick({ lat: 48.1, lon: 11.5 });
    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({ project_id: PROJECT, lat: '48.10000000', lon: '11.50000000' });
  });
});
