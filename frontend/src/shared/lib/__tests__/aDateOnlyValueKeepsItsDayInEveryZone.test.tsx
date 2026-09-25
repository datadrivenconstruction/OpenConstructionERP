// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A date-only value ("2026-01-26") prints as 26 January in every time zone.
 *
 * `new Date("2026-01-26")` is midnight UTC, and formatting it in the browser's
 * own zone prints 25 January anywhere west of UTC. The tendering list did
 * exactly that for a package deadline the API held as 2026-01-26, while the
 * award report printed the 26th: two views of one package, a day apart, for a
 * reader in Toronto.
 *
 * The convention the shared layer uses is to pin a date-only value to UTC when
 * formatting, so its calendar day is printed as written. A true timestamp keeps
 * local rendering: 23:30 UTC is already the next morning in Tokyo.
 *
 * The suite runs in UTC (see `src/test/setup.ts`), where this bug cannot show,
 * so each case moves the process to a real zone and first proves the move took
 * effect. A green result without that sentinel could simply mean UTC.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { fmtDate, formatDateValue } from '../formatters';
import { dateOnlyFormatOptions, isDateOnlyPast } from '../dates';
import { DateDisplay } from '../../ui/DateDisplay';

const ZONES: Array<{ zone: string; januaryOffsetMinutes: number }> = [
  { zone: 'America/Toronto', januaryOffsetMinutes: 300 },
  { zone: 'Europe/Berlin', januaryOffsetMinutes: -60 },
  { zone: 'Asia/Tokyo', januaryOffsetMinutes: -540 },
];

function moveTo(zone: string, januaryOffsetMinutes: number): void {
  process.env.TZ = zone;
  // Sentinel: without this the whole file could pass in UTC.
  expect(new Date('2026-01-26T00:00:00Z').getTimezoneOffset()).toBe(januaryOffsetMinutes);
}

afterEach(() => {
  process.env.TZ = 'UTC';
});

const DAY_OPTIONS: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'numeric', year: 'numeric' };

/** The day of month the formatted string names, read with the same options in UTC. */
function dayOf(formatted: string): string {
  // en-US numeric: M/D/YYYY
  return formatted.split('/')[1] ?? '';
}

describe.each(ZONES)('a date-only value in $zone', ({ zone, januaryOffsetMinutes }) => {
  it('is printed as the day it names by the shared value formatter', () => {
    moveTo(zone, januaryOffsetMinutes);
    expect(dayOf(formatDateValue('2026-01-26', DAY_OPTIONS, 'en-US'))).toBe('26');
  });

  it('is printed as the day it names in the medium style the tendering list uses', () => {
    moveTo(zone, januaryOffsetMinutes);
    expect(formatDateValue('2026-01-26', { dateStyle: 'medium' }, 'en-US')).toBe('Jan 26, 2026');
  });

  it('is printed as the day it names by fmtDate and DateDisplay', () => {
    moveTo(zone, januaryOffsetMinutes);
    expect(fmtDate('2026-01-26', DAY_OPTIONS)).toMatch(/26/);
    const { container } = render(<DateDisplay value="2026-01-26" format="numeric" />);
    expect(container.textContent).toMatch(/26/);
  });

  it('is not overdue on its own day', () => {
    moveTo(zone, januaryOffsetMinutes);
    // Late evening of the 26th in this zone.
    const lateOnTheDay = new Date('2026-01-26T12:00:00Z');
    expect(isDateOnlyPast('2026-01-26', lateOnTheDay)).toBe(false);
    expect(isDateOnlyPast('2026-01-25', lateOnTheDay)).toBe(true);
  });

  it('a true timestamp keeps its local rendering', () => {
    moveTo(zone, januaryOffsetMinutes);
    const instant = '2026-01-25T23:30:00Z';
    const expected = new Date(instant).toLocaleDateString('en-US', DAY_OPTIONS);
    expect(formatDateValue(instant, DAY_OPTIONS, 'en-US')).toBe(expected);
    // Tokyo is already on the 26th, Toronto still on the 25th.
    expect(dayOf(expected)).toBe(zone === 'America/Toronto' ? '25' : '26');
  });
});

describe('the defect this guards', () => {
  it('formatting new Date("2026-01-26") in Toronto prints the 25th', () => {
    // What the tendering list's own formatter did. Kept as a characterisation
    // so the zone switch above is shown to reproduce the reported day.
    moveTo('America/Toronto', 300);
    expect(new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' }).format(new Date('2026-01-26'))).toBe(
      'Jan 25, 2026',
    );
  });
});

describe('dateOnlyFormatOptions', () => {
  it('pins only a date-only value to UTC', () => {
    expect(dateOnlyFormatOptions('2026-01-26', DAY_OPTIONS).timeZone).toBe('UTC');
    expect(dateOnlyFormatOptions('2026-01-26T10:00:00Z', DAY_OPTIONS).timeZone).toBeUndefined();
  });

  it('never overrides a zone the caller chose', () => {
    expect(dateOnlyFormatOptions('2026-01-26', { timeZone: 'Asia/Tokyo' }).timeZone).toBe('Asia/Tokyo');
  });
});
