// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for <MoneyDisplay> — strict-currency formatter (Wave 2).
//
// Covers:
//   * Em-dash placeholder when amount is null / undefined / NaN.
//   * Em-dash placeholder when currency is missing or invalid
//     (Strict-currency policy — no silent EUR fallback).
//   * String-typed amount is parsed correctly (Decimal-as-string).
//   * amount=0 and negative amounts format correctly.
//   * Locale-aware formatting:
//       - en-US for USD → $1,234.56
//       - de-DE for EUR → uses comma separators (intl test environment
//         supplies the canonical Intl tables for these two pairs).
//   * Dev-mode console.warn fires exactly once per instance (re-render
//     does not re-warn) for missing or invalid currency.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';

import { MoneyDisplay } from './MoneyDisplay';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

// Overrides the global `react-i18next` mock in src/test/setup.ts for this file
// only. That mock returns the `defaultValue`, which is character-identical to
// the hardcoded literal this component used to carry — so an assertion on the
// English words passes whether or not the string ever reaches i18next. Marker
// mode returns the key instead, which only a real `t()` call can produce.
const i18nMock = vi.hoisted(() => ({ marker: false }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (i18nMock.marker) return `«${key}»`;
      if (typeof opts === 'object' && opts !== null && 'defaultValue' in opts) {
        return String(opts.defaultValue);
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children?: unknown }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
  I18nextProvider: ({ children }: { children?: unknown }) => children,
}));

// Helper — set the locale on the store before render. The component
// reads numberLocale via a selector, so updates take effect on the
// next render.
function setLocale(locale: 'en-US' | 'de-DE' | 'ar-SA' | 'ja-JP') {
  usePreferencesStore.setState({ numberLocale: locale });
}

beforeEach(() => {
  // Default to en-US so most tests have a predictable comma/period
  // formatting that doesn't depend on the host's locale.
  setLocale('en-US');
  i18nMock.marker = false;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MoneyDisplay - em-dash placeholders', () => {
  it('renders em-dash when amount is null', () => {
    const { container } = render(<MoneyDisplay amount={null} currency="USD" />);
    expect(container.textContent).toBe('—');
  });

  it('renders em-dash when amount is undefined', () => {
    const { container } = render(<MoneyDisplay amount={undefined} currency="USD" />);
    expect(container.textContent).toBe('—');
  });

  it('renders em-dash when amount is NaN (non-numeric string)', () => {
    const { container } = render(<MoneyDisplay amount="not-a-number" currency="USD" />);
    expect(container.textContent).toBe('—');
  });

  it('renders em-dash when currency is null', () => {
    const { container } = render(
      <MoneyDisplay amount={100} currency={null as unknown as string} />,
    );
    expect(container.textContent).toBe('—');
  });

  it('renders em-dash when currency is undefined', () => {
    const { container } = render(<MoneyDisplay amount={100} />);
    expect(container.textContent).toBe('—');
  });

  it('renders em-dash when currency is empty string', () => {
    const { container } = render(<MoneyDisplay amount={100} currency="" />);
    expect(container.textContent).toBe('—');
  });

  it('renders em-dash when currency is non-ISO shape (3 letters required)', () => {
    const { container } = render(<MoneyDisplay amount={100} currency="us" />);
    expect(container.textContent).toBe('—');
  });

  it('attaches a "Currency not set" tooltip when the gap is surfaced', () => {
    render(<MoneyDisplay amount={100} currency="" />);
    const span = screen.getByTitle('Currency not set');
    expect(span).toBeInTheDocument();
  });

  it('attaches the same tooltip on the invalid-code branch', () => {
    // The component has two em-dash branches and each carries its own
    // tooltip. Only the missing-currency one was asserted, so a change that
    // touched one and not the other read as fully covered.
    render(<MoneyDisplay amount={100} currency="us" />);
    expect(screen.getByTitle('Currency not set')).toBeInTheDocument();
  });
});

describe('MoneyDisplay - valid currency formatting', () => {
  it.each(['always', 'never', 'exceptZero', 'auto'] as const)(
    'keeps Intl sign policy %s for decimal strings', (signDisplay) => {
      const amount = '-0.000';
      const expected = new Intl.NumberFormat('en-US', {
        style: 'currency', currency: 'USD', signDisplay,
      }).format(-0);
      const { container } = render(<MoneyDisplay amount={amount} currency="USD" signDisplay={signDisplay} />);
      expect(container.textContent).toBe(expected);
    },
  );

  it.each([true, false])('keeps compact notation with showCode=%s', (showCode) => {
    const { container } = render(<MoneyDisplay amount="1234567.89" currency="USD" compact showCode={showCode} />);
    expect(container.textContent).toBe(showCode ? '1.2M USD' : '$1.2M');
  });

  it.each([
    ['9007199254740993.01', 'USD', '9,007,199,254,740,993.01 USD'],
    ['9007199254740993', 'JPY', '9,007,199,254,740,993 JPY'],
    ['900719925474099.123', 'KWD', '900,719,925,474,099.123 KWD'],
    ['99.9900', 'USD', '99.99 USD'],
    ['9.999', 'KWD', '9.999 KWD'],
  ])('preserves decimal-string digits for %s %s', (amount, currency, expected) => {
    const { container } = render(<MoneyDisplay amount={amount} currency={currency} showCode />);
    expect(container.textContent).toBe(expected);
  });

  it('preserves the final cent when formatting a currency symbol', () => {
    const { container } = render(<MoneyDisplay amount="9007199254740993.01" currency="USD" />);
    expect(container.textContent).toBe('$9,007,199,254,740,993.01');
  });

  it('localizes an exact large decimal with the reader preference', () => {
    setLocale('de-DE');
    const { container } = render(<MoneyDisplay amount="9007199254740993.01" currency="EUR" showCode />);
    expect(container.textContent).toBe('9.007.199.254.740.993,01 EUR');
  });

  it('formats a positive integer amount with USD', () => {
    render(<MoneyDisplay amount={1234.56} currency="USD" />);
    // Intl renders "$1,234.56" — any whitespace variants from a future
    // CLDR are tolerated via regex.
    expect(screen.getByText(/\$1,234\.56/)).toBeInTheDocument();
  });

  it('formats amount=0 (does not get treated as "missing")', () => {
    render(<MoneyDisplay amount={0} currency="USD" />);
    expect(screen.getByText(/\$0\.00/)).toBeInTheDocument();
  });

  it('formats negative amounts with the minus sign', () => {
    render(<MoneyDisplay amount={-42} currency="USD" />);
    // en-US Intl renders negative as "-$42.00" (no space).
    expect(screen.getByText(/-\$42\.00/)).toBeInTheDocument();
  });

  it('accepts amount as a string (Decimal-as-string) and parses it', () => {
    render(<MoneyDisplay amount="1234.5" currency="USD" />);
    expect(screen.getByText(/\$1,234\.50/)).toBeInTheDocument();
  });

  it('uses de-DE locale separators when numberLocale = de-DE + EUR', () => {
    setLocale('de-DE');
    render(<MoneyDisplay amount={1234.56} currency="EUR" />);
    // de-DE EUR: "1.234,56 €" — match the digits + decimal comma.
    expect(screen.getByText(/1\.234,56/)).toBeInTheDocument();
  });

  it('respects ISO minor-units for JPY (0 decimals)', () => {
    render(<MoneyDisplay amount={1234} currency="JPY" />);
    // en-US: "¥1,234" with no decimal portion.
    expect(screen.getByText(/¥1,234/)).toBeInTheDocument();
    // Negative sanity: ensure no ".00" was appended.
    expect(screen.queryByText(/¥1,234\.00/)).toBeNull();
  });

  it('respects ISO minor-units for KWD (3 decimals)', () => {
    render(<MoneyDisplay amount={1.234} currency="KWD" showCode />);
    // showCode renders "<formatted> KWD"; KWD has 3 decimals.
    expect(screen.getByText(/1\.234 KWD/)).toBeInTheDocument();
  });

  it('appends the ISO code when showCode=true', () => {
    render(<MoneyDisplay amount={100} currency="USD" showCode />);
    expect(screen.getByText(/100\.00 USD/)).toBeInTheDocument();
  });

  it('colorizes positive amounts when colorize=true', () => {
    const { container } = render(
      <MoneyDisplay amount={50} currency="USD" colorize />,
    );
    expect(container.querySelector('.text-semantic-success')).not.toBeNull();
  });

  it('colorizes negative amounts with the error class when colorize=true', () => {
    const { container } = render(
      <MoneyDisplay amount={-50} currency="USD" colorize />,
    );
    expect(container.querySelector('.text-semantic-error')).not.toBeNull();
  });

  it('does NOT colorize zero (neutral)', () => {
    const { container } = render(
      <MoneyDisplay amount={0} currency="USD" colorize />,
    );
    expect(container.querySelector('.text-semantic-success')).toBeNull();
    expect(container.querySelector('.text-semantic-error')).toBeNull();
  });

  it('trims whitespace inside the currency prop', () => {
    render(<MoneyDisplay amount={100} currency="  USD  " />);
    expect(screen.getByText(/\$100\.00/)).toBeInTheDocument();
  });
});

describe('MoneyDisplay exact fallback', () => {
  function emulateNumberOnlyEngine() {
    const Native = Intl.NumberFormat;
    return vi.spyOn(Intl, 'NumberFormat').mockImplementation(function (locales, options) {
      const formatter = new Native(locales, options);
      Object.defineProperty(formatter, 'format', {
        value: (value: string | number | bigint) => new Native(locales, options).format(Number(value)),
      });
      return formatter;
    });
  }

  it('rechecks capabilities after the Intl constructor is replaced', () => {
    const oldEngine = emulateNumberOnlyEngine();
    const first = render(<MoneyDisplay amount="9007199254740993.01" currency="USD" />);
    expect(first.container.textContent).toBe('9007199254740993.01 USD');
    first.unmount();
    oldEngine.mockRestore();
    const second = render(<MoneyDisplay amount="9007199254740993.01" currency="USD" />);
    expect(second.container.textContent).toBe('$9,007,199,254,740,993.01');
  });

  it('keeps existing numeric formatting on a number-only engine', () => {
    emulateNumberOnlyEngine();
    const { container } = render(<MoneyDisplay amount={1234.5} currency="USD" />);
    expect(container.textContent).toBe('$1,234.50');
  });

  it.each([
    ['9007199254740993.0100', undefined, '9007199254740993.0100 USD'],
    ['9007199254740993.0100', 'always', '+9007199254740993.0100 USD'],
    ['-9007199254740993.0100', 'never', '9007199254740993.0100 USD'],
    ['-0.000', 'exceptZero', '0.000 USD'],
    ['-0.000', 'negative', '0.000 USD'],
    ['-0.000', 'auto', '-0.000 USD'],
    ['0.000', 'always', '+0.000 USD'],
    ['1.000', 'exceptZero', '+1.000 USD'],
    ['-1.000', 'always', '-1.000 USD'],
  ] as const)('keeps exact raw %s with sign policy %s on old engines', (amount, signDisplay, expected) => {
    emulateNumberOnlyEngine();
    const { container } = render(<MoneyDisplay amount={amount} currency="USD" signDisplay={signDisplay} compact />);
    expect(container.textContent).toBe(expected);
  });

  it('keeps exact digits when Intl throws', () => {
    vi.spyOn(Intl, 'NumberFormat').mockImplementation(function () {
      throw new RangeError('unavailable formatter');
    });
    const { container } = render(<MoneyDisplay amount="9007199254740993.0100" currency="USD" />);
    expect(container.textContent).toBe('9007199254740993.0100 USD');
  });

  it('preserves the raw amount when capability succeeds but currency formatting fails', () => {
    const Native = Intl.NumberFormat;
    vi.spyOn(Intl, 'NumberFormat').mockImplementation(function (locales, options) {
      const formatter = new Native(locales, options);
      if (options?.style === 'currency') {
        Object.defineProperty(formatter, 'format', {
          value: () => { throw new RangeError('currency formatting failed'); },
        });
      }
      return formatter;
    });
    const { container } = render(<MoneyDisplay amount="9007199254740993.0100" currency="USD" signDisplay="always" />);
    expect(container.textContent).toBe('+9007199254740993.0100 USD');
  });

  it('colors a tiny negative decimal without underflow through Number', () => {
    const { container } = render(<MoneyDisplay amount={`-0.${'0'.repeat(330)}1`} currency="USD" colorize />);
    expect(container.querySelector('.text-semantic-error')).not.toBeNull();
  });
});

/**
 * #205 — the tooltip was hardcoded English inside the money primitive, which
 * every register on the platform renders.
 *
 * The key is `projects.currency_not_set` rather than a new one. It already
 * exists in all 29 locales, and its other call site (ProjectDetailPage, the
 * project header badge) renders it as `{currency ?? t(...)}` — the slot a
 * currency *value* occupies, which is the same thing this tooltip says about
 * the em-dash it sits on. The neighbouring `costs_catalogs.currency_not_set`
 * is "Not set": right inside a labelled `<option>`, wrong as a standalone
 * tooltip with no subject.
 *
 * Asserted against a marker rather than English words: a literal and a
 * resolved `defaultValue` are the same characters, so the English assertions
 * above pass either way and gate nothing on their own.
 */
describe('MoneyDisplay tooltip is translatable (#205)', () => {
  function titleOf(currency: string): string | null {
    const { container } = render(<MoneyDisplay amount={100} currency={currency} />);
    return container.querySelector('span')?.getAttribute('title') ?? null;
  }

  it('takes the missing-currency tooltip from a key', () => {
    i18nMock.marker = true;
    expect(titleOf('')).toBe('«projects.currency_not_set»');
  });

  it('takes the invalid-currency tooltip from the same key', () => {
    i18nMock.marker = true;
    expect(titleOf('us')).toBe('«projects.currency_not_set»');
  });

  it('leaves no English fragment beside the key in either branch', () => {
    i18nMock.marker = true;
    for (const currency of ['', 'us']) {
      const title = titleOf(currency);
      expect(title).toBeTruthy();
      // Strip the marker; anything left came from a literal.
      expect(title!.replace(/«[a-z_.]+»/g, ''), `currency=${JSON.stringify(currency)}`).toBe('');
    }
  });
});

describe('MoneyDisplay - dev console warnings (one-shot)', () => {
  it('emits exactly one console.warn when currency is missing, even on re-render', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { rerender } = render(<MoneyDisplay amount={100} />);
    // Re-render the same component instance — the per-instance ref
    // should suppress further warnings.
    rerender(<MoneyDisplay amount={200} />);
    rerender(<MoneyDisplay amount={300} />);

    const calls = warn.mock.calls.filter((args) =>
      String(args[0] ?? '').includes('[MoneyDisplay]'),
    );
    expect(calls.length).toBe(1);
  });

  it('emits one warn for an invalid currency code, mentioning the offending value', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(<MoneyDisplay amount={100} currency="us" />);
    const calls = warn.mock.calls.filter((args) =>
      String(args[0] ?? '').includes('[MoneyDisplay]'),
    );
    expect(calls.length).toBe(1);
    expect(String(calls[0]?.[0] ?? '')).toContain('us');
  });

  it('does NOT emit a warning when a valid currency is supplied', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(<MoneyDisplay amount={100} currency="USD" />);
    const calls = warn.mock.calls.filter((args) =>
      String(args[0] ?? '').includes('[MoneyDisplay]'),
    );
    expect(calls.length).toBe(0);
  });
});
