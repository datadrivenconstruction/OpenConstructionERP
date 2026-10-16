// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "New estimate" with "Import a file" creates the BOQ first and then imports
// into it. When the import fails, or reads nothing, that BOQ used to stay
// behind as an empty orphan and the window navigated into it. It must now be
// deleted, the window must stay open with a readable reason, and nothing may
// navigate away.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: () => Promise.resolve([{ id: 'proj-a', name: 'Alpha Tower' }]),
}));

const create = vi.fn();
const deleteBoq = vi.fn();
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    boqApi: {
      ...actual.boqApi,
      create: (...args: unknown[]) => create(...args),
      deleteBoq: (...args: unknown[]) => deleteBoq(...args),
    },
  };
});

const navigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigate };
});

import { CreateBOQModal } from '../CreateBOQPage';
import { useAuthStore } from '@/stores/useAuthStore';

// Creating an estimate needs boq.create, editor and above.
useAuthStore.setState({ userRole: 'editor' });

afterEach(() => {
  cleanup();
  create.mockReset();
  deleteBoq.mockReset();
  navigate.mockReset();
  vi.restoreAllMocks();
});

async function submitImport(response: Response | Error) {
  create.mockResolvedValue({ id: 'boq-1' });
  deleteBoq.mockResolvedValue(undefined);
  const spy = vi.spyOn(globalThis, 'fetch');
  if (response instanceof Error) spy.mockRejectedValue(response);
  else spy.mockResolvedValue(response);
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CreateBOQModal open onClose={onClose} defaultProjectId="proj-a" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByRole('option', { name: 'Alpha Tower' })).toBeInTheDocument());
  fireEvent.click(screen.getByTestId('create-boq-import-mode'));
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['x'], 'kosten.xlsx')] } });
  fireEvent.submit(screen.getByTestId('create-boq-file-picker').closest('form') as HTMLFormElement);
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  return { onClose };
}

const json = (body: unknown, status: number) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('New estimate import failure', () => {
  it('deletes the BOQ and stays open when the server refuses the file', async () => {
    const { onClose } = await submitImport(json({ detail: 'Unsupported file' }, 422));
    await waitFor(() => expect(deleteBoq).toHaveBeenCalledWith('boq-1'));
    expect(navigate).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('deletes the BOQ when the import reads nothing', async () => {
    const { onClose } = await submitImport(json({ imported: 0, skipped: 0, total_items: 0, errors: [] }, 200));
    await waitFor(() => expect(deleteBoq).toHaveBeenCalledWith('boq-1'));
    expect(await screen.findByText(/No positions could be read from kosten\.xlsx/)).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows no raw network error text', async () => {
    await submitImport(new TypeError('Failed to fetch'));
    await waitFor(() => expect(deleteBoq).toHaveBeenCalledWith('boq-1'));
    expect(screen.queryByText(/Failed to fetch/)).toBeNull();
  });

  it('waits for a background import job and deletes the BOQ when the job read nothing', async () => {
    create.mockResolvedValue({ id: 'boq-1' });
    deleteBoq.mockResolvedValue(undefined);
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes('/import/auto/')) return json({ job_id: 'job-1', status: 'pending', progress_percent: 0 }, 202);
      if (url.includes('/import/jobs/job-1/')) {
        return json(
          { job_id: 'job-1', status: 'success', progress_percent: 100, result: { imported: 0, total_items: 0, errors: [] } },
          200,
        );
      }
      return json({}, 404);
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CreateBOQModal open onClose={() => {}} defaultProjectId="proj-a" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByRole('option', { name: 'Alpha Tower' })).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('create-boq-import-mode'));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['x'], 'computo.xpwe')] } });
    fireEvent.submit(screen.getByTestId('create-boq-file-picker').closest('form') as HTMLFormElement);
    await waitFor(() => expect(deleteBoq).toHaveBeenCalledWith('boq-1'));
    expect(await screen.findByText(/No positions could be read from computo\.xpwe/)).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('keeps the BOQ and opens it when the import succeeds', async () => {
    await submitImport(json({ imported: 2, skipped: 0, total_items: 2, errors: [] }, 200));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/boq/boq-1'));
    expect(deleteBoq).not.toHaveBeenCalled();
  });
});
