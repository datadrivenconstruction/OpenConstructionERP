// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// An Excel 97-2003 workbook (.xls) is read by no importer. The New BOQ window
// used to create an empty BOQ and then post the file to /import/auto/, which
// refused it in English. It now says what to do in the user's language, under
// the file picker, and creates nothing.

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
});

function pick(name: string) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['x'], name)] } });
}

describe('New estimate import', () => {
  it('refuses an .xls workbook with the save-as-xlsx hint and creates no BOQ', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CreateBOQModal open onClose={() => {}} defaultProjectId="proj-a" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByRole('option', { name: 'Alpha Tower' })).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('create-boq-import-mode'));
    pick('koltsegvetes.xls');

    expect(screen.getByRole('alert')).toHaveTextContent('.xlsx');
    fireEvent.submit(screen.getByTestId('create-boq-file-picker').closest('form') as HTMLFormElement);
    expect(create).not.toHaveBeenCalled();
    expect(fetchSpy.mock.calls.some(([url]) => String(url).includes('/import/auto/'))).toBe(false);
    fetchSpy.mockRestore();
  });

  it('does not flag an .xlsx workbook', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CreateBOQModal open onClose={() => {}} defaultProjectId="proj-a" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByTestId('create-boq-import-mode'));
    pick('koltsegvetes.xlsx');

    expect(screen.queryByRole('alert')).toBeNull();
  });
});
