// UI QA: brief page flows with the network mocked (backend states, parse errors, reload after conflict).
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import type { BriefDoc } from '../data/briefModel';

const api = vi.hoisted(() => ({ fetchBrief: vi.fn(), saveBrief: vi.fn(), confirmBrief: vi.fn() }));
vi.mock('../api', () => api);
vi.mock('../PlotEditor', () => ({ PlotEditor: () => <div data-testid="plot-stub" /> }));
vi.mock('@/features/projects/api', () => ({
  projectsApi: { get: vi.fn(async () => ({ id: 'p1', name: 'Block A', country_code: 'DE', locale: 'de', currency: 'EUR', address: null })) },
}));
vi.mock('@/features/documents/api', () => ({ fetchDocuments: vi.fn(async () => ({ items: [], total: 0 })) }));

import BriefPage from '../BriefPage';

vi.mock('react-i18next', async () => (await import('../testStrings')).i18nMock());

const base = (version: number, floors: number): BriefDoc => ({
  schema: 'ddc-brief/1',
  brief_id: '11111111-1111-4111-8111-111111111111',
  project_id: '22222222-2222-4222-8222-222222222222',
  version,
  name: `v${version}`,
  country: 'DE',
  locale: 'de',
  depth_level: 'D2',
  use: { category: 'residential_multi' },
  massing: { floors_above: floors },
  programme: {},
  provenance: { '/massing/floors_above': { status: 'proposed', sources: [{ kind: 'user' }] } },
});

function mount() {
  useProjectContextStore.setState({ activeProjectId: 'p1' } as never);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><BriefPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

const floorsInput = () => document.querySelector('input[name="/massing/floors_above"]') as HTMLInputElement;
const saveButton = () => screen.getByRole('button', { name: /^save/i }) as HTMLButtonElement;

async function typeFloors(user: ReturnType<typeof userEvent.setup>, text: string) {
  await waitFor(() => expect(floorsInput()).toBeTruthy());
  await user.clear(floorsInput());
  await user.type(floorsInput(), text);
}

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
});

describe('brief page', () => {
  it('Reload after a 409 shows the newer server version, not the cached old one', async () => {
    api.fetchBrief.mockResolvedValueOnce(base(1, 3)).mockResolvedValue(base(2, 7));
    api.saveBrief.mockRejectedValue(new ApiError(409, 'Conflict', { detail: 'changed' }));
    const user = userEvent.setup();
    mount();
    await waitFor(() => expect(floorsInput()?.value).toBe('3'));
    await typeFloors(user, '4');
    await user.click(saveButton());
    await user.click(await screen.findByRole('button', { name: /reload/i }));
    await waitFor(() => expect(api.fetchBrief).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(floorsInput()?.value).toBe('7'));
  });

  it('an unparsable entry blocks Save instead of silently saving the previous value', async () => {
    api.fetchBrief.mockResolvedValue(base(1, 3));
    const user = userEvent.setup();
    mount();
    await waitFor(() => expect(floorsInput()?.value).toBe('3'));
    await typeFloors(user, '4');
    await user.type(floorsInput(), 'x');
    expect(floorsInput().value).toBe('4x');
    expect(saveButton().disabled).toBe(true);
  });

  it('hex notation is not accepted as a number', async () => {
    api.fetchBrief.mockResolvedValue(base(1, 3));
    const user = userEvent.setup();
    mount();
    await typeFloors(user, '0x10');
    expect(floorsInput().getAttribute('aria-invalid')).toBe('true');
  });

  it('428 offers Reload like 409 does', async () => {
    api.fetchBrief.mockResolvedValue(base(1, 3));
    api.saveBrief.mockRejectedValue(new ApiError(428, 'Precondition Required', { detail: 'Send If-Match with the brief version' }));
    const user = userEvent.setup();
    mount();
    await typeFloors(user, '5');
    await user.click(saveButton());
    expect(await screen.findByRole('button', { name: /reload/i })).toBeTruthy();
  });

  it('confirm buttons name the value they act on', async () => {
    api.fetchBrief.mockResolvedValue(base(1, 3));
    mount();
    await waitFor(() => expect(floorsInput()?.value).toBe('3'));
    const confirms = screen
      .getAllByRole('button')
      .filter((b) => /^confirm$/i.test((b.textContent ?? '').trim()) || /^bestätigen$/i.test((b.textContent ?? '').trim()));
    expect(confirms.length).toBeGreaterThan(1);
    const names = confirms.map((b) => b.getAttribute('aria-label') ?? b.textContent);
    expect(new Set(names).size).toBe(names.length);
  });

  it('cite buttons name the value they act on', async () => {
    api.fetchBrief.mockResolvedValue(base(1, 3));
    mount();
    await waitFor(() => expect(floorsInput()?.value).toBe('3'));
    const cites = Array.from(document.querySelectorAll('button[aria-label]')).filter((b) => b.querySelector('svg'));
    expect(cites.length).toBeGreaterThan(1);
    expect(new Set(cites.map((b) => b.getAttribute('aria-label'))).size).toBe(cites.length);
  });

  it('an invalid input is linked to its error message', async () => {
    api.fetchBrief.mockResolvedValue(base(1, 3));
    const user = userEvent.setup();
    mount();
    await typeFloors(user, '999');
    expect(floorsInput().getAttribute('aria-invalid')).toBe('true');
    expect(floorsInput().getAttribute('aria-describedby')).toBeTruthy();
  });

  it('a required input says so to assistive technology', async () => {
    api.fetchBrief.mockResolvedValue(base(1, 3));
    mount();
    await waitFor(() => expect(floorsInput()?.value).toBe('3'));
    expect(floorsInput().required || floorsInput().getAttribute('aria-required') === 'true').toBe(true);
  });

  it('leaving with unsaved edits is guarded', async () => {
    api.fetchBrief.mockResolvedValue(base(1, 3));
    const user = userEvent.setup();
    mount();
    await typeFloors(user, '4');
    const ev = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
  });

  it('a new brief can be saved as a draft before every required value is known', async () => {
    api.fetchBrief.mockResolvedValue(null);
    mount();
    await waitFor(() => expect(document.querySelector('input[name="/name"]')).toBeTruthy());
    await userEvent.setup().type(document.querySelector('input[name="/name"]') as HTMLInputElement, ' draft');
    expect(saveButton().disabled).toBe(false);
  });
});
