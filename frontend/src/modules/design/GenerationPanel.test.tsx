import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU } from './testStrings';

const api = vi.hoisted(() => ({
  can: true,
  lock: null as null | { held_by: string; mine: boolean; expires_at: string },
  brief: { version: 3, provenance: { '/country': { status: 'confirmed' } } } as unknown,
  gen: { enabled: true, reason: null, job: null } as { enabled: boolean; reason: string | null; job: unknown },
  start: vi.fn(async () => ({ job_id: 'j1' })),
  cancel: vi.fn(async () => ({})),
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/stores/useToastStore', () => ({ useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: () => {} }) }));
vi.mock('./api', () => ({
  fetchAccess: vi.fn(async () => ({ can_accept: api.can, currency: null, lock: api.lock })),
  fetchBrief: vi.fn(async () => api.brief),
  fetchGeneration: vi.fn(async () => api.gen),
  startGeneration: api.start,
  cancelGeneration: api.cancel,
}));
vi.mock('@/shared/ui', async () => {
  return {
    Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
    Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
    CardHeader: ({ title }: { title: string }) => <header>{title}</header>,
    Button: ({ children, disabled, onClick }: { children: React.ReactNode; disabled?: boolean; onClick?: () => void }) => (
      <button type="button" disabled={disabled} onClick={onClick}>{children}</button>
    ),
  };
});

import GenerationPanel from './GenerationPanel';

async function mount(lang: 'en' | 'ru' = 'en') {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}><GenerationPanel projectId="p1" /></I18nextProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  cleanup();
  api.can = true;
  api.lock = null;
  api.brief = { version: 3, provenance: { '/country': { status: 'confirmed' } } };
  api.gen = { enabled: true, reason: null, job: null };
  api.start.mockClear();
  api.cancel.mockClear();
});

describe('GenerationPanel', () => {
  it('starts a generation from the confirmed brief version', async () => {
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: 'Generate revision' }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith('p1', 3));
  });

  it('is hidden from people who may not accept', async () => {
    api.can = false;
    await mount();
    await waitFor(() => expect(screen.queryByTestId('generation-panel')).toBeNull());
  });

  it('says why it is off: no generator on the server, unconfirmed brief, editor holds the lock', async () => {
    api.gen = { enabled: false, reason: 'Generation on the server is not set up: OE_DESIGN_DDC_CLI is not set.', job: null };
    await mount();
    expect(await screen.findByTestId('generation-blocked')).toHaveTextContent('OE_DESIGN_DDC_CLI');
    expect(screen.getByRole('button', { name: 'Generate revision' })).toBeDisabled();
    cleanup();
    api.gen = { enabled: true, reason: null, job: null };
    api.brief = { version: 3, provenance: { '/country': { status: 'proposed' } } };
    await mount();
    expect(await screen.findByTestId('generation-blocked')).toHaveTextContent('Confirm every value');
    cleanup();
    api.brief = { version: 3, provenance: {} };
    api.lock = { held_by: 'Anna', mine: false, expires_at: '2026-01-01T00:00:00Z' };
    await mount();
    expect(await screen.findByTestId('generation-blocked')).toHaveTextContent('Anna');
  });

  it('shows a running job with progress and cancels it', async () => {
    api.gen = { enabled: true, reason: null, job: { job_id: 'j1', status: 'running', progress: 0.4, log_tail: ['> ddc gen'] } };
    const user = await mount();
    expect(await screen.findByText('Running')).toBeInTheDocument();
    expect(screen.getByText('> ddc gen')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate revision' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(api.cancel).toHaveBeenCalledWith('j1'));
  });

  it('shows the error of a failed job, in Russian too', async () => {
    api.gen = { enabled: true, reason: null, job: { job_id: 'j1', status: 'failed', progress: 0.1, log_tail: [], error: 'ddc gen failed (exit code 2)' } };
    await mount('ru');
    expect(await screen.findByText('Ошибка')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('exit code 2');
  });
});
