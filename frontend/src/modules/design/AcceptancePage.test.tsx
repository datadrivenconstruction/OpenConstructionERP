import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
afterEach(() => usePreferencesStore.setState({ numberLocale: 'auto' }));
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU, DE } from './testStrings';
import type { Impact, ImpactRow } from './data/acceptance';
import type { RevisionView } from './data/revisions';

const h = vi.hoisted(() => ({
  project: 'p1' as string | null,
  revisions: [] as unknown[],
  access: { can_accept: true, currency: 'EUR', lock: null } as unknown,
  impact: null as unknown,
  impactError: false,
  revisionsError: false,
  accept: vi.fn(),
  reject: vi.fn(),
  listCalls: 0,
  listHangs: false,
  toast: vi.fn(),
  viewer: null as null | { modelId: string; isolatedIds: string[] | null; overlay: Map<string, string> | null },
  elements: [] as unknown[],
  elementsByModel: {} as Record<string, unknown[]>,
  coSettings: { mode: 'off', can_change: true, can_create: true } as unknown,
  coView: null as unknown,
  coCreate: vi.fn(),
  coMode: vi.fn(),
  scheduleCalls: 0,
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (sel: (s: { activeProjectId: string | null }) => unknown) => sel({ activeProjectId: h.project }),
}));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: unknown }) => unknown) => sel({ addToast: h.toast }),
}));
vi.mock('@/shared/lib/api', () => ({
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock('./api', () => ({
  fetchRevisions: vi.fn(async () => {
    h.listCalls += 1;
    if (h.listHangs) return new Promise<never>(() => {});
    if (h.revisionsError) throw new Error('list down');
    return h.revisions;
  }),
  fetchAccess: vi.fn(async () => h.access),
  fetchImpact: vi.fn(async () => {
    if (h.impactError) throw new Error('impact down');
    return h.impact;
  }),
  acceptRevision: (...a: unknown[]) => h.accept(...a),
  rejectRevision: (...a: unknown[]) => h.reject(...a),
  fetchChangeOrderSettings: vi.fn(async () => h.coSettings),
  saveChangeOrderMode: (...a: unknown[]) => h.coMode(...a),
  fetchRevisionChangeOrder: vi.fn(async () => h.coView),
  createRevisionChangeOrder: (...a: unknown[]) => h.coCreate(...a),
}));
vi.mock('./procurementApi', () => ({
  fetchProcurementImpact: vi.fn(async (id: string) => ({ schema: 'ddc-procurement-impact/1', revision_id: id, procurement: false })),
  setupProcurement: vi.fn(),
}));
vi.mock('./scheduleApi', () => ({
  fetchScheduleImpact: vi.fn(async (id: string) => {
    h.scheduleCalls += 1;
    return { schema: 'ddc-schedule-impact/1', revision_id: id, schedule: false };
  }),
  setupSchedule: vi.fn(),
}));
vi.mock('@/features/bim/api', () => ({
  fetchBIMElements: vi.fn(async (id: string) => ({ items: h.elementsByModel[id] ?? [], total: (h.elementsByModel[id] ?? []).length })),
}));
vi.mock('@/features/bim/useModelViewerData', () => ({
  useModelViewerData: (_p: string, id: string | null) => ({
    activeModel: id ? { id, metadata: {} } : null, elements: h.elements, geometryUrl: id ? `/g/${id}` : null,
    isLoadingElements: false, isLoadingModels: false, models: [],
  }),
}));
vi.mock('@/shared/ui/BIMViewer', () => ({
  BIMViewer: (p: { modelId: string; isolatedIds: string[] | null; diffChangeByStableId: Map<string, string> | null }) => {
    h.viewer = { modelId: p.modelId, isolatedIds: p.isolatedIds, overlay: p.diffChangeByStableId };
    return <div data-testid="viewer">viewer {p.modelId}</div>;
  },
}));
vi.mock('@/shared/ui', async () => {
  const React = await import('react');
  const box = (name: string) => ({ children, title, description, hint, onRetry }: Record<string, unknown>) =>
    React.createElement('div', { 'data-ui': name, role: name === 'ErrorState' ? 'alert' : undefined },
      React.createElement('p', null, title as string), React.createElement('p', null, (description ?? hint) as string),
      onRetry ? React.createElement('button', { onClick: onRetry as () => void }, 'Retry') : null, children as never);
  return {
    Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
    Button: ({ children, loading, icon: _i, variant: _v, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; icon?: unknown; variant?: string }) =>
      <button type="button" {...rest} disabled={rest.disabled || loading}>{children}</button>,
    Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
    CardHeader: ({ title }: { title: string }) => <header>{title}</header>,
    EmptyState: box('EmptyState'), ErrorState: box('ErrorState'),
    PageHeader: ({ srTitle, subtitle }: { srTitle?: string; subtitle?: string }) => <header><h1>{srTitle}</h1><p>{subtitle}</p></header>,
    Skeleton: () => <span data-testid="skeleton" />,
  };
});

import AcceptancePage from './AcceptancePage';

const rev = (n: number, over: Partial<RevisionView> = {}): RevisionView => ({
  revision_id: `r${n}`, project_id: 'p1', number: n, parent_revision_id: n > 1 ? `r${n - 1}` : null, status: 'shared',
  source_kind: 'editor', depth_level: 'D2', message: `message ${n}`, bim_model_id: `m${n}`, decided_by: null,
  decided_at: null, decision_comment: null, created_at: '2026-01-01T10:00:00Z', ...over,
});
const row = (rule: string, over: Partial<ImpactRow> = {}): ImpactRow => ({
  rule, label: `Label ${rule}`, cost_group: '331', unit: 'm2', position_id: `pos-${rule}`, ordinal: '1', new_position: false,
  current_quantity: '10', model_quantity_now: '10', model_quantity_new: '10', new_quantity: '10', quantity_delta: '0',
  override: false, override_quantity: null, unit_rate: '100', cost_delta: '0', flags: [],
  elements: { before: 1, after: 1, added: [], removed: [], added_count: 0, removed_count: 0 }, ...over,
});
const impact = (rows: ImpactRow[], totals?: Impact['totals']): Impact => ({
  schema: 'ddc-impact/1', revision_id: 'r2', estimate: true, rows, model_delta_by_type: [],
  totals: totals ?? { current: '1000', after: '1700.5', delta: '700.5', unpriced_positions: 0 },
});
const el = (key: string, hash = 'h') => ({ id: `id-${key}`, stable_id: key, name: key, element_type: 'Wall', storey: 'EG',
  geometry_hash: hash, quantities: { area_m2: 10 } });

async function mount(lang: 'en' | 'ru' | 'de' = 'en', path = '/design/acceptance') {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU }, de: { translation: DE } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}><MemoryRouter initialEntries={[path]}><AcceptancePage /></MemoryRouter></I18nextProvider>
    </QueryClientProvider>,
  );
  return user;
}

beforeEach(() => {
  cleanup();
  h.project = 'p1';
  h.revisions = [rev(2), rev(1, { status: 'published' })];
  h.access = { can_accept: true, currency: 'EUR', lock: null };
  h.impact = impact([
    row('walls', { quantity_delta: '20', new_quantity: '30', cost_delta: '2000', elements: { before: 1, after: 3, added: ['k/new'], removed: [], added_count: 2, removed_count: 0 } }),
    row('slab', { override: true, override_quantity: '12', model_quantity_new: '14', flags: ['override'] }),
    row('roof', { flags: ['no_match'] }),
    row('doors'),
  ]);
  h.impactError = false;
  h.revisionsError = false;
  h.listCalls = 0;
  h.listHangs = false;
  h.viewer = null;
  h.elements = [el('k/new'), el('k/a')];
  h.elementsByModel = { m1: [el('k/a'), el('k/gone')], m2: [el('k/a'), el('k/new')] };
  h.accept = vi.fn(async () => rev(2, { status: 'published' }));
  h.reject = vi.fn(async () => rev(2, { status: 'rejected' }));
  h.toast = vi.fn();
  h.coSettings = { mode: 'off', can_change: true, can_create: true };
  h.coView = null;
  h.coCreate = vi.fn();
  h.coMode = vi.fn(async (_p: string, mode: string) => ({ mode }));
  h.scheduleCalls = 0;
});

const acceptBtn = () => screen.getByRole('button', { name: 'Accept' }) as HTMLButtonElement;
const rejectBtn = () => screen.getByRole('button', { name: 'Reject' }) as HTMLButtonElement;

describe('AcceptancePage states', () => {
  it('asks for a project when none is active', async () => {
    h.project = null;
    await mount();
    expect(screen.getByText('Select a project')).toBeTruthy();
  });

  it('says so when nothing waits for a decision', async () => {
    h.revisions = [rev(1, { status: 'published' })];
    await mount();
    expect(await screen.findByText('Nothing waits for a decision')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull();
    // after the usual single accept, schedule and take-off are set up from here, for the accepted revision
    expect(await screen.findByTestId('schedule-setup')).toBeTruthy();
    expect(await screen.findByTestId('procurement-setup')).toBeTruthy();
    expect(vi.mocked((await import('./scheduleApi')).fetchScheduleImpact)).toHaveBeenCalledWith('r1');
  });

  it('says so with no revisions at all', async () => {
    h.revisions = [];
    await mount();
    expect(await screen.findByText('Nothing waits for a decision')).toBeTruthy();
  });

  it('shows the list error and retries', async () => {
    h.revisionsError = true;
    const user = await mount();
    expect(await screen.findByText('list down')).toBeTruthy();
    h.revisionsError = false;
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('button', { name: 'Accept' })).toBeTruthy();
  });

  it('shows the impact error without hiding the decision', async () => {
    h.impactError = true;
    await mount();
    expect(await screen.findByText('impact down')).toBeTruthy();
    expect(acceptBtn()).toBeTruthy();
  });

  it('says when the project has no estimate yet', async () => {
    h.impact = { ...impact([]), estimate: false, totals: undefined };
    await mount();
    expect(await screen.findByTestId('no-estimate')).toBeTruthy();
  });

  it('says when no position changes', async () => {
    h.impact = impact([row('a'), row('b')], { current: '5', after: '5', delta: '0', unpriced_positions: 0 });
    await mount();
    expect(await screen.findByTestId('no-movement')).toBeTruthy();
    expect(screen.getByText('2 positions stay the same.')).toBeTruthy();
  });
});

describe('AcceptancePage impact', () => {
  it('lists overrides and flagged positions first, then the ones that change, and counts the rest', async () => {
    await mount();
    const attention = await screen.findByTestId('attention-rows');
    expect(within(attention).getAllByRole('button').map((b) => b.getAttribute('data-testid'))).toEqual(['row-slab', 'row-roof']);
    const moving = screen.getByTestId('moving-rows');
    expect(within(moving).getAllByRole('button').map((b) => b.getAttribute('data-testid'))).toEqual(['row-walls']);
    expect(screen.getByText('1 positions stay the same.')).toBeTruthy();
    expect(attention.textContent).toContain('Manual quantity');
    expect(attention.textContent).toContain('Your quantity 12 m² is kept; the model says 14 m².');
    expect(attention.textContent).toContain('Matches nothing now');
  });

  it('shows the totals with sign and currency', async () => {
    await mount();
    const totals = await screen.findByTestId('totals');
    expect(totals.textContent).toMatch(/€\s?1,000\.00/);
    expect(totals.textContent).toMatch(/€\s?1,700\.50/);
    expect(totals.textContent).toMatch(/\+€\s?700\.50/);
  });

  it('a negative change shows its minus', async () => {
    h.impact = impact([row('a', { quantity_delta: '-2', cost_delta: '-200' })], { current: '1000', after: '800', delta: '-200', unpriced_positions: 0 });
    await mount();
    expect((await screen.findByTestId('totals')).textContent).toMatch(/-€\s?200\.00/);
  });

  it('warns about positions without a price', async () => {
    h.impact = impact([row('a')], { current: '0', after: '0', delta: '0', unpriced_positions: 3 });
    await mount();
    const note = await screen.findByTestId('unpriced');
    expect(note.textContent).toContain('3 positions have no price');
    expect(note.textContent).toContain('count as zero');
    expect(screen.getByTestId('unpriced-link').getAttribute('href')).toBe('/design/estimate');
  });

  it('the decision card comes before the estimate in the page order so stacked layouts reach it first', async () => {
    h.impact = impact([row('a')]);
    await mount();
    const totals = await screen.findByTestId('totals');
    const accept = screen.getByRole('button', { name: 'Accept' });
    expect(accept.compareDocumentPosition(totals) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('clicking a row isolates its added elements in the viewer, and again releases them', async () => {
    const user = await mount();
    await user.click(await screen.findByTestId('row-walls'));
    await waitFor(() => expect(h.viewer?.isolatedIds).toEqual(['id-k/new']));
    await user.click(screen.getByTestId('row-walls'));
    await waitFor(() => expect(h.viewer?.isolatedIds).toBeNull());
  });

  it('the viewer shows the revision with the change overlay against its base', async () => {
    await mount();
    await screen.findByTestId('viewer');
    await waitFor(() => expect([...(h.viewer?.overlay ?? [])]).toEqual([['k/new', 'added']]));
    expect(h.viewer?.modelId).toBe('m2');
    expect((await screen.findByTestId('model-bar')).textContent).toContain('1 removed');
  });

  it('the first revision has no base to compare with', async () => {
    h.revisions = [rev(1)];
    h.impact = impact([]);
    await mount();
    expect((await screen.findByTestId('model-bar')).textContent).toContain('First revision');
  });
});

describe('AcceptancePage who may decide', () => {
  it('a non-manager sees why and cannot press anything', async () => {
    h.access = { can_accept: false, currency: 'EUR', lock: null };
    await mount();
    expect(await screen.findByTestId('blocker-role')).toBeTruthy();
    expect(acceptBtn().disabled).toBe(true);
    expect(rejectBtn().disabled).toBe(true);
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(true);
  });

  it('a revision based on an older accepted one is stale', async () => {
    h.revisions = [rev(3, { parent_revision_id: 'r1' }), rev(2, { status: 'published', parent_revision_id: 'r1' }), rev(1, { status: 'archived' })];
    await mount();
    expect(await screen.findByTestId('blocker-stale')).toBeTruthy();
    expect(acceptBtn().disabled).toBe(true);
  });

  it('a stale or waiting revision cannot be accepted but can still be rejected', async () => {
    h.revisions = [rev(3, { parent_revision_id: 'r2' }), rev(2, { parent_revision_id: 'r1' }), rev(1, { status: 'published' })];
    const user = await mount('en', '/design/acceptance?revision=r3');
    expect((await screen.findByTestId('blocker-waiting')).textContent)
      .toContain('Revision 2, which this one builds on, is still waiting');
    expect(acceptBtn().disabled).toBe(true);
    await user.type(screen.getByRole('textbox'), 'superseded');
    expect(rejectBtn().disabled).toBe(false);
    await user.click(rejectBtn());
    await user.click(screen.getByRole('button', { name: 'Confirm reject' }));
    await waitFor(() => expect(h.reject).toHaveBeenCalledWith('r3', 'superseded'));
  });

  it('a lock held by someone else is shown but does not block the decision', async () => {
    h.access = { can_accept: true, currency: 'EUR', lock: { held_by: 'Erika Muster', mine: false, expires_at: '2026-01-01T00:00:00Z' } };
    await mount();
    expect((await screen.findByTestId('lock-notice')).textContent).toContain('Erika Muster');
    expect(acceptBtn().disabled).toBe(false);
  });

  it('my own lock shows nothing', async () => {
    h.access = { can_accept: true, currency: 'EUR', lock: { held_by: 'Me', mine: true, expires_at: '2026-01-01T00:00:00Z' } };
    await mount();
    await screen.findByRole('button', { name: 'Accept' });
    expect(screen.queryByTestId('lock-notice')).toBeNull();
  });
});

describe('AcceptancePage deciding', () => {
  it('accepting needs a second step and sends the comment', async () => {
    const user = await mount();
    await screen.findByTestId('totals');
    await user.type(screen.getByRole('textbox'), '  fine  ');
    await user.click(acceptBtn());
    expect(h.accept).not.toHaveBeenCalled();
    const confirm = screen.getByTestId('confirm-row');
    expect(confirm.textContent).toContain('Accepting updates 1 positions');
    await user.click(within(confirm).getByRole('button', { name: 'Confirm accept' }));
    await waitFor(() => expect(h.accept).toHaveBeenCalledTimes(1));
    expect(h.accept).toHaveBeenCalledWith('r2', '  fine  ');
    await waitFor(() => expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success', title: 'Revision 2 accepted' })));
  });

  it('a decided revision leaves the queue at once, before the list reloads', async () => {
    const user = await mount();
    await screen.findByTestId('totals');
    h.listHangs = true;
    await user.click(acceptBtn());
    await user.click(within(screen.getByTestId('confirm-row')).getByRole('button', { name: 'Confirm accept' }));
    expect(await screen.findByText('Nothing waits for a decision')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull();
  });

  it('refreshes the revision list after a decision, whatever the result', async () => {
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    const before = h.listCalls;
    await user.click(screen.getByRole('button', { name: 'Confirm accept' }));
    await waitFor(() => expect(h.listCalls).toBeGreaterThan(before));
  });

  it('cancel leaves everything as it was', async () => {
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByTestId('confirm-row')).toBeNull();
    expect(h.accept).not.toHaveBeenCalled();
  });

  it('a failed accept says nothing changed, shows the reason, and lets the person try again', async () => {
    h.accept = vi.fn(async () => { throw new Error('Another revision was accepted at the same time'); });
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    const before = h.listCalls;
    await user.click(screen.getByRole('button', { name: 'Confirm accept' }));
    const failed = await screen.findByTestId('decision-failed');
    expect(failed.textContent).toContain('Nothing was changed.');
    expect(failed.textContent).toContain('Another revision was accepted at the same time');
    expect(h.toast).not.toHaveBeenCalled();
    await waitFor(() => expect(h.listCalls).toBeGreaterThan(before));
    expect(screen.queryByTestId('confirm-row')).toBeNull();
    expect(acceptBtn().disabled).toBe(false);
    h.accept = vi.fn(async () => rev(2, { status: 'published' }));
    await user.click(acceptBtn());
    await user.click(screen.getByRole('button', { name: 'Confirm accept' }));
    await waitFor(() => expect(screen.queryByTestId('decision-failed')).toBeNull());
  });

  it('a 403 from the server surfaces the same way', async () => {
    h.accept = vi.fn(async () => { throw new Error('Only a project manager may decide on revisions'); });
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    await user.click(screen.getByRole('button', { name: 'Confirm accept' }));
    expect((await screen.findByTestId('decision-failed')).textContent).toContain('Only a project manager');
  });

  it('rejecting needs a comment', async () => {
    const user = await mount();
    await screen.findByTestId('totals');
    expect(rejectBtn().disabled).toBe(true);
    expect(screen.getByText('Write a reason to reject.')).toBeTruthy();
    await user.type(screen.getByRole('textbox'), '   ');
    expect(rejectBtn().disabled).toBe(true);
    await user.type(screen.getByRole('textbox'), 'wrong storey count');
    expect(rejectBtn().disabled).toBe(false);
    await user.click(rejectBtn());
    expect(screen.getByTestId('confirm-row').textContent).toContain('estimate stays as it is');
    await user.click(screen.getByRole('button', { name: 'Confirm reject' }));
    await waitFor(() => expect(h.reject).toHaveBeenCalledWith('r2', expect.stringContaining('wrong storey count')));
    expect(h.accept).not.toHaveBeenCalled();
    await waitFor(() => expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Revision 2 rejected' })));
  });

  it('with several waiting revisions the oldest is shown and another can be picked', async () => {
    h.revisions = [rev(4, { parent_revision_id: 'r1' }), rev(2, { parent_revision_id: 'r1' }), rev(1, { status: 'published' })];
    h.coSettings = { mode: 'off', can_change: false, can_create: true };  // only the revision picker is a combobox
    const user = await mount();
    const select = (await screen.findByRole('combobox')) as HTMLSelectElement;
    expect(select.value).toBe('r2');
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Revision 2 - message 2', 'Revision 4 - message 4',
    ]);
    await user.selectOptions(select, 'r4');
    await waitFor(() => expect(h.viewer?.modelId).toBe('m4'));
  });

  it('opened for a waiting revision (?revision=) shows that one, not the oldest', async () => {
    h.revisions = [rev(4, { parent_revision_id: 'r1' }), rev(2, { parent_revision_id: 'r1' }), rev(1, { status: 'published' })];
    h.coSettings = { mode: 'off', can_change: false, can_create: true };
    await mount('en', '/design/acceptance?revision=r4');
    const select = (await screen.findByRole('combobox')) as HTMLSelectElement;
    expect(select.value).toBe('r4');
    await waitFor(() => expect(h.viewer?.modelId).toBe('m4'));
  });
});

describe('AcceptancePage keyboard and languages', () => {
  it('everything is reachable by keyboard and Enter opens the confirmation', async () => {
    const user = await mount();
    await screen.findByTestId('totals');
    acceptBtn().focus();
    await user.keyboard('{Enter}');
    expect(screen.getByTestId('confirm-row')).toBeTruthy();
    // Focus moves to the confirming button so Enter again completes it without a mouse.
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Confirm accept' }));
  });

  it('rows toggle with the keyboard', async () => {
    const user = await mount();
    const rowBtn = await screen.findByTestId('row-walls');
    rowBtn.focus();
    await user.keyboard(' ');
    expect(rowBtn.getAttribute('aria-pressed')).toBe('true');
  });

  it.each([
    ['ru', 'Принять', 'Требуют внимания (2)', '1 000,00'],
    ['de', 'Annehmen', 'Zu prüfen (2)', '1.000,00'],
  ] as const)('renders %s', async (lang, accept, attention, current) => {
    // Amounts follow the ERP's number format setting ('auto' = the UI language of the app's own i18n).
    usePreferencesStore.setState({ numberLocale: lang === 'ru' ? 'ru-RU' : 'de-DE' });
    await mount(lang);
    expect(await screen.findByRole('button', { name: accept })).toBeTruthy();
    expect(await screen.findByText(attention)).toBeTruthy();
    expect((await screen.findByTestId('totals')).textContent).toContain(current);
  });
});

describe('AcceptancePage estimate link', () => {
  it('links from the estimate panel to the estimate screen', async () => {
    await mount();
    const link = (await screen.findByTestId('estimate-link')) as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('/design/estimate');
  });
});

describe('AcceptancePage change orders (R9)', () => {
  const created = (over: Record<string, unknown> = {}) => ({
    revision_id: 'r2', number: 2, revision_status: 'published', mode: 'ask', state: 'created', snapshot: true,
    change_order: { id: 'co1', code: 'CO-007', title: 'Design revision R2', status: 'draft', cost_impact: '700.5',
      currency: 'EUR', unpriced_positions: 2, url: '/changeorders?highlight=co1' }, ...over,
  });

  it('asks on accept, sends the answer and then links the draft change order', async () => {
    h.coSettings = { mode: 'ask', can_change: true, can_create: true };
    h.coView = created();
    const user = await mount();
    await screen.findByTestId('totals');
    await user.click(acceptBtn());
    const confirm = screen.getByTestId('confirm-row');
    const box = within(confirm).getByRole('checkbox') as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(screen.getByTestId('co-ask').textContent).toContain('Also draft a change order');
    await user.click(box);
    h.revisions = [rev(2, { status: 'published' }), rev(1, { status: 'archived' })];
    await user.click(within(confirm).getByRole('button', { name: 'Confirm accept' }));
    await waitFor(() => expect(h.accept).toHaveBeenCalledWith('r2', '', true));
    const note = await screen.findByTestId('co-note');
    expect(note.textContent).toContain('Revision 2: Accepted');
    expect(note.textContent).toContain('Draft change order CO-007 created.');
    expect(note.textContent).toContain('700.5');
    expect(screen.getByTestId('co-unpriced').textContent).toContain('Positions without a rate: 2');
    expect(screen.getByTestId('co-open').getAttribute('href')).toBe('/changeorders?highlight=co1');
    expect(note.textContent).toContain('never automatically');
  });

  it('leaving the box empty accepts without a change order', async () => {
    h.coSettings = { mode: 'ask', can_change: true, can_create: true };
    const user = await mount();
    await screen.findByTestId('totals');
    await user.click(acceptBtn());
    await user.click(within(screen.getByTestId('confirm-row')).getByRole('button', { name: 'Confirm accept' }));
    await waitFor(() => expect(h.accept).toHaveBeenCalledWith('r2', '', false));
  });

  it('"always" states it, and warns when the role may not create change orders', async () => {
    h.coSettings = { mode: 'always', can_change: false, can_create: false };
    const user = await mount();
    await screen.findByTestId('totals');
    await user.click(acceptBtn());
    expect(within(screen.getByTestId('confirm-row')).queryByRole('checkbox')).toBeNull();
    const note = screen.getByTestId('co-always').textContent ?? '';
    expect(note).toContain('will be created');
    expect(note).toContain('may not create change orders');
    expect(screen.queryByTestId('co-mode')).toBeNull();
    await user.click(within(screen.getByTestId('confirm-row')).getByRole('button', { name: 'Confirm accept' }));
    await waitFor(() => expect(h.accept).toHaveBeenCalledWith('r2', ''));
  });

  it('"off" says nothing on accept; a manager switches the setting', async () => {
    const user = await mount();
    await screen.findByTestId('totals');
    await user.click(acceptBtn());
    expect(screen.queryByTestId('co-ask')).toBeNull();
    expect(screen.queryByTestId('co-always')).toBeNull();
    const mode = screen.getByTestId('co-mode') as HTMLSelectElement;
    expect(mode.value).toBe('off');
    await user.selectOptions(mode, 'always');
    await waitFor(() => expect(h.coMode).toHaveBeenCalledWith('p1', 'always'));
  });

  it('opened from a change order (?revision=) shows that revision, and a declined one can be drafted once', async () => {
    h.revisions = [rev(2, { status: 'published' }), rev(1, { status: 'archived' })];
    h.coSettings = { mode: 'ask', can_change: true, can_create: true };
    h.coView = created({ state: 'declined', change_order: null });
    h.coCreate = vi.fn(async () => created());
    const user = await mount('en', '/design/acceptance?revision=r2');
    const note = await screen.findByTestId('co-note');
    expect(note.textContent).toContain('No change order was drafted');
    await user.click(screen.getByTestId('co-create'));
    await waitFor(() => expect(h.coCreate).toHaveBeenCalledWith('r2'));
    expect((await screen.findByTestId('co-open')).getAttribute('href')).toBe('/changeorders?highlight=co1');
    expect(screen.queryByTestId('co-create')).toBeNull();
  });

  it('a revision accepted with the setting off says why no change order can be drafted', async () => {
    h.revisions = [rev(2, { status: 'published' }), rev(1, { status: 'archived' })];
    h.coView = created({ mode: 'off', state: 'none', snapshot: false, change_order: null });
    await mount('ru', '/design/acceptance?revision=r2');
    const note = await screen.findByTestId('co-note');
    expect(note.textContent).toContain('снимка стоимости для черновика нет');
    expect(screen.queryByTestId('co-create')).toBeNull();
  });

  it('ignores ?revision= of a revision that still waits for a decision', async () => {
    await mount('en', '/design/acceptance?revision=r2');
    await screen.findByTestId('totals');
    expect(screen.queryByTestId('co-note')).toBeNull();
  });
});

describe('AcceptancePage schedule', () => {
  it('shows the schedule delta under the estimate delta and asks again after an accept', async () => {
    const user = await mount();
    expect(await screen.findByTestId('no-schedule')).toBeTruthy();
    await screen.findByTestId('totals');
    expect(screen.getByTestId('schedule-setup')).toBeTruthy();
    const before = h.scheduleCalls;
    await user.click(acceptBtn());
    await user.click(within(screen.getByTestId('confirm-row')).getByRole('button', { name: 'Confirm accept' }));
    await waitFor(() => expect(h.accept).toHaveBeenCalled());
    await waitFor(() => expect(h.scheduleCalls).toBeGreaterThan(before));
  });
});
