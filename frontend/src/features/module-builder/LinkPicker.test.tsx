// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The link picker: an id is never typed and never shown.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return { ...actual, lookupRecords: vi.fn(), lookupLabels: vi.fn() };
});

import { lookupLabels, lookupRecords } from './api';
import { LinkPicker } from './LinkPicker';

const records = vi.mocked(lookupRecords);
const labels = vi.mocked(lookupLabels);

function Harness({ initial = '', onChange }: { initial?: string; onChange: (id: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="pick">Contract</label>
      <LinkPicker
        id="pick"
        target="contract"
        projectId="p1"
        value={value}
        label="Contract"
        onChange={(id) => {
          setValue(id);
          onChange(id);
        }}
      />
    </>
  );
}

function renderPicker(initial = '') {
  const onChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness initial={initial} onChange={onChange} />
    </QueryClientProvider>,
  );
  return { onChange };
}

beforeEach(() => {
  vi.clearAllMocks();
  records.mockResolvedValue({
    items: [
      { id: 'c-1', label: 'Frame works', sublabel: 'C-2026-014' },
      { id: 'c-2', label: 'Facade', sublabel: null },
    ],
  });
  labels.mockResolvedValue({ labels: { 'c-1': 'Frame works' } });
});

describe('the link picker', () => {
  it('shows the stored link by its name, asked for in one batch', async () => {
    renderPicker('c-1');
    await waitFor(() => expect(screen.getByLabelText('Contract')).toHaveProperty('value', 'Frame works'));
    expect(labels).toHaveBeenCalledWith('contract', ['c-1']);
  });

  it('says a link the reader may not see is not visible, rather than showing its id', async () => {
    labels.mockResolvedValue({ labels: {} });
    renderPicker('c-9');
    await waitFor(() =>
      expect(screen.getByLabelText('Contract').getAttribute('placeholder')).toBe('Not visible to you'),
    );
    expect(screen.queryByDisplayValue('c-9')).toBeNull();
  });

  it('searches inside the project and stores the id of the record picked', async () => {
    const user = userEvent.setup();
    const { onChange } = renderPicker();
    await user.click(screen.getByRole('combobox'));
    await user.type(screen.getByRole('combobox'), 'Fra');

    await waitFor(() =>
      expect(records).toHaveBeenLastCalledWith('contract', { projectId: 'p1', q: 'Fra', limit: 20 }),
    );
    await user.click(await screen.findByRole('option', { name: /Frame works/ }));
    expect(onChange).toHaveBeenCalledWith('c-1');
    expect(screen.getByRole('combobox')).toHaveProperty('value', 'Frame works');
    // The record chosen here is already named; no second round trip for it.
    expect(labels).not.toHaveBeenCalled();
  });

  it('can be cleared', async () => {
    const user = userEvent.setup();
    const { onChange } = renderPicker('c-1');
    await user.click(await screen.findByTestId('link-picker-clear'));
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('says so when nothing matches', async () => {
    records.mockResolvedValue({ items: [] });
    const user = userEvent.setup();
    renderPicker();
    await user.click(screen.getByRole('combobox'));
    expect(await screen.findByText('Nothing matches')).toBeTruthy();
  });
});

describe('a reader who may not list the target', () => {
  const refused = () => Object.assign(new Error('Forbidden'), { status: 403 });

  it('says they cannot choose from it, and does not ask again', async () => {
    records.mockRejectedValue(refused());
    const user = userEvent.setup();
    renderPicker();
    await user.click(screen.getByRole('combobox'));
    expect(await screen.findByTestId('link-picker-forbidden')).toBeTruthy();
    expect(records).toHaveBeenCalledTimes(1);
  });

  it('shows a stored link as not visible rather than as a failure', async () => {
    labels.mockRejectedValue(refused());
    renderPicker('c-1');
    await waitFor(() =>
      expect(screen.getByLabelText('Contract').getAttribute('placeholder')).toBe('Not visible to you'),
    );
    expect(labels).toHaveBeenCalledTimes(1);
  });
});
