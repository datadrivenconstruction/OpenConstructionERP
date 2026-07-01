import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { formatDistanceToNow } from 'date-fns';
import { getIntlLocale } from '../lib/formatters';

export interface DateDisplayProps {
  value: string | Date | null | undefined;
  format?: 'date' | 'datetime' | 'relative' | 'time';
  className?: string;
}

const DATE_OPTIONS: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: 'short',
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
 * Renders a formatted date string based on the user's current i18next language.
 * Supports date, datetime, time, and relative (e.g. "3 hours ago") formats.
 * Returns an em-dash for null, undefined, or invalid input values.
 */
export function DateDisplay({ value, format = 'date', className }: DateDisplayProps) {
  // Ensure i18n is initialized so getIntlLocale() reads the current language
  useTranslation();

  if (value == null) {
    return <span className={clsx('text-content-tertiary', className)}>&mdash;</span>;
  }

  const dateObj = value instanceof Date ? value : new Date(value);

  if (Number.isNaN(dateObj.getTime())) {
    return <span className={clsx('text-content-tertiary', className)}>&mdash;</span>;
  }

  const locale = getIntlLocale();

  let formatted: string;
  try {
    switch (format) {
      case 'relative':
        formatted = formatDistanceToNow(dateObj, { addSuffix: true });
        break;
      case 'datetime':
        formatted = new Intl.DateTimeFormat(locale, DATETIME_OPTIONS).format(dateObj);
        break;
      case 'time':
        formatted = new Intl.DateTimeFormat(locale, TIME_OPTIONS).format(dateObj);
        break;
      case 'date':
      default: {
        const options = (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value))
          ? { ...DATE_OPTIONS, timeZone: 'UTC' }
          : DATE_OPTIONS;
        formatted = new Intl.DateTimeFormat(locale, options).format(dateObj);
        break;
      }
    }
  } catch {
    formatted = dateObj.toLocaleDateString();
  }

  return (
    <time dateTime={dateObj.toISOString()} className={className}>
      {formatted}
    </time>
  );
}
