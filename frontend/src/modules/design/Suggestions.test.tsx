import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN } from './testStrings';
import type { Suggestions as S } from './suggestApi';

const h = vi.hoisted(() => ({ data: null as unknown, post: vi.fn(), fails: false }));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/shared/lib/api', () => ({
  apiPost: vi.fn(async (path: string, body: unknown) => {
    if (path.endsWith('/suggestions')) {
      if (h.fails) throw new Error('boom');
      return h.data;
    }
    return h.post(path, body);
  }),
  getErrorMessage: (e: unknown) => String(e),
}));
vi.mock('@/shared/ui', () => ({
  Button: ({ children, variant: _v, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string }) =>
    <button type="button" {...rest}>{children}</button>,
}));

import { Suggestions } from './Suggestions';

const DATA = (): S => ({
  position_id: 'pos1', unit: 'm2', currency: 'EUR',
  assemblies: [
    { assembly_id: 'a1', code: 'ASM-1', name: 'Wall complete', unit: 'm2', rate: '150', currency: 'EUR', shared_words: ['wall'], usable: true, unusable_reason: null },
    { assembly_id: 'a2', code: 'ASM-2', name: 'Wall dollar', unit: 'm2', rate: '99', currency: 'USD', shared_words: ['wall'], usable: false, unusable_reason: 'currency' },
  ],
  cost_match: {
    run_id: 'run1', result_id: 'res1', region: 'DE_BERLIN', tier: 'high_confidence', tie: false, hint: '',
    candidates: [
      { cost_item_id: 'c1', code: 'C-1', description: 'Außenwand', unit: 'm2', rate: '321.5', currency: 'EUR', confidence: '0.9100', suggested: true, usable: true, unusable_reason: null },
      { cost_item_id: 'c2', code: 'C-2', description: 'Außenwand m3', unit: 'm3', rate: '9', currency: 'EUR', confidence: '0.6000', suggested: false, usable: false, unusable_reason: 'unit' },
    ],
  },
});

async function mount(onDone = vi.fn()) {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: 'en', resources: { en: { translation: EN } }, keySeparator: false, nsSeparator: false,
    interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}>
        <Suggestions projectId="p1" positionId="pos1" rule="wall_ext" onDone={onDone} />
      </I18nextProvider>
    </QueryClientProvider>,
  );
  return { user, onDone };
}

beforeEach(() => { cleanup(); h.data = DATA(); h.fails = false; h.post.mockReset(); h.post.mockResolvedValue(undefined); });

describe('Suggestions', () => {
  it('shows Cost Match and assemblies, applies nothing until Use, and disables rows in another unit or currency', async () => {
    await mount();
    expect(await screen.findByTestId('cm-c1')).toBeTruthy();
    expect(h.post).not.toHaveBeenCalled();
    expect((screen.getByTestId('cm-use-c2') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId('asm-use-a2') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId('cm-c2').textContent).toContain('other unit');
    expect(screen.getByTestId('asm-a2').textContent).toContain('other currency');
  });

  it('confirms a Cost Match row with its result id and closes', async () => {
    const { user, onDone } = await mount();
    await user.click(await screen.findByTestId('cm-use-c1'));
    await waitFor(() => expect(h.post).toHaveBeenCalledWith(
      '/v1/design/projects/p1/estimate/positions/pos1/confirm-suggestion', { result_id: 'res1', cost_item_id: 'c1' }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it('confirms an assembly by its id', async () => {
    const { user } = await mount();
    await user.click(await screen.findByTestId('asm-use-a1'));
    await waitFor(() => expect(h.post).toHaveBeenCalledWith(
      '/v1/design/projects/p1/estimate/positions/pos1/confirm-suggestion', { assembly_id: 'a1' }));
  });

  it('says so when the ERP has nothing, and stays silent when the lookup fails', async () => {
    h.data = { ...DATA(), assemblies: [], cost_match: null };
    await mount();
    expect(await screen.findByTestId('suggest-none-wall_ext')).toBeTruthy();
    cleanup();
    h.fails = true;
    await mount();
    await waitFor(() => expect(screen.queryByTestId('suggestions-wall_ext')).toBeNull());
  });
});
