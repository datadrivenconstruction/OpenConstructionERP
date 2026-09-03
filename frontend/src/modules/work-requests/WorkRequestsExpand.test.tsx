// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// The second wave of Work Requests behaviour, against a mocked backend:
// the printable sheet, the checklist and its closing-stage refusal, bulk
// actions reporting BOTH halves of a partial result, the export carrying
// the current filters, duplicate opening the new draft, and the late pill.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Department, Summary, WorkRequest } from './api';
import { checklistProgress, daysLate, dueClause, fmtDay, isLate, nameOfUser, onDepartmentSide, outstandingRequired, shortUrl } from './lib';

const m = vi.hoisted(() => ({
  fetchDepartments: vi.fn(),
  fetchRequests: vi.fn(),
  fetchRequest: vi.fn(),
  fetchSummary: vi.fn(),
  fetchMyQueue: vi.fn(),
  fetchUsers: vi.fn(),
  fetchProjects: vi.fn(),
  fetchMe: vi.fn(),
  fetchHours: vi.fn(),
  fetchComments: vi.fn(),
  fetchActivity: vi.fn(),
  fetchPlanner: vi.fn(),
  moveStage: vi.fn(),
  patchRequest: vi.fn(),
  createRequest: vi.fn(),
  tickChecklist: vi.fn(),
  addChecklistItem: vi.fn(),
  patchChecklistItem: vi.fn(),
  deleteChecklistItem: vi.fn(),
  reorderChecklist: vi.fn(),
  resetChecklist: vi.fn(),
  duplicateRequest: vi.fn(),
  bulkPatch: vi.fn(),
  exportRequests: vi.fn(),
  fetchTemplates: vi.fn(),
  fetchScheduleActivities: vi.fn(),
  fetchBoqPositions: vi.fn(),
}));

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  ...m,
}));

// `exportRequestsUrl` is deliberately NOT mocked: the point of the export
// test is that the real URL builder carries the real filters.
import { exportRequestsUrl } from './api';
import WorkRequestsPage from './WorkRequestsPage';
import { RequestDetail } from './RequestDetail';
import { RequestPrintSheet } from './PrintSheet';
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
  target_days: 10,
  stages: [
    { key: 'built', name: 'Built', colour: '#1361c9', order: 1, closes: false },
    { key: 'ready_for_fat', name: 'Ready for FAT', colour: '#14713d', order: 2, closes: true },
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
  stages: [{ key: 'ready_to_draft', name: 'Ready to draft', colour: '#1361c9', order: 1, closes: false }],
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
  status: 'in_progress',
  allowed_transitions: ['review', 'complete', 'cancelled'],
  stage: 'built',
  stage_name: 'Built',
  stage_closes: false,
  stage_history: [],
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
  links: [{ label: 'GA drawing', url: 'https://example.test/ga.pdf' }],
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

const CHECKLIST: WorkRequest['checklist'] = [
  { key: 'busbars', label: 'Busbars torqued and marked', required: true, done: true, by: 'Robin Placeholder', at: '2026-09-02' },
  { key: 'megger', label: 'Megger test recorded', required: true, done: false, by: null, at: null },
  { key: 'labels', label: 'Labels fitted', required: false, done: false, by: null, at: null },
];

const R1 = base({});
const R2 = base({
  id: 'r2',
  reference: 'WR-DRF-000003',
  department: 'drafting',
  department_name: 'Drafting',
  request_type: 'ga',
  title: 'GA drawing for MSB-1',
  stage: 'ready_to_draft',
  assignees: [],
  responsible: null,
  deviation_hours: null,
});

const SUMMARY: Summary = {
  departments: [
    { key: 'workshop', name: 'Workshop', colour: '#a4470c', open: 1, overdue: 1, with_requester: 0, due_this_week: 0, hours_quoted: 48, hours_logged: 12, awaiting_close: 0, late: 2 },
    { key: 'drafting', name: 'Drafting', colour: '#2f42a8', open: 1, overdue: 0, with_requester: 0, due_this_week: 0, hours_quoted: 6, hours_logged: 0, awaiting_close: 0, late: 0 },
  ],
};

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/work-requests']}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The detail, with the reader's identity swappable - the checklist is
 *  only tickable by the department side, so who is looking is the point. */
function DetailHarness({ id, meId = 'u2' }: { id: string; meId?: string }) {
  const me = { id: meId, name: meId === 'u2' ? 'Robin Placeholder' : 'Pat Placeholder' };
  const actions = useRequestActions({ departments: [WORKSHOP, DRAFTING], me, onOpen: () => undefined });
  return (
    <>
      <RequestDetail id={id} departments={[WORKSHOP, DRAFTING]} me={me} actions={actions} onOpenOther={() => undefined} />
      {actions.element}
    </>
  );
}

beforeEach(() => {
  for (const fn of Object.values(m)) fn.mockReset();
  localStorage.clear();
  window.history.replaceState(null, '', '/work-requests');
  useProjectContextStore.getState().clearProject();
  m.fetchDepartments.mockResolvedValue([WORKSHOP, DRAFTING]);
  m.fetchRequests.mockImplementation(async (f: { department?: string } = {}) => [R1, R2].filter((r) => !f.department || r.department === f.department));
  m.fetchRequest.mockResolvedValue(R1);
  m.fetchSummary.mockResolvedValue(SUMMARY);
  m.fetchMyQueue.mockResolvedValue({ assigned: [], responsible: [], raised: [], needs_my_answer: [] });
  m.fetchUsers.mockResolvedValue([
    { id: 'u1', email: 'pat@example.test', full_name: 'Pat Placeholder' },
    { id: 'u2', email: 'robin@example.test', full_name: 'Robin Placeholder' },
  ]);
  m.fetchProjects.mockResolvedValue([{ id: 'p1', name: 'Placeholder Works - Plant upgrade', project_code: 'PJ-001', client_id: 'c1' }]);
  m.fetchMe.mockResolvedValue({ id: 'u2', email: 'robin@example.test', full_name: 'Robin Placeholder' });
  m.fetchHours.mockResolvedValue([]);
  m.fetchComments.mockResolvedValue([]);
  m.fetchActivity.mockResolvedValue([]);
  m.fetchTemplates.mockResolvedValue([]);
  m.fetchScheduleActivities.mockResolvedValue([]);
  m.fetchBoqPositions.mockResolvedValue([]);
  m.exportRequests.mockResolvedValue(undefined);
  m.patchRequest.mockImplementation(async (_id: string, patch: Partial<WorkRequest>) => ({ ...R1, ...patch }));
});

/* ── The pure rules underneath ───────────────────────────────────── */

describe('lateness and checklist rules', () => {
  it('never invents lateness the server did not report', () => {
    // No flag, no target date: nothing may be claimed, however overdue
    // the requester's own due date is.
    expect(isLate(base({ is_overdue: true, due_date: '2020-01-01' }))).toBe(false);
    expect(daysLate(base({}))).toBeNull();
  });

  it("reads the server's flag, and falls back to a target date it can compare", () => {
    expect(isLate(base({ is_late: true, days_late: 3 }))).toBe(true);
    expect(daysLate(base({ is_late: true, days_late: 3 }))).toBe(3);
    // A target date in the past with no flag is still late…
    expect(isLate(base({ target_date: '2020-01-01' }))).toBe(true);
    // …but a closed request never is: it stopped counting when it closed.
    expect(isLate(base({ target_date: '2020-01-01', status: 'closed' }))).toBe(false);
    // And the server's own `false` beats a stale target date.
    expect(isLate(base({ target_date: '2020-01-01', is_late: false }))).toBe(false);
  });

  it('counts a checklist, and knows which items gate a close', () => {
    const req = base({ checklist: CHECKLIST });
    expect(checklistProgress(req)).toEqual({ done: 1, total: 3 });
    // The server's own counts win when it sends them.
    expect(checklistProgress(base({ checklist: CHECKLIST, checklist_done: 2, checklist_total: 9 }))).toEqual({ done: 2, total: 9 });
    expect(outstandingRequired(req).map((i) => i.key)).toEqual(['megger']);
    // A payload with no checklist at all is "nothing to show", not a throw.
    expect(checklistProgress(base({}))).toEqual({ done: 0, total: 0 });
  });

  it('puts the checklist on the department side of the net', () => {
    const req = base({ checklist: CHECKLIST });
    expect(onDepartmentSide(req, WORKSHOP, { id: 'u2', name: 'Robin Placeholder' })).toBe(true);
    expect(onDepartmentSide(req, WORKSHOP, { id: 'u1', name: 'Pat Placeholder' })).toBe(false);
    // A department that lists nobody has not been set up - everyone is in.
    expect(onDepartmentSide(base({ assignees: [], responsible: null }), DRAFTING, { id: 'u1', name: 'Pat Placeholder' })).toBe(true);
    // Signed out: nobody to record as having ticked it.
    expect(onDepartmentSide(req, WORKSHOP, null)).toBe(false);
  });
});

/* ── 1. The printable sheet ──────────────────────────────────────── */

describe('the printable request sheet', () => {
  it('renders every block the workshop floor needs', () => {
    // `autoPrint` off: the sheet is being READ here, not sent to a printer.
    wrap(<RequestPrintSheet req={base({ checklist: CHECKLIST })} departments={[WORKSHOP]} onDone={() => undefined} autoPrint={false} />);
    const sheet = screen.getByTestId('wr-print-sheet');

    // Header: reference, title, job + client, department, status/stage.
    expect(within(sheet).getByText('WR-WKS-000012')).toBeTruthy();
    expect(within(sheet).getByText('MSB-1 switchboard build')).toBeTruthy();
    expect(sheet.textContent).toContain('PJ-001');
    expect(sheet.textContent).toContain('Placeholder Works');
    expect(sheet.textContent).toContain('Workshop');
    expect(sheet.textContent).toContain('In progress · Built');

    // The typed fields as a two-column table, the scope, the people.
    expect(within(sheet).getByText('Form')).toBeTruthy();
    expect(within(sheet).getByText('Amps')).toBeTruthy();
    expect(sheet.textContent).toContain('Form 3b, 2500A');
    expect(sheet.textContent).toContain('Robin Placeholder');

    // Hours, and the cost - the department carries an hourly rate.
    expect(within(sheet).getByText('Quoted')).toBeTruthy();
    expect(within(sheet).getByText('At completion')).toBeTruthy();
    expect(within(sheet).getByText('Deviation')).toBeTruthy();
    expect(within(sheet).getByText('Cost at completion')).toBeTruthy();

    // The checklist, with a box per item and the required ones starred.
    expect(sheet.textContent).toContain('1 of 3');
    expect(within(sheet).getByText('Megger test recorded')).toBeTruthy();
    expect(sheet.querySelectorAll('.wrp-check .box')).toHaveLength(3);

    // Links, and the signature strip.
    expect(sheet.textContent).toContain('https://example.test/ga.pdf');
    expect(within(sheet).getByText('Completed by')).toBeTruthy();
    expect(within(sheet).getByText('Checked by')).toBeTruthy();
  });

  it('never prints a user id where the reader expects a person', () => {
    const list: WorkRequest['checklist'] = [
      { key: 'busbars', label: 'Busbars torqued and marked', required: true, done: true, by: 'u2', at: '2026-09-02' },
      { key: 'megger', label: 'Megger test recorded', required: true, done: true, by: 'e58c94e2-3258-4725-be3f-499ffc07eb58', at: '2026-09-02' },
    ];
    wrap(
      <RequestPrintSheet
        req={base({ checklist: list })}
        departments={[WORKSHOP]}
        users={[{ id: 'u2', email: 'robin@example.test', full_name: 'Robin Placeholder' }]}
        onDone={() => undefined}
        autoPrint={false}
      />,
    );
    const sheet = screen.getByTestId('wr-print-sheet');
    expect(sheet.textContent).toContain('Robin Placeholder');
    // A uuid on a sheet somebody signs is worse than no name at all.
    expect(sheet.textContent).not.toContain('e58c94e2');
    // The date still stands on its own for the line it cannot name.
    expect(sheet.querySelectorAll('.wrp-check .by')[1]?.textContent).toBe(fmtDay('2026-09-02'));
  });

  it('omits the cost outright when the department has no rate', () => {
    wrap(
      <RequestPrintSheet
        req={base({ department: 'drafting', cost_at_completion: null })}
        departments={[DRAFTING]}
        onDone={() => undefined}
        autoPrint={false}
      />,
    );
    // An invented figure on a printed sheet is one somebody quotes back.
    expect(screen.queryByText('Cost at completion')).toBeNull();
  });

  it('the drawer’s Print action mounts the sheet and asks the browser to print', async () => {
    const print = vi.fn();
    // jsdom has no real print dialog; the component only asks for one.
    Object.defineProperty(window, 'print', { value: print, writable: true, configurable: true });
    wrap(<DetailHarness id="r1" />);
    fireEvent.click(await screen.findByTestId('wr-print-btn'));
    await waitFor(() => expect(print).toHaveBeenCalledTimes(1));
  });
});

/* ── 2. Checklists in the drawer ─────────────────────────────────── */

describe('the checklist', () => {
  it('shows the progress line and posts one tick', async () => {
    m.fetchRequest.mockResolvedValue(base({ checklist: CHECKLIST }));
    m.tickChecklist.mockResolvedValue(base({ checklist: CHECKLIST.map((i) => (i.key === 'megger' ? { ...i, done: true } : i)) }));
    wrap(<DetailHarness id="r1" />);

    expect((await screen.findByTestId('wr-checklist-progress')).textContent).toContain('1 of 3');
    // The required ones say so, and the signed-off one carries its author.
    const list = screen.getByTestId('wr-checklist');
    expect(within(list).getAllByText('required')).toHaveLength(2);
    expect(list.textContent).toContain('Robin Placeholder');

    fireEvent.click(screen.getByTestId('wr-chk-megger'));
    await waitFor(() => expect(m.tickChecklist).toHaveBeenCalledWith('r1', 'megger', true));
  });

  it('is read-only for a reader who is not on the department side', async () => {
    m.fetchRequest.mockResolvedValue(base({ checklist: CHECKLIST }));
    // u1 raised it; the Workshop signs it off.
    wrap(<DetailHarness id="r1" meId="u1" />);
    await screen.findByTestId('wr-checklist');
    expect((screen.getByTestId('wr-chk-megger') as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByTestId('wr-checklist-readonly').textContent).toContain('Only the department doing the work');
    fireEvent.click(screen.getByTestId('wr-chk-megger'));
    expect(m.tickChecklist).not.toHaveBeenCalled();
  });

  it('surfaces a refused closing stage inline, naming the outstanding items', async () => {
    m.fetchRequest.mockResolvedValue(base({ checklist: CHECKLIST }));
    m.moveStage.mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: { error: 'Ready for FAT closes the request; these are still outstanding: Megger test recorded', allowed: [] },
      }),
    );
    wrap(<DetailHarness id="r1" />);
    await screen.findByTestId('wr-checklist');

    // The closing stage asks for a note first (qAsk), then moves.
    fireEvent.click(screen.getByRole('button', { name: /Ready for FAT/ }));
    fireEvent.click(await screen.findByRole('button', { name: 'Move' }));
    await waitFor(() => expect(m.moveStage).toHaveBeenCalled());

    const refusal = await screen.findByTestId('wr-checklist-refusal');
    // The server's own sentence, verbatim…
    expect(refusal.textContent).toContain('still outstanding: Megger test recorded');
    // …and the items this screen knows are outstanding, under it.
    expect(within(refusal).getByRole('listitem').textContent).toBe('Megger test recorded');
  });
});

/* ── 3. Bulk actions on the List ─────────────────────────────────── */

describe('bulk actions', () => {
  it('selects every row on the page and reports a partial result honestly', async () => {
    m.bulkPatch.mockResolvedValue({
      updated: ['r1'],
      refused: [{ id: 'r2', reason: 'Drafting has no stage "ready_for_fat"' }],
    });
    wrap(<WorkRequestsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'List' }));
    await screen.findByTestId('wr-row-r1');

    fireEvent.click(screen.getByTestId('wr-select-all'));
    expect(screen.getByTestId('wr-bulk-count').textContent).toContain('2 selected');

    fireEvent.click(screen.getByTestId('wr-bulk-template'));
    await waitFor(() => expect(m.bulkPatch).toHaveBeenCalledWith(['r1', 'r2'], { is_template: true }));

    const result = await screen.findByTestId('wr-bulk-result');
    // BOTH halves - never a bare success toast over a refusal.
    expect(result.textContent).toContain('1 updated, 1 refused');
    expect(result.textContent).toContain('WR-DRF-000003');
    expect(result.textContent).toContain('Drafting has no stage "ready_for_fat"');
    // What was refused stays ticked so it can be fixed and retried.
    await waitFor(() => expect(screen.getByTestId('wr-bulk-count').textContent).toContain('1 selected'));
  });

  it('sends a due date from the browser’s own picker, and clears the selection with Clear', async () => {
    m.bulkPatch.mockResolvedValue({ updated: ['r1'], refused: [] });
    wrap(<WorkRequestsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'List' }));
    fireEvent.click(await screen.findByTestId('wr-select-r1'));
    expect(screen.getByTestId('wr-bulk-count').textContent).toContain('1 selected');

    fireEvent.click(screen.getByTestId('wr-bulk-due'));
    fireEvent.change(screen.getByTestId('wr-bulk-due-input'), { target: { value: '2026-10-09' } });
    fireEvent.click(screen.getByTestId('wr-bulk-due-apply'));
    await waitFor(() => expect(m.bulkPatch).toHaveBeenCalledWith(['r1'], { due_date: '2026-10-09' }));
    // (The test i18n harness never picks a `_one` default, so the assertion
    // is on the part of the sentence that does not depend on plural rules.)
    expect((await screen.findByTestId('wr-bulk-result')).textContent).toContain('updated - due 2026-10-09');

    // Nothing refused, so nothing stays ticked and the bar goes away.
    await waitFor(() => expect(screen.queryByTestId('wr-bulkbar')).toBeNull());
  });

  it('ticking a row does not open it', async () => {
    wrap(<WorkRequestsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'List' }));
    fireEvent.click(await screen.findByTestId('wr-select-r1'));
    // The drawer would slide over the list after every box.
    expect(screen.queryByTestId('wr-detail')).toBeNull();
  });
});

/* ── 4. Export ───────────────────────────────────────────────────── */

describe('export', () => {
  it('builds an export URL that carries the list’s own filters', () => {
    const url = exportRequestsUrl(
      { project_id: 'p1', department: 'workshop', status: 'in_progress', request_types: ['switchboard', 'ga'], q: 'MSB', include_closed: true, late_only: true },
      'xlsx',
    );
    expect(url).toContain('/requests/export?');
    expect(url).toContain('project_id=p1');
    expect(url).toContain('department=workshop');
    expect(url).toContain('status=in_progress');
    expect(url).toContain('request_types=switchboard%2Cga');
    expect(url).toContain('q=MSB');
    expect(url).toContain('include_closed=true');
    expect(url).toContain('late_only=true');
    expect(url).toContain('format=xlsx');
    // A filter nobody set is never sent as an empty parameter.
    expect(exportRequestsUrl({}, 'csv')).not.toContain('department=');
  });

  it('downloads through the authed fetch, with whatever the toolbar is showing', async () => {
    wrap(<WorkRequestsPage />);
    fireEvent.click(await screen.findByRole('tab', { name: /Workshop/ }));
    fireEvent.click(screen.getByTestId('wr-late-only'));
    await waitFor(() => expect(m.fetchRequests).toHaveBeenLastCalledWith(expect.objectContaining({ department: 'workshop', late_only: true })));

    fireEvent.click(screen.getByTestId('wr-export-btn'));
    fireEvent.click(await screen.findByRole('menuitem', { name: /CSV/ }));
    await waitFor(() => expect(m.exportRequests).toHaveBeenCalledTimes(1));
    expect(m.exportRequests.mock.calls[0]?.[0]).toMatchObject({ department: 'workshop', late_only: true });
    expect(m.exportRequests.mock.calls[0]?.[1]).toBe('csv');
  });
});

/* ── 5. Templates and duplicate ──────────────────────────────────── */

describe('duplicate and templates', () => {
  it('asks for a title, duplicates, and opens the new draft', async () => {
    const copy = base({ id: 'r9', reference: 'WR-WKS-000099', title: 'MSB-2 switchboard build', status: 'draft' });
    m.duplicateRequest.mockResolvedValue(copy);
    const opened = vi.fn();

    function DupHarness() {
      const actions = useRequestActions({ departments: [WORKSHOP, DRAFTING], me: { id: 'u2', name: 'Robin Placeholder' }, onOpen: opened });
      return (
        <>
          <button type="button" onClick={() => void actions.duplicate(R1)}>
            dup
          </button>
          {actions.element}
        </>
      );
    }
    wrap(<DupHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'dup' }));

    // Prefilled with "… (copy)" so Enter is a sensible answer.
    const field = (await screen.findByDisplayValue('MSB-1 switchboard build (copy)')) as HTMLInputElement;
    fireEvent.change(field, { target: { value: 'MSB-2 switchboard build' } });
    fireEvent.click(screen.getByRole('button', { name: 'Duplicate' }));

    await waitFor(() => expect(m.duplicateRequest).toHaveBeenCalledWith('r1', { title: 'MSB-2 switchboard build' }));
    // Straight into the new draft - a duplicate nobody opens is one
    // nobody finishes.
    await waitFor(() => expect(opened).toHaveBeenCalledWith(copy));
  });

  it('offers nothing as a template on a server that ignores the filter', async () => {
    // The unmocked `fetchTemplates` is what filters; here the mock stands
    // in for a backend that answered with the ORDINARY list.
    const { fetchTemplates } = await vi.importActual<typeof import('./api')>('./api');
    const spy = vi.spyOn(globalThis, 'fetch');
    spy.mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [base({}), base({ id: 't1', is_template: true })], total: 2, limit: 500, offset: 0 }), headers: new Headers({ 'content-type': 'application/json' }) } as unknown as Response);
    const out = await fetchTemplates('workshop');
    // Only the one that actually says it is a template.
    expect(out.map((r) => r.id)).toEqual(['t1']);
    spy.mockRestore();
  });

  it('keeps a template off the board even if the server forgets to', async () => {
    m.fetchRequests.mockResolvedValue([R1, base({ id: 't1', reference: 'WR-WKS-000900', title: 'Standard 3b switchboard', is_template: true })]);
    wrap(<WorkRequestsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'List' }));
    await screen.findByTestId('wr-row-r1');
    // A template is a shape to raise FROM, not work anybody owes.
    expect(screen.queryByTestId('wr-row-t1')).toBeNull();
  });

  it('starts a raise from a template, keeping its shape but not its job', async () => {
    const tpl = base({
      id: 't1',
      reference: 'WR-WKS-000900',
      title: 'Standard 3b switchboard',
      description: 'The usual build',
      is_template: true,
      project_id: 'pOther',
      quoted_hours: 32,
      fields: { form: '4a', amps: 1600 },
    });
    m.fetchTemplates.mockResolvedValue([tpl]);
    useProjectContextStore.getState().setActiveProject('p1', 'Placeholder Works - Plant upgrade');
    wrap(<WorkRequestsPage />);
    await screen.findAllByRole('tab');
    fireEvent.click(screen.getByTestId('wr-raise-btn'));
    const dialog = await screen.findByTestId('wr-raise');

    fireEvent.click(within(dialog).getByTestId('wr-template-btn'));
    fireEvent.click(await screen.findByRole('option', { name: /Standard 3b switchboard/ }));

    // The shape: department, type, title, description, typed fields, hours.
    expect((await within(dialog).findByLabelText(/^Title/)).getAttribute('value') ?? (within(dialog).getByLabelText(/^Title/) as HTMLInputElement).value).toBe('Standard 3b switchboard');
    await waitFor(() => expect((within(dialog).getByLabelText(/^Form/) as HTMLSelectElement).value).toBe('4a'));
    expect((within(dialog).getByLabelText(/^Amps/) as HTMLInputElement).value).toBe('1600');
    expect((within(dialog).getByLabelText(/Quoted hours/) as HTMLInputElement).value).toBe('32');
    expect(within(dialog).getByTestId('wr-template-chip').textContent).toContain('Standard 3b switchboard');

    // NOT the job: a shape that drags last quarter's job number with it is
    // how the wrong job gets billed. The active project stands.
    expect(within(dialog).getByTestId('wr-raise-job').textContent).toContain('PJ-001');
  });
});

/* ── 6. Lateness on screen ───────────────────────────────────────── */

describe('the late pill', () => {
  it('shows on the row and the drawer header, and filters the list', async () => {
    const late = base({ is_late: true, days_late: 3, target_date: '2026-08-31' });
    m.fetchRequests.mockResolvedValue([late, R2]);
    m.fetchRequest.mockResolvedValue(late);

    wrap(<WorkRequestsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'List' }));
    const row = await screen.findByTestId('wr-row-r1');
    expect(within(row).getByTestId('wr-late-pill').textContent).toBe('3 days late');
    // The one that is not late wears no pill at all.
    expect(within(screen.getByTestId('wr-row-r2')).queryByTestId('wr-late-pill')).toBeNull();

    // "Late only" cuts the list down even against a server that ignores it.
    fireEvent.click(screen.getByTestId('wr-late-only'));
    // The filter change refetches, so the late one has to come BACK before
    // the absence of the other one means anything.
    await waitFor(() => expect(screen.getByTestId('wr-row-r1')).toBeTruthy());
    expect(screen.queryByTestId('wr-row-r2')).toBeNull();
  });

  it('puts the per-department late count in the tab tooltip', async () => {
    wrap(<WorkRequestsPage />);
    const tab = await screen.findByRole('tab', { name: /Workshop/ });
    await waitFor(() => expect(tab.getAttribute('title')).toContain('2 past the department target'));
    // A department with none says nothing about lateness.
    expect(screen.getByRole('tab', { name: /Drafting/ }).getAttribute('title')).not.toContain('past the department target');
  });
});

/* ── 7. The drawer's own wording and formatting ──────────────────── */

describe('what the drawer says, and how it says it', () => {
  it('turns a checklist tick’s user ID into a person, and shows nothing when it cannot', async () => {
    // The wire sends `by` as a USER ID. The drawer used to print it, so a
    // signed-off line read "e58c94e2-3258-4725-be3f-499ffc07eb58 · Sep 03,
    // 2026" as though that were a colleague.
    const list: WorkRequest['checklist'] = [
      { key: 'busbars', label: 'Busbars torqued and marked', required: true, done: true, by: 'u2', at: '2026-09-02' },
      { key: 'megger', label: 'Megger test recorded', required: true, done: true, by: 'e58c94e2-3258-4725-be3f-499ffc07eb58', at: '2026-09-02' },
    ];
    m.fetchRequest.mockResolvedValue(base({ checklist: list }));
    wrap(<DetailHarness id="r1" />);
    const box = await screen.findByTestId('wr-checklist');

    // Resolved through the users the module already loads for its pickers.
    await waitFor(() => expect(box.textContent).toContain('Robin Placeholder'));
    // An id it cannot place shows the DATE and nothing else - never the id.
    expect(box.textContent).not.toContain('e58c94e2');
    // Both dates go through the app's own formatter, not `toString()`.
    expect(box.textContent).toContain(fmtDay('2026-09-02'));
  });

  it('reads the ball banner as a sentence, and never repeats the distance on the due row', async () => {
    m.fetchRequest.mockResolvedValue(base({ due_date: '2026-09-20', days_until_due: 17, is_overdue: false }));
    // Read as the REQUESTER: the ball is the department's, so the banner
    // has to name them rather than fall back to "with you".
    wrap(<DetailHarness id="r1" meId="u1" />);
    const banner = await screen.findByTestId('wr-ball-banner');

    // "With Workshop. in 57 days" was not a sentence. This is.
    expect(banner.textContent).toContain('With Workshop · due in 17 days');
    expect(banner.textContent).not.toMatch(/With Workshop\.\s*in/);

    // The banner carries the DISTANCE. The Dates section carries the DATE
    // - the same words twice on one screen is how the original read.
    const detail = screen.getByTestId('wr-detail');
    expect(detail.querySelectorAll('[data-testid="wr-ball-due"]')).toHaveLength(1);
    expect(detail.textContent).toContain(fmtDay('2026-09-20'));
  });

  it('says "overdue by" rather than gluing a bare fragment on', async () => {
    m.fetchRequest.mockResolvedValue(base({ due_date: '2026-08-20', days_until_due: -3, is_overdue: true }));
    wrap(<DetailHarness id="r1" />);
    const banner = await screen.findByTestId('wr-ball-banner');
    expect(banner.textContent).toContain('overdue by 3 days');
  });

  it('names every stage in full - no chevron may clip its own label', async () => {
    m.fetchRequest.mockResolvedValue(R1);
    wrap(<DetailHarness id="r1" />);
    await screen.findByTestId('wr-detail');
    // The label is its own element (so a browser check can compare
    // scrollWidth to clientWidth) and it carries the WHOLE name.
    for (const s of WORKSHOP.stages) {
      expect(screen.getByTestId(`wr-step-name-${s.key}`).textContent).toBe(s.name);
    }
  });

  it('shows a link compactly, with the whole url in the title and a safe target', async () => {
    const url = 'http://127.0.0.1:5200/projects/cdf558ff-5ad6-4da0-9016-bfe0233d1bee/files';
    m.fetchRequest.mockResolvedValue(
      base({
        field_specs: [{ key: 'ifc', label: 'IFC drawing link', type: 'url' }],
        fields: { ifc: url },
      }),
    );
    wrap(<DetailHarness id="r1" />);
    const detail = await screen.findByTestId('wr-detail');
    const link = within(detail).getByTitle(url) as HTMLAnchorElement;
    // A raw url printed across the row told the reader nothing…
    expect(link.textContent).not.toContain('cdf558ff-5ad6-4da0');
    expect(link.textContent).toContain('127.0.0.1:5200');
    // …and a new tab opened from it must not keep a handle on this one.
    expect(link.target).toBe('_blank');
    expect(link.rel).toContain('noopener');
    expect(link.rel).toContain('noreferrer');
  });

  it('labels the responsible control with what pressing it does', async () => {
    m.fetchRequest.mockResolvedValue(base({ responsible: null }));
    wrap(<DetailHarness id="r1" />);
    const detail = await screen.findByTestId('wr-detail');
    // "Who is responsible?" read as a question the screen was asking.
    expect(detail.textContent).toContain('Set who is responsible');
    expect(detail.textContent).not.toContain('Who is responsible?');
  });
});

/* ── 8. Editing the checklist itself ─────────────────────────────── */

describe('editing the checklist', () => {
  const EDITABLE: WorkRequest['checklist'] = [
    { key: 'busbars', label: 'Busbars torqued and marked', required: true, done: true, by: 'u2', at: '2026-09-02', source: 'type' },
    { key: 'megger', label: 'Megger test recorded', required: true, done: false, by: null, at: null, source: 'type' },
    { key: 'extra', label: 'Client witness booked', required: false, done: false, by: null, at: null, source: 'request' },
  ];

  const openEditor = async () => {
    wrap(<DetailHarness id="r1" />);
    await screen.findByTestId('wr-checklist');
    fireEvent.click(screen.getByTestId('wr-checklist-edit-toggle'));
    return screen.findByTestId('wr-checklist-add');
  };

  beforeEach(() => {
    m.fetchRequest.mockResolvedValue(base({ checklist: EDITABLE }));
    m.addChecklistItem.mockResolvedValue(base({ checklist: EDITABLE }));
    m.patchChecklistItem.mockResolvedValue(base({ checklist: EDITABLE }));
    m.deleteChecklistItem.mockResolvedValue(base({ checklist: EDITABLE }));
    m.reorderChecklist.mockResolvedValue(base({ checklist: EDITABLE }));
    m.resetChecklist.mockResolvedValue(base({ checklist: EDITABLE }));
  });

  it('adds, renames, re-requires, reorders and removes - each through its own endpoint', async () => {
    await openEditor();

    // Add.
    fireEvent.change(screen.getByLabelText('Add item'), { target: { value: 'Torque report filed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));
    await waitFor(() => expect(m.addChecklistItem).toHaveBeenCalledWith('r1', { label: 'Torque report filed', required: false }));

    // Rename: the draft commits on blur.
    const row = screen.getByTestId('wr-chk-edit-megger');
    const input = within(row).getByLabelText('Checklist item');
    fireEvent.change(input, { target: { value: 'Insulation resistance recorded' } });
    fireEvent.blur(input);
    await waitFor(() => expect(m.patchChecklistItem).toHaveBeenCalledWith('r1', 'megger', { label: 'Insulation resistance recorded' }));

    // Required is its own toggle, not a re-word.
    fireEvent.click(screen.getByTestId('wr-chk-req-extra'));
    await waitFor(() => expect(m.patchChecklistItem).toHaveBeenCalledWith('r1', 'extra', { required: true }));

    // Reorder sends the WHOLE new order, not a delta.
    fireEvent.click(within(screen.getByTestId('wr-chk-edit-extra')).getByLabelText('Move up'));
    await waitFor(() => expect(m.reorderChecklist).toHaveBeenCalledWith('r1', ['busbars', 'extra', 'megger']));

    // Remove.
    fireEvent.click(screen.getByTestId('wr-chk-del-extra'));
    await waitFor(() => expect(m.deleteChecklistItem).toHaveBeenCalledWith('r1', 'extra'));
  });

  it('marks the lines that were added on this request', async () => {
    await openEditor();
    expect(screen.getByTestId('wr-chk-edit-extra').textContent).toContain('added here');
    // An inherited line says nothing - most of them are inherited.
    expect(screen.getByTestId('wr-chk-edit-megger').textContent).not.toContain('added here');
  });

  it('puts the refusal to delete a ticked line on the line itself', async () => {
    m.deleteChecklistItem.mockRejectedValue(
      new ApiError(409, 'Conflict', { detail: 'Busbars torqued and marked has been signed off - untick it first.' }),
    );
    await openEditor();
    fireEvent.click(screen.getByTestId('wr-chk-del-busbars'));
    const err = await screen.findByTestId('wr-chk-err-busbars');
    // The server's own sentence, beside the row it is about.
    expect(err.textContent).toContain('signed off');
    // …and the row is still there.
    expect(screen.getByTestId('wr-chk-edit-busbars')).toBeTruthy();
  });

  it('asks before replacing the list with the type’s standard one', async () => {
    await openEditor();
    fireEvent.click(screen.getByTestId('wr-checklist-reset'));
    // A destructive move behind a confirm - it clears every tick.
    fireEvent.click(await screen.findByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(m.resetChecklist).toHaveBeenCalledWith('r1'));
  });

  it('degrades to read-only against a server that has no editing endpoints', async () => {
    m.addChecklistItem.mockRejectedValue(new ApiError(404, 'Not Found', null));
    await openEditor();
    fireEvent.change(screen.getByLabelText('Add item'), { target: { value: 'Anything' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));

    // Buttons that cannot work are worse than none: the editor closes and
    // says why, and the list is still signable.
    await screen.findByTestId('wr-checklist-noedit');
    expect(screen.queryByTestId('wr-checklist-add')).toBeNull();
    expect(screen.queryByTestId('wr-checklist-edit-toggle')).toBeNull();
    expect(screen.getByTestId('wr-chk-megger')).toBeTruthy();
  });
});

/* ── 9. The pure formatters the wording rests on ─────────────────── */

describe('the wording helpers', () => {
  it('says what the distance is a distance TO', () => {
    expect(dueClause(base({ due_date: null, days_until_due: null }))).toBeNull();
    expect(dueClause(base({ due_date: '2026-09-20', days_until_due: 57 }))?.text).toBe('due in 57 days');
    expect(dueClause(base({ due_date: '2026-09-20', days_until_due: 1 }))?.text).toBe('due in 1 day');
    expect(dueClause(base({ due_date: '2026-09-20', days_until_due: 0 }))?.text).toBe('due today');
    const late = dueClause(base({ due_date: '2026-08-01', days_until_due: -3, is_overdue: true }));
    expect(late?.text).toBe('overdue by 3 days');
    expect(late?.overdue).toBe(true);
    // No day count from the server: the date itself, never a bare number.
    expect(dueClause(base({ due_date: '2026-09-20', days_until_due: null }))?.text).toBe(`due ${fmtDay('2026-09-20')}`);
  });

  it('never hands a reader an id where it promised a person', () => {
    const users = [
      { id: 'u1', email: 'pat@example.test', full_name: 'Pat Placeholder' },
      { id: 'u2', email: 'robin@example.test', full_name: '' },
    ];
    expect(nameOfUser(users, 'u1')).toBe('Pat Placeholder');
    // No name on the record: the email is a person, a uuid is not.
    expect(nameOfUser(users, 'u2')).toBe('robin@example.test');
    expect(nameOfUser(users, 'e58c94e2-3258-4725-be3f-499ffc07eb58')).toBeNull();
    expect(nameOfUser(users, null)).toBeNull();
    // No users loaded yet: an id-shaped value is still never shown.
    expect(nameOfUser(undefined, 'e58c94e2-3258-4725-be3f-499ffc07eb58')).toBeNull();
    // An older payload that already put a NAME in the field is passed through.
    expect(nameOfUser(users, 'Robin Placeholder')).toBe('Robin Placeholder');
  });

  it('shortens a url without hiding it', () => {
    expect(shortUrl('http://127.0.0.1:5200/projects/cdf558ff-5ad6-4da0-9016-bfe0233d1bee/files')).toBe('127.0.0.1:5200/…/files');
    expect(shortUrl('https://example.test/ga.pdf')).toBe('example.test/ga.pdf');
    expect(shortUrl('https://example.test/')).toBe('example.test');
    // Not a url at all: shown as given, trimmed to something a row can hold.
    expect(shortUrl('not a url')).toBe('not a url');
    expect(shortUrl(`x${'y'.repeat(80)}`).length).toBeLessThanOrEqual(44);
  });
});
