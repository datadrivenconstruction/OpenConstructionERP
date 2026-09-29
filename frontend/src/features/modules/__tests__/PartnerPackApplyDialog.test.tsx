// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// <PartnerPackApplyDialog /> - what a pack activation shows when it fails as a
// whole, what it shows when it finishes, and who may start it.
//
// Production case this pins: a viewer account opened the dialog, the stream
// endpoint answered 403 before its first frame, and the dialog ended on
// "Finished with warnings" over an empty checklist with a toast of raw JSON.
// The founder read that as "nothing happens".

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';

import type { ApplyPreview } from '../partnerPacks';
import type { StreamInstallEvent } from '@/features/onboarding/partnerPacksApi';

/* ── Mocks ─────────────────────────────────────────────────────────────── */

const packMock = vi.hoisted(() => ({ useApplyPreview: vi.fn() }));
vi.mock('../partnerPacks', async () => {
  const actual = await vi.importActual<typeof import('../partnerPacks')>('../partnerPacks');
  return { ...actual, ...packMock };
});

const streamMock = vi.hoisted(() => ({ fullInstallPackStream: vi.fn() }));
vi.mock('@/features/onboarding/partnerPacksApi', async () => {
  const actual = await vi.importActual<typeof import('@/features/onboarding/partnerPacksApi')>(
    '@/features/onboarding/partnerPacksApi',
  );
  return { ...actual, ...streamMock };
});

const i18nMock = vi.hoisted(() => {
  const inst = {
    language: 'en',
    changeLanguage: vi.fn(async (lng: string) => {
      inst.language = lng;
    }),
  };
  return {
    inst,
    loadLocaleResource: vi.fn(async () => {}),
  };
});
vi.mock('@/app/i18n', () => ({
  default: i18nMock.inst,
  loadLocaleResource: i18nMock.loadLocaleResource,
  normalizePackLocale: (l: string | null | undefined) => (l ? l.split('-')[0]! : 'en'),
  SUPPORTED_LANGUAGES: [
    { code: 'en', name: 'English' },
    { code: 'de', name: 'Deutsch' },
  ],
}));

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

const addToast = vi.hoisted(() => vi.fn());
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (s: { addToast: typeof addToast }) => unknown) => selector({ addToast }),
}));

const authState = vi.hoisted(() => ({ userRole: 'admin' as string | null }));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector: (s: { userRole: string | null }) => unknown) =>
    selector({ userRole: authState.userRole }),
}));

import { PartnerPackApplyDialog } from '../PartnerPackApplyDialog';
import { PackInstallError } from '@/features/onboarding/partnerPacksApi';

/* ── Fixtures ──────────────────────────────────────────────────────────── */

function preview(overrides: Partial<ApplyPreview['plan']> = {}): ApplyPreview {
  return {
    slug: 'germany-de',
    partner_name: 'Germany',
    pack_version: '1.0.0',
    will_disable_modules: false,
    will_install_demo: false,
    plan: {
      branding: { partner_name: 'Germany', powered_by: 'Germany pack', primary_color: '#000' },
      modules_to_enable: [],
      modules_to_enable_missing: [],
      modules_to_disable: [],
      modules_to_disable_missing: [],
      default_currency: 'EUR',
      default_locale: 'de',
      additional_locales: [],
      rule_packs_active: [],
      rule_packs_documentation_only: [],
      cwicr_regions: ['cwicr-de-berlin', 'cwicr-de-munich'],
      cost_bases: [
        {
          slug: 'cwicr-de-berlin',
          db_id: 'DE_BERLIN',
          loadable: true,
          market: 'Germany / DACH',
          currency: 'EUR',
          lang_code: 'de',
          flag: 'de',
          positions: 55719,
          has_catalog: true,
          reason_code: null,
        },
        {
          slug: 'cwicr-de-munich',
          db_id: null,
          loadable: false,
          market: null,
          currency: null,
          lang_code: null,
          flag: null,
          positions: null,
          has_catalog: false,
          reason_code: 'no_published_base',
        },
      ],
      warnings: [],
      ...overrides,
    },
  };
}

const STEPS = [
  { step: 'apply_pack', label_key: 'modules.pp_step_apply', label: 'Apply preset' },
  { step: 'locale', label_key: 'modules.pp_step_locale', label: 'Install language' },
  { step: 'cost_db', label_key: 'modules.pp_step_cost_db', label: 'Load work catalog' },
  { step: 'resources', label_key: 'modules.pp_step_resources', label: 'Load resources' },
  { step: 'catalog', label_key: 'modules.pp_step_catalog', label: 'Load resource catalogue' },
  { step: 'demos', label_key: 'modules.pp_step_demos', label: 'Create demo project' },
] as const;

type Done = { step: (typeof STEPS)[number]['step']; status: 'ok' | 'error' | 'skipped'; detail: Record<string, unknown> };

/** A stream implementation that emits start, one step_done per entry, done. */
function streamOf(dones: Done[], ok: boolean) {
  return async (_slug: string, onEvent: (e: StreamInstallEvent) => void) => {
    onEvent({ type: 'start', slug: 'germany-de', total: STEPS.length, steps: [...STEPS] });
    dones.forEach((d, index) => {
      onEvent({ type: 'step_start', step: d.step, index, total: STEPS.length });
      onEvent({ type: 'step_done', step: d.step, index, total: STEPS.length, status: d.status, detail: d.detail });
    });
    // The dialog reads the verdict off ``done`` and the rows off step_done.
    onEvent({ type: 'done', slug: 'germany-de', ok, steps: [] });
  };
}

function renderDialog() {
  return render(
    <PartnerPackApplyDialog open onClose={vi.fn()} slug="germany-de" partnerName="Germany" />,
  );
}

function activate() {
  fireEvent.click(screen.getByRole('button', { name: /Activate pack/ }));
}

beforeEach(() => {
  authState.userRole = 'admin';
  i18nMock.inst.language = 'en';
  packMock.useApplyPreview.mockReturnValue({ data: preview(), isLoading: false, isError: false });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/* ── Whole-install failures ────────────────────────────────────────────── */

describe('a failed install says what failed and why', () => {
  it('a 403 before the first frame explains the account may not install packs', async () => {
    streamMock.fullInstallPackStream.mockRejectedValue(
      new PackInstallError('forbidden', 403, "Role 'admin' required", 'Activation failed (HTTP 403)'),
    );
    renderDialog();
    activate();

    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('This account may not install packs')).toBeTruthy();
    expect(within(alert).getByText(/needs an administrator/)).toBeTruthy();
    expect(within(alert).getByText(/Role 'admin' required/)).toBeTruthy();
    // Where to go instead: a copy of their own, where they are the admin.
    const link = within(alert).getByRole('link', { name: 'Download and install guide' });
    expect(link.getAttribute('href')).toBe('https://openconstructionerp.com/download');
    // Not the partial-install view the 403 used to end on.
    expect(screen.queryByText('Finished with warnings')).toBeNull();
    expect(screen.queryByText(/Pack activated/)).toBeNull();
    // Retrying cannot help a 403, so it is not offered.
    expect(screen.queryByRole('button', { name: /Try again/ })).toBeNull();
    expect(addToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: 'This account may not install packs' }),
    );
  });

  it.each([
    ['unauthenticated', 401, 'Your session has ended'],
    ['server', 500, 'The server failed while installing the pack'],
    ['network', null, 'Could not reach the server'],
    ['incomplete', 200, 'The connection dropped during the installation'],
  ] as const)('%s failure shows its own headline and a retry', async (kind, status, title) => {
    streamMock.fullInstallPackStream.mockRejectedValue(new PackInstallError(kind, status, null, 'x'));
    renderDialog();
    activate();

    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText(title)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Try again/ })).toBeTruthy();
  });

  it('a stream cut after it started keeps the finished rows and flags the rest', async () => {
    streamMock.fullInstallPackStream.mockImplementation(async (_s: string, onEvent: (e: StreamInstallEvent) => void) => {
      onEvent({ type: 'start', slug: 'germany-de', total: STEPS.length, steps: [...STEPS] });
      onEvent({ type: 'step_done', step: 'apply_pack', index: 0, total: 6, status: 'ok', detail: { rule_sets: [] } });
      throw new PackInstallError('incomplete', 200, null, 'cut');
    });
    renderDialog();
    activate();

    await screen.findByRole('alert');
    const list = screen.getByTestId('pack-install-steps');
    expect(list.querySelector('[data-step="apply_pack"]')?.getAttribute('data-state')).toBe('ok');
    expect(list.querySelector('[data-step="cost_db"]')?.getAttribute('data-state')).toBe('error');
  });
});

/* ── Successful install summary ────────────────────────────────────────── */

describe('a finished install is verifiable step by step', () => {
  it('names the language, each base, the catalogue, the rules and the demos', async () => {
    streamMock.fullInstallPackStream.mockImplementation(
      streamOf(
        [
          { step: 'apply_pack', status: 'ok', detail: { rule_sets: ['din276'] } },
          { step: 'locale', status: 'ok', detail: { locale: 'de' } },
          {
            step: 'cost_db',
            status: 'ok',
            detail: {
              items: 55719,
              bases: [
                { slug: 'cwicr-de-berlin', db_id: 'DE_BERLIN', status: 'ok', items: 55719, resources: 900 },
                { slug: 'cwicr-de-munich', db_id: null, status: 'skipped', reason_code: 'no_published_base' },
              ],
            },
          },
          { step: 'resources', status: 'ok', detail: { resources: 900 } },
          {
            step: 'catalog',
            status: 'ok',
            detail: { resources: 4200, catalogs: [{ db_id: 'DE_BERLIN', status: 'ok', resources: 4200 }] },
          },
          { step: 'demos', status: 'ok', detail: { installed: ['a', 'b'] } },
        ],
        true,
      ),
    );
    renderDialog();
    activate();

    await screen.findByText('Everything above is installed and ready to use.');
    // The language is read back after the switch, not assumed.
    await waitFor(() => expect(screen.getByText('The interface is in Deutsch.')).toBeTruthy());
    expect(i18nMock.inst.changeLanguage).toHaveBeenCalledWith('de');
    expect(screen.getByText(/DE_BERLIN: .*work items loaded/)).toBeTruthy();
    expect(screen.getByText(/cwicr-de-munich: skipped, no cost database is published/)).toBeTruthy();
    expect(screen.getByText(/Resource catalogue DE_BERLIN: .*resources loaded/)).toBeTruthy();
    expect(screen.getByText('Validation rules switched on for new projects: din276')).toBeTruthy();
    expect(screen.getByText(/Sample projects created: 2/)).toBeTruthy();
  });

  it('a failed cost base is named with its reason and can be retried alone', async () => {
    streamMock.fullInstallPackStream.mockImplementationOnce(
      streamOf(
        [
          { step: 'apply_pack', status: 'ok', detail: { rule_sets: [] } },
          { step: 'locale', status: 'ok', detail: { locale: 'de' } },
          {
            step: 'cost_db',
            status: 'error',
            detail: {
              bases: [
                {
                  slug: 'cwicr-de-berlin',
                  db_id: 'DE_BERLIN',
                  status: 'error',
                  reason_code: 'load_failed',
                  error: 'download timed out',
                },
              ],
            },
          },
          { step: 'resources', status: 'skipped', detail: { reason_code: 'no_cost_db' } },
          { step: 'catalog', status: 'skipped', detail: { reason_code: 'no_cost_db' } },
          { step: 'demos', status: 'skipped', detail: { reason_code: 'not_requested', installed: [] } },
        ],
        false,
      ),
    );
    renderDialog();
    activate();

    await screen.findByText(/Some steps failed: Load work catalog/);
    expect(screen.getByText('DE_BERLIN: not loaded, download timed out')).toBeTruthy();

    streamMock.fullInstallPackStream.mockImplementationOnce(async () => {});
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }));
    await waitFor(() => expect(streamMock.fullInstallPackStream).toHaveBeenCalledTimes(2));
    const retryOpts = streamMock.fullInstallPackStream.mock.calls[1]![2];
    expect(retryOpts.onlySteps).toEqual(['cost_db']);
  });
});

/* ── Cost bases offered up front ───────────────────────────────────────── */

describe('the country cost bases are offered before install', () => {
  it('ticks every loadable base and sends the choice', async () => {
    streamMock.fullInstallPackStream.mockImplementation(streamOf([], true));
    renderDialog();

    const bases = screen.getByTestId('pack-cost-bases');
    const box = within(bases).getAllByRole('checkbox')[0] as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(within(bases).getByText(/cwicr-de-munich: no cost database is published/)).toBeTruthy();

    activate();
    await waitFor(() => expect(streamMock.fullInstallPackStream).toHaveBeenCalled());
    const opts = streamMock.fullInstallPackStream.mock.calls[0]![2];
    expect(opts.costRegions).toEqual(['cwicr-de-berlin']);
    expect(opts.installCatalog).toBe(true);
  });

  it('says so when the country has no base to load', () => {
    packMock.useApplyPreview.mockReturnValue({
      data: preview({ cwicr_regions: [], cost_bases: [] }),
      isLoading: false,
      isError: false,
    });
    renderDialog();
    expect(screen.getByTestId('pack-no-cost-base').textContent).toMatch(
      /No cost database is published for this country yet/,
    );
  });
});

/* ── Permission ────────────────────────────────────────────────────────── */

describe('who may install', () => {
  it('a viewer sees why and cannot start the install', () => {
    authState.userRole = 'viewer';
    renderDialog();
    const note = screen.getByRole('note');
    expect(note.textContent).toMatch(/Only an administrator can activate a pack/);
    expect(within(note).getByRole('link', { name: 'Download and install guide' })).toBeTruthy();
    const button = screen.getByRole('button', { name: /Activate pack/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(streamMock.fullInstallPackStream).not.toHaveBeenCalled();
  });

  it('an owner, which the server ranks as admin, may install', () => {
    authState.userRole = 'owner';
    renderDialog();
    const button = screen.getByRole('button', { name: /Activate pack/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });
});
