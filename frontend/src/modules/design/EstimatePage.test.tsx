import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { MemoryRouter } from 'react-router-dom';
import { EN, RU, DE } from './testStrings';
import fixture from './data/fixtures/estimate.de-residential.json';
import live from './data/fixtures/estimate.live-de.json';
import type { Estimate, EstimatePosition, EstimateView } from './data/estimate';
import type { RevisionView } from './data/revisions';

class HttpError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const h = vi.hoisted(() => ({
  project: 'p1' as string | null,
  estimate: null as unknown,
  estimateError: null as unknown,
  revisions: [] as unknown[],
  access: { can_accept: true, currency: 'EUR', lock: null } as unknown,
  accessPending: false,
  rules: [] as unknown[],
  brief: null as unknown,
  reason: vi.fn(),
  run: vi.fn(),
  starter: vi.fn(),
  estimateCalls: 0,
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (sel: (s: { activeProjectId: string | null }) => unknown) => sel({ activeProjectId: h.project }),
}));
vi.mock('@/shared/lib/api', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock('./api', () => ({
  LINK_VERSION: '1',
  fetchEstimate: vi.fn(async () => {
    h.estimateCalls += 1;
    if (h.estimateError) throw h.estimateError;
    return h.estimate;
  }),
  fetchRevisions: vi.fn(async () => h.revisions),
  fetchAccess: vi.fn(() => (h.accessPending ? new Promise(() => {}) : Promise.resolve(h.access))),
  fetchEstimateRules: vi.fn(async () => h.rules),
  fetchBrief: vi.fn(async () => h.brief),
  saveOverrideReason: (...a: unknown[]) => h.reason(...a),
  runEstimate: (...a: unknown[]) => h.run(...a),
  installStarterRules: (...a: unknown[]) => h.starter(...a),
}));
vi.mock('@/features/costs/CwicrMatchPanel', () => ({ CwicrMatchPanel: () => null }));
vi.mock('@/shared/ui', async () => {
  const React = await import('react');
  const box = (name: string) => ({ children, title, description, hint, onRetry, action }: Record<string, unknown>) =>
    React.createElement('div', { 'data-ui': name, role: name === 'ErrorState' ? 'alert' : undefined },
      React.createElement('p', null, title as string), React.createElement('p', null, (description ?? hint) as string),
      onRetry ? React.createElement('button', { onClick: onRetry as () => void }, 'Retry') : null, children as never, action as never);
  return {
    Badge: ({ children }: { children: React.ReactNode }) => <span data-badge>{children}</span>,
    Button: ({ children, loading, icon: _i, variant: _v, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; icon?: unknown; variant?: string }) =>
      <button type="button" {...rest} disabled={rest.disabled || loading}>{children}</button>,
    Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
    CardHeader: ({ title, subtitle }: { title: string; subtitle?: string }) => <header>{title}{subtitle ? <small>{subtitle}</small> : null}</header>,
    EmptyState: box('EmptyState'), ErrorState: box('ErrorState'),
    PageHeader: ({ srTitle, subtitle }: { srTitle?: string; subtitle?: string }) => <header><h1>{srTitle}</h1><p>{subtitle}</p></header>,
    Skeleton: () => <span data-testid="skeleton" />,
  };
});

import EstimatePage from './EstimatePage';

const base = fixture as unknown as Estimate;
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const est = (patch: Partial<Estimate> = {}): Estimate => ({ ...clone(base), ...patch });
const withPosition = (e: Estimate, rule: string, patch: Partial<EstimatePosition>): Estimate => {
  e.positions = e.positions.map((p) => (p.rule === rule ? { ...p, ...patch } : p));
  return e;
};
const rev = (n: number, over: Partial<RevisionView> = {}): RevisionView => ({
  revision_id: base.revision_id ?? 'r1', project_id: 'p1', number: n, parent_revision_id: null, status: 'published',
  source_kind: 'editor', depth_level: 'D2', message: `message ${n}`, bim_model_id: `m${n}`, decided_by: null,
  decided_at: null, decision_comment: null, created_at: '2026-01-01T10:00:00Z', ...over,
});

async function mount(lang: 'en' | 'ru' | 'de' = 'en') {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU }, de: { translation: DE } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}><MemoryRouter><EstimatePage /></MemoryRouter></I18nextProvider>
    </QueryClientProvider>,
  );
  return user;
}

beforeEach(() => {
  cleanup();
  h.project = 'p1';
  h.estimate = est();
  h.estimateError = null;
  h.revisions = [rev(3)];
  h.access = { can_accept: true, currency: 'EUR', lock: null };
  h.accessPending = false;
  h.rules = [];
  h.brief = null;
  h.estimateCalls = 0;
  h.reason = vi.fn(async () => undefined);
  h.run = vi.fn(async () => ({ revision_id: 'r', positions: 14 }));
  h.starter = vi.fn(async () => ({ rules: 14, country: 'DE' }));
});

describe('estimate with a range', () => {
  it('shows low, mid and high with the currency and the living-area basis', async () => {
    await mount();
    const totals = await screen.findByTestId('range-totals');
    expect(within(totals).getByText(/^€\s?97,245$/)).toBeTruthy();
    expect(within(totals).getByText(/^€\s?132,118$/)).toBeTruthy();
    expect(within(totals).getByText(/^€\s?275,090$/)).toBeTruthy();
    expect(screen.getByText('Living area 28.4 m²')).toBeTruthy();
    expect(screen.getByText(/Cost groups 100, 600 have no sourced benchmark/)).toBeTruthy();
  });

  it('does not show the check as passed when inside_range is null', async () => {
    await mount();
    const note = await screen.findByTestId('check-unknown');
    expect(note.textContent).toContain('Not checkable: no priced cost base.');
    expect(note.textContent).toContain('Not comparable');
    expect(screen.queryByTestId('check-inside')).toBeNull();
    expect(screen.queryByText(/inside the benchmark range/)).toBeNull();
  });

  it('shows "inside" only for an explicit true, and says below/above for false', async () => {
    h.estimate = est({ inside_range: true, inside_range_note: null });
    await mount();
    expect(await screen.findByTestId('check-inside')).toBeTruthy();
    cleanup();
    h.estimate = est({ inside_range: false, total: '1000' });
    await mount();
    expect((await screen.findByTestId('check-outside')).textContent).toContain('below the benchmark range');
    expect(screen.queryByTestId('check-inside')).toBeNull();
  });

  it('never reads a zero priced total as below the range or as a saving', async () => {
    h.estimate = est({ inside_range: false, total: '0' });
    await mount();
    const priced = await screen.findByTestId('priced-total');
    expect(priced.textContent).toContain('Nothing is priced yet');
    expect((await screen.findByTestId('check-outside')).textContent).not.toMatch(/below/);
  });

  it('shows dashes, not zero euros, when nothing is priced and no range can be formed', async () => {
    const b = clone(base);
    h.estimate = est({ total: '0', range: { ...b.range, basis_living_area_m2: '0',
      total: { low: '0', mid: '0', high: '0', complete: false } } });
    await mount();
    const totals = await screen.findByTestId('range-totals');
    expect(within(totals).queryByText(/€/)).toBeNull();
    expect(within(totals).getAllByText('–')).toHaveLength(3);
    expect(screen.queryByText(/Living area/)).toBeNull();
  });

  it('lists each benchmark once with publisher, url and date', async () => {
    await mount();
    const list = await screen.findByTestId('benchmark-list');
    const items = within(list).getAllByRole('listitem');
    expect(items.length).toBeGreaterThanOrEqual(1);
    expect(list.textContent).toContain('ARGE Kiel');
    expect(list.textContent).toContain('2024-04-02');
    const links = within(list).getAllByRole('link') as HTMLAnchorElement[];
    expect(links.every((a) => /^https:\/\//.test(a.href) && a.rel.includes('noopener'))).toBe(true);
    const urls = links.map((a) => a.href);
    expect(new Set(urls).size).toBe(urls.length);
  });

  it('links to the revision the estimate was computed on', async () => {
    await mount();
    const link = (await screen.findByTestId('revision-link')) as HTMLAnchorElement;
    expect(link.textContent).toBe('Revision 3');
    expect(link.getAttribute('href')).toBe(`/design/revisions?rev=${base.revision_id}`);
  });
});

describe('page language', () => {
  it('shows a visible page title', async () => {
    await mount();
    expect((await screen.findAllByRole('heading', { level: 1 })).map((h) => h.textContent)).toContain('Estimate');
    cleanup();
    await mount('ru');
    expect((await screen.findAllByRole('heading', { level: 1 })).map((h) => h.textContent)).toContain('Смета');
  });

  it('renders server notes from their codes, so ru and de show no English', async () => {
    await mount('ru');
    const note = await screen.findByTestId('check-unknown');
    expect(note.textContent).toContain('Сравнить нельзя');
    expect(note.textContent).not.toContain('Not comparable');
    expect(screen.getByTestId('missing-services').textContent).toContain('Ни один открытый источник');
    expect(screen.getByTestId('missing-finishes').textContent).toContain('отделку');
    expect(screen.getByTestId('missing-reinforcement').textContent).toContain('У входного значения');
    cleanup();
    await mount('de');
    expect((await screen.findByTestId('check-unknown')).textContent).toContain('Nicht vergleichbar');
    expect(screen.getByTestId('missing-services').textContent).toContain('Keine offene Quelle');
  });

  it('falls back to the server text for a code the page does not know', async () => {
    const e = est({ inside_range_note_code: 'brand_new', inside_range_note: 'Server says so' });
    withPosition(e, 'services', { provenance: { ...base.positions.find((p) => p.rule === 'services')!.provenance, missing_code: 'rate_missing_x', missing: 'Custom rule text' } });
    h.estimate = e;
    await mount('ru');
    expect((await screen.findByTestId('check-unknown')).textContent).toContain('Server says so');
    expect(screen.getByTestId('missing-services').textContent).toBe('Custom rule text');
  });

  it('lists sources that are not used in the range with the reason', async () => {
    await mount('de');
    const box = await screen.findByTestId('benchmarks-not-used');
    expect(box.textContent).toContain('Statistisches Bundesamt');
    expect(box.textContent).toContain('Thüringer Landesamt für Statistik');
    expect(box.textContent).toContain('andere Bezugsgröße');
    expect(box.textContent).toContain('nur ein Einzelwert');
    expect(within(screen.getByTestId('benchmark-list')).queryByText(/Thüringer/)).toBeNull();
  });
});

describe('positions', () => {
  it('groups by DIN 276 cost group in numeric order with source badges', async () => {
    await mount();
    await screen.findByTestId('range-totals');
    const ids = screen.getAllByTestId(/^group-/).map((g) => g.getAttribute('data-testid'));
    expect(ids).toEqual(['group-200', 'group-320', 'group-330', 'group-334', 'group-340', 'group-344', 'group-350', 'group-360', 'group-400', 'group-500', 'group-700']);
    const wall = screen.getByTestId('pos-wall_ext');
    expect(within(wall).getByText('Model')).toBeTruthy();
    expect(within(screen.getByTestId('pos-site_works')).getByText('Assumption')).toBeTruthy();
  });

  it('formats quantities in the page language', async () => {
    await mount('de');
    expect((await screen.findByTestId('qty-slab')).textContent).toBe('401,2 m²');
    cleanup();
    await mount('ru');
    expect((await screen.findByTestId('qty-door')).textContent).toBe('1 шт');
  });

  it('marks unpriced and rate-missing positions and shows no guessed rate', async () => {
    await mount();
    const wall = await screen.findByTestId('pos-wall_ext');
    expect(within(wall).getAllByText('Unpriced').length).toBeGreaterThanOrEqual(2);
    expect(wall.textContent).not.toMatch(/\/m²/);
    const services = screen.getByTestId('pos-services');
    expect(within(services).getByText('No unit rate')).toBeTruthy();
    expect(screen.getByTestId('missing-services').textContent).toContain('No open source splits');
    expect(within(screen.getByTestId('pos-reinforcement')).getByText('Input missing')).toBeTruthy();
    expect(screen.getByTestId('subtotal-330').textContent).toBe('Unpriced');
    expect(screen.getByTestId('unpriced-count').textContent).toMatch(/^11 positions have no unit rate\./);
  });

  it('says plainly when no cost database is loaded for the country, and where to load one', async () => {
    h.estimate = est({ cost_regions: [] });
    await mount();
    const link = await screen.findByTestId('no-cost-base');
    expect(link.textContent).toBe(EN['design.estimate.cost_pick_none']!);
    expect(link.getAttribute('href')).toBe('/costs');
  });

  it('no such note once a cost database for the country is there', async () => {
    h.estimate = est({ cost_regions: ['DE_BERLIN'] });
    await mount();
    await screen.findByTestId('unpriced-count');
    expect(screen.queryByTestId('no-cost-base')).toBeNull();
  });

  it('shows formula, assumption and source of a derived position', async () => {
    await mount();
    const box = await screen.findByTestId('assumption-site_works');
    expect(box.textContent).toContain('living_area_m2');
    expect(box.textContent).toContain('WoFlV');
    const bench = within(box).getByTestId('bench-site_works');
    expect(bench.textContent).toContain('41.77');
    const link = within(bench).getByRole('link') as HTMLAnchorElement;
    expect(link.href).toMatch(/^https:\/\//);
  });
});

describe('manual quantity', () => {
  const overridden = () => {
    const e = est();
    withPosition(e, 'wall_ext', {
      quantity: '80', override: true, override_quantity: '80', model_quantity: '82.5', override_reason: null,
      flags: ['override', 'unpriced'],
    });
    return e;
  };

  it('flags the override, shows the model value beside it and keeps a smaller quantity neutral', async () => {
    h.estimate = overridden();
    await mount();
    const row = await screen.findByTestId('pos-wall_ext');
    expect(within(row).getByText('Manual quantity')).toBeTruthy();
    const note = screen.getByTestId('override-wall_ext');
    expect(note.textContent).toContain('Your quantity 80 m² is kept; the model says 82.5 m².');
    expect(note.textContent).toContain('(-2.5 m²)');
    expect(row.innerHTML).not.toMatch(/semantic-success|saving/i);
    expect(within(row).getByText('No reason recorded yet.')).toBeTruthy();
  });

  it('saves a trimmed reason through the manager endpoint', async () => {
    h.estimate = overridden();
    const user = await mount();
    const row = await screen.findByTestId('pos-wall_ext');
    const save = within(row).getByRole('button', { name: 'Save reason' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    await user.type(within(row).getByLabelText('Reason for the manual quantity'), '  Façade redesigned  ');
    expect(save.disabled).toBe(false);
    await user.click(save);
    await waitFor(() => expect(h.reason).toHaveBeenCalledWith('p1', base.positions.find((p) => p.rule === 'wall_ext')!.position_id, '  Façade redesigned  '));
    await waitFor(() => expect(h.estimateCalls).toBeGreaterThan(1));
  });

  it('shows a failed save with its status text and keeps what was typed', async () => {
    h.estimate = overridden();
    h.reason = vi.fn(async () => { throw new HttpError(403, 'Only a project manager may change the estimate'); });
    const user = await mount();
    const row = await screen.findByTestId('pos-wall_ext');
    const box = within(row).getByLabelText('Reason for the manual quantity') as HTMLTextAreaElement;
    await user.type(box, 'x');
    await user.click(within(row).getByRole('button', { name: 'Save reason' }));
    const err = await within(row).findByTestId('mutation-error');
    expect(err.textContent).toContain('You do not have access to this estimate.');
    expect(err.textContent).toContain('Only a project manager');
    expect(box.value).toBe('x');
  });

  it('fails closed: no save for a non-manager, and none until permissions have answered', async () => {
    h.estimate = overridden();
    h.access = { can_accept: false, currency: 'EUR', lock: null };
    await mount();
    const row = await screen.findByTestId('pos-wall_ext');
    expect(within(row).queryByRole('button', { name: 'Save reason' })).toBeNull();
    expect((within(row).getByLabelText('Reason for the manual quantity') as HTMLTextAreaElement).readOnly).toBe(true);
    expect(screen.getByTestId('read-only')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Compute estimate' }) as HTMLButtonElement).disabled).toBe(true);
    cleanup();
    h.accessPending = true;
    await mount();
    const row2 = await screen.findByTestId('pos-wall_ext');
    expect(within(row2).queryByRole('button', { name: 'Save reason' })).toBeNull();
    expect((screen.getByRole('button', { name: 'Compute estimate' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('states', () => {
  it('asks for a project when none is active', async () => {
    h.project = null;
    await mount();
    expect(screen.getByText('Select a project')).toBeTruthy();
  });

  it('shows a skeleton while loading', async () => {
    h.estimate = new Promise(() => {});
    await mount();
    expect(screen.getAllByTestId('skeleton').length).toBeGreaterThan(0);
  });

  it.each([
    [401, 'Your session has ended. Sign in again.'],
    [403, 'You do not have access to this estimate.'],
    [409, 'The estimate changed meanwhile. Reload and try again.'],
    [500, 'The server failed to handle the request. Try again later.'],
    [404, 'The estimate could not be loaded'],
  ])('maps a %i answer to a clear message and offers a retry', async (status, text) => {
    h.estimateError = new HttpError(status, 'server said no');
    await mount();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(text);
    expect(alert.textContent).toContain('server said no');
    expect(within(alert).getByRole('button', { name: 'Retry' })).toBeTruthy();
  });

  it('without an accepted revision points to the revisions page', async () => {
    h.estimate = { estimate: false } as EstimateView;
    h.revisions = [rev(1, { status: 'shared' })];
    await mount();
    expect(await screen.findByText('No accepted revision yet')).toBeTruthy();
    expect((screen.getByText('Open revisions') as HTMLAnchorElement).getAttribute('href')).toBe('/design/revisions');
  });

  it('without rules offers the starter set, prefilled from the brief country', async () => {
    h.estimate = { estimate: false } as EstimateView;
    h.brief = { country: 'DE' };
    h.rules = [];
    const user = await mount();
    expect(await screen.findByText('No estimate rules yet')).toBeTruthy();
    const input = screen.getByLabelText('Country') as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe('DE'));
    await user.click(screen.getByRole('button', { name: 'Install starter rules' }));
    await waitFor(() => expect(h.starter).toHaveBeenCalledWith('p1', 'DE'));
  });

  it('offers the starter set to managers only', async () => {
    h.estimate = { estimate: false } as EstimateView;
    h.access = { can_accept: false, currency: 'EUR', lock: null };
    h.brief = { country: 'DE' };
    await mount();
    await screen.findByText('No estimate rules yet');
    expect((screen.getByRole('button', { name: 'Install starter rules' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Only a project manager can do this.')).toBeTruthy();
  });

  it('shows why a starter install failed', async () => {
    h.estimate = { estimate: false } as EstimateView;
    h.brief = { country: 'FR' };
    h.starter = vi.fn(async () => { throw new HttpError(404, 'No starter rule set for country FR'); });
    const user = await mount();
    await screen.findByText('No estimate rules yet');
    await waitFor(() => expect((screen.getByLabelText('Country') as HTMLInputElement).value).toBe('FR'));
    await user.click(screen.getByRole('button', { name: 'Install starter rules' }));
    expect((await screen.findByTestId('mutation-error')).textContent).toContain('No starter rule set for country FR');
  });

  it('with rules but no estimate offers to compute it, and reports a conflict', async () => {
    h.estimate = { estimate: false } as EstimateView;
    h.rules = [{ id: 'wall_ext', kind: 'model', enabled: true }];
    h.run = vi.fn(async () => { throw new HttpError(409, 'Another run is in progress'); });
    const user = await mount();
    await screen.findByText('The estimate has not been computed');
    await user.click(screen.getByRole('button', { name: 'Compute estimate' }));
    const err = await screen.findByTestId('mutation-error');
    expect(err.textContent).toContain('The estimate changed meanwhile');
    expect(err.textContent).toContain('Another run is in progress');
  });

  it('computing refreshes the estimate', async () => {
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: 'Compute estimate' }));
    await waitFor(() => expect(h.run).toHaveBeenCalledWith('p1'));
    await waitFor(() => expect(h.estimateCalls).toBeGreaterThan(1));
  });

  it('has Russian and German headings', async () => {
    await mount('ru');
    expect(await screen.findByText('Диапазон сметы')).toBeTruthy();
    cleanup();
    await mount('de');
    expect(await screen.findByText('Spanne der Kostenschätzung')).toBeTruthy();
  });
});

describe('answer of a real ERP (live capture)', () => {
  it('renders the range, the unchecked verdict and unpriced positions from the live shape', async () => {
    h.estimate = live;
    h.revisions = [rev(1, { revision_id: (live as { revision_id: string }).revision_id })];
    await mount();
    const totals = await screen.findByTestId('range-totals');
    expect(totals.textContent).toContain('97,245');
    expect(screen.getByTestId('check-unknown')).toBeTruthy();
    expect(screen.queryByTestId('check-inside')).toBeNull();
    // four-decimal quantities are shown without padding; rate 0.0000 is unpriced, not a price of zero
    expect(screen.getByTestId('qty-wall_ext').textContent).toBe('82.5 m²');
    for (const rule of ['wall_ext', 'finishes', 'reinforcement', 'services']) {
      expect(within(screen.getByTestId(`pos-${rule}`)).getAllByText('Unpriced').length).toBeGreaterThan(0);
    }
    expect(screen.getByTestId('subtotal-200').textContent).toContain('3,042');
  });
});

describe('money in the project currency', () => {
  it('shows the project currency, BOQ totals with markups and the new flags', async () => {
    const e = est({
      currency: 'CHF',
      boq: { direct_cost: '49044.00', markups_total: '4904.40', grand_total: '53948.40', currency: 'CHF' },
      inside_range: null,
      inside_range_note: 'server text',
      inside_range_note_code: 'currency_mismatch',
    });
    withPosition(e, 'wall_ext', { flags: ['quantity_missing'] });
    const site = e.positions.find((p) => p.rule === 'site_works');
    if (site) withPosition(e, 'site_works', { flags: ['rate_missing'], provenance: { ...site.provenance, missing_code: 'currency_mismatch' } });
    h.estimate = e;
    await mount();
    expect((await screen.findByTestId('project-currency')).textContent).toBe(EN['design.estimate.project_currency'].replace('{{currency}}', 'CHF'));
    const boq = screen.getByTestId('boq-totals');
    expect(within(boq).getByText(EN['design.estimate.boq_grand_total'])).toBeTruthy();
    expect(boq.textContent).toMatch(/53,948\.40/);
    expect(boq.textContent).toMatch(/CHF/);
    expect(screen.getByTestId('check-unknown').textContent).toContain(EN['design.estimate.note.currency_mismatch']);
    expect(within(screen.getByTestId('pos-wall_ext')).getByText(EN['design.estimate.flag.quantity_missing'])).toBeTruthy();
    if (site) expect(within(screen.getByTestId('pos-site_works')).getByText(EN['design.estimate.flag.currency_mismatch'])).toBeTruthy();
  });
});
