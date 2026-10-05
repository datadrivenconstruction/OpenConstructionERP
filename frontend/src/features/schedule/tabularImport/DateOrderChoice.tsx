// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Day first or month first, for a file whose dates read both ways.
 *
 * "03/04/2026" is 3 April in most of the world and March 4 in the US. When no
 * date in the file settles it, the importer only suggests an order and the
 * person confirms it; each choice shows what the file's own example becomes.
 */
import { useTranslation } from 'react-i18next';
import { CalendarDays } from 'lucide-react';
import clsx from 'clsx';

import { getIntlLocale } from '@/shared/lib/formatters';
import type { DateOrder } from './tabularImport';

const NUMERIC = /^(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})/;

/** The example read in `order`, written out with the month's name, or `null`. */
export function readExample(example: string | null, order: DateOrder): string | null {
  const match = example ? NUMERIC.exec(example.trim()) : null;
  if (!match) return null;
  const first = Number(match[1]);
  const second = Number(match[2]);
  let year = Number(match[3]);
  if (match[3]!.length === 2) year += year < 70 ? 2000 : 1900;
  const [day, month] = order === 'dmy' ? [first, second] : [second, first];
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return date.toLocaleDateString(getIntlLocale(), { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
}

export interface DateOrderChoiceProps {
  /** The order the person confirmed, `null` while unconfirmed. */
  value: DateOrder | null;
  onChange: (order: DateOrder) => void;
  /** What the importer proposes, and why ("durations" or "convention"). */
  suggested: DateOrder | null;
  suggestedBy?: string | null;
  /** One date from the file that reads both ways. */
  example: string | null;
  /** The file cannot be imported until an order is chosen. */
  required: boolean;
  disabled?: boolean;
}

export function DateOrderChoice({
  value,
  onChange,
  suggested,
  suggestedBy,
  example,
  required,
  disabled = false,
}: DateOrderChoiceProps) {
  const { t } = useTranslation();

  const options: { order: DateOrder; label: string }[] = [
    { order: 'dmy', label: t('schedule.tabular_import.date_dmy', { defaultValue: 'Day first (31/12/2026)' }) },
    { order: 'mdy', label: t('schedule.tabular_import.date_mdy', { defaultValue: 'Month first (12/31/2026)' }) },
  ];

  return (
    <fieldset
      className={clsx(
        'rounded-lg border p-3',
        required && !value ? 'border-semantic-warning bg-semantic-warning-bg/40' : 'border-border-light',
      )}
      data-testid="tabular-date-order"
    >
      <legend className="flex items-center gap-1.5 px-1 text-xs font-semibold text-content-primary">
        <CalendarDays size={14} className="text-content-secondary" />
        {t('schedule.tabular_import.date_order_title', { defaultValue: 'How are the dates written?' })}
      </legend>
      {required && !value && (
        <p className="mb-2 text-xs text-content-secondary">
          {example
            ? t('schedule.tabular_import.date_order_needed_example', {
                defaultValue: 'Dates such as "{{example}}" read either way. Choose the order before importing.',
                example,
              })
            : t('schedule.tabular_import.date_order_needed', {
                defaultValue: 'Some dates read either way. Choose the order before importing.',
              })}
        </p>
      )}
      <div className="flex flex-col gap-2 sm:flex-row">
        {options.map(({ order, label }) => {
          const reading = readExample(example, order);
          return (
            <label
              key={order}
              className={clsx(
                'flex flex-1 cursor-pointer items-start gap-2 rounded-md border px-3 py-2 text-xs',
                value === order ? 'border-oe-blue bg-oe-blue-subtle' : 'border-border-light',
                disabled && 'cursor-not-allowed opacity-60',
              )}
            >
              <input
                type="radio"
                name="tabular-date-order"
                value={order}
                checked={value === order}
                disabled={disabled}
                onChange={() => onChange(order)}
                className="mt-0.5 accent-oe-blue"
              />
              <span>
                <span className="block font-medium text-content-primary">{label}</span>
                {reading && example && (
                  <span className="block text-content-secondary">
                    {t('schedule.tabular_import.date_reads_as', {
                      defaultValue: '"{{example}}" becomes {{date}}',
                      example,
                      date: reading,
                    })}
                  </span>
                )}
                {suggested === order && value !== order && (
                  <span className="mt-0.5 block text-oe-blue-text">
                    {suggestedBy === 'durations'
                      ? t('schedule.tabular_import.date_suggested_durations', {
                          defaultValue: 'Suggested: matches the durations in the file',
                        })
                      : t('schedule.tabular_import.date_suggested', { defaultValue: 'Suggested' })}
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
