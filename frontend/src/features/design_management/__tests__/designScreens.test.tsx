// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The design screens as a reader meets them: an empty list says what it is
// for and what to do first, a list reads in plain words, a form will not send
// a draft that lacks something, and a refused write shows the server's reason.

import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('react-i18next', async () => (await import('./i18nMock')).i18nMockModule);
vi.mock('@/shared/ui/ProjectPeopleSelect', () => ({
  ProjectPeopleSelect: ({ id }: { id?: string }) => <input id={id} readOnly />,
}));
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    createRole: vi.fn(),
    createDeliverable: vi.fn(),
    listApprovalPoints: vi.fn(),
    listUnresolvedWbs: vi.fn(),
    listPermits: vi.fn(),
    listOptions: vi.fn(),
    reopenApprovalPoint: vi.fn(),
    listReleases: vi.fn(),
    listDistributionRules: vi.fn(),
    listReports: vi.fn(),
    movePermit: vi.fn(),
    removePermitItem: vi.fn(),
  };
});

import { ApiError } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import * as api from '../api';
import { ERROR_TEXT } from '../errors';
import { DrawingsPanel } from '../DrawingsPanel';
import { IssuePanel } from '../IssuePanel';
import { PermitsPanel } from '../PermitsPanel';
import { SchedulePanel } from '../SchedulePanel';
import { TeamPanel } from '../TeamPanel';
import { WbsPanel } from '../WbsPanel';
import { context, deliverable, drawing, permit, permitItem, release, role, setup, wbsNode } from './fixtures';

const mocked = vi.mocked(api);

const yes = { allowed: true, applies: true, reason: null };
const absent = { allowed: false, applies: false, reason: null };

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.listApprovalPoints.mockResolvedValue([]);
  mocked.listUnresolvedWbs.mockResolvedValue([]);
  mocked.listPermits.mockResolvedValue([]);
  mocked.listReports.mockResolvedValue([]);
  mocked.listOptions.mockImplementation(async (_project, kind) => ({ kind, available: false, reason: 'source_not_installed', items: [] }));
  mocked.listReleases.mockResolvedValue([]);
  mocked.listDistributionRules.mockResolvedValue([]);
  useToastStore.setState({ toasts: [] });
});
afterEach(cleanup);

describe('TeamPanel', () => {
  it('an empty team says who belongs here and offers the first step', () => {
    wrap(<TeamPanel ctx={context()} />);
    expect(screen.getByText('No design team yet')).toBeInTheDocument();
    expect(screen.getByText(/Add the parties that design this project/)).toBeInTheDocument();
    expect(screen.getAllByText('Add role').length).toBeGreaterThan(0);
  });

  it('lists a role with its party, originator code, person and state', () => {
    const ctx = context({
      roles: [role({ user_id: 'u1' }), role({ id: 'r2', code: 'R-02', title: 'Fire engineer', party_kind: 'specialist', originator_code: 'FIR', state: 'planned' })],
      personName: (id) => (id === 'u1' ? 'Dana Weber' : null),
    });
    wrap(<TeamPanel ctx={ctx} />);
    const rows = screen.getAllByTestId('role-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Architect');
    expect(rows[0]).toHaveTextContent('Lead designer');
    expect(rows[0]).toHaveTextContent('ARC');
    expect(rows[0]).toHaveTextContent('Dana Weber');
    expect(rows[0]).toHaveTextContent('Active');
    // nobody named must be said, not left blank
    expect(rows[1]).toHaveTextContent('Nobody named');
    expect(rows[1]).toHaveTextContent('Specialist');
  });

  it('does not send a role without its required fields', () => {
    wrap(<TeamPanel ctx={context()} />);
    fireEvent.click(screen.getByTestId('role-add'));
    fireEvent.click(screen.getByTestId('form-submit'));
    expect(screen.getByTestId('form-problems')).toHaveTextContent('Fill in:');
    expect(screen.getByTestId('form-problems')).toHaveTextContent('Kind of party');
    expect(mocked.createRole).not.toHaveBeenCalled();
  });

  it('sends only what was filled in and shows why the server refused', async () => {
    mocked.createRole.mockRejectedValue(
      new ApiError(422, 'Unprocessable', {
        detail: {
          code: 'originator_required',
          message: 'A discipline designer needs an originator code.',
          violations: [{ code: 'originator_required', field: 'originator_code', value: null }],
        },
      }),
    );
    const onChanged = vi.fn();
    wrap(<TeamPanel ctx={context({ onChanged })} />);
    fireEvent.click(screen.getByTestId('role-add'));
    fireEvent.change(screen.getByTestId('field-title'), { target: { value: 'Structural engineer' } });
    fireEvent.change(screen.getByTestId('field-party_kind'), { target: { value: 'discipline_designer' } });
    fireEvent.click(screen.getByTestId('form-submit'));
    const refusal = await screen.findByTestId('form-refusal');
    expect(refusal).toHaveTextContent('A discipline designer needs an originator code.');
    expect(refusal).toHaveTextContent('Originator code');
    expect(mocked.createRole).toHaveBeenCalledWith('p1', { title: 'Structural engineer', party_kind: 'discipline_designer' });
    // a refused write changes nothing, so nothing is refetched and the dialog stays
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByTestId('field-title')).toHaveValue('Structural engineer');
  });

  it('closes the dialog and refreshes after the server accepted the role', async () => {
    mocked.createRole.mockResolvedValue(role());
    const onChanged = vi.fn();
    wrap(<TeamPanel ctx={context({ onChanged })} />);
    fireEvent.click(screen.getByTestId('role-add'));
    fireEvent.change(screen.getByTestId('field-title'), { target: { value: 'Architect' } });
    fireEvent.change(screen.getByTestId('field-party_kind'), { target: { value: 'lead_designer' } });
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByTestId('form-submit')).toBeNull());
  });
});

describe('SchedulePanel', () => {
  it('an empty schedule explains the list with an example', async () => {
    wrap(<SchedulePanel ctx={context()} />);
    expect(screen.getByText('No design schedule yet')).toBeInTheDocument();
    expect(screen.getByText(/List what each designer has to deliver in each phase/)).toBeInTheDocument();
    expect(await screen.findByText(/No approval points yet/)).toBeInTheDocument();
  });

  it('shows each line with its phase, designer, drawings against plan and state', () => {
    const ctx = context({
      roles: [role()],
      deliverables: [deliverable(), deliverable({ id: 'd2', code: 'DL-002', title: 'Models', waived: true, waived_rationale: 'Not in scope', state: 'waived', role_id: null })],
      drawings: [drawing()],
    });
    wrap(<SchedulePanel ctx={ctx} />);
    const rows = screen.getAllByTestId('schedule-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Permit drawings');
    expect(rows[0]).toHaveTextContent('Permit design');
    expect(rows[0]).toHaveTextContent('Architect');
    expect(within(rows[0]!).getByTestId('schedule-progress')).toHaveTextContent('1 of 3');
    expect(rows[0]).toHaveTextContent('In progress');
    expect(rows[1]).toHaveTextContent('Waived because: Not in scope');
    expect(within(rows[1]!).getByTestId('schedule-progress')).toHaveTextContent('0 of 3');
  });
});

describe('approval points', () => {
  const point = {
    id: 'ap1',
    code: 'AP-01',
    title: 'Concept sign-off',
    phase_code: 'concept',
    kind: 'owner_approval' as const,
    governance_gate_id: null,
    approver_role_id: null,
    state: 'rejected' as const,
    approval_instance_id: null,
    decided_by: null,
    decided_at: null,
    note: '',
  };

  it('offers reopen and submit as the server says, and reopens with one click', async () => {
    mocked.listApprovalPoints.mockResolvedValue([
      { ...point, can: { reopen: yes, submit: { allowed: false, applies: true, reason: 'no_approval_route' } } },
      { ...point, id: 'ap2', code: 'AP-02', state: 'approved', can: { reopen: absent, submit: absent } },
    ]);
    mocked.reopenApprovalPoint.mockResolvedValue({ ...point, state: 'open' });
    const onChanged = vi.fn();
    wrap(<SchedulePanel ctx={context({ onChanged })} />);
    const rows = await screen.findAllByTestId('point-row');
    expect(rows[0]).toHaveTextContent('Rejected');
    expect(within(rows[0]!).getByTestId('point-submit')).toBeDisabled();
    expect(within(rows[0]!).getByTestId('point-submit-reason')).toHaveTextContent(ERROR_TEXT.no_approval_route!);
    expect(within(rows[1]!).queryByTestId('point-reopen')).toBeNull();
    expect(within(rows[1]!).queryByTestId('point-submit')).toBeNull();
    fireEvent.click(within(rows[0]!).getByTestId('point-reopen'));
    await waitFor(() => expect(mocked.reopenApprovalPoint).toHaveBeenCalledWith('p1', 'ap1'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('on a project without gates the phase is free text and the form says there are no gates', async () => {
    mocked.listOptions.mockImplementation(async (_project, kind) => ({
      kind,
      available: kind === 'governance_gates',
      reason: null,
      items: kind === 'governance_gates' ? [{ id: 'g1', label: 'Left over gate', code: 'g1' }] : [],
    }));
    wrap(<SchedulePanel ctx={context({ setup: setup({ phases: [], gates_in_use: false }) })} />);
    fireEvent.click(await screen.findByTestId('line-add'));
    const phase = await screen.findByTestId('field-phase_code');
    expect(phase.tagName).toBe('INPUT');
    expect(phase).not.toBeRequired();
    expect(screen.getByText('This project does not use gates, so a phase is optional.')).toBeInTheDocument();
    // a line is saved without a phase: nothing is sent for it
    mocked.createDeliverable.mockResolvedValue(deliverable({ phase_code: null }));
    fireEvent.change(screen.getByTestId('field-title'), { target: { value: 'Floor plans' } });
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.createDeliverable).toHaveBeenCalled());
    expect(mocked.createDeliverable.mock.calls[0]![1]).not.toHaveProperty('phase_code');
    await waitFor(() => expect(screen.queryByTestId('field-title')).toBeNull());
    fireEvent.click(screen.getByTestId('point-add'));
    expect(await screen.findByText('This project does not use gates.')).toBeInTheDocument();
    expect((await screen.findByTestId('field-phase_code')).tagName).toBe('INPUT');
    expect(screen.queryByTestId('field-governance_gate_id')).toBeNull();
  });

  it('shows the gate picker only when project governance has gates to offer', async () => {
    mocked.listOptions.mockImplementation(async (_project, kind) =>
      kind === 'governance_gates'
        ? { kind, available: true, reason: null, items: [{ id: 'g1', label: 'Brief to concept', code: 'brief_to_concept' }] }
        : { kind, available: false, reason: 'scheme_has_no_form_list', items: [] },
    );
    wrap(<SchedulePanel ctx={context()} />);
    await waitFor(() => expect(mocked.listOptions).toHaveBeenCalledWith('p1', 'governance_gates'));
    fireEvent.click(screen.getByTestId('point-add'));
    expect(await screen.findByTestId('field-governance_gate_id')).toHaveTextContent('Brief to concept');
    fireEvent.click(screen.getByText('Cancel'));
    fireEvent.click(screen.getByTestId('line-add'));
    // with a phase model the phase is one of its phases and the form insists on it
    expect(screen.getByTestId('field-phase_code').tagName).toBe('SELECT');
    expect(screen.getByTestId('field-phase_code')).toBeRequired();
    // the pinned scheme has no form list, so the schedule line form has no such field
    expect(screen.queryByTestId('field-form_code')).toBeNull();
  });
});

describe('DrawingsPanel', () => {
  it('an empty register says where numbers and files come from', () => {
    wrap(<DrawingsPanel ctx={context()} />);
    expect(screen.getByText('No drawings yet')).toBeInTheDocument();
    expect(screen.getByText(/It gets its number from the scheme of the project/)).toBeInTheDocument();
  });

  it('shows number, revision, status and the warnings of a drawing, and filters by what is typed', () => {
    const ctx = context({
      roles: [role()],
      drawings: [
        drawing(),
        drawing({
          id: 'dr2',
          number: 'A-002',
          title: 'Section A',
          cde_state: 'wip',
          revision_code: 'P02',
          aliases: ['OLD-7'],
          legacy_scheme: true,
          title_block_mismatch: true,
          title_block_number: 'A-020',
        }),
      ],
    });
    wrap(<DrawingsPanel ctx={ctx} />);
    const rows = screen.getAllByTestId('drawing-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('A-001');
    expect(rows[0]).toHaveTextContent('Ground floor plan');
    expect(rows[0]).toHaveTextContent('P01');
    expect(rows[0]).toHaveTextContent('Shared');
    expect(rows[1]).toHaveTextContent('Formerly OLD-7');
    expect(rows[1]).toHaveTextContent('Number of an earlier scheme');
    expect(within(rows[1]!).getByTestId('title-block-mismatch')).toHaveTextContent('Title block shows A-020');
    expect(rows[1]).toHaveTextContent('Work in progress');

    fireEvent.change(screen.getByTestId('drawing-search'), { target: { value: 'A-002' } });
    expect(screen.getAllByTestId('drawing-row')).toHaveLength(1);
    fireEvent.change(screen.getByTestId('drawing-search'), { target: { value: 'no such drawing' } });
    expect(screen.queryAllByTestId('drawing-row')).toHaveLength(0);
    expect(screen.getByText('No drawing matches this search.')).toBeInTheDocument();
  });
});

describe('WbsPanel', () => {
  it('an empty breakdown shows how to start', () => {
    wrap(<WbsPanel ctx={context()} />);
    expect(screen.getByText('No work breakdown yet')).toBeInTheDocument();
    expect(screen.getByText(/Start with the top level/)).toBeInTheDocument();
  });

  it('lists parents before children and flags duplicates, use and dangling references', async () => {
    mocked.listUnresolvedWbs.mockResolvedValue([{ module: 'cost_model', table: 'cost_lines', row_id: 'x1', value: '9.9' }]);
    const ctx = context({
      wbs: [
        wbsNode({ id: 'w2', parent_id: 'w1', code: '1.1', name: 'Substructure', level: 2, references: { costs: 2, schedule: 3 }, duplicate_code: true }),
        wbsNode(),
      ],
    });
    wrap(<WbsPanel ctx={ctx} />);
    const rows = screen.getAllByTestId('wbs-row');
    expect(rows.map((r) => r.querySelector('td')?.textContent)).toEqual(['1', '1.1']);
    expect(rows[0]).toHaveTextContent('Not used yet');
    expect(rows[1]).toHaveTextContent('5 records');
    expect(within(rows[1]!).getByTestId('wbs-duplicate')).toHaveTextContent('Code used twice');
    const warning = await screen.findByTestId('wbs-unresolved');
    expect(warning).toHaveTextContent('1 record refers to a code that matches no node.');
    expect(warning).toHaveTextContent('Cost model refers to "9.9"');
  });
});

describe('IssuePanel', () => {
  it('an empty issue tab says what a release is and that recipients are needed', async () => {
    wrap(<IssuePanel ctx={context()} />);
    expect(await screen.findByText('No releases yet')).toBeInTheDocument();
    expect(await screen.findByText(/Without a recipient a release cannot be issued/)).toBeInTheDocument();
  });

  it('the Issue button follows the answer of the server and shows its reason', async () => {
    mocked.listReleases.mockResolvedValue([
      release({
        state: 'ready',
        approval_status: 'pending',
        can: {
          transitions: { draft: yes, cancelled: { allowed: false, applies: true, reason: 'forbidden' } },
          issue: { allowed: false, applies: true, reason: 'release_not_approved' },
          approve: { allowed: false, applies: true, reason: 'release_four_eyes' },
        },
      }),
      release({
        id: 'rl2',
        code: 'REL-002',
        title: 'Tender set',
        state: 'ready',
        approval_status: 'approved',
        can: { transitions: { draft: yes }, issue: yes, approve: absent },
      }),
    ]);
    wrap(<IssuePanel ctx={context()} />);
    const rows = await screen.findAllByTestId('release-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByTestId('release-approval')).toHaveTextContent('Waiting for approval');
    expect(within(rows[0]!).getByTestId('release-issue')).toBeDisabled();
    expect(within(rows[0]!).getByTestId('release-issue-reason')).toHaveTextContent('The release has not been approved on its approval route yet.');
    expect(within(rows[1]!).getByTestId('release-approval')).toHaveTextContent('Approved for issue');
    expect(within(rows[1]!).getByTestId('release-issue')).toBeEnabled();
    expect(within(rows[1]!).queryByTestId('release-issue-reason')).toBeNull();
    // a step this user may not take is shown greyed out with the reason, not hidden
    expect(within(rows[0]!).getByTestId('release-to-draft')).toBeEnabled();
    expect(within(rows[0]!).getByTestId('release-to-cancelled')).toBeDisabled();
    // the reason is words on the screen, not only a tooltip
    expect(within(rows[0]!).getByTestId('release-to-cancelled-reason')).toHaveTextContent(ERROR_TEXT.forbidden!);
    expect(within(rows[1]!).queryByTestId('release-to-cancelled')).toBeNull();
  });

  it('a draft release that is not ready shows no Issue button at all', async () => {
    mocked.listReleases.mockResolvedValue([release({ can: { transitions: { ready: yes, cancelled: yes }, issue: absent, approve: absent } })]);
    wrap(<IssuePanel ctx={context()} />);
    const row = await screen.findByTestId('release-row');
    expect(within(row).getByTestId('release-to-ready')).toHaveTextContent('Mark ready');
    expect(within(row).queryByTestId('release-issue')).toBeNull();
  });

  it('a recipient without a purpose receives releases of any purpose', async () => {
    mocked.listDistributionRules.mockResolvedValue([
      {
        id: 'ru1',
        recipient_list_id: null,
        recipient_role_id: 'r1',
        discipline_codes: [],
        form_codes: [],
        phase_codes: [],
        wbs_node_ids: [],
        min_suitability: null,
        purpose: '',
        format: 'pdf',
        copies_paper: 0,
        ack_required: false,
        active: true,
      },
    ]);
    wrap(<IssuePanel ctx={context({ roles: [role()] })} />);
    const row = await screen.findByTestId('rule-row');
    expect(row).toHaveTextContent('Architect');
    expect(row).toHaveTextContent('Any purpose');
  });
});

describe('PermitsPanel', () => {
  it('an empty permit tab says what the package is for', async () => {
    wrap(<PermitsPanel ctx={context()} />);
    expect(await screen.findByText('No permit package yet')).toBeInTheDocument();
    expect(screen.getByText(/You see at once which items are still missing/)).toBeInTheDocument();
  });

  it('a failing list is an error with a retry, not an empty package', async () => {
    mocked.listPermits.mockRejectedValue(new ApiError(500, 'Server Error', { detail: 'database unavailable' }));
    wrap(<PermitsPanel ctx={context()} />);
    expect(await screen.findByText('The permit packages could not be loaded')).toBeInTheDocument();
    expect(screen.queryByText('No permit package yet')).toBeNull();
  });

  it('shows what is missing, and a refused step shows the reason of the server', async () => {
    mocked.listPermits.mockResolvedValue([
      permit({
        can: { transitions: { ready: yes, submitted: yes, withdrawn: yes } },
        missing: ['i2'],
        items: [
          permitItem(),
          permitItem({ id: 'i2', kind: 'report', title: 'Fire safety concept', present: false, state_ok: false }),
          permitItem({ id: 'i3', kind: 'form', title: 'Application form', required: false, state_ok: false }),
        ],
      }),
    ]);
    mocked.movePermit.mockRejectedValue(
      new ApiError(409, 'Conflict', { detail: { code: 'permit_incomplete', message: 'Required items are missing or not shared yet.' } }),
    );
    wrap(<PermitsPanel ctx={context()} />);
    const card = await screen.findByTestId('permit-card');
    expect(card).toHaveTextContent('Building permit');
    expect(within(card).getByTestId('permit-state')).toHaveTextContent('Being assembled');
    expect(within(card).getByTestId('permit-missing')).toHaveTextContent('1 required item is missing or not shared yet.');
    const items = within(card).getAllByTestId('permit-item');
    expect(items.map((i) => i.getAttribute('data-state'))).toEqual(['ready', 'missing', 'not_shared']);
    expect(items[1]).toHaveTextContent('Document missing');
    expect(items[2]).toHaveTextContent('optional');

    fireEvent.click(within(card).getByTestId('permit-to-ready'));
    await waitFor(() => expect(mocked.movePermit).toHaveBeenCalledWith('p1', 'pm1', 'ready'));
    await waitFor(() =>
      expect(useToastStore.getState().toasts.map((toast) => toast.title)).toContain('Required items are missing or not shared yet.'),
    );
  });

  it('removing an item from the package asks first and removes nothing until confirmed', async () => {
    mocked.listPermits.mockResolvedValue([permit({ state: 'assembling', items: [permitItem()] })]);
    mocked.removePermitItem.mockResolvedValue(undefined);
    wrap(<PermitsPanel ctx={context()} />);
    const card = await screen.findByTestId('permit-card');
    fireEvent.click(within(card).getByRole('button', { name: 'Remove' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Remove this item from the package?');
    expect(mocked.removePermitItem).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(mocked.removePermitItem).not.toHaveBeenCalled();
    fireEvent.click(within(card).getByRole('button', { name: 'Remove' }));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(mocked.removePermitItem).toHaveBeenCalledWith('p1', 'pm1', 'i1'));
  });

  it('a submitted package offers no editing and only the step a person takes', async () => {
    mocked.listPermits.mockResolvedValue([permit({
        state: 'submitted',
        items: [permitItem()],
        superseded_content: true,
        can: { transitions: { withdrawn: yes, approved: { allowed: false, applies: false, reason: 'permit_state_read_from_cycle' } } },
      }),
    ]);
    wrap(<PermitsPanel ctx={context()} />);
    const card = await screen.findByTestId('permit-card');
    expect(within(card).getByTestId('permit-superseded')).toBeInTheDocument();
    expect(within(card).queryByTestId('permit-item-add')).toBeNull();
    expect(within(card).queryByTestId('permit-to-ready')).toBeNull();
    expect(within(card).getByTestId('permit-to-withdrawn')).toHaveTextContent('Withdraw');
    expect(within(card).queryByTestId('permit-to-approved')).toBeNull();
  });
});
