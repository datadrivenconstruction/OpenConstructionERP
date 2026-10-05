// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) => {
      const o = (typeof opts === 'string' ? { defaultValue: opts } : (opts ?? {})) as Record<string, unknown>;
      const template = typeof o.defaultValue === 'string' ? o.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, n: string) => String(o[n] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { HintStepper } from './HintStepper';

let client: QueryClient;
function renderStepper(hints: string[], total: number) {
  return render(
    <QueryClientProvider client={client}>
      <HintStepper taskId="t2-markups" hints={hints} total={total} courseLocale="en-GB" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  api.apiPost.mockReset();
});
afterEach(() => {
  cleanup();
  client.clear();
});

describe('HintStepper', () => {
  it('offers the first hint without showing any', () => {
    renderStepper([], 3);
    expect(screen.queryAllByTestId('trainer-hint')).toHaveLength(0);
    expect(screen.getByTestId('trainer-hint-next').textContent).toBe('Show a hint');
  });

  it('shows the revealed hints with "Hint n of total" and offers the next', () => {
    renderStepper(['Both markups apply to direct cost.', 'Profit is 5% of 30,414.00.'], 3);
    expect(screen.getByTestId('trainer-hint-count').textContent).toBe('Hint 2 of 3');
    expect(screen.getAllByTestId('trainer-hint')).toHaveLength(2);
    expect(screen.getByTestId('trainer-hint-next').textContent).toBe('Show the next hint');
  });

  it('asks the server for the next hint, one press at a time', async () => {
    let resolve: () => void = () => {};
    api.apiPost.mockImplementation(() => new Promise<void>((r) => (resolve = r)));
    renderStepper(['Both markups apply to direct cost.'], 2);
    const next = screen.getByTestId('trainer-hint-next');
    fireEvent.click(next);
    fireEvent.click(next);
    await waitFor(() => expect(api.apiPost).toHaveBeenCalledTimes(1));
    fireEvent.click(next);
    expect(api.apiPost).toHaveBeenCalledTimes(1);
    expect(api.apiPost.mock.calls[0]![0]).toBe('/v1/trainer/tasks/t2-markups/hints/reveal');
    resolve();
    await waitFor(() => expect(next.getAttribute('aria-busy')).toBeNull());
  });

  it('has no button once every hint is shown, and nothing that reads as a penalty', () => {
    renderStepper(['One.', 'Two.'], 2);
    expect(screen.queryByTestId('trainer-hint-next')).toBeNull();
    const text = screen.getByTestId('trainer-hints').textContent ?? '';
    expect(text).not.toMatch(/penalt|cost you|points?|lose|deduct/i);
  });

  it('says so when a hint did not load', async () => {
    api.apiPost.mockRejectedValue(new Error('network'));
    renderStepper([], 2);
    fireEvent.click(screen.getByTestId('trainer-hint-next'));
    expect((await screen.findByRole('alert')).textContent).toContain('The hint did not load');
  });

  it('renders nothing for a task without hints', () => {
    const { container } = renderStepper([], 0);
    expect(container.innerHTML).toBe('');
  });
});
