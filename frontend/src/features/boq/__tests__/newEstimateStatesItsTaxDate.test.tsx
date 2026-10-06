// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A bill's tax date is its own field. A bill priced at 2025 rates for works in
// 2026 states base date 2025 and tax date 2026, and is taxed at 2026's rate.
// Left blank, the tax date is sent as null so the server taxes the bill on its
// base date, which keeps following the base date if that is changed later.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: () => Promise.resolve([{ id: 'proj-a', name: 'Alpha Tower' }]),
}));

const create = vi.fn();
vi.mock('../api', () => ({
  boqApi: { create: (data: unknown) => create(data) },
}));

import { CreateBOQModal } from '../CreateBOQPage';

function renderModal() {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CreateBOQModal open onClose={() => {}} defaultProjectId="proj-a" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function fillAndSubmit(base: string, tax: string) {
  await waitFor(() => expect(screen.getByRole('option', { name: 'Alpha Tower' })).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText('e.g. Main Building - Structural Works'), {
    target: { value: 'Shell and core' },
  });
  fireEvent.change(screen.getByTestId('create-boq-base-date'), { target: { value: base } });
  fireEvent.change(screen.getByTestId('create-boq-tax-date'), { target: { value: tax } });
  fireEvent.click(screen.getByRole('button', { name: 'Create BOQ' }));
}

beforeEach(() => {
  create.mockReset();
  create.mockResolvedValue({ id: 'boq-1' });
});

afterEach(() => {
  cleanup();
});

describe('New estimate tax date', () => {
  it('sends a tax date apart from the price base', async () => {
    renderModal();
    await fillAndSubmit('2025-06', '2026-01-01');
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0]).toMatchObject({ base_date: '2025-06', tax_date: '2026-01-01' });
  });

  it('sends null when the tax date is left blank, so the base date decides', async () => {
    renderModal();
    await fillAndSubmit('2025-Q2', '');
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0]).toMatchObject({ base_date: '2025-Q2', tax_date: null });
  });

  it('shows the price base as the tax date placeholder', async () => {
    renderModal();
    await waitFor(() => expect(screen.getByRole('option', { name: 'Alpha Tower' })).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('create-boq-base-date'), { target: { value: '2025-Q2' } });
    expect(screen.getByTestId('create-boq-tax-date')).toHaveAttribute('placeholder', '2025-Q2');
  });

  it('refuses a date the server could not tax on, before the round trip', async () => {
    renderModal();
    await fillAndSubmit('2025-06', '01.02.2026');
    expect(await screen.findByText(/2026-Q1/)).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });
});
