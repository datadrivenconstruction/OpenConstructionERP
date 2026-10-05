// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

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

import { meFixture } from './__fixtures__/me';
import {
  CoursePath,
  isCourseFinished,
  nextTaskOf,
  passedRun,
  sortTasks,
  stationStateOf,
  taskHref,
} from './CoursePath';
import type { TaskSummary } from './types';
import { useTrainerUiStore } from './useTrainerUiStore';

const tasks = meFixture.tasks;

beforeEach(() => useTrainerUiStore.getState().reset());
afterEach(() => cleanup());

function withStatus(list: TaskSummary[], status: TaskSummary['status']): TaskSummary[] {
  return list.map((t) => ({ ...t, status }));
}

describe('path helpers', () => {
  it('the next task is the first neither passed nor locked, in course order', () => {
    expect(nextTaskOf(tasks)?.id).toBe('t2-markups');
    expect(nextTaskOf([...tasks].reverse())?.id).toBe('t2-markups');
    expect(nextTaskOf(withStatus(tasks, 'passed'))).toBeNull();
  });

  it('an empty course is never finished', () => {
    expect(isCourseFinished([])).toBe(false);
    expect(isCourseFinished(tasks)).toBe(false);
    expect(isCourseFinished(withStatus(tasks, 'passed'))).toBe(true);
  });

  it('maps every status to a station state', () => {
    const one = tasks[0]!;
    expect(stationStateOf({ ...one, status: 'passed' })).toBe('done');
    expect(stationStateOf({ ...one, status: 'locked' })).toBe('locked');
    expect(stationStateOf({ ...one, status: 'needs_revision' })).toBe('revision');
    expect(stationStateOf({ ...one, status: 'in_progress' })).toBe('current');
    expect(stationStateOf({ ...one, status: 'not_started' })).toBe('open');
  });

  it('counts the passed run from the start of the path', () => {
    expect(passedRun(tasks)).toBe(1);
    expect(passedRun(sortTasks(withStatus(tasks, 'passed')))).toBe(5);
  });

  it('the task href carries the anchor, else falls back to the screen', () => {
    expect(taskHref(tasks[1]!, null)).toBe('/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel');
    expect(taskHref(tasks[0]!, null)).toBe('/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b');
    expect(taskHref({ target: { route: '/boq/x#here', anchor: 'there' } }, null)).toBe('/boq/x#here');
    expect(taskHref({ target: null }, { label: 'Variations', route: '/variations' })).toBe('/variations');
    expect(taskHref({ target: null }, null)).toBeNull();
  });
});

describe('CoursePath', () => {
  function renderPath(selected: string | null = 't2-markups', onSelect = vi.fn()) {
    render(
      <MemoryRouter>
        <CoursePath
          tasks={tasks}
          nextTaskId="t2-markups"
          selectedTaskId={selected}
          onSelect={onSelect}
          courseLocale="en-GB"
          detailId="detail"
        />
      </MemoryRouter>,
    );
    return onSelect;
  }

  it('draws one station per task with its state in the accessible name', () => {
    renderPath();
    const stations = screen.getAllByRole('button');
    expect(stations).toHaveLength(5);
    expect(stations[0]).toHaveAccessibleName('Task 1: Price the blockwork and read the direct cost, verified');
    expect(stations[1]).toHaveAccessibleName('Task 2: Add overheads and profit, needs another look');
    expect(stations[2]).toHaveAccessibleName('Task 3: Level the roofing bids and award, locked');
    expect(stations[1]).toHaveAttribute('aria-pressed', 'true');
    expect(stations[0]).toHaveAttribute('aria-pressed', 'false');
    expect(stations[0]).toHaveAttribute('aria-controls', 'detail');
    // Where the task happens and what it opens reach a screen reader too.
    expect(stations[2]).toHaveAccessibleDescription('Bid Management Opens Progress claims');
    expect(stations[1]).toHaveAccessibleDescription('Bill of Quantities Opens Bid Management');
  });

  it('every row says what the learner does, where, and what it opens', () => {
    renderPath();
    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]!).getByText('Price the blockwork and read the direct cost')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Bill of Quantities')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Opens Markups')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Bid Management')).toBeInTheDocument();
    expect(within(rows[3]!).getByText('Contracts')).toBeInTheDocument();
    expect(within(rows[4]!).getByText('Variations')).toBeInTheDocument();
    expect(within(rows[4]!).getByText('Earns Course badge')).toBeInTheDocument();
  });

  it('course text carries the course language', () => {
    renderPath();
    expect(screen.getByText('Add overheads and profit')).toHaveAttribute('lang', 'en-GB');
  });

  it('the next station pulses, and only that one', () => {
    renderPath();
    const pulses = screen.getAllByTestId('trainer-station-pulse');
    expect(pulses).toHaveLength(1);
    expect(screen.getAllByRole('listitem')[1]!.contains(pulses[0]!)).toBe(true);
    expect(pulses[0]!.className).toContain('motion-reduce:hidden');
  });

  it('a click selects, including a locked station', () => {
    const onSelect = renderPath();
    fireEvent.click(screen.getAllByRole('button')[3]!);
    expect(onSelect).toHaveBeenCalledWith('t4-valuation');
  });

  it('arrow keys walk the stations, Home and End jump', () => {
    renderPath();
    const stations = screen.getAllByRole('button');
    stations[1]!.focus();
    fireEvent.keyDown(stations[1]!, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(stations[2]);
    fireEvent.keyDown(stations[2]!, { key: 'ArrowLeft' });
    expect(document.activeElement).toBe(stations[1]);
    fireEvent.keyDown(stations[1]!, { key: 'End' });
    expect(document.activeElement).toBe(stations[4]);
    fireEvent.keyDown(stations[4]!, { key: 'Home' });
    expect(document.activeElement).toBe(stations[0]);
  });

  it('the green track covers the passed run', () => {
    renderPath();
    // 5 stations: centres at 10%..90%, one passed task fills 20%.
    expect(screen.getByTestId('trainer-path-track-fill').style.width).toBe('20%');
  });

  it('names an unknown module through its target route, or says it is another screen', () => {
    const odd: TaskSummary[] = [
      { ...tasks[0]!, id: 'a', module: 'oe_mystery', target: { route: '/projects/p1/variations', anchor: null } },
      { ...tasks[0]!, id: 'b', n: 2, module: 'mystery', target: null },
    ];
    render(
      <MemoryRouter>
        <CoursePath tasks={odd} nextTaskId={null} selectedTaskId={null} onSelect={vi.fn()} courseLocale="en-GB" />
      </MemoryRouter>,
    );
    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]!).getByText('Variations')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Another screen of the app')).toBeInTheDocument();
  });
});
