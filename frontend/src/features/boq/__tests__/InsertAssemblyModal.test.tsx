// Insert assembly into an existing position: pick, preview the components and
// the new rate, scale with a factor, apply. Gypsum partition GYP-1 at 29.40/m2
// into a 120 m2 position priced at 25.00.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

import * as api from '@/shared/lib/api';
import { InsertAssemblyModal, parseFactor, type ApplyToPositionResult } from '../InsertAssemblyModal';

const getMock = vi.mocked(api.apiGet);
const postMock = vi.mocked(api.apiPost);

const assembly = { id: 'asm-1', code: 'GYP-1', name: 'Gypsum partition', unit: 'm2', category: 'drywall', total_rate: 29.4, currency: 'USD' };

function result(extra: Partial<ApplyToPositionResult> = {}): ApplyToPositionResult {
  return {
    position_id: 'pos-1',
    assembly_code: 'GYP-1',
    assembly_name: 'Gypsum partition',
    assembly_unit: 'm2',
    position_unit: 'm2',
    mode: 'replace',
    factor: '1',
    currency: 'USD',
    quantity: '120',
    assembly_rate: '29.40',
    before: { unit_rate: '25.00', total: '3000.00', resource_count: 0 },
    after: { unit_rate: '29.40', total: '3528.00', resource_count: 2 },
    resources: [
      { name: 'Gypsum board', unit: 'm2', quantity: 2.1, unit_rate: 4, total: 8.4 },
      { name: 'Drywall labour', unit: 'h', quantity: 0.35, unit_rate: 60, total: 21 },
    ],
    warnings: [],
    ...extra,
  };
}

function renderModal(onApplied = vi.fn(), metadata: Record<string, unknown> | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <InsertAssemblyModal
          position={{ id: 'pos-1', ordinal: '01.010', description: 'Partition wall', unit: 'm2', metadata }}
          onClose={vi.fn()}
          onApplied={onApplied}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onApplied;
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  getMock.mockResolvedValue({ items: [assembly] });
});

describe('InsertAssemblyModal', () => {
  it('accepts a factor above zero up to the limit', () => {
    expect(parseFactor('')).toBe(1);
    expect(parseFactor('1,1')).toBe(1.1);
    expect(parseFactor('0')).toBeNull();
    expect(parseFactor('-2')).toBeNull();
    expect(parseFactor('20000')).toBeNull();
  });

  it('previews the components and the new rate without saving, then applies', async () => {
    postMock.mockImplementation(async (_url, body) =>
      (body as { dry_run?: boolean }).dry_run ? result() : result({ previous: { unit_rate: '25.00', metadata: {} } }),
    );
    const onApplied = renderModal();
    fireEvent.click(await screen.findByText('Gypsum partition'));
    const table = await screen.findByTestId('insert-assembly-components');
    expect(table).toHaveTextContent('Gypsum board');
    expect(table).toHaveTextContent('Drywall labour');
    expect(screen.getByTestId('insert-assembly-result')).toHaveTextContent('29.40');
    expect(postMock).toHaveBeenCalledWith(
      '/v1/assemblies/asm-1/apply-to-position/',
      expect.objectContaining({ position_id: 'pos-1', factor: 1, mode: 'replace', dry_run: true }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Insert into position' }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(expect.objectContaining({ assembly_code: 'GYP-1' })));
    expect(postMock).toHaveBeenLastCalledWith(
      '/v1/assemblies/asm-1/apply-to-position/',
      expect.not.objectContaining({ dry_run: true }),
    );
  });

  it('blocks apply on a bad factor and explains the bounds', async () => {
    postMock.mockResolvedValue(result());
    renderModal();
    fireEvent.click(await screen.findByText('Gypsum partition'));
    await screen.findByTestId('insert-assembly-result');
    fireEvent.change(screen.getByLabelText('Quantity factor'), { target: { value: '0' } });
    expect(screen.getByText('Enter a number above 0 and up to 10000.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Insert into position' })).toBeDisabled();
  });

  it('shows a unit warning and offers only replace for whole-position resources', async () => {
    postMock.mockResolvedValue(result({ warnings: [{ code: 'unit_mismatch', assembly_unit: 'm2', position_unit: 'ft2' }] }));
    renderModal(vi.fn(), { resources: [{ name: 'Paint' }], resource_quantity_basis: 'per_position' });
    fireEvent.click(await screen.findByText('Gypsum partition'));
    expect(await screen.findByTestId('insert-assembly-warnings')).toHaveTextContent('ft2');
    expect(screen.getByRole('radio', { name: 'Add the assembly to them' })).toBeDisabled();
  });

  it('says so when the user has no assemblies', async () => {
    getMock.mockResolvedValue({ items: [] });
    renderModal();
    expect(await screen.findByText('No assemblies yet')).toBeInTheDocument();
  });
});
