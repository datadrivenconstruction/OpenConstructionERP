// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The date-format preference reaches the screen through two seams: the
// `DateDisplay` component and the `fmtDate` helper. This renders one surface
// of each shape a reader recognises - a table cell, a detail header, a form
// field - and drives the preference through all three at once, so a refactor
// that unhooks any single surface fails here rather than shipping a setting
// that works everywhere except the page someone happens to be looking at.
//
// The second thing under test is reactivity. `DateDisplay` subscribes to the
// store instead of reading it once, because a preference that only takes
// effect after navigating away is indistinguishable from a broken one.

import { describe, it, expect, beforeEach, afterAll } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import i18next from 'i18next';
import { DateDisplay } from '../DateDisplay';
import { fmtDate } from '../../lib/formatters';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

const DUE = '2026-03-14';

const originalLanguage = i18next.language;
function setLanguage(lang: string) {
  (i18next as unknown as { language: string }).language = lang;
}
afterAll(() => setLanguage(originalLanguage));

/** A read-only form field showing a formatted date, the `fmtDate` seam. */
function DueDateField() {
  // Subscribing is what makes the field repaint when Settings changes; the
  // value itself comes from the shared helper.
  usePreferencesStore((s) => s.dateFormat);
  return <input readOnly aria-label="due" value={fmtDate(DUE)} />;
}

function Surfaces() {
  return (
    <>
      <h2>
        <DateDisplay value={DUE} />
      </h2>
      <table>
        <tbody>
          <tr>
            <td>
              <DateDisplay value={DUE} format="numeric" />
            </td>
          </tr>
        </tbody>
      </table>
      <DueDateField />
    </>
  );
}

function readSurfaces() {
  const header = screen.getByRole('heading').textContent ?? '';
  const cell = screen.getByRole('cell').textContent ?? '';
  const field = (screen.getByLabelText('due') as HTMLInputElement).value;
  return { header, cell, field };
}

// 102 files render dates through this component, so the guarantee that an
// untouched account sees no change has to hold for the component itself and
// not only for the formatter underneath it.
describe('DateDisplay renders exactly what it rendered before while the preference is unset', () => {
  const LANGUAGES: [string, string][] = [
    ['de', 'de-DE'],
    // Neither British nor American: plain `English` claims no region, and
    // `English (UK)` and `English (US)` are the separate entries beside it.
    // `LOCALE_MAP` follows, resolving `en` to itself.
    ['en', 'en'],
    ['ru', 'ru-RU'],
    ['ja', 'ja-JP'],
    ['ar', 'ar-SA'],
  ];

  // The option sets the component used before the preference was wired in.
  const DATE_OPTIONS: Intl.DateTimeFormatOptions = { day: '2-digit', month: 'short', year: 'numeric' };
  const NUMERIC_DATE_OPTIONS: Intl.DateTimeFormatOptions = { day: '2-digit', month: '2-digit', year: 'numeric' };
  const DATETIME_OPTIONS: Intl.DateTimeFormatOptions = {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  };
  const TIME_OPTIONS: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' };

  beforeEach(() => {
    localStorage.clear();
    usePreferencesStore.getState().resetPreferences();
  });

  for (const [lang, locale] of LANGUAGES) {
    it(`matches the language-derived rendering in ${lang}`, () => {
      setLanguage(lang);
      const stamp = '2026-03-14T14:30:00Z';
      const cases: ['date' | 'numeric' | 'datetime' | 'time', string, Intl.DateTimeFormatOptions][] = [
        // Date-only values were pinned to UTC before and must still be.
        ['date', DUE, { ...DATE_OPTIONS, timeZone: 'UTC' }],
        ['numeric', DUE, { ...NUMERIC_DATE_OPTIONS, timeZone: 'UTC' }],
        ['date', stamp, DATE_OPTIONS],
        ['numeric', stamp, NUMERIC_DATE_OPTIONS],
        ['datetime', stamp, DATETIME_OPTIONS],
        ['time', stamp, TIME_OPTIONS],
      ];
      for (const [format, value, options] of cases) {
        const { unmount } = render(
          <h2>
            <DateDisplay value={value} format={format} />
          </h2>,
        );
        expect(screen.getByRole('heading').textContent, `${format} / ${value}`).toBe(
          new Intl.DateTimeFormat(locale, options).format(new Date(value)),
        );
        unmount();
      }
    });
  }
});

describe('the date-format preference reaches every date surface', () => {
  beforeEach(() => {
    localStorage.clear();
    usePreferencesStore.getState().resetPreferences();
    setLanguage(originalLanguage);
  });

  it('leaves all three surfaces on the language rendering while it is automatic', () => {
    render(<Surfaces />);
    const { header, cell, field } = readSurfaces();
    // Unqualified `en` in the test environment, the language having no
    // explicit setting here: a written month in the long form, a month-first
    // numeric date in the dense one, because CLDR has no region-free English
    // and `en` inherits the American reading. The exact strings are proved
    // equal to the pre-change rendering in dateFormatPreference.test.ts; here
    // what matters is that nothing has been forced into one shared order yet.
    expect(header).not.toBe(DUE);
    expect(cell).not.toBe(DUE);
    expect(field).not.toBe(DUE);
    expect(cell).toBe('03/14/2026');
  });

  it('moves all three surfaces together when the preference changes, without a remount', () => {
    render(<Surfaces />);
    const before = readSurfaces();

    act(() => {
      usePreferencesStore.getState().setPreference('dateFormat', 'YYYY-MM-DD');
    });

    const after = readSurfaces();
    expect(after.header).toBe('2026-03-14');
    expect(after.cell).toBe('2026-03-14');
    expect(after.field).toBe('2026-03-14');
    expect(after.header).not.toBe(before.header);
    expect(after.cell).not.toBe(before.cell);
    expect(after.field).not.toBe(before.field);
  });

  it('follows a second preference change, so the seam is not a one-shot read', () => {
    render(<Surfaces />);
    act(() => {
      usePreferencesStore.getState().setPreference('dateFormat', 'YYYY-MM-DD');
    });
    act(() => {
      usePreferencesStore.getState().setPreference('dateFormat', 'DD.MM.YYYY');
    });
    const { header, cell, field } = readSurfaces();
    expect(header).toBe('14.03.2026');
    expect(cell).toBe('14.03.2026');
    expect(field).toBe('14.03.2026');
  });

  it('keeps rendering a missing date as an em-dash under an explicit preference', () => {
    // The null branch returns before any formatting happens; both hooks have
    // to have run by then or React throws on exactly this branch.
    act(() => {
      usePreferencesStore.getState().setPreference('dateFormat', 'MM/DD/YYYY');
    });
    render(
      <h2>
        <DateDisplay value={null} />
      </h2>,
    );
    expect(screen.getByRole('heading').textContent).toBe('—');
  });
});
