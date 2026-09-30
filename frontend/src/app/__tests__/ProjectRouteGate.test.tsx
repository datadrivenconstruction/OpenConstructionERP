// A link to /projects/<gone id>/... opened the module page anyway and every
// panel failed on its own 404. The gate answers a gone project with one message
// and a way back to the project list, and leaves a working project alone.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ApiError } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/features/projects/api', () => ({ projectsApi: { get: (...a: unknown[]) => mocks.get(...a) } }));

import { ProjectRouteGate } from '../ProjectRouteGate';

function mount(projectId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/projects/${projectId}/boq`]}>
        <Routes>
          <Route
            path="/projects/:projectId/boq"
            element={
              <ProjectRouteGate projectId={projectId}>
                <p>module page</p>
              </ProjectRouteGate>
            }
          />
          <Route path="/projects" element={<p>project list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useProjectContextStore.getState().setActiveProject('p-gone', 'Gone');
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('ProjectRouteGate', () => {
  it('answers a gone project with a message and a link to the list', async () => {
    mocks.get.mockRejectedValue(new ApiError(404, 'Not Found', 'Project not found'));
    mount('p-gone');
    expect(await screen.findByText('Project not found')).toBeTruthy();
    expect(screen.queryByText('module page')).toBeNull();
    await waitFor(() => expect(useProjectContextStore.getState().activeProjectId).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Browse projects' }));
    expect(await screen.findByText('project list')).toBeTruthy();
  });

  it('renders the page for a project that exists', async () => {
    mocks.get.mockResolvedValue({ id: 'p-ok', name: 'Fine' });
    mount('p-ok');
    expect(await screen.findByText('module page')).toBeTruthy();
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith('p-ok'));
    expect(screen.queryByText('Project not found')).toBeNull();
  });
});
