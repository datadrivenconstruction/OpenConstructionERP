import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN } from './testStrings';

const m = vi.hoisted(() => ({ mid: '' as string, ctxFail: false, user: 'u1' }));
vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (sel: (s: { userId: string }) => unknown) => sel({ userId: m.user }) }));
vi.mock('./api', () => ({
  LINK_VERSION: '1',
  fetchEstimate: vi.fn(async () => ({ estimate: true, total: '6490138.4', positions: [{ rule: 'slab', kind: 'model', unit_rate: '120', total: '6490138.4', flags: [], provenance: {} }], range: { currency: 'EUR', ...(m.mid ? { total: { low: '1', mid: m.mid, high: '2' } } : {}) } })),
  fetchAccess: vi.fn(async () => ({ currency: 'EUR' })),
}));
vi.mock('./FieldReportLinks', () => ({ FieldReportLinks: () => <p>reports</p> }));
vi.mock('./linksApi', async () => ({
  ...(await vi.importActual<object>('./linksApi')),
  fetchOverview: vi.fn(async () => ({ project_id: 'p1', waiting_revision_id: null, steps: [
    { id: 'model', done: true, count: 2, url: '/design/revisions' },
    { id: 'schedule', done: false, count: null, url: '/design/revisions' },
    { id: 'procurement', done: false, count: null, url: '/design/revisions' }] })),
  fetchLinks: vi.fn(async () => ({ keys: ['w1'], positions: [], packages: [],
    activities: [{ activity_id: 'a1', schedule_id: 's1', name: 'Walls 1st floor', start_date: '2027-03-01', end_date: '2027-03-09', storey: '1OG', elements: ['w1'] }] })),
  fetchElementContext: vi.fn(async () => {
    if (m.ctxFail) throw new Error('down');
    return { keys: ['w1'], found: 1, quantities: [{ kind: 'volume_m3', value: '12.5' }],
      documents: [{ document_id: 'd1', name: '1OG.pdf', category: 'drawing', version: 1, link_type: 'design_sheet', revision: 3, elements: ['w1'], url: '/documents?id=d1' }],
      remarks: [{ kind: 'task', id: 't1', title: 'Crack in wall', status: 'open', due: '2027-04-01', elements: ['w1'], url: '/tasks?id=t1' }] };
  }),
}));

import { SelectionPanel } from './SelectionPanel';
import type { DraftLine, DraftView } from './draftApi';

async function mount(selection: { element_key: string; ifc_class?: string }[] = [{ element_key: 'w1', ifc_class: 'IfcWall' }], draft: DraftView | null = null) {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({ lng: 'en', resources: { en: { translation: EN } }, keySeparator: false,
    nsSeparator: false, interpolation: { escapeValue: false } });
  const user = userEvent.setup();
  render(
    <I18nextProvider i18n={inst}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><SelectionPanel projectId="p1" selection={selection} draft={draft} /></MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
  return user;
}
const order = () => screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);

beforeEach(() => { cleanup(); localStorage.clear(); m.ctxFail = false; m.user = 'u1'; m.mid = ''; });

describe('selection panel', () => {
  it('with nothing selected it shows the project in figures and the next steps', async () => {
    await mount([]);
    expect(await screen.findByTestId('snapshot-total')).toHaveTextContent(/^€\s?6,490,138$/);
    expect(screen.getByTestId('snapshot-label')).toHaveTextContent(EN['design.estimate.priced_total']!);
    expect(screen.getByTestId('snapshot-estimate')).toHaveTextContent('1 of 1 priced');
    expect(screen.getByTestId('project-snapshot')).toHaveTextContent(EN['design.overview.step.model']! + '2');
    expect(screen.getByTestId('snapshot-next-schedule')).toHaveAttribute('href', '/design/revisions');
    expect(screen.getByTestId('snapshot-status-schedule')).toHaveTextContent(EN['design.overview.todo.schedule']!);
    expect(screen.getByTestId('snapshot-next-schedule')).toHaveTextContent(EN['design.overview.action.schedule']!);
    expect(screen.queryByTestId('block-estimate')).toBeNull();
  });

  it('with a range the hero is the same figure and label as the estimate page (mid), priced sum named below', async () => {
    m.mid = '5190000';
    await mount([]);
    expect(await screen.findByTestId('snapshot-total')).toHaveTextContent(/^€\s?5,190,000$/);
    expect(screen.getByTestId('snapshot-label')).toHaveTextContent(`${EN['design.estimate.range']!} · ${EN['design.estimate.mid']!}`);
    expect(screen.getByTestId('snapshot-priced')).toHaveTextContent(new RegExp(`${EN['design.estimate.priced_total']!} €\\s?6,490,138`));
  });

  it('shows every block: cost, quantities, BOQ, schedule, procurement, documents, field reports, remarks', async () => {
    await mount();
    expect(order()).toEqual(['estimate', 'quantities', 'boq', 'schedule', 'procurement', 'documents', 'field_reports', 'remarks']
      .map((b) => EN[`design.panel.block.${b}`]!));
    expect(await screen.findByTestId('selection-quantities')).toHaveTextContent('Volume, m³12.5');
    expect(screen.getByTestId('doc-d1')).toHaveAttribute('href', '/documents?id=d1');
    expect(screen.getByTestId('doc-d1')).toHaveTextContent('Sheet, revision 3');
    expect(screen.getByTestId('remark-t1')).toHaveTextContent('Crack in wall');
    expect(screen.getByTestId('remark-t1')).toHaveTextContent('open · due 2027-04-01');
    expect(await screen.findByTestId('link-activity-a1')).toBeTruthy();
    expect(within(screen.getByTestId('block-boq')).getByText(EN['design.panel.none.boq']!)).toBeTruthy();
  });

  it('blocks are hidden and reordered (buttons and Alt+arrows), remembered per user', async () => {
    const user = await mount();
    await user.click(screen.getByTestId('panel-customize'));
    expect(screen.getByTestId('panel-customize')).toHaveAttribute('aria-expanded', 'true');
    const box = screen.getByRole('checkbox', { name: EN['design.panel.block.estimate']! });
    expect(document.activeElement).toBe(box);
    await user.keyboard('{Alt>}{ArrowDown}{/Alt}');
    expect(order().slice(0, 2)).toEqual([EN['design.panel.block.quantities']!, EN['design.panel.block.estimate']!]);
    expect(document.activeElement).toBe(screen.getByRole('checkbox', { name: EN['design.panel.block.estimate']! }));
    await user.click(screen.getByRole('button', { name: 'Move Open remarks up' }));
    await user.click(screen.getByRole('checkbox', { name: EN['design.panel.block.documents']! }));
    expect(screen.queryByTestId('block-documents')).toBeNull();
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('panel-chooser')).toBeNull();
    expect(document.activeElement).toBe(screen.getByTestId('panel-customize'));
    expect(JSON.parse(localStorage.getItem('ddc-design-selection-panel:u1')!)).toEqual({
      order: ['quantities', 'estimate', 'boq', 'schedule', 'procurement', 'documents', 'remarks', 'field_reports'], hidden: ['documents'],
    });
    cleanup();
    m.user = 'u2';
    await mount();
    expect(order()[0]).toBe(EN['design.panel.block.estimate']!); // another person keeps the default
  });

  it('a block that cannot load says so and retries; hiding all says how to get them back', async () => {
    m.ctxFail = true;
    const user = await mount();
    const docs = screen.getByTestId('block-documents');
    expect(await within(docs).findByText(/Could not be loaded/)).toBeTruthy();
    m.ctxFail = false;
    await user.click(within(docs).getByRole('button', { name: EN['design.panel.retry']! }));
    expect(await screen.findByTestId('doc-d1')).toBeTruthy();
    await user.click(screen.getByTestId('panel-customize'));
    for (const b of screen.getAllByRole('checkbox')) await user.click(b);
    expect(screen.getByTestId('panel-all-hidden')).toHaveTextContent(EN['design.panel.all_hidden']!);
    await user.click(screen.getByTestId('panel-reset'));
    expect(order()).toHaveLength(8);
  });

  it('a line without a rate or outside the accepted model shows why, never a 0 total', async () => {
    const line = (o: Partial<DraftLine>): DraftLine => ({ rule: 'r', unit: 'm2', elements: 1, element_keys: ['w1'], quantity: '20',
      current_quantity: '20', unit_rate: '50', total: '1000', current_total: '1000', position_id: 'p', description: 'Priced wall', flags: [], ...o });
    const draft = { project_id: 'p1', revision_id: 'r', parent_revision_id: null, package_sha256: 'a', package_bytes: 1, element_count: 1,
      updated_at: '2026-11-25T10:00:00Z', estimate: { estimate: true, model_total: '1000', lines: [
        line({}),
        line({ rule: 'wall_ext', description: 'Outer wall', unit_rate: '0', total: null, flags: ['rate_missing'] }),
        line({ rule: 'stair', description: 'stair', unit_rate: null, total: null, current_quantity: null, position_id: null, flags: ['no_position'] }),
      ] } } as DraftView;
    await mount([{ element_key: 'w1', ifc_class: 'IfcWall' }], draft);
    const unpriced = within(screen.getByTestId('line-wall_ext'));
    expect(unpriced.getByTestId('line-unpriced')).toHaveTextContent(EN['design.panel.unpriced.no_source']!);
    expect(unpriced.getByRole('link')).toHaveAttribute('href', '/costs/import');
    expect(screen.getByTestId('line-wall_ext')).not.toHaveTextContent('€');
    expect(within(screen.getByTestId('line-stair')).getByRole('link')).toHaveAttribute('href', '/design/acceptance');
    expect(screen.getByTestId('line-stair')).toHaveTextContent(EN['design.panel.unpriced.not_accepted']!);
    expect(screen.getByTestId('selection-cost')).toHaveTextContent(/1,000/);
    expect(screen.getByTestId('selection-cost')).toHaveTextContent('1 of 3 priced');
  });
});
