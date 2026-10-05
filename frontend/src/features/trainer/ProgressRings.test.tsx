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

import { orderRings, ProgressRings, ringDashArray, ringFraction } from './ProgressRings';

afterEach(() => cleanup());

describe('ring maths', () => {
  it('fills by done/total and clamps to 0..1', () => {
    expect(ringFraction(1, 5)).toBeCloseTo(0.2);
    expect(ringFraction(7, 5)).toBe(1);
    expect(ringFraction(-1, 5)).toBe(0);
    expect(ringFraction(3, 0)).toBe(0);
    expect(ringFraction(Number.NaN, 5)).toBe(0);
  });

  it('builds the dasharray from the circumference', () => {
    const c = 2 * Math.PI * 58;
    expect(ringDashArray(58, 0.2)).toBe(`${(c * 0.2).toFixed(1)} ${c.toFixed(1)}`);
    expect(ringDashArray(58, 0)).toBe(`0.0 ${c.toFixed(1)}`);
  });

  it('puts Numbers, Trace, Explain first and keeps any other id after them', () => {
    const ids = orderRings([{ id: 'habit' }, { id: 'explain' }, { id: 'numbers' }, { id: 'trace' }]).map((r) => r.id);
    expect(ids).toEqual(['numbers', 'trace', 'explain', 'habit']);
  });
});

describe('ProgressRings', () => {
  const three = [
    { id: 'numbers', done: 1, total: 5 },
    { id: 'trace', done: 2, total: 5 },
    { id: 'explain', done: 1, total: 5 },
  ];

  it('labels the figure with every ring, joined as a list', () => {
    render(<ProgressRings rings={three} />);
    const fig = screen.getByRole('img');
    expect(fig).toHaveAttribute(
      'aria-label',
      'Progress rings: Numbers 1 of 5, Trace 2 of 5, and Explain 1 of 5',
    );
  });

  it('draws each arc to its own fraction (no animation without matchMedia)', () => {
    render(<ProgressRings rings={three} />);
    const outer = screen.getByTestId('trainer-ring-arc-numbers');
    // Outer ring radius = 132/2 - 12/2 = 60.
    expect(outer.getAttribute('stroke-dasharray')).toBe(ringDashArray(60, 0.2));
    const middle = screen.getByTestId('trainer-ring-arc-trace');
    expect(middle.getAttribute('stroke-dasharray')).toBe(ringDashArray(60 - 16, 0.4));
  });

  it('total 0 draws the grey track only', () => {
    const { container } = render(<ProgressRings rings={[{ id: 'numbers', done: 0, total: 0 }]} />);
    expect(screen.queryByTestId('trainer-ring-arc-numbers')).toBeNull();
    expect(container.querySelectorAll('circle')).toHaveLength(1);
    expect(container.querySelector('circle')?.getAttribute('class')).toContain('stroke-border');
  });

  it('takes any ring ids: a fourth ring with the course label', () => {
    const { container } = render(
      <ProgressRings rings={[...three, { id: 'habit', done: 3, total: 4, label: 'Habit' }]} />,
    );
    expect(container.querySelectorAll('[data-ring]')).toHaveLength(4);
    expect(screen.getByTestId('trainer-ring-arc-habit')).toBeInTheDocument();
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('Habit 3 of 4');
    expect(screen.getByText('3/4')).toBeInTheDocument();
  });

  it('takes a single ring without assuming three', () => {
    const { container } = render(<ProgressRings rings={[{ id: 'trace', done: 1, total: 1 }]} />);
    expect(container.querySelectorAll('[data-ring]')).toHaveLength(1);
    expect(screen.getByText('Trace')).toBeInTheDocument();
  });

  it('an id with neither a known name nor a label shows the id', () => {
    render(<ProgressRings rings={[{ id: 'site_walk', done: 0, total: 2 }]} />);
    expect(screen.getByText('site_walk')).toBeInTheDocument();
  });

  it('starts empty and sweeps in when motion is allowed', async () => {
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia;
    try {
      render(<ProgressRings rings={three} />);
      const outer = screen.getByTestId('trainer-ring-arc-numbers');
      expect(outer.getAttribute('stroke-dasharray')).toBe(ringDashArray(60, 0));
      await vi.waitFor(() => expect(outer.getAttribute('stroke-dasharray')).toBe(ringDashArray(60, 0.2)));
    } finally {
      window.matchMedia = original;
    }
  });

  it('reduced motion draws the rings filled at once', () => {
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
    try {
      render(<ProgressRings rings={three} />);
      expect(screen.getByTestId('trainer-ring-arc-numbers').getAttribute('stroke-dasharray')).toBe(
        ringDashArray(60, 0.2),
      );
    } finally {
      window.matchMedia = original;
    }
  });
});
