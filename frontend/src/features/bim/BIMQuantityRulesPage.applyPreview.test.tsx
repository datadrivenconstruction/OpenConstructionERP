import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({
  listQuantityMaps: vi.fn(), fetchBIMModels: vi.fn(), fetchBIMElements: vi.fn(),
  fetchSmartViewProperties: vi.fn(), fetchBIMDataframeSchema: vi.fn(),
  applyQuantityMaps: vi.fn(), boqList: vi.fn(), boqGet: vi.fn(), apiGet: vi.fn(),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => {
    let value = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
    for (const [k, v] of Object.entries(opts ?? {})) value = value.replace(`{{${k}}}`, String(v));
    return value;
  }, i18n: { language: 'en' } }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));
vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  ...Object.fromEntries(['listQuantityMaps', 'fetchBIMModels', 'fetchBIMElements', 'fetchSmartViewProperties',
    'fetchBIMDataframeSchema', 'applyQuantityMaps'].map((key) => [key, (...args: unknown[]) => mocks[key as keyof typeof mocks](...args)])),
}));
vi.mock('@/features/boq/api', () => ({ boqApi: {
  list: (...a: unknown[]) => mocks.boqList(...a), get: (...a: unknown[]) => mocks.boqGet(...a),
} }));
vi.mock('@/shared/lib/api', async (original) => ({
  ...(await original<typeof import('@/shared/lib/api')>()), apiGet: (...a: unknown[]) => mocks.apiGet(...a),
}));
vi.mock('@/features/bim_requirements/RulePackLibrary', () => ({ RulePackLibrary: () => null }));
vi.mock('./BIMRequirementsImport', () => ({ default: () => null }));

import { BIMQuantityRulesPage } from './BIMQuantityRulesPage';
import { ApiError } from '@/shared/lib/api';
import type { QuantityMapApplyResult } from './api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

const fingerprint = 'a'.repeat(64);
const result: QuantityMapApplyResult = {
  preview_fingerprint: fingerprint, matched_elements: 1, rules_applied: 1,
  links_created: 0, positions_created: 0, links_to_create: 1, positions_to_create: 1, results: [],
};
let client: QueryClient;

async function page() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/bim/rules']}>
    <BIMQuantityRulesPage />
  </MemoryRouter></QueryClientProvider>);
  await waitFor(() => expect((screen.getByLabelText('BIM model') as HTMLSelectElement).value).toBe('m-1'));
  await waitFor(() => expect(client.isFetching()).toBe(0));
}

async function preview() {
  fireEvent.click(screen.getByRole('button', { name: 'Preview (dry run)' }));
  await screen.findByText('Applying will create 1 new BOQ positions.');
  return within(screen.getByRole('dialog')).getByRole('button', { name: 'Apply rules' }) as HTMLButtonElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: 'Villa' });
  useToastStore.setState({ toasts: [], history: [] });
  mocks.listQuantityMaps.mockResolvedValue({ items: [], total: 0 });
  mocks.fetchBIMModels.mockResolvedValue({ items: [
    { id: 'm-1', name: 'First model', status: 'ready', version: '1' },
    { id: 'm-2', name: 'Second model', status: 'ready', version: '1' },
  ], total: 2 });
  mocks.fetchBIMElements.mockResolvedValue({ items: [], total: 0 });
  mocks.fetchSmartViewProperties.mockResolvedValue({ entries: [], element_count: 0 });
  mocks.fetchBIMDataframeSchema.mockRejectedValue(new Error('no sidecar schema'));
  mocks.boqList.mockResolvedValue([{ id: 'b-1', name: 'Bill one' }, { id: 'b-2', name: 'Bill two' }]);
  mocks.boqGet.mockResolvedValue({ positions: [] });
  mocks.apiGet.mockResolvedValue([]);
  mocks.applyQuantityMaps.mockResolvedValue(result);
});

afterEach(() => { cleanup(); client?.clear(); });

describe('Apply the reviewed quantity-map preview', () => {
  it('does not apply on mount or before preview; shows the actual effects', async () => {
    await page();
    expect(mocks.applyQuantityMaps).not.toHaveBeenCalled();
    expect((screen.getByRole('button', { name: 'Apply rules' }) as HTMLButtonElement).disabled).toBe(true);
    const button = await preview();
    expect(button.disabled).toBe(false);
    expect(screen.getByText(/Quantities and prices of existing positions stay unchanged/)).toBeTruthy();
    expect(mocks.applyQuantityMaps).toHaveBeenCalledExactlyOnceWith('m-1', true, null);
  });

  it('sends the reviewed fingerprint and blocks a rapid double click', async () => {
    await page();
    fireEvent.change(screen.getByLabelText('BOQ'), { target: { value: 'b-1' } });
    const button = await preview();
    let finish: (value: QuantityMapApplyResult) => void = () => {};
    mocks.applyQuantityMaps.mockReturnValue(new Promise<QuantityMapApplyResult>((resolve) => { finish = resolve; }));
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(mocks.applyQuantityMaps).toHaveBeenLastCalledWith('m-1', false, 'b-1', fingerprint));
    expect(mocks.applyQuantityMaps).toHaveBeenCalledTimes(2);
    await act(async () => finish({ ...result, links_created: 1, positions_created: 1 }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect((screen.getByRole('button', { name: 'Apply rules' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it.each(['BIM model', 'BOQ'])('invalidates the preview when %s changes', async (label) => {
    await page();
    await preview();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' }));
    fireEvent.change(screen.getByLabelText(label), { target: { value: label === 'BOQ' ? 'b-2' : 'm-2' } });
    expect((screen.getByRole('button', { name: 'Apply rules' }) as HTMLButtonElement).disabled).toBe(true);
    expect(mocks.applyQuantityMaps).toHaveBeenCalledTimes(1);
  });

  it('ignores a late preview response after changing the model', async () => {
    let finish: (value: QuantityMapApplyResult) => void = () => {};
    mocks.applyQuantityMaps.mockReturnValue(new Promise<QuantityMapApplyResult>((resolve) => { finish = resolve; }));
    await page();
    fireEvent.click(screen.getByRole('button', { name: 'Preview (dry run)' }));
    await waitFor(() => expect(mocks.applyQuantityMaps).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText('BIM model'), { target: { value: 'm-2' } });
    await act(async () => finish(result));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect((screen.getByRole('button', { name: 'Apply rules' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('invalidates the result when rule data is refreshed', async () => {
    await page();
    await preview();
    await act(async () => client.setQueryData(['bim-quantity-maps'], { items: [{ id: 'r-1', name: 'Changed', is_active: false }], total: 1 }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect((screen.getByRole('button', { name: 'Apply rules' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('automatically prepares ready model rules once and only writes after confirmation', async () => {
    mocks.listQuantityMaps.mockResolvedValue({ items: [{ id: 'r-1', name: 'Walls', is_active: true }], total: 1 });
    await page();
    await screen.findByText('Applying will create 1 new BOQ positions.');
    expect(mocks.applyQuantityMaps).toHaveBeenCalledExactlyOnceWith('m-1', true, null);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' }));
    await act(async () => client.invalidateQueries({ queryKey: ['bim-models'] }));
    expect(mocks.applyQuantityMaps).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('waits for conversion then prepares again when the ready model version changes', async () => {
    mocks.listQuantityMaps.mockResolvedValue({ items: [{ id: 'r-1', name: 'Walls', is_active: true }], total: 1 });
    mocks.fetchBIMModels.mockResolvedValue({ items: [{ id: 'm-1', name: 'First model', status: 'processing', version: '1' }], total: 1 });
    await page();
    expect(mocks.applyQuantityMaps).not.toHaveBeenCalled();
    const models = (version: string) => ({ items: [{ id: 'm-1', name: 'First model', status: 'ready', version }], total: 1 });
    await act(async () => client.setQueryData(['bim-models', 'p-1'], models('1')));
    await waitFor(() => expect(mocks.applyQuantityMaps).toHaveBeenCalledTimes(1));
    await screen.findByText('Applying will create 1 new BOQ positions.');
    await act(async () => client.setQueryData(['bim-models', 'p-1'], models('2')));
    await waitFor(() => expect(mocks.applyQuantityMaps).toHaveBeenCalledTimes(2));
    expect(mocks.applyQuantityMaps.mock.calls.every((call) => call[1] === true)).toBe(true);
  });

  it('shows its localized stale refusal, not raw server text, and requires a new preview', async () => {
    await page();
    const button = await preview();
    mocks.applyQuantityMaps.mockRejectedValue(new ApiError(409, 'Conflict', {
      detail: { code: 'quantity_preview_stale', message: 'RAW PRIVATE SERVER TEXT' },
    }));
    fireEvent.click(button);
    await waitFor(() => expect(useToastStore.getState().toasts.at(-1)?.message).toBe(
      'The model, rules or BOQ changed. Run a new preview before applying.',
    ));
    expect((screen.getByRole('button', { name: 'Apply rules' }) as HTMLButtonElement).disabled).toBe(true);
    expect(JSON.stringify(useToastStore.getState().toasts)).not.toContain('RAW PRIVATE');
  });
});
