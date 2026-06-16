import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
  apiGetMock,
  listDocumentsMock,
  searchParams,
  setSearchParamsMock,
} = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  listDocumentsMock: vi.fn(),
  searchParams: new URLSearchParams('tab=measurements&doc=document-1&source=document'),
  setSearchParamsMock: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearchParams: () => [searchParams, setSearchParamsMock],
  };
});

vi.mock('@/shared/lib/api', () => ({
  apiGet: apiGetMock,
  apiPost: vi.fn(),
}));

vi.mock('@/features/ai/api', () => ({
  aiApi: {
    getSettings: vi.fn(async () => ({})),
  },
}));

vi.mock('@/features/ai-estimator/useAiReadiness', () => ({
  hasLlmKey: () => false,
}));

vi.mock('../api', () => ({
  takeoffApi: {
    listDocuments: listDocumentsMock,
  },
}));

vi.mock('@/modules/pdf-takeoff/TakeoffViewerModule', () => ({
  default: (props: {
    initialMeasurementDocumentId?: string;
    initialMeasurementDocumentSource?: string;
  }) => (
    <div
      data-testid="takeoff-viewer"
      data-document-id={props.initialMeasurementDocumentId}
      data-document-source={props.initialMeasurementDocumentSource}
    />
  ),
}));

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { TakeoffPage } from '../TakeoffPage';

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TakeoffPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TakeoffPage Project Files deep links', () => {
  beforeEach(() => {
    localStorage.clear();
    useProjectContextStore.getState().clearProject();
    apiGetMock.mockReset();
    listDocumentsMock.mockReset();
    setSearchParamsMock.mockReset();
    searchParams.set('tab', 'measurements');
    searchParams.set('doc', 'document-1');
    searchParams.set('source', 'document');
    searchParams.delete('docId');
    searchParams.delete('measurementId');
    searchParams.delete('name');

    apiGetMock.mockImplementation(async (url: string) => {
      if (url === '/v1/projects/') return [];
      if (url === '/v1/documents/document-1') {
        return {
          id: 'document-1',
          name: 'Plan.pdf',
          filename: 'Plan.pdf',
          project_id: 'project-1',
          metadata: {},
        };
      }
      if (url === '/v1/projects/project-1') {
        return {
          id: 'project-1',
          name: 'Project One',
          description: '',
          classification_standard: '',
        };
      }
      if (url.startsWith('/v1/boq/boqs/')) return [];
      return [];
    });
    listDocumentsMock.mockResolvedValue([]);
  });

  it('restores project context before mounting a Project Files document deep link', async () => {
    renderPage();

    const viewer = await screen.findByTestId('takeoff-viewer');

    expect(viewer).toHaveAttribute('data-document-id', 'document-1');
    expect(viewer).toHaveAttribute('data-document-source', 'document');
    await waitFor(() => {
      const state = useProjectContextStore.getState();
      expect(state.activeProjectId).toBe('project-1');
      expect(state.activeProjectName).toBe('Project One');
    });
    expect(apiGetMock).toHaveBeenCalledWith('/v1/documents/document-1');
    expect(apiGetMock).toHaveBeenCalledWith('/v1/projects/project-1');
  });

  it('does not treat a plain takeoff document restore URL as a Markups deep link miss', async () => {
    searchParams.set('doc', 'takeoff-doc-1');
    searchParams.delete('source');
    listDocumentsMock.mockResolvedValue([
      {
        id: 'other-takeoff-doc',
        filename: 'Other.pdf',
      },
    ]);

    renderPage();

    await waitFor(() => {
      expect(listDocumentsMock).toHaveBeenCalled();
    });
    await expect(
      screen.findByTestId('takeoff-deeplink-not-found', {}, { timeout: 100 }),
    ).rejects.toThrow();
  });

  it('shows the Markups deep-link miss only when a measurement target is present', async () => {
    searchParams.set('doc', 'missing-takeoff-doc');
    searchParams.set('measurementId', 'measurement-1');
    searchParams.delete('source');
    listDocumentsMock.mockResolvedValue([]);

    renderPage();

    expect(await screen.findByTestId('takeoff-deeplink-not-found')).toBeInTheDocument();
  });
});
