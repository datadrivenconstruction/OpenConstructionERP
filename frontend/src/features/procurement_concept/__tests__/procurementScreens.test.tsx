// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The screens one by one: what each shows, which buttons the server's
// capability flags leave open, what a write sends, and how a refusal reads.

import type { ReactElement } from 'react';
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', async () => (await import('./i18nMock')).i18nMockModule);
vi.mock('@/features/subcontractors/api', () => ({ listSubcontractors: vi.fn(async () => ({ items: [], total: 0 })) }));
vi.mock('@/features/supplier-catalogs/api', () => ({ listVendors: vi.fn(async () => ({ items: [], total: 0 })) }));
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    conceptAction: vi.fn(),
    downloadExport: vi.fn(),
    setPackageState: vi.fn(),
    createExecution: vi.fn(),
    linkExecution: vi.fn(),
    listTenderPackages: vi.fn(),
    listCostSections: vi.fn(),
    deleteProfile: vi.fn(),
    listAdvanceReleases: vi.fn(),
    putPackage: vi.fn(),
    getThreshold: vi.fn(),
    listCandidates: vi.fn(),
    confirmShortlist: vi.fn(),
    deleteCandidate: vi.fn(),
    confirmSchedule: vi.fn(),
    createFramework: vi.fn(),
    patchFramework: vi.fn(),
    setFrameworkState: vi.fn(),
    getLedger: vi.fn(),
    deleteSounding: vi.fn(),
    createSounding: vi.fn(),
  };
});

import en from '@/app/locales/en';
import { ApiError } from '@/shared/lib/api';
import * as api from '../api';
import { AwardSchedule } from '../AwardSchedule';
import { REGISTER_MAX_PAGES, REGISTER_PAGE, filterCompanies, readRegister } from '../CompanyPicker';
import { ConceptRecord } from '../ConceptRecord';
import { Frameworks } from '../Frameworks';
import type { LabelContext } from '../labels';
import { MarketSoundings } from '../MarketSoundings';
import { PackageBoard } from '../PackageBoard';
import { PackageDialog } from '../PackageDialog';
import { PrequalPanel } from '../PrequalPanel';
import {
  LOCKED,
  NO_RIGHTS,
  agreementPackage,
  blockingFinding,
  can,
  catalogue,
  closedCan,
  noGatesCan,
  concept,
  framework,
  ledger,
  matrix,
  packageCan,
  packageView,
  profile,
  schedule,
  soundingTight,
  thresholdCheck,
  unplannedPackage,
  warningFinding,
} from './fixtures';
import { enT } from './i18nMock';

const mocked = vi.mocked(api);
const labels: LabelContext = { t: enT as LabelContext['t'], language: 'en', exists: (k) => k in en.translation };
const refusal = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  new ApiError(status, 'Refused', { detail: { code, message: 'server sentence', ...extra } });
const readOnly = () => concept({ can: NO_RIGHTS });
const yes = { allowed: true, reason: null, applies: true };
const denied = (reason: string, applies = true) => ({ allowed: false, reason, applies });

function show(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}
const rowOf = (testId: string, attr: string, value: string) =>
  screen.getAllByTestId(testId).find((r) => r.getAttribute(attr) === value) as HTMLElement;

beforeEach(() => {
  vi.resetAllMocks();
  mocked.listCostSections.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 0 });
});
afterEach(cleanup);

describe('the company registers behind the picker', () => {
  const rows = (n: number, from = 0) => Array.from({ length: n }, (_, i) => ({ id: `c${from + i}` }));

  it('reads one page when the register fits in it', async () => {
    const page = vi.fn(async () => ({ items: rows(3), total: 3 }));
    expect(await readRegister(page)).toEqual({ items: rows(3), missing: 0 });
    expect(page).toHaveBeenCalledTimes(1);
    expect(page).toHaveBeenCalledWith(0, REGISTER_PAGE);
  });

  it('reads the next pages until it has every company', async () => {
    const total = REGISTER_PAGE + 5;
    const page = vi.fn(async (offset: number) => ({ items: rows(offset === 0 ? REGISTER_PAGE : 5, offset), total }));
    const got = await readRegister(page);
    expect(got.items).toHaveLength(total);
    expect(got.missing).toBe(0);
    expect(page).toHaveBeenLastCalledWith(REGISTER_PAGE, REGISTER_PAGE);
  });

  it('stops at the page budget and counts what it left out', async () => {
    const budget = REGISTER_PAGE * REGISTER_MAX_PAGES;
    const page = vi.fn(async (offset: number) => ({ items: rows(REGISTER_PAGE, offset), total: budget + 40 }));
    const got = await readRegister(page);
    expect(page).toHaveBeenCalledTimes(REGISTER_MAX_PAGES);
    expect(got.items).toHaveLength(budget);
    expect(got.missing).toBe(40);
  });

  it('narrows by every word typed, whatever the case', () => {
    const list = [
      { value: 'subcontractor:1', name: 'Northern Roofing Works' },
      { value: 'vendor:2', name: 'Steel supply north' },
    ];
    expect(filterCompanies(list, '  ')).toEqual(list);
    expect(filterCompanies(list, 'NORTH')).toEqual(list);
    expect(filterCompanies(list, 'north roof')).toEqual([list[0]]);
    expect(filterCompanies(list, 'glazing')).toEqual([]);
  });
});

describe('PackageBoard', () => {
  const packages = [packageView(), unplannedPackage, agreementPackage];
  const board = (over: Partial<Parameters<typeof PackageBoard>[0]> = {}) => {
    const props = {
      projectId: 'p1',
      concept: concept(),
      packages,
      labels,
      onPlan: vi.fn(),
      onCandidates: vi.fn(),
      onChanged: vi.fn(),
      ...over,
    };
    show(<PackageBoard {...props} />);
    return props;
  };

  it('says where packages come from when the delivery model has none', () => {
    board({ packages: [] });
    expect(screen.getByText('The delivery model has no package plan yet.')).toBeInTheDocument();
    expect(screen.queryByTestId('package-board')).toBeNull();
  });

  it('shows a planned package with its value, threshold, procedure and state', () => {
    board();
    const row = rowOf('package-row', 'data-package', 'CP-01');
    expect(row).toHaveTextContent('Structural works');
    expect(row).toHaveTextContent('2,400,000');
    expect(within(row).getByTestId('threshold-badge')).toBeInTheDocument();
    expect(within(row).getByTestId('package-state')).toHaveTextContent('Procedure set');
    expect(within(row).getByTestId('package-plan')).toHaveTextContent('Change plan');
  });

  it('names the latest procedure start only while the package is still to be awarded', () => {
    board({ packages: [packageView()] });
    expect(within(rowOf('package-row', 'data-package', 'CP-01')).getByTestId('package-start-by')).toBeInTheDocument();
    cleanup();
    board({ packages: [packageView({}, { state: 'awarded' })] });
    const row = rowOf('package-row', 'data-package', 'CP-01');
    expect(within(row).queryByTestId('package-start-by')).toBeNull();
    expect(within(row).getByTestId('package-state')).toHaveTextContent('Awarded');
  });

  it('offers the first step on a package with no award plan', () => {
    const props = board();
    const row = rowOf('package-row', 'data-package', 'CP-03');
    expect(within(row).getByTestId('package-unplanned')).toBeInTheDocument();
    expect(within(row).queryByTestId('package-hold')).toBeNull();
    fireEvent.click(within(row).getByTestId('package-plan'));
    expect(props.onPlan).toHaveBeenCalledWith('k3');
  });

  it('offers no award plan for a package that is not procured on its own', () => {
    board();
    const row = rowOf('package-row', 'data-package', 'CP-00');
    expect(within(row).getByTestId('not-procured')).toBeInTheDocument();
    expect(within(row).queryByTestId('package-plan')).toBeNull();
    expect(within(row).queryByTestId('package-execution')).toBeNull();
  });

  it('puts a package on hold in one step', async () => {
    mocked.setPackageState.mockResolvedValue(undefined as never);
    const props = board();
    fireEvent.click(within(rowOf('package-row', 'data-package', 'CP-01')).getByTestId('package-hold'));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    expect(mocked.setPackageState.mock.calls[0]!.slice(0, 3)).toEqual(['p1', 'k1', 'hold']);
  });

  it('asks before cancelling, and sends nothing until the reader agrees', async () => {
    mocked.setPackageState.mockResolvedValue(undefined as never);
    board();
    const row = rowOf('package-row', 'data-package', 'CP-01');
    fireEvent.click(within(row).getByTestId('package-cancel'));
    expect(within(row).getByTestId('package-confirm')).toBeInTheDocument();
    expect(mocked.setPackageState).not.toHaveBeenCalled();
    fireEvent.click(within(row).getByTestId('package-confirm-yes'));
    await waitFor(() => expect(mocked.setPackageState).toHaveBeenCalledTimes(1));
    expect(mocked.setPackageState.mock.calls[0]!.slice(0, 3)).toEqual(['p1', 'k1', 'cancel']);
  });

  it('creates the bid package only after a confirmation', async () => {
    mocked.createExecution.mockResolvedValue(undefined as never);
    board();
    const row = rowOf('package-row', 'data-package', 'CP-01');
    expect(within(row).getByTestId('package-execution')).toHaveTextContent('Create bid package');
    fireEvent.click(within(row).getByTestId('package-execution'));
    expect(mocked.createExecution).not.toHaveBeenCalled();
    fireEvent.click(within(row).getByTestId('package-confirm-yes'));
    await waitFor(() => expect(mocked.createExecution).toHaveBeenCalledWith('p1', 'k1'));
  });

  it('shows the reason of a refused move', async () => {
    mocked.setPackageState.mockRejectedValue(refusal(409, 'concept_locked'));
    board();
    fireEvent.click(within(rowOf('package-row', 'data-package', 'CP-01')).getByTestId('package-hold'));
    expect(await screen.findByTestId('refusal-box')).toHaveAttribute('data-code', 'concept_locked');
  });

  it('keeps every write closed, with the reason, for a reader the server gave no rights', () => {
    board({ concept: readOnly(), packages: [packageView({ can: packageCan({ all: 'not_procurement_owner' }) })] });
    const row = rowOf('package-row', 'data-package', 'CP-01');
    for (const id of ['package-plan', 'package-hold', 'package-cancel', 'package-execution', 'package-link']) {
      expect(within(row).getByTestId(id)).toBeDisabled();
    }
    expect(within(row).getAllByTestId('disabled-reason')[0]).toHaveAttribute('data-reason', 'not_procurement_owner');
    expect(screen.getByTestId('board-locked')).toHaveTextContent(en.translation['procurement_concept.errors.not_procurement_owner']!);
    // Reading the candidates stays open.
    expect(within(row).getByTestId('package-candidates')).toBeEnabled();
  });

  it('locks the plan but leaves steering open once the concept is submitted', () => {
    board({
      concept: concept({ state: 'in_review', can: LOCKED }),
      packages: [packageView({ can: packageCan({ edit: 'concept_locked', resume: 'package_not_on_hold', create_execution: 'concept_not_approved' }) })],
    });
    const row = rowOf('package-row', 'data-package', 'CP-01');
    expect(within(row).getByTestId('package-plan')).toBeDisabled();
    expect(within(row).getByTestId('package-hold')).toBeEnabled();
    // Tendering waits for the approval, and the row says so instead of hiding the button.
    expect(within(row).getByTestId('package-execution')).toBeDisabled();
    expect(within(row).queryByTestId('package-resume')).toBeNull();
  });

  it('shows the buttons the flags of the row name, whatever the state reads', () => {
    board({ packages: [packageView({ can: packageCan({ hold: 'package_not_found', cancel: 'package_closed', create_execution: 'execution_exists' }) })] });
    const row = rowOf('package-row', 'data-package', 'CP-01');
    expect(within(row).queryByTestId('package-hold')).toBeNull();
    expect(within(row).queryByTestId('package-cancel')).toBeNull();
    expect(within(row).queryByTestId('package-execution')).toBeNull();
    expect(within(row).getByTestId('package-resume')).toBeEnabled();
  });

  it('links a tender package that already exists, and not one that serves another package', async () => {
    mocked.listTenderPackages.mockResolvedValue({
      items: [
        { id: 't1', name: 'Structure tender', status: 'draft', deadline: '2027-04-01', linked_package_id: null, linked_package_code: null, can: { link: yes } },
        { id: 't2', name: 'Facade tender', status: 'draft', deadline: null, linked_package_id: 'k9', linked_package_code: 'CP-09', can: { link: denied('execution_exists') } },
      ],
      total: 2,
      offset: 0,
      limit: 2,
    });
    mocked.linkExecution.mockResolvedValue(undefined as never);
    const props = board();
    fireEvent.click(within(rowOf('package-row', 'data-package', 'CP-01')).getByTestId('package-link'));
    const options = await screen.findAllByTestId('link-tender-option');
    expect(options.map((o) => o.getAttribute('data-allowed'))).toEqual(['yes', 'no']);
    expect(options[1]).toHaveTextContent('Already serves CP-09');
    expect(within(options[1]!).getByRole('radio')).toBeDisabled();
    expect(screen.getByTestId('link-tender-save')).toBeDisabled();
    fireEvent.click(within(options[0]!).getByRole('radio'));
    fireEvent.click(screen.getByTestId('link-tender-save'));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    expect(mocked.linkExecution).toHaveBeenCalledWith('p1', 'k1', 't1');
  });

  it('leaves out a tender package the server says cannot be linked at all', async () => {
    mocked.listTenderPackages.mockResolvedValue({
      items: [
        { id: 't1', name: 'Structure tender', status: 'draft', deadline: null, linked_package_id: null, linked_package_code: null, can: { link: yes } },
        { id: 't2', name: 'Facade tender', status: 'draft', deadline: null, linked_package_id: 'k9', linked_package_code: 'CP-09', can: { link: denied('execution_exists', false) } },
      ],
      total: 2,
      offset: 0,
      limit: 2,
    });
    board();
    fireEvent.click(within(rowOf('package-row', 'data-package', 'CP-01')).getByTestId('package-link'));
    const options = await screen.findAllByTestId('link-tender-option');
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent('Structure tender');
  });

  it('says every tender package is taken when none is left to link', async () => {
    mocked.listTenderPackages.mockResolvedValue({
      items: [{ id: 't2', name: 'Facade tender', status: 'draft', deadline: null, linked_package_id: 'k9', linked_package_code: 'CP-09', can: { link: denied('execution_exists', false) } }],
      total: 1,
      offset: 0,
      limit: 1,
    });
    board();
    fireEvent.click(within(rowOf('package-row', 'data-package', 'CP-01')).getByTestId('package-link'));
    expect(await screen.findByTestId('link-tender-empty')).toHaveTextContent('already serves an award package');
  });

  it('says so when the project has no tender package to link', async () => {
    mocked.listTenderPackages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 0 });
    board();
    fireEvent.click(within(rowOf('package-row', 'data-package', 'CP-01')).getByTestId('package-link'));
    expect(await screen.findByTestId('link-tender-empty')).toBeInTheDocument();
  });
});

describe('ConceptRecord', () => {
  const record = (over: Partial<Parameters<typeof ConceptRecord>[0]> = {}) => {
    const props = {
      projectId: 'p1',
      concept: concept(),
      findings: [blockingFinding, warningFinding],
      findingsLoading: false,
      labels,
      refLabel: (ref: string) => ref,
      onEdit: vi.fn(),
      onChanged: vi.fn(),
      ...over,
    };
    show(<ConceptRecord {...props} />);
    return props;
  };

  it('lists what blocks approval before the warnings', () => {
    record();
    expect(screen.getByTestId('concept-findings')).toHaveTextContent('Blocking approval: 1. Warnings: 1.');
    const items = within(screen.getByTestId('finding-list')).getAllByRole('listitem');
    expect(items.map((i) => i.getAttribute('data-blocking'))).toEqual(['yes', 'no']);
    expect(items[0]).toHaveTextContent(en.translation['procurement_concept.findings.package_without_procedure_plan']!);
  });

  it('says so when the rule check found nothing', () => {
    record({ findings: [] });
    expect(screen.getByTestId('concept-findings')).toHaveTextContent('Nothing found.');
  });

  it('submits a draft for review', async () => {
    mocked.conceptAction.mockResolvedValue(concept({ state: 'in_review' }) as never);
    const props = record();
    fireEvent.click(screen.getByTestId('concept-submit'));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    expect(mocked.conceptAction).toHaveBeenCalledWith('p1', 'submit', undefined);
  });

  it('a refused submit lists every finding the server named', async () => {
    mocked.conceptAction.mockRejectedValue(refusal(422, 'package_without_procedure_plan', { violations: [blockingFinding] }));
    record();
    fireEvent.click(screen.getByTestId('concept-submit'));
    const box = await screen.findByTestId('refusal-box');
    expect(box).toHaveAttribute('data-code', 'package_without_procedure_plan');
    expect(within(box).getByTestId('refusal-violations').querySelector('[data-finding="package_without_procedure_plan"]')).not.toBeNull();
  });

  it('offers no approve button: the governance gate approves, and the screen says so', () => {
    record({ concept: concept({ state: 'in_review', can: LOCKED }) });
    expect(screen.queryByTestId('concept-approve')).toBeNull();
    expect(screen.queryByTestId('concept-reopen')).toBeNull();
    expect(screen.getByTestId('approval-by-gate')).toHaveTextContent('The governance gate approves the concept.');
    expect(screen.getByTestId('concept-return')).toBeEnabled();
  });

  it('lets a manager approve by hand on a project without gates, and says who approves', async () => {
    mocked.conceptAction.mockResolvedValue(concept({ state: 'approved' }) as never);
    const submitted = concept({ state: 'in_review', gates_in_use: false, can: noGatesCan({ edit_plan: 'concept_locked', submit: 'invalid_transition' }) });
    const props = record({ concept: submitted });
    expect(screen.queryByTestId('approval-by-gate')).toBeNull();
    expect(screen.getByTestId('approval-by-hand')).toHaveTextContent('a person with the manage right approves the concept');
    expect(screen.getByTestId('concept-record')).toHaveTextContent('A manager approves it');
    expect(screen.getByTestId('concept-approve')).toHaveTextContent('Approve concept');
    fireEvent.click(screen.getByTestId('concept-approve'));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    expect(mocked.conceptAction).toHaveBeenCalledWith('p1', 'approve', undefined);
  });

  it('keeps approval closed with the reason for the person who submitted', () => {
    const own = concept({
      state: 'in_review',
      gates_in_use: false,
      can: noGatesCan({ edit_plan: 'concept_locked', submit: 'invalid_transition', approve: 'approver_is_submitter' }),
    });
    record({ concept: own });
    expect(screen.getByTestId('concept-approve')).toBeDisabled();
    expect(screen.getByTestId('concept-record')).toHaveTextContent(en.translation['procurement_concept.errors.approver_is_submitter']!);
  });

  it('names submit for approval, not for a gate, on a project without gates', () => {
    record({ concept: concept({ gates_in_use: false, can: noGatesCan({ approve: 'concept_not_submitted', return: 'invalid_transition' }) }) });
    expect(screen.getByTestId('concept-submit')).toHaveTextContent('Submit for approval');
    expect(screen.getByTestId('concept-approve')).toBeDisabled();
    expect(screen.getByTestId('concept-record')).not.toHaveTextContent('for the gate');
  });

  it('reopens an approved concept by hand where the server offers it', async () => {
    mocked.conceptAction.mockResolvedValue(concept({ state: 'reopened' }) as never);
    const approved = concept({
      state: 'approved',
      gates_in_use: false,
      can: noGatesCan({ edit_plan: 'concept_locked', submit: 'invalid_transition', return: 'invalid_transition', approve: 'invalid_transition' }, { reopen: yes }),
    });
    record({ concept: approved });
    expect(screen.queryByTestId('concept-approve')).toBeNull();
    fireEvent.click(screen.getByTestId('concept-reopen'));
    // Nothing is sent until the reason is given: the server records it with the reopening.
    expect(mocked.conceptAction).not.toHaveBeenCalled();
    expect(screen.getByTestId('concept-reopen-confirm')).toBeDisabled();
    fireEvent.change(document.getElementById('pc-reopen-reason') as HTMLTextAreaElement, { target: { value: '  Scope of the facade changed ' } });
    fireEvent.click(screen.getByTestId('concept-reopen-confirm'));
    await waitFor(() => expect(mocked.conceptAction).toHaveBeenCalledWith('p1', 'reopen', 'Scope of the facade changed'));
    await waitFor(() => expect(screen.queryByTestId('concept-reopen-form')).toBeNull());
  });

  it('returns a submitted concept to draft', async () => {
    mocked.conceptAction.mockResolvedValue(concept() as never);
    record({ concept: concept({ state: 'in_review', can: LOCKED }) });
    fireEvent.click(screen.getByTestId('concept-return'));
    await waitFor(() => expect(mocked.conceptAction).toHaveBeenCalledWith('p1', 'return', undefined));
  });

  it('keeps submit closed with the reason the server gave', () => {
    record({ concept: concept({ can: can({ submit: 'not_procurement_owner', return: 'invalid_transition' }) }) });
    expect(screen.getByTestId('concept-submit')).toBeDisabled();
    expect(screen.queryByTestId('concept-return')).toBeNull();
    expect(screen.getAllByTestId('disabled-reason')[0]).toHaveAttribute('data-reason', 'not_procurement_owner');
  });

  it('names the gate that releases procurement, or says it is not known', () => {
    record();
    expect(screen.getByTestId('concept-record')).toHaveTextContent('g3');
    cleanup();
    record({ concept: concept({ resolved_release_gate_code: null }) });
    expect(screen.getByTestId('concept-record')).toHaveTextContent('Not known yet');
  });

  it('says gates are not used on a project without a phase model', () => {
    record({ concept: concept({ resolved_release_gate_code: null, gates_in_use: false }) });
    expect(screen.getByTestId('concept-record')).toHaveTextContent('None, this project does not use gates');
    expect(screen.getByTestId('concept-record')).not.toHaveTextContent('Not known yet');
    cleanup();
    // Gates in use and none resolved is the real gap and keeps its words.
    record({ concept: concept({ resolved_release_gate_code: null, gates_in_use: true, released_from_start: false }) });
    expect(screen.getByTestId('concept-record')).toHaveTextContent('Not known yet');
  });

  it('says procurement is open from the start where the phase model has no release gate', () => {
    record({ concept: concept({ resolved_release_gate_code: null, released_from_start: true }) });
    expect(screen.getByTestId('concept-record')).toHaveTextContent('None, procurement is open from the project start');
    expect(screen.getByTestId('concept-record')).not.toHaveTextContent('Not known yet');
  });

  it('says so when the person who submitted also approved', () => {
    record({ concept: concept({ state: 'approved', can: LOCKED, four_eyes_violated: true }) });
    expect(screen.getByTestId('four-eyes')).toBeInTheDocument();
  });

  it('offers no lifecycle step on a binding concept', () => {
    record({ concept: concept({ state: 'binding', can: closedCan('binding_requires_change_request') }) });
    for (const action of ['submit', 'return']) expect(screen.queryByTestId(`concept-${action}`)).toBeNull();
    expect(screen.getByTestId('concept-edit')).toBeDisabled();
  });

  it('downloads the printable record', async () => {
    mocked.downloadExport.mockResolvedValue(undefined as never);
    record();
    fireEvent.click(screen.getByTestId('export-concept'));
    await waitFor(() => expect(mocked.downloadExport).toHaveBeenCalledWith('p1', 'concept', 'pdf'));
  });
});

describe('PackageDialog', () => {
  const dialog = (view = packageView()) => {
    const props = {
      open: true,
      onClose: vi.fn(),
      projectId: 'p1',
      view,
      catalogue,
      frameworks: [framework],
      profiles: [profile],
      labels,
      onSaved: vi.fn(),
    };
    show(<PackageDialog {...props} />);
    return props;
  };

  it('asks for the value first on a package without an award plan, and does not ask the server for a check', () => {
    dialog(unplannedPackage);
    expect(screen.getByTestId('threshold-pending')).toBeInTheDocument();
    expect(mocked.getThreshold).not.toHaveBeenCalled();
    // The catalogue's procedures are offered until the check narrows them.
    expect(screen.getAllByTestId('procedure-option')).toHaveLength(2);
  });

  it('shows the threshold check and marks the procedures it rules out', async () => {
    mocked.getThreshold.mockResolvedValue(thresholdCheck);
    dialog();
    expect(await screen.findByTestId('threshold-status')).toBeInTheDocument();
    expect(mocked.getThreshold.mock.calls[0]!.slice(0, 2)).toEqual(['p1', 'k1']);
    const options = screen.getAllByTestId('procedure-option');
    expect(options.map((o) => o.getAttribute('data-allowed'))).toEqual(['yes', 'no']);
    expect(within(screen.getByTestId('threshold-rows')).getByText(/5,538,000/)).toBeInTheDocument();
  });

  it('sends only what changed, the amount as a string', async () => {
    mocked.getThreshold.mockResolvedValue(thresholdCheck);
    mocked.putPackage.mockResolvedValue(packageView() as never);
    const props = dialog();
    fireEvent.change(document.getElementById('pk-value') as HTMLInputElement, { target: { value: '2500000.50' } });
    fireEvent.click(screen.getByTestId('package-save'));
    await waitFor(() => expect(props.onSaved).toHaveBeenCalledWith(false));
    expect(mocked.putPackage).toHaveBeenCalledWith('p1', 'k1', { estimated_value: '2500000.50' });
  });

  it('offers a commitment with its own status word, and says so when the commitment matrix is not connected', async () => {
    mocked.getThreshold.mockResolvedValue(thresholdCheck);
    mocked.listAdvanceReleases.mockResolvedValue({
      items: [{ kind: 'commitment', id: 'cm1', gate_code: null, label: 'CR-1 Long lead steel', status: 'partly released', date: null, releases: false }],
      total: 1,
      offset: 0,
      limit: 1,
      commitments: { available: true, reason: null },
    });
    dialog();
    fireEvent.click(screen.getByTestId('package-advance'));
    await waitFor(() => expect((document.getElementById('pk-advance-release') as HTMLSelectElement).options.length).toBe(2));
    const select = document.getElementById('pk-advance-release') as HTMLSelectElement;
    expect(select.options[1]!.value).toBe('commitment:cm1');
    expect(select.options[1]!.textContent).toBe('Commitment CR-1 Long lead steel (partly released)');
    expect(screen.queryByTestId('commitments-unavailable')).toBeNull();
    cleanup();

    mocked.listAdvanceReleases.mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 0,
      commitments: { available: false, reason: 'commitment_release_unavailable' },
    });
    dialog();
    fireEvent.click(screen.getByTestId('package-advance'));
    expect(await screen.findByTestId('commitments-unavailable')).toHaveTextContent(
      en.translation['procurement_concept.errors.commitment_release_unavailable']!,
    );
  });

  it('leaves the advance switch out where no gate holds procurement back', () => {
    mocked.getThreshold.mockResolvedValue(thresholdCheck);
    const base = packageView();
    dialog({ ...base, can: { ...base.can, set_advance: denied('advance_not_applicable', false) } });
    expect(screen.queryByTestId('package-advance')).toBeNull();
    expect(screen.queryByTestId('advance-leftover')).toBeNull();
    expect(document.getElementById('pk-advance-reason')).toBeNull();
    expect(mocked.listAdvanceReleases).not.toHaveBeenCalled();
  });

  it('keeps the switch on a package that still carries the mark, so it can be cleared', async () => {
    mocked.getThreshold.mockResolvedValue(thresholdCheck);
    mocked.putPackage.mockResolvedValue(packageView() as never);
    const base = packageView({}, { is_advance: true, advance_reason: 'Long lead item' });
    dialog({ ...base, can: { ...base.can, set_advance: denied('advance_not_applicable', false) } });
    const tick = screen.getByTestId('package-advance') as HTMLInputElement;
    expect(tick.checked).toBe(true);
    expect(screen.getByTestId('advance-leftover')).toHaveTextContent(en.translation['procurement_concept.errors.advance_not_applicable']!);
    // The release fields make no sense here and nothing is asked of the server for them.
    expect(document.getElementById('pk-advance-reason')).toBeNull();
    expect(document.getElementById('pk-advance-release')).toBeNull();
    expect(mocked.listAdvanceReleases).not.toHaveBeenCalled();
    fireEvent.click(tick);
    expect(screen.queryByTestId('advance-leftover')).toBeNull();
    fireEvent.click(screen.getByTestId('package-save'));
    await waitFor(() => expect(mocked.putPackage).toHaveBeenCalledTimes(1));
    expect(mocked.putPackage.mock.calls[0]![2]).toMatchObject({ is_advance: false });
  });

  it('lets a package that carries the mark without a reason be saved with other edits', async () => {
    mocked.getThreshold.mockResolvedValue(thresholdCheck);
    mocked.putPackage.mockResolvedValue(packageView() as never);
    const base = packageView({}, { is_advance: true, advance_reason: '' });
    dialog({ ...base, can: { ...base.can, set_advance: denied('advance_not_applicable', false) } });
    fireEvent.change(document.getElementById('pk-notes') as HTMLTextAreaElement, { target: { value: 'Checked with the planner' } });
    expect(screen.getByTestId('package-save')).not.toBeDisabled();
    fireEvent.click(screen.getByTestId('package-save'));
    await waitFor(() => expect(mocked.putPackage).toHaveBeenCalledTimes(1));
    expect(mocked.putPackage.mock.calls[0]![2]).toEqual({ notes: 'Checked with the planner' });
  });

  it('names what releases an advance package from the acts of the release gate', async () => {
    mocked.getThreshold.mockResolvedValue(thresholdCheck);
    mocked.putPackage.mockResolvedValue(packageView() as never);
    mocked.listAdvanceReleases.mockResolvedValue({
      items: [
        { kind: 'gate_decision', id: 'd1', gate_code: 'g3', label: 'Go with conditions', status: 'decided', date: '2026-12-01', releases: true },
        { kind: 'condition', id: 'c1', gate_code: 'g3', label: 'Soil report accepted', status: 'open', date: null, releases: false },
      ],
      total: 2,
      offset: 0,
      limit: 2,
    });
    dialog();
    // Nothing is asked of the server while the package is not an advance package.
    expect(mocked.listAdvanceReleases).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('package-advance'));
    await waitFor(() => expect((document.getElementById('pk-advance-release') as HTMLSelectElement).options.length).toBe(3));
    const select = document.getElementById('pk-advance-release') as HTMLSelectElement;
    expect(select.options[2]!.textContent).toBe('Soil report accepted (still open)');
    fireEvent.change(document.getElementById('pk-advance-reason') as HTMLTextAreaElement, { target: { value: 'Long lead item' } });
    fireEvent.change(select, { target: { value: 'gate_decision:d1' } });
    fireEvent.click(screen.getByTestId('package-save'));
    await waitFor(() => expect(mocked.putPackage).toHaveBeenCalledTimes(1));
    expect(mocked.putPackage).toHaveBeenCalledWith('p1', 'k1', {
      is_advance: true,
      advance_reason: 'Long lead item',
      advance_release_kind: 'gate_decision',
      advance_release_id: 'd1',
    });
  });

  it('refuses a value that is not a number before anything is sent', () => {
    dialog(unplannedPackage);
    fireEvent.change(document.getElementById('pk-value') as HTMLInputElement, { target: { value: 'about two million' } });
    expect(screen.getByTestId('package-save')).toBeDisabled();
    expect(screen.getByTestId('form-problems')).toBeInTheDocument();
  });

  it('shows the server reason when the save is refused', async () => {
    mocked.putPackage.mockRejectedValue(refusal(422, 'procedure_not_allowed'));
    dialog(unplannedPackage);
    fireEvent.change(document.getElementById('pk-value') as HTMLInputElement, { target: { value: '100' } });
    fireEvent.change(document.getElementById('pk-currency') as HTMLInputElement, { target: { value: 'eur' } });
    fireEvent.click(screen.getByTestId('package-save'));
    expect(await screen.findByTestId('refusal-box')).toHaveAttribute('data-code', 'procedure_not_allowed');
    expect(mocked.putPackage).toHaveBeenCalledWith('p1', 'k3', { estimated_value: '100', currency: 'EUR' });
  });
});

describe('PrequalPanel', () => {
  const panel = (over: Partial<Parameters<typeof PrequalPanel>[0]> = {}) => {
    const props = {
      projectId: 'p1',
      concept: concept(),
      packages: [packageView(), unplannedPackage],
      profiles: [profile],
      catalogue,
      packageId: null,
      labels,
      onSelectPackage: vi.fn(),
      onGoToPackages: vi.fn(),
      onChanged: vi.fn(),
      ...over,
    };
    show(<PrequalPanel {...props} />);
    return props;
  };

  it('leaves out the candidate buttons the server says do not apply, and keeps a refused one with its reason', async () => {
    const base = matrix();
    mocked.listCandidates.mockResolvedValue({
      ...base,
      can: { ...base.can, add: denied('package_closed', false), score: denied('package_closed', false), reference: denied('not_procurement_owner'), delete: denied('package_closed', false) },
    });
    panel();
    const row = (await screen.findAllByTestId('candidate-row'))[0]!;
    for (const id of ['candidate-score', 'candidate-edit', 'candidate-remove']) expect(within(row).queryByTestId(id)).toBeNull();
    expect(screen.queryByTestId('candidate-add')).toBeNull();
    expect(within(row).getByTestId('candidate-reference')).toBeDisabled();
  });

  it('removes a profile nothing uses, after asking', async () => {
    mocked.listCandidates.mockResolvedValue(matrix());
    mocked.deleteProfile.mockResolvedValue(undefined as never);
    const spare = { ...profile, id: 'pf2', name: 'Spare profile', in_use: false, can: { edit: yes, delete: yes } };
    const props = panel({ profiles: [profile, spare] });
    const row = (await screen.findAllByTestId('profile-row')).find((r) => r.getAttribute('data-profile') === 'pf2') as HTMLElement;
    expect(row).toHaveTextContent('Not used by any package');
    fireEvent.click(within(row).getByTestId('profile-remove'));
    fireEvent.click(within(row).getByTestId('profile-remove-yes'));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    expect(mocked.deleteProfile).toHaveBeenCalledWith('p1', 'pf2');
  });

  it('keeps the delete of a profile in use closed with the reason, and leaves it out where it does not apply', async () => {
    mocked.listCandidates.mockResolvedValue(matrix());
    const used = { ...profile, in_use: true, can: { edit: yes, delete: denied('profile_in_use') } };
    const fixed = { ...profile, id: 'pf3', name: 'Fixed profile', can: { edit: yes, delete: denied('profile_in_use', false) } };
    panel({ profiles: [used, fixed] });
    const rows = await screen.findAllByTestId('profile-row');
    expect(within(rows[0]!).getByTestId('profile-remove')).toBeDisabled();
    expect(within(rows[0]!).getByTestId('disabled-reason')).toHaveAttribute('data-reason', 'profile_in_use');
    expect(within(rows[1]!).queryByTestId('profile-remove')).toBeNull();
  });

  it('sends the reader to the packages while none has an award plan', () => {
    const props = panel({ packages: [unplannedPackage] });
    expect(screen.getByText('No package has an award plan yet')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Packages' }));
    expect(props.onGoToPackages).toHaveBeenCalled();
    expect(mocked.listCandidates).not.toHaveBeenCalled();
  });

  it('shows the candidates with their scores, and what the short list still lacks', async () => {
    mocked.listCandidates.mockResolvedValue(matrix());
    panel();
    expect(await screen.findByTestId('candidate-matrix')).toBeInTheDocument();
    const rows = screen.getAllByTestId('candidate-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByTestId('candidate-total')).toHaveTextContent('82.8');
    expect(within(rows[1]!).getByTestId('candidate-unregistered')).toBeInTheDocument();
    expect(screen.getByTestId('shortlist-check').querySelector('[data-finding="shortlist_below_min_bidders"]')).not.toBeNull();
  });

  it('confirms the short list of the package on screen', async () => {
    mocked.listCandidates.mockResolvedValue(matrix({ findings: [] }));
    mocked.confirmShortlist.mockResolvedValue(undefined as never);
    const props = panel();
    fireEvent.click(await screen.findByTestId('shortlist-confirm'));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    expect(mocked.confirmShortlist).toHaveBeenCalledWith('p1', 'k1');
  });

  it('shows why the short list was refused', async () => {
    mocked.listCandidates.mockResolvedValue(matrix());
    mocked.confirmShortlist.mockRejectedValue(
      refusal(409, 'shortlist_not_confirmable', { violations: [{ code: 'shortlist_below_min_bidders', severity: 'error', ref: 'CP-01', blocks_approval: true }] }),
    );
    panel();
    fireEvent.click(await screen.findByTestId('shortlist-confirm'));
    expect(await screen.findByTestId('refusal-box')).toHaveAttribute('data-code', 'shortlist_not_confirmable');
  });

  it('asks before removing a candidate', async () => {
    mocked.listCandidates.mockResolvedValue(matrix());
    mocked.deleteCandidate.mockResolvedValue(undefined as never);
    panel();
    await screen.findByTestId('candidate-matrix');
    fireEvent.click(screen.getAllByTestId('candidate-remove')[1]!);
    expect(mocked.deleteCandidate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('candidate-remove-yes'));
    await waitFor(() => expect(mocked.deleteCandidate).toHaveBeenCalledWith('p1', 'cand2'));
  });

  it('keeps the confirmation and the removal closed for an editor without steering, with the reason', async () => {
    mocked.listCandidates.mockResolvedValue(matrix({ can: { add: yes, score: yes, reference: yes, set_list: denied('not_procurement_owner'), delete: denied('not_procurement_owner'), confirm_shortlist: denied('not_procurement_owner') } }));
    panel();
    expect(await screen.findByTestId('shortlist-confirm')).toBeDisabled();
    for (const b of screen.getAllByTestId('candidate-remove')) expect(b).toBeDisabled();
    // Adding a company to the long list and scoring stay open to an editor.
    expect(screen.getByTestId('candidate-add')).toBeEnabled();
    expect(screen.getAllByTestId('candidate-score')[0]).toBeEnabled();
  });

  it('does not let an editor without steering move a company between the lists', async () => {
    mocked.listCandidates.mockResolvedValue(matrix({ can: { add: yes, score: yes, reference: yes, set_list: denied('not_procurement_owner'), delete: denied('not_procurement_owner'), confirm_shortlist: denied('not_procurement_owner') } }));
    panel();
    await screen.findByTestId('candidate-matrix');
    fireEvent.click(screen.getByTestId('candidate-add'));
    expect(document.getElementById('cd-list')).toBeDisabled();
    expect((document.getElementById('cd-list') as HTMLSelectElement).value).toBe('long');
  });

  it('closes every write for a viewer', async () => {
    const off = denied('permission_denied');
    mocked.listCandidates.mockResolvedValue(matrix({ can: { add: off, score: off, reference: off, set_list: off, delete: off, confirm_shortlist: off } }));
    panel({ profiles: [{ ...profile, can: { edit: off, delete: off } }] });
    await screen.findByTestId('candidate-matrix');
    for (const id of ['candidate-add', 'shortlist-confirm', 'profile-edit']) expect(screen.getByTestId(id)).toBeDisabled();
    for (const id of ['candidate-score', 'candidate-edit', 'candidate-reference', 'candidate-remove']) {
      for (const b of screen.getAllByTestId(id)) expect(b).toBeDisabled();
    }
  });

  it('keeps a short list with open findings visible, with the reason it cannot be confirmed', async () => {
    mocked.listCandidates.mockResolvedValue(matrix({ can: { ...matrix().can, confirm_shortlist: denied('shortlist_invalid') } }));
    panel();
    expect(await screen.findByTestId('shortlist-confirm')).toBeDisabled();
  });

  it('offers no confirmation once the short list is confirmed', async () => {
    mocked.listCandidates.mockResolvedValue(matrix({ package_state: 'shortlisted', can: { ...matrix().can, confirm_shortlist: denied('invalid_transition', false) } }));
    panel();
    await screen.findByTestId('candidate-matrix');
    expect(screen.queryByTestId('shortlist-confirm')).toBeNull();
  });
});

describe('AwardSchedule', () => {
  const view = (over: Partial<Parameters<typeof AwardSchedule>[0]> = {}) => {
    const props = { projectId: 'p1', concept: concept(), schedule, labels, onGoToPackages: vi.fn(), onChanged: vi.fn(), ...over };
    show(<AwardSchedule {...props} />);
    return props;
  };

  it('explains what feeds the schedule when there is nothing to plan', () => {
    view({ schedule: { ...schedule, items: [], total: 0 } });
    expect(screen.getByText('No award dates to plan yet')).toBeInTheDocument();
  });

  it('shows the proposal, and says what a row without dates still needs', () => {
    view();
    const ready = rowOf('schedule-row', 'data-package', 'CP-01');
    expect(within(ready).getByTestId('schedule-proposed')).toBeInTheDocument();
    expect(ready).toHaveTextContent('83 days');
    const open = rowOf('schedule-row', 'data-package', 'CP-03');
    expect(within(open).getByTestId('schedule-incomplete')).toBeInTheDocument();
    expect(within(open).getByRole('checkbox')).toBeDisabled();
    expect(within(open).getByTestId('schedule-findings').querySelector('[data-finding="need_date_missing"]')).not.toBeNull();
  });

  it('writes nothing to the project schedule until the reader confirms, then only the rows picked', async () => {
    mocked.confirmSchedule.mockResolvedValue({ items: [schedule.items[0]!], total: 1, offset: 0, limit: 1 } as never);
    const props = view();
    expect(mocked.confirmSchedule).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('schedule-confirm'));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    expect(mocked.confirmSchedule).toHaveBeenCalledWith('p1', ['k1']);
    expect(await screen.findByTestId('schedule-confirmed')).toHaveTextContent('Packages: 1.');
  });

  it('has nothing to confirm once every row is unpicked', () => {
    view();
    fireEvent.click(within(rowOf('schedule-row', 'data-package', 'CP-01')).getByRole('checkbox'));
    expect(screen.getByTestId('schedule-confirm')).toBeDisabled();
  });

  it('marks a row whose milestones are already in the schedule and does not pick it again', () => {
    const done = { ...schedule.items[0]!, start_activity_id: 'a1', award_activity_id: 'a2' };
    view({ schedule: { ...schedule, items: [done] } });
    expect(screen.getByTestId('schedule-in')).toBeInTheDocument();
    expect(screen.getByRole('checkbox')).not.toBeChecked();
  });

  it('shows the reason of a refused confirmation', async () => {
    mocked.confirmSchedule.mockRejectedValue(refusal(403, 'not_procurement_owner'));
    view();
    fireEvent.click(screen.getByTestId('schedule-confirm'));
    expect(await screen.findByTestId('refusal-box')).toHaveAttribute('data-code', 'not_procurement_owner');
    expect(screen.queryByTestId('schedule-confirmed')).toBeNull();
  });
});

describe('Frameworks', () => {
  const view = (frameworks = [framework], over: Partial<Parameters<typeof Frameworks>[0]> = {}) => {
    const props = { frameworks, canCreate: yes, labels, onChanged: vi.fn(), ...over };
    show(<Frameworks {...props} />);
    return props;
  };

  it('says what a framework agreement is for and offers to add the first one', () => {
    view([]);
    expect(screen.getByText('No framework agreements yet')).toBeInTheDocument();
    expect(screen.getByTestId('framework-add')).toBeInTheDocument();
  });

  it('shows an agreement with its ceiling, period and what it covers', () => {
    view();
    const entry = screen.getByTestId('framework-entry');
    expect(entry).toHaveTextContent('FW-SUPPLY-01');
    expect(entry).toHaveTextContent('2,500,000');
    expect(within(entry).getByTestId('framework-state')).toHaveTextContent('Active');
  });

  it('opens the call-offs with what is used and what remains', async () => {
    mocked.getLedger.mockResolvedValue(ledger);
    view();
    fireEvent.click(screen.getByTestId('framework-ledger-toggle'));
    expect(await screen.findByTestId('ledger-remaining')).toHaveTextContent('2,190,000');
    expect(screen.getByTestId('ledger-called-off')).toHaveTextContent('310,000');
    expect(screen.getAllByTestId('ledger-entry')).toHaveLength(1);
    expect(mocked.getLedger.mock.calls[0]![0]).toBe('fw1');
  });

  it('says the remaining value cannot be determined instead of showing a number', async () => {
    mocked.getLedger.mockResolvedValue({ ...ledger, remaining_value: null, remaining_known: false, unconverted_entries: 1 });
    view();
    fireEvent.click(screen.getByTestId('framework-ledger-toggle'));
    expect(await screen.findByTestId('ledger-remaining')).toHaveTextContent('cannot be determined');
    expect(screen.getByTestId('ledger-unconverted')).toBeInTheDocument();
    expect(screen.queryByTestId('ledger-incomplete')).toBeNull();
  });

  it('warns when a source of call-offs could not be read', async () => {
    mocked.getLedger.mockResolvedValue({ ...ledger, remaining_value: null, remaining_known: false, complete: false });
    view();
    fireEvent.click(screen.getByTestId('framework-ledger-toggle'));
    expect(await screen.findByTestId('ledger-incomplete')).toBeInTheDocument();
  });

  it('asks before closing an agreement for good', async () => {
    mocked.setFrameworkState.mockResolvedValue(framework as never);
    view();
    fireEvent.click(screen.getByTestId('framework-move-terminated'));
    expect(mocked.setFrameworkState).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('framework-close-yes'));
    await waitFor(() => expect(mocked.setFrameworkState).toHaveBeenCalledWith('fw1', 'terminated'));
  });

  it('offers the moves the server lists for the agreement, and no others', () => {
    view([{ ...framework, can: { edit: yes, transitions: ['terminated'] } }]);
    expect(screen.getByTestId('framework-move-terminated')).toBeInTheDocument();
    expect(screen.queryByTestId('framework-move-exhausted')).toBeNull();
    expect(screen.queryByTestId('framework-move-expired')).toBeNull();
  });

  it('closes every write for who does not own the agreements, with the reason', () => {
    view([{ ...framework, can: { edit: denied('not_framework_owner'), transitions: [] } }], { canCreate: denied('permission_denied') });
    expect(screen.getByTestId('framework-add')).toBeDisabled();
    expect(screen.getByTestId('framework-edit')).toBeDisabled();
    expect(screen.queryByTestId('framework-move-terminated')).toBeNull();
    // The call-offs stay readable.
    expect(screen.getByTestId('framework-ledger-toggle')).toBeEnabled();
  });

  it('shows the reason when the server refuses the move', async () => {
    mocked.setFrameworkState.mockRejectedValue(refusal(403, 'permission_denied'));
    view();
    fireEvent.click(screen.getByTestId('framework-move-exhausted'));
    expect(await screen.findByTestId('refusal-box')).toHaveAttribute('data-code', 'permission_denied');
  });

  it('creates an agreement with its ceiling as a string', async () => {
    mocked.createFramework.mockResolvedValue(framework as never);
    const props = view([]);
    fireEvent.click(screen.getByTestId('framework-add'));
    expect(screen.getByTestId('framework-save')).toBeDisabled();
    const type = (id: string, value: string) => fireEvent.change(document.getElementById(id) as HTMLInputElement, { target: { value } });
    type('fw-code', ' FW-02 ');
    type('fw-title', 'Scaffolding framework');
    type('fw-max', '750000');
    type('fw-currency', 'eur');
    type('fw-start', '2026-11-01');
    type('fw-end', '2028-10-31');
    fireEvent.click(screen.getByTestId('framework-save'));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    const body = mocked.createFramework.mock.calls[0]![0];
    expect(body).toMatchObject({ code: 'FW-02', max_value: '750000', currency: 'EUR', start_date: '2026-11-01', end_date: '2028-10-31' });
    expect(typeof body.max_value).toBe('string');
  });
});

describe('MarketSoundings', () => {
  const view = (soundings = [soundingTight], over: Partial<Parameters<typeof MarketSoundings>[0]> = {}) => {
    const props = { projectId: 'p1', soundings, can: { create: yes, edit: yes, delete: yes }, packages: [packageView()], labels, onChanged: vi.fn(), ...over };
    show(<MarketSoundings {...props} />);
    return props;
  };

  it('says what a market sounding is for and offers to record the first one', () => {
    view([]);
    expect(screen.getByTestId('market-soundings')).toBeInTheDocument();
    expect(screen.getByTestId('sounding-add')).toBeInTheDocument();
    expect(screen.queryByTestId('sounding-entry')).toBeNull();
  });

  it('flags a tight market that has no answer yet', () => {
    view();
    const entry = screen.getByTestId('sounding-entry');
    expect(entry).toHaveTextContent('Structural steel');
    expect(entry).toHaveTextContent('CP-01');
    expect(within(entry).getByTestId('sounding-unmitigated')).toBeInTheDocument();
  });

  it('does not flag a sounding the server counts as answered', () => {
    view([{ ...soundingTight, mitigation: 'Split the steel into two lots', unmitigated: false }]);
    expect(screen.queryByTestId('sounding-unmitigated')).toBeNull();
  });

  it('closes the writes for a viewer', () => {
    const off = denied('permission_denied');
    view([soundingTight], { can: { create: off, edit: off, delete: off } });
    for (const id of ['sounding-add', 'sounding-edit', 'sounding-remove']) expect(screen.getByTestId(id)).toBeDisabled();
  });

  it('asks before removing a sounding', async () => {
    mocked.deleteSounding.mockResolvedValue(undefined as never);
    const props = view();
    fireEvent.click(screen.getByTestId('sounding-remove'));
    expect(mocked.deleteSounding).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('sounding-remove-yes'));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    expect(mocked.deleteSounding).toHaveBeenCalledWith('p1', 'ms1');
  });

  it('names the companies asked once the reader opens the list', async () => {
    const base = matrix();
    const asked = base.items[0]!;
    mocked.listCandidates.mockResolvedValue(base);
    show(
      <MarketSoundings
        projectId="p1"
        soundings={[{ ...soundingTight, package_ids: ['k1'], participant_candidate_ids: [asked.id, 'gone'] }]}
        packages={[packageView()]}
        labels={labels}
        onChanged={vi.fn()}
      />,
    );
    const toggle = screen.getByTestId('sounding-participants-toggle');
    expect(toggle).toHaveTextContent('Companies asked: 2');
    expect(mocked.listCandidates).not.toHaveBeenCalled();
    fireEvent.click(toggle);
    const names = await screen.findByTestId('sounding-participant-names');
    expect(names).toHaveTextContent(asked.name);
    expect(names).toHaveTextContent('A company no longer among the candidates');
  });
});
