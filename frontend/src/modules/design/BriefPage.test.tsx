// Brief page: link version negotiation, and the incomplete-draft status.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ApiError } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import type { BriefDoc } from './data/briefModel';

const api = vi.hoisted(() => ({ fetchBrief: vi.fn(), saveBrief: vi.fn(), confirmBrief: vi.fn() }));
vi.mock('./api', () => api);
vi.mock('./PlotEditor', () => ({ PlotEditor: () => <div /> }));
vi.mock('@/features/projects/api', () => ({
  projectsApi: { get: vi.fn(async () => ({ id: 'p1', name: 'Block A', country_code: 'DE', locale: 'de', currency: 'EUR', address: null })) },
}));
vi.mock('@/features/documents/api', () => ({ fetchDocuments: vi.fn(async () => ({ items: [], total: 0 })) }));

import BriefPage from './BriefPage';

const stored: BriefDoc = {
  schema: 'ddc-brief/1', brief_id: '11111111-1111-4111-8111-111111111111', project_id: '22222222-2222-4222-8222-222222222222',
  version: 1, country: 'DE', locale: 'de', depth_level: 'D2', use: { category: 'residential_multi' },
  massing: { floors_above: 3 }, programme: {}, provenance: {},
};
const floors = () => document.querySelector('input[name="/massing/floors_above"]') as HTMLInputElement;

function mount() {
  useProjectContextStore.setState({ activeProjectId: 'p1' } as never);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><BriefPage /></MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  useToastStore.setState({ toasts: [] } as never);
});

describe('brief page and the link version', () => {
  it('426 says the ERP does not support this version and offers no useless Reload', async () => {
    api.fetchBrief.mockResolvedValue(stored);
    api.saveBrief.mockRejectedValue(new ApiError(426, 'Upgrade Required', { detail: { supported: [2] } }));
    const user = userEvent.setup();
    mount();
    await waitFor(() => expect(floors()?.value).toBe('3'));
    await user.clear(floors());
    await user.type(floors(), '4');
    await user.click(screen.getByRole('button', { name: /^save/i }));
    await waitFor(() => expect(useToastStore.getState().toasts.some((x) => /does not support the version/i.test(x.message ?? ''))).toBe(true));
    expect(screen.queryByRole('button', { name: /reload/i })).toBeNull();
  });

  it('a draft without its required values is saved as a draft and shown as incomplete', async () => {
    api.fetchBrief.mockResolvedValue(null);
    api.saveBrief.mockImplementation(async (_p: string, d: BriefDoc) => ({ ...d, version: 1 }));
    const user = userEvent.setup();
    mount();
    await waitFor(() => expect(document.querySelector('input[name="/name"]')).toBeTruthy());
    expect(await screen.findByText(/Incomplete: \d+ required values missing/)).toBeTruthy();
    await user.type(document.querySelector('input[name="/name"]') as HTMLInputElement, ' x');
    await user.click(screen.getByRole('button', { name: /^save/i }));
    await waitFor(() => expect(api.saveBrief).toHaveBeenCalled());
    expect(api.saveBrief.mock.calls[0]![3]).toBe(true);
  });
});

describe('backend states', () => {
  it('401 on load says the session ended', async () => {
    api.fetchBrief.mockRejectedValue(new ApiError(401, 'Unauthorized', {}));
    mount();
    expect(await screen.findByText(/session has ended/i)).toBeTruthy();
  });

  it('an unreachable server on load says so and offers a retry that works', async () => {
    api.fetchBrief.mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValue(stored);
    const user = userEvent.setup();
    mount();
    expect(await screen.findByText(/cannot be reached/i)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /retry|try again/i }));
    await waitFor(() => expect(floors()?.value).toBe('3'));
  });

  it('an unreachable server on save keeps the edit and the unsaved state', async () => {
    api.fetchBrief.mockResolvedValue(stored);
    api.saveBrief.mockRejectedValue(new TypeError('Failed to fetch'));
    const user = userEvent.setup();
    mount();
    await waitFor(() => expect(floors()?.value).toBe('3'));
    await user.clear(floors());
    await user.type(floors(), '9');
    await user.click(screen.getByRole('button', { name: /^save/i }));
    await waitFor(() => expect(useToastStore.getState().toasts.some((x) => /cannot be reached/i.test(x.message ?? ''))).toBe(true));
    expect(floors().value).toBe('9');
    expect((screen.getByRole('button', { name: /^save/i }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(/unsaved changes/i)).toBeTruthy();
  });
});

describe('leaving with unsaved edits', () => {
  function link() {
    const a = document.createElement('a');
    a.href = '/projects';
    a.textContent = 'Projects';
    document.body.appendChild(a);
    return a;
  }

  it('an in-app link asks first and is stopped when declined', async () => {
    api.fetchBrief.mockResolvedValue(stored);
    const user = userEvent.setup();
    mount();
    await waitFor(() => expect(floors()?.value).toBe('3'));
    await user.clear(floors());
    await user.type(floors(), '4');
    const a = link();
    const seen: boolean[] = [];
    document.addEventListener('click', (e) => seen.push(e.defaultPrevented));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(seen.at(-1) ?? true).toBe(true);
    confirm.mockReturnValue(true);
    const ev = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    a.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
    confirm.mockRestore();
    a.remove();
  });

  it('no question when nothing was edited', async () => {
    api.fetchBrief.mockResolvedValue(stored);
    mount();
    await waitFor(() => expect(floors()?.value).toBe('3'));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const a = link();
    a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
    a.remove();
  });

  it('a saved brief points on to the design editor; a new one does not', async () => {
    api.fetchBrief.mockResolvedValue(stored);
    mount();
    const next = await screen.findByTestId('brief-next');
    expect(next.querySelector('a')?.getAttribute('href')).toBe('/design/editor');
  });

  it('no editor pointer before the first save', async () => {
    api.fetchBrief.mockResolvedValue(null);
    mount();
    await waitFor(() => expect(floors()).toBeTruthy());
    expect(screen.queryByTestId('brief-next')).toBeNull();
  });
});
