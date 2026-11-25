import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU, DE } from './testStrings';
import type { QuickResult } from './startApi';

const h = vi.hoisted(() => ({ run: vi.fn() }));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  getErrorMessage: (e: unknown) => String(e),
}));
vi.mock('./startApi', () => ({
  fetchQuickTypes: vi.fn(async () => ({ types: [{ id: 'office', generator: true, priced: true }] })),
  runQuick: (...a: unknown[]) => h.run(...a),
}));
vi.mock('@/shared/ui', () => ({
  Button: ({ children, variant: _v, icon: _i, size: _s, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string; icon?: unknown; size?: string }) =>
    <button type="button" {...rest}>{children}</button>,
}));

import { QuickMassing } from './QuickMassing';

// Real server output for the 4-storey 2,400 m2 office (backend test_frontend_fixture_is_the_real_output keeps it in sync)
import OFFICE from './data/quickOffice.fixture.json';
const RESULT = OFFICE as unknown as QuickResult;

async function mount() {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: 'en', fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU }, de: { translation: DE } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}><QuickMassing projectId="p1" country="DE" /></I18nextProvider>
    </QueryClientProvider>,
  );
}

describe('QuickMassing', () => {
  it('sends the short brief to the project endpoint, shows model, cost and programme', async () => {
    h.run.mockResolvedValue(RESULT);
    await mount();
    await userEvent.click(screen.getByRole('button', { name: EN['design.quick.run']! }));
    expect(h.run).toHaveBeenCalledWith('p1', expect.objectContaining({
      building_type: 'office', gfa_m2: 2400, storeys: 4, quality: 'standard', country: 'DE',
    }));
    await waitFor(() => expect(screen.getByTestId('quick-kpis')).toBeTruthy());
    expect(screen.getByText(EN['design.quick.q.wall_ext']!)).toBeTruthy();
    // no window ratio and no sourced durations: shown as missing, not as a number
    expect(screen.getAllByText(new RegExp(EN['design.quick.no_source']!)).length).toBeGreaterThan(1);
    expect(screen.getByText(EN['design.quick.rate_missing']!)).toBeTruthy();
    expect(screen.getAllByText(/model_params|spec\.rs/).length).toBeGreaterThan(0);
  });

  it('shows an implausible brief as a message, not a number', async () => {
    h.run.mockResolvedValue({ ...RESULT, model: null, cost: null, schedule: null, suggestions: [],
      issues: [{ code: 'footprint_over_plot', field: 'plot_area_m2', severity: 'error', params: { footprint: 600, plot: 500 } }] });
    await mount();
    await userEvent.click(screen.getByRole('button', { name: EN['design.quick.run']! }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('500'));
  });

  it('has every string in English, German and Russian', () => {
    const keys = Object.keys(EN).filter((k) => k.startsWith('design.quick.'));
    expect(keys.length).toBeGreaterThan(60);
    expect(keys.filter((k) => !DE[k] || !RU[k])).toEqual([]);
  });
});
