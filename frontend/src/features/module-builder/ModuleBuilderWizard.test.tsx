// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Building a register by clicking through the wizard.
 *
 * The path that matters is the one a person actually takes: describe it or
 * pick a template, look at the summary, maybe tick a suggestion, create. Each
 * test walks part of it with real clicks rather than by setting state,
 * because the failures worth catching here are the ones where a screen lets
 * you past something the server will refuse - and that only shows up when the
 * button is pressed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const navigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigate, useParams: () => ({}) };
});

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    fetchVocabulary: vi.fn(),
    fetchInstalledModules: vi.fn(),
    draftSpec: vi.fn(),
    suggestForSpec: vi.fn(),
    previewModule: vi.fn(),
    installModule: vi.fn(),
  };
});

import { ApiError } from '@/shared/lib/api';

import {
  draftSpec,
  fetchInstalledModules,
  fetchVocabulary,
  installModule,
  previewModule,
  suggestForSpec,
  type InstalledModule,
  type ModuleSpec,
  type PreviewResponse,
  type Suggestion,
  type Vocabulary,
} from './api';
import { ModuleBuilderWizard } from './ModuleBuilderWizard';

const vocabulary = vi.mocked(fetchVocabulary);
const installedList = vi.mocked(fetchInstalledModules);
const draft = vi.mocked(draftSpec);
const suggest = vi.mocked(suggestForSpec);
const preview = vi.mocked(previewModule);
const install = vi.mocked(installModule);

/** A server from before links and features: the request shapes must stay the old ones. */
const VOCABULARY: Vocabulary = {
  field_types: [
    { type: 'text', label: 'Text', hint: 'A short line.' },
    { type: 'number', label: 'Quantity', hint: 'A measured amount.' },
    { type: 'money', label: 'Money', hint: 'Kept exact.' },
    { type: 'date', label: 'Date', hint: 'A day.' },
  ],
  rule_kinds: [
    { kind: 'required', label: 'Must be filled in', hint: '', applies_to: ['text', 'number', 'money', 'date'], needs_other_field: false, needs_bounds: false },
    { kind: 'positive', label: 'Must be above zero', hint: '', applies_to: ['number', 'money'], needs_other_field: false, needs_bounds: false },
    { kind: 'range', label: 'Between two values', hint: '', applies_to: ['number', 'money'], needs_other_field: false, needs_bounds: true },
  ],
  reserved_field_names: ['id', 'metadata', 'project_id'],
  reserved_keys: ['boq', 'costs'],
  max_fields: 40,
  assistant_available: true,
};

/** The current server: links and features are understood. */
const VOCABULARY_V2: Vocabulary = {
  ...VOCABULARY,
  field_types: [...VOCABULARY.field_types, { type: 'link', label: 'Link', hint: 'A record elsewhere.' }],
  reserved_field_names: [...VOCABULARY.reserved_field_names, 'status'],
  link_targets: [
    { target: 'contract', module: 'oe_contracts', available: true },
    { target: 'contact', module: 'oe_contacts', available: true },
    { target: 'document', module: 'oe_documents', available: false },
  ],
  features: ['status', 'due', 'export', 'comments'],
};

const DRAFTED: ModuleSpec = {
  key: 'pour_register',
  display_name: 'Pour Register',
  description: 'Every concrete pour on the job.',
  category: 'community',
  icon: 'Boxes',
  version: '0.1.0',
  author: '',
  // This fixture is what /draft returns, so it carries the mark the wizard renders.
  drafted_by: 'assistant',
  entity: {
    name: 'pour',
    display_name: 'Pour',
    plural_name: 'Pours',
    project_scoped: true,
    fields: [
      { name: 'reference', label: 'Reference', type: 'text', required: true, help_text: '', unit: '', options: [], in_list: true },
      { name: 'volume', label: 'Volume', type: 'number', required: false, help_text: '', unit: 'm3', options: [], in_list: true },
      { name: 'poured_on', label: 'Poured on', type: 'date', required: false, help_text: '', unit: '', options: [], in_list: true },
    ],
  },
  rules: [
    { code: 'VOLUME_POSITIVE', message: 'A pour of nothing is not a pour.', kind: 'positive', field: 'volume', min_value: null, max_value: null, other_field: '', severity: 'error' },
  ],
};

const LINK_CONTRACT: Suggestion = {
  id: 'link:contract',
  kind: 'link',
  target: 'contract',
  confidence: 'high',
  reason: 'The pours are billed against a contract.',
  patch: {
    field: { name: 'contract', label: 'Contract', type: 'link', target: 'contract', required: false, help_text: '', unit: '', options: [], in_list: true },
  },
};

const LINK_DOCUMENT: Suggestion = {
  id: 'link:document',
  kind: 'link',
  target: 'document',
  confidence: 'low',
  reason_code: 'link_module_name',
  patch: {
    field: { name: 'document', label: 'Delivery ticket', type: 'link', target: 'document', required: false, help_text: '', unit: '', options: [], in_list: true },
  },
};

const STATUS: Suggestion = {
  id: 'feature:status',
  kind: 'feature',
  feature: 'status',
  confidence: 'medium',
  reason_code: 'status_register',
  patch: {
    status: {
      states: [
        { code: 'open', label: 'Open', done: false },
        { code: 'in_progress', label: 'In progress', done: false },
        { code: 'done', label: 'Done', done: true },
      ],
    },
  },
};

const PREVIEW: PreviewResponse = {
  spec: DRAFTED,
  files: [
    { path: 'manifest.py', lines: 24, content: '' },
    { path: 'models.py', lines: 51, content: '' },
    { path: 'router.py', lines: 96, content: '' },
  ],
  total_lines: 171,
  base_path: '/api/v1/pour-register',
  review_token: 'issued-for-this-preview',
};

const INSTALLED: InstalledModule = {
  key: 'pour_register',
  module_name: 'oe_pour_register',
  display_name: 'Pour Register',
  version: '0.1.0',
  generated_at: '2026-08-07T00:00:00Z',
  entity: 'Pour',
  field_count: 3,
  rule_count: 1,
  base_path: '/api/v1/pour-register',
};

function renderWizard(onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ModuleBuilderWizard open onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onClose };
}

type User = ReturnType<typeof userEvent.setup>;

/** Describe it in a sentence and land on the review screen. */
async function draftIt(user: User) {
  await user.click(await screen.findByTestId('module-builder-description'));
  await user.paste('A register of every concrete pour on the job.');
  await user.click(screen.getByTestId('module-builder-draft'));
  await screen.findByTestId('module-builder-proposal');
}

async function openFineTune(user: User) {
  await user.click(screen.getByTestId('module-builder-fine-tune'));
  await screen.findByTestId('module-builder-fine-tune-body');
}

async function openAdvanced(user: User) {
  await user.click(screen.getByTestId('module-builder-advanced'));
  await screen.findByTestId('module-builder-key');
}

/** From a fresh wizard to the create screen with its preview in. */
async function toCreate(user: User) {
  await draftIt(user);
  await user.click(screen.getByTestId('module-builder-next'));
  await screen.findByTestId('module-builder-create');
  await waitFor(() => expect(screen.getByTestId('module-builder-install')).not.toBeDisabled());
}

function suggestionCard(id: string) {
  return screen.getByTestId(`module-builder-suggestion-${id}`);
}

beforeEach(() => {
  vi.clearAllMocks();
  vocabulary.mockResolvedValue(VOCABULARY);
  installedList.mockResolvedValue({ items: [], total: 0, runtime_root: '/tmp' });
  draft.mockResolvedValue({ spec: DRAFTED, source: 'assistant' });
  suggest.mockResolvedValue({ suggestions: [] });
  preview.mockResolvedValue(PREVIEW);
  install.mockResolvedValue(INSTALLED);
});

describe('the first screen', () => {
  it('asks one plain question and offers the assistant only when one is connected', async () => {
    renderWizard();
    expect(await screen.findByText('What do you want to keep track of?')).toBeTruthy();
    expect(await screen.findByTestId('module-builder-draft')).toBeTruthy();
  });

  it('is never a dead end without an AI provider: templates and a blank start remain', async () => {
    vocabulary.mockResolvedValue({ ...VOCABULARY, assistant_available: false });
    const user = userEvent.setup();
    renderWizard();
    expect(await screen.findByText(/No AI is connected/i)).toBeTruthy();
    expect(screen.queryByTestId('module-builder-draft')).toBeNull();
    expect(screen.queryByTestId('module-builder-description')).toBeNull();
    expect(screen.getByTestId('module-builder-template-concrete_pours')).toBeTruthy();

    await user.click(screen.getByTestId('module-builder-scratch'));
    expect(await screen.findByTestId('module-builder-name')).toBeTruthy();
  });

  it('offers all six templates', async () => {
    renderWizard();
    await screen.findByTestId('module-builder-template-concrete_pours');
    for (const id of ['work_permits', 'site_measurements', 'material_deliveries', 'site_diary', 'safety_briefings']) {
      expect(screen.getByTestId(`module-builder-template-${id}`)).toBeTruthy();
    }
  });

  it('shows a calm progress state while the assistant drafts', async () => {
    draft.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-description'));
    await user.paste('A register of every concrete pour on the job.');
    await user.click(screen.getByTestId('module-builder-draft'));
    expect(await screen.findByTestId('module-builder-drafting')).toBeTruthy();
    expect(screen.getByText(/up to 20 seconds/)).toBeTruthy();
  });

  it('shows the assistant refusal instead of burying it in a toast', async () => {
    draft.mockRejectedValue(new ApiError(422, 'Unprocessable Entity', { detail: 'That is not a register.' }));
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-description'));
    await user.paste('make me a sandwich please');
    await user.click(screen.getByTestId('module-builder-draft'));
    expect(await screen.findByRole('alert')).toHaveTextContent('That is not a register.');
  });

  it('sends the old request to a server that does not know the locale field', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    expect(draft).toHaveBeenCalledWith('A register of every concrete pour on the job.');
  });

  it('asks a current server to write in the reader language', async () => {
    vocabulary.mockResolvedValue(VOCABULARY_V2);
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    expect(draft).toHaveBeenCalledWith('A register of every concrete pour on the job.', 'en');
  });
});

describe('a template', () => {
  it('fills the summary in the reader language and lands on the review screen', async () => {
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-template-concrete_pours'));

    expect(screen.getByTestId('module-builder-name')).toHaveProperty('value', 'Concrete pours');
    const chips = screen.getByTestId('module-builder-field-chips');
    expect(within(chips).getByText('Pour reference')).toBeTruthy();
    expect(within(screen.getByTestId('module-builder-check-list')).getByText(/before it happened/)).toBeTruthy();
    // A template is complete: the primary button is ready to press.
    expect(screen.getByTestId('module-builder-next')).not.toBeDisabled();
  });

  it('steps around a module already installed here rather than failing at install', async () => {
    installedList.mockResolvedValue({
      items: [{ ...INSTALLED, key: 'concrete_pours' }],
      total: 1,
      runtime_root: '/tmp',
    });
    const user = userEvent.setup();
    renderWizard();
    // The installed list has to be in before the template is picked.
    await waitFor(() => expect(installedList).toHaveBeenCalled());
    await user.click(await screen.findByTestId('module-builder-template-concrete_pours'));
    await openFineTune(user);
    await openAdvanced(user);
    expect(screen.getByTestId('module-builder-key')).toHaveProperty('value', 'concrete_pours_2');
  });

  it('brings its own suggestions, none of them switched on', async () => {
    vocabulary.mockResolvedValue(VOCABULARY_V2);
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-template-work_permits'));

    const card = await screen.findByTestId('module-builder-suggestion-feature:status');
    expect(card.getAttribute('data-applied')).toBe('false');
    expect(suggestionCard('feature:due').getAttribute('data-applied')).toBe('false');
    // The server's rules are asked too, for the template's spec.
    await waitFor(() => expect(suggest).toHaveBeenCalled());
    expect(suggest.mock.calls[0]?.[0].key).toBe('work_permits');
  });

  it('shows no suggestions to a server that cannot install them', async () => {
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-template-work_permits'));
    await screen.findByTestId('module-builder-proposal');
    expect(screen.queryByTestId('module-builder-suggestions')).toBeNull();
    expect(suggest).not.toHaveBeenCalled();
  });
});

describe('suggestions', () => {
  beforeEach(() => {
    vocabulary.mockResolvedValue(VOCABULARY_V2);
    draft.mockResolvedValue({ spec: DRAFTED, source: 'assistant', suggestions: [LINK_CONTRACT] });
    suggest.mockResolvedValue({ suggestions: [LINK_CONTRACT, STATUS, LINK_DOCUMENT] });
  });

  it('merges the assistant and the rules by id, and applies none of them', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await screen.findByTestId('module-builder-suggestion-feature:status');

    expect(screen.getAllByTestId('module-builder-suggestion-link:contract')).toHaveLength(1);
    for (const id of ['link:contract', 'feature:status']) {
      expect(suggestionCard(id).getAttribute('data-applied')).toBe('false');
    }
    // The assistant's own sentence, and a band rather than a fake percentage.
    expect(within(suggestionCard('link:contract')).getByText('The pours are billed against a contract.')).toBeTruthy();
    expect(within(suggestionCard('link:contract')).getByText('High confidence')).toBeTruthy();
  });

  it('applies a suggestion when ticked and takes it back when unticked', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    const chips = screen.getByTestId('module-builder-field-chips');
    expect(within(chips).queryByText('Contract')).toBeNull();

    await user.click(within(suggestionCard('link:contract')).getByRole('switch'));
    expect(within(chips).getByText('Contract')).toBeTruthy();
    expect(suggestionCard('link:contract').getAttribute('data-applied')).toBe('true');

    await user.click(within(suggestionCard('link:contract')).getByRole('switch'));
    expect(within(chips).queryByText('Contract')).toBeNull();
  });

  it('accepts everything that can be applied in one click', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await screen.findByTestId('module-builder-suggestion-feature:status');
    await user.click(screen.getByTestId('module-builder-accept-all'));

    expect(suggestionCard('link:contract').getAttribute('data-applied')).toBe('true');
    expect(suggestionCard('feature:status').getAttribute('data-applied')).toBe('true');
    // The document module is switched off here, so that one stays off.
    expect(suggestionCard('link:document').getAttribute('data-applied')).toBe('false');
    expect(within(suggestionCard('link:document')).getByRole('switch')).toBeDisabled();
  });

  it('keeps going when the suggestion service fails', async () => {
    suggest.mockRejectedValue(new Error('down'));
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await waitFor(() => expect(suggest).toHaveBeenCalled());
    expect(screen.getByTestId('module-builder-next')).not.toBeDisabled();
  });

  it('works with a server whose draft carries no suggestions', async () => {
    draft.mockResolvedValue({ spec: DRAFTED });
    suggest.mockResolvedValue({ suggestions: [] });
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    expect(screen.queryByTestId('module-builder-suggestions')).toBeNull();
    expect(screen.getByTestId('module-builder-next')).not.toBeDisabled();
  });
});

describe('the review screen', () => {
  it('marks a drafted specification and leaves a hand-built one unmarked', async () => {
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-scratch'));
    expect(screen.queryByTestId('module-builder-ai-mark')).toBeNull();
    await user.click(screen.getByTestId('module-builder-step-describe'));
    await draftIt(user);
    expect(screen.getByTestId('module-builder-ai-mark')).toBeTruthy();
  });

  it('names the key from the module name so nobody has to invent one', async () => {
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-scratch'));
    await user.click(screen.getByTestId('module-builder-name'));
    await user.paste('Concrete Pour Register');
    await openAdvanced(user);
    expect(screen.getByTestId('module-builder-key')).toHaveProperty('value', 'concrete_pour_register');
  });

  it('gives a name with no Latin letters a key the server accepts', async () => {
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-scratch'));
    await user.click(screen.getByTestId('module-builder-name'));
    await user.paste('Журнал бетонирования');
    await openAdvanced(user);
    const key = (screen.getByTestId('module-builder-key') as HTMLInputElement).value;
    expect(key).toMatch(/^register_[a-z0-9]+$/);
    expect(screen.queryByTestId('module-builder-key-problems')).toBeNull();
  });

  it('stops leaning on the name once the key has been typed over', async () => {
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-scratch'));
    await user.click(screen.getByTestId('module-builder-name'));
    await user.paste('Pour Register');
    await openAdvanced(user);
    await user.clear(screen.getByTestId('module-builder-key'));
    await user.paste('pours');
    await user.click(screen.getByTestId('module-builder-name'));
    await user.paste(' v2');
    expect(screen.getByTestId('module-builder-key')).toHaveProperty('value', 'pours');
  });

  it('refuses a key a shipped module already owns, says so under Advanced, and blocks creating', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await openFineTune(user);
    await openAdvanced(user);
    await user.clear(screen.getByTestId('module-builder-key'));
    await user.paste('boq');
    expect(
      within(screen.getByTestId('module-builder-key-problems')).getByText(/part of the platform is already called/i),
    ).toBeTruthy();
    expect(screen.getByTestId('module-builder-next')).toBeDisabled();
  });

  it('points at what needs attention while Fine-tune is closed', async () => {
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-scratch'));
    // A blank start opens Fine-tune; close it to see the summary line.
    await user.click(screen.getByTestId('module-builder-fine-tune'));
    expect(screen.getByTestId('module-builder-problems')).toBeTruthy();
    await user.click(screen.getByTestId('module-builder-show-problems'));
    expect(screen.getByTestId('module-builder-fine-tune-body')).toBeTruthy();
  });

  it('will not move on with no checks at all, and offers one in a click', async () => {
    const user = userEvent.setup();
    renderWizard();
    await user.click(await screen.findByTestId('module-builder-scratch'));
    await user.click(screen.getByTestId('module-builder-name'));
    await user.paste('Pour Register');
    await user.click(screen.getByTestId('module-builder-field-label-0'));
    await user.paste('Reference');

    expect(screen.getAllByText(/checks at least one thing before an entry is saved/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId('module-builder-next')).toBeDisabled();

    await user.click(screen.getByTestId('module-builder-quick-rule'));
    expect(within(screen.getByTestId('module-builder-check-list')).getByText('Reference must be filled in.')).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId('module-builder-next')).not.toBeDisabled());
  });

  it('will not move on with a field that has no label', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await openFineTune(user);
    await user.click(screen.getByTestId('module-builder-add-field'));
    expect(await screen.findByText(/needs a label/i)).toBeTruthy();
    expect(screen.getByTestId('module-builder-next')).toBeDisabled();
  });

  it('offers exactly the field types the server said it may', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await openFineTune(user);
    const select = screen.getByTestId('module-builder-field-type-0');
    const offered = within(select).getAllByRole('option').map((o) => o.textContent);
    expect(offered).toEqual(['Text', 'Quantity', 'Money', 'Date']);
  });

  it('names a new column from its label, around the names the platform reserves', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await openFineTune(user);
    await user.click(screen.getByTestId('module-builder-add-field'));
    await user.click(screen.getByTestId('module-builder-field-label-3'));
    await user.paste('Metadata');
    await openAdvanced(user);
    // Nobody on the simple path should meet "reserved"; the name steps aside.
    expect(screen.getByTestId('module-builder-field-name-3')).toHaveProperty('value', 'metadata_2');
    expect(screen.queryByText(/already keeps/i)).toBeNull();
  });

  it('refuses a column name the generated record already uses, when typed by hand', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await openFineTune(user);
    await openAdvanced(user);
    await user.clear(screen.getByTestId('module-builder-field-name-0'));
    await user.paste('metadata');
    expect(await screen.findByText(/already keeps/i)).toBeTruthy();
    expect(screen.getByTestId('module-builder-next')).toBeDisabled();
  });

  it('fills a new check with a sentence so it works the moment it is added', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await openFineTune(user);
    await user.click(screen.getByTestId('module-builder-add-rule-required'));
    expect(screen.getByTestId('module-builder-rule-message-1')).toHaveProperty('value', 'Reference must be filled in.');

    // Blanking it is still refused: a check needs a message that tells people what to fix.
    await user.clear(screen.getByTestId('module-builder-rule-message-1'));
    expect(await screen.findByText(/tells people what to fix/i)).toBeTruthy();
    expect(screen.getByTestId('module-builder-next')).toBeDisabled();
  });

  it('offers only the checks that can apply to the chosen field', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await openFineTune(user);
    expect(screen.getByTestId('module-builder-add-rule-required')).toBeTruthy();
    expect(screen.queryByTestId('module-builder-add-rule-positive')).toBeNull();
    await user.selectOptions(screen.getByTestId('module-builder-rule-field'), 'volume');
    expect(await screen.findByTestId('module-builder-add-rule-positive')).toBeTruthy();
  });
});

describe('the table preview', () => {
  it('shows the columns the register would open on, with no values in the rows at all', async () => {
    // The load-bearing one. A plausible sample row reads as a real record on
    // the screen where somebody decides whether the module is right.
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await openFineTune(user);

    const table = within(screen.getByTestId('module-builder-preview')).getByRole('table');
    expect(within(table).getByText('Reference')).toBeTruthy();
    expect(within(table).getByText('m3')).toBeTruthy();
    const body = table.querySelector('tbody');
    expect(body?.querySelectorAll('tr').length).toBeGreaterThan(0);
    expect(body?.textContent?.trim()).toBe('');
  });

  it('says the register would open empty when no field is shown in the table', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await openFineTune(user);
    for (const i of [0, 1, 2]) await user.click(screen.getByTestId(`module-builder-field-in-list-${i}`));
    expect(screen.getByTestId('module-builder-preview-empty')).toBeTruthy();
  });
});

describe('the create screen', () => {
  it('previews on arrival and keeps the files and the URL one click away', async () => {
    const user = userEvent.setup();
    renderWizard();
    await toCreate(user);

    expect(preview).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('manifest.py')).toBeNull();
    await user.click(screen.getByTestId('module-builder-what-created'));
    const review = screen.getByTestId('module-builder-review');
    expect(within(review).getByText(/3 files, 171 lines/)).toBeTruthy();
    expect(within(review).getByText('router.py')).toBeTruthy();
    expect(within(review).getByText(/\/api\/v1\/pour-register/)).toBeTruthy();
    expect(install).not.toHaveBeenCalled();
  });

  it('sends the old spec shape to a server from before features', async () => {
    const user = userEvent.setup();
    renderWizard();
    await toCreate(user);
    const sent = preview.mock.calls[0]?.[0];
    expect(sent?.entity.plural_name).toBe('Pours');
    expect(sent).not.toHaveProperty('features');
    expect(sent).not.toHaveProperty('schema_version');
  });

  it('sends features and links to a current server, and target only on a link', async () => {
    vocabulary.mockResolvedValue(VOCABULARY_V2);
    suggest.mockResolvedValue({ suggestions: [LINK_CONTRACT] });
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    await user.click(within(await screen.findByTestId('module-builder-suggestion-link:contract')).getByRole('switch'));
    await user.click(screen.getByTestId('module-builder-next'));
    await waitFor(() => expect(preview).toHaveBeenCalled());

    const sent = preview.mock.calls[0]?.[0] as ModuleSpec;
    expect(sent.schema_version).toBe(2);
    expect(sent.features).toEqual({ status: null, due: null, export: false, comments: false });
    const link = sent.entity.fields.find((f) => f.type === 'link');
    expect(link?.target).toBe('contract');
    expect(sent.entity.fields.find((f) => f.name === 'reference')).not.toHaveProperty('target');
  });

  it('installs with the token of the preview, then offers to open the module', async () => {
    const user = userEvent.setup();
    const { onClose } = renderWizard();
    await toCreate(user);
    await user.click(screen.getByTestId('module-builder-install'));

    await screen.findByTestId('module-builder-done');
    expect(install).toHaveBeenCalledWith(PREVIEW.spec, 'issued-for-this-preview');
    expect(screen.getByText(/ready to use/i)).toBeTruthy();

    await user.click(screen.getByTestId('module-builder-open'));
    expect(navigate).toHaveBeenCalledWith('/modules/pour_register');
    expect(onClose).toHaveBeenCalled();
  });

  it('previews again when the spec changed since the last preview, and installs with the new token', async () => {
    const renamed = { ...PREVIEW, review_token: 'issued-for-the-rename' };
    preview.mockResolvedValueOnce(PREVIEW).mockResolvedValueOnce(renamed);
    const user = userEvent.setup();
    renderWizard();
    await toCreate(user);

    await user.click(screen.getByTestId('module-builder-step-proposal'));
    await user.click(screen.getByTestId('module-builder-name'));
    await user.paste(' 2026');
    await user.click(screen.getByTestId('module-builder-next'));
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2));
    expect(preview.mock.calls[1]?.[0].display_name).toBe('Pour Register 2026');

    await waitFor(() => expect(screen.getByTestId('module-builder-install')).not.toBeDisabled());
    await user.click(screen.getByTestId('module-builder-install'));
    await waitFor(() => expect(install).toHaveBeenCalledWith(renamed.spec, 'issued-for-the-rename'));
  });

  it('does not preview again when nothing changed', async () => {
    const user = userEvent.setup();
    renderWizard();
    await toCreate(user);
    await user.click(screen.getByTestId('module-builder-step-proposal'));
    await user.click(screen.getByTestId('module-builder-next'));
    await waitFor(() => expect(screen.getByTestId('module-builder-install')).not.toBeDisabled());
    expect(preview).toHaveBeenCalledTimes(1);
  });

  it('stays on the create screen and says why when the install is refused', async () => {
    install.mockRejectedValue(new ApiError(409, 'Conflict', { detail: 'A module with that key is already installed.' }));
    const user = userEvent.setup();
    renderWizard();
    await toCreate(user);
    await user.click(screen.getByTestId('module-builder-install'));

    expect(await screen.findByRole('alert')).toHaveTextContent('A module with that key is already installed.');
    expect(screen.queryByTestId('module-builder-done')).toBeNull();
    expect(screen.getByTestId('module-builder-install')).toBeTruthy();
  });

  it('says in words which kept entries a rebuild under the same name would clash with', async () => {
    install.mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: {
          code: 'layout_conflict',
          message: 'The table oe_pour_register_pour already exists with a different layout.',
          params: {
            records: 7,
            fields: [
              { name: 'poured_on', label: 'Poured on', problem: 'changed' },
              { name: 'volume', label: 'Volume', problem: 'new_required' },
            ],
          },
        },
      }),
    );
    const user = userEvent.setup();
    renderWizard();
    await toCreate(user);
    await user.click(screen.getByTestId('module-builder-install'));

    const refused = await screen.findByTestId('module-builder-upgrade-refused');
    expect(refused.getAttribute('data-code')).toBe('layout_conflict');
    expect(refused.textContent).toMatch(/Entries are already kept under this name/);
    expect(refused.textContent).toMatch(/7 entries/);
    const problems = within(refused).getByTestId('module-builder-upgrade-problems');
    expect(problems.textContent).toMatch(/kind of value Poured on holds/);
    expect(problems.textContent).toMatch(/Volume is new and must be filled in/);
    // The server's own sentence names a table; the screen speaks in fields.
    expect(refused.textContent).not.toMatch(/oe_pour_register_pour/);
    expect(screen.queryByTestId('module-builder-done')).toBeNull();
  });
});

describe('the step rail', () => {
  it('goes back to a finished step in one press, and offers no step ahead', async () => {
    const user = userEvent.setup();
    renderWizard();
    await draftIt(user);
    expect(screen.queryByTestId('module-builder-step-create')).toBeNull();
    expect(screen.queryByTestId('module-builder-step-proposal')).toBeNull();
    await user.click(screen.getByTestId('module-builder-step-describe'));
    expect(screen.getByTestId('module-builder-description')).toBeTruthy();
  });
});
