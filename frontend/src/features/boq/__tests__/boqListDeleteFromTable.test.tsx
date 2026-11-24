// The table view's trash button used to set a confirm id that only the grid
// cards rendered, so clicking it did nothing. It must ask, then delete.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), del: vi.fn() }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: (url: string) => api.get(url),
    apiPost: (url: string, body: unknown) => api.post(url, body),
    apiDelete: (url: string) => api.del(url),
  };
});

vi.mock('@/modules/collaboration/components/PresenceAvatars', () => ({ PresenceAvatars: () => null }));
vi.mock('../CreateBOQPage', () => ({ CreateBOQModal: () => null }));

import { BOQListPage } from '../BOQListPage';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('oe_boq_list_view', 'table');
  useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
  useAuthStore.setState({ userRole: 'admin', userId: 'u1' } as never);
  api.get.mockImplementation((url: string) => {
    if (url.startsWith('/v1/projects/')) return Promise.resolve([{ id: 'p1', name: 'Harbour', currency: 'EUR' }]);
    return Promise.resolve(url === '/v1/documents/file-types-by-project/' ? {} : []);
  });
  api.post.mockImplementation((url: string) =>
    Promise.resolve(
      url === '/v1/boq/boqs/by-projects/'
        ? { p1: [{ id: 'b1', project_id: 'p1', name: 'Quay wall', status: 'draft', created_at: '2026-01-01T00:00:00Z', position_count: 3, grand_total: '10.00' }] }
        : {},
    ),
  );
  api.del.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('BOQ list, table view, delete', () => {
  it('opens a confirm dialog from the trash button and deletes on confirm', async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <BOQListPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText('Quay wall')).toBeTruthy());

    const row = screen.getByText('Quay wall').closest('[role="button"], [tabindex]') as HTMLElement;
    const trash = within(row ?? document.body).getAllByTitle(/delete/i)[0]!;
    fireEvent.click(trash);

    const dialog = await screen.findByRole('alertdialog');
    expect(api.del).not.toHaveBeenCalled();
    const buttons = within(dialog).getAllByRole('button', { name: /delete/i });
    fireEvent.click(buttons[buttons.length - 1]!);

    await waitFor(() => expect(api.del).toHaveBeenCalledWith('/v1/boq/boqs/b1'));
  });
});
