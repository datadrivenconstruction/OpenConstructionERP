// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const template = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

const modeState = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('./useTrainerMode', () => ({ useTrainerMode: () => modeState.current }));

import { meFixture } from './__fixtures__/me';
import { CourseMapPage, ringsFromProgress } from './CourseMapPage';
import type { TrainerMe } from './types';
import type { TrainerMode, TrainerModeState } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

const refetch = vi.fn();

function setMode(state: TrainerModeState, me: TrainerMe | null = null) {
  const mode: TrainerMode = {
    state,
    academyMode: state !== 'off',
    known: state !== 'checking',
    active: state === 'enrolled',
    me,
    refetch,
  };
  modeState.current = mode;
}

function Probe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.hash}</div>;
}

function renderMap() {
  return render(
    <MemoryRouter initialEntries={['/academy']}>
      <Routes>
        <Route path="/academy" element={<CourseMapPage />} />
        <Route path="*" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );
}

function finishedMe(): TrainerMe {
  return {
    ...meFixture,
    tasks: meFixture.tasks.map((t) => ({ ...t, status: 'passed' as const })),
    progress: { ...meFixture.progress, done: 5 },
  };
}

beforeEach(() => {
  refetch.mockReset();
  useTrainerUiStore.getState().reset();
});
afterEach(() => cleanup());

describe('CourseMapPage states', () => {
  it.each(['checking', 'loading'] as const)('%s shows the skeleton, never a blank page', (state) => {
    setMode(state);
    renderMap();
    const loading = screen.getByTestId('trainer-map-loading');
    expect(loading).toHaveAttribute('aria-busy', 'true');
    expect(within(loading).getByText('Loading your course')).toBeInTheDocument();
  });

  it('error explains, reassures, and retries', () => {
    setMode('error');
    renderMap();
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Your course did not load')).toBeInTheDocument();
    expect(screen.getByText('Nothing you entered is lost. Try again in a moment.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it.each(['none', 'off'] as const)('%s shows "No course yet" with Check again', (state) => {
    setMode(state);
    renderMap();
    expect(screen.getByText('No course yet')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe('CourseMapPage ready', () => {
  it('hero shows the course in its locale and the verified counter', () => {
    setMode('enrolled', meFixture);
    renderMap();
    const h1 = screen.getByRole('heading', { level: 1, name: meFixture.course.title });
    expect(h1.closest('[lang]')).toHaveAttribute('lang', 'en-GB');
    expect(screen.getByText(meFixture.course.summary!)).toBeInTheDocument();
    expect(screen.getByTestId('trainer-map-counter')).toHaveTextContent('1/5tasks verified');
  });

  it('rings come from the API ring map, any ids', () => {
    expect(ringsFromProgress(meFixture.progress.rings).map((r) => r.id)).toEqual(['numbers', 'trace', 'explain']);
    const extra = { ...meFixture.progress.rings, habit: { done: 1, total: 2 } } as unknown as TrainerMe['progress']['rings'];
    expect(ringsFromProgress(extra).map((r) => r.id)).toEqual(['numbers', 'trace', 'explain', 'habit']);
    setMode('enrolled', meFixture);
    renderMap();
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('Trace 2 of 5');
  });

  it('week card uses the API week', () => {
    setMode('enrolled', meFixture);
    renderMap();
    expect(screen.getByText('1 of 3 verified tasks')).toBeInTheDocument();
  });

  it('week card still renders when the API sends no week', () => {
    setMode('enrolled', { ...meFixture, week: null });
    renderMap();
    expect(screen.getByText('0 of 3 verified tasks')).toBeInTheDocument();
  });

  it('Up next names the task, its check and its screen, and Continue opens it', () => {
    setMode('enrolled', meFixture);
    renderMap();
    const card = screen.getByTestId('trainer-up-next');
    expect(within(card).getByText('Add overheads and profit')).toBeInTheDocument();
    expect(within(card).getByText('Type the overheads amount.')).toBeInTheDocument();
    expect(within(card).getByText('You work in Bill of Quantities.')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Continue in Bill of Quantities' }));
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel',
    );
    expect(useTrainerUiStore.getState().dockTaskId).toBe('t2-markups');
    expect(useTrainerUiStore.getState().dockOpen).toBe(true);
  });

  it('Up next says Start for a task not started', () => {
    const me = { ...meFixture, tasks: meFixture.tasks.map((t) => (t.n === 2 ? { ...t, status: 'not_started' as const } : t)) };
    setMode('enrolled', me);
    renderMap();
    expect(within(screen.getByTestId('trainer-up-next')).getByRole('button', { name: 'Start task 2' })).toBeInTheDocument();
  });

  it('Up next has a Watch link to the task video', () => {
    setMode('enrolled', meFixture);
    renderMap();
    expect(within(screen.getByTestId('trainer-up-next')).getByRole('link', { name: 'Watch' })).toHaveAttribute(
      'href',
      '/videos?episode=FX02',
    );
  });

  it('the detail defaults to the next task and follows a station click', () => {
    setMode('enrolled', meFixture);
    renderMap();
    const detail = screen.getByTestId('trainer-task-detail');
    expect(within(detail).getByRole('heading', { name: 'Add overheads and profit' })).toBeInTheDocument();
    // Selecting does not write the default into the store; only a click does.
    expect(useTrainerUiStore.getState().selectedTaskId).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Task 4: Value the first claim, locked' }));
    expect(useTrainerUiStore.getState().selectedTaskId).toBe('t4-valuation');
    expect(within(screen.getByTestId('trainer-task-detail')).getByRole('heading', { name: 'Value the first claim' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Task 4: Value the first claim, locked' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('a stale stored selection falls back to the next task', () => {
    useTrainerUiStore.getState().selectTask('gone');
    setMode('enrolled', meFixture);
    renderMap();
    expect(within(screen.getByTestId('trainer-task-detail')).getByRole('heading', { name: 'Add overheads and profit' })).toBeInTheDocument();
  });

  it('dates in course text are written in words in the course locale', () => {
    const me = { ...meFixture, course: { ...meFixture.course, summary: 'Tender closes 2026-09-01.' } };
    setMode('enrolled', me);
    renderMap();
    expect(screen.getByText('Tender closes 1 September 2026.')).toBeInTheDocument();
  });

  it('a course in another script carries its own lang and dir', () => {
    const me = { ...meFixture, course: { ...meFixture.course, locale: 'ar-SA', language: 'ar', country: 'SA' } };
    setMode('enrolled', me);
    renderMap();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1.closest('[lang]')).toHaveAttribute('dir', 'rtl');
  });
});

describe('CourseMapPage finished', () => {
  it('Up next becomes the badge card; the path stays and the detail shows the last task', () => {
    setMode('enrolled', finishedMe());
    renderMap();
    expect(screen.queryByTestId('trainer-up-next')).toBeNull();
    const badge = screen.getByTestId('trainer-badge-card');
    expect(within(badge).getByText('Course complete')).toBeInTheDocument();
    expect(within(badge).getByText('Quillmere Depot: bill to variation')).toBeInTheDocument();
    expect(within(badge).getByText('5 of 5 verified.')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /verified$/ })).toHaveLength(5);
    expect(within(screen.getByTestId('trainer-task-detail')).getByRole('heading', { name: 'Value the rooflight variation' })).toBeInTheDocument();
    expect(screen.queryAllByTestId('trainer-station-pulse')).toHaveLength(0);
  });

  it('an empty task list is not a finished course', () => {
    setMode('enrolled', { ...meFixture, tasks: [] });
    renderMap();
    expect(screen.queryByTestId('trainer-badge-card')).toBeNull();
    expect(screen.getByTestId('trainer-up-next')).toBeInTheDocument();
  });

  it('nothing open and not finished says so instead of an empty card', () => {
    const me = { ...meFixture, tasks: meFixture.tasks.map((t) => (t.status === 'passed' ? t : { ...t, status: 'locked' as const })) };
    setMode('enrolled', me);
    renderMap();
    expect(within(screen.getByTestId('trainer-up-next')).getByText(/Nothing is open right now/)).toBeInTheDocument();
  });
});
