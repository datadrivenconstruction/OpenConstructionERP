// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The submittal register of a contractor that installs equipment has three
// questions put to it every week: what is with the reviewer and for how long,
// what came back without a release, and which long-lead items are running out
// of time. The server answers all three (the summary route, the derived
// figures on each row, the vocabulary of codes). These hold the page to
// showing those answers as sent:
//
// - a count on the strip opens the rows behind it, through the list route's
//   own filter where it has one;
// - the codes, their letters and the discipline list are the vocabulary
//   route's, so the fixtures below use letters and labels no default has;
// - days in review, days overdue and days late are the server's numbers. The
//   fixture dates are deliberately impossible for those numbers, so a screen
//   that subtracted dates would print something else;
// - a row from before any of this existed, in a project whose server does not
//   answer the summary, renders as it did.
//
// The page is rendered whole, so a control that is built but never mounted
// fails here too.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  downloadWithAuth: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), setOpen: vi.fn(), custom: [] }),
}));

vi.mock('@/features/approval-routes', () => ({
  ApprovalInstanceCard: () => null,
  ApprovalTargetBadge: () => null,
}));

import { SubmittalsPage } from './SubmittalsPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const PROJECT = { id: 'p-1', name: 'Data centre fit-out' };

/** A row as the server sent it before the register columns existed. */
const LEGACY = {
  id: 's-1',
  project_id: 'p-1',
  submittal_number: 'SUB-001',
  title: 'Cable tray shop drawings',
  spec_section: '26 05 36',
  submittal_type: 'shop_drawing',
  status: 'draft',
  ball_in_court: null,
  revision: 1,
  date_submitted: null,
  date_required: '2026-10-15',
  description: null,
  linked_boq_item_ids: [],
  metadata: {},
  created_by: null,
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-01T08:00:00Z',
};

/**
 * A long-lead chiller with the reviewer, past the review period and past the
 * date its approval was needed by. Submitted "in 2099", so any day count the
 * screen worked out from the dates would be zero or negative, not 25.
 */
const CHILLER = {
  ...LEGACY,
  id: 's-2',
  submittal_number: 'SUB-002',
  title: 'Air cooled chiller data',
  spec_section: '23 64 23',
  submittal_type: 'product_data',
  status: 'under_review',
  date_submitted: '2099-01-01',
  discipline: 'hvac',
  manufacturer: 'Example Cooling Works',
  model_reference: 'ACW-450',
  country_of_origin: 'TR',
  supplier: 'Example Trading',
  supplier_name: 'Example Trading',
  review_period_days: 14,
  required_on_site_date: '2099-06-01',
  long_lead: true,
  lead_time_weeks: 16,
  days_in_review: 25,
  review_due_date: '2099-01-15',
  review_overdue_days: 11,
  approval_needed_by: '2099-02-09',
  approval_late_days: 20,
  submit_by_date: '2099-01-26',
};

/** A fresher submittal with the reviewer, inside its review period. */
const PANEL = {
  ...LEGACY,
  id: 's-3',
  submittal_number: 'SUB-003',
  title: 'Main switchboard drawings',
  status: 'submitted',
  date_submitted: '2099-01-01',
  discipline: 'electrical',
  review_period_days: 14,
  days_in_review: 3,
  review_overdue_days: 0,
  review_due_date: '2099-01-15',
};

/** Revision 2 of a submittal whose first revision came back for correction. */
const DUCT = {
  ...LEGACY,
  id: 's-4',
  submittal_number: 'SUB-004',
  title: 'Ductwork fabrication drawings',
  status: 'submitted',
  revision: 2,
  current_revision: 2,
  date_submitted: '2099-02-01',
  discipline: 'hvac',
  review_history: [
    {
      revision: 1,
      outcome: 'revise_and_resubmit',
      code: '3',
      date_submitted: '2099-01-05',
      date_returned: '2099-01-19',
      reviewer_id: null,
      notes: 'Fire damper access panels missing on level 2.',
      resubmit_for_record: false,
    },
  ],
};

// Letters and labels no default carries, so they can only have come from here.
const VOCABULARY = {
  locale: 'en',
  types: [
    { code: 'shop_drawing', label: 'Shop drawing', short_code: null },
    { code: 'product_data', label: 'Product data', short_code: null },
    { code: 'method_statement', label: 'Method statement', short_code: null },
    { code: 'sample', label: 'Sample', short_code: null },
  ],
  disciplines: [
    { code: 'hvac', label: 'Climate systems', short_code: 'HX' },
    { code: 'electrical', label: 'Power', short_code: 'EP' },
  ],
  outcomes: [
    { code: 'approved', label: 'Approved', short_code: '1' },
    { code: 'approved_as_noted', label: 'Approved as noted', short_code: '2' },
    { code: 'revise_and_resubmit', label: 'Revise and resubmit', short_code: '3' },
    { code: 'rejected', label: 'Rejected', short_code: '4' },
  ],
  sort_fields: ['created_at', 'submittal_number', 'title', 'status', 'date_required'],
};

const SUMMARY = {
  project_id: 'p-1',
  as_of: '2026-10-10',
  total: 42,
  by_status: [{ code: 'under_review', count: 9 }],
  by_type: [
    { code: 'shop_drawing', count: 17 },
    { code: 'product_data', count: 12 },
  ],
  by_discipline: [
    { code: 'hvac', count: 12 },
    { code: 'facade', count: 2 },
    { code: '', count: 3 },
  ],
  by_outcome: [
    { code: 'approved', count: 14, review_code: '1' },
    { code: 'approved_as_noted', count: 5, review_code: '2' },
    { code: 'revise_and_resubmit', count: 6, review_code: '3' },
    { code: 'rejected', count: 1, review_code: '4' },
  ],
  awaiting_review: 9,
  review_overdue: 2,
  review_period_unknown: 4,
  long_lead: 6,
  long_lead_awaiting_approval: 3,
  approval_late: 1,
  long_lead_without_lead_time: 1,
};

const FINDINGS = {
  status: 'warnings',
  score: 0.8,
  counts: { total: 3, passed: 1, errors: 1, warnings: 1 },
  results: [
    {
      rule_id: 'submittal.long_lead_has_lead_time',
      rule_name: 'Submittal Long Lead Has Lead Time',
      severity: 'error',
      category: 'completeness',
      passed: false,
      message: 'Marked long lead with no lead time recorded.',
      element_ref: null,
      suggestion: 'Record the lead time in weeks.',
    },
    {
      rule_id: 'submittal.material_has_manufacturer',
      rule_name: 'Submittal Material Has Manufacturer',
      severity: 'warning',
      category: 'completeness',
      passed: true,
      message: 'OK',
      element_ref: null,
      suggestion: null,
    },
  ],
};

interface Server {
  rows: unknown[];
  /** `null` stands for a server that does not answer the route with a summary. */
  summary: unknown;
  vocabulary: unknown;
}

/** Route a GET by path, most specific first, as the real routes are matched. */
function serve({ rows, summary, vocabulary }: Server): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/submittals/summary/')) return Promise.resolve(summary);
    if (path.startsWith('/v1/submittals/vocabulary/')) return Promise.resolve(vocabulary);
    if (path.includes('/validate/')) return Promise.resolve(FINDINGS);
    if (path.startsWith('/v1/submittals/?')) return Promise.resolve(rows);
    if (path.startsWith('/v1/projects')) return Promise.resolve([PROJECT]);
    return Promise.resolve([]);
  });
}

/** The query string of the most recent list request. */
function lastListQuery(): URLSearchParams {
  const paths = api.apiGet.mock.calls.map((call) => String(call[0])).filter((p) => p.startsWith('/v1/submittals/?'));
  return new URLSearchParams((paths[paths.length - 1] ?? '').split('?')[1] ?? '');
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/submittals']}>
        <SubmittalsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The titles on screen, top to bottom. */
function listedTitles(): string[] {
  return [LEGACY, CHILLER, PANEL, DUCT]
    .map((row) => screen.queryByText(row.title))
    .filter((el): el is HTMLElement => el !== null)
    .sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))
    .map((el) => el.textContent ?? '');
}

beforeEach(() => {
  api.downloadWithAuth.mockResolvedValue(undefined);
  api.apiPost.mockResolvedValue({ ...LEGACY, id: 's-new' });
  useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: PROJECT.name });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('a register from before the register columns', () => {
  it('renders the row and the four tiles as it always did', async () => {
    // The summary and vocabulary routes answer with something that is not
    // theirs, which is what an older server does with an unknown static path.
    serve({ rows: [LEGACY], summary: [LEGACY], vocabulary: [LEGACY] });
    renderPage();
    await screen.findByText(LEGACY.title);

    expect(screen.queryByTestId('submittals-summary')).toBeNull();
    expect(screen.getByText('Pending Review')).toBeTruthy();
    expect(screen.getByText('Rejected / Resubmit')).toBeTruthy();
    // No discipline or approval-deadline column for a list that fills neither.
    expect(screen.queryByText('Disc.')).toBeNull();
    expect(screen.queryByText('Approval needed by')).toBeNull();
    // Nothing is sortable until the server says what it can sort by.
    expect(screen.queryByTestId('submittals-sort-title')).toBeNull();
    expect(screen.queryByTestId('review-clock-s-1')).toBeNull();

    fireEvent.click(screen.getByText(LEGACY.title));
    await screen.findByTestId('submittal-pdf-s-1');
    expect(screen.queryByTestId('submittal-procurement-s-1')).toBeNull();
    expect(screen.queryByTestId('submittal-outcome-s-1')).toBeNull();
    expect(screen.queryByTestId('submittal-history-s-1')).toBeNull();
  });

  it('asks the list for nothing it did not ask before', async () => {
    serve({ rows: [LEGACY], summary: null, vocabulary: null });
    renderPage();
    await screen.findByText(LEGACY.title);
    expect(lastListQuery().toString()).toBe('project_id=p-1&limit=100');
  });
});

describe('the counts above the register', () => {
  it('shows the summary route figures, not counts of the rows on screen', async () => {
    serve({ rows: [CHILLER], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    await screen.findByTestId('submittals-summary');

    expect(screen.getByTestId('submittals-stat-total').textContent).toContain('42');
    expect(screen.getByTestId('submittals-stat-awaiting').textContent).toContain('9');
    expect(screen.getByTestId('submittals-stat-review-overdue').textContent).toBe('2 past the review period');
    expect(screen.getByText('4 with no review period recorded')).toBeTruthy();
    expect(screen.getByTestId('submittals-stat-long-lead').textContent).toContain('3');
    expect(screen.getByText('of 6 long-lead items; opens them all')).toBeTruthy();
    expect(screen.getByTestId('submittals-stat-approval-late').textContent).toContain('1');
    // The old tiles are replaced, not stacked under the new ones.
    expect(screen.queryByText('Pending Review')).toBeNull();
  });

  it('opens the late approvals through the list route filter, and closes them again', async () => {
    serve({ rows: [CHILLER, PANEL], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    await screen.findByTestId('submittals-summary');

    fireEvent.click(screen.getByTestId('submittals-stat-approval-late'));
    await waitFor(() => expect(lastListQuery().get('approval_late')).toBe('true'));
    expect(screen.getByTestId('submittals-stat-approval-late').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByTestId('submittals-filter-approval-late').getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(screen.getByTestId('submittals-stat-approval-late'));
    await waitFor(() => expect(lastListQuery().get('approval_late')).toBeNull());
  });

  it('opens what came back for correction by its outcome code', async () => {
    serve({ rows: [CHILLER], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    const chip = await screen.findByTestId('submittals-outcome-revise_and_resubmit');
    // The letter is the one the summary served for the outcome, with its count.
    expect(chip.textContent).toContain('3');
    expect(chip.textContent).toContain('6');

    fireEvent.click(chip);
    await waitFor(() => expect(lastListQuery().get('outcome')).toBe('revise_and_resubmit'));
    // A shortcut opens its cut alone: no other filter rides along.
    expect(lastListQuery().toString()).toBe('project_id=p-1&outcome=revise_and_resubmit&limit=100');
  });

  it('lists what is with the reviewer, longest wait first by the server day count', async () => {
    serve({ rows: [LEGACY, PANEL, CHILLER], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    await screen.findByText(LEGACY.title);
    expect(listedTitles()).toEqual([LEGACY.title, PANEL.title, CHILLER.title]);

    fireEvent.click(screen.getByTestId('submittals-stat-awaiting'));
    await waitFor(() => expect(screen.queryByText(LEGACY.title)).toBeNull());
    // 25 days before 3 days; the draft is not with the reviewer at all.
    expect(listedTitles()).toEqual([CHILLER.title, PANEL.title]);
  });

  it('opens a discipline, and does not offer a filter for rows that have none', async () => {
    serve({ rows: [CHILLER], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    const chip = await screen.findByTestId('submittals-discipline-hvac');
    // Mark and label from the vocabulary; a project's own code reads as stored.
    expect(chip.textContent).toContain('HX');
    expect(chip.textContent).toContain('Climate systems');
    expect(screen.getByTestId('submittals-discipline-facade').textContent).toContain('Facade');
    expect(screen.getByText('No discipline: 3')).toBeTruthy();

    fireEvent.click(chip);
    await waitFor(() => expect(lastListQuery().get('discipline')).toBe('hvac'));
  });
});

describe('the legend of review codes', () => {
  it('says in one line what each code means for ordering, with the served letters', async () => {
    serve({ rows: [CHILLER], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    await screen.findByTestId('submittals-summary');
    expect(screen.queryByTestId('submittals-outcome-legend')).toBeNull();

    fireEvent.click(screen.getByTestId('submittals-legend-toggle'));
    const legend = screen.getByTestId('submittals-outcome-legend');
    const lines = within(legend).getAllByRole('listitem').map((li) => li.textContent ?? '');

    expect(lines).toHaveLength(4);
    expect(lines[0]).toContain('1');
    expect(lines[0]).toContain('Released: order and install as submitted.');
    expect(lines[1]).toContain("Released: order and install, with the reviewer's notes taken into account.");
    expect(lines[2]).toContain('3');
    expect(lines[2]).toContain('Not released: do not order. Correct it and send in a new revision.');
    expect(lines[3]).toContain('Not released: do not order. A different proposal is needed.');
  });
});

describe('the figures on a row', () => {
  it('prints days in review and days overdue as the server counted them', async () => {
    serve({ rows: [CHILLER, PANEL], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    await screen.findByText(CHILLER.title);

    const late = screen.getByTestId('review-clock-s-2');
    expect(late.textContent).toContain('25 d');
    expect(late.textContent).toContain('+11');
    expect(late.getAttribute('title')).toBe('25 d in review, 11 d past the review period');

    const inside = screen.getByTestId('review-clock-s-3');
    expect(inside.textContent).toContain('3 d');
    expect(inside.textContent).not.toContain('+');
    expect(inside.getAttribute('title')).toBe('3 d in review, inside the review period');
  });

  it('marks the long-lead item and how late its approval is', async () => {
    serve({ rows: [CHILLER, PANEL], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    await screen.findByText(CHILLER.title);

    expect(screen.getAllByText('Long-lead item, 16 wk lead time').length).toBeGreaterThan(0);
    expect(screen.getByText('20 d late')).toBeTruthy();
    expect(screen.getByText('Approval needed by')).toBeTruthy();
    // Maker and model sit under the title; the discipline is its served mark.
    expect(screen.getByText('Example Cooling Works / ACW-450')).toBeTruthy();
    expect(screen.getAllByTitle('Climate systems').map((el) => el.textContent)).toContain('HX');
  });

  it('shows the revision a resubmission replaces, and what the checks find', async () => {
    serve({ rows: [DUCT], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    fireEvent.click(await screen.findByText(DUCT.title));

    const history = await screen.findByTestId('submittal-history-s-4');
    expect(history.textContent).toContain('R2 replaces R1, which came back as 3 (Revise & Resubmit).');
    expect(history.textContent).toContain('Fire damper access panels missing on level 2.');
    expect(history.textContent).toContain('Current revision, no decision yet');

    // Only the rule that did not pass is listed, with its suggestion.
    const findings = await screen.findByTestId('submittal-findings-s-4');
    expect(findings.textContent).toContain('Marked long lead with no lead time recorded.');
    expect(findings.textContent).toContain('Record the lead time in weeks.');
    expect(within(findings).getAllByRole('listitem')).toHaveLength(1);
  });
});

describe('the shop drawing register and the other cuts', () => {
  it('is the same register filtered by type, on the list and in the export', async () => {
    serve({ rows: [LEGACY], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    await screen.findByText(LEGACY.title);

    const tab = screen.getByTestId('submittals-type-tab-shop_drawing');
    expect(tab.textContent).toContain('Shop drawings');
    expect(tab.textContent).toContain('17');
    fireEvent.click(tab);
    await waitFor(() => expect(lastListQuery().get('type')).toBe('shop_drawing'));
    expect(tab.getAttribute('aria-selected')).toBe('true');

    fireEvent.click(screen.getByTestId('submittals-export'));
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(String(api.downloadWithAuth.mock.calls[0]?.[0])).toBe(
      '/api/v1/submittals/export/?project_id=p-1&format=pdf&locale=en&type=shop_drawing',
    );

    // The control says what the document follows now that it is not the whole register.
    fireEvent.click(screen.getByTestId('submittals-export-more'));
    expect(screen.getByText(/The export follows the type tab and the filters/)).toBeTruthy();
  });

  it('offers the served disciplines plus the codes the project files under', async () => {
    serve({ rows: [CHILLER], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    const select = (await screen.findByTestId('submittals-filter-discipline')) as HTMLSelectElement;
    await waitFor(() => expect(select.options.length).toBe(4));
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
      'All disciplines',
      'HX - Climate systems',
      'EP - Power',
      'FAC - Facade',
    ]);

    fireEvent.change(select, { target: { value: 'electrical' } });
    await waitFor(() => expect(lastListQuery().get('discipline')).toBe('electrical'));

    // Filters add up, and all of them reach the export.
    fireEvent.click(screen.getByTestId('submittals-filter-long-lead'));
    fireEvent.click(screen.getByTestId('submittals-filter-review-overdue'));
    await waitFor(() => expect(lastListQuery().get('review_overdue')).toBe('true'));
    expect(lastListQuery().toString()).toBe(
      'project_id=p-1&discipline=electrical&long_lead=true&review_overdue=true&limit=100',
    );

    fireEvent.click(screen.getByTestId('submittals-export'));
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(String(api.downloadWithAuth.mock.calls[0]?.[0])).toBe(
      '/api/v1/submittals/export/?project_id=p-1&format=pdf&locale=en&discipline=electrical&long_lead=true&review_overdue=true',
    );

    fireEvent.click(screen.getByTestId('submittals-filter-clear'));
    await waitFor(() => expect(lastListQuery().toString()).toBe('project_id=p-1&limit=100'));
  });

  it('orders the list on the server, by a column the server lists as sortable', async () => {
    serve({ rows: [CHILLER], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    const header = await screen.findByTestId('submittals-sort-title');

    fireEvent.click(header);
    await waitFor(() => expect(lastListQuery().get('sort')).toBe('title'));
    expect(lastListQuery().get('order')).toBe('asc');
    fireEvent.click(screen.getByTestId('submittals-sort-title'));
    await waitFor(() => expect(lastListQuery().get('order')).toBe('desc'));
  });
});

describe('filing a submittal', () => {
  async function openCreateForm() {
    serve({ rows: [LEGACY], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    await screen.findByText(LEGACY.title);
    fireEvent.click(screen.getByRole('button', { name: 'New Submittal' }));
    return screen.findByRole('dialog');
  }

  it('asks for the lead time only for a long-lead item, and then requires it', async () => {
    const dialog = await openCreateForm();
    fireEvent.change(within(dialog).getByLabelText(/^Title/), { target: { value: 'Chiller data' } });
    fireEvent.change(within(dialog).getByLabelText(/^Spec Section/), { target: { value: '23 64 23' } });
    const save = within(dialog).getByRole('button', { name: 'Create Submittal' }) as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    expect(within(dialog).queryByLabelText(/Lead time \(weeks\)/)).toBeNull();

    fireEvent.click(within(dialog).getByLabelText('Long-lead item'));
    const lead = within(dialog).getByLabelText(/Lead time \(weeks\)/) as HTMLInputElement;
    expect(within(dialog).getByText('A long-lead item needs its lead time')).toBeTruthy();
    expect(save.disabled).toBe(true);

    fireEvent.change(lead, { target: { value: '16' } });
    expect(within(dialog).queryByText('A long-lead item needs its lead time')).toBeNull();
    expect(save.disabled).toBe(false);

    // Unticking takes the lead time with it.
    fireEvent.click(within(dialog).getByLabelText('Long-lead item'));
    expect(within(dialog).queryByLabelText(/Lead time \(weeks\)/)).toBeNull();
  });

  it('prompts for the manufacturer on a material submittal, without blocking', async () => {
    const dialog = await openCreateForm();
    const prompt = /A material submittal without a manufacturer/;
    expect(within(dialog).queryByText(prompt)).toBeNull();

    fireEvent.change(within(dialog).getByLabelText('Type'), { target: { value: 'product_data' } });
    expect(within(dialog).getByText(prompt)).toBeTruthy();

    fireEvent.change(within(dialog).getByLabelText('Manufacturer / brand'), {
      target: { value: 'Example Cooling Works' },
    });
    expect(within(dialog).queryByText(prompt)).toBeNull();
  });

  it('offers the disciplines the vocabulary serves and sends what was filled in', async () => {
    const dialog = await openCreateForm();
    const discipline = within(dialog).getByLabelText('Discipline') as HTMLSelectElement;
    expect(Array.from(discipline.options).map((option) => option.textContent)).toEqual([
      'No discipline',
      'HX - Climate systems',
      'EP - Power',
      'Other (type a code)',
    ]);

    fireEvent.change(within(dialog).getByLabelText(/^Title/), { target: { value: 'Chiller data' } });
    fireEvent.change(within(dialog).getByLabelText(/^Spec Section/), { target: { value: '23 64 23' } });
    fireEvent.change(discipline, { target: { value: 'hvac' } });
    fireEvent.change(within(dialog).getByLabelText('Manufacturer / brand'), {
      target: { value: 'Example Cooling Works' },
    });
    fireEvent.change(within(dialog).getByLabelText('Required on site'), { target: { value: '2027-03-01' } });
    fireEvent.change(within(dialog).getByLabelText('Review period (days)'), { target: { value: '14' } });
    fireEvent.click(within(dialog).getByLabelText('Long-lead item'));
    fireEvent.change(within(dialog).getByLabelText(/Lead time \(weeks\)/), { target: { value: '16' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create Submittal' }));

    await waitFor(() => expect(api.apiPost).toHaveBeenCalledTimes(1));
    expect(api.apiPost.mock.calls[0]?.[0]).toBe('/v1/submittals/');
    expect(api.apiPost.mock.calls[0]?.[1]).toEqual({
      project_id: 'p-1',
      title: 'Chiller data',
      description: undefined,
      spec_section: '23 64 23',
      submittal_type: 'shop_drawing',
      date_required: undefined,
      discipline: 'hvac',
      manufacturer: 'Example Cooling Works',
      required_on_site_date: '2027-03-01',
      long_lead: true,
      lead_time_weeks: 16,
      review_period_days: 14,
    });
  });

  it('lets a project type a discipline of its own', async () => {
    const dialog = await openCreateForm();
    fireEvent.change(within(dialog).getByLabelText('Discipline'), { target: { value: '__other__' } });
    const typed = within(dialog).getByLabelText('Discipline') as HTMLInputElement;
    expect(typed.tagName).toBe('INPUT');

    fireEvent.change(typed, { target: { value: '3d scan' } });
    expect(within(dialog).getByText(/Use a short code/)).toBeTruthy();
    // Clearing the error must not swap the input out from under the caret.
    fireEvent.change(typed, { target: { value: 'Fire Stopping' } });
    expect(within(dialog).queryByText(/Use a short code/)).toBeNull();
    expect(within(dialog).getByLabelText('Discipline')).toBe(typed);
  });
});

describe('recording a review', () => {
  it('offers the served default mark, and the corrected copy only for approved as noted', async () => {
    serve({ rows: [PANEL], summary: SUMMARY, vocabulary: VOCABULARY });
    renderPage();
    fireEvent.click(await screen.findByText(PANEL.title));
    fireEvent.click(await screen.findByRole('button', { name: 'Review' }));

    const code = (await screen.findByLabelText('Review code')) as HTMLInputElement;
    expect(code.placeholder).toBe('1');
    expect(screen.queryByLabelText('Corrected copy to be resubmitted for record')).toBeNull();
    expect(screen.getByTestId('submittal-decision-hint').textContent).toBe(
      'Released: order and install as submitted.',
    );

    fireEvent.click(screen.getByRole('radio', { name: 'Approved as Noted' }));
    expect(code.placeholder).toBe('2');
    fireEvent.click(screen.getByLabelText('Corrected copy to be resubmitted for record'));
    fireEvent.change(code, { target: { value: 'AAN' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit Review' }));

    await waitFor(() => expect(api.apiPost).toHaveBeenCalledTimes(1));
    expect(api.apiPost.mock.calls[0]?.[0]).toBe('/v1/submittals/s-3/review/');
    expect(api.apiPost.mock.calls[0]?.[1]).toEqual({
      status: 'approved_as_noted',
      notes: undefined,
      code: 'AAN',
      resubmit_for_record: true,
    });
  });
});
