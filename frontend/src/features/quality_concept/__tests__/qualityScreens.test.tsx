// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The panels and their dialogs against fixtures: which buttons a state shows,
// what a form refuses to send, what goes to the server, and how a refusal reads.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';

vi.mock('react-i18next', async () => (await import('./i18nMock')).i18nMockModule);
vi.mock('@/features/teams/api', () => ({ listRoster: vi.fn(async () => ({ items: [], total: 0 })) }));
vi.mock('@/shared/ui/ProjectPeopleSelect', () => ({ ProjectPeopleSelect: () => null }));
vi.mock('../api', async (importOriginal) => (await import('./apiMock')).apiMock(importOriginal));

import { ApiError } from '@/shared/lib/api';

import * as api from '../api';
import type { CatalogueChoice, ExpertReport } from '../api';
import { MAY_SUBMIT, NOT_MANAGER, PLAN_CLOSED, SHELL, concept, matrix, page, progress, proof, unit } from './fixtures';
import { emptyProject, renderPage } from './harness';

const mocked = vi.mocked(api);

beforeEach(() => {
  vi.resetAllMocks();
  emptyProject(mocked);
});
afterEach(cleanup);

describe('concept tab', () => {
  it('keeps submit closed while the server says the concept is incomplete and lists why', async () => {
    mocked.getConcept.mockResolvedValue(
      concept({
        findings: [
          { code: 'standards_basis_missing', severity: 'error', ref: '', params: {} },
          { code: 'stage_without_owner', severity: 'warning', ref: 'factory_test', params: {} },
        ],
      }),
    );
    renderPage();
    expect(await screen.findByTestId('concept-submit')).toBeDisabled();
    expect(screen.getByTestId('concept-state')).toHaveTextContent('Draft');
    expect(screen.getByText('Open points: 1 stop the submission, 2 in all')).toBeInTheDocument();
    expect(screen.getByText('No standard is named yet')).toBeInTheDocument();
    expect(await screen.findByText('Stage Factory acceptance test has no owner')).toBeInTheDocument();
    expect(screen.getByTestId('concept-next-step')).toHaveTextContent('Clear the open points below');
    expect(screen.queryByTestId('plan-locked')).toBeNull();
  });

  it('submits when the server allows it and shows the refusal with every violation', async () => {
    mocked.getConcept.mockResolvedValue(concept({ can: MAY_SUBMIT }));
    mocked.submitConcept.mockRejectedValue(
      new ApiError(422, 'Unprocessable', {
        detail: {
          code: 'concept_incomplete',
          message: 'The concept is not complete.',
          violations: [{ code: 'package_without_proofs', severity: 'error', ref: 'pkg-shell', params: {} }],
        },
      }),
    );
    renderPage();
    fireEvent.click(await screen.findByTestId('concept-submit'));
    const note = await screen.findByTestId('refusal-note');
    expect(mocked.submitConcept).toHaveBeenCalledWith('p1');
    expect(note).toHaveTextContent('The concept is not complete.');
    expect(within(note).getByTestId('finding')).toHaveAttribute('data-code', 'package_without_proofs');
  });

  it('locks the plan in review and offers only the way back', async () => {
    mocked.getConcept.mockResolvedValue(concept({ state: 'in_review', revision_no: 1, can: PLAN_CLOSED }));
    mocked.conceptAction.mockResolvedValue(concept());
    renderPage();
    expect(await screen.findByTestId('plan-locked')).toBeInTheDocument();
    expect(screen.queryByTestId('concept-submit')).toBeNull();
    expect(screen.getByTestId('scope-edit')).toBeDisabled();
    fireEvent.click(screen.getByTestId('concept-return'));
    await waitFor(() => expect(mocked.conceptAction).toHaveBeenCalledWith('p1', 'return'));
  });

  it('offers no approval on this page in any state', async () => {
    mocked.getConcept.mockResolvedValue(concept({ state: 'approved', can: PLAN_CLOSED }));
    renderPage();
    expect(await screen.findByTestId('concept-next-step')).toHaveTextContent('The concept is approved.');
    expect(screen.queryByRole('button', { name: /approv|revis|reopen/i })).toBeNull();
    expect(screen.queryByTestId('concept-submit')).toBeNull();
    expect(screen.queryByTestId('concept-return')).toBeNull();
  });

  it('follows the server when the reader may not manage the plan', async () => {
    mocked.getConcept.mockResolvedValue(concept({ can: NOT_MANAGER }));
    renderPage();
    expect(await screen.findByTestId('concept-submit')).toBeDisabled();
    expect(screen.getByTestId('concept-next-step')).toHaveTextContent(
      'Only a manager or the owner of the quality area can submit the concept.',
    );
    expect(screen.getByTestId('plan-locked')).toHaveTextContent('can change the plan');
    expect(screen.getByTestId('scope-edit')).toBeDisabled();
    expect(await screen.findByTestId('standard-add')).toBeDisabled();
  });

  it('creates the handover documents of the chosen set and says how many', async () => {
    mocked.getConcept.mockResolvedValue(concept({ documentation_set_code: 'residential' }));
    mocked.applyDocumentationSet.mockResolvedValue({ slots_added: ['om_manual', 'warranties'], fm_data_added: ['asset_dataset'] });
    renderPage();
    fireEvent.click(await screen.findByTestId('documentation-set-apply'));
    expect(await screen.findByTestId('documentation-set-applied')).toHaveTextContent(
      'Handover documents and data deliverables created: 3',
    );
    expect(mocked.applyDocumentationSet).toHaveBeenCalledWith('p1');
  });

  it('keeps that step closed until a set is chosen', async () => {
    renderPage();
    expect(await screen.findByTestId('documentation-set-apply')).toBeDisabled();
  });

  it('refuses a package scope with a repeated reference and saves a clean one', async () => {
    mocked.patchConcept.mockResolvedValue(concept());
    renderPage();
    fireEvent.click(await screen.findByTestId('scope-edit'));
    fireEvent.click(screen.getByTestId('package-add'));
    const refs = screen.getAllByTestId('package-ref');
    fireEvent.change(refs[0]!, { target: { value: 'pkg-shell' } });
    fireEvent.change(refs[1]!, { target: { value: 'pkg-shell' } });
    expect(screen.getByTestId('form-problem')).toHaveTextContent('A package reference appears twice');
    expect(screen.getByTestId('form-submit')).toBeDisabled();

    fireEvent.change(refs[1]!, { target: { value: 'pkg-roof' } });
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.patchConcept).toHaveBeenCalled());
    expect(mocked.patchConcept.mock.calls[0]![1]).toEqual({
      packages: [
        { ref: 'pkg-shell', code: '', title: '', no_proofs_rationale: '' },
        { ref: 'pkg-roof', code: '', title: '', no_proofs_rationale: '' },
      ],
      holidays: [],
    });
  });
});

describe('proofs tab', () => {
  it('sends the reader to name the packages first', async () => {
    renderPage('proofs');
    expect(await screen.findByText('No proofs planned yet')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Name the packages' }));
    expect(await screen.findByTestId('concept-panel')).toBeInTheDocument();
  });

  it('accepts a delivered proof and never an open one', async () => {
    mocked.getConcept.mockResolvedValue(concept({ packages: [SHELL], applicable_packages: [SHELL] }));
    mocked.listProofs.mockResolvedValue(
      page([proof({ id: 'open' }), proof({ id: 'done', state: 'delivered', counted: 1 })]),
    );
    mocked.proofAction.mockResolvedValue(proof());
    renderPage('proofs');
    const rows = await screen.findAllByTestId('proof-entry');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).queryByTestId('proof-action-accept')).toBeNull();
    expect(within(rows[0]!).getByText('Pressure test')).toBeInTheDocument();
    fireEvent.click(within(rows[1]!).getByTestId('proof-action-accept'));
    await waitFor(() => expect(mocked.proofAction).toHaveBeenCalledWith('p1', 'done', 'accept'));
  });

  it('asks for a reason before a waiver is requested', async () => {
    mocked.listProofs.mockResolvedValue(page([proof()]));
    mocked.requestWaiver.mockResolvedValue(proof());
    renderPage('proofs');
    fireEvent.click(await screen.findByTestId('proof-action-request_waiver'));
    expect(screen.getByTestId('form-submit')).toBeDisabled();
    fireEvent.change(screen.getByTestId('waiver-reason'), { target: { value: ' Not part of this contract ' } });
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.requestWaiver).toHaveBeenCalledWith('p1', 'pr1', 'Not part of this contract'));
  });

  it('turns a requested waiver into a decision', async () => {
    mocked.listProofs.mockResolvedValue(page([proof({ requested_by: 'u2', decision_rationale: 'Out of scope' })]));
    mocked.decideWaiver.mockResolvedValue(proof());
    renderPage('proofs');
    expect(await screen.findByTestId('waiver-pending')).toHaveTextContent('Waiver requested: Out of scope');
    expect(screen.queryByTestId('proof-action-request_waiver')).toBeNull();
    fireEvent.click(screen.getByTestId('proof-action-approve_waiver'));
    await waitFor(() => expect(mocked.decideWaiver).toHaveBeenCalledWith('p1', 'pr1', true));
  });
});

describe('stages tab', () => {
  it('says what a blocked stage waits for', async () => {
    mocked.getStageMatrix.mockResolvedValue(matrix([progress()]));
    renderPage('stages');
    fireEvent.click(await screen.findByTestId('matrix-cell'));
    const detail = screen.getByTestId('stage-detail');
    expect(detail).toHaveTextContent('Ventilation plant: Factory acceptance test');
    expect(within(detail).getByTestId('precondition')).toHaveAttribute('data-met', 'false');
    expect(detail).toHaveTextContent('Required proofs delivered');
    expect(detail).toHaveTextContent('Proofs are still missing');
    expect(within(detail).queryByTestId('stage-action-open_test')).toBeNull();
    expect(within(detail).queryByTestId('stage-action-request_release')).toBeNull();
  });

  it('asks for the release of a passed stage and says where it is decided', async () => {
    mocked.getStageMatrix.mockResolvedValue(
      matrix([progress({ state: 'passed', computed_state: 'passed', preconditions: [] })]),
    );
    mocked.requestStageRelease.mockResolvedValue({
      progress_id: 'sp1',
      hold_gate: { id: 'g1', gate_number: 4, required_party_role: 'qa', status: 'open' },
    });
    renderPage('stages');
    fireEvent.click(await screen.findByTestId('matrix-cell'));
    fireEvent.click(screen.getByTestId('stage-action-request_release'));
    const note = await screen.findByTestId('release-requested');
    expect(mocked.requestStageRelease).toHaveBeenCalledWith('p1', 'sp1');
    expect(note).toHaveTextContent('Client quality assurance');
  });

  it('shows an unreadable precondition as not applicable, never as passed', async () => {
    mocked.getStageMatrix.mockResolvedValue(
      matrix([
        progress({
          preconditions: [
            { code: 'plant_item_delivered', met: true, reason: 'no_plant_register', params: { not_applicable: true } },
          ],
        }),
      ]),
    );
    renderPage('stages');
    fireEvent.click(await screen.findByTestId('matrix-cell'));
    const row = screen.getByTestId('precondition');
    expect(row).toHaveAttribute('data-met', 'not-applicable');
    expect(row).toHaveTextContent('Equipment delivered');
    expect(row).toHaveTextContent('Not applicable');
    expect(row).toHaveTextContent('No equipment register is installed');
  });

  it('brings a stage back that was marked not applicable', async () => {
    mocked.getStageMatrix.mockResolvedValue(
      matrix([progress({ state: 'not_applicable', computed_state: 'not_applicable', rationale: 'Bought as a unit' })]),
    );
    mocked.reinstateStage.mockResolvedValue(progress());
    renderPage('stages');
    fireEvent.click(await screen.findByTestId('matrix-cell'));
    expect(screen.getByTestId('stage-detail')).toHaveTextContent('Bought as a unit');
    fireEvent.click(screen.getByTestId('stage-action-reinstate'));
    await waitFor(() => expect(mocked.reinstateStage).toHaveBeenCalledWith('p1', 'sp1'));
  });

  it('wants a reason before a stage is marked not applicable', async () => {
    mocked.getStageMatrix.mockResolvedValue(matrix([progress()]));
    mocked.markStageNotApplicable.mockResolvedValue(progress());
    renderPage('stages');
    fireEvent.click(await screen.findByTestId('matrix-cell'));
    fireEvent.click(screen.getByTestId('stage-action-not_applicable'));
    expect(screen.getByTestId('form-submit')).toBeDisabled();
    fireEvent.change(screen.getByTestId('stage-na-reason'), { target: { value: 'No factory test for this plant' } });
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() =>
      expect(mocked.markStageNotApplicable).toHaveBeenCalledWith('p1', 'sp1', 'No factory test for this plant'),
    );
  });
});

describe('acceptance tab', () => {
  it('explains the screen while nothing is planned', async () => {
    renderPage('acceptance');
    expect(await screen.findByText('No acceptance planned yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add acceptance unit' })).toBeInTheDocument();
  });

  it('requests an acceptance with the open points carried as reservations', async () => {
    mocked.listUnits.mockResolvedValue(page([unit({ unmet: [{ kind: 'defects', ref: 'd1' }] })]));
    mocked.requestAcceptance.mockResolvedValue(unit({ state: 'requested' }));
    renderPage('acceptance');
    const card = await screen.findByTestId('acceptance-unit');
    expect(within(card).getByTestId('unit-state')).toHaveTextContent('Planned');
    expect(within(card).queryByRole('button', { name: /^accept$/i })).toBeNull();
    fireEvent.click(within(card).getByTestId('unit-action-request'));
    const dialog = screen.getByTestId('unit-request-dialog');
    expect(dialog).toHaveTextContent('Open defect');
    fireEvent.click(screen.getByTestId('request-with-reservations'));
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.requestAcceptance).toHaveBeenCalledWith('p1', 'u1', true));
  });

  it('shows the reason of the server inside the dialog when a request is refused', async () => {
    mocked.listUnits.mockResolvedValue(page([unit()]));
    mocked.requestAcceptance.mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: {
          code: 'acceptance_preconditions_unmet',
          message_key: 'quality_concept.errors.acceptance_preconditions_unmet',
          message: 'Server text',
        },
      }),
    );
    renderPage('acceptance');
    fireEvent.click(await screen.findByTestId('unit-action-request'));
    fireEvent.click(screen.getByTestId('form-submit'));
    expect(await screen.findByTestId('refusal-note')).toHaveTextContent(
      'Acceptance cannot be requested: preconditions are not met.',
    );
    expect(screen.getByTestId('unit-request-dialog')).toBeInTheDocument();
  });

  it('offers an effect again once its confirmation was revoked', async () => {
    const revoked = {
      id: 'e1',
      unit_id: 'u1',
      effect: 'risk_transfer',
      effective_date: '2027-03-02',
      source_url: null,
      review_status: 'unconfirmed',
      confirmed_by: 'u9',
      confirmed_at: '2027-03-03T08:00:00Z',
      outcome: { revoked_at: '2027-03-05T08:00:00Z' },
    };
    mocked.listUnits.mockResolvedValue(
      page([
        unit({
          state: 'accepted',
          effects_applied: [revoked],
          effects_proposed: [{ effect: 'risk_transfer', review_status: 'unconfirmed' }],
        }),
      ]),
    );
    renderPage('acceptance');
    expect(await screen.findByTestId('effect-proposed')).toHaveTextContent('Risk passes to the client');
    expect(screen.queryByTestId('effect-applied')).toBeNull();
  });

  it('lets an accepted unit confirm what the regime proposes, one effect at a time', async () => {
    mocked.listUnits.mockResolvedValue(
      page([
        unit({
          state: 'accepted',
          accepted_on: '2027-03-02',
          effects_proposed: [{ effect: 'risk_transfer', review_status: 'unconfirmed' }],
        }),
      ]),
    );
    mocked.confirmEffect.mockResolvedValue({
      id: 'e1',
      unit_id: 'u1',
      effect: 'risk_transfer',
      effective_date: '2027-03-02',
      source_url: null,
      review_status: 'unconfirmed',
      confirmed_by: 'u9',
      confirmed_at: '2027-03-03T08:00:00Z',
      outcome: {},
    });
    renderPage('acceptance');
    const row = await screen.findByTestId('effect-proposed');
    expect(row).toHaveTextContent('Risk passes to the client');
    expect(screen.queryByTestId('unit-action-request')).toBeNull();
    fireEvent.click(within(row).getByTestId('effect-confirm'));
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.confirmEffect).toHaveBeenCalled());
    expect(mocked.confirmEffect.mock.calls[0]![2]).toMatchObject({ effect: 'risk_transfer' });
  });
});

describe('a reader who may not manage the plan', () => {
  beforeEach(() => {
    mocked.getConcept.mockResolvedValue(concept({ can: NOT_MANAGER }));
  });

  it('can request an acceptance and record dates, and nothing that changes the plan', async () => {
    mocked.listUnits.mockResolvedValue(page([unit({ state: 'requested' }), unit({ id: 'u2', code: 'AU-2' })]));
    renderPage('acceptance');
    const cards = await screen.findAllByTestId('acceptance-unit');
    expect(screen.getByTestId('unit-add')).toBeDisabled();
    expect(within(cards[0]!).getByTestId('unit-action-record_dates')).toBeEnabled();
    expect(within(cards[0]!).getByTestId('unit-action-refuse')).toBeDisabled();
    expect(within(cards[0]!).getByTestId('unit-action-schedule_inspection')).toBeDisabled();
    expect(within(cards[0]!).getByTestId('unit-action-withdraw')).toBeDisabled();
    expect(within(cards[1]!).getByTestId('unit-action-request')).toBeEnabled();
  });

  it('gets no add button on an empty acceptance plan', async () => {
    renderPage('acceptance');
    expect(await screen.findByText('No acceptance planned yet')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add acceptance unit' })).toBeNull();
  });

  it('can run a stage test but not take the stage out of the plan', async () => {
    mocked.getStageMatrix.mockResolvedValue(
      matrix([progress({ state: 'ready', computed_state: 'ready', preconditions: [] })]),
    );
    renderPage('stages');
    fireEvent.click(await screen.findByTestId('matrix-cell'));
    expect(screen.getByTestId('stage-action-open_test')).toBeEnabled();
    expect(screen.getByTestId('stage-action-not_applicable')).toBeDisabled();
    expect(screen.getByTestId('stage-depends')).toBeDisabled();
  });

  it('is not offered the catalogue stages on an empty stage plan', async () => {
    renderPage('stages');
    expect(await screen.findByText('No commissioning stages yet')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Use the catalogue stages' })).toBeNull();
  });

  it('cannot add a certification target', async () => {
    renderPage('certification');
    expect(await screen.findByText('No certification target')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add certification target' })).toBeNull();
  });
});

describe('capability flags of a record', () => {
  it('closes the waiver decision for the person who asked, and says why', async () => {
    mocked.listProofs.mockResolvedValue(
      page([
        proof({
          requested_by: 'u2',
          decision_rationale: 'Out of scope',
          can: { decide_waiver: false, edit: true, delete: true },
          can_reason: { decide_waiver: 'approver_is_requester' },
        }),
      ]),
    );
    renderPage('proofs');
    const approve = await screen.findByTestId('proof-action-approve_waiver');
    expect(approve).toBeDisabled();
    expect(screen.getByTestId('proof-action-reject_waiver')).toBeDisabled();
    expect(approve.getAttribute('title')).toBeTruthy();
    expect(approve.getAttribute('title')).not.toContain('quality_concept.');
  });

  it('lets the flag of the record win over what the concept allows', async () => {
    mocked.listUnits.mockResolvedValue(
      page([unit({ can: { request: false, record_dates: true, edit: false, delete: false }, can_reason: { request: 'edit_required' } })]),
    );
    renderPage('acceptance');
    const card = await screen.findByTestId('acceptance-unit');
    expect(within(card).getByTestId('unit-action-request')).toBeDisabled();
    expect(within(card).getByTestId('unit-action-record_dates')).toBeEnabled();
  });

  it('opens an action for a reader the concept flags would have stopped', async () => {
    mocked.getConcept.mockResolvedValue(concept({ can: NOT_MANAGER }));
    mocked.getStageMatrix.mockResolvedValue(
      matrix([progress({ state: 'ready', computed_state: 'ready', preconditions: [], can: { open_test: true, not_applicable: true } })]),
    );
    renderPage('stages');
    fireEvent.click(await screen.findByTestId('matrix-cell'));
    expect(screen.getByTestId('stage-action-not_applicable')).toBeEnabled();
  });

  it('names the record a finding points at', async () => {
    mocked.getConcept.mockResolvedValue(
      concept({
        findings: [{ code: 'proof_without_deliverer', severity: 'error', ref: 'pr1', params: {}, label: 'Pressure test, shell' }],
      }),
    );
    renderPage();
    expect(await screen.findByTestId('finding')).toBeInTheDocument();
    expect(screen.queryByText(/pr1/)).toBeNull();
  });
});

describe('expert reports', () => {
  it('offers trigger and frequency from the vocabulary and sends the codes', async () => {
    mocked.createExpertReport.mockResolvedValue({
      id: 'x1',
      subject: 'Facade',
      expert_contact_id: null,
      trigger: 'before_acceptance',
      frequency: 'once',
      due_dates: [],
      commitment_ref: null,
      state: 'planned',
    });
    renderPage('preservation');
    fireEvent.click(await screen.findByTestId('report-add'));
    fireEvent.change(screen.getByTestId('report-subject'), { target: { value: 'Facade' } });
    fireEvent.change(screen.getByTestId('report-trigger'), { target: { value: 'before_acceptance' } });
    fireEvent.change(screen.getByTestId('report-frequency'), { target: { value: 'once' } });
    expect(within(screen.getByTestId('report-frequency')).getByText('Once')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.createExpertReport).toHaveBeenCalled());
    expect(mocked.createExpertReport.mock.calls[0]![1]).toMatchObject({
      subject: 'Facade',
      trigger: 'before_acceptance',
      frequency: 'once',
    });
  });
});

describe('listings to choose from', () => {
  const choice = (over: Partial<CatalogueChoice> = {}): CatalogueChoice => ({
    kind: 'quality',
    source: 'shipped',
    id: 'cat-1',
    code: 'base',
    name: { key: null, text: { en: 'Base catalogue' } },
    state: 'active',
    versions: [1],
    latest_version: 1,
    review_status: null,
    jurisdiction_countries: [],
    default: true,
    pinned: true,
    ...over,
  });

  it('pins the catalogue the reader picks, with its source and latest version', async () => {
    mocked.listCatalogues.mockResolvedValue({
      ...page([
        choice(),
        choice({ source: 'pack', id: 'cat-2', code: 'pack', name: { key: null, text: { en: 'Pack catalogue' } }, versions: [1, 2, 3], latest_version: 3, default: false, pinned: false }),
      ]),
      can: { pin: true },
    });
    mocked.pinCatalogue.mockResolvedValue(concept());
    renderPage();
    fireEvent.click(await screen.findByTestId('catalogue-change'));
    expect(screen.getByText('Pack catalogue')).toBeInTheDocument();
    expect(screen.getByTestId('form-submit')).toBeDisabled();
    fireEvent.click(screen.getAllByTestId('catalogue-choice')[1]!);
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.pinCatalogue).toHaveBeenCalled());
    expect(mocked.pinCatalogue.mock.calls[0]![1]).toEqual({
      catalogue_source: 'pack',
      catalogue_id: 'cat-2',
      catalogue_version: 3,
    });
  });

  it('does not offer the change to a reader who may not pin', async () => {
    mocked.listCatalogues.mockResolvedValue({ ...page([choice()]), can: { pin: false } });
    renderPage();
    await screen.findByTestId('concept-state');
    await waitFor(() => expect(mocked.listCatalogues).toHaveBeenCalled());
    expect(screen.queryByTestId('catalogue-change')).toBeNull();
  });

  it('sends the contact the reader picked for an expert report', async () => {
    mocked.listOptions.mockResolvedValue({ ...page([{ id: 'c1', label: 'Structural expert' }]), available: true, reason: null });
    mocked.createExpertReport.mockResolvedValue({
      id: 'x1',
      subject: 'Facade',
      expert_contact_id: 'c1',
      trigger: '',
      frequency: '',
      due_dates: [],
      commitment_ref: null,
      state: 'planned',
    });
    renderPage('preservation');
    fireEvent.click(await screen.findByTestId('report-add'));
    fireEvent.change(screen.getByTestId('report-subject'), { target: { value: 'Facade' } });
    await screen.findByText('Structural expert');
    expect(mocked.listOptions.mock.calls[0]!.slice(0, 2)).toEqual(['p1', 'contact']);
    fireEvent.change(screen.getByTestId('report-expert'), { target: { value: 'c1' } });
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.createExpertReport).toHaveBeenCalled());
    expect(mocked.createExpertReport.mock.calls[0]![1]).toMatchObject({ subject: 'Facade', expert_contact_id: 'c1' });
  });

  it('leaves a reference out of the request when the reader did not touch it', async () => {
    mocked.createExpertReport.mockResolvedValue({
      id: 'x1',
      subject: 'Facade',
      expert_contact_id: null,
      trigger: '',
      frequency: '',
      due_dates: [],
      commitment_ref: null,
      state: 'planned',
    });
    renderPage('preservation');
    fireEvent.click(await screen.findByTestId('report-add'));
    fireEvent.change(screen.getByTestId('report-subject'), { target: { value: 'Facade' } });
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.createExpertReport).toHaveBeenCalled());
    expect(mocked.createExpertReport.mock.calls[0]![1]).not.toHaveProperty('expert_contact_id');
  });

  it('takes a typed reference and says why when no list can be offered', async () => {
    mocked.listOptions.mockResolvedValue({ ...page([]), available: false, reason: 'plant_listing_unavailable' });
    renderPage('preservation');
    fireEvent.click(await screen.findByTestId('report-add'));
    await waitFor(() => expect(screen.getByTestId('report-expert').tagName).toBe('INPUT'));
    expect(screen.getByText('The plant register offers no list to choose from in this installation.')).toBeInTheDocument();
    expect(screen.queryByText(/quality_concept\./)).toBeNull();
  });
});

describe('stored evidence links', () => {
  it('names the linked record and closes linking when the record says so', async () => {
    mocked.listProofs.mockResolvedValue(
      page([proof({ can: { link_evidence: false, edit: true }, can_reason: { link_evidence: 'edit_required' } })]),
    );
    mocked.listLinks.mockResolvedValue(
      page([
        {
          id: 'l1',
          owner_kind: 'proof',
          owner_id: 'pr1',
          link_kind: 'cc_inspection',
          link_id: 'i1',
          retest_of: null,
          note: '',
          label: 'Pressure test 12',
          exists: true,
        },
      ]),
    );
    mocked.listCandidates.mockResolvedValue(page([]));
    renderPage('proofs');
    fireEvent.click(await screen.findByTestId('proof-links-toggle'));
    expect(await screen.findByText('Pressure test 12')).toBeInTheDocument();
    expect(screen.getByTestId('evidence-add').getAttribute('title')).toBeTruthy();
    const remove = screen.getByRole('button', { name: 'Remove link' });
    expect(remove).toBeDisabled();
    expect(remove.getAttribute('title')).toBeTruthy();
    expect(remove.getAttribute('title')).not.toContain('quality_concept.');
  });
});

describe('what the server names', () => {
  it('shows the frame document the concept is bound to', async () => {
    mocked.getConcept.mockResolvedValue(
      concept({ governance_document: { id: 'g1', code: 'QC-1', label: { key: null, text: { en: 'Quality frame' } }, status: 'draft' } }),
    );
    renderPage();
    expect((await screen.findByTestId('concept-frame-document')).textContent).toContain('Quality frame');
  });
});

describe('gate, retests and names', () => {
  it('says why the governance gate cannot read the concept and what to do', async () => {
    mocked.getReadiness.mockResolvedValue({
      concept: true,
      approved: false,
      errors: [],
      preservation_unplanned: [],
      gate_detail: 'quality_frame_document_missing',
    });
    renderPage();
    const note = await screen.findByTestId('gate-detail');
    expect(note.textContent).toContain('add the quality concept to the frame documents');
    expect(note.textContent).not.toContain('quality_frame_document_missing');
  });

  it('links a record as the retest of an earlier one', async () => {
    mocked.listProofs.mockResolvedValue(page([proof()]));
    mocked.listLinks.mockResolvedValue(
      page([
        {
          id: 'l1',
          owner_kind: 'proof',
          owner_id: 'pr1',
          link_kind: 'cc_test_result',
          link_id: 't1',
          retest_of: null,
          note: '',
          label: 'Pressure test 12',
          exists: true,
        },
        {
          id: 'l2',
          owner_kind: 'proof',
          owner_id: 'pr1',
          link_kind: 'cc_test_result',
          link_id: 't2',
          retest_of: 'l1',
          note: '',
          label: 'Pressure test 13',
          exists: true,
        },
      ]),
    );
    mocked.listCandidates.mockResolvedValue(page([{ id: 't3', label: 'Pressure test 14' }]));
    mocked.addLink.mockResolvedValue({
      id: 'l3',
      owner_kind: 'proof',
      owner_id: 'pr1',
      link_kind: 'cc_test_result',
      link_id: 't3',
      retest_of: 'l2',
      note: '',
    });
    renderPage('proofs');
    fireEvent.click(await screen.findByTestId('proof-links-toggle'));
    expect((await screen.findByTestId('evidence-retest')).textContent).toBe('Retest of Pressure test 12');
    await screen.findByText('Pressure test 14');
    fireEvent.change(screen.getByTestId('evidence-candidate'), { target: { value: 't3' } });
    fireEvent.change(screen.getByTestId('evidence-retest-of'), { target: { value: 'l2' } });
    fireEvent.click(screen.getByTestId('evidence-add'));
    await waitFor(() => expect(mocked.addLink).toHaveBeenCalled());
    expect(mocked.addLink.mock.calls[0]![1]).toMatchObject({ link_id: 't3', retest_of: 'l2' });
  });

  it('asks before a link is removed and removes nothing until confirmed', async () => {
    mocked.listProofs.mockResolvedValue(page([proof()]));
    mocked.listLinks.mockResolvedValue(
      page([
        {
          id: 'l1',
          owner_kind: 'proof',
          owner_id: 'pr1',
          link_kind: 'cc_test_result',
          link_id: 't1',
          retest_of: null,
          note: '',
          label: 'Pressure test 12',
          exists: true,
        },
      ]),
    );
    mocked.listCandidates.mockResolvedValue(page([]));
    mocked.removeLink.mockResolvedValue(undefined);
    renderPage('proofs');
    fireEvent.click(await screen.findByTestId('proof-links-toggle'));
    await screen.findByText('Pressure test 12');
    fireEvent.click(screen.getByRole('button', { name: 'Remove link' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Remove this link?');
    expect(mocked.removeLink).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove link' }));
    await waitFor(() => expect(mocked.removeLink).toHaveBeenCalledWith('p1', 'l1'));
  });

  it('names who asked for a waiver', async () => {
    mocked.listProofs.mockResolvedValue(
      page([proof({ requested_by: 'u2', requested_by_name: 'Site manager one', decision_rationale: 'Out of scope' })]),
    );
    renderPage('proofs');
    const line = await screen.findByTestId('waiver-pending');
    expect(line.textContent).toBe('Waiver requested by Site manager one: Out of scope');
  });
});

describe('the reason of a closed button', () => {
  it('is written out beside the buttons, once per reason', async () => {
    mocked.listUnits.mockResolvedValue(
      page([
        unit({
          can: { request: false, edit: false, delete: false, record_dates: true },
          can_reason: { request: 'edit_required', edit: 'manage_required', delete: 'manage_required' },
        }),
      ]),
    );
    renderPage('acceptance');
    const card = await screen.findByTestId('acceptance-unit');
    const note = within(card).getByTestId('closed-reason');
    expect(note.textContent).toContain('Only a manager or the owner of the quality area can change the plan.');
    expect(note.querySelectorAll('span')).toHaveLength(2);
    expect(note.textContent).not.toContain('quality_concept.');
  });

  it('is absent when nothing is closed', async () => {
    mocked.listUnits.mockResolvedValue(page([unit({ can: { request: true, edit: true, delete: true }, can_reason: {} })]));
    renderPage('acceptance');
    const card = await screen.findByTestId('acceptance-unit');
    expect(within(card).queryByTestId('closed-reason')).toBeNull();
  });
});

describe('a reason every row shares', () => {
  const closed = { can: { edit: false, delete: false }, can_reason: { edit: 'edit_required', delete: 'edit_required' } };

  it('is written once above the list and left off the rows', async () => {
    mocked.listUnits.mockResolvedValue(page([unit(closed), unit({ id: 'u2', code: 'AU-2', ...closed })]));
    renderPage('acceptance');
    const cards = await screen.findAllByTestId('acceptance-unit');
    expect(cards).toHaveLength(2);
    expect(screen.getAllByText('You need the permission to edit quality records for this.')).toHaveLength(1);
    expect(screen.getByTestId('closed-reason-shared')).toBeInTheDocument();
    expect(within(cards[0]!).queryByTestId('closed-reason')).toBeNull();
  });

  it('keeps a reason on its row when the rows differ', async () => {
    mocked.listUnits.mockResolvedValue(
      page([
        unit(closed),
        unit({ id: 'u2', code: 'AU-2', can: { edit: false, delete: true }, can_reason: { edit: 'manage_required' } }),
      ]),
    );
    renderPage('acceptance');
    const cards = await screen.findAllByTestId('acceptance-unit');
    expect(screen.queryByTestId('closed-reason-shared')).toBeNull();
    expect(within(cards[0]!).getByTestId('closed-reason').textContent).toContain('You need the permission');
    expect(within(cards[1]!).getByTestId('closed-reason').textContent).toContain('Only a manager');
  });

  it('says beside the packages button why the plan is closed', async () => {
    mocked.getConcept.mockResolvedValue(concept({ can: NOT_MANAGER }));
    renderPage();
    const note = await screen.findByTestId('scope-closed-reason');
    expect(note.textContent).toBe('Only a manager or the owner of the quality area can change the plan.');
    expect(screen.getByTestId('scope-edit')).toBeDisabled();
  });
});

describe('a list without a shared reason', () => {
  const report = (id: string, over: Partial<ExpertReport> = {}): ExpertReport => ({
    id,
    subject: `Report ${id}`,
    expert_contact_id: null,
    trigger: '',
    frequency: '',
    due_dates: [],
    commitment_ref: null,
    state: 'planned',
    ...over,
  });

  it('has exactly as many items as rows', async () => {
    mocked.listExpertReports.mockResolvedValue(
      page([report('x1'), report('x2', { can: { edit: false }, can_reason: { edit: 'manage_required' } })]),
    );
    renderPage('preservation');
    const list = await screen.findByTestId('report-list');
    expect(list.children).toHaveLength(2);
    expect(screen.queryByTestId('closed-reason-shared')).toBeNull();
  });

  it('gains one item for the reason when every row shares it', async () => {
    const closed = { can: { edit: false, delete: false }, can_reason: { edit: 'manage_required', delete: 'manage_required' } };
    mocked.listExpertReports.mockResolvedValue(page([report('x1', closed), report('x2', closed)]));
    renderPage('preservation');
    const list = await screen.findByTestId('report-list');
    expect(list.children).toHaveLength(3);
    expect(within(list).getAllByText('Only a manager or the owner of the quality area can change the plan.')).toHaveLength(1);
  });
});

describe('after a refused write', () => {
  it('reads the concept again, because the refusal can mean it moved', async () => {
    mocked.submitConcept.mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: {
          code: 'binding_requires_change_request',
          message_key: 'quality_concept.errors.binding_requires_change_request',
          message: 'The concept is binding; change it through a change request of the frame document.',
        },
      }),
    );
    mocked.getConcept.mockResolvedValue(concept({ can: MAY_SUBMIT }));
    renderPage();
    fireEvent.click(await screen.findByTestId('concept-submit'));
    await waitFor(() => expect(mocked.submitConcept).toHaveBeenCalled());
    await waitFor(() => expect(mocked.getConcept.mock.calls.length).toBeGreaterThan(1));
  });
});

describe('a project without gates', () => {
  const HERE = { approve_applies: true, approve: true, approve_reason: null, reopen_applies: true, reopen: true, reopen_reason: null };

  it('approves a submitted concept on its own page and says the project uses no gates', async () => {
    mocked.getConcept.mockResolvedValue(concept({ state: 'in_review', gates_in_use: false, can: { ...PLAN_CLOSED, ...HERE } }));
    mocked.approveConcept.mockResolvedValue(concept({ state: 'binding', gates_in_use: false }));
    renderPage();
    expect((await screen.findByTestId('concept-next-step')).textContent).toContain('does not use gates');
    expect(screen.queryByTestId('concept-reopen')).toBeNull();
    fireEvent.click(screen.getByTestId('concept-approve'));
    await waitFor(() => expect(mocked.approveConcept).toHaveBeenCalledWith('p1'));
  });

  it('closes the approval for the person who submitted, with the reason written out', async () => {
    mocked.getConcept.mockResolvedValue(
      concept({
        state: 'in_review',
        gates_in_use: false,
        can: { ...PLAN_CLOSED, ...HERE, approve: false, approve_reason: 'approver_is_submitter' },
      }),
    );
    renderPage();
    expect(await screen.findByTestId('concept-approve')).toBeDisabled();
    expect(screen.getByTestId('concept-closed-reason').textContent).toBe(
      'Whoever submitted the quality concept cannot approve it. A second person who may manage the quality concept must approve it.',
    );
  });

  it('reopens a binding concept only with a reason', async () => {
    mocked.getConcept.mockResolvedValue(concept({ state: 'binding', gates_in_use: false, can: { ...PLAN_CLOSED, ...HERE } }));
    mocked.reopenConcept.mockResolvedValue(concept({ state: 'revising', gates_in_use: false }));
    renderPage();
    fireEvent.click(await screen.findByTestId('concept-reopen'));
    expect(screen.getByTestId('form-submit')).toBeDisabled();
    fireEvent.change(screen.getByTestId('reopen-reason'), { target: { value: 'Facade system changed' } });
    fireEvent.click(screen.getByTestId('form-submit'));
    await waitFor(() => expect(mocked.reopenConcept).toHaveBeenCalledWith('p1', { rationale: 'Facade system changed' }));
  });

  it('offers neither action where a gate decides', async () => {
    mocked.getConcept.mockResolvedValue(
      concept({ state: 'in_review', gates_in_use: true, can: { ...PLAN_CLOSED, approve_applies: false, reopen_applies: false } }),
    );
    renderPage();
    expect((await screen.findByTestId('concept-next-step')).textContent).toContain('governance gate');
    expect(screen.queryByTestId('concept-approve')).toBeNull();
    expect(screen.queryByTestId('concept-reopen')).toBeNull();
  });

  it('says who reopened a revision and why', async () => {
    mocked.listRevisions.mockResolvedValue(
      page([
        {
          id: 'r2',
          revision_no: 2,
          reason: 'reopened',
          created_by: 'u9',
          created_by_name: 'Project lead one',
          snapshot: { reopen_reason: 'Facade system changed' },
        },
      ]),
    );
    renderPage();
    const list = await screen.findByTestId('revision-list');
    expect(list.textContent).toContain('Reopened');
    expect(list.textContent).toContain('Project lead one');
    expect(list.textContent).toContain('Facade system changed');
  });
});

describe('a plan in force without gates', () => {
  it('says beside the packages button that the concept must be reopened', async () => {
    mocked.getConcept.mockResolvedValue(concept({ state: 'binding', gates_in_use: false, can: PLAN_CLOSED }));
    renderPage();
    expect((await screen.findByTestId('scope-closed-reason')).textContent).toBe(
      'The plan is in force. Reopen the quality concept with a reason to change it.',
    );
  });
});
