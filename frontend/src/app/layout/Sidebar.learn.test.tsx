// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Learn card (Videos, Cases) at the top of the sidebar: where it sits, that
// the user can hide it and bring it back, and that the choice survives a
// reload. "Survives a reload" is read off the store module itself: the store
// reads localStorage once, at import, so re-rendering the sidebar would only
// prove the in-memory state. The last test imports a fresh copy of the store
// over the stored value instead.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: unknown }) =>
      typeof opts?.defaultValue === 'string' ? opts.defaultValue : key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

vi.mock('@/shared/lib/useI18nReady', () => ({ useI18nReady: () => 0 }));
vi.mock('./CustomBranding', () => ({ CustomBranding: () => null }));
vi.mock('@/shared/ui/UpdateChecker', () => ({ UpdateNotification: () => null }));
vi.mock('@/features/modules/RequestCustomModuleDialog', () => ({
  RequestCustomModuleDialog: () => null,
}));
vi.mock('@/shared/hooks/useSidebarBadges', () => ({
  useSidebarBadges: () => ({ tasks: 0, rfi: 0, safety: 0 }),
}));
vi.mock('@/shared/hooks/useHiddenModules', () => ({
  useHiddenModules: () => ({ hiddenModules: [], setHiddenModules: vi.fn() }),
}));
vi.mock('@/features/projects/useProjectProfile', () => ({
  useActiveProjectProfile: () => ({ projectId: null, profile: undefined, isLoading: false }),
  buildModuleGate: () => ({ active: false, byRoute: () => null }),
}));

import { Sidebar } from './Sidebar';
import { LearnTopBarButton } from './LearnTopBarButton';
import { LEARN_GROUP_ID } from './navCatalog';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useSidebarCollapseStore } from '@/stores/useSidebarCollapseStore';
import { useToastStore } from '@/stores/useToastStore';

const HIDDEN_GROUPS_KEY = 'oe_hidden_groups';

function renderSidebar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        {/* The top bar's cap, which is where the card goes when hidden. */}
        <LearnTopBarButton />
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const nav = () => screen.getByRole('navigation', { name: 'Main navigation' });

const storedHiddenGroups = (): string[] => JSON.parse(localStorage.getItem(HIDDEN_GROUPS_KEY) ?? '[]');

beforeEach(() => {
  localStorage.clear();
  api.apiGet.mockReset();
  api.apiGet.mockImplementation((path: string) =>
    path === '/v1/users/me/onboarding/'
      ? Promise.resolve({ completed: true, company_type: null })
      : Promise.resolve([]),
  );
  useAuthStore.setState({ isAuthenticated: true, userRole: 'editor', userId: 'user-a', accessToken: null });
  useModuleStore.setState({ enabledModules: {}, hiddenGroups: [] });
  useViewModeStore.getState().setMode('simple');
  useSidebarCollapseStore.getState().setIconified(false);
  useToastStore.setState({ toasts: [] });
});

afterEach(() => cleanup());

describe('the featured article', () => {
  it('is no longer in the menu; it lives on the Cases page', () => {
    renderSidebar();
    const article = Array.from(document.querySelectorAll('a')).filter((a) =>
      (a.getAttribute('href') ?? '').includes('uberization-of-construction'),
    );
    expect(article).toEqual([]);
    expect(screen.queryByText('Uberization of Construction')).toBeNull();
  });
});

describe('the Learn card', () => {
  it('opens the menu, above Pinned, with Videos and then Cases', () => {
    localStorage.setItem('oce-pinned-routes', JSON.stringify(['/boq']));
    renderSidebar();

    const learn = screen.getByTestId('sidebar-learn');
    const hrefs = within(learn)
      .getAllByRole('link')
      .map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual(['/videos', '/cases']);

    const firstLinks = within(nav())
      .getAllByRole('link')
      .slice(0, 3)
      .map((a) => a.getAttribute('href'));
    expect(firstLinks).toEqual(['/videos', '/cases', '/boq']);
  });

  it('explains on its header that it can be hidden and shown again', () => {
    renderSidebar();

    const hide = screen.getByTestId('sidebar-learn-hide');
    const hintId = hide.getAttribute('aria-describedby');
    expect(hintId).toBeTruthy();
    const hint = document.getElementById(hintId!);
    expect(hint?.getAttribute('role')).toBe('tooltip');
    expect(hint?.textContent).toMatch(/graduation cap in the top bar/i);
    // Shown on hover and keyboard focus, and always where there is no hover.
    expect(hide.className).toContain('group-hover/learnhead:opacity-100');
    expect(hide.className).toContain('group-focus-within/learnhead:opacity-100');
    expect(hide.className).toContain('[@media(hover:none)]:opacity-100');
  });

  it('hides in one click into the top bar, says so, and comes back from there in one click', async () => {
    renderSidebar();
    expect(screen.queryByTestId('header-learn-restore')).toBeNull();

    fireEvent.click(screen.getByTestId('sidebar-learn-hide'));

    await waitFor(() => expect(screen.queryByTestId('sidebar-learn')).toBeNull());
    const hrefs = within(nav())
      .getAllByRole('link')
      .map((a) => a.getAttribute('href'));
    expect(hrefs).not.toContain('/videos');
    expect(hrefs).not.toContain('/cases');
    expect(storedHiddenGroups()).toEqual([LEARN_GROUP_ID]);

    const toast = useToastStore.getState().toasts.at(-1);
    expect(toast?.message).toMatch(/top bar/);
    expect(toast?.action).toBeDefined();

    const restore = screen.getByTestId('header-learn-restore');
    expect(restore.getAttribute('aria-label')).toBe('Show video guides & use cases');
    expect(restore.getAttribute('title')).toBe('Put Video guides and Use cases back at the top of the menu');
    fireEvent.click(restore);

    await screen.findByTestId('sidebar-learn');
    expect(storedHiddenGroups()).toEqual([]);
    expect(screen.queryByTestId('header-learn-restore')).toBeNull();
  });

  it('comes back from the toast Undo as well', async () => {
    renderSidebar();
    fireEvent.click(screen.getByTestId('sidebar-learn-hide'));
    await waitFor(() => expect(screen.queryByTestId('sidebar-learn')).toBeNull());

    useToastStore.getState().toasts.at(-1)!.action!.onClick();

    await screen.findByTestId('sidebar-learn');
    expect(storedHiddenGroups()).toEqual([]);
  });

  it('comes back from the top bar in the icon-only sidebar too, and an old hidden choice shows the cap', () => {
    // Stored before this release, when the way back sat at the foot of the menu.
    useModuleStore.getState().setGroupHidden(LEARN_GROUP_ID, true);
    useSidebarCollapseStore.getState().setIconified(true);
    renderSidebar();

    expect(screen.queryByTestId('sidebar-learn')).toBeNull();
    fireEvent.click(screen.getByTestId('header-learn-restore'));
    expect(screen.getByTestId('sidebar-learn')).toBeTruthy();
    expect(screen.queryByTestId('header-learn-restore')).toBeNull();
  });

  it('counts toward the "hidden" chip, and the menu editor can switch it back on', async () => {
    useModuleStore.getState().setGroupHidden(LEARN_GROUP_ID, true);
    renderSidebar();

    fireEvent.click(screen.getByTitle('Show hidden'));
    // In the editor the card is back on screen, dimmed, with the section eye.
    const learn = await screen.findByTestId('sidebar-learn');
    expect(learn.className).toContain('opacity-50');
    fireEvent.click(within(learn).getByRole('button', { name: /^Show .* section$/ }));
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(storedHiddenGroups()).toEqual([]));
    expect(screen.getByTestId('sidebar-learn').className).not.toContain('opacity-50');
  });

  it('stays shown when the cap restores it while the menu editor is open, and Save keeps it', async () => {
    useModuleStore.getState().setGroupHidden(LEARN_GROUP_ID, true);
    renderSidebar();
    fireEvent.click(screen.getByTitle('Show hidden'));
    await screen.findByTestId('sidebar-learn');

    fireEvent.click(screen.getByTestId('header-learn-restore'));
    await waitFor(() => expect(storedHiddenGroups()).toEqual([]));
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(storedHiddenGroups()).toEqual([]));
    expect(screen.getByTestId('sidebar-learn').className).not.toContain('opacity-50');
    expect(screen.queryByTestId('header-learn-restore')).toBeNull();
  });

  it('stays hidden after a reload', async () => {
    localStorage.setItem(HIDDEN_GROUPS_KEY, JSON.stringify([LEARN_GROUP_ID]));
    vi.resetModules();
    const fresh = await import('@/stores/useModuleStore');
    expect(fresh.useModuleStore.getState().hiddenGroups).toEqual([LEARN_GROUP_ID]);

    localStorage.setItem(HIDDEN_GROUPS_KEY, JSON.stringify([]));
    vi.resetModules();
    const shown = await import('@/stores/useModuleStore');
    expect(shown.useModuleStore.getState().hiddenGroups).toEqual([]);
  });
});

describe('the flight between the menu and the top bar', () => {
  type FakeAnimation = { el: Element; frames: Keyframe[]; onfinish: (() => void) | null; oncancel: (() => void) | null };
  let animations: FakeAnimation[] = [];
  let reduce = false;
  // Where each slot is, per test: the menu's cap near the top left, the top
  // bar's near the top right, both close to the top edge of the window.
  let rects: Record<string, Partial<DOMRect>> = {};
  const box = (left: number, top: number, size = 20) =>
    ({ left, top, width: size, height: size, right: left + size, bottom: top + size, x: left, y: top, toJSON: () => ({}) }) as DOMRect;

  beforeEach(() => {
    reduce = false;
    animations = [];
    rects = { sidebar: box(24, 12), topbar: box(900, 14) };
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('prefers-reduced-motion') ? reduce : false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
    }));
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      const anchor = this.getAttribute('data-learn-anchor');
      if (anchor) return rects[anchor] as DOMRect;
      // Everything else, the menu's scroll area included, fills the window.
      return box(0, 0, 4000);
    });
    (HTMLElement.prototype as unknown as { animate: unknown }).animate = function (this: Element, frames: Keyframe[]) {
      const a: FakeAnimation = { el: this, frames, onfinish: null, oncancel: null };
      animations.push(a);
      return a as unknown as Animation;
    };
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete (HTMLElement.prototype as unknown as { animate?: unknown }).animate;
    document.querySelectorAll('[data-testid="learn-flight-ghost"]').forEach((g) => g.remove());
  });

  const ghost = () => document.querySelector<HTMLElement>('[data-testid="learn-flight-ghost"]');
  const flight = () => animations.find((a) => a.el.getAttribute('data-testid') === 'learn-flight-ghost')!;

  it('flies a ghost of the cap to the top bar on an arc that stays on screen, then pulses the cap and clears up', async () => {
    renderSidebar();
    fireEvent.click(screen.getByTestId('sidebar-learn-hide'));
    await waitFor(() => expect(ghost()).not.toBeNull());
    expect(ghost()!.getAttribute('aria-hidden')).toBe('true');

    const frames = flight().frames.map((f) => String(f.transform));
    const ys = frames.map((f) => Number(/translate\([-\d.]+px, ([-\d.]+)px\)/.exec(f)![1]));
    expect(frames[0]).toContain('translate(20px, 8px)');
    expect(frames[2]).toContain('translate(896px, 10px)');
    // Both slots sit near the top edge; the arc's peak must not leave the window.
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(4);

    flight().onfinish!();
    expect(ghost()).toBeNull();
    const pulse = animations.at(-1)!;
    expect(pulse.el.getAttribute('data-testid')).toBe('header-learn-restore');
    expect(String(pulse.frames[1]!.transform)).toContain('scale(');
  });

  it('flies back into the menu from the top bar, and lands focus on the hide control', async () => {
    useModuleStore.getState().setGroupHidden(LEARN_GROUP_ID, true);
    renderSidebar();
    const cap = screen.getByTestId('header-learn-restore');
    cap.focus();
    fireEvent.click(cap);
    await waitFor(() => expect(ghost()).not.toBeNull());
    expect(document.activeElement).toBe(screen.getByTestId('sidebar-learn-hide'));
    flight().onfinish!();
    expect(ghost()).toBeNull();
  });

  it('moves keyboard focus to the cap after hiding, not to the page', async () => {
    renderSidebar();
    const hide = screen.getByTestId('sidebar-learn-hide');
    hide.focus();
    fireEvent.click(hide);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('header-learn-restore')));
  });

  it('does not fly from a slot the reader cannot see, such as the closed phone drawer', async () => {
    rects.sidebar = box(-300, 12);
    renderSidebar();
    fireEvent.click(screen.getByTestId('sidebar-learn-hide'));
    // The cap still gets its pulse; nothing flies in from off screen.
    await waitFor(() => expect(animations.length).toBeGreaterThan(0));
    expect(ghost()).toBeNull();
    expect(animations.at(-1)!.el.getAttribute('data-testid')).toBe('header-learn-restore');
  });

  it('skips the flight under reduced motion and only fades the cap in', async () => {
    reduce = true;
    renderSidebar();
    fireEvent.click(screen.getByTestId('sidebar-learn-hide'));
    await waitFor(() => expect(animations.length).toBeGreaterThan(0));
    expect(ghost()).toBeNull();
    expect(animations.at(-1)!.frames).toEqual([{ opacity: 0 }, { opacity: 1 }]);
    expect(screen.getByTestId('header-learn-restore')).toBeTruthy();
  });
});
