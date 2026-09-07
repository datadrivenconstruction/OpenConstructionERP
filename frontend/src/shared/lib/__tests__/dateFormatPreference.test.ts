// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// `oe_preferences.dateFormat` was stored and offered in Settings but read by
// no rendering surface, so picking a format changed nothing. Wiring it up has
// one hard constraint: an account that never picked a format must render
// exactly what it rendered before, byte for byte. That is not a formality -
// there was no "unset" state to preserve, because both the account column and
// the store defaulted to the concrete order `DD.MM.YYYY`. `'auto'` is the new
// unset state, and the first block below is the proof that it is inert.
//
// The equivalence is asserted against the ORIGINAL expression, not against a
// reimplementation of it, so a future change to either side has to keep them
// equal rather than keep two copies of the same mistake in step.

import { describe, it, expect, beforeEach, afterAll, vi } from 'vitest';
import i18next from 'i18next';
import { formatDateWithPreference, fmtDate, getIntlLocale } from '../formatters';
import { LOCALE_MAP } from '../intlLocale';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { usePreferencesStore, type DateFormat } from '@/stores/usePreferencesStore';

vi.mock('@/shared/lib/api', () => ({ apiGet: vi.fn() }));

/** A spread wide enough to catch order, separator, script and calendar drift. */
const LOCALES = ['de-DE', 'en-US', 'ru-RU', 'ja-JP', 'ar-SA'] as const;

/** The option sets the real date surfaces use, mirrored from DateDisplay. */
const DATE_OPTIONS: Intl.DateTimeFormatOptions = { day: '2-digit', month: 'short', year: 'numeric' };
const NUMERIC_DATE_OPTIONS: Intl.DateTimeFormatOptions = { day: '2-digit', month: '2-digit', year: 'numeric' };
const DATETIME_OPTIONS: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'UTC',
};
const TIME_OPTIONS: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' };

const TIMESTAMP = new Date('2026-03-14T14:30:00Z');
/** Date-only values are pinned to UTC by both seams; mirror that here. */
const DATE_ONLY = new Date('2026-03-14');

const originalLanguage = i18next.language;
function setLanguage(lang: string) {
  (i18next as unknown as { language: string }).language = lang;
}

beforeEach(() => {
  localStorage.clear();
  usePreferencesStore.getState().resetPreferences();
  setLanguage(originalLanguage);
});

afterAll(() => {
  setLanguage(originalLanguage);
});

describe("the unset default ('auto') renders exactly what the language rendered before", () => {
  for (const locale of LOCALES) {
    it(`is byte-identical for ${locale}`, () => {
      const cases: [string, Date, Intl.DateTimeFormatOptions][] = [
        ['date, timestamp', TIMESTAMP, DATE_OPTIONS],
        ['date, date-only pinned to UTC', DATE_ONLY, { ...DATE_OPTIONS, timeZone: 'UTC' }],
        ['numeric, timestamp', TIMESTAMP, NUMERIC_DATE_OPTIONS],
        ['numeric, date-only pinned to UTC', DATE_ONLY, { ...NUMERIC_DATE_OPTIONS, timeZone: 'UTC' }],
        ['datetime', TIMESTAMP, DATETIME_OPTIONS],
        ['time', TIMESTAMP, TIME_OPTIONS],
      ];
      for (const [label, date, options] of cases) {
        // The right-hand side is the expression the code ran before the
        // preference existed.
        expect(formatDateWithPreference(date, locale, options, 'auto'), label).toBe(
          new Intl.DateTimeFormat(locale, options).format(date),
        );
      }
    });
  }

  for (const lang of ['de', 'en', 'ru', 'ja', 'ar']) {
    it(`keeps fmtDate byte-identical with the UI language set to ${lang}`, () => {
      setLanguage(lang);
      // Timestamp: no UTC pinning, caller options passed straight through.
      expect(fmtDate('2026-03-14T14:30:00Z')).toBe(
        new Date('2026-03-14T14:30:00Z').toLocaleDateString(getIntlLocale(), {
          day: '2-digit',
          month: 'short',
          year: 'numeric',
        }),
      );
      // Date-only: the seam pins it to UTC so the calendar day cannot slip.
      expect(fmtDate('2026-03-14')).toBe(
        new Date('2026-03-14').toLocaleDateString(getIntlLocale(), {
          day: '2-digit',
          month: 'short',
          year: 'numeric',
          timeZone: 'UTC',
        }),
      );
      // Caller-supplied options are honoured unchanged too.
      expect(fmtDate('2026-03-14', NUMERIC_DATE_OPTIONS)).toBe(
        new Date('2026-03-14').toLocaleDateString(getIntlLocale(), {
          ...NUMERIC_DATE_OPTIONS,
          timeZone: 'UTC',
        }),
      );
    });
  }

  it("starts on 'auto', so a browser that never touched Settings is on the inert path", () => {
    expect(usePreferencesStore.getState().dateFormat).toBe('auto');
  });
});

describe('each supported preference value renders its own order', () => {
  const EXPECTED: Record<Exclude<DateFormat, 'auto'>, string> = {
    'DD.MM.YYYY': '14.03.2026',
    'MM/DD/YYYY': '03/14/2026',
    'YYYY-MM-DD': '2026-03-14',
  };

  for (const [pref, expected] of Object.entries(EXPECTED) as [Exclude<DateFormat, 'auto'>, string][]) {
    it(`renders ${pref} as ${expected}`, () => {
      expect(formatDateWithPreference(TIMESTAMP, 'en-US', NUMERIC_DATE_OPTIONS, pref)).toBe(expected);
    });

    it(`forces the long month numeric under ${pref}`, () => {
      // The vocabulary has no long-month token, so an explicit order implies
      // an all-numeric date even where the language would have written "Mar".
      expect(formatDateWithPreference(TIMESTAMP, 'en-US', DATE_OPTIONS, pref)).toBe(expected);
    });

    it(`keeps the time intact alongside the date under ${pref}`, () => {
      const withPref = formatDateWithPreference(TIMESTAMP, 'en-US', DATETIME_OPTIONS, pref);
      // Only the date fields move. Everything the language put after them -
      // the date/time connector, the hour, the day period - is still there.
      // The separator before PM is matched as \s rather than a literal space
      // because ICU emits a narrow no-break space through formatToParts and an
      // ordinary space through format(); see formatDateWithPreference.
      expect(withPref.startsWith(expected), withPref).toBe(true);
      expect(withPref.slice(expected.length)).toMatch(/^,\s02:30\sPM$/u);
    });
  }

  it('reorders without switching the script or the calendar', () => {
    // Arabic renders Arabic-Indic digits on the Islamic calendar. The
    // preference changes the ORDER, so every field value the language
    // produced must still be present afterwards.
    const parts = new Intl.DateTimeFormat('ar-SA', NUMERIC_DATE_OPTIONS).formatToParts(TIMESTAMP);
    const field = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
    const rendered = formatDateWithPreference(TIMESTAMP, 'ar-SA', NUMERIC_DATE_OPTIONS, 'YYYY-MM-DD');
    expect(rendered).toBe(`${field('year')}-${field('month')}-${field('day')}`);
  });

  it('leaves a time-only cell alone, having no date fields to reorder', () => {
    for (const pref of ['DD.MM.YYYY', 'MM/DD/YYYY', 'YYYY-MM-DD'] as const) {
      expect(formatDateWithPreference(TIMESTAMP, 'en-US', TIME_OPTIONS, pref)).toBe(
        new Intl.DateTimeFormat('en-US', TIME_OPTIONS).format(TIMESTAMP),
      );
    }
  });

  it('leaves a partial date (month and year only) to the language', () => {
    const monthYear: Intl.DateTimeFormatOptions = { month: 'long', year: 'numeric' };
    expect(formatDateWithPreference(TIMESTAMP, 'en-US', monthYear, 'YYYY-MM-DD')).toBe(
      new Intl.DateTimeFormat('en-US', monthYear).format(TIMESTAMP),
    );
  });

  it('reaches fmtDate, which reads the preference from the store', () => {
    usePreferencesStore.getState().setPreference('dateFormat', 'YYYY-MM-DD');
    setLanguage('de');
    expect(fmtDate('2026-03-14')).toBe('2026-03-14');
  });
});

// ---------------------------------------------------------------------------
// The one language 'auto' does not follow.
//
// Kyrgyz orders a date year, day, month. Spelled out that is idiomatic
// (`2026-ж., 3-ноябрь`); in digits it prints `2026-03-11` for 3 November and
// every reader takes it for ISO, so the day and the month swap silently. These
// assertions have to fail in BOTH directions: red if the exception is reverted,
// and red if it spreads to a words-based format or to any other language.
// ---------------------------------------------------------------------------

describe('Kyrgyz is the single all-numeric exception to the auto path', () => {
  /** 3 November 2026: day and month are both <= 12, so the order is ambiguous. */
  const AMBIGUOUS = new Date('2026-11-03T12:00:00Z');
  const NUMERIC_UTC: Intl.DateTimeFormatOptions = { ...NUMERIC_DATE_OPTIONS, timeZone: 'UTC' };
  const WORDS_UTC: Intl.DateTimeFormatOptions = { ...DATE_OPTIONS, timeZone: 'UTC' };

  it('renders an all-numeric Kyrgyz date day-first instead of year-day-month', () => {
    expect(formatDateWithPreference(AMBIGUOUS, 'ky', NUMERIC_UTC, 'auto')).toBe('03.11.2026');
  });

  it('is a correction, not a restatement: the language on its own gets this wrong', () => {
    // Guards the premise. If a future ICU ships a day-first Kyrgyz short
    // pattern, this fails and the exception above should be deleted rather
    // than kept as a no-op that nobody can tell is dead.
    expect(new Intl.DateTimeFormat('ky', NUMERIC_UTC).format(AMBIGUOUS)).toBe('2026-03-11');
  });

  it('leaves the words-based Kyrgyz date exactly as the language writes it', () => {
    // `2026-ж., 3-ноябрь` is correct and unambiguous. The exception must not
    // reach it, which is the whole reason it keys on a numeric month.
    expect(formatDateWithPreference(AMBIGUOUS, 'ky', WORDS_UTC, 'auto')).toBe(
      new Intl.DateTimeFormat('ky', WORDS_UTC).format(AMBIGUOUS),
    );
  });

  it('does not leak into any other language on the numeric path', () => {
    for (const locale of [...LOCALES, 'kk', 'uz', 'ru-KG', 'en-GB', 'th']) {
      expect(formatDateWithPreference(AMBIGUOUS, locale, NUMERIC_UTC, 'auto'), locale).toBe(
        new Intl.DateTimeFormat(locale, NUMERIC_UTC).format(AMBIGUOUS),
      );
    }
  });

  it('still lets an explicit preference win, so the escape hatch is intact', () => {
    expect(formatDateWithPreference(AMBIGUOUS, 'ky', NUMERIC_UTC, 'YYYY-MM-DD')).toBe('2026-11-03');
  });

  it('is an exception of exactly one across every offered language', () => {
    // The population, printed beside the verdict. A gate whose denominator is
    // not the whole set can be satisfied by narrowing the set instead.
    const unreadable = SUPPORTED_LANGUAGES.filter(({ code }) => {
      const tag = LOCALE_MAP[code] ?? code;
      const order = new Intl.DateTimeFormat(tag, NUMERIC_UTC)
        .formatToParts(AMBIGUOUS)
        .filter((p) => p.type !== 'literal')
        .map((p) => p.type.charAt(0))
        .join('');
      return !['dmy', 'mdy', 'ymd'].includes(order);
    }).map((entry) => entry.code);
    expect(unreadable).toEqual(['ky']);
  });
});
