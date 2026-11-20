import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU } from './testStrings';
import type { ProcurementImpact, TakeoffRow } from './data/procurement';
import { changedRows, signed } from './data/procurement';

const h = vi.hoisted(() => ({ impact: null as unknown, error: false, setup: vi.fn() }));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/shared/lib/api', () => ({ getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)) }));
vi.mock('./procurementApi', () => ({
  fetchProcurementImpact: vi.fn(async () => {
    if (h.error) throw new Error('procurement down');
    return h.impact;
  }),
  setupProcurement: (...a: unknown[]) => h.setup(...a),
}));
vi.mock('@/shared/ui', async () => {
  const React = await import('react');
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

import { ProcurementPanel } from './ProcurementPanel';

const row = (key: string, over: Partial<TakeoffRow> = {}): TakeoffRow => ({
  group_key: key, label: `Type ${key}`, ifc_class: 'IfcWall', basis: 'area_m2', unit: 'm2', new_line: false,
  current_quantity: '82.5', model_quantity_now: '82.5', model_quantity_new: '82.5', new_quantity: '82.5',
  quantity_delta: '0', override: false, override_quantity: null, elements: { before: 1, after: 1 },
  package: { id: 'p', name: 'Design take-off: IfcWall', status: 'draft' }, new_package: false,
  flags: ['lead_time_missing', 'unpriced'], ...over,
});
const impact = (rows: TakeoffRow[], over: Partial<ProcurementImpact> = {}): ProcurementImpact => ({
  schema: 'ddc-procurement-impact/1', revision_id: 'r2', procurement: true, follow: true, group_by: 'type_key', rows,
  totals: { lines_changed: 2, lines_added: 1, lines_removed: 1, overrides_kept: 1, packages_affected: 2, packages_new: 1,
    issued_packages_affected: 1, unpriced_lines: 4 }, ...over,
});
const NONE = { schema: 'ddc-procurement-impact/1', revision_id: 'r2', procurement: false };

async function mount(lang: 'en' | 'ru' = 'en', canManage = true) {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}><MemoryRouter>
        <ProcurementPanel projectId="p1" revisionId="r2" canManage={canManage} />
      </MemoryRouter></I18nextProvider>
    </QueryClientProvider>,
  );
  return user;
}

beforeEach(() => {
  cleanup();
  h.error = false;
  h.setup = vi.fn(async () => ({ procurement: true }));
  h.impact = impact([
    row('wall/new', { new_line: true, current_quantity: '0', new_quantity: '20', quantity_delta: '20', package: null, new_package: true }),
    row('wall/ext', { override: true, override_quantity: '90', current_quantity: '90', new_quantity: '90',
      model_quantity_new: '165', quantity_delta: '7.5', flags: ['override', 'unpriced'] }),
    row('slab/c', { basis: 'volume_m3', unit: 'm3', current_quantity: '80.24', new_quantity: '160.48', quantity_delta: '80.24' }),
    row('door/a', { basis: 'count', unit: 'pcs', current_quantity: '1', new_quantity: '0', quantity_delta: '-1', flags: ['no_match'] }),
    row('stay/same'),
  ]);
});

describe('take-off helpers', () => {
  it('keeps new, changed, overridden and dropped lines; signs quantities', () => {
    const rows = (h.impact as ProcurementImpact).rows!;
    expect(changedRows(rows).map((r) => r.group_key)).toEqual(['wall/new', 'wall/ext', 'slab/c', 'door/a']);
    expect([signed('3.5'), signed('-2'), signed('0'), signed('80.2400')]).toEqual(['+3.5', '-2', '0', '+80.24']);
  });
});

describe('ProcurementPanel', () => {
  it('shows what changes, per line and per package, and keeps people\'s quantities visible', async () => {
    await mount();
    const totals = await screen.findByTestId('procurement-totals');
    expect(within(totals).getByTestId('procurement-lines').textContent).toBe('2 changed, 1 new, 1 gone');
    expect(within(totals).getByTestId('procurement-packages').textContent).toBe('3');
    expect(within(totals).getByTestId('procurement-issued').textContent).toBe('1');
    expect(within(screen.getByTestId('procurement-rows')).getAllByRole('listitem')).toHaveLength(4);
    expect(screen.getByTestId('procurement-row-wall/new').textContent).toContain('A new tender package is raised');
    expect(screen.getByTestId('procurement-row-wall/ext').textContent).toContain('kept: set by a person (model 165 m2)');
    expect(screen.getByTestId('procurement-row-slab/c').textContent).toContain('80.24 → 160.48 m3');
    expect(screen.getByTestId('procurement-row-slab/c').textContent).toContain('Package Design take-off: IfcWall (draft)');
    expect(screen.getByTestId('procurement-row-door/a').textContent).toContain('no longer in the model');
    expect(screen.getByTestId('procurement-overrides').textContent).toBe('Quantities set by a person are kept: 1.');
    expect(screen.getByTestId('procurement-link').getAttribute('href')).toBe('/tendering');
  });

  it('warns about issued packages and says nothing is priced or timed', async () => {
    await mount();
    expect((await screen.findByTestId('procurement-issued-note')).textContent).toContain('reviews and sends it in Tendering');
    expect(screen.getByTestId('procurement-unpriced').textContent).toContain('No prices and no lead times are assumed');
    expect(screen.getByTestId('procurement-assumption').textContent).toContain('convention by IFC class');
  });

  it('says when nothing changes or following is paused', async () => {
    h.impact = impact([row('stay/same')], { follow: false, totals: { lines_changed: 0, lines_added: 0, lines_removed: 0,
      overrides_kept: 0, packages_affected: 0, packages_new: 0, issued_packages_affected: 0, unpriced_lines: 1 } });
    await mount();
    expect(await screen.findByTestId('procurement-no-change')).toBeTruthy();
    expect(screen.getByTestId('procurement-paused')).toBeTruthy();
    expect(screen.queryByTestId('procurement-issued-note')).toBeNull();
  });

  it('offers setup to a manager with the grouping, and asks again after it', async () => {
    h.impact = NONE;
    const user = await mount();
    await screen.findByTestId('no-procurement');
    await user.selectOptions(screen.getByTestId('procurement-group-by'), 'ifc_class');
    h.impact = impact([]);
    await user.click(screen.getByTestId('procurement-setup'));
    expect(h.setup).toHaveBeenCalledWith('p1', 'ifc_class');
    expect(await screen.findByTestId('procurement-totals')).toBeTruthy();
  });

  it('tells others who can create it', async () => {
    h.impact = NONE;
    await mount('en', false);
    await screen.findByTestId('no-procurement');
    expect(screen.queryByTestId('procurement-setup')).toBeNull();
    expect(screen.getByText('A project manager can create it.')).toBeTruthy();
  });

  it('shows a failed setup, and a failed calculation with a retry', async () => {
    h.impact = NONE;
    h.setup = vi.fn(async () => { throw new Error('no revision'); });
    const user = await mount();
    await user.click(await screen.findByTestId('procurement-setup'));
    expect((await screen.findByRole('alert')).textContent).toContain('no revision');
    cleanup();
    h.error = true;
    h.impact = impact([row('stay/same')]);
    const u2 = await mount();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The procurement change could not be calculated');
    h.error = false;
    await u2.click(within(alert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByTestId('procurement-totals')).toBeTruthy());
  });

  it('speaks Russian', async () => {
    await mount('ru');
    expect((await screen.findByTestId('procurement-lines')).textContent).toBe('изменено 2, новых 1, исчезло 1');
    expect(screen.getByText('Уже выданы')).toBeTruthy();
  });
});
