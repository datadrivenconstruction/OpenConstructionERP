// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tests for the Plan Room entry states.
 *
 * The page used to dead-end: a project with no drawings showed an empty
 * dropdown and "choose a drawing above", and a project whose documents were
 * spreadsheets or models listed them as drawings that then failed to render.
 * These drive the real fetch path with the network stubbed at ``apiGet`` so
 * the drawing filter and the way out to the upload page stay under test.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: vi.fn(),
  };
});

import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { PlanRoomPage } from './PlanRoomPage';
import { fetchPlanRoomDrawingList, fetchPlanRoomDrawings, isDrawingDocument } from './api';

const NON_DRAWINGS = [
  { id: 'doc-xlsx', name: 'boq.xlsx', mime_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
  { id: 'doc-ifc', name: 'model.ifc', mime_type: 'application/octet-stream' },
  { id: 'doc-jpg', name: 'site.jpg', mime_type: 'image/jpeg' },
];

function stubApi(documents: unknown[]) {
  (apiGet as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url.startsWith('/v1/plan-room/projects/')) return Promise.resolve({ items: documents, superseded_hidden: 0 });
    if (url.startsWith('/v1/projects')) return Promise.resolve([{ id: 'proj-1', name: 'Tower A' }]);
    return Promise.resolve([]);
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/plan-room']}>
        <Routes>
          <Route path="/plan-room" element={<PlanRoomPage />} />
          <Route path="/files" element={<div>files page</div>} />
          <Route path="/projects" element={<div>projects page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('isDrawingDocument', () => {
  it('keeps PDFs and drops spreadsheets, models and photos', () => {
    expect(isDrawingDocument({ name: 'A-101.pdf', mime_type: 'application/pdf' })).toBe(true);
    for (const row of NON_DRAWINGS) expect(isDrawingDocument(row)).toBe(false);
  });

  it('falls back to the file extension when the MIME type is missing', () => {
    expect(isDrawingDocument({ filename: 'Plan.PDF', mime_type: '' })).toBe(true);
    expect(isDrawingDocument({ filename: 'plan.dwg', mime_type: null })).toBe(false);
  });

  it('reads the issued, current drawings from the plan-room endpoint', async () => {
    stubApi([{ id: 'doc-pdf', filename: 'A-101.pdf', revision_code: 'C.01', is_current_revision: true }]);
    const items = await fetchPlanRoomDrawings('proj-1');
    expect(items).toEqual([
      { id: 'doc-pdf', filename: 'A-101.pdf', revision_code: 'C.01', is_current_revision: true },
    ]);
    expect(apiGet).toHaveBeenCalledWith('/v1/plan-room/projects/proj-1/drawings/');
  });

  it('asks for earlier revisions only when told to', async () => {
    stubApi([]);
    await fetchPlanRoomDrawingList('proj-1', true);
    expect(apiGet).toHaveBeenCalledWith('/v1/plan-room/projects/proj-1/drawings/?include_superseded=true');
  });
});

describe('PlanRoomPage entry states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    try {
      localStorage.clear();
    } catch {
      /* storage blocked - the page still renders */
    }
  });

  it('offers the upload page when the project has no drawings', async () => {
    useProjectContextStore.setState({ activeProjectId: 'proj-1', activeProjectName: 'Tower A' });
    stubApi([]);
    renderPage();

    expect(await screen.findByText('No drawings in this project yet')).toBeInTheDocument();
    // The non-drawing documents are not offered as drawings.
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    // The steps stay open while there is nothing to open.
    expect(screen.getByText('Open a drawing from the list.')).toBeInTheDocument();
    // The breadcrumb names the project.
    expect(screen.getByText('Tower A')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Upload drawings' }));
    expect(await screen.findByText('files page')).toBeInTheDocument();
  });

  it('sends the reader to the project list when no project is active', async () => {
    useProjectContextStore.setState({ activeProjectId: null, activeProjectName: null });
    stubApi([]);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Go to projects' }));
    expect(await screen.findByText('projects page')).toBeInTheDocument();
  });
});
