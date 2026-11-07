// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Academy links as a reader meets them: the "Learn this step" chip on a
// screen, its popover, the paid marker (crown and a tooltip, never a price),
// the hub page and the settings switch.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, afterEach, beforeAll, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const counted = opts?.count === 1 ? opts.defaultValue_one : opts?.defaultValue_other;
      const template = typeof opts?.defaultValue === 'string' ? opts.defaultValue : typeof counted === 'string' ? counted : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

import { ModuleVideosSlot } from './ModuleVideosSlot';
import { AcademyItemCard, AcademyItemRow } from './AcademyItemLinks';
import { CoursesPage } from './CoursesPage';
import { LearningTipsCard } from '../settings/LearningTipsCard';
import { ITEM_COUNT_BY_ROUTE, VIDEO_COUNT_BY_ROUTE } from './academyIndex.generated';
import { ACADEMY_ITEMS } from './academyItems.generated';
import { itemsForRoute, itemsForScreen } from './academyItems';
import { useVideoHintsStore } from './videoRoutes';
import { useVideosStore } from './useVideosStore';

function renderAt(path: string, node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const itemOnlyRoute = Object.keys(ITEM_COUNT_BY_ROUTE).find((r) => !(r in VIDEO_COUNT_BY_ROUTE))!;
const bothRoute = '/boq';
const paidItem = ACADEMY_ITEMS.find((i) => i.access === 'paid')!;
const freeItem = ACADEMY_ITEMS.find((i) => i.access === 'free' && i.kind === 'course')!;

beforeAll(async () => {
  await import('./ModuleVideosPanel');
}, 60_000);

beforeEach(() => {
  localStorage.clear();
  useVideoHintsStore.setState({ off: false, hidden: [] });
  useVideosStore.setState({ role: null, market: 'auto', started: {}, watched: {} });
});
afterEach(() => cleanup());

describe('the chip on a screen', () => {
  it('is there in the first render for a route that has courses but no videos', () => {
    expect(itemOnlyRoute).toBeTruthy();
    renderAt(itemOnlyRoute, <ModuleVideosSlot />);
    const toggle = screen.getByTestId('module-videos-toggle');
    expect(toggle.textContent).toContain('Learn this step');
    expect(toggle.textContent).toContain(String(ITEM_COUNT_BY_ROUTE[itemOnlyRoute]));
  });

  it('keeps the videos wording where a route has videos only', () => {
    const videoOnly = Object.keys(VIDEO_COUNT_BY_ROUTE).find((r) => !(r in ITEM_COUNT_BY_ROUTE))!;
    renderAt(videoOnly, <ModuleVideosSlot />);
    expect(screen.getByTestId('module-videos-toggle').textContent).toContain('Videos for this step');
  });

  it('counts videos and courses together', () => {
    renderAt(bothRoute, <ModuleVideosSlot />);
    const total = VIDEO_COUNT_BY_ROUTE[bothRoute]! + ITEM_COUNT_BY_ROUTE[bothRoute]!;
    expect(screen.getByTestId('module-videos-toggle').textContent).toContain(String(total));
  });

  it('is hidden after "hide here" for that screen only, and when hidden everywhere', () => {
    useVideoHintsStore.getState().hideOn(itemOnlyRoute);
    renderAt(itemOnlyRoute, <ModuleVideosSlot />);
    expect(screen.queryByTestId('module-videos')).toBeNull();
    cleanup();
    renderAt(bothRoute, <ModuleVideosSlot />);
    expect(screen.getByTestId('module-videos')).toBeTruthy();
    cleanup();
    useVideoHintsStore.setState({ off: true, hidden: [] });
    renderAt(bothRoute, <ModuleVideosSlot />);
    expect(screen.queryByTestId('module-videos')).toBeNull();
  });

  it('opens nothing by itself', () => {
    renderAt(bothRoute, <ModuleVideosSlot />);
    expect(screen.getByTestId('module-videos-toggle').getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByTestId('academy-item-row')).toBeNull();
  });

  it('opens the courses in a popover: new-tab links, at most one purple row', async () => {
    renderAt(bothRoute, <ModuleVideosSlot />);
    fireEvent.click(screen.getByTestId('module-videos-toggle'));
    const rows = await screen.findAllByTestId('academy-item-row');
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThanOrEqual(3);
    expect(rows.filter((r) => r.getAttribute('data-access') === 'paid').length).toBeLessThanOrEqual(1);
    for (const row of rows) {
      expect(row.getAttribute('target')).toBe('_blank');
      expect(row.getAttribute('rel')).toContain('noopener');
      expect(row.getAttribute('href')).toMatch(/^https:\/\/openconstructionacademy\.com\//);
    }
    expect(screen.getByText('All courses and guides').closest('a')?.getAttribute('href')).toBe(
      `/courses?route=${encodeURIComponent(bothRoute)}`,
    );
  });

  it('lists what the ranking picked, and no more than three', async () => {
    renderAt(bothRoute, <ModuleVideosSlot />);
    fireEvent.click(screen.getByTestId('module-videos-toggle'));
    const rows = await screen.findAllByTestId('academy-item-row');
    const allowed = itemsForRoute(bothRoute).map((i) => i.title);
    expect(rows.length).toBe(itemsForScreen(bothRoute, { language: 'en', market: null }, 3).length);
    for (const row of rows) expect(allowed.some((title) => row.textContent?.includes(title))).toBe(true);
  });
});

describe('the paid marker', () => {
  it('shows a crown and a tooltip the link is described by', () => {
    render(<AcademyItemRow item={paidItem} />);
    const link = screen.getByTestId('academy-item-row');
    const tip = screen.getByRole('tooltip');
    expect(link.getAttribute('aria-describedby')).toBe(tip.id);
    expect(tip.textContent).toBe('Paid training course');
    expect(link.querySelector('svg.lucide-crown')).not.toBeNull();
  });

  it('shows neither on a free row', () => {
    render(<AcademyItemRow item={freeItem} />);
    const link = screen.getByTestId('academy-item-row');
    expect(link.getAttribute('aria-describedby')).toBeNull();
    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(link.querySelector('svg.lucide-crown')).toBeNull();
  });

  it('hides the tooltip on Escape while focus stays, and brings it back on blur', () => {
    render(<AcademyItemRow item={paidItem} />);
    const link = screen.getByTestId('academy-item-row');
    const tip = screen.getByRole('tooltip');
    link.focus();
    fireEvent.keyDown(link, { key: 'Escape' });
    expect(tip.className).toContain('!opacity-0');
    fireEvent.blur(link);
    expect(tip.className).not.toContain('!opacity-0');
  });

  it('uses the word "paid" only inside the tooltip, on rows and cards', () => {
    const { container } = render(
      <>
        <AcademyItemRow item={paidItem} />
        <AcademyItemCard item={paidItem} />
        <AcademyItemRow item={freeItem} />
      </>,
    );
    // Titles are the Academy's own words; everything else is ours.
    container.querySelectorAll('[role="tooltip"], [lang]').forEach((el) => el.remove());
    expect((container.textContent ?? '').toLowerCase()).not.toMatch(/paid|price|\bplan\b|\bbuy\b|checkout|upgrade|€/);
  });

  it('gives a lesson its own wording', () => {
    render(<AcademyItemRow item={{ ...paidItem, kind: 'lesson' }} />);
    expect(screen.getByRole('tooltip').textContent).toBe('Lesson from a paid training course');
  });

  it('opens the Academy in a new tab from a card, with the content language on the title', () => {
    render(<AcademyItemCard item={freeItem} />);
    const card = screen.getByTestId('academy-item-card');
    expect(card.getAttribute('target')).toBe('_blank');
    expect(card.getAttribute('rel')).toBe('noopener noreferrer');
    expect(within(card).getByText(freeItem.title).getAttribute('lang')).toBe(freeItem.contentLanguage);
  });
});

describe('the hub page', () => {
  it('lists the items in a grid of links', () => {
    renderAt('/courses', <CoursesPage />);
    expect(screen.getAllByTestId('academy-item-card').length).toBeGreaterThan(20);
  });

  it('narrows to one screen from the URL and says which', () => {
    renderAt(`/courses?route=${encodeURIComponent(bothRoute)}`, <CoursesPage />);
    expect(screen.getByTestId('courses-route-chip').textContent).toContain('This screen only');
    const cards = screen.getAllByTestId('academy-item-card');
    const here = ACADEMY_ITEMS.filter((i) => i.routes.includes(bothRoute));
    expect(cards.length).toBeGreaterThanOrEqual(here.filter((i) => !i.market).length);
    expect(cards.length).toBeLessThanOrEqual(here.length);
  });

  it('shows a way out when no filter matches', () => {
    renderAt('/courses?q=zzzzzz-nothing', <CoursesPage />);
    expect(screen.getByText('Nothing matches these filters')).toBeTruthy();
    fireEvent.click(screen.getByText('Clear filters'));
    expect(screen.getAllByTestId('academy-item-card').length).toBeGreaterThan(20);
  });

  it('lists a country item for every reader, flagged with its country', () => {
    renderAt('/courses', <CoursesPage />);
    const hr = ACADEMY_ITEMS.find((i) => i.market === 'HR')!;
    expect(screen.getByText(hr.title)).toBeTruthy();
    expect(screen.getAllByTestId('academy-item-country').length).toBe(ACADEMY_ITEMS.filter((i) => i.country ?? i.market).length);
  });

  it('narrows by country, shows the count and removes the filter again', () => {
    renderAt('/courses?country=HR&sort=az', <CoursesPage />);
    const hrCount = ACADEMY_ITEMS.filter((i) => i.market === 'HR').length;
    expect(screen.getAllByTestId('academy-item-card').length).toBe(hrCount);
    expect(screen.getByTestId('courses-count').textContent).toContain(String(hrCount));
    fireEvent.click(screen.getByLabelText(/Remove filter/));
    expect(screen.getAllByTestId('academy-item-card').length).toBe(ACADEMY_ITEMS.length);
  });

  it('draws no flag on a universal item', () => {
    renderAt('/courses?country=none', <CoursesPage />);
    expect(screen.queryAllByTestId('academy-item-country')).toHaveLength(0);
  });
});

describe('the learning tips card', () => {
  it('writes the global switch to the same store the chip reads', () => {
    render(<LearningTipsCard />);
    const sw = screen.getByTestId('learning-tips-switch');
    expect(sw.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(sw);
    expect(JSON.parse(localStorage.getItem('oe_videos_hints')!).off).toBe(true);
    expect(sw.getAttribute('aria-checked')).toBe('false');
  });

  it('counts hidden screens and brings them all back', () => {
    useVideoHintsStore.setState({ off: false, hidden: ['/boq', '/finance'] });
    render(<LearningTipsCard />);
    expect(screen.getByTestId('learning-tips-hidden-count').textContent).toContain('2');
    fireEvent.click(screen.getByTestId('learning-tips-show-all'));
    expect(localStorage.getItem('oe_videos_hints')).toBeNull();
    expect(useVideoHintsStore.getState().hidden).toEqual([]);
  });
});
