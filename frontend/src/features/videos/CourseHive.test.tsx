// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { CourseHive } from './CourseHive';
import { ITEMS } from './academyItems';
import type { AcademyItem } from './academyTypes';
import {
  DONE_KEY,
  courseStatuses,
  defaultPath,
  hexDistance,
  hiveLayout,
  learningPaths,
  pathPercent,
  spiralCells,
} from './learningPaths';

const course = (slug: string, routes: string[], extra: Partial<AcademyItem> = {}): AcademyItem => ({
  id: `course:${slug}`,
  kind: 'course',
  title: slug,
  url: `https://example.org/${slug}/`,
  languages: ['en'],
  contentLanguage: 'en',
  access: 'free',
  durationMin: 180,
  topics: [],
  routes,
  ...extra,
});

const SAMPLE = [
  course('alpha-handover', ['/closeout']),
  course('alpha-tender', ['/tendering']),
  course('alpha-takeoff', ['/takeoff'], { access: 'paid' }),
  course('alpha-estimate', ['/boq'], { country: 'GB' }),
  course('beta-one', ['/boq']),
];

describe('hex layout', () => {
  it('spirals out with every cell next to the one before it', () => {
    for (const n of [1, 6, 7, 17, 18, 25]) {
      const cells = spiralCells(n);
      expect(cells).toHaveLength(n);
      expect(hexDistance(cells[0]!, { q: 0, r: 0 })).toBe(1);
      for (let i = 1; i < n; i++) expect(hexDistance(cells[i]!, cells[i - 1]!)).toBe(1);
      expect(new Set(cells.map((c) => `${c.q},${c.r}`)).size).toBe(n);
    }
  });

  it('places cells inside the comb without overlap', () => {
    const l = hiveLayout(17);
    expect(l.cells).toHaveLength(17);
    for (const b of [l.centre, ...l.cells]) {
      expect(b.left).toBeGreaterThanOrEqual(-1e-9);
      expect(b.top).toBeGreaterThanOrEqual(-1e-9);
      expect(b.left + b.width).toBeLessThanOrEqual(100 + 1e-9);
      expect(b.top + b.height).toBeLessThanOrEqual(100 + 1e-9);
    }
    const all = [l.centre, ...l.cells];
    for (let i = 0; i < all.length; i++)
      for (let j = i + 1; j < all.length; j++)
        expect(Math.hypot(all[i]!.cx - all[j]!.cx, all[i]!.cy - all[j]!.cy)).toBeGreaterThan(1.7);
    // Two full rings around the centre: 5 columns of 2 units at a 1.5 pitch.
    expect(l.width).toBeCloseTo(8);
  });
});

describe('learning paths', () => {
  it('groups by project and orders by the lifecycle', () => {
    const [alpha] = learningPaths(SAMPLE);
    expect(alpha!.id).toBe('alpha');
    expect(alpha!.country).toBe('GB');
    expect(alpha!.courses.map((c) => c.id.split('-')[1])).toEqual(['takeoff', 'estimate', 'tender', 'handover']);
    expect(learningPaths(SAMPLE)).toHaveLength(1);
  });

  it('builds paths from the shipped catalogue', () => {
    const paths = learningPaths(ITEMS);
    expect(paths.length).toBeGreaterThan(0);
    expect(defaultPath(paths, null)).toBe(paths[0]);
  });

  it('marks done, then one next, then ahead', () => {
    const [alpha] = learningPaths(SAMPLE);
    const done = { 'course:alpha-takeoff': true } as const;
    expect(courseStatuses(alpha!.courses, done)).toEqual(['done', 'next', 'ahead', 'ahead']);
    expect(pathPercent(alpha!.courses, done)).toBe(25);
  });
});

describe('CourseHive', () => {
  beforeEach(() => localStorage.clear());
  const paths = learningPaths(SAMPLE);

  it('renders status, numbers and progress', () => {
    localStorage.setItem(DONE_KEY, JSON.stringify({ 'course:alpha-takeoff': true }));
    render(<CourseHive paths={paths} />);
    expect(screen.getByTestId('course-hive-cell-1').dataset.status).toBe('done');
    expect(screen.getByTestId('course-hive-cell-2').dataset.status).toBe('next');
    expect(screen.getByTestId('course-hive-cell-2').getAttribute('aria-current')).toBe('step');
    expect(screen.getByTestId('course-hive-cell-3').dataset.status).toBe('ahead');
    expect(screen.getByTestId('course-hive-percent').textContent).toBe('25%');
    expect(screen.getByTestId('course-hive-detail-title').textContent).toBe('alpha-estimate');
  });

  it('moves along the path with the keyboard', () => {
    render(<CourseHive paths={paths} />);
    const first = screen.getByTestId('course-hive-cell-1');
    expect(first.tabIndex).toBe(0);
    first.focus();
    fireEvent.keyDown(first, { key: 'ArrowRight' });
    const second = screen.getByTestId('course-hive-cell-2');
    expect(document.activeElement).toBe(second);
    expect(second.tabIndex).toBe(0);
    expect(first.tabIndex).toBe(-1);
    fireEvent.keyDown(second, { key: 'End' });
    expect(document.activeElement).toBe(screen.getByTestId('course-hive-cell-4'));
    expect(screen.getByTestId('course-hive-detail-title').textContent).toBe('alpha-handover');
  });

  it('marks a course done and persists it', () => {
    render(<CourseHive paths={paths} />);
    fireEvent.click(screen.getByTestId('course-hive-toggle'));
    expect(screen.getByTestId('course-hive-cell-1').dataset.status).toBe('done');
    expect(JSON.parse(localStorage.getItem(DONE_KEY)!)).toEqual({ 'course:alpha-takeoff': true });
  });

  it('has a vertical chain for phones with the same order', () => {
    render(<CourseHive paths={paths} />);
    const chain = screen.getByTestId('course-hive-chain');
    expect(chain.className).toContain('sm:hidden');
    expect(screen.getByTestId('course-hive-comb').className).toMatch(/\bhidden\b.*\bsm:block\b/);
    expect(screen.getByTestId('course-hive-chain-1').getAttribute('aria-label')).toContain('1. alpha-takeoff');
    expect(chain.querySelectorAll('li')).toHaveLength(4);
  });
});
