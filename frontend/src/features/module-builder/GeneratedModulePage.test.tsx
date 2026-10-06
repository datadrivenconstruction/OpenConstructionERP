// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The generic screen, driven by a specification it has never seen before.
 *
 * The point of these is that nothing about the module under test is compiled
 * in. The spec below is invented here, and the assertions are about the screen
 * having read it: the columns it drew, the inputs it chose, the field a refusal
 * landed on. A renderer that quietly ignored half the spec would still show a
 * table, so each test names something specific the spec asked for.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => vi.fn(), useParams: () => ({ moduleKey: 'pour_register' }) };
});

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    fetchInstalledModules: vi.fn(),
    fetchModuleUiSpec: vi.fn(),
    fetchModuleRecords: vi.fn(),
    createModuleRecord: vi.fn(),
    updateModuleRecord: vi.fn(),
    deleteModuleRecord: vi.fn(),
    lookupLabels: vi.fn(),
    lookupRecords: vi.fn(),
  };
});

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, downloadWithAuth: vi.fn() };
});

// The thread itself has its own tests and its own server; here the question is
// only whether the record's form offers one, and for which entity.
vi.mock('@/shared/ui/CommentThread', () => ({
  CommentThread: ({ entityType, entityId }: { entityType: string; entityId: string }) => (
    <div data-testid="comment-thread">{`${entityType}/${entityId}`}</div>
  ),
}));

import { ApiError, downloadWithAuth } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import {
  createModuleRecord,
  deleteModuleRecord,
  fetchInstalledModules,
  fetchModuleRecords,
  fetchModuleUiSpec,
  lookupLabels,
  updateModuleRecord,
  type GeneratedRecord,
  type InstalledList,
  type ModuleUiSpec,
} from './api';
import { GeneratedModulePage } from './GeneratedModulePage';

const installed = vi.mocked(fetchInstalledModules);
const uiSpec = vi.mocked(fetchModuleUiSpec);
const records = vi.mocked(fetchModuleRecords);
const create = vi.mocked(createModuleRecord);
const update = vi.mocked(updateModuleRecord);
const remove = vi.mocked(deleteModuleRecord);

const BASE_PATH = '/api/v1/pour-register';

const INSTALLED: InstalledList = {
  items: [
    {
      key: 'pour_register',
      module_name: 'oe_pour_register',
      display_name: 'Pour Register',
      version: '0.1.0',
      generated_at: '2026-08-07T00:00:00Z',
      entity: 'Pour',
      field_count: 5,
      rule_count: 2,
      base_path: BASE_PATH,
    },
  ],
  total: 1,
  runtime_root: '/home/oe/.openestimate/modules',
};

const SPEC: ModuleUiSpec = {
  key: 'pour_register',
  display_name: 'Pour Register',
  description: 'Every pour, what went in it and who signed it off.',
  category: 'community',
  icon: 'Boxes',
  version: '0.1.0',
  author: '',
  drafted_by: 'wizard',
  entity: {
    name: 'pour',
    display_name: 'Pour',
    plural_name: 'Pours',
    project_scoped: true,
    fields: [
      { name: 'reference', label: 'Pour reference', type: 'text', required: true, help_text: '', unit: '', options: [], in_list: true },
      { name: 'volume', label: 'Volume', type: 'number', required: false, help_text: 'As delivered', unit: 'm3', options: [], in_list: true },
      { name: 'cost', label: 'Cost', type: 'money', required: false, help_text: '', unit: '', options: [], in_list: true },
      { name: 'poured_on', label: 'Poured on', type: 'date', required: false, help_text: '', unit: '', options: [], in_list: true },
      { name: 'mix', label: 'Mix', type: 'select', required: false, help_text: '', unit: '', options: ['C25/30', 'C32/40'], in_list: true },
      { name: 'signed_off', label: 'Signed off', type: 'boolean', required: false, help_text: '', unit: '', options: [], in_list: true },
      { name: 'notes', label: 'Notes', type: 'long_text', required: false, help_text: '', unit: '', options: [], in_list: false },
    ],
  },
  rules: [
    { code: 'REFERENCE_REQUIRED', message: 'A pour without a reference cannot be traced.', kind: 'required', field: 'reference', min_value: null, max_value: null, other_field: '', severity: 'error' },
    { code: 'VOLUME_POSITIVE', message: 'A pour of nothing is not a pour.', kind: 'positive', field: 'volume', min_value: null, max_value: null, other_field: '', severity: 'error' },
  ],
};

const ROW: GeneratedRecord = {
  id: 'rec-1',
  project_id: 'p1',
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  reference: 'P-014',
  volume: '18.50',
  cost: '4210.00',
  poured_on: '2026-08-01',
  mix: 'C25/30',
  signed_off: true,
  notes: 'Slab B.',
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <GeneratedModulePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useProjectContextStore.setState({ activeProjectId: 'p1', activeProjectName: 'Site A' });
  installed.mockResolvedValue(INSTALLED);
  uiSpec.mockResolvedValue(SPEC);
  records.mockResolvedValue({ items: [ROW], total: 1 });
  create.mockResolvedValue(ROW);
  update.mockResolvedValue(ROW);
  remove.mockResolvedValue(undefined);
});

describe('reading a module it has never seen', () => {
  it('asks the server where the module lives instead of guessing', async () => {
    renderPage();
    await waitFor(() => expect(uiSpec).toHaveBeenCalledWith(BASE_PATH));
    // The route carries `pour_register`; the URL is `pour-register`. Nothing
    // here turned one into the other - the installed list did.
    // offset is part of the call now: the register pages by offset rather
    // than reading one capped page and saying nothing about the rest.
    expect(records).toHaveBeenCalledWith(BASE_PATH, { projectId: 'p1', limit: 200, offset: 0 });
  });

  it('draws the columns the spec marked, and not the ones it did not', async () => {
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent ?? '');
    expect(headers.some((h) => h.includes('Pour reference'))).toBe(true);
    expect(headers.some((h) => h.includes('Volume'))).toBe(true);
    // `notes` is in_list: false, so it belongs on the record and not in the table.
    expect(headers.some((h) => h.includes('Notes'))).toBe(false);
  });

  it('names the unit in the column heading rather than on every row', async () => {
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    expect(within(table).getByText(/\(m3\)/)).toBeTruthy();
  });

  it('renders a checkbox column as a word, not as true', async () => {
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    expect(within(table).queryByText('true')).toBeNull();
    expect(within(table).getByText('Yes')).toBeTruthy();
  });

  it('shows the module own rules on the screen it built', async () => {
    renderPage();
    expect(await screen.findByText('A pour of nothing is not a pour.')).toBeTruthy();
  });

  it('says so when the instance carries no such module', async () => {
    installed.mockResolvedValue({ items: [], total: 0, runtime_root: '/tmp' });
    renderPage();
    expect(await screen.findByText(/No such module on this instance/i)).toBeTruthy();
    // And it does not go on to ask a module that is not there for its spec.
    expect(uiSpec).not.toHaveBeenCalled();
  });

  it('says in words that a module switched off for safety was switched off, and asks it nothing', async () => {
    const [module] = INSTALLED.items;
    installed.mockResolvedValue({
      ...INSTALLED,
      items: [{ ...module!, status: 'quarantined', problem: { code: 'unverifiable' } }],
    });
    renderPage();
    const notice = await screen.findByTestId('runtime-module-quarantined');
    expect(notice.textContent).toMatch(/Switched off for safety/);
    expect(notice.textContent).toMatch(/could not be checked\. Its records are kept/);
    // Its address answers nothing, so neither the spec nor the records are asked for.
    expect(uiSpec).not.toHaveBeenCalled();
    expect(records).not.toHaveBeenCalled();
  });

  it('offers to record the first one when there is nothing yet', async () => {
    records.mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(await screen.findByText(/No Pours yet/i)).toBeTruthy();
  });
});

describe('the project a record belongs to', () => {
  it('will not let a scoped record be started without a project', async () => {
    useProjectContextStore.setState({ activeProjectId: null });
    renderPage();
    await screen.findByTestId('runtime-module-page');
    expect(screen.getByTestId('runtime-module-new')).toBeDisabled();
    // Asking for the records would 422 on the missing project, so it does not.
    expect(records).not.toHaveBeenCalled();
  });

  it('does not demand one from a module whose records are not scoped', async () => {
    useProjectContextStore.setState({ activeProjectId: null });
    uiSpec.mockResolvedValue({ ...SPEC, entity: { ...SPEC.entity, project_scoped: false } });
    renderPage();
    await screen.findByTestId('runtime-module-table');
    expect(records).toHaveBeenCalledWith(BASE_PATH, { projectId: null, limit: 200, offset: 0 });
    expect(screen.getByTestId('runtime-module-new')).not.toBeDisabled();
  });
});

describe('recording one', () => {
  it('builds a form from the spec, one input per field', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('runtime-module-table');
    await user.click(screen.getByTestId('runtime-module-new'));

    // A select is a select, a checkbox is a checkbox, a date is a date. A
    // renderer that put everything in a text box would still "work".
    expect(await screen.findByLabelText(/Mix/)).toHaveProperty('tagName', 'SELECT');
    expect(screen.getByLabelText(/Signed off/)).toHaveProperty('type', 'checkbox');
    expect(screen.getByLabelText(/Poured on/)).toHaveProperty('type', 'date');
    expect(screen.getByLabelText(/Notes/).tagName).toBe('TEXTAREA');
  });

  it('sends money as the string that was typed', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('runtime-module-table');
    await user.click(screen.getByTestId('runtime-module-new'));
    await screen.findByLabelText(/Pour reference/);

    await user.type(screen.getByLabelText(/Pour reference/), 'P-015');
    await user.type(screen.getByLabelText(/Volume/), '12.5');
    await user.type(screen.getByLabelText(/^Cost/), '1234.05');
    await user.click(screen.getByTestId('runtime-module-save'));

    await waitFor(() => expect(create).toHaveBeenCalled());
    const [path, payload] = create.mock.calls[0] ?? [];
    expect(path).toBe(BASE_PATH);
    expect(payload).toMatchObject({ project_id: 'p1', reference: 'P-015', cost: '1234.05', volume: '12.5' });
    expect(typeof (payload as Record<string, unknown>).cost).toBe('string');
  });

  it('answers a rule before the round trip rather than after it', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('runtime-module-table');
    await user.click(screen.getByTestId('runtime-module-new'));
    await screen.findByLabelText(/Pour reference/);

    // The reference is required and empty, and the volume breaks a rule.
    await user.type(screen.getByLabelText(/Volume/), '0');
    await user.click(screen.getByTestId('runtime-module-save'));

    // Scoped to the form: the same sentence is also on the page, in the panel
    // that lists what this module checks, and that one was there all along.
    const form = screen.getByRole('dialog');
    expect(await within(form).findByText('A pour of nothing is not a pour.')).toBeTruthy();
    expect(create).not.toHaveBeenCalled();
  });

  it('puts a refusal from the server on the field it is about', async () => {
    create.mockRejectedValue(
      new ApiError(422, 'Unprocessable Entity', {
        detail: [{ code: 'VOLUME_POSITIVE', message: 'The batching plant reported nothing.', field: 'volume' }],
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('runtime-module-table');
    await user.click(screen.getByTestId('runtime-module-new'));
    await screen.findByLabelText(/Pour reference/);

    await user.type(screen.getByLabelText(/Pour reference/), 'P-016');
    await user.click(screen.getByTestId('runtime-module-save'));

    expect(await screen.findByText('The batching plant reported nothing.')).toBeTruthy();
  });
});

describe('correcting one', () => {
  it('opens the row that was clicked, not a blank form', async () => {
    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    await user.click(within(table).getByLabelText('Edit'));

    const reference = await screen.findByLabelText(/Pour reference/);
    expect(reference).toHaveProperty('value', 'P-014');
    expect(screen.getByLabelText(/^Cost/)).toHaveProperty('value', '4210.00');
  });

  it('sends only what changed', async () => {
    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    await user.click(within(table).getByLabelText('Edit'));
    await screen.findByLabelText(/Pour reference/);

    await user.clear(screen.getByLabelText(/Volume/));
    await user.type(screen.getByLabelText(/Volume/), '19');
    await user.click(screen.getByTestId('runtime-module-save'));

    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0]?.[2]).toEqual({ volume: '19' });
  });
});

describe('removing one', () => {
  it('asks before it does, and then does', async () => {
    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    await user.click(within(table).getByLabelText('Delete'));

    expect(await screen.findByText(/cannot be undone/i)).toBeTruthy();
    expect(remove).not.toHaveBeenCalled();

    await user.click(screen.getByTestId('confirm-dialog-confirm'));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(BASE_PATH, 'rec-1'));
  });
});

/**
 * A generated register is the screen a module exists to provide, and it used to
 * read one capped page of 200 and render it with nothing said about the rest.
 * These cover the three things that follow from fixing that: the count is
 * always on screen, a search never answers about rows it has not read, and a
 * sort is not offered over a partial set.
 */
const ROW_B: GeneratedRecord = {
  ...ROW,
  id: 'rec-2',
  reference: 'A-001',
  volume: '3.00',
  cost: '99.00',
  poured_on: '2026-07-02',
};

describe('the generated register over more rows than one page', () => {
  it('says how many of the total are on screen', async () => {
    records.mockResolvedValue({ items: [ROW, ROW_B], total: 5 });
    renderPage();
    await screen.findByTestId('runtime-module-table');
    expect(screen.getByTestId('runtime-module-count').textContent).toBe('Showing 2 of 5');
  });

  it('offers to load the rest, and refuses to sort until it is loaded', async () => {
    records.mockResolvedValue({ items: [ROW, ROW_B], total: 5 });
    renderPage();
    await screen.findByTestId('runtime-module-table');

    expect(screen.getByTestId('runtime-module-more')).toBeTruthy();
    // The header is plain text, not a control. Sorting three of five rows puts
    // a row on top that is not the largest and says nothing about it.
    expect(screen.queryByTestId('runtime-module-sort-cost')).toBeNull();
  });

  it('sorts once every row is in, and sorts by value rather than by rendered text', async () => {
    const user = userEvent.setup();
    records.mockResolvedValue({ items: [ROW, ROW_B], total: 2 });
    renderPage();
    await screen.findByTestId('runtime-module-table');

    expect(screen.queryByTestId('runtime-module-more')).toBeNull();
    await user.click(screen.getByTestId('runtime-module-sort-cost'));

    // 99.00 before 4210.00 ascending. Compared as strings "4210.00" sorts
    // first, which is the bug this asserts against.
    const cells = screen.getAllByRole('row').slice(1).map((r) => r.textContent ?? '');
    expect(cells[0]).toContain('A-001');
    expect(cells[1]).toContain('P-014');
  });

  it('filters to what the reader can see, and counts the filtered rows', async () => {
    const user = userEvent.setup();
    records.mockResolvedValue({ items: [ROW, ROW_B], total: 2 });
    renderPage();
    await screen.findByTestId('runtime-module-table');

    await user.type(screen.getByTestId('runtime-module-search'), 'A-001');
    await waitFor(() =>
      expect(screen.getByTestId('runtime-module-count').textContent).toBe('Showing 1 of 2'),
    );
    expect(screen.queryByText('P-014')).toBeNull();
  });

  it('keeps empty cells at the bottom whichever way the column is sorted', async () => {
    const user = userEvent.setup();
    const blank: GeneratedRecord = { ...ROW, id: 'rec-3', reference: 'Z-999', cost: '' };
    records.mockResolvedValue({ items: [ROW, ROW_B, blank], total: 3 });
    renderPage();
    await screen.findByTestId('runtime-module-table');

    await user.click(screen.getByTestId('runtime-module-sort-cost'));
    let rows = screen.getAllByRole('row').slice(1).map((r) => r.textContent ?? '');
    expect(rows[2]).toContain('Z-999');

    // Descending flips the rows that have a value. It must not float the
    // blanks to the top: a column sorted the other way would otherwise open
    // on a screen of empty cells and hide what was asked for.
    await user.click(screen.getByTestId('runtime-module-sort-cost'));
    rows = screen.getAllByRole('row').slice(1).map((r) => r.textContent ?? '');
    expect(rows[0]).toContain('P-014');
    expect(rows[2]).toContain('Z-999');
  });

  it('says a module was described without checks rather than heading an empty list', async () => {
    uiSpec.mockResolvedValue({ ...SPEC, rules: [] });
    records.mockResolvedValue({ items: [ROW], total: 1 });
    renderPage();
    await screen.findByTestId('runtime-module-table');
    expect(screen.getByText(/described without any checks/i)).toBeTruthy();
  });
});

/**
 * Paging with DISTINCT pages. The tests above hand back the same rows for every
 * offset, which is enough to check what the screen says but not enough to check
 * that a second page is really fetched, really appended, and really stops. A
 * mock that answers identically forever hides both an off-by-one offset and a
 * loop that never terminates.
 */
describe('the generated register fetching a real second page', () => {
  it('appends the next page and stops offering once it holds them all', async () => {
    const user = userEvent.setup();
    records
      .mockResolvedValueOnce({ items: [ROW], total: 2 })
      .mockResolvedValueOnce({ items: [ROW_B], total: 2 });
    renderPage();
    await screen.findByTestId('runtime-module-table');
    expect(screen.getByTestId('runtime-module-count').textContent).toBe('Showing 1 of 2');

    await user.click(screen.getByTestId('runtime-module-more'));

    await waitFor(() =>
      expect(screen.getByTestId('runtime-module-count').textContent).toBe('Showing 2 of 2'),
    );
    expect(screen.getByText('P-014')).toBeTruthy();
    expect(screen.getByText('A-001')).toBeTruthy();
    // Nothing left to ask for, so the control goes and sorting becomes real.
    expect(screen.queryByTestId('runtime-module-more')).toBeNull();
    expect(screen.getByTestId('runtime-module-sort-cost')).toBeTruthy();
    expect(records).toHaveBeenCalledTimes(2);
    // Offset is the count already held, not the page number.
    expect(records).toHaveBeenLastCalledWith(BASE_PATH, { projectId: 'p1', limit: 200, offset: 1 });
  });

  it('pulls the unread pages in before it answers a search', async () => {
    const user = userEvent.setup();
    records
      .mockResolvedValueOnce({ items: [ROW], total: 2 })
      .mockResolvedValueOnce({ items: [ROW_B], total: 2 });
    renderPage();
    await screen.findByTestId('runtime-module-table');

    // A-001 is on the page that has not been read yet. Before this, the search
    // would have said nothing found about a record that exists, which is the
    // whole reason the auto-load is there.
    await user.type(screen.getByTestId('runtime-module-search'), 'A-001');

    await waitFor(() => expect(records).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText('A-001')).toBeTruthy());
    expect(screen.queryByText('P-014')).toBeNull();
  });
});

/**
 * The functions a module can carry: a status, a deadline, links to other
 * records, an export and comments. Each is read off the spec, so a module
 * without one must show none of its controls.
 */
const FEATURED: ModuleUiSpec = {
  ...SPEC,
  schema_version: 2,
  entity: {
    ...SPEC.entity,
    // Two columns out of the table, so the link fits under the column cap.
    fields: [
      ...SPEC.entity.fields.map((f) => (f.name === 'cost' || f.name === 'mix' ? { ...f, in_list: false } : f)),
      { name: 'contract', label: 'Contract', type: 'link', target: 'contract', required: false, help_text: '', unit: '', options: [], in_list: true },
    ],
  },
  features: {
    status: {
      states: [
        { code: 'planned', label: 'Planned', done: false },
        { code: 'poured', label: 'Poured', done: false },
        { code: 'approved', label: 'Approved', done: true },
      ],
    },
    due: { field: 'poured_on', remind_days_before: 3 },
    export: true,
    comments: true,
  },
};

const PLANNED: GeneratedRecord = { ...ROW, id: 'rec-p', reference: 'P-100', status: 'planned', poured_on: '2020-01-01', contract: 'c-1' };
const APPROVED: GeneratedRecord = { ...ROW, id: 'rec-a', reference: 'P-200', status: 'approved', poured_on: '2020-01-01', contract: 'c-2' };

const labels = vi.mocked(lookupLabels);
const download = vi.mocked(downloadWithAuth);

describe('a module with functions switched on', () => {
  beforeEach(() => {
    uiSpec.mockResolvedValue(FEATURED);
    records.mockResolvedValue({ items: [PLANNED, APPROVED], total: 2 });
    labels.mockResolvedValue({ labels: { 'c-1': 'Frame works' } });
    download.mockResolvedValue(undefined);
  });

  it('shows the stage of every record as a badge', async () => {
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    expect(within(table).getByText('Planned')).toBeTruthy();
    expect(within(table).getByText('Approved')).toBeTruthy();
  });

  it('filters by stage, and All brings every row back', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('runtime-module-table');
    const chips = screen.getByTestId('runtime-module-status-filter');

    await user.click(within(chips).getByRole('button', { name: /Approved/ }));
    await waitFor(() => expect(screen.getByTestId('runtime-module-count').textContent).toBe('Showing 1 of 2'));
    expect(screen.queryByText('P-100')).toBeNull();
    expect(screen.getByText('P-200')).toBeTruthy();

    await user.click(within(chips).getByRole('button', { name: /All/ }));
    await waitFor(() => expect(screen.getByTestId('runtime-module-count').textContent).toBe('Showing 2 of 2'));
  });

  it('names linked records, asking once per target, and says which it may not show', async () => {
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    expect(await within(table).findByText('Frame works')).toBeTruthy();
    expect(within(table).getByText('Not visible to you')).toBeTruthy();
    expect(within(table).queryByText('c-1')).toBeNull();
    expect(labels).toHaveBeenCalledTimes(1);
    expect(labels).toHaveBeenCalledWith('contract', ['c-1', 'c-2']);
  });

  it('marks an overdue date, unless the record is finished', async () => {
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    const planned = within(table).getByText('P-100').closest('tr');
    const approved = within(table).getByText('P-200').closest('tr');
    expect(planned?.querySelector('[data-due="overdue"]')).not.toBeNull();
    expect(approved?.querySelector('[data-due]')).toBeNull();
  });

  it('exports the register of this project', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('runtime-module-table');
    await user.click(screen.getByTestId('runtime-module-export'));
    await user.click(screen.getByTestId('runtime-module-export-xlsx'));
    await waitFor(() =>
      expect(download).toHaveBeenCalledWith(`${BASE_PATH}/export?format=xlsx&project_id=p1`, 'pour_register.xlsx'),
    );
  });

  it('offers comments on a record that exists, for that record', async () => {
    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    await user.click(within(table).getAllByLabelText('Edit')[0]!);
    expect(await screen.findByTestId('comment-thread')).toHaveTextContent('built.pour_register/rec-p');
  });

  it('moves a record on to the next stage from the form', async () => {
    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    await user.click(within(table).getAllByLabelText('Edit')[0]!);
    const picker = await screen.findByTestId('runtime-module-status-picker');
    await user.click(within(picker).getByRole('radio', { name: 'Poured' }));
    await user.click(screen.getByTestId('runtime-module-save'));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0]?.[2]).toEqual({ status: 'poured' });
  });
});

describe('a module with no functions switched on', () => {
  it('shows none of their controls', async () => {
    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByTestId('runtime-module-table');
    expect(screen.queryByTestId('runtime-module-export')).toBeNull();
    expect(screen.queryByTestId('runtime-module-status-filter')).toBeNull();
    await user.click(within(table).getByLabelText('Edit'));
    await screen.findByLabelText(/Pour reference/);
    expect(screen.queryByTestId('runtime-module-comments')).toBeNull();
    expect(screen.queryByTestId('runtime-module-status-picker')).toBeNull();
  });
});
