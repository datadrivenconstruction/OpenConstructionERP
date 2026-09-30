// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Where the card's way into the pack picker lands, in both of its states.
 *
 * WHY THE DESTINATION IS TESTED AND NOT THE CLICK. This card's empty state
 * pointed its only button at `/onboarding`, and the wizard mounted there
 * bounces anyone with `oe_onboarding_completed` straight back to `/` with
 * `replace`. Every reader who can see a dashboard has that flag, so the
 * button did nothing for all of them - and a test that asserted the button
 * renders, or that clicking it calls navigate, would have been green through
 * the whole life of the defect. Both facts it needed were true: there WAS a
 * button and it DID navigate. So these tests never look at the call, they
 * follow the navigation through a real router and ask what is on screen at
 * the end of it, with the flag set the way a real reader's browser has it.
 *
 * WHY THE GUARD IS IN THE HARNESS. The `/onboarding` route here carries the
 * wizard's own `isOnboardingCompleted`, imported from the onboarding feature
 * rather than restated, so a test that passes is a test whose guard reads the
 * same storage key the wizard reads. The first case exists to prove that
 * guard is live: it walks a control button into `/onboarding` and watches it
 * come back to `/`. Without it, a harness that had quietly stopped bouncing
 * would make every later assertion green for the wrong reason.
 *
 * WHY THE FLAG IS ASSERTED AFTER THE CLICK. There is a way to make the
 * wizard reachable from here - remove the completed flag first, the way
 * Settings' "restart onboarding" does. It would pass a naive destination
 * test and silently restart a finished user's setup, which is worse than the
 * dead button. So the flag is asserted intact on the way out.
 *
 * Run: npx vitest run src/features/dashboard/__tests__/RegionalPackCard.test.tsx
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import {
  MemoryRouter,
  Routes,
  Route,
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
} from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { RegionalPackCard } from '../RegionalPackCard';
import { isOnboardingCompleted } from '@/features/onboarding';
import { apiGet } from '@/shared/lib/api';

// The shared setup (`src/test/setup.ts`) replaces `useNavigate` with a fresh
// no-op spy for every test in the suite. That is why no existing test could
// have caught this defect even in principle: under that mock every navigation
// is swallowed, a button aimed at a guarded route and a button aimed at a good
// one behave identically, and the only thing left to assert is the string
// passed to a spy. Put the real router back for this file, because the whole
// question here is where the reader ends up.
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual };
});

vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    typeof opts === 'object' && opts !== null && 'defaultValue' in opts
      ? String(opts.defaultValue)
      : key;
  return {
    useTranslation: () => ({ t, i18n: { language: 'en' } }),
    initReactI18next: { type: '3rdParty', init: () => {} },
  };
});

// The card asks the backend which pack is active; "none" is the state that
// renders the button. Nothing here is about the request itself.
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: vi.fn().mockResolvedValue({ active: false }),
    apiPost: vi.fn().mockResolvedValue({}),
  };
});

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_TSX = resolve(HERE, '../../../app/App.tsx');

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

/** The route the wizard owns, carrying the wizard's real guard: the same
 *  helper it calls, and the same replace-bounce to the dashboard. */
function GuardedOnboardingRoute() {
  if (isOnboardingCompleted()) return <Navigate to="/" replace />;
  return <div data-testid="wizard">wizard</div>;
}

/** Stands in for ModulesPage, and reports the tab it was asked for, because
 *  the pathname alone does not say whether the pack picker opens. */
function PacksRoute() {
  const [params] = useSearchParams();
  return <div data-testid="modules-page">{params.get('tab') ?? 'no-tab'}</div>;
}

/** A button that does what the card used to do, so the guard can be watched
 *  turning someone away rather than assumed to. */
function OnboardingBoundControl() {
  const navigate = useNavigate();
  return (
    <>
      <RegionalPackCard />
      <button type="button" onClick={() => navigate('/onboarding')}>
        control
      </button>
    </>
  );
}

function renderApp(home: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <LocationProbe />
        <Routes>
          <Route path="/" element={home} />
          <Route path="/onboarding" element={<GuardedOnboardingRoute />} />
          <Route path="/modules" element={<PacksRoute />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const location = () => screen.getByTestId('location').textContent;

describe('RegionalPackCard, no pack active', () => {
  beforeEach(() => {
    // Every reader who reaches a dashboard has finished onboarding: either the
    // wizard wrote this flag, or the dashboard wrote it after the server said
    // so. This is the only interesting state, not an edge case.
    localStorage.setItem('oe_onboarding_completed', 'true');
  });

  afterEach(() => {
    localStorage.removeItem('oe_onboarding_completed');
  });

  it('reaches the wizard only while the flag is absent, and is bounced once it is set', async () => {
    // Half one: the flag off. The control button lands on the wizard, which
    // proves the harness really navigates. Without this half, the bounce below
    // is indistinguishable from a click that did nothing at all - and a click
    // that does nothing is exactly what the suite-wide `useNavigate` mock
    // produces, so the vacuous version of this test would have been green on
    // both the defect and the fix.
    localStorage.removeItem('oe_onboarding_completed');
    const open = renderApp(<OnboardingBoundControl />);
    fireEvent.click(await screen.findByText('control'));
    await waitFor(() => expect(screen.getByTestId('wizard')).toBeTruthy());
    expect(location()).toBe('/onboarding');
    open.unmount();

    // Half two: the flag on, which is every dashboard reader. The same button
    // now never arrives.
    localStorage.setItem('oe_onboarding_completed', 'true');
    renderApp(<OnboardingBoundControl />);
    fireEvent.click(await screen.findByText('control'));
    await waitFor(() => expect(location()).toBe('/'));
    expect(screen.queryByTestId('wizard')).toBeNull();
  });

  it('sends the reader to a screen that renders for them, not to the guarded wizard', async () => {
    renderApp(<RegionalPackCard />);

    fireEvent.click(await screen.findByText('Install a country pack'));

    // The destination has to hold. Landing back on the dashboard is the
    // defect, and it is a pass for any assertion that only watches the click.
    await waitFor(() => expect(screen.getByTestId('modules-page')).toBeTruthy());
    expect(location()).toBe('/modules?tab=partner-packs');
    expect(location()).not.toBe('/');
    expect(screen.queryByTestId('wizard')).toBeNull();

    // The tab, not just the page: the modules page opens on company profiles
    // without it, which answers a different question than the button asks.
    expect(screen.getByTestId('modules-page').textContent).toBe('partner-packs');
  });

  it('leaves the onboarding-completed flag alone', async () => {
    renderApp(<RegionalPackCard />);

    fireEvent.click(await screen.findByText('Install a country pack'));

    await waitFor(() => expect(screen.getByTestId('modules-page')).toBeTruthy());
    expect(localStorage.getItem('oe_onboarding_completed')).toBe('true');
  });

  it('aims at a path the app actually routes', () => {
    // The harness serves /modules because the app does. Read it back from the
    // route table so a rename there fails here rather than in a browser.
    const app = readFileSync(APP_TSX, 'utf8');
    expect(app).toMatch(/<Route\s+path="\/modules"/);
  });
});

/** A pack the card can draw every row from, so the test exercises the state a
 *  reader with a pack actually sees rather than a stripped one. */
const ACTIVE_PACK = {
  active: true,
  manifest: {
    slug: 'de-din276',
    partner_name: 'Germany (DIN 276)',
    partner_url: null,
    pack_version: '1.0.0',
    description: 'German cost groups, VAT and price data.',
    default_locale: 'de-DE',
    additional_locales: ['en'],
    cwicr_regions: ['de'],
    default_currency: 'EUR',
    default_tax_template: 'de_vat',
    validation_rule_packs: ['din276-reference'],
    validation_rule_sets: ['din276', 'boq_quality'],
    default_modules: ['oe_boq', 'oe_validation'],
    metadata: { country: 'de' },
  },
};

describe('RegionalPackCard, a pack already active', () => {
  beforeEach(() => {
    localStorage.setItem('oe_onboarding_completed', 'true');
    vi.mocked(apiGet).mockResolvedValue(ACTIVE_PACK);
  });

  afterEach(() => {
    localStorage.removeItem('oe_onboarding_completed');
    vi.mocked(apiGet).mockResolvedValue({ active: false });
  });

  // The state with a pack is the one that answered "which pack is on" and then
  // stopped. There was no control of any kind on it, so the card told a reader
  // who already had a pack nothing about changing it or adding another, and a
  // reader who wanted a second market had to know the Packs tab existed. The
  // empty state's button is not a substitute: a reader in this state never
  // sees it. Asserted through the router for the same reason as above - the
  // question is where the reader lands, not that a handler fired.
  it('offers a way to the pack picker to a reader who already has a pack', async () => {
    renderApp(<RegionalPackCard />);

    fireEvent.click(await screen.findByText('Change or add a country pack'));

    await waitFor(() => expect(screen.getByTestId('modules-page')).toBeTruthy());
    expect(location()).toBe('/modules?tab=partner-packs');
    expect(screen.getByTestId('modules-page').textContent).toBe('partner-packs');
  });

  // The two states must not both be on screen at once: the empty state's
  // primary button and this quiet one say different things about what the
  // reader already has, and a card showing both would be reporting two
  // different answers to "which pack is on".
  it('does not also draw the button that belongs to the empty state', async () => {
    renderApp(<RegionalPackCard />);

    await screen.findByText('Change or add a country pack');
    expect(screen.queryByText('Install a country pack')).toBeNull();
  });
});

/** The label of every tile on screen, in order, read from the tile itself. */
function tileLabels(): string[] {
  return screen.getAllByTestId('regional-pack-tile').map((tile) => tile.querySelector('p')?.textContent ?? '');
}

function tileValue(label: string): HTMLElement {
  const tile = screen
    .getAllByTestId('regional-pack-tile')
    .find((el) => el.querySelector('p')?.textContent === label);
  if (!tile) throw new Error(`no tile labelled ${label}`);
  return tile.querySelector('div > div:last-child') as HTMLElement;
}

describe('RegionalPackCard, the compact tile layout', () => {
  afterEach(() => {
    vi.mocked(apiGet).mockResolvedValue({ active: false });
  });

  it('draws one tile per fact the pack sets up, with the value beside each label', async () => {
    vi.mocked(apiGet).mockResolvedValue(ACTIVE_PACK);
    renderApp(<RegionalPackCard />);

    await screen.findByTestId('regional-pack-active');
    expect(tileLabels()).toEqual([
      'Language',
      'Currency',
      'Local price databases',
      'Validation rules',
      'Local tax rules',
      'Modules switched on',
    ]);
    expect(tileValue('Currency').textContent).toBe('EUR');
    expect(tileValue('Local price databases').textContent).toBe('1');
    expect(tileValue('Modules switched on').textContent).toBe('2');
    // The market's own standard by name, and not the generic quality set that
    // every pack switches on beside it.
    expect(tileValue('Validation rules').textContent).toBe('DIN 276');
    expect(screen.getByText('Germany (DIN 276)')).toBeTruthy();
    expect(screen.getByText('Active')).toBeTruthy();
  });

  it('skips the tiles a pack is silent on instead of printing an empty value', async () => {
    vi.mocked(apiGet).mockResolvedValue({
      active: true,
      manifest: {
        ...ACTIVE_PACK.manifest,
        cwicr_regions: [],
        default_tax_template: null,
        default_modules: [],
        validation_rule_sets: ['boq_quality'],
      },
    });
    renderApp(<RegionalPackCard />);

    await screen.findByTestId('regional-pack-active');
    expect(tileLabels()).toEqual(['Language', 'Currency', 'Validation rules']);
    // Only the generic checks are on, so the tile says "on" with a tick that
    // carries its own spoken label rather than naming a standard.
    expect(tileValue('Validation rules').querySelector('[role="img"]')?.getAttribute('aria-label')).toBe(
      'Validation rules',
    );
  });

  it('shows the compact install prompt and no tiles when no pack is active', async () => {
    renderApp(<RegionalPackCard />);

    await screen.findByTestId('regional-pack-none');
    expect(screen.getByText('No regional pack is active')).toBeTruthy();
    expect(screen.queryAllByTestId('regional-pack-tile')).toHaveLength(0);
  });

  it('holds its frame with a skeleton while the answer is on its way', async () => {
    vi.mocked(apiGet).mockReturnValue(new Promise(() => {}));
    renderApp(<RegionalPackCard />);

    expect(await screen.findByTestId('regional-pack-loading')).toBeTruthy();
    expect(screen.queryByTestId('regional-pack-none')).toBeNull();
  });

  it('reports a failed request as a failure, not as "no pack", and retries on request', async () => {
    vi.mocked(apiGet).mockRejectedValue(new Error('offline'));
    renderApp(<RegionalPackCard />);

    await screen.findByTestId('regional-pack-error');
    expect(screen.queryByText('No regional pack is active')).toBeNull();
    expect(screen.queryByText('Install a country pack')).toBeNull();

    const callsBefore = vi.mocked(apiGet).mock.calls.length;
    vi.mocked(apiGet).mockResolvedValue(ACTIVE_PACK);
    fireEvent.click(screen.getByText('Retry'));
    await screen.findByTestId('regional-pack-active');
    expect(vi.mocked(apiGet).mock.calls.length).toBeGreaterThan(callsBefore);
  });
});

describe('RegionalPackCard, strings', () => {
  const CARD = resolve(HERE, '../RegionalPackCard.tsx');
  const EN = resolve(HERE, '../../../app/locales/en.ts');

  /** The card's source with comments removed, so prose about the UI does not
   *  read as UI. */
  function code(): string {
    return readFileSync(CARD, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '');
  }

  it('puts no literal text between JSX tags', () => {
    const literals = (code().match(/>[^<>{}]*</g) ?? [])
      .map((m) => m.slice(1, -1).trim())
      .filter((text) => /\p{L}{2,}/u.test(text));
    expect(literals).toEqual([]);
  });

  it('asks only for keys the English locale answers', () => {
    const en = readFileSync(EN, 'utf8');
    const keys = [...code().matchAll(/\bt\(\s*'([^'`]+)'/g)].map((m) => m[1]!);
    expect(keys.length).toBeGreaterThan(8);
    const missing = keys.filter((key) => !en.includes(`"${key}":`));
    expect(missing).toEqual([]);
  });
});
