// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

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
import { DEFAULT_WEEK_GOAL, weekGoal, WeekStrip } from './WeekStrip';

afterEach(() => cleanup());

const days = meFixture.week!.days;

describe('weekGoal', () => {
  it('uses the course goal, else 3', () => {
    expect(DEFAULT_WEEK_GOAL).toBe(3);
    expect(weekGoal(5)).toBe(5);
    expect(weekGoal(null)).toBe(3);
    expect(weekGoal(undefined)).toBe(3);
    expect(weekGoal(0)).toBe(3);
    expect(weekGoal(-2)).toBe(3);
    expect(weekGoal(Number.NaN)).toBe(3);
  });
});

describe('WeekStrip', () => {
  it('shows the week summary against the goal', () => {
    render(<WeekStrip goal={3} done={1} days={days} />);
    expect(screen.getByText('This week')).toBeInTheDocument();
    expect(screen.getByText('1 of 3 verified tasks')).toBeInTheDocument();
  });

  it('defaults the goal to 3 when the course sets none', () => {
    render(<WeekStrip goal={null} done={0} days={[]} />);
    expect(screen.getByText('0 of 3 verified tasks')).toBeInTheDocument();
  });

  it('names every day in words with its state, Monday first, in UTC', () => {
    render(<WeekStrip goal={3} done={1} days={days} />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
    expect(items[0]).toHaveTextContent('Monday, October 5: verified task');
    expect(items[1]).toHaveTextContent('Tuesday, October 6: nothing yet');
    expect(items[5]).toHaveTextContent('Saturday, October 10: day off');
    expect(items[0]).toHaveAttribute('data-state', 'done');
  });

  it('marks today only when told which day it is', () => {
    const { rerender, container } = render(<WeekStrip goal={3} done={1} days={days} />);
    expect(container.querySelector('[data-today]')).toBeNull();
    rerender(<WeekStrip goal={3} done={1} days={days} today="2026-10-07" />);
    expect(container.querySelector('[data-today]')).toHaveTextContent('Wed');
  });

  it('never frames an empty day as a loss: no red, no streak words', () => {
    const { container } = render(<WeekStrip goal={3} done={0} days={days} />);
    expect(container.innerHTML).not.toMatch(/error|red-|streak|lost|missed/i);
  });

  it('says the goal is reached once it is, and not before', () => {
    const { rerender } = render(<WeekStrip goal={3} done={2} days={days} />);
    expect(screen.queryByTestId('trainer-week-goal-met')).toBeNull();
    rerender(<WeekStrip goal={3} done={4} days={days} />);
    expect(screen.getByTestId('trainer-week-goal-met')).toBeInTheDocument();
  });

  it('with no days shows only the title and the summary', () => {
    render(<WeekStrip goal={2} done={1} days={[]} />);
    expect(screen.queryByRole('list')).toBeNull();
    expect(screen.getByText('1 of 2 verified tasks')).toBeInTheDocument();
  });
});
