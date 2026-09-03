// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// The Work Requests screens against a mocked backend: tabs from the
// departments, board columns from the stages, the raise dialog's dynamic
// fields and the body it posts, the needs-info banner, a planner cell
// edit, the 409 shown inline, and the honest state on a server without
// the module.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import type { Department, Planner, Summary, WorkRequest } from './api';
import {
  NEUTRAL,
  addDays,
  addMonths,
  dayHead,
  dayOf,
  daysBetween,
  fieldSpecsOf,
  firstOfMonth,
  fmtMoney,
  isoDay,
  matchesTypes,
  mondayOf,
  moneyNumber,
  monthGrid,
  plotsFor,
  resolveColour,
  sameMonth,
  statusPath,
  tintStyle,
  typeKeysOf,
  typeLabelsOf,
  typesOf,
  unionDisciplines,
  unionFields,
} from './lib';

const m = vi.hoisted(() => ({
  fetchDepartments: vi.fn(),
  fetchRequests: vi.fn(),
  fetchRequest: vi.fn(),
  fetchSummary: vi.fn(),
  fetchMyQueue: vi.fn(),
  fetchUsers: vi.fn(),
  fetchProjects: vi.fn(),
  fetchMe: vi.fn(),
  createRequest: vi.fn(),
  moveStage: vi.fn(),
  patchRequest: vi.fn(),
  answerInfo: vi.fn(),
  fetchHours: vi.fn(),
  fetchComments: vi.fn(),
  fetchActivity: vi.fn(),
  fetchPlanner: vi.fn(),
  putPlannerAlloc: vi.fn(),
  putPlannerCapacity: vi.fn(),
  patchDepartment: vi.fn(),
  createRequestType: vi.fn(),
  patchRequestType: vi.fn(),
  deleteRequestType: vi.fn(),
  reorderRequestTypes: vi.fn(),
}));

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  ...m,
}));

import WorkRequestsPage from './WorkRequestsPage';
import ManageDepartmentsPage, { slugKey } from './ManageDepartmentsPage';
import { RequestDetail } from './RequestDetail';
import { PlannerView } from './PlannerView';
import { useRequestActions } from './actions';

/* ── Fixtures (no real people, companies or jobs) ─────────────────── */

const WORKSHOP: Department = {
  key: 'workshop',
  name: 'Workshop',
  prefix: 'WKS',
  position: 0,
  colour: '#a4470c',
  description: 'Switchboard build and test',
  active: true,
  lead_user_id: 'u2',
  member_ids: ['u2'],
  hourly_rate: '95.00',
  stages: [
    { key: 'built', name: 'Built', colour: '#1361c9', order: 1, closes: false },
    { key: 'ready_to_test', name: 'Ready to test', colour: '#6136ad', order: 2, closes: false },
    { key: 'ready_for_fat', name: 'Ready for FAT', colour: '#14713d', order: 3, closes: true },
  ],
  request_types: [
    {
      key: 'switchboard',
      label: 'Switchboard',
      disciplines: ['build', 'test'],
      position: 0,
      active: true,
      fields: [
        { key: 'form', label: 'Form', type: 'select', options: ['3b', '4a'], required: true },
        { key: 'amps', label: 'Amps', type: 'number' },
      ],
    },
    {
      // Shares `amps` with Switchboard on purpose: the union must ask it
      // ONCE, and must keep the discipline each type brings of its own.
      key: 'control_panel',
      label: 'Control panel',
      disciplines: ['build', 'wire'],
      position: 1,
      active: true,
      fields: [
        { key: 'amps', label: 'Amps', type: 'number' },
        { key: 'enclosure', label: 'Enclosure', type: 'text' },
      ],
    },
    {
      key: 'legacy_fab',
      label: 'Fabrication (retired)',
      disciplines: ['build'],
      position: 2,
      active: false,
      fields: [],
    },
  ],
};

const DRAFTING: Department = {
  key: 'drafting',
  name: 'Drafting',
  prefix: 'DRF',
  position: 1,
  colour: '#2f42a8',
  description: 'Drawings and as-builts',
  active: true,
  lead_user_id: null,
  member_ids: [],
  hourly_rate: null,
  stages: [
    { key: 'ready_to_draft', name: 'Ready to draft', colour: '#1361c9', order: 1, closes: false },
    { key: 'ifc', name: 'IFC', colour: '#14713d', order: 2, closes: true },
  ],
  request_types: [{ key: 'ga', label: 'General arrangement', disciplines: ['drafting'], fields: [] }],
};

const base = (over: Partial<WorkRequest>): WorkRequest => ({
  id: 'r1',
  reference: 'WR-WKS-000012',
  project_id: 'p1',
  project_code: 'PJ-001',
  project_name: 'Placeholder Works - Plant upgrade',
  client_name: 'Placeholder Works',
  department: 'workshop',
  department_name: 'Workshop',
  request_type: 'switchboard',
  title: 'MSB-1 switchboard build',
  description: 'Form 3b, 2500A',
  status: 'submitted',
  allowed_transitions: ['accepted', 'cancelled'],
  stage: 'built',
  stage_name: 'Built',
  stage_closes: false,
  stage_history: [{ stage: 'built', at: '2026-09-01T00:00:00Z', by_id: 'u2', by_name: 'Robin Placeholder', note: null }],
  raised_by_id: 'u1',
  raised_by_name: 'Pat Placeholder',
  assignees: [{ id: 'u2', name: 'Robin Placeholder' }],
  responsible: { id: 'u2', name: 'Robin Placeholder' },
  cost_centres: { build: 'PJ-001-SB' },
  estimated_hours: { build: 40, test: 8 },
  quoted_hours: 48,
  hours_logged: 12,
  hours_to_complete: 30,
  hours_at_completion: 42,
  deviation_hours: -6,
  cost_at_completion: '3990.00',
  info_required_by: null,
  due_date: '2026-09-20',
  days_until_due: 17,
  is_overdue: false,
  scheduled_start: null,
  scheduled_end: null,
  delivered_at: null,
  tested_at: null,
  priority: 'high',
  links: [],
  fields: { form: '3b', amps: 2500 },
  planner_uploaded: false,
  ball_in_court: 'department',
  needs_info: null,
  depends_on: [],
  blocks: [],
  parent_id: null,
  parent_reference: null,
  children: [],
  comment_count: 0,
  attachments: [],
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
  closed_at: null,
  ...over,
});

const R1 = base({});
const R2 = base({ id: 'r2', reference: 'WR-DRF-000003', department: 'drafting', department_name: 'Drafting', request_type: 'ga', title: 'GA drawing for MSB-1', stage: 'ready_to_draft', stage_name: 'Ready to draft', assignees: [], responsible: null, quoted_hours: 6, hours_logged: 0, deviation_hours: null });

const SUMMARY: Summary = {
  departments: [
    { key: 'workshop', name: 'Workshop', colour: '#a4470c', open: 1, overdue: 0, with_requester: 0, due_this_week: 0, hours_quoted: 48, hours_logged: 12, awaiting_close: 0 },
    { key: 'drafting', name: 'Drafting', colour: '#2f42a8', open: 1, overdue: 0, with_requester: 0, due_this_week: 0, hours_quoted: 6, hours_logged: 0, awaiting_close: 0 },
  ],
};

const MONDAY = mondayOf(isoDay(new Date()));
const PLANNER: Planner = {
  days: daysBetween(MONDAY, addDays(MONDAY, 32)),
  members: [{ id: 'u2', name: 'Robin Placeholder' }],
  rows: [{ request_id: 'r1', reference: 'WR-WKS-000012', title: 'MSB-1 switchboard build', project_code: 'PJ-001', due_date: '2026-09-20', stage: 'built', assignees: [{ id: 'u2', name: 'Robin Placeholder' }], alloc: {} }],
  capacity: { [MONDAY]: { available: 3, allocated: 0 } },
};

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/work-requests']}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function DetailHarness({ id }: { id: string }) {
  const actions = useRequestActions({ departments: [WORKSHOP, DRAFTING], me: { id: 'u1', name: 'Pat Placeholder' }, onOpen: () => undefined });
  return (
    <>
      <RequestDetail id={id} departments={[WORKSHOP, DRAFTING]} me={{ id: 'u1', name: 'Pat Placeholder' }} actions={actions} onOpenOther={() => undefined} />
      {actions.element}
    </>
  );
}

beforeEach(() => {
  for (const fn of Object.values(m)) fn.mockReset();
  localStorage.clear();
  // The page mirrors its state into the URL; jsdom keeps it between tests.
  window.history.replaceState(null, '', '/work-requests');
  useProjectContextStore.getState().clearProject();
  m.fetchDepartments.mockResolvedValue([WORKSHOP, DRAFTING]);
  m.patchDepartment.mockResolvedValue(WORKSHOP);
  m.reorderRequestTypes.mockResolvedValue(WORKSHOP.request_types);
  m.patchRequestType.mockResolvedValue(WORKSHOP.request_types[0]);
  m.createRequestType.mockResolvedValue(WORKSHOP.request_types[0]);
  m.deleteRequestType.mockResolvedValue(undefined);
  // The mock honours the department filter the way the server would.
  m.fetchRequests.mockImplementation(async (f: { department?: string } = {}) => [R1, R2].filter((r) => !f.department || r.department === f.department));
  m.fetchRequest.mockResolvedValue(R1);
  m.fetchSummary.mockResolvedValue(SUMMARY);
  m.fetchMyQueue.mockResolvedValue({ assigned: [], responsible: [], raised: [R1], needs_my_answer: [] });
  m.fetchUsers.mockResolvedValue([
    { id: 'u1', email: 'pat@example.test', full_name: 'Pat Placeholder' },
    { id: 'u2', email: 'robin@example.test', full_name: 'Robin Placeholder' },
  ]);
  m.fetchProjects.mockResolvedValue([{ id: 'p1', name: 'Placeholder Works - Plant upgrade', project_code: 'PJ-001', client_id: 'c1' }]);
  m.fetchMe.mockResolvedValue({ id: 'u1', email: 'pat@example.test', full_name: 'Pat Placeholder' });
  m.fetchHours.mockResolvedValue([]);
  m.fetchComments.mockResolvedValue([]);
  m.fetchActivity.mockResolvedValue([]);
  m.fetchPlanner.mockResolvedValue(PLANNER);
  m.putPlannerAlloc.mockResolvedValue(PLANNER.rows[0]);
  m.patchRequest.mockImplementation(async (_id: string, patch: Partial<WorkRequest>) => ({ ...R1, ...patch }));
});

describe('WorkRequestsPage', () => {
  it('renders one tab per active department, All first, with open counts', async () => {
    wrap(<WorkRequestsPage />);
    const tabs = await screen.findAllByRole('tab');
    expect(tabs.map((t) => t.textContent?.replace(/\d+$/, '').trim())).toEqual(['All', 'Workshop', 'Drafting']);
    // Counts come from /summary: 1 + 1 open.
    await waitFor(() => expect(within(tabs[0] as HTMLElement).getByText('2')).toBeTruthy());
    expect(within(tabs[1] as HTMLElement).getByText('1')).toBeTruthy();
  });

  it('builds the board columns from the department stages', async () => {
    wrap(<WorkRequestsPage />);
    fireEvent.click(await screen.findByRole('tab', { name: /Workshop/ }));
    await waitFor(() => expect(m.fetchRequests).toHaveBeenLastCalledWith(expect.objectContaining({ department: 'workshop' })));
    const built = await screen.findByTestId('wr-col-built');
    expect(screen.getByTestId('wr-col-ready_to_test')).toBeTruthy();
    const fat = screen.getByTestId('wr-col-ready_for_fat');
    expect(within(fat).getByText('closes')).toBeTruthy();
    // The card sits in its stage column with reference, job and client.
    expect(within(built).getByText('WR-WKS-000012')).toBeTruthy();
    expect(within(built).getByText('PJ-001')).toBeTruthy();
    expect(within(built).getByText(/Placeholder Works/)).toBeTruthy();
  });

  it('raise dialog renders the request type fields and posts the right body', async () => {
    useProjectContextStore.getState().setActiveProject('p1', 'Placeholder Works - Plant upgrade');
    m.createRequest.mockResolvedValue(base({ id: 'r9', reference: 'WR-WKS-000013', title: 'DB-2 build' }));
    wrap(<WorkRequestsPage />);
    await screen.findAllByRole('tab'); // departments loaded → Raise is enabled
    fireEvent.click(screen.getByTestId('wr-raise-btn'));
    const dialog = await screen.findByTestId('wr-raise');
    fireEvent.click(within(dialog).getByRole('button', { name: /Workshop/ }));
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Switchboard' }));
    // The type's own fields and its disciplines appear.
    const form = (await within(dialog).findByLabelText(/^Form/)) as HTMLSelectElement;
    const amps = within(dialog).getByLabelText(/^Amps/) as HTMLInputElement;
    expect(within(dialog).getByLabelText('build hours')).toBeTruthy();
    expect(within(dialog).getByLabelText('test cost centre')).toBeTruthy();
    // The job defaulted to the active project.
    await waitFor(() => expect(within(dialog).getByTestId('wr-raise-job').textContent).toContain('PJ-001'));

    fireEvent.change(within(dialog).getByLabelText(/^Title/), { target: { value: 'DB-2 build' } });
    fireEvent.change(form, { target: { value: '3b' } });
    fireEvent.change(amps, { target: { value: '2500' } });
    fireEvent.change(within(dialog).getByLabelText('build hours'), { target: { value: '40' } });
    fireEvent.change(within(dialog).getByLabelText('build cost centre'), { target: { value: 'PJ-001-SB' } });
    fireEvent.change(within(dialog).getByLabelText(/Quoted hours/), { target: { value: '48' } });
    fireEvent.change(within(dialog).getByLabelText(/^Due/), { target: { value: '2026-10-01' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Urgent' }));
    fireEvent.click(within(dialog).getByTestId('wr-raise-submit'));

    await waitFor(() => expect(m.createRequest).toHaveBeenCalledTimes(1));
    expect(m.createRequest.mock.calls[0]?.[0]).toMatchObject({
      project_id: 'p1',
      department: 'workshop',
      // Both spellings: the array is the contract, the scalar is what a
      // backend that predates it still reads.
      request_type: 'switchboard',
      request_types: ['switchboard'],
      title: 'DB-2 build',
      fields: { form: '3b', amps: 2500 },
      estimated_hours: { build: 40 },
      cost_centres: { build: 'PJ-001-SB' },
      quoted_hours: 48,
      due_date: '2026-10-01',
      priority: 'urgent',
      draft: false,
    });
  });

  it('raises ONE request that is several types, asking the union of their fields once', async () => {
    useProjectContextStore.getState().setActiveProject('p1', 'Placeholder Works - Plant upgrade');
    m.createRequest.mockResolvedValue(base({ id: 'r9', reference: 'WR-WKS-000014', title: 'MCC-4 build' }));
    wrap(<WorkRequestsPage />);
    await screen.findAllByRole('tab');
    fireEvent.click(screen.getByTestId('wr-raise-btn'));
    const dialog = await screen.findByTestId('wr-raise');
    fireEvent.click(within(dialog).getByRole('button', { name: /Workshop/ }));

    // A retired type is not offered at all - it only survives on the
    // requests that already carry it.
    expect(within(dialog).queryByTestId('wr-type-legacy_fab')).toBeNull();

    fireEvent.click(await within(dialog).findByTestId('wr-type-switchboard'));
    fireEvent.click(within(dialog).getByTestId('wr-type-control_panel'));

    // `amps` is on both types and is asked ONCE; each type's own field is
    // asked as well, and the disciplines are the union of the two.
    expect(within(dialog).getAllByLabelText(/^Amps/)).toHaveLength(1);
    expect(within(dialog).getByLabelText(/^Form/)).toBeTruthy();
    expect(within(dialog).getByLabelText(/^Enclosure/)).toBeTruthy();
    expect(within(dialog).getByLabelText('build hours')).toBeTruthy();
    expect(within(dialog).getByLabelText('test hours')).toBeTruthy();
    expect(within(dialog).getByLabelText('wire hours')).toBeTruthy();

    fireEvent.change(within(dialog).getByLabelText(/^Title/), { target: { value: 'MCC-4 build' } });
    fireEvent.change(within(dialog).getByLabelText(/^Form/), { target: { value: '4a' } });
    fireEvent.change(within(dialog).getByLabelText(/^Enclosure/), { target: { value: 'IP54 floor standing' } });
    fireEvent.click(within(dialog).getByTestId('wr-raise-submit'));

    await waitFor(() => expect(m.createRequest).toHaveBeenCalledTimes(1));
    const body = m.createRequest.mock.calls[0]?.[0] as { request_types: string[]; request_type: string; fields: Record<string, unknown> };
    // The order the chips were pressed in is the order that is sent.
    expect(body.request_types).toEqual(['switchboard', 'control_panel']);
    expect(body.request_type).toBe('switchboard');
    expect(body.fields).toMatchObject({ form: '4a', enclosure: 'IP54 floor standing' });
  });

  it('deselecting a type drops the questions it brought, and its answers', async () => {
    useProjectContextStore.getState().setActiveProject('p1', 'Placeholder Works - Plant upgrade');
    m.createRequest.mockResolvedValue(base({ id: 'r9', reference: 'WR-WKS-000015' }));
    wrap(<WorkRequestsPage />);
    await screen.findAllByRole('tab');
    fireEvent.click(screen.getByTestId('wr-raise-btn'));
    const dialog = await screen.findByTestId('wr-raise');
    fireEvent.click(within(dialog).getByRole('button', { name: /Workshop/ }));
    fireEvent.click(await within(dialog).findByTestId('wr-type-switchboard'));
    fireEvent.click(within(dialog).getByTestId('wr-type-control_panel'));
    fireEvent.change(within(dialog).getByLabelText(/^Enclosure/), { target: { value: 'IP54' } });
    fireEvent.change(within(dialog).getByLabelText('wire hours'), { target: { value: '6' } });
    fireEvent.change(within(dialog).getByLabelText(/^Title/), { target: { value: 'MSB only' } });
    fireEvent.change(within(dialog).getByLabelText(/^Form/), { target: { value: '3b' } });

    // Take Control panel back off: its field and its discipline go with it.
    fireEvent.click(within(dialog).getByTestId('wr-type-control_panel'));
    expect(within(dialog).queryByLabelText(/^Enclosure/)).toBeNull();
    expect(within(dialog).queryByLabelText('wire hours')).toBeNull();

    fireEvent.click(within(dialog).getByTestId('wr-raise-submit'));
    await waitFor(() => expect(m.createRequest).toHaveBeenCalledTimes(1));
    const body = m.createRequest.mock.calls[0]?.[0] as { request_types: string[]; fields: Record<string, unknown>; estimated_hours: Record<string, number> };
    expect(body.request_types).toEqual(['switchboard']);
    // The typed values do NOT ride along under a type that was removed.
    expect(body.fields).not.toHaveProperty('enclosure');
    expect(body.estimated_hours).not.toHaveProperty('wire');
  });

  it('refuses to raise without a request type and says so inline', async () => {
    wrap(<WorkRequestsPage />);
    await screen.findAllByRole('tab');
    fireEvent.click(screen.getByTestId('wr-raise-btn'));
    const dialog = await screen.findByTestId('wr-raise');
    fireEvent.click(within(dialog).getByRole('button', { name: /Workshop/ }));
    fireEvent.click(within(dialog).getByTestId('wr-raise-submit'));
    expect(await within(dialog).findByText('Pick at least one request type.')).toBeTruthy();
    expect(m.createRequest).not.toHaveBeenCalled();
  });

  it('filters by request type as ANY-OF, on the wire and on the rows', async () => {
    const scada = base({ id: 'r3', reference: 'WR-AUT-000004', title: 'SCADA screens', request_type: 'scada', request_types: ['scada', 'plc'] });
    m.fetchRequests.mockImplementation(async () => [R1, R2, scada]);
    wrap(<WorkRequestsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'List' }));
    await screen.findByTestId('wr-row-r1');

    fireEvent.change(screen.getByTestId('wr-filter-type'), { target: { value: 'control_panel' } });
    await waitFor(() =>
      expect(m.fetchRequests).toHaveBeenLastCalledWith(expect.objectContaining({ request_types: ['control_panel'] })),
    );
    // The mock ignores the parameter, the way a backend without it would;
    // the rows on screen must still honour the filter.
    await waitFor(() => expect(screen.queryByTestId('wr-row-r1')).toBeNull());
    expect(screen.queryByTestId('wr-row-r3')).toBeNull();
  });

  it('the tab badge, the board and the "N requests" line agree on the same set', async () => {
    // Engineering-style shape: nothing open, one finished waiting to be
    // closed off. The badge used to read 0 beside a board showing a card.
    m.fetchSummary.mockResolvedValue({
      departments: [
        { key: 'workshop', name: 'Workshop', colour: 'orange', open: 0, overdue: 0, with_requester: 0, due_this_week: 0, hours_quoted: 48, hours_logged: 12, awaiting_close: 1 },
        { key: 'drafting', name: 'Drafting', colour: 'indigo', open: 1, overdue: 0, with_requester: 0, due_this_week: 0, hours_quoted: 6, hours_logged: 0, awaiting_close: 0 },
      ],
    } satisfies Summary);
    wrap(<WorkRequestsPage />);
    const tabs = await screen.findAllByRole('tab');
    await waitFor(() => expect(within(tabs[1] as HTMLElement).getByText('1')).toBeTruthy());
    // All = 0 + 1 open, plus the one awaiting close.
    expect(within(tabs[0] as HTMLElement).getByText('2')).toBeTruthy();
  });

  it('refuses to raise without a title and says so inline', async () => {
    wrap(<WorkRequestsPage />);
    await screen.findAllByRole('tab'); // departments loaded → Raise is enabled
    fireEvent.click(screen.getByTestId('wr-raise-btn'));
    const dialog = await screen.findByTestId('wr-raise');
    fireEvent.click(within(dialog).getByTestId('wr-raise-submit'));
    expect(await within(dialog).findByText('Give it a title.')).toBeTruthy();
    expect(within(dialog).getByText('Pick a department.')).toBeTruthy();
    expect(m.createRequest).not.toHaveBeenCalled();
  });

  it('shows a 409 from a stage move inline with the allowed transitions', async () => {
    m.moveStage.mockRejectedValue(new ApiError(409, 'Conflict', { detail: { error: 'Cannot go from submitted to ready_to_test', allowed: ['built', 'cancelled'] } }));
    wrap(<WorkRequestsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'List' }));
    const row = await screen.findByTestId('wr-row-r1');
    fireEvent.contextMenu(row);
    const menu = await screen.findByRole('menu');
    fireEvent.click(within(menu).getByRole('menuitem', { name: /Ready to test/ }));
    await waitFor(() => expect(m.moveStage).toHaveBeenCalledWith('r1', 'ready_to_test'));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Cannot go from submitted to ready_to_test');
    expect(alert.textContent).toContain('allowed: built, cancelled');
  });

  it('is honest when the server has no Work Requests module (404)', async () => {
    m.fetchDepartments.mockRejectedValue(new ApiError(404, 'Not Found', { detail: 'Not Found' }));
    wrap(<WorkRequestsPage />);
    expect(await screen.findByText(/does not have the Work Requests module yet/)).toBeTruthy();
    expect(screen.queryByRole('tab')).toBeNull();
    expect((screen.getByTestId('wr-raise-btn') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('RequestDetail', () => {
  it('shows the needs-info banner and posts the answer', async () => {
    m.fetchRequest.mockResolvedValue(base({ needs_info: 'Which form - 3b or 4a?', ball_in_court: 'requester' }));
    m.answerInfo.mockResolvedValue(base({}));
    wrap(<DetailHarness id="r1" />);
    const banner = await screen.findByTestId('wr-needs-info');
    expect(banner.textContent).toContain('Which form - 3b or 4a?');
    // The requester (me) is who it is addressed to.
    expect(banner.textContent).toContain('needs information from you');
    fireEvent.change(within(banner).getByLabelText('Answer'), { target: { value: 'Form 3b' } });
    fireEvent.click(within(banner).getByRole('button', { name: 'Answer' }));
    await waitFor(() => expect(m.answerInfo).toHaveBeenCalledWith('r1', 'Form 3b'));
  });

  it('renders the stage stepper and the hours arithmetic', async () => {
    wrap(<DetailHarness id="r1" />);
    const steps = await screen.findByRole('group', { name: 'Stages' });
    const buttons = within(steps).getAllByRole('button');
    expect(buttons.map((b) => b.textContent)).toEqual(['1Built', '2Ready to test', '3 · closesReady for FAT']);
    expect(buttons[0]?.getAttribute('aria-current')).toBe('step');
    // Deviation −6h under the quote, cost at completion from the server.
    expect(screen.getByText('−6h')).toBeTruthy();
    expect(screen.getByText(/under the quote/)).toBeTruthy();
    expect(screen.getByText('3,990')).toBeTruthy();
  });
});

describe('PlannerView', () => {
  it('a cell edit PUTs the row allocation keyed by the day', async () => {
    wrap(<PlannerView dept={WORKSHOP} requests={[R1]} onOpen={() => undefined} />);
    await waitFor(() => expect(m.fetchPlanner).toHaveBeenCalledWith('workshop', MONDAY, addDays(MONDAY, 32)));
    const cell = (await screen.findAllByLabelText(MONDAY))[0] as HTMLInputElement; // the request row, before the capacity row
    fireEvent.change(cell, { target: { value: '2' } });
    fireEvent.keyDown(cell, { key: 'Enter' });
    await waitFor(() => expect(m.putPlannerAlloc).toHaveBeenCalledWith('r1', { [MONDAY]: 2 }));
    // 2 heads × 8h = 16h against the 48h quote.
    expect(screen.getByText('16h')).toBeTruthy();
  });

  it('folds weekends and shows five weeks', async () => {
    wrap(<PlannerView dept={WORKSHOP} requests={[R1]} onOpen={() => undefined} />);
    const heads = await screen.findAllByText(/Week of/);
    expect(heads.length).toBe(5);
    const sat = PLANNER.days.find((d) => new Date(d + 'T00:00').getDay() === 6) as string;
    expect(screen.queryAllByLabelText(sat)).toHaveLength(0);
  });
});

/* ── The drift the backend documented, held down by tests ─────────── */

describe('money and the status machine', () => {
  it('reads a Decimal-as-TEXT money field rather than assuming a number', () => {
    // The API sends "5220.00"; `toLocaleString` on a STRING silently
    // ignores its options, so the old code printed the raw "5220.00".
    expect(fmtMoney('5220.00')).toBe(fmtMoney(5220));
    expect(fmtMoney('5220.00')).not.toContain('.00');
    expect(fmtMoney(null)).toBe('—');
    expect(fmtMoney('not money')).toBe('—');
    expect(moneyNumber('125.00')).toBe(125);
    expect(moneyNumber(null)).toBeNull();
  });

  it('routes a board drop through the hops the server insists on', () => {
    // submitted → in_progress is not an edge: it has to be accepted first.
    expect(statusPath('submitted', 'in_progress', ['accepted', 'cancelled'])).toEqual(['accepted', 'in_progress']);
    expect(statusPath('in_progress', 'complete', ['on_hold', 'review', 'complete', 'cancelled'])).toEqual(['complete']);
    expect(statusPath('submitted', 'submitted')).toEqual([]);
    // Terminal: no route, so the server gets to refuse it in its own words.
    expect(statusPath('closed', 'in_progress', [])).toBeNull();
  });
});

describe('deep links from the widgets outside this module', () => {
  it('accepts ?department= (the dashboard card) as well as ?dept=', async () => {
    window.history.replaceState(null, '', '/work-requests?department=workshop');
    wrap(<WorkRequestsPage />);
    const tab = await screen.findByRole('tab', { name: /Workshop/ });
    await waitFor(() => expect(tab.getAttribute('aria-selected')).toBe('true'));
    // …and the alias is consumed, so a reload does not fight the tabs.
    await waitFor(() => expect(window.location.search).toBe('?dept=workshop'));
  });

  it('opens the raise dialog on the linked job for ?raise=1&project=', async () => {
    window.history.replaceState(null, '', '/work-requests?raise=1&project=p1');
    wrap(<WorkRequestsPage />);
    const dialog = await screen.findByTestId('wr-raise');
    await waitFor(() => expect(within(dialog).getByTestId('wr-raise-job').textContent).toContain('PJ-001'));
    await waitFor(() => expect(window.location.search).toBe(''));
  });
});

/* ── The colour tokens the backend actually sends ─────────────────── */

describe('department colour tokens', () => {
  it('resolves the tokens that are not CSS colours at all', () => {
    // `rose`, `slate` and `amber` are backend tokens, NOT CSS keywords -
    // painted raw they produced no colour, which is how the Hazardous Area
    // chips ended up transparent on the live seed.
    expect(resolveColour('rose')).toMatch(/^#/);
    expect(resolveColour('slate')).toMatch(/^#/);
    expect(resolveColour('amber')).toMatch(/^#/);
    // Hazardous Area is becoming red: it must resolve, and to the module's
    // own mid-dark ink rather than #f00, which is what keeps the AA fix in
    // wr.css (mix 66% towards near-black / 56% towards white) working.
    expect(resolveColour('red')).toBe('#a92c23');
    expect(resolveColour('RED')).toBe('#a92c23');
    // A hex somebody picked is left alone; nothing at all is the neutral.
    expect(resolveColour('#123456')).toBe('#123456');
    expect(resolveColour(null)).toBe(NEUTRAL);
    // Every token the backend's own allow-list names has an answer.
    for (const token of ['slate', 'blue', 'teal', 'green', 'amber', 'orange', 'rose', 'violet', 'red', 'grey', 'gray', 'indigo', 'cyan']) {
      expect(resolveColour(token), token).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it('tints through the resolver, so a token never reaches CSS raw', () => {
    expect(tintStyle('rose').background).toContain('#a52f5b');
    expect(tintStyle('rose').background).not.toContain('rose');
  });
});

/* ── Several types on one request ─────────────────────────────────── */

describe('multi-type helpers', () => {
  const req = (over: Partial<WorkRequest>) => base(over);

  it('treats a payload with only the legacy field as a list of one', () => {
    expect(typeKeysOf(req({ request_type: 'scada', request_types: undefined }))).toEqual(['scada']);
    expect(typeKeysOf(req({ request_type: 'scada', request_types: [] }))).toEqual(['scada']);
    expect(typeKeysOf(req({ request_type: 'scada', request_types: ['scada', 'plc'] }))).toEqual(['scada', 'plc']);
  });

  it('unions the fields of several types, first occurrence winning', () => {
    const [sw, cp] = [WORKSHOP.request_types[0]!, WORKSHOP.request_types[1]!];
    expect(unionFields([sw, cp]).map((f) => f.key)).toEqual(['form', 'amps', 'enclosure']);
    // Order follows the types, so reversing them reverses the questions.
    expect(unionFields([cp, sw]).map((f) => f.key)).toEqual(['amps', 'enclosure', 'form']);
    expect(unionDisciplines([sw, cp])).toEqual(['build', 'test', 'wire']);
  });

  it('prefers the server field_specs over anything worked out here', () => {
    const server = [{ key: 'only_this', label: 'Only this', type: 'text' as const }];
    expect(fieldSpecsOf(req({ request_types: ['switchboard'], field_specs: server }), WORKSHOP)).toBe(server);
    expect(fieldSpecsOf(req({ request_types: ['switchboard', 'control_panel'] }), WORKSHOP).map((f) => f.key)).toEqual([
      'form',
      'amps',
      'enclosure',
    ]);
  });

  it('hides retired types from the pickers but keeps them for management', () => {
    expect(typesOf(WORKSHOP).map((x) => x.key)).toEqual(['switchboard', 'control_panel']);
    expect(typesOf(WORKSHOP, true).map((x) => x.key)).toEqual(['switchboard', 'control_panel', 'legacy_fab']);
    // A backend that ships neither `active` nor `position` must not lose
    // its types: absent means active, and the server's order stands.
    expect(typesOf(DRAFTING).map((x) => x.key)).toEqual(['ga']);
  });

  it('matches the type filter as ANY-OF, not all-of', () => {
    const r = req({ request_types: ['scada', 'plc', 'fds'] });
    expect(matchesTypes(r, [])).toBe(true);
    expect(matchesTypes(r, ['plc'])).toBe(true);
    expect(matchesTypes(r, ['fds', 'ga'])).toBe(true);
    expect(matchesTypes(r, ['ga'])).toBe(false);
  });

  it('labels a type the department has since dropped rather than blanking it', () => {
    expect(typeLabelsOf(req({ request_types: ['switchboard', 'gone'] }), WORKSHOP)).toEqual(['Switchboard', 'gone']);
    // The server's own labels win when it sends a full set.
    expect(typeLabelsOf(req({ request_types: ['a', 'b'], request_type_labels: ['A!', 'B!'] }), WORKSHOP)).toEqual(['A!', 'B!']);
  });
});

describe('the planner month boundary', () => {
  it('names the month on the first column and wherever it turns over', () => {
    expect(dayHead('2026-09-28', undefined)).toEqual({ day: '28', month: expect.any(String) });
    expect(dayHead('2026-09-30', '2026-09-29')).toEqual({ day: '30', month: null });
    // "30, 02" used to read as two days in one month.
    expect(dayHead('2026-10-02', '2026-09-30').month).toBeTruthy();
  });
});

describe('ManageDepartmentsPage', () => {
  it('mints the key a label would get, and says so before asking', () => {
    expect(slugKey('Functional design specification')).toBe('functional_design_specification');
    expect(slugKey('  PLC / SCADA!  ')).toBe('plc_scada');
    expect(slugKey('---')).toBe('');
  });

  it('lists a department, its live AND retired types, and adds one', async () => {
    m.createRequestType.mockResolvedValue({ key: 'fds', label: 'FDS', disciplines: [], fields: [] });
    wrap(<ManageDepartmentsPage />);
    // The screen asks for the retired ones - it is the only one that may.
    await waitFor(() => expect(m.fetchDepartments).toHaveBeenCalledWith(true));
    expect(await screen.findByDisplayValue('Switchboard')).toBeTruthy();
    expect(screen.getByDisplayValue('Fabrication (retired)')).toBeTruthy();

    fireEvent.change(screen.getByTestId('wr-newtype'), { target: { value: 'FDS' } });
    expect(screen.getByText('key: fds')).toBeTruthy();
    fireEvent.click(screen.getByTestId('wr-addtype'));
    await waitFor(() =>
      expect(m.createRequestType).toHaveBeenCalledWith('workshop', expect.objectContaining({ key: 'fds', label: 'FDS' })),
    );
  });

  it('refuses a key that is already taken, without asking the server', async () => {
    wrap(<ManageDepartmentsPage />);
    await screen.findByDisplayValue('Switchboard');
    fireEvent.change(screen.getByTestId('wr-newtype'), { target: { value: 'Control panel' } });
    expect(screen.getByText(/already a type here/)).toBeTruthy();
    expect((screen.getByTestId('wr-addtype') as HTMLButtonElement).disabled).toBe(true);
    expect(m.createRequestType).not.toHaveBeenCalled();
  });

  it('reorders by sending the whole order, and never optimistically', async () => {
    m.reorderRequestTypes.mockResolvedValue([]);
    wrap(<ManageDepartmentsPage />);
    await screen.findByDisplayValue('Switchboard');
    fireEvent.click(screen.getByLabelText('Move Control panel up'));
    await waitFor(() =>
      expect(m.reorderRequestTypes).toHaveBeenCalledWith('workshop', ['control_panel', 'switchboard', 'legacy_fab']),
    );
  });

  it('retires a type rather than deleting it, and restores it again', async () => {
    m.patchRequestType.mockResolvedValue({ key: 'switchboard', label: 'Switchboard', disciplines: [], fields: [], active: false });
    wrap(<ManageDepartmentsPage />);
    await screen.findByDisplayValue('Switchboard');
    const rows = screen.getAllByRole('listitem');
    fireEvent.click(within(rows[0] as HTMLElement).getByRole('button', { name: 'Retire' }));
    await waitFor(() => expect(m.patchRequestType).toHaveBeenCalledWith('workshop', 'switchboard', { active: false }));
    // The retired one offers the opposite.
    expect(within(rows[2] as HTMLElement).getByRole('button', { name: 'Restore' })).toBeTruthy();
  });

  it("shows the server's own refusal against the type it is about", async () => {
    m.reorderRequestTypes.mockRejectedValue(
      new ApiError(409, 'Conflict', { detail: '3 requests still use “Switchboard” - retire it instead.' }),
    );
    wrap(<ManageDepartmentsPage />);
    await screen.findByDisplayValue('Switchboard');
    fireEvent.click(screen.getByLabelText('Move Control panel up'));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('retire it instead');
  });

  it('says plainly that the account cannot manage, rather than failing silently', async () => {
    m.patchDepartment.mockRejectedValue(new ApiError(403, 'Forbidden', { detail: 'Forbidden' }));
    wrap(<ManageDepartmentsPage />);
    const name = await screen.findByLabelText(/^Name/);
    fireEvent.change(name, { target: { value: 'Workshop and fabrication' } });
    fireEvent.click(screen.getByTestId('wr-dept-save'));
    expect((await screen.findByRole('alert')).textContent).toContain('cannot manage departments');
  });

  it('saves a type’s fields, dropping the noise a text field cannot carry', async () => {
    m.patchRequestType.mockResolvedValue({ key: 'switchboard', label: 'Switchboard', disciplines: [], fields: [] });
    wrap(<ManageDepartmentsPage />);
    await screen.findByDisplayValue('Switchboard');
    const rows = screen.getAllByRole('listitem');
    fireEvent.click(within(rows[0] as HTMLElement).getByRole('button', { name: 'Fields…' }));
    fireEvent.change(within(rows[0] as HTMLElement).getByLabelText('Field 2 label'), { target: { value: 'Amperage' } });
    fireEvent.click(within(rows[0] as HTMLElement).getByTestId('wr-savefields-switchboard'));
    await waitFor(() => expect(m.patchRequestType).toHaveBeenCalled());
    const sent = m.patchRequestType.mock.calls[0]?.[2] as { fields: Record<string, unknown>[] };
    expect(sent.fields[0]).toEqual({ key: 'form', label: 'Form', type: 'select', options: ['3b', '4a'], required: true });
    // A non-select carries no `options`, and `required: false` is not sent.
    expect(sent.fields[1]).toEqual({ key: 'amps', label: 'Amperage', type: 'number' });
  });
});

describe('BoardView drops', () => {
  it('accepts a submitted request before moving it to In progress', async () => {
    wrap(<WorkRequestsPage />);
    // The All board's columns are statuses; R1 is submitted.
    const card = await screen.findByTestId('wr-card-r1');
    fireEvent.dragStart(card);
    const col = screen.getByTestId('wr-col-in_progress');
    fireEvent.dragOver(col);
    fireEvent.drop(col);
    await waitFor(() => expect(m.patchRequest).toHaveBeenCalledWith('r1', { status: 'accepted' }));
    await waitFor(() => expect(m.patchRequest).toHaveBeenCalledWith('r1', { status: 'in_progress' }));
    // No inline refusal: the gesture succeeded.
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

/* ── The month view ───────────────────────────────────────────────── */

/**
 * Fixture dates are built INSIDE the month the grid opens on, rather
 * than hard-coded: the view starts on today's month, so a literal
 * "2026-09-20" would quietly stop being on the grid the month after this
 * was written and take six tests with it.
 */
const THIS_MONTH = isoDay(new Date()).slice(0, 7);
const onDay = (n: number) => `${THIS_MONTH}-${String(n).padStart(2, '0')}`;

/** A workshop request whose types bring two typed date fields. */
const KEYED = base({
  id: 'rk',
  reference: 'WR-WKS-000044',
  title: 'Panel with factory and test dates',
  due_date: onDay(12),
  info_required_by: onDay(6),
  field_specs: [
    { key: 'form', label: 'Form', type: 'select', options: ['3b', '4a'] },
    { key: 'tested_by', label: 'Tested by (date)', type: 'date' },
    { key: 'drawings_to_factory_by', label: 'Date the factory receives drawings', type: 'date' },
  ],
  fields: { form: '3b', tested_by: onDay(21), drawings_to_factory_by: onDay(14) },
});

/** Open, workshop, and carrying no date of any kind - the tray's tenant. */
const UNDATED = base({
  id: 'ru',
  reference: 'WR-WKS-000045',
  title: 'Nobody has dated this one',
  status: 'accepted',
  due_date: null,
  days_until_due: null,
  info_required_by: null,
  assignees: [],
});

async function openMonth() {
  wrap(<WorkRequestsPage />);
  await screen.findAllByRole('tab');
  fireEvent.click(screen.getByRole('button', { name: 'Month' }));
  return screen.findByTestId('wr-month');
}

describe('MonthView', () => {
  it('puts a request in the cell of its due date, and nowhere else', async () => {
    m.fetchRequests.mockResolvedValue([base({ due_date: onDay(11), days_until_due: 8 })]);
    await openMonth();
    const cell = await screen.findByTestId(`wr-day-${onDay(11)}`);
    expect(within(cell).getByText('WR-WKS-000012')).toBeTruthy();
    // Drawn ONCE - not on every day of the month.
    expect(screen.getAllByTestId('wr-ev-r1-due_date')).toHaveLength(1);
    expect(within(screen.getByTestId(`wr-day-${onDay(12)}`)).queryByText('WR-WKS-000012')).toBeNull();
    // Whole Monday-first weeks, and a month label that names the year.
    expect(screen.getByTestId('wr-month-label').textContent).toMatch(/\d{4}$/);
    expect(screen.getAllByTestId(/^wr-day-/).length % 7).toBe(0);
  });

  it('lists the undated open requests in the tray, with a count', async () => {
    m.fetchRequests.mockResolvedValue([base({ due_date: onDay(11) }), UNDATED]);
    await openMonth();
    const tray = await screen.findByTestId('wr-month-tray');
    expect(within(tray).getByText('WR-WKS-000045')).toBeTruthy();
    // The dated one is on the grid, not in the tray.
    expect(within(tray).queryByText('WR-WKS-000012')).toBeNull();
    expect(within(tray).getByText('1')).toBeTruthy();
    expect(screen.getByTestId('wr-month-count').textContent).toContain('1 with no date');
  });

  it('hides the tray outright when every request carries a date', async () => {
    m.fetchRequests.mockResolvedValue([base({ due_date: onDay(11) })]);
    await openMonth();
    await screen.findByTestId(`wr-day-${onDay(11)}`);
    expect(screen.queryByTestId('wr-month-tray')).toBeNull();
  });

  it('PATCHes the due date when a tray chip is dropped on a day', async () => {
    m.fetchRequests.mockResolvedValue([UNDATED]);
    await openMonth();
    const chip = await screen.findByTestId('wr-mtchip-ru');
    fireEvent.dragStart(chip);
    const day = screen.getByTestId(`wr-day-${onDay(17)}`);
    fireEvent.dragOver(day);
    fireEvent.drop(day);
    await waitFor(() => expect(m.patchRequest).toHaveBeenCalledWith('ru', { due_date: onDay(17) }));
  });

  it('moves a dated chip to the day it is dropped on', async () => {
    m.fetchRequests.mockResolvedValue([base({ due_date: onDay(11) })]);
    await openMonth();
    const chip = await screen.findByTestId('wr-ev-r1-due_date');
    fireEvent.dragStart(chip);
    const day = screen.getByTestId(`wr-day-${onDay(19)}`);
    fireEvent.dragOver(day);
    fireEvent.drop(day);
    await waitFor(() => expect(m.patchRequest).toHaveBeenCalledWith('r1', { due_date: onDay(19) }));
  });

  it('shows three chips and a "+N more" once a day carries five', async () => {
    const crowd = Array.from({ length: 5 }, (_, i) =>
      base({ id: `c${i}`, reference: `WR-WKS-00010${i}`, title: `Crowded ${i}`, due_date: onDay(13) }),
    );
    m.fetchRequests.mockResolvedValue(crowd);
    await openMonth();
    const cell = await screen.findByTestId(`wr-day-${onDay(13)}`);
    expect(within(cell).getAllByTestId(/^wr-ev-/)).toHaveLength(3);
    // Five items, three drawn: the pill takes the fourth slot.
    expect(within(cell).getByTestId(`wr-evmore-${onDay(13)}`).textContent).toBe('+2 more');
  });

  it('keeps four chips as four - the pill only appears past the cap', async () => {
    const four = Array.from({ length: 4 }, (_, i) =>
      base({ id: `f${i}`, reference: `WR-WKS-00020${i}`, title: `Four ${i}`, due_date: onDay(13) }),
    );
    m.fetchRequests.mockResolvedValue(four);
    await openMonth();
    const cell = await screen.findByTestId(`wr-day-${onDay(13)}`);
    expect(within(cell).getAllByTestId(/^wr-ev-/)).toHaveLength(4);
    expect(within(cell).queryByTestId(`wr-evmore-${onDay(13)}`)).toBeNull();
  });

  it('switches which date is plotted, and says the other two are read-only', async () => {
    m.fetchRequests.mockResolvedValue([KEYED]);
    await openMonth();
    const modes = screen.getByTestId('wr-month-modes');
    const dayOfChip = (el: HTMLElement) => el.closest('[data-testid^="wr-day-"]')?.getAttribute('data-testid');

    // Due (the default): one chip, on the due date, draggable.
    const due = await screen.findByTestId('wr-ev-rk-due_date');
    expect(dayOfChip(due)).toBe(`wr-day-${onDay(12)}`);
    expect(due.getAttribute('draggable')).toBe('true');

    // Info required by: the same request, a different day.
    fireEvent.click(within(modes).getByRole('button', { name: 'Info required by' }));
    const info = await screen.findByTestId('wr-ev-rk-info_required_by');
    expect(dayOfChip(info)).toBe(`wr-day-${onDay(6)}`);
    expect(screen.queryByTestId('wr-ev-rk-due_date')).toBeNull();

    // Key dates: ONE request, TWO chips, each naming its own date, and
    // read-only - a typed date belongs to the type, not to the calendar.
    fireEvent.click(within(modes).getByRole('button', { name: 'Key dates' }));
    const tested = await screen.findByTestId('wr-ev-rk-tested_by');
    const drawings = screen.getByTestId('wr-ev-rk-drawings_to_factory_by');
    expect(dayOfChip(tested)).toBe(`wr-day-${onDay(21)}`);
    expect(dayOfChip(drawings)).toBe(`wr-day-${onDay(14)}`);
    expect(within(tested).getByText('Tested by (date)')).toBeTruthy();
    expect(within(drawings).getByText('Date the factory receives drawings')).toBeTruthy();
    expect(tested.getAttribute('draggable')).toBe('false');
    expect(screen.getByText(/read-only here/)).toBeTruthy();
  });

  it('a read-only mode refuses the drop rather than writing the wrong field', async () => {
    m.fetchRequests.mockResolvedValue([KEYED]);
    await openMonth();
    fireEvent.click(within(screen.getByTestId('wr-month-modes')).getByRole('button', { name: 'Key dates' }));
    const chip = await screen.findByTestId('wr-ev-rk-tested_by');
    fireEvent.dragStart(chip);
    fireEvent.drop(screen.getByTestId(`wr-day-${onDay(19)}`));
    await waitFor(() => expect(screen.getByTestId('wr-month-count')).toBeTruthy());
    expect(m.patchRequest).not.toHaveBeenCalled();
  });

  it('applies the department tab and the search to the grid AND the tray', async () => {
    const otherUndated = base({ id: 'ro', reference: 'WR-DRF-000009', department: 'drafting', title: 'Drafting, undated', due_date: null, status: 'accepted' });
    m.fetchRequests.mockImplementation(async (f: { department?: string } = {}) =>
      [base({ due_date: onDay(11) }), UNDATED, otherUndated].filter((r) => !f.department || r.department === f.department),
    );
    await openMonth();
    let tray = await screen.findByTestId('wr-month-tray');
    await waitFor(() => expect(within(tray).getByText('WR-DRF-000009')).toBeTruthy());
    expect(within(tray).getByText('WR-WKS-000045')).toBeTruthy();

    fireEvent.click(screen.getByRole('tab', { name: /Workshop/ }));
    await waitFor(() => expect(m.fetchRequests).toHaveBeenLastCalledWith(expect.objectContaining({ department: 'workshop' })));
    tray = await screen.findByTestId('wr-month-tray');
    await waitFor(() => expect(within(tray).queryByText('WR-DRF-000009')).toBeNull());
    expect(within(tray).getByText('WR-WKS-000045')).toBeTruthy();
    expect(screen.getByTestId(`wr-day-${onDay(11)}`)).toBeTruthy();

    // The search box is applied to the rows rather than on the wire, and
    // must cut the grid as well as the tray.
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'Nobody has dated' } });
    await waitFor(() => expect(screen.queryByTestId('wr-ev-r1-due_date')).toBeNull());
    expect(within(screen.getByTestId('wr-month-tray')).getByText('WR-WKS-000045')).toBeTruthy();
  });

  it('is the fourth view, right after the planner, and is kept in the URL', async () => {
    m.fetchRequests.mockResolvedValue([base({ due_date: onDay(11) })]);
    await openMonth();
    expect(new URLSearchParams(window.location.search).get('view')).toBe('month');
    const seg = screen.getByRole('group', { name: 'View' });
    expect(Array.from(seg.querySelectorAll('button')).map((b) => b.textContent)).toEqual(['Board', 'List', 'Planner', 'Month', 'My queue']);
  });
});

describe('the month grid itself', () => {
  it('starts on a Monday, covers whole weeks, and takes six rows only when it must', () => {
    // September 2026 starts on a Tuesday and has 30 days: 1 + 30 = 31, five rows.
    const sep = monthGrid('2026-09-15');
    expect(sep).toHaveLength(5);
    expect(sep[0]?.[0]).toBe('2026-08-31');
    expect(dayOf(sep[0]?.[0] as string).getDay()).toBe(1);
    expect(sep.every((w) => w.length === 7)).toBe(true);
    expect(sep.flat()).toContain('2026-09-30');

    // August 2026 starts on a Saturday and has 31 days: 5 + 31 = 36, six rows.
    const aug = monthGrid('2026-08-10');
    expect(aug).toHaveLength(6);
    expect(aug.every((w) => w.length === 7)).toBe(true);
    expect(aug.flat()).toContain('2026-08-31');
  });

  it('steps a month at a time without landing in the one after next', () => {
    expect(addMonths('2026-01-31', 1)).toBe('2026-02-28');
    expect(addMonths('2026-03-15', -1)).toBe('2026-02-15');
    expect(firstOfMonth('2026-09-22')).toBe('2026-09-01');
    expect(sameMonth('2026-09-01', '2026-09-30')).toBe(true);
    expect(sameMonth('2026-09-30', '2026-10-01')).toBe(false);
  });

  it('plots one chip per typed date, and none for a date field left empty', () => {
    const keys = plotsFor([KEYED], 'key', [WORKSHOP, DRAFTING]).map((p) => p.key);
    expect(keys).toEqual(['drawings_to_factory_by', 'tested_by']);
    const blank = base({ id: 'rb', field_specs: KEYED.field_specs, fields: { form: '3b' } });
    expect(plotsFor([blank], 'key', [WORKSHOP, DRAFTING])).toHaveLength(0);
    expect(plotsFor([KEYED], 'due', [WORKSHOP]).map((p) => p.day)).toEqual([onDay(12)]);
    expect(plotsFor([UNDATED], 'due', [WORKSHOP])).toHaveLength(0);
    expect(plotsFor([UNDATED], 'info', [WORKSHOP])).toHaveLength(0);
  });
});

/* ── The planner's new gestures ───────────────────────────────────── */

function plannerHarness(rows: Planner['rows'], requests: WorkRequest[]) {
  function Harness() {
    const actions = useRequestActions({ departments: [WORKSHOP, DRAFTING], me: null, onOpen: () => undefined });
    return (
      <>
        <PlannerView dept={WORKSHOP} requests={requests} actions={actions} onOpen={() => undefined} />
        {actions.element}
      </>
    );
  }
  m.fetchPlanner.mockResolvedValue({ ...PLANNER, rows });
  return wrap(<Harness />);
}

describe('PlannerView - tray, menus and the scroll affordance', () => {
  const OPEN_A = base({ id: 'r1', reference: 'WR-WKS-000012', status: 'accepted' });
  const OPEN_B = base({ id: 'r7', reference: 'WR-WKS-000077', title: 'Nothing planned for this one', status: 'accepted' });

  it('lists the department’s unplanned open requests in the Unscheduled tray', async () => {
    // r1 has a day booked in the window; r7 has an empty row.
    plannerHarness(
      [
        { ...PLANNER.rows[0], alloc: { [MONDAY]: 2 } } as Planner['rows'][number],
        { request_id: 'r7', reference: 'WR-WKS-000077', title: 'Nothing planned for this one', project_code: 'PJ-001', due_date: null, stage: 'built', assignees: [], alloc: {} },
      ],
      [OPEN_A, OPEN_B],
    );
    const tray = await screen.findByTestId('wr-plan-tray');
    expect(within(tray).getByText('WR-WKS-000077')).toBeTruthy();
    // The one with a booking is NOT unscheduled.
    expect(within(tray).queryByText('WR-WKS-000012')).toBeNull();
  });

  it('starts an allocation when a tray chip is dropped on a day', async () => {
    plannerHarness(
      [{ request_id: 'r7', reference: 'WR-WKS-000077', title: 'Nothing planned for this one', project_code: 'PJ-001', due_date: null, stage: 'built', assignees: [], alloc: {} }],
      [OPEN_B],
    );
    const chip = await screen.findByTestId('wr-plan-chip-r7');
    fireEvent.dragStart(chip);
    const cell = document.querySelector(`td.cell[data-day="${MONDAY}"]`) as HTMLElement;
    fireEvent.dragOver(cell);
    fireEvent.drop(cell);
    // One head on the day it was dropped on, and nothing else touched.
    await waitFor(() => expect(m.putPlannerAlloc).toHaveBeenCalledWith('r7', { [MONDAY]: 1 }));
  });

  it('offers 0/1/2/3, fill-the-week and clear on a cell, and writes the whole row once', async () => {
    plannerHarness([{ ...PLANNER.rows[0], alloc: {} } as Planner['rows'][number]], [OPEN_A]);
    await screen.findByTestId('wr-plan-row-r1');
    const cell = document.querySelector(`td.cell[data-day="${MONDAY}"]`) as HTMLElement;
    fireEvent.contextMenu(cell, { clientX: 40, clientY: 40 });
    const menu = await screen.findByRole('menu');
    expect(within(menu).getByText('Nobody')).toBeTruthy();
    expect(within(menu).getByText('Fill the rest of the week')).toBeTruthy();
    expect(within(menu).getByText('Clear')).toBeTruthy();
    fireEvent.click(within(menu).getByText('2 on it'));
    await waitFor(() => expect(m.putPlannerAlloc).toHaveBeenCalledWith('r1', { [MONDAY]: 2 }));
  });

  it('clears a whole row from the row menu, in one write', async () => {
    plannerHarness([{ ...PLANNER.rows[0], alloc: { [MONDAY]: 2, [addDays(MONDAY, 1)]: 1 } } as Planner['rows'][number]], [OPEN_A]);
    const rowHead = await screen.findByTestId('wr-plan-row-r1');
    fireEvent.contextMenu(rowHead, { clientX: 40, clientY: 40 });
    const menu = await screen.findByRole('menu');
    // The request's own menu is there too - one menu, not two vocabularies.
    expect(within(menu).getByText('Log hours…')).toBeTruthy();
    fireEvent.click(within(menu).getByText("Clear this row's allocation"));
    await waitFor(() => expect(m.putPlannerAlloc).toHaveBeenCalledWith('r1', {}));
  });

  it('offers the scroll arrows inside the sticky header cells, not over them', async () => {
    plannerHarness([{ ...PLANNER.rows[0], alloc: {} } as Planner['rows'][number]], [OPEN_A]);
    await screen.findByTestId('wr-plan-row-r1');
    // Both live in the two sticky columns; which one SHOWS is a measured
    // decision the CSS makes, but neither may float over the grid.
    const prev = document.querySelector('.wr-gscroll.prev');
    const next = document.querySelector('.wr-gscroll.next');
    expect(prev?.closest('th')?.classList.contains('first')).toBe(true);
    expect(next?.closest('th')?.classList.contains('tot')).toBe(true);
  });
});
