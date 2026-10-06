// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Adding fields and functions to a module that is already installed.
 *
 * The promise under test is that the wizard never offers a change the server
 * would refuse on a module holding records: what entries hold is locked (a
 * field's kind and name, its choices, the stages), wording stays editable,
 * the update goes out under the same key with the token of its own preview,
 * and the module's page is told to read itself again. The server's refusal is
 * still shown in words if it ever comes back.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => vi.fn() };
});

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    fetchVocabulary: vi.fn(),
    fetchInstalledModules: vi.fn(),
    fetchModuleUiSpec: vi.fn(),
    suggestForSpec: vi.fn(),
    previewModule: vi.fn(),
    installModule: vi.fn(),
    previewUpgrade: vi.fn(),
    upgradeModule: vi.fn(),
  };
});

const role = vi.hoisted(() => ({ current: 'admin' }));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (select: (s: { userRole: string }) => unknown) => select({ userRole: role.current }),
}));

import { ApiError } from '@/shared/lib/api';

import {
  RUNTIME_MODULE_QUERY_KEY,
  fetchInstalledModules,
  fetchModuleUiSpec,
  fetchVocabulary,
  installModule,
  previewModule,
  previewUpgrade,
  suggestForSpec,
  upgradeModule,
  type InstalledModule,
  type ModuleSpec,
  type PreviewResponse,
  type Suggestion,
  type UpgradeResult,
  type Vocabulary,
} from './api';
import { ExtendModuleButton } from './ExtendModuleButton';
import { ModuleBuilderWizard } from './ModuleBuilderWizard';

const VOCABULARY: Vocabulary = {
  field_types: [
    { type: 'text', label: 'Text', hint: '' },
    { type: 'number', label: 'Quantity', hint: '' },
    { type: 'date', label: 'Date', hint: '' },
    { type: 'link', label: 'Link', hint: '' },
    { type: 'select', label: 'Choice', hint: '' },
  ],
  rule_kinds: [
    { kind: 'required', label: 'Must be filled in', hint: '', applies_to: ['text', 'number', 'date'], needs_other_field: false, needs_bounds: false },
  ],
  reserved_field_names: ['id', 'metadata', 'project_id'],
  reserved_keys: ['boq'],
  max_fields: 40,
  assistant_available: false,
  link_targets: [{ target: 'contract', module: 'oe_contracts', available: true }],
  features: ['status', 'due', 'export', 'comments'],
  upgrade: true,
};

const INSTALLED_SPEC: ModuleSpec & { generated_at: string } = {
  key: 'pour_register',
  display_name: 'Pour Register',
  description: 'Every concrete pour on the job.',
  category: 'community',
  icon: 'Boxes',
  version: '0.1.0',
  author: '',
  drafted_by: 'wizard',
  schema_version: 2,
  entity: {
    name: 'pour',
    display_name: 'Pour',
    plural_name: 'Pours',
    project_scoped: true,
    fields: [
      { name: 'reference', label: 'Reference', type: 'text', required: true, help_text: '', unit: '', options: [], in_list: true },
      { name: 'poured_on', label: 'Poured on', type: 'date', required: false, help_text: '', unit: '', options: [], in_list: true },
    ],
  },
  rules: [
    { code: 'REFERENCE_REQUIRED', message: 'Give the pour a reference.', kind: 'required', field: 'reference', min_value: null, max_value: null, other_field: '', severity: 'error' },
  ],
  features: { status: null, due: null, export: true, comments: false },
  generated_at: '2026-10-01T00:00:00Z',
};

const MODULE: InstalledModule = {
  key: 'pour_register',
  module_name: 'oe_pour_register',
  display_name: 'Pour Register',
  version: '0.1.0',
  generated_at: '2026-10-01T00:00:00Z',
  entity: 'Pour',
  field_count: 2,
  rule_count: 1,
  base_path: '/api/v1/pour-register',
};

const UPDATED: UpgradeResult = {
  key: 'pour_register',
  module_name: 'oe_pour_register',
  base_path: '/api/v1/pour-register',
  record_count: 12,
  changes: [{ kind: 'field_added', field: 'volume' }],
};

const GRADE = {
  name: 'grade',
  label: 'Grade',
  type: 'select' as const,
  required: false,
  help_text: '',
  unit: '',
  options: ['C25/30', 'C30/37'],
  in_list: true,
};

const EXPORT: Suggestion = { id: 'feature:export', kind: 'feature', feature: 'export', confidence: 'medium', patch: { export: true } };
const COMMENTS: Suggestion = { id: 'feature:comments', kind: 'feature', feature: 'comments', confidence: 'medium', patch: { comments: true } };

function previewFor(spec: ModuleSpec): PreviewResponse {
  return { spec, files: [{ path: 'models.py', lines: 40, content: '' }], total_lines: 40, base_path: MODULE.base_path, review_token: 'upgrade-token' };
}

function renderUpgrade() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ModuleBuilderWizard open onClose={vi.fn()} upgrade={{ key: MODULE.key, basePath: MODULE.base_path }} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { invalidate };
}

type User = ReturnType<typeof userEvent.setup>;

/** Add one new number field called Volume. */
async function addVolume(user: User) {
  await user.click(screen.getByTestId('module-builder-add-field'));
  const label = screen.getByTestId('module-builder-field-label-2');
  await user.type(label, 'Volume');
}

beforeEach(() => {
  vi.clearAllMocks();
  role.current = 'admin';
  vi.mocked(fetchVocabulary).mockResolvedValue(VOCABULARY);
  vi.mocked(fetchInstalledModules).mockResolvedValue({ items: [MODULE], total: 1, runtime_root: '/tmp' });
  vi.mocked(fetchModuleUiSpec).mockResolvedValue(INSTALLED_SPEC);
  vi.mocked(suggestForSpec).mockResolvedValue({ suggestions: [EXPORT, COMMENTS] });
  vi.mocked(previewUpgrade).mockImplementation(async (_key, spec) => previewFor(spec));
  vi.mocked(upgradeModule).mockResolvedValue(UPDATED);
});

describe('opening on an installed module', () => {
  it('starts at Review with the module as it is, and never offers to describe it again', async () => {
    renderUpgrade();
    expect(await screen.findByTestId('module-builder-proposal')).toBeTruthy();
    expect(screen.queryByTestId('module-builder-description')).toBeNull();
    // A name is wording: it can change without touching a record.
    expect(screen.getByTestId('module-builder-name')).not.toBeDisabled();
    expect(fetchModuleUiSpec).toHaveBeenCalledWith(MODULE.base_path);
  });

  it('locks what entries hold in an installed field: its kind, its internal name, the field itself', async () => {
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    expect(screen.getByTestId('module-builder-field-locked-0')).toBeTruthy();
    expect(screen.getByTestId('module-builder-field-type-0')).toBeDisabled();
    expect(screen.queryByTestId('module-builder-remove-field-0')).toBeNull();
    expect(screen.getByTestId('module-builder-rule-locked-0')).toBeTruthy();

    await user.click(screen.getByTestId('module-builder-advanced'));
    expect(screen.getByTestId('module-builder-key')).toBeDisabled();
    expect(screen.getByTestId('module-builder-table-name')).toBeDisabled();
    expect(screen.getByTestId('module-builder-field-name-0')).toBeDisabled();
  });

  it('leaves the wording of an installed field and where it shows editable, and counts that as an update', async () => {
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    expect(screen.getByTestId('module-builder-field-in-list-0')).not.toBeDisabled();
    expect(screen.getByTestId('module-builder-field-required-1')).not.toBeDisabled();
    const label = screen.getByTestId('module-builder-field-label-1');
    expect(label).not.toBeDisabled();
    await user.clear(label);
    await user.type(label, 'Cast on');
    await user.type(screen.getByTestId('module-builder-name'), ' 2026');

    await user.click(screen.getByTestId('module-builder-next'));
    expect(await screen.findByTestId('module-builder-update-reworded')).toBeTruthy();
    expect(screen.queryByTestId('module-builder-update-additions')?.textContent ?? '').not.toMatch(/New fields/);
    await waitFor(() => expect(screen.getByTestId('module-builder-update')).not.toBeDisabled());
    const [key, sent] = vi.mocked(previewUpgrade).mock.calls.at(-1)!;
    // A new label is not a new column, and a new name is not a new module.
    expect(key).toBe('pour_register');
    expect(sent.key).toBe('pour_register');
    expect(sent.display_name).toBe('Pour Register 2026');
    expect(sent.entity.fields.map((f) => f.name)).toEqual(['reference', 'poured_on']);
    const field = sent.entity.fields.find((f) => f.name === 'poured_on');
    expect(field?.label).toBe('Cast on');
    expect(field?.type).toBe('date');
  });

  it('keeps the choices entries may hold, and lets new ones follow', async () => {
    vi.mocked(fetchModuleUiSpec).mockResolvedValue({
      ...INSTALLED_SPEC,
      entity: { ...INSTALLED_SPEC.entity, fields: [...INSTALLED_SPEC.entity.fields, GRADE] },
    });
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    const choices = screen.getByTestId('module-builder-field-options-2');
    const kept = within(choices).getAllByRole('textbox');
    expect(kept).toHaveLength(2);
    for (const input of kept) expect(input).toBeDisabled();
    expect(within(choices).queryByRole('button', { name: 'Remove' })).toBeNull();

    await user.click(screen.getByTestId('module-builder-add-option-2'));
    const added = within(choices).getAllByRole('textbox')[2]!;
    expect(added).not.toBeDisabled();
    await user.type(added, 'C35/45');
    expect(within(choices).getAllByRole('button', { name: 'Remove' })).toHaveLength(1);

    await user.click(screen.getByTestId('module-builder-next'));
    const listed = await screen.findByTestId('module-builder-update-choices');
    expect(listed.textContent).toMatch(/C35\/45 in Grade/);
    await waitFor(() => expect(screen.getByTestId('module-builder-update')).not.toBeDisabled());
    const [, sent] = vi.mocked(previewUpgrade).mock.calls.at(-1)!;
    expect(sent.entity.fields.find((f) => f.name === 'grade')?.options).toEqual(['C25/30', 'C30/37', 'C35/45']);
  });

  it('lets a new field be edited and removed like any other', async () => {
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    await addVolume(user);
    expect(screen.getByTestId('module-builder-field-type-2')).not.toBeDisabled();
    expect(screen.getByTestId('module-builder-remove-field-2')).toBeTruthy();
    expect(screen.queryByTestId('module-builder-field-locked-2')).toBeNull();
  });

  it('keeps a function already on switched on, and offers the rest', async () => {
    renderUpgrade();
    const exportCard = await screen.findByTestId('module-builder-suggestion-feature:export');
    expect(exportCard.getAttribute('data-locked')).toBe('true');
    expect(within(exportCard).getByRole('switch')).toBeDisabled();
    const comments = screen.getByTestId('module-builder-suggestion-feature:comments');
    expect(within(comments).getByRole('switch')).not.toBeDisabled();
  });
});

describe('a register with nothing recorded yet', () => {
  function holding(records: number) {
    vi.mocked(previewUpgrade).mockImplementation(async (_key, spec) => ({ ...previewFor(spec), record_count: records }));
  }

  it('lets anything change but the key and the internal name, and says why', async () => {
    holding(0);
    renderUpgrade();
    expect(await screen.findByTestId('module-builder-upgrade-empty')).toHaveTextContent(
      'Nothing is recorded yet, so you can change anything.',
    );
    expect(screen.queryByTestId('module-builder-field-locked-0')).toBeNull();
    expect(screen.getByTestId('module-builder-field-type-0')).not.toBeDisabled();
    expect(screen.getByTestId('module-builder-remove-field-1')).toBeTruthy();
    expect(screen.queryByTestId('module-builder-rule-locked-0')).toBeNull();
    const exportCard = await screen.findByTestId('module-builder-suggestion-feature:export');
    expect(within(exportCard).getByRole('switch')).not.toBeDisabled();

    const user = userEvent.setup();
    await user.click(screen.getByTestId('module-builder-advanced'));
    expect(screen.getByTestId('module-builder-key')).toBeDisabled();
    expect(screen.getByTestId('module-builder-table-name')).toBeDisabled();
    expect(screen.getByTestId('module-builder-field-name-0')).not.toBeDisabled();
  });

  it('takes a field away, says so, and sends the register as shown under the same key', async () => {
    holding(0);
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-upgrade-empty');
    await user.click(screen.getByTestId('module-builder-remove-field-1'));
    await user.click(screen.getByTestId('module-builder-next'));

    expect((await screen.findByTestId('module-builder-update-removed')).textContent).toMatch(/Poured on/);
    expect(screen.getByTestId('module-builder-update-note').textContent).toMatch(/Nothing is recorded yet/);
    await waitFor(() => expect(screen.getByTestId('module-builder-update')).not.toBeDisabled());
    const [key, sent] = vi.mocked(previewUpgrade).mock.calls.at(-1)!;
    expect(key).toBe('pour_register');
    expect(sent.entity.fields.map((f) => f.name)).toEqual(['reference']);
    await user.click(screen.getByTestId('module-builder-update'));
    await screen.findByTestId('module-builder-done');
    expect(upgradeModule).toHaveBeenCalledWith('pour_register', expect.objectContaining({ key: 'pour_register' }), 'upgrade-token');
  });

  it('keeps the locks once the module holds records', async () => {
    holding(3);
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    await waitFor(() => expect(previewUpgrade).toHaveBeenCalled());
    expect(screen.getByTestId('module-builder-field-type-0')).toBeDisabled();
    expect(screen.queryByTestId('module-builder-upgrade-empty')).toBeNull();
    expect(screen.queryByTestId('module-builder-remove-field-1')).toBeNull();
  });
});

describe('updating', () => {
  it('waits for something new before it can update', async () => {
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    // Only the count of records was asked for, with the module unchanged.
    await waitFor(() => expect(previewUpgrade).toHaveBeenCalledTimes(1));
    await user.click(screen.getByTestId('module-builder-next'));
    expect(await screen.findByTestId('module-builder-update-nothing')).toBeTruthy();
    expect(screen.getByTestId('module-builder-update')).toBeDisabled();
    expect(previewUpgrade).toHaveBeenCalledTimes(1);
  });

  it('says what is added, then updates under the same key with its own preview token', async () => {
    const user = userEvent.setup();
    const { invalidate } = renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    await addVolume(user);
    await user.click(screen.getByTestId('module-builder-next'));

    const additions = await screen.findByTestId('module-builder-update-additions');
    expect(within(additions).getByText('Volume')).toBeTruthy();
    expect(screen.getByTestId('module-builder-update-note').textContent).toMatch(/stay as they are/);
    await waitFor(() => expect(screen.getByTestId('module-builder-update')).not.toBeDisabled());

    const [key, sent] = vi.mocked(previewUpgrade).mock.calls.at(-1)!;
    expect(key).toBe('pour_register');
    expect(sent.key).toBe('pour_register');
    expect(sent.entity.fields.map((f) => f.name)).toEqual(['reference', 'poured_on', 'volume']);

    await user.click(screen.getByTestId('module-builder-update'));
    await screen.findByTestId('module-builder-done');
    expect(upgradeModule).toHaveBeenCalledWith('pour_register', expect.objectContaining({ key: 'pour_register' }), 'upgrade-token');
    expect(installModule).not.toHaveBeenCalled();
    expect(previewModule).not.toHaveBeenCalled();
    // The module's own page reads its new columns afresh.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: [RUNTIME_MODULE_QUERY_KEY] });
    expect(screen.getByText(/Your register is updated/)).toBeTruthy();
    // The answer carries no display name; the name the person sees is the spec's.
    expect(screen.getByTestId('module-builder-done').textContent).toMatch(/Pour Register/);
  });

  it('says in words why the server refused, how many entries are at stake, and what to do', async () => {
    vi.mocked(upgradeModule).mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: {
          code: 'upgrade_not_additive',
          message: 'This change is not additive.',
          params: { records: 12, problems: [{ code: 'field_retyped', field: 'poured_on', label: 'Poured on' }] },
        },
      }),
    );
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    await addVolume(user);
    await user.click(screen.getByTestId('module-builder-next'));
    await waitFor(() => expect(screen.getByTestId('module-builder-update')).not.toBeDisabled());
    await user.click(screen.getByTestId('module-builder-update'));

    const refused = await screen.findByTestId('module-builder-upgrade-refused');
    expect(refused.textContent).toMatch(/12 entries/);
    expect(within(refused).getByTestId('module-builder-upgrade-problems').textContent).toMatch(
      /kind of value Poured on holds/,
    );
    expect(refused.textContent).not.toMatch(/not additive/);
    expect(screen.queryByTestId('module-builder-done')).toBeNull();
  });

  it('shows a refusal of the preview before anyone presses Update, and keeps the button off', async () => {
    vi.mocked(previewUpgrade).mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: {
          code: 'upgrade_not_additive',
          message: 'This change is not additive.',
          params: { records: 1, problems: [{ code: 'field_new_required', field: 'volume', label: 'Volume' }] },
        },
      }),
    );
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    await addVolume(user);
    await user.click(screen.getByTestId('module-builder-next'));

    const refused = await screen.findByTestId('module-builder-upgrade-refused');
    expect(refused.textContent).toMatch(/1 entry already holds/);
    expect(refused.textContent).toMatch(/Volume is new and must be filled in.+Make it optional/);
    expect(screen.getByTestId('module-builder-update')).toBeDisabled();
    expect(upgradeModule).not.toHaveBeenCalled();
  });

  it('names the parts of the platform a new link needs that are switched off here', async () => {
    vi.mocked(upgradeModule).mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: { code: 'links_switched_off', message: 'oe_contracts is not loaded.', params: { targets: ['contract'] } },
      }),
    );
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    await addVolume(user);
    await user.click(screen.getByTestId('module-builder-next'));
    await waitFor(() => expect(screen.getByTestId('module-builder-update')).not.toBeDisabled());
    await user.click(screen.getByTestId('module-builder-update'));

    const refused = await screen.findByTestId('module-builder-upgrade-refused');
    expect(refused.getAttribute('data-code')).toBe('links_switched_off');
    expect(refused.textContent).toMatch(/switched off here: Contract./);
    expect(refused.textContent).not.toMatch(/oe_contracts/);
  });

  it('says the previous version is still serving when the new one did not start', async () => {
    vi.mocked(upgradeModule).mockRejectedValue(
      new ApiError(409, 'Conflict', { detail: { code: 'upgrade_failed', message: 'ImportError in router.py' } }),
    );
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    await addVolume(user);
    await user.click(screen.getByTestId('module-builder-next'));
    await waitFor(() => expect(screen.getByTestId('module-builder-update')).not.toBeDisabled());
    await user.click(screen.getByTestId('module-builder-update'));

    const refused = await screen.findByTestId('module-builder-upgrade-refused');
    expect(refused.textContent).toMatch(/previous one is still serving and nothing recorded was lost/);
    expect(refused.textContent).not.toMatch(/ImportError/);
  });

  it('points at rebuilding when the saved description cannot be read', async () => {
    vi.mocked(previewUpgrade).mockRejectedValue(
      new ApiError(409, 'Conflict', { detail: { code: 'module_unreadable', message: 'spec.json failed validation' } }),
    );
    const user = userEvent.setup();
    renderUpgrade();
    await screen.findByTestId('module-builder-fine-tune-body');
    await addVolume(user);
    await user.click(screen.getByTestId('module-builder-next'));

    const refused = await screen.findByTestId('module-builder-upgrade-refused');
    expect(refused.textContent).toMatch(/Build it again from the builder under the same internal name/);
    expect(refused.textContent).not.toMatch(/spec\.json/);
    expect(screen.getByTestId('module-builder-update')).toBeDisabled();
  });
});

describe('the button that opens it', () => {
  function renderButton() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ExtendModuleButton moduleKey={MODULE.key} basePath={MODULE.base_path} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('shows for an administrator on a server that can update in place', async () => {
    renderButton();
    expect(await screen.findByTestId('module-builder-extend-pour_register')).toBeTruthy();
  });

  it('stays away from anyone else, and from a server that cannot', async () => {
    role.current = 'editor';
    renderButton();
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId('module-builder-extend-pour_register')).toBeNull();
    expect(fetchVocabulary).not.toHaveBeenCalled();
  });

  it('is not offered by a server without the upgrade path', async () => {
    vi.mocked(fetchVocabulary).mockResolvedValue({ ...VOCABULARY, upgrade: undefined });
    renderButton();
    await waitFor(() => expect(fetchVocabulary).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId('module-builder-extend-pour_register')).toBeNull();
  });
});
