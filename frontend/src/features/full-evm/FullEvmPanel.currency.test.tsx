// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ getProject: vi.fn(), create: vi.fn(), list: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({
  t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key,
  i18n: { language: 'en' },
}) }));
vi.mock('@/features/projects/api', () => ({ projectsApi: { get: mocks.getProject } }));
vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  createBaseline: mocks.create, listBaselines: mocks.list,
  listMeasures: vi.fn().mockResolvedValue({ items: [] }),
}));

import { FullEvmPanel } from './FullEvmPanel';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

let client: QueryClient;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue({ items: [] });
  mocks.getProject.mockResolvedValue({ id: 'project-a', currency: 'JPY' });
  mocks.create.mockResolvedValue({ id: 'created' });
  useProjectContextStore.setState({ activeProjectId: 'project-a' });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 120_000 }, mutations: { retry: false } } });
});
afterEach(() => { cleanup(); client.clear(); });

function openForm() {
  render(<QueryClientProvider client={client}><FullEvmPanel /></QueryClientProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'New baseline' }));
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'New plan' } });
  fireEvent.change(screen.getByLabelText('Budget at completion'), { target: { value: '1234.567' } });
}
const submit = () => screen.getByRole('button', { name: 'Create' });

it.each([' jpy ', 'KWD', 'XXX', null, ''])('submits the project denomination %s without inventing precision', async (currency) => {
  mocks.getProject.mockResolvedValue({ id: 'project-a', currency });
  openForm();
  await waitFor(() => expect(submit()).not.toBeDisabled());
  fireEvent.click(submit());
  await waitFor(() => expect(mocks.create).toHaveBeenCalledWith({
    project_id: 'project-a', name: 'New plan', bac: '1234.567', currency: currency?.trim().toUpperCase() || null,
  }));
  expect(mocks.create.mock.calls[0]?.[0]).not.toHaveProperty('minor_units');
});

it('blocks a switched project while loading, then submits its own currency', async () => {
  let resolve!: (value: { id: string; currency: string }) => void;
  openForm();
  await waitFor(() => expect(submit()).not.toBeDisabled());
  mocks.getProject.mockImplementation(() => new Promise((done) => { resolve = done; }));
  act(() => useProjectContextStore.setState({ activeProjectId: 'project-b' }));
  await waitFor(() => expect(mocks.getProject).toHaveBeenCalledWith('project-b'));
  expect(submit()).toBeDisabled();
  fireEvent.click(submit());
  expect(mocks.create).not.toHaveBeenCalled();
  await act(async () => resolve({ id: 'project-b', currency: 'KWD' }));
  await waitFor(() => expect(submit()).not.toBeDisabled());
  fireEvent.click(submit());
  await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ project_id: 'project-b', currency: 'KWD' })));
});

it.each(['error', 'wrong-project'])('does not create with %s project data', async (mode) => {
  if (mode === 'error') mocks.getProject.mockRejectedValue(new Error('Project unavailable'));
  else mocks.getProject.mockResolvedValue({ id: 'project-old', currency: 'EUR' });
  openForm();
  await waitFor(() => expect(mocks.getProject).toHaveBeenCalled());
  await waitFor(() => expect(client.isFetching()).toBe(0));
  expect(submit()).toBeDisabled();
  fireEvent.click(submit());
  expect(mocks.create).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
});

it.each(['success', 'error'])('does not submit cached currency while refetching: %s', async (outcome) => {
  client.setQueryData(['project', 'project-a'], { id: 'project-a', currency: 'EUR' });
  let resolve!: (value: { id: string; currency: string }) => void;
  let reject!: (reason: Error) => void;
  mocks.getProject.mockImplementation(() => new Promise((done, fail) => { resolve = done; reject = fail; }));
  openForm();
  await waitFor(() => expect(mocks.getProject).toHaveBeenCalledWith('project-a'));
  expect(submit()).toBeDisabled();
  expect(screen.getByRole('status')).toHaveTextContent('Loading');
  if (outcome === 'error') {
    await act(async () => reject(new Error('Refresh failed')));
    expect(submit()).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('Refresh failed');
    mocks.getProject.mockResolvedValue({ id: 'project-a', currency: 'JPY' });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  } else await act(async () => resolve({ id: 'project-a', currency: 'JPY' }));
  await waitFor(() => expect(submit()).not.toBeDisabled());
  fireEvent.click(submit());
  await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ currency: 'JPY' })));
});

it('keeps the stored denomination and amount of a legacy baseline', async () => {
  mocks.list.mockResolvedValue({ items: [{
    id: 'legacy', name: 'Legacy plan', bac: '100.00', currency: 'EUR', minor_units: 2,
    status: 'draft', validation_status: 'pending', periods: [],
  }] });
  render(<QueryClientProvider client={client}><FullEvmPanel /></QueryClientProvider>);
  expect((await screen.findAllByText('100.00 EUR')).length).toBeGreaterThan(0);
  expect(mocks.create).not.toHaveBeenCalled();
});
