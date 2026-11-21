import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU, DE } from '../testStrings';
import type { Impact, ImpactRow } from '../data/acceptance';
import type { RevisionView } from '../data/revisions';

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
  toast: vi.fn(),
  viewer: null as null | { modelId: string; isolatedIds: string[] | null; overlay: Map<string, string> | null },
  elements: [] as unknown[],
  elementsByModel: {} as Record<string, unknown[]>,
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
vi.mock('../api', () => ({
  fetchRevisions: vi.fn(async () => {
    h.listCalls += 1;
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
  fetchChangeOrderSettings: vi.fn(async () => ({ mode: 'off', can_change: false, can_create: false })),
  fetchRevisionChangeOrder: vi.fn(async () => null),
}));
vi.mock('../procurementApi', () => ({
  fetchProcurementImpact: vi.fn(async (id: string) => ({ schema: 'ddc-procurement-impact/1', revision_id: id, procurement: false })),
  setupProcurement: vi.fn(),
}));
vi.mock('../scheduleApi', () => ({
  fetchScheduleImpact: vi.fn(async (id: string) => ({ schema: 'ddc-schedule-impact/1', revision_id: id, schedule: false })),
  setupSchedule: vi.fn(),
}));
vi.mock('@/features/bim/api', () => ({
  fetchBIMElements: vi.fn(async (id: string) => ({ items: h.elementsByModel[id] ?? [] })),
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

import AcceptancePage from '../AcceptancePage';

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

const queryClientRef: { current: QueryClient | null } = { current: null };

async function mount(lang: 'en' | 'ru' | 'de' = 'en') {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU }, de: { translation: DE } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  queryClientRef.current = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClientRef.current}>
      <I18nextProvider i18n={inst}><MemoryRouter><AcceptancePage /></MemoryRouter></I18nextProvider>
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
  h.viewer = null;
  h.elements = [el('k/new'), el('k/a')];
  h.elementsByModel = { m1: [el('k/a'), el('k/gone')], m2: [el('k/a'), el('k/new')] };
  h.accept = vi.fn(async () => rev(2, { status: 'published' }));
  h.reject = vi.fn(async () => rev(2, { status: 'rejected' }));
  h.toast = vi.fn();
});

const acceptBtn = () => screen.getByRole('button', { name: 'Accept' }) as HTMLButtonElement;

describe('acceptance QA', () => {
  it('a confirmation prompt never carries over to a different revision', async () => {
    h.revisions = [rev(3), rev(2), rev(1, { status: 'published' })];
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    expect(screen.getByTestId('confirm-row')).toBeTruthy();
    // someone else rejects revision 2 meanwhile: the list refreshes and the page now shows revision 3
    h.revisions = [rev(3, { parent_revision_id: 'r1' }), rev(2, { status: 'rejected' }), rev(1, { status: 'published' })];
    await act(async () => { await queryClientRef.current!.invalidateQueries({ queryKey: ['design-revisions'] }); });
    await waitFor(() => expect(screen.getByTestId('model-bar').textContent).toContain('3'));
    expect(screen.queryByTestId('confirm-row')).toBeNull();
  });

  it('keeps the reason when the revision was decided elsewhere (409) and nothing else is pending', async () => {
    h.revisions = [rev(2), rev(1, { status: 'published' })];
    h.accept = vi.fn(async () => { h.revisions = [rev(2, { status: 'published' }), rev(1, { status: 'published' })]; throw new Error('Revision is published, not awaiting a decision'); });
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    await user.click(within(screen.getByTestId('confirm-row')).getAllByRole('button')[0]!);
    await waitFor(() => expect(screen.queryByTestId('confirm-row')).toBeNull());
    expect(await screen.findByText(/not awaiting a decision/)).toBeTruthy();
  });

  it('an access check that fails does not leave Accept enabled', async () => {
    h.access = Promise.reject(new Error('403'));
    await mount();
    await screen.findByTestId('model-bar');
    await waitFor(() => expect(acceptBtn().disabled).toBe(true));
  });

  it('an estimate that falls to zero because nothing matches is not shown as a saving', async () => {
    h.impact = impact([row('a', { flags: ['no_match'], new_quantity: '0', quantity_delta: '-10', cost_delta: '-1000' })],
      { current: '1000', after: '0', delta: '-1000', unpriced_positions: 0 });
    await mount();
    const totals = await screen.findByTestId('totals');
    expect(within(totals).getByText(/-€1,000\.00/).className).not.toMatch(/success/);
  });

  it('quantities follow the page language and use the unit with its exponent', async () => {
    h.impact = impact([row('a', { current_quantity: '28.4000', new_quantity: '0.0000', quantity_delta: '-28.4', unit: 'm2', cost_delta: '-3041.64' })]);
    await mount('de');
    const r = await screen.findByTestId('row-a');
    expect(r.textContent).not.toMatch(/28\.4000/);
    expect(r.textContent).not.toMatch(/ m2\b/);
  });
});
