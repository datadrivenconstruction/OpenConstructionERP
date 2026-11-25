import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU, DE } from './testStrings';
import type { ScheduleImpact, ScheduleRow } from './data/schedule';
import { changedRows, signedDays } from './data/schedule';

const h = vi.hoisted(() => ({ impact: null as unknown, error: false, setup: vi.fn() }));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/shared/lib/api', () => ({ getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)) }));
vi.mock('./scheduleApi', () => ({
  fetchScheduleImpact: vi.fn(async () => {
    if (h.error) throw new Error('schedule down');
    return h.impact;
  }),
  setupSchedule: (...a: unknown[]) => h.setup(...a),
}));
vi.mock('@/shared/ui', async () => {
  return {
    Badge: ({ children }: { children: React.ReactNode }) => <span data-ui="badge">{children}</span>,
    Button: ({ children, variant: _v, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string }) =>
      <button type="button" {...rest}>{children}</button>,
    Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
    CardHeader: ({ title }: { title: string }) => <header>{title}</header>,
    ErrorState: ({ title, hint, onRetry }: { title: string; hint: string; onRetry: () => void }) =>
      <div role="alert"><p>{title}</p><p>{hint}</p><button type="button" onClick={onRetry}>Retry</button></div>,
    Skeleton: () => <span data-testid="skeleton" />,
  };
});

import { SchedulePanel } from './SchedulePanel';

const SRC = {
  title: 'Aufwandswerte von Mauerwerksarbeiten', publisher: 'wiki', country: 'DE',
  url: 'https://wiki.bubiza.de/doku.php?id=aufwandswerte-von-mauerwerksarbeiten', page: '5.1.10',
  published: '2024-05-29', retrieved: '2026-11-13', quote: '0,78 h/qm',
};
const row = (rule: string, storey: string, over: Partial<ScheduleRow> = {}): ScheduleRow => ({
  rule, label: `Label ${rule}`, storey, activity_id: `a-${rule}-${storey}`, new_activity: false, current_days: 3,
  model_days_now: 3, model_days_new: 3, new_days: 3, delta_days: 0, override: false, override_days: null, flags: [],
  quantity: '82.50', unit: 'm2', provenance: { worked: 'ceil(82.50 m2 × 0.78 h/m2 ÷ (4 × 8 h)) = 3', source: SRC }, ...over,
});
const impact = (rows: ScheduleRow[], over: Partial<ScheduleImpact> = {}): ScheduleImpact => ({
  schema: 'ddc-schedule-impact/1', revision_id: 'r2', schedule: true, schedule_id: 's1', start: '2027-03-01', rows,
  totals: { current_finish: '2027-03-29', after_finish: '2027-04-05', current_days: 28, after_days: 35, delta_days: 7,
    activities_added: 1, overrides_kept: 1 },
  rate_missing: [{ rule: 'roof', label: 'Dächer', unit: 'm2', missing: 'none', quantity: '400' },
    { rule: 'window', label: 'Fenster', unit: 'm2', missing: 'none', quantity: '40' }],
  not_scheduled: [], complete: false, ...over,
});
const NONE = { schema: 'ddc-schedule-impact/1', revision_id: 'r2', schedule: false };

async function mount(lang: 'en' | 'ru' | 'de' = 'en', canManage = true, needsEstimate = false) {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU }, de: { translation: DE } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}><MemoryRouter>
        <SchedulePanel projectId="p1" revisionId="r2" canManage={canManage} locale="en-US" needsEstimate={needsEstimate} />
      </MemoryRouter></I18nextProvider>
    </QueryClientProvider>,
  );
  return user;
}

beforeEach(() => {
  cleanup();
  h.error = false;
  h.setup = vi.fn(async () => ({ schedule: true }));
  h.impact = impact([
    row('wall_ext', '1.OG', { new_activity: true, activity_id: null, current_days: null, delta_days: 3 }),
    row('slab', 'EG', { override: true, override_days: 20, new_days: 20, current_days: 20, model_days_new: 16, flags: ['override'] }),
    row('wall_ext', 'EG'),
    row('foundation', '', { new_days: 0, delta_days: -5, current_days: 5, flags: ['no_match'] }),
  ]);
});

describe('schedule helpers', () => {
  it('keeps new, changed, overridden and dropped activities; signs days', () => {
    const rows = (h.impact as ScheduleImpact).rows!;
    expect(changedRows(rows).map((r) => `${r.rule}/${r.storey}`)).toEqual(['wall_ext/1.OG', 'slab/EG', 'foundation/']);
    expect([signedDays(3), signedDays(-2), signedDays(0)]).toEqual(['+3', '-2', '0']);
  });
});

describe('SchedulePanel', () => {
  it('shows finish now and after, the delta, and only the activities that change', async () => {
    await mount();
    const totals = await screen.findByTestId('schedule-totals');
    expect(within(totals).getByTestId('schedule-delta').textContent).toBe('+7 days');
    expect(totals.textContent).toContain('3/29/2027');
    expect(totals.textContent).toContain('4/5/2027');
    const rows = screen.getByTestId('schedule-rows');
    expect(within(rows).getAllByRole('listitem')).toHaveLength(3);
    const up = screen.getByTestId('schedule-row-wall_ext-1.OG');
    expect(up.textContent).toContain('new');
    expect(up.textContent).toContain('0 → 3 working days');
    expect(up.textContent).toContain('ceil(82.50 m2 × 0.78 h/m2 ÷ (4 × 8 h)) = 3');
    const link = within(up).getByRole('link');
    expect(link.getAttribute('href')).toBe(SRC.url);
    expect(link.textContent).toBe('Source: Aufwandswerte von Mauerwerksarbeiten, 2024-05-29 (read 2026-11-13)');
    expect(screen.getByTestId('schedule-row-slab-EG').textContent).toContain('kept: set by a person (model 16 d)');
    const gone = screen.getByTestId('schedule-row-foundation-building');
    expect(gone.textContent).toContain('no longer in the model');
    expect(gone.textContent).toContain('whole building');
  });

  it('never hides missing rates: lists the trades left out, and says durations are an assumption', async () => {
    await mount();
    const note = await screen.findByTestId('schedule-missing');
    expect(note.textContent).toBe('2 trades have no sourced productivity rate and are not in this change: Dächer, Fenster.');
    expect(screen.getByTestId('schedule-overrides').textContent).toBe('Durations set by a person are kept: 1.');
    expect(screen.getByTestId('schedule-assumption').textContent).toContain('ceil(quantity × labour hours per unit');
    expect(screen.getByTestId('schedule-link').getAttribute('href')).toBe('/schedule?project_id=p1');
  });

  it('says when nothing changes', async () => {
    h.impact = impact([row('wall_ext', 'EG')], { rate_missing: [], complete: true,
      totals: { current_finish: '2027-03-03', after_finish: '2027-03-03', current_days: 2, after_days: 2, delta_days: 0,
        activities_added: 0, overrides_kept: 0 } });
    await mount();
    expect((await screen.findByTestId('schedule-delta')).textContent).toBe('0 days');
    expect(screen.getByTestId('schedule-no-change')).toBeTruthy();
    expect(screen.queryByTestId('schedule-missing')).toBeNull();
  });

  it('offers setup to a manager when the project has no schedule, and asks again after it', async () => {
    h.impact = NONE;
    const user = await mount();
    await screen.findByTestId('no-schedule');
    h.impact = impact([]);
    await user.click(screen.getByTestId('schedule-setup'));
    expect(h.setup).toHaveBeenCalledWith('p1');
    expect(await screen.findByTestId('schedule-totals')).toBeTruthy();
  });

  it('holds setup back and points to the estimate while the project has none', async () => {
    h.impact = NONE;
    await mount('en', true, true);
    await screen.findByTestId('no-schedule');
    expect((screen.getByTestId('schedule-setup') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId('schedule-needs-estimate').textContent).toMatch(/Compute the estimate first/);
  });

  it('tells others who can set it up', async () => {
    h.impact = NONE;
    await mount('en', false);
    await screen.findByTestId('no-schedule');
    expect(screen.queryByTestId('schedule-setup')).toBeNull();
    expect(screen.getByText('A project manager can set it up.')).toBeTruthy();
  });

  it('shows a failed setup, and a failed calculation with a retry', async () => {
    h.impact = NONE;
    h.setup = vi.fn(async () => { throw new Error('no estimate'); });
    const user = await mount();
    await user.click(await screen.findByTestId('schedule-setup'));
    expect((await screen.findByRole('alert')).textContent).toContain('no estimate');
    cleanup();
    h.error = true;
    h.impact = impact([row('wall_ext', 'EG')]);
    const u2 = await mount();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The schedule change could not be calculated');
    h.error = false;
    await u2.click(within(alert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByTestId('schedule-totals')).toBeTruthy());
  });

  it('speaks German and Russian', async () => {
    await mount('de');
    expect((await screen.findByTestId('schedule-delta')).textContent).toBe('+7 Tage');
    expect(screen.getByTestId('schedule-row-wall_ext-1.OG').textContent).toContain('0 → 3 Arbeitstage');
    cleanup();
    await mount('ru');
    expect((await screen.findByTestId('schedule-delta')).textContent).toBe('+7 дн.');
    expect(screen.getByText('Окончание после')).toBeTruthy();
  });

  it('without a finish on either side the change is a dash, not 0 days', async () => {
    const base = impact([]);
    h.impact = { ...base, totals: { ...base.totals!, current_finish: null, after_finish: null, delta_days: 0 } };
    await mount();
    expect(await screen.findByTestId('schedule-delta')).toHaveTextContent(/^—$/);
  });
});
