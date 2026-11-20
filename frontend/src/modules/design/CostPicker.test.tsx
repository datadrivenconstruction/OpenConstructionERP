import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN } from './testStrings';

const h = vi.hoisted(() => ({ price: vi.fn(), panelProps: null as null | Record<string, unknown> }));

vi.mock('@/shared/lib/api', () => ({ getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)) }));
vi.mock('./Suggestions', () => ({ Suggestions: () => null }));
vi.mock('./api', () => ({ priceFromCostItem: (...a: unknown[]) => h.price(...a) }));
vi.mock('@/shared/ui', () => ({
  Button: ({ children, variant: _v, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string }) =>
    <button type="button" {...rest}>{children}</button>,
}));
vi.mock('@/features/costs/CwicrMatchPanel', () => ({
  CwicrMatchPanel: (props: Record<string, unknown>) => {
    h.panelProps = props;
    return <button onClick={() => (props.onApply as (m: unknown) => void)({ cost_item_id: 'ci-7' })}>apply-row</button>;
  },
}));

import { CostPicker } from './CostPicker';

async function mount(regions: string[]) {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: 'en', resources: { en: { translation: EN } }, keySeparator: false, nsSeparator: false,
    interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}>
        <CostPicker projectId="p1" positionId="pos1" rule="wall_ext" query="Außenwände" unit="m2" regions={regions} />
      </I18nextProvider>
    </QueryClientProvider>,
  );
  return user;
}

beforeEach(() => { cleanup(); h.price.mockReset(); h.price.mockResolvedValue(undefined); h.panelProps = null; });

describe('CostPicker', () => {
  it('opens the ERP cost-match panel for the position, region and unit, and prices from the chosen item', async () => {
    const user = await mount(['DE_BERLIN']);
    expect(screen.queryByText('apply-row')).toBeNull();
    await user.click(screen.getByTestId('cost-pick-wall_ext'));
    expect(h.panelProps).toMatchObject({ initialQuery: 'Außenwände', unitHint: 'm2', region: 'DE_BERLIN' });
    await user.click(screen.getByText('apply-row'));
    await waitFor(() => expect(h.price).toHaveBeenCalledWith('p1', 'pos1', 'ci-7'));
    await waitFor(() => expect(screen.queryByText('apply-row')).toBeNull());
  });

  it('says so when no cost database is loaded for the country, and offers no search', async () => {
    const user = await mount([]);
    await user.click(screen.getByTestId('cost-pick-wall_ext'));
    expect(screen.getByTestId('cost-none-wall_ext')).toBeTruthy();
    expect(screen.queryByText('apply-row')).toBeNull();
  });

  it('shows the server refusal (unit or currency mismatch) and keeps the panel open', async () => {
    h.price.mockRejectedValue(new Error('Cost item unit differs'));
    const user = await mount(['DE_BERLIN']);
    await user.click(screen.getByTestId('cost-pick-wall_ext'));
    await user.click(screen.getByText('apply-row'));
    expect((await screen.findByRole('alert')).textContent).toContain('Cost item unit differs');
    expect(screen.getByText('apply-row')).toBeTruthy();
  });
});
