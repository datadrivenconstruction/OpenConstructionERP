import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU, DE } from './testStrings';
import { DISMISS_KEY, INSTALLER_SEEN_KEY, type LinkFile } from './data/offer';

const h = vi.hoisted(() => ({
  project: 'p1' as string | null,
  createLink: vi.fn(),
  access: { can_accept: true, currency: null, lock: null } as { can_accept: boolean; currency: string | null; lock: { held_by: string; mine: boolean; expires_at: string } | null },
  revisions: [] as { revision_id: string; number: number }[],
  toast: vi.fn(),
  enabled: {} as Record<string, boolean>,
  setEnabled: vi.fn(),
  saved: [] as { name: string; text: string }[],
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (sel: (s: { activeProjectId: string | null }) => unknown) => sel({ activeProjectId: h.project }),
}));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: unknown }) => unknown) => sel({ addToast: h.toast }),
}));
vi.mock('@/stores/useModuleStore', () => ({
  useModuleStore: (sel: (s: { enabledModules: Record<string, boolean>; setModuleEnabled: unknown }) => unknown) =>
    sel({ enabledModules: h.enabled, setModuleEnabled: h.setEnabled }),
}));
vi.mock('@/shared/lib/api', () => ({ getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)) }));
vi.mock('@/features/projects/api', () => ({ projectsApi: { get: vi.fn(async () => ({ id: 'p1', name: 'Wohnhaus Beispielstraße' })) } }));
vi.mock('./api', () => ({ createLink: (...a: unknown[]) => h.createLink(...a), fetchRevisions: async () => h.revisions, fetchAccess: async () => h.access }));
vi.mock('@/shared/ui', async () => {
  return {
    Button: ({ children, loading, icon: _i, variant: _v, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; icon?: unknown; variant?: string }) =>
      <button type="button" {...rest} disabled={rest.disabled || loading}>{children}</button>,
    Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
    CardHeader: ({ title, subtitle }: { title: string; subtitle?: string }) => <header>{title}{subtitle}</header>,
    EmptyState: ({ title, description }: { title: string; description?: string }) => <div><p>{title}</p><p>{description}</p></div>,
    PageHeader: ({ srTitle, subtitle }: { srTitle?: string; subtitle?: string }) => <header><h1>{srTitle}</h1><p>{subtitle}</p></header>,
  };
});

import EditorLinkPage from './EditorLinkPage';
import { DesignOffer } from './DesignOffer';

const link = (over: Partial<LinkFile> = {}): LinkFile => ({
  schema: 'ddc-link/1', erp_url: 'http://127.0.0.1:8000', project_id: 'p1', project_name: 'Wohnhaus Beispielstraße',
  code: 'secretcode', expires_at: new Date(Date.now() + 300_000).toISOString(), action: 'open', revision_id: null, ...over,
});

async function mount(ui: React.ReactElement, lang: 'en' | 'ru' | 'de' = 'en') {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU }, de: { translation: DE } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><I18nextProvider i18n={inst}>{ui}</I18nextProvider></MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

beforeEach(() => {
  cleanup();
  localStorage.clear();
  h.project = 'p1';
  h.createLink = vi.fn(async () => link());
  h.revisions = [{ revision_id: 'r1', number: 1 }, { revision_id: 'r2', number: 2 }];
  h.toast = vi.fn();
  h.access = { can_accept: true, currency: null, lock: null };
  h.enabled = {};
  h.setEnabled = vi.fn();
  h.saved = [];
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }));
  HTMLAnchorElement.prototype.click = function click(this: HTMLAnchorElement) {
    h.saved.push({ name: this.download, text: '' });
  };
});

describe('EditorLinkPage', () => {
  it('asks for a project when none is active', async () => {
    h.project = null;
    await mount(<EditorLinkPage />);
    expect(screen.getByText('Select a project')).toBeTruthy();
  });

  it('the button asks the server for an open-link and saves a file named after the project', async () => {
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    await waitFor(() => expect(h.createLink).toHaveBeenCalledWith('p1', 'open', 'r2'));
    await waitFor(() => expect(h.saved).toEqual([{ name: 'Wohnhaus-Beispielstrasse.ddclink', text: '' }]));
    expect((await screen.findByTestId('link-saved')).textContent).toContain('Wohnhaus-Beispielstrasse.ddclink');
  });

  it('a project without revisions opens a new design instead of failing', async () => {
    h.revisions = [];
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    await waitFor(() => expect(h.createLink).toHaveBeenCalledWith('p1', 'new'));
  });

  it('starting a new design asks for a new-link', async () => {
    const user = await mount(<EditorLinkPage />);
    await user.click(await screen.findByRole('button', { name: 'Start a new design' }));
    await waitFor(() => expect(h.createLink).toHaveBeenCalledWith('p1', 'new'));
  });

  it.each([
    [403, 'Ask the project owner', false],
    [503, 'OE_DESIGN_PUBLIC_URL', true],
    [429, 'Wait a minute', true],
    [401, 'Sign in again', false],
  ] as const)('a %s failure says what to do and no file is saved', async (status, text, retry) => {
    h.createLink = vi.fn(async () => { throw Object.assign(new Error('raw server text'), { status }); });
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    const box = await screen.findByTestId('link-error');
    expect(box.textContent).toContain(text);
    expect(box.textContent).not.toContain('raw server text');
    expect(!!screen.queryByRole('button', { name: 'Try again' })).toBe(retry);
    expect(h.saved).toEqual([]);
    expect(screen.queryByTestId('link-saved')).toBeNull();
  });

  it('Try again asks the same question again and clears the error', async () => {
    h.createLink = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error('x'), { status: 503 }))
      .mockResolvedValue(link());
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    await user.click(await screen.findByRole('button', { name: 'Try again' }));
    await screen.findByTestId('link-saved');
    expect(screen.queryByTestId('link-error')).toBeNull();
    expect(h.createLink).toHaveBeenNthCalledWith(2, 'p1', 'open', 'r2');
  });

  it('a network failure is told apart from a refusal', async () => {
    h.createLink = vi.fn(async () => { throw new TypeError('Failed to fetch'); });
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    expect((await screen.findByTestId('link-error')).textContent).toContain('could not be reached');
  });

  it('the saved line names the minutes left and offers the file again', async () => {
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    expect((await screen.findByTestId('link-saved')).textContent).toMatch(/within [45] minutes/);
    await user.click(screen.getByRole('button', { name: 'Save the file again' }));
    expect(h.saved).toHaveLength(2);
    expect(h.createLink).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('link-next').querySelector('a[href="/design/revisions"]')).toBeTruthy();
  });

  it('an expired link offers a new one in one click, for the same action', async () => {
    h.createLink = vi.fn().mockResolvedValueOnce(link({ expires_at: '2020-01-01T00:00:00Z' })).mockResolvedValue(link());
    const user = await mount(<EditorLinkPage />);
    await user.click(await screen.findByRole('button', { name: 'Start a new design' }));
    await user.click(await screen.findByRole('button', { name: 'Create a new link' }));
    await waitFor(() => expect(h.createLink).toHaveBeenNthCalledWith(2, 'p1', 'new'));
    await waitFor(() => expect(screen.getByTestId('link-saved').textContent).toContain('Saved'));
    expect(screen.queryByRole('button', { name: 'Create a new link' })).toBeNull();
  });

  it('shows who has the project open in the editor', async () => {
    h.access = { can_accept: true, currency: null, lock: { held_by: 'Anna', mine: false, expires_at: '2030-01-01T00:00:00Z' } };
    await mount(<EditorLinkPage />);
    expect((await screen.findByTestId('editor-lock')).textContent).toContain('Anna has this project open');
  });

  it('a project with no revision has one button, not two that do the same', async () => {
    h.revisions = [];
    await mount(<EditorLinkPage />);
    await screen.findByRole('button', { name: 'Open in design editor' });
    expect(screen.queryByRole('button', { name: 'Start a new design' })).toBeNull();
  });

  it('an already expired link is not presented as usable', async () => {
    h.createLink = vi.fn(async () => link({ expires_at: '2020-01-01T00:00:00Z' }));
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    expect((await screen.findByTestId('link-saved')).textContent).toContain('expired');
  });

  it('says design MCP is off by default and names the switch', async () => {
    await mount(<EditorLinkPage />);
    expect(screen.getByTestId('mcp-hint').textContent).toContain('OE_DESIGN_MCP_ENABLED');
  });

  it('the installer hint opens by itself on the first visit and stays reachable after', async () => {
    await mount(<EditorLinkPage />);
    expect((screen.getByTestId('installer-hint') as HTMLDetailsElement).open).toBe(true);
    expect(localStorage.getItem(INSTALLER_SEEN_KEY)).toBe('1');
    cleanup();
    await mount(<EditorLinkPage />);
    const again = screen.getByTestId('installer-hint') as HTMLDetailsElement;
    expect(again.open).toBe(false);
    expect(again.querySelector('summary')?.textContent).toContain('Do not have the editor');
  });

  it('without a configured installer address it says so instead of linking nowhere', async () => {
    await mount(<EditorLinkPage />);
    const hint = screen.getByTestId('installer-hint');
    expect(hint.querySelector('a')).toBeNull();
    expect(hint.textContent).toContain('administrator');
  });

  it('the link code never reaches the page text', async () => {
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    await screen.findByTestId('link-saved');
    expect(document.body.textContent).not.toContain('secretcode');
  });

  it.each([['ru', 'Открыть в редакторе'], ['de', 'Im Entwurfseditor öffnen']] as const)('renders %s', async (lang, label) => {
    await mount(<EditorLinkPage />, lang);
    expect(screen.getByRole('button', { name: label })).toBeTruthy();
  });

  it('both buttons are reachable with Tab and activate with Enter', async () => {
    const user = await mount(<EditorLinkPage />);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Open in design editor' }));
    await user.keyboard('{Enter}');
    await waitFor(() => expect(h.createLink).toHaveBeenCalled());
    await user.tab();
    expect(document.activeElement).toBe(await screen.findByRole('button', { name: 'Start a new design' }));
  });
});

describe('DesignOffer', () => {
  it('the tour question switches the module on and points to the editor page', async () => {
    const user = await mount(<DesignOffer variant="tour" />);
    expect(screen.getByText('Do you work with models and drawings?')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Yes, switch it on' }));
    expect(h.setEnabled).toHaveBeenCalledWith('design', true);
    expect((await screen.findByTestId('design-offer-done')).querySelector('a')?.getAttribute('href')).toBe('/design/editor');
  });

  it('"not now" is remembered and the question stays away; nothing is switched on', async () => {
    const user = await mount(<DesignOffer variant="tour" />);
    await user.click(screen.getByRole('button', { name: 'Not now' }));
    expect(h.setEnabled).not.toHaveBeenCalled();
    expect(localStorage.getItem(DISMISS_KEY)).toBe('1');
    expect(screen.queryByTestId('design-offer-tour')).toBeNull();
    // It says where to switch it on later; that line is gone on the next visit.
    expect(screen.getByTestId('design-offer-later').querySelector('a')?.getAttribute('href')).toBe('/modules');
    cleanup();
    await mount(<DesignOffer variant="tour" />);
    expect(screen.queryByTestId('design-offer-tour')).toBeNull();
  });

  it('the empty-state line is still there after the question was dismissed', async () => {
    localStorage.setItem(DISMISS_KEY, '1');
    await mount(<DesignOffer variant="empty" />);
    expect(screen.getByTestId('design-offer-empty')).toBeTruthy();
  });

  it('renders nothing once the module is on, so the host screens are unchanged', async () => {
    h.enabled = { design: true };
    await mount(<><DesignOffer variant="tour" /><DesignOffer variant="empty" /></>);
    expect(screen.queryByTestId('design-offer-tour')).toBeNull();
    expect(screen.queryByTestId('design-offer-empty')).toBeNull();
    expect(document.body.textContent).toBe('');
  });

  it('an unknown module state counts as off, not on', async () => {
    h.enabled = {};
    await mount(<DesignOffer variant="empty" />);
    expect(screen.getByTestId('design-offer-empty')).toBeTruthy();
  });

  it('the empty-state action switches the module on', async () => {
    const user = await mount(<DesignOffer variant="empty" />);
    await user.click(screen.getByRole('button', { name: 'Switch on the design editor link' }));
    expect(h.setEnabled).toHaveBeenCalledWith('design', true);
  });

  it.each([['ru', 'Вы работаете с моделями и чертежами?'], ['de', 'Arbeiten Sie mit Modellen und Zeichnungen?']] as const)(
    'asks in %s', async (lang, q) => {
      await mount(<DesignOffer variant="tour" />, lang);
      expect(screen.getByText(q)).toBeTruthy();
    });

  it('the question is a labelled region and its buttons take focus in order', async () => {
    const user = await mount(<DesignOffer variant="tour" />);
    expect(screen.getByRole('region', { name: 'Do you work with models and drawings?' })).toBeTruthy();
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Yes, switch it on' }));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Not now' }));
  });
});

describe('EditorLinkPage in the desktop app', () => {
  const calls: { cmd: string; args?: Record<string, unknown> }[] = [];
  let answers: Record<string, unknown[]> = {};
  const install = () => {
    calls.length = 0;
    (window as unknown as { __TAURI__: unknown }).__TAURI__ = {
      core: {
        invoke: async (cmd: string, args?: Record<string, unknown>) => {
          calls.push({ cmd, args });
          const next = answers[cmd]?.shift();
          if (next instanceof Error) throw next;
          return next;
        },
      },
    };
  };
  beforeEach(() => {
    answers = {};
    install();
  });
  afterEach(() => {
    delete (window as unknown as { __TAURI__?: unknown }).__TAURI__;
  });

  it('starts the editor with the link and saves no file', async () => {
    answers.design_editor_launch = [{ result: 'started' }];
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    expect(await screen.findByTestId('desktop-started')).toBeTruthy();
    expect(h.saved).toEqual([]);
    const launch = calls.find((c) => c.cmd === 'design_editor_launch')!;
    expect(launch.args?.confirmed).toBe(false);
    expect(JSON.parse(launch.args?.link as string).code).toBe('secretcode');
    expect(document.body.textContent).not.toContain('secretcode');
  });

  it('an unsigned build is only started after an explicit confirmation', async () => {
    answers.design_editor_launch = [
      { result: 'needs_confirmation', reason: 'unsigned \u2014 verification unavailable' },
      { result: 'started' },
    ];
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    const box = await screen.findByTestId('desktop-unsigned');
    expect(box.textContent).toContain('verification unavailable');
    expect(screen.queryByTestId('desktop-started')).toBeNull();
    expect(calls.filter((c) => c.cmd === 'design_editor_launch')).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Install and start it anyway' }));
    expect(await screen.findByTestId('desktop-started')).toBeTruthy();
    const launches = calls.filter((c) => c.cmd === 'design_editor_launch');
    expect(launches.map((c) => c.args?.confirmed)).toEqual([false, true]);
    expect(h.createLink).toHaveBeenCalledTimes(1);
  });

  it('without an installed editor it offers download and an install from a file', async () => {
    answers.design_editor_launch = [{ result: 'not_installed' }];
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    expect(await screen.findByTestId('desktop-missing')).toBeTruthy();
    const fromFile = screen.getByRole('button', { name: 'Install from a file' }) as HTMLButtonElement;
    expect(fromFile.disabled).toBe(true);
    await user.type(screen.getByLabelText('Path to the editor file'), 'D:\in\OpenConstructionDesign-1.exe');
    answers.design_editor_launch = [{ result: 'started' }];
    answers.design_editor_install_local = [{ result: 'needs_confirmation', reason: 'unsigned \u2014 verification unavailable' }, { result: 'installed', name: 'OpenConstructionDesign-1.exe', signature: { state: 'unsigned', reason: 'x' } }];
    await user.click(fromFile);
    await screen.findByTestId('desktop-unsigned');
    await user.click(screen.getByRole('button', { name: 'Install and start it anyway' }));
    await waitFor(() => expect(screen.getByText('Installed OpenConstructionDesign-1.exe.')).toBeTruthy());
    expect(calls.filter((c) => c.cmd === 'design_editor_install_local').map((c) => c.args)).toEqual([
      { path: 'D:\in\OpenConstructionDesign-1.exe', confirmed: false },
      { path: 'D:\in\OpenConstructionDesign-1.exe', confirmed: true },
    ]);
  });

  it('the download button asks the shell, which owns the address', async () => {
    answers.design_editor_launch = [{ result: 'not_installed' }, { result: 'started' }];
    answers.design_editor_download = [{ result: 'installed', name: 'OpenConstructionDesign-2.exe', signature: { state: 'verified', signer: 'DDC' } }];
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    await user.click(await screen.findByRole('button', { name: 'Download the editor' }));
    await waitFor(() => expect(screen.getByText('Installed OpenConstructionDesign-2.exe.')).toBeTruthy());
    expect(calls.find((c) => c.cmd === 'design_editor_download')?.args).toEqual({ confirmed: false });
    expect(screen.queryByTestId('desktop-missing')).toBeNull();
    // The press that found the editor missing is finished by itself: same link, no second click.
    expect(await screen.findByTestId('desktop-started')).toBeTruthy();
    expect(calls.filter((c) => c.cmd === 'design_editor_launch')).toHaveLength(2);
    expect(h.createLink).toHaveBeenCalledTimes(1);
  });

  it('a refusal from the shell is shown with its reason and a way on', async () => {
    answers.design_editor_launch = [new Error('the signature is invalid: tampered')];
    const user = await mount(<EditorLinkPage />);
    await user.click(screen.getByRole('button', { name: 'Open in design editor' }));
    await waitFor(() => expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error', message: 'the signature is invalid: tampered' })));
    expect(screen.queryByTestId('desktop-unsigned')).toBeNull();
    expect((await screen.findByTestId('link-error')).textContent).toContain('install it again');
  });
});
