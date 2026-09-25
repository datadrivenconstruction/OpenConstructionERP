// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tests for the Gantt header rendering.
 *
 * Scope note: jsdom does not paint, so nothing here can prove a clipped label
 * actually stops at the clip. That was verified separately in Chromium by
 * rasterising the two labels and reading the rightmost inked pixel. What these
 * tests defend is the wiring, which is what a later edit is likely to drop: the
 * clip has to be attached to every top-row label, sized to that label's own
 * cell, and scoped to the chart instance.
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { GanttChart } from './GanttChart';
import type { GanttActivity } from './ganttUtils';
import { COLUMN_WIDTH } from './ganttUtils';

// Opens mid-January, which is what gives the leading month a cell narrower than
// its own label. A range starting on the 1st does not reproduce the bug.
const ACTIVITIES: GanttActivity[] = [
  { id: 'a', name: 'Groundworks', start: '2026-01-25', end: '2026-02-20', progress: 40 },
  { id: 'b', name: 'Frame', start: '2026-02-21', end: '2026-03-28', progress: 0 },
];

function renderChart() {
  return render(
    <GanttChart activities={ACTIVITIES} startDate="2026-01-25" endDate="2026-03-31" />,
  );
}

/** The top row is the first header row: the month labels. */
function topRowLabels(container: HTMLElement): SVGTextElement[] {
  const texts = [...container.querySelectorAll<SVGTextElement>('.gantt-header text')];
  // Top row sits in the upper half of the 48px header, bottom row below it.
  return texts.filter((el) => Number(el.getAttribute('y')) < 24);
}

describe('GanttChart header', () => {
  it('clips every top-row month label', () => {
    const { container } = renderChart();
    const labels = topRowLabels(container);

    expect(labels.length).toBeGreaterThan(1);
    for (const label of labels) {
      expect(
        label.getAttribute('clip-path'),
        `"${label.textContent}" is unclipped and can paint over its neighbour`,
      ).toMatch(/^url\(#.+\)$/);
    }
  });

  it('sizes each clip to its own cell, not to a shared width', () => {
    const { container } = renderChart();
    const labels = topRowLabels(container);

    const widths = labels.map((label) => {
      const ref = label.getAttribute('clip-path');
      expect(ref, `"${label.textContent}" has no clip-path to size`).not.toBeNull();
      const id = ref!.slice(5, -1);
      const rect = container.querySelector(`clipPath[id="${CSS.escape(id)}"] rect`);
      expect(rect, `clip-path points at #${id}, which is not defined`).not.toBeNull();
      return Number(rect!.getAttribute('width'));
    });

    // The partial leading month must get a visibly smaller clip than the whole
    // months after it. One shared width would defeat the fix while still
    // satisfying the previous test.
    //
    // Compare against the widest of the rest rather than looping over them. The
    // trailing month can be partial too, so a loop has to skip it, and skipping
    // it leaves nothing to assert on a two-cell range: the body never runs and
    // the test passes without checking anything.
    const [leading, ...rest] = widths;
    expect(leading!).toBeGreaterThan(0);
    expect(rest.length).toBeGreaterThan(0);
    expect(Math.max(...rest)).toBeGreaterThan(leading! * 2);
  });

  it('scopes clip ids per chart so two charts on a page do not share them', () => {
    // Both charts render the same months, so a hardcoded id would collide and
    // one chart would clip its labels against the other's column positions.
    const { container } = render(
      <div>
        <GanttChart activities={ACTIVITIES} startDate="2026-01-25" endDate="2026-03-31" />
        <GanttChart activities={ACTIVITIES} startDate="2026-01-25" endDate="2026-03-31" />
      </div>,
    );

    const ids = [...container.querySelectorAll('clipPath')].map((n) => n.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size, 'two charts emitted colliding clipPath ids').toBe(ids.length);
  });
});

/**
 * The START and END columns of the left table.
 *
 * A programme that runs past New Year prints two rows that read the same six
 * characters and mean dates a year apart, and nothing on the screen resolves
 * which is which. The year has to appear then - and only then, because on a
 * programme inside one year it is the same digits on every row.
 *
 * The dates below are chosen so no day number can be mistaken for a year: the
 * single-year fixture sits in 2026 and never uses the 26th, and the multi-year
 * one never uses the 27th or 28th.
 */
const SINGLE_YEAR: GanttActivity[] = [
  { id: 'a', name: 'Groundworks', start: '2026-03-05', end: '2026-07-18', progress: 100 },
  { id: 'b', name: 'Frame', start: '2026-07-19', end: '2026-11-12', progress: 0 },
];

// Both activities start on the 5th of March. Without a year the two START cells
// are character-for-character identical while standing two years apart, which is
// the defect stated as data.
const MULTI_YEAR: GanttActivity[] = [
  { id: 'a', name: 'Enabling works', start: '2026-03-05', end: '2027-01-11', progress: 100 },
  { id: 'b', name: 'Fit-out', start: '2028-03-05', end: '2028-09-14', progress: 0 },
];

function cellText(container: HTMLElement, testId: string): string {
  const cell = container.querySelector(`[data-testid="${testId}"]`);
  expect(cell, `no ${testId} cell rendered`).not.toBeNull();
  return cell!.textContent ?? '';
}

describe('GanttChart date columns', () => {
  it('leaves the year off a programme that stays inside one calendar year', () => {
    const { container } = render(<GanttChart activities={SINGLE_YEAR} />);

    for (const id of ['gantt-start-a', 'gantt-end-a', 'gantt-start-b', 'gantt-end-b']) {
      const text = cellText(container, id);
      // Non-empty first: an assertion that only forbids characters passes on a
      // cell that renders nothing at all.
      expect(text.trim().length, `${id} is empty`).toBeGreaterThan(0);
      expect(text, `${id} prints a year nobody needs on a single-year programme`).not.toMatch(
        /26/,
      );
    }
  });

  it('prints the year once the programme crosses into another year', () => {
    const { container } = render(<GanttChart activities={MULTI_YEAR} />);

    const startA = cellText(container, 'gantt-start-a');
    const startB = cellText(container, 'gantt-start-b');

    expect(startA).toMatch(/26/);
    expect(startB).toMatch(/28/);
    expect(cellText(container, 'gantt-end-a')).toMatch(/27/);
    // The point of the whole thing: two same-day-and-month rows two years apart
    // have to read differently.
    expect(startA, 'two rows two years apart print the same date').not.toBe(startB);
  });

  it('writes that year in full, not as two digits', () => {
    // "05 Mar 26" puts a two-digit year next to a two-digit day on either side
    // of the month, and the reader has to work out which number is which. The
    // expected years are read off the fixture rather than typed, so this keeps
    // meaning the same thing when the dates move.
    const { container } = render(<GanttChart activities={MULTI_YEAR} />);

    const cases: [string, string][] = [
      ['gantt-start-a', MULTI_YEAR[0]!.start],
      ['gantt-end-a', MULTI_YEAR[0]!.end],
      ['gantt-start-b', MULTI_YEAR[1]!.start],
      ['gantt-end-b', MULTI_YEAR[1]!.end],
    ];

    for (const [testId, iso] of cases) {
      const fullYear = String(new Date(`${iso}T00:00:00Z`).getUTCFullYear());
      expect(cellText(container, testId), `${testId} abbreviates the year`).toContain(fullYear);
    }
  });

  it('reads the span off the activities, not off the padded timeline range', () => {
    // getDateRange pads a month past the last activity when no explicit range is
    // given, so a programme ending in December spills into January. Deriving the
    // flag from that padding would print a year on a single-year programme.
    const { container } = render(
      <GanttChart
        activities={[
          { id: 'a', name: 'Winter works', start: '2026-11-02', end: '2026-12-18', progress: 0 },
        ]}
      />,
    );

    expect(cellText(container, 'gantt-end-a')).not.toMatch(/26/);
  });

  it('carries the same dates into the bar label a screen reader announces', () => {
    const { container } = render(<GanttChart activities={MULTI_YEAR} />);

    const labels = [...container.querySelectorAll('g[role="img"]')].map(
      (g) => g.getAttribute('aria-label') ?? '',
    );
    const fitOut = labels.find((l) => l.startsWith('Fit-out'));
    expect(fitOut, 'no bar label for the second activity').toBeDefined();
    expect(fitOut!).toMatch(/28/);
  });
});

describe('GanttChart bar length', () => {
  // End dates are inclusive, as the schedule API stores them: an activity from
  // the 4th to the 4th works one day and one from the 4th to the 8th works five.
  function barWidth(container: HTMLElement, name: string): number {
    const group = [...container.querySelectorAll('g[role="img"]')].find((g) =>
      (g.getAttribute('aria-label') ?? '').startsWith(`${name}:`),
    );
    expect(group, `no bar for ${name}`).toBeTruthy();
    return Number(group!.querySelector('rect')!.getAttribute('width'));
  }

  it('draws a one-day activity one day wide and a five-day one five days wide', () => {
    const { container } = render(
      <GanttChart
        viewMode="day"
        activities={[
          { id: 'one', name: 'One day', start: '2026-05-04', end: '2026-05-04', progress: 0 },
          { id: 'five', name: 'Five days', start: '2026-05-04', end: '2026-05-08', progress: 0 },
        ]}
        startDate="2026-05-01"
        endDate="2026-05-20"
      />,
    );
    expect(barWidth(container, 'One day')).toBe(COLUMN_WIDTH.day);
    expect(barWidth(container, 'Five days')).toBe(5 * COLUMN_WIDTH.day);
  });
});
