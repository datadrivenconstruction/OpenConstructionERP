// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The register of modules built here, and the one destructive control on it.
 *
 * The case worth guarding is the removal: the default must leave the records
 * alone, and asking for them to go too must be a separate, deliberate tick.
 * A confirm dialog that silently dropped a table would look identical.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    fetchInstalledModules: vi.fn(),
    uninstallModule: vi.fn(),
    fetchVocabulary: vi.fn(),
  };
});

import { useAuthStore } from '@/stores/useAuthStore';

import {
  fetchInstalledModules,
  fetchVocabulary,
  uninstallModule,
  type InstalledList,
  type Vocabulary,
} from './api';
import { ModuleBuilderPage } from './ModuleBuilderPage';

const installed = vi.mocked(fetchInstalledModules);
const uninstall = vi.mocked(uninstallModule);

const VOCABULARY: Vocabulary = {
  field_types: [{ type: 'text', label: 'Text', hint: '' }],
  rule_kinds: [
    { kind: 'required', label: 'Must be filled in', hint: '', applies_to: ['text'], needs_other_field: false, needs_bounds: false },
  ],
  reserved_field_names: [],
  reserved_keys: [],
  max_fields: 40,
  assistant_available: false,
};

const LIST: InstalledList = {
  items: [
    {
      key: 'pour_register',
      module_name: 'oe_pour_register',
      display_name: 'Pour Register',
      version: '0.2.0',
      generated_at: '2026-08-07T00:00:00Z',
      entity: 'Pour',
      field_count: 6,
      rule_count: 3,
      base_path: '/api/v1/pour-register',
    },
  ],
  total: 1,
  runtime_root: '/home/oe/.openestimate/modules',
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ModuleBuilderPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchVocabulary).mockResolvedValue(VOCABULARY);
  installed.mockResolvedValue(LIST);
  uninstall.mockResolvedValue({
    key: 'pour_register',
    module_name: 'oe_pour_register',
    removed: true,
    data_dropped: false,
  });
  useAuthStore.setState({ userRole: 'admin' });
});

describe('the register', () => {
  it('lists what is installed and where it answers', async () => {
    renderPage();
    const list = await screen.findByTestId('module-builder-list');
    expect(within(list).getByText('Pour Register')).toBeTruthy();
    expect(within(list).getByText('/api/v1/pour-register')).toBeTruthy();
    expect(within(list).getByText(/6 fields/)).toBeTruthy();
  });

  it('keeps the server directory out of the explainer prose, folded away for an administrator', async () => {
    renderPage();
    const path = await screen.findByText('/home/oe/.openestimate/modules');
    const folded = path.closest('details');
    expect(folded).toBeTruthy();
    expect(folded?.hasAttribute('open')).toBe(false);
    expect(folded?.getAttribute('data-testid')).toBe('module-builder-files-location');
  });

  it('links each module to the screen it renders on, by key', async () => {
    renderPage();
    const link = await screen.findByTestId('module-builder-open-pour_register');
    expect(link.getAttribute('href')).toBe('/modules/pour_register');
  });

  it('says nothing has been built rather than showing an empty table', async () => {
    installed.mockResolvedValue({ items: [], total: 0, runtime_root: '/tmp' });
    renderPage();
    expect(await screen.findByText(/Nothing has been built here yet/i)).toBeTruthy();
  });
});

describe('a module switched off for safety', () => {
  function quarantined(problem: { code: string; params?: Record<string, unknown> }) {
    const [module] = LIST.items;
    installed.mockResolvedValue({ ...LIST, items: [{ ...module!, status: 'quarantined', problem }] });
  }

  it('says why in plain words, naming the files, and offers neither opening nor adding to it', async () => {
    quarantined({ code: 'unsafe_code', params: { files: ['router.py', 'service.py'] } });
    renderPage();
    const message = await screen.findByTestId('module-builder-quarantined-pour_register');
    expect(message.textContent).toMatch(/code that its description does not produce \(router\.py.+service\.py\)/);
    expect(message.textContent).toMatch(/Its records are kept/);
    expect(screen.getByText('Switched off for safety')).toBeTruthy();
    expect(screen.queryByTestId('module-builder-open-pour_register')).toBeNull();
    expect(screen.queryByTestId('module-builder-extend-pour_register')).toBeNull();
    // Its address answers nothing, so the card does not print it as if it did.
    expect(screen.queryByText('/api/v1/pour-register')).toBeNull();
    // Removing it still works.
    expect(screen.getByTestId('module-builder-remove-pour_register')).toBeTruthy();
  });

  it('explains a module from an older builder that could not be checked', async () => {
    quarantined({ code: 'unverifiable' });
    renderPage();
    const message = await screen.findByTestId('module-builder-quarantined-pour_register');
    expect(message.textContent).toMatch(/older version of the builder and could not be checked/);
  });

  it('still reads as a sentence for a reason this screen does not know yet', async () => {
    quarantined({ code: 'something_new' });
    renderPage();
    const message = await screen.findByTestId('module-builder-quarantined-pour_register');
    expect(message.textContent).toMatch(/switched off for safety\. Its records are kept/);
    expect(message.textContent).not.toMatch(/something_new/);
  });
});

describe('who may change it', () => {
  it('shows a viewer the register without the controls that would be refused', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderPage();
    await screen.findByTestId('module-builder-list');
    expect(screen.queryByTestId('module-builder-page-build')).toBeNull();
    expect(screen.queryByTestId('module-builder-remove-pour_register')).toBeNull();
  });
});

describe('removing a module', () => {
  it('keeps the records unless asked, and says so before confirming', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('module-builder-list');
    await user.click(screen.getByTestId('module-builder-remove-pour_register'));

    expect(await screen.findByText(/Its records stay/i)).toBeTruthy();
    await user.click(screen.getByTestId('module-builder-confirm-remove'));

    await waitFor(() => expect(uninstall).toHaveBeenCalledWith('pour_register', false));
  });

  it('drops the data only when that was ticked', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('module-builder-list');
    await user.click(screen.getByTestId('module-builder-remove-pour_register'));

    const choice = await screen.findByTestId('module-builder-drop-data');
    await user.click(within(choice).getByRole('checkbox'));
    // The warning only appears once the choice has actually been made.
    expect(await screen.findByText(/cannot be undone/i)).toBeTruthy();

    await user.click(screen.getByTestId('module-builder-confirm-remove'));
    await waitFor(() => expect(uninstall).toHaveBeenCalledWith('pour_register', true));
  });

  it('forgets the tick when the dialog is dismissed', async () => {
    // Otherwise the next module removed inherits a destructive choice made
    // about a different one.
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('module-builder-list');
    await user.click(screen.getByTestId('module-builder-remove-pour_register'));
    const choice = await screen.findByTestId('module-builder-drop-data');
    await user.click(within(choice).getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await user.click(screen.getByTestId('module-builder-remove-pour_register'));
    const again = await screen.findByTestId('module-builder-drop-data');
    expect(within(again).getByRole('checkbox')).toHaveProperty('checked', false);
  });
});
