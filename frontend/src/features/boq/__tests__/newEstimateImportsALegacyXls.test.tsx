// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// An Excel 97-2003 workbook (.xls) imports from the New BOQ window like an .xlsx.
//
// The window used to refuse an .xls under the file picker with a request to
// save it as .xlsx, because no importer read the format. The spreadsheet
// importer reads it now, so the refusal would only stand between the user and
// a file the server takes: the window must offer .xls in its picker, raise no
// alert for one, and hand it to /import/auto/ after creating the BOQ.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: () => Promise.resolve([{ id: 'proj-a', name: 'Alpha Tower' }]),
}));

const create = vi.fn();
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return { ...actual, boqApi: { ...actual.boqApi, create: (...args: unknown[]) => create(...args) } };
});

import { CreateBOQModal } from '../CreateBOQPage';

afterEach(() => {
  cleanup();
  create.mockReset();
  vi.restoreAllMocks();
});

function pick(name: string) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['x'], name)] } });
}

async function openImport() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CreateBOQModal open onClose={() => {}} defaultProjectId="proj-a" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByRole('option', { name: 'Alpha Tower' })).toBeInTheDocument());
  fireEvent.click(screen.getByTestId('create-boq-import-mode'));
}

describe('New estimate import', () => {
  it('offers .xls in the file picker next to .xlsx', async () => {
    await openImport();
    const accept = (document.querySelector('input[type="file"]') as HTMLInputElement).accept.split(',');
    expect(accept).toContain('.xlsx');
    expect(accept).toContain('.xls');
  });

  it('raises no alert for an .xls and posts it to the import after creating the BOQ', async () => {
    create.mockResolvedValue({ id: 'boq-1' });
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ imported: 3, skipped: 0, total_items: 3, errors: [], source_format: 'xls' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    await openImport();
    pick('koltsegvetes.xls');

    expect(screen.queryByRole('alert')).toBeNull();
    fireEvent.submit(screen.getByTestId('create-boq-file-picker').closest('form') as HTMLFormElement);

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(fetchSpy.mock.calls.some(([url]) => String(url).includes('/boqs/boq-1/import/auto/'))).toBe(true),
    );
    const call = fetchSpy.mock.calls.find(([url]) => String(url).includes('/import/auto/'));
    const body = (call?.[1] as RequestInit | undefined)?.body as FormData;
    expect((body.get('file') as File).name).toBe('koltsegvetes.xls');
  });

  it('does not flag an .xlsx workbook', async () => {
    await openImport();
    pick('koltsegvetes.xlsx');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
