// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { formatDistanceToNow } from 'date-fns';
import { getIntlLocale, formatDateWithPreference } from '../lib/formatters';
import { getDateFnsLocale } from '../lib/dateFnsLocale';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

export interface DateDisplayProps {
  value: string | Date | null | undefined;
  format?: 'date' | 'numeric' | 'datetime' | 'relative' | 'time';
  className?: string;
}

const DATE_OPTIONS: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
};

/** All-numeric date (de-DE: 14.03.2026) for dense cards and list rows. */
const NUMERIC_DATE_OPTIONS: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
};

const DATETIME_OPTIONS: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
};

const TIME_OPTIONS: Intl.DateTimeFormatOptions = {
  hour: '2-digit',
  minute: '2-digit',
};

/**
 * Locale-aware date/time display component.
 *
 * Renders a formatted date string based on the user's current i18next language
 * and their date-format preference (Settings → Regional → Date Format), which
 * reorders the day/month/year fields when it is set to anything but automatic.
 * Supports date, datetime, time, and relative (e.g. "3 hours ago") formats.
 * Returns an em-dash for null, undefined, or invalid input values.
 */
export function DateDisplay({ value, format = 'date', className }: DateDisplayProps) {
  // Ensure i18n is initialized so getIntlLocale() reads the current language
  useTranslation();
  // Subscribe rather than read through getState() so a change in Settings
  // repaints the pages that are already open. Both hooks stay above the early
  // returns below: a null date must not render fewer hooks than a real one.
  const datePref = usePreferencesStore((s) => s.dateFormat);

  if (value == null) {
    return <span className={clsx('text-content-tertiary', className)}>&mdash;</span>;
  }

  const dateObj = value instanceof Date ? value : new Date(value);

  if (Number.isNaN(dateObj.getTime())) {
    return <span className={clsx('text-content-tertiary', className)}>&mdash;</span>;
  }

  const locale = getIntlLocale();
  // A date-only string (YYYY-MM-DD) parses as UTC midnight; see the date case.
  const isDateOnly = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);

  let formatted: string;
  try {
    switch (format) {
      case 'relative':
        // `locale` is not optional in the way its signature suggests: omitting
        // it does not mean "use the ambient language", it means en-US. The
        // absolute branches below already pass `locale` to Intl, so leaving it
        // off here was the one place this component answered in English.
        formatted = formatDistanceToNow(dateObj, {
          addSuffix: true,
          locale: getDateFnsLocale(),
        });
        break;
      case 'datetime':
        formatted = formatDateWithPreference(dateObj, locale, DATETIME_OPTIONS, datePref);
        break;
      case 'time':
        // No date fields, so nothing for the preference to reorder.
        formatted = new Intl.DateTimeFormat(locale, TIME_OPTIONS).format(dateObj);
        break;
      case 'numeric':
        // Same UTC pinning rationale as 'date' below.
        formatted = formatDateWithPreference(
          dateObj,
          locale,
          isDateOnly ? { ...NUMERIC_DATE_OPTIONS, timeZone: 'UTC' } : NUMERIC_DATE_OPTIONS,
          datePref,
        );
        break;
      case 'date':
      default:
        // Render date-only values in UTC so the calendar day is not pushed
        // back a day at negative UTC offsets (e.g. UTC-6). Timestamps keep
        // local-zone rendering.
        formatted = formatDateWithPreference(
          dateObj,
          locale,
          isDateOnly ? { ...DATE_OPTIONS, timeZone: 'UTC' } : DATE_OPTIONS,
          datePref,
        );
        break;
    }
  } catch {
    formatted = dateObj.toLocaleDateString(getIntlLocale());
  }

  return (
    <time dateTime={dateObj.toISOString()} className={className}>
      {formatted}
    </time>
  );
}
