// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNumberLocale } from '../../stores/usePreferencesStore';
import { currencyFractionDigits } from '../lib/money';
import { isDecimalString } from '../lib/exactDecimal';

// Older engines silently convert strings to Number. Detect actual precision,
// including the fractional digits, and recheck if a polyfill replaces Intl.
const exactStringSupport = new WeakMap<typeof Intl.NumberFormat, boolean>();

function formatDecimal(formatter: Intl.NumberFormat, value: number | string): string {
  // TypeScript's ES2023 Intl declaration predates the decimal-string overload.
  return (formatter.format as (input: number | string) => string)(value);
}

function supportsExactStrings(): boolean {
  const constructor = Intl.NumberFormat;
  const cached = exactStringSupport.get(constructor);
  if (cached !== undefined) return cached;
  let supported = false;
  try {
    const probe = new Intl.NumberFormat('en-US', { useGrouping: false, maximumFractionDigits: 2 });
    supported = formatDecimal(probe, '9007199254740993.01') === '9007199254740993.01';
  } catch {
    // Missing/throwing Intl is also an exact-raw-text fallback.
  }
  exactStringSupport.set(constructor, supported);
  return supported;
}

function rawDecimalWithSign(value: string, policy: MoneyDisplayProps['signDisplay']): string {
  const negative = value.startsWith('-');
  const magnitude = negative ? value.slice(1) : value;
  const zero = !/[1-9]/.test(magnitude);
  if (policy === 'never' || (zero && (policy === 'exceptZero' || policy === 'negative'))) return magnitude;
  if (negative) return value;
  return policy === 'always' || (policy === 'exceptZero' && !zero) ? `+${value}` : value;
}

export interface MoneyDisplayProps {
  amount: number | string | null | undefined;
  currency?: string;
  compact?: boolean;
  showCode?: boolean;
  className?: string;
  colorize?: boolean;
  /**
   * Sign policy, forwarded to `Intl`. Pass `'always'` on a delta or a movement
   * so the plus lands where the reader's language puts it, rather than in
   * front for everyone as a hand-written `+<MoneyDisplay …/>` would be.
   *
   * It does not on its own hold the sign to the figure. `+` and a currency
   * symbol are both prefix-numeric under the Unicode line-breaking algorithm
   * and only one prefix may open an unbreakable numeric run, so a narrow cell
   * may break between them however the string was produced. The cell has to
   * say `whitespace-nowrap` too.
   */
  signDisplay?: Intl.NumberFormatOptions['signDisplay'];
}

/**
 * Locale-aware monetary value display.
 *
 * Uses the user's preferred locale and currency from the preferences store.
 * Supports compact notation (e.g. 1.2M), currency code suffix, and
 * colorized output (green/red) for positive/negative values.
 *
 * Audit I1-I3 fix: respects ISO-4217 minor-unit counts so JPY/KRW/IDR
 * render without decimals, BHD/KWD/OMR/TND render with three. The old
 * implementation hardcoded ``minimumFractionDigits=2``, which turned
 * "100 JPY" into "100.00 JPY" and "100 KWD" into "100.00 KWD" (losing
 * a fils of precision for the latter). When the browser's ``Intl``
 * has up-to-date currency data this would be a no-op — but we can't
 * rely on every supported browser/Node version having the latest
 * tables, hence the explicit overrides.
 *
 * Strict-currency policy (UX-audit fix): when neither the caller nor
 * the user preferences provide a currency, we no longer fall back to
 * EUR silently — a Saudi user with no project currency configured
 * would otherwise see Euros on every card. Instead the component
 * renders an em-dash with a "Currency not set" tooltip, surfacing the
 * configuration gap. In dev builds we also emit a single console
 * warning per component instance so call sites can be flushed out
 * organically.
 */
export function MoneyDisplay({
  amount,
  currency,
  compact = false,
  showCode = false,
  className,
  colorize = false,
  signDisplay,
}: MoneyDisplayProps) {
  // The one resolver, not the raw preference: it reads the number-format
  // setting when the reader has chosen one and the UI language when they have
  // not, which is what keeps this component agreeing with every surface that
  // formats through `getNumberLocale()`, which is now all of them. It is
  // the hook form of that same resolver, so this component also repaints
  // when the setting moves. It is selector-scoped inside, so the
  // component still stays out of the re-render path for unrelated
  // preferences-store mutations (v4.3 audit).
  // Note: we no longer read `currency` from the prefs store. The
  // user-preferences default (always 'EUR' for a fresh install) was
  // the source of the silent-EUR-fallback bug a Saudi user would hit
  // on every money cell. Caller must supply a `currency` prop.
  const numberLocale = useNumberLocale();

  // Above the early returns below: a hook after them renders a different
  // number of hooks on the null-amount branch alone, which React only
  // reports at runtime on that branch.
  const { t } = useTranslation();

  // Dev-only one-shot warning when no currency is supplied by the caller.
  // Tracked per-instance so we don't spam the console on every re-render.
  const warnedMissingCurrencyRef = useRef(false);

  if (amount == null) {
    return <span className={clsx('text-content-tertiary', className)}>&mdash;</span>;
  }

  const exactDecimal = typeof amount === 'string' && isDecimalString(amount) ? amount : null;
  // For canonical strings this is only a sign indicator, never the amount.
  // Preserve even underflow-sized nonzero values for color decisions.
  const numericValue = exactDecimal !== null
    ? /[1-9]/.test(exactDecimal) ? exactDecimal.startsWith('-') ? -1 : 1 : 0
    : typeof amount === 'string' ? parseFloat(amount) : amount;
  const formatValue = exactDecimal ?? numericValue;

  if (Number.isNaN(numericValue)) {
    return <span className={clsx('text-content-tertiary', className)}>&mdash;</span>;
  }

  // Strict currency resolution — no silent EUR fallback. Treat
  // null / undefined / empty-string `currency` prop as "currency not
  // set" and surface an em-dash so the configuration gap is visible
  // rather than masked by a wrong currency symbol (a Saudi user with
  // no project currency configured would otherwise see Euros).
  const trimmedCurrency = typeof currency === 'string' ? currency.trim() : currency;
  if (!trimmedCurrency) {
    if (import.meta.env.DEV && !warnedMissingCurrencyRef.current) {
      warnedMissingCurrencyRef.current = true;
      // eslint-disable-next-line no-console
      console.warn('[MoneyDisplay] missing currency prop');
    }
    return (
      <span
        className={clsx('text-content-tertiary', className)}
        title={t('projects.currency_not_set', { defaultValue: 'Currency not set' })}
      >
        &mdash;
      </span>
    );
  }

  // Validate ISO-4217 shape; a non-matching value (e.g. "us" lowercased,
  // or a numeric code) still means "misconfigured" so we surface the
  // same em-dash rather than guess at EUR.
  if (!/^[A-Z]{3}$/.test(trimmedCurrency)) {
    if (import.meta.env.DEV && !warnedMissingCurrencyRef.current) {
      warnedMissingCurrencyRef.current = true;
      // eslint-disable-next-line no-console
      console.warn(`[MoneyDisplay] invalid currency code: ${trimmedCurrency}`);
    }
    return (
      <span
        className={clsx('text-content-tertiary', className)}
        title={t('projects.currency_not_set', { defaultValue: 'Currency not set' })}
      >
        &mdash;
      </span>
    );
  }

  const safeCurrency = trimmedCurrency;

  // How many decimals this currency gets, asked of the engine rather than of a
  // table of our own. On a screen the reader decides, and how many minor units
  // a currency has is part of what their language considers normal for it: a
  // Hungarian does not write forints with fillér, so a static ISO 4217 list
  // that made us print them was arguing with the reader rather than with CLDR.
  // The opposite rule is the right one for a document and lives with the code
  // that writes documents, because an invoice declares its amount to a bank
  // and a tax office, whose authority is ISO 4217 and not the locale of
  // whoever is looking at a screen.
  //
  // This is the same call the bill and every other money surface make, so one
  // currency cannot carry two decimal counts depending on which page you are
  // on. Five codes used to do exactly that: COP, HUF, IDR, LBP and PKR.
  const minorUnits = currencyFractionDigits(safeCurrency);

  let formatted: string;
  try {
    if (exactDecimal !== null && !supportsExactStrings()) {
      throw new Error('Intl does not preserve decimal strings');
    }
    if (showCode) {
      // Format number without currency, then append ISO code
      const numFmt = new Intl.NumberFormat(numberLocale, {
        minimumFractionDigits: compact ? 0 : minorUnits,
        maximumFractionDigits: compact ? 1 : minorUnits,
        ...(compact ? { notation: 'compact' as const } : {}),
        ...(signDisplay ? { signDisplay } : {}),
      });
      formatted = `${formatDecimal(numFmt, formatValue)} ${safeCurrency}`;
    } else {
      const opts: Intl.NumberFormatOptions = {
        style: 'currency',
        currency: safeCurrency,
        minimumFractionDigits: compact ? 0 : minorUnits,
        maximumFractionDigits: compact ? 1 : minorUnits,
        ...(signDisplay ? { signDisplay } : {}),
      };
      if (compact) {
        opts.notation = 'compact';
      }
      formatted = formatDecimal(new Intl.NumberFormat(numberLocale, opts), formatValue);
    }
  } catch {
    // Preserve the existing numeric fallback when Intl itself has failed.
    const n = Number.isFinite(numericValue) ? numericValue : 0;
    const plus = signDisplay === 'always' && n >= 0 ? '+' : '';
    // Canonical strings retain every digit; neither fallback claims localized
    // or compact formatting when the formatter could not provide it.
    formatted = exactDecimal !== null
      ? `${rawDecimalWithSign(exactDecimal, signDisplay)} ${safeCurrency}`
      : `${plus}${n.toFixed(minorUnits)} ${safeCurrency}`;
  }

  const colorClass = colorize
    ? numericValue > 0
      ? 'text-semantic-success'
      : numericValue < 0
        ? 'text-semantic-error'
        : ''
    : '';

  return <span className={clsx(colorClass, className)}>{formatted}</span>;
}
