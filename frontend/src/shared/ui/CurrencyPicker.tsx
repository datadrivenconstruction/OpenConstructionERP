// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CurrencyPicker - grouped <select> over the shared currency catalogue with
// an opt-in "Custom..." free-text fallback, so any module that lets a user
// pick a currency (cost catalog, assembly create, regional default) can set
// a code outside the common presets (e.g. XAF, XOF, GTQ) without us having
// to enumerate every ISO-4217 code in a dropdown.
//
// Why it exists: the catalog and assembly forms each hard-coded a short
// ~11-18 entry <select>, so an operator working in a currency we did not
// list could not select it at all (the project forms already solved this
// via CURRENCY_GROUPS + a "__custom__" sentinel; this packages that exact
// pattern as one reusable control).
//
// Behaviour contract:
//   * `value` is the resolved currency code the parent stores (e.g. "USD"
//     or a custom "XAF"), NEVER the literal sentinel.
//   * If `value` is a known catalogue code the matching option is selected.
//     If `value` is non-empty but not in the catalogue, the picker shows the
//     "Custom..." option with `value` pre-filled in the free-text input.
//   * `onChange` always receives a normalized code (whitespace stripped,
//     upper-cased) for both preset and custom selections. A custom code is
//     not hard-blocked; an invalid shape just surfaces a soft hint.

import { useState, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CURRENCY_GROUPS,
  CURRENCY_CODES,
  CUSTOM_CURRENCY_SENTINEL,
  normalizeCurrencyCode,
  isValidCurrencyCode,
} from '@/features/projects/currencyGroups';

export interface CurrencyPickerProps {
  /** Resolved currency code (e.g. "EUR", "USD", or a custom "XAF"). */
  value: string;
  /** Called with the normalized code for preset or custom selections. */
  onChange: (code: string) => void;
  /** Field label. */
  label?: string;
  /** Extra classes on the <select>. */
  selectClassName?: string;
  /** id wired to the <select> for <label htmlFor=...> a11y. */
  id?: string;
  /** Disable the control. */
  disabled?: boolean;
}

const DEFAULT_SELECT_CLASS =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary cursor-pointer appearance-none';

export function CurrencyPicker({
  value,
  onChange,
  label,
  selectClassName,
  id,
  disabled = false,
}: CurrencyPickerProps) {
  const { t } = useTranslation();

  // A non-empty value that is not one of the catalogue codes means the user
  // (or a previously saved preference) is on a custom code; reflect that by
  // selecting "Custom..." and seeding the free-text input. We keep custom
  // mode in local state so the input stays visible while the field is empty
  // mid-typing (an empty custom value would otherwise look like a preset).
  const valueIsCustom = value !== '' && !CURRENCY_CODES.has(value);
  const [customMode, setCustomMode] = useState(valueIsCustom);

  const showCustom = customMode || valueIsCustom;
  const selectValue = showCustom ? CUSTOM_CURRENCY_SENTINEL : value;

  const handleSelect = (e: ChangeEvent<HTMLSelectElement>) => {
    const next = e.target.value;
    if (next === CUSTOM_CURRENCY_SENTINEL) {
      setCustomMode(true);
      // Do not clobber an existing custom code if we are re-entering custom.
      if (!valueIsCustom) onChange('');
      return;
    }
    setCustomMode(false);
    onChange(next);
  };

  const handleCustomInput = (e: ChangeEvent<HTMLInputElement>) => {
    onChange(normalizeCurrencyCode(e.target.value));
  };

  const customInvalid = showCustom && value.trim().length > 0 && !isValidCurrencyCode(value);

  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label htmlFor={id} className="text-sm font-medium text-content-primary">
          {label}
        </label>
      )}
      <select
        id={id}
        value={selectValue}
        onChange={handleSelect}
        disabled={disabled}
        className={selectClassName ?? DEFAULT_SELECT_CLASS}
      >
        {CURRENCY_GROUPS.map((g) => (
          <optgroup
            key={g.group}
            label={t(`projects.group_${g.group.toLowerCase().replace(/[^a-z0-9]/g, '_')}`, {
              defaultValue: g.group,
            })}
          >
            {g.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.value === CUSTOM_CURRENCY_SENTINEL
                  ? t('currency_picker.custom_option', { defaultValue: 'Custom...' })
                  : o.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>

      {showCustom && (
        <>
          <input
            type="text"
            value={value}
            onChange={handleCustomInput}
            placeholder={t('currency_picker.custom_placeholder', { defaultValue: 'e.g. XAF' })}
            maxLength={10}
            aria-label={t('currency_picker.custom_aria', {
              defaultValue: 'Custom currency code',
            })}
            aria-invalid={customInvalid}
            className={`h-10 w-full rounded-lg border bg-surface-primary px-3 text-sm text-content-primary uppercase placeholder:normal-case placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:border-transparent ${
              customInvalid
                ? 'border-amber-400 focus:ring-amber-400'
                : 'border-border focus:ring-oe-blue'
            }`}
          />
          {customInvalid && (
            <p className="text-[11px] text-amber-700 dark:text-amber-400">
              {t('currency_picker.custom_hint', {
                defaultValue: 'Use a 3-letter ISO code (e.g. XAF) so amounts format correctly.',
              })}
            </p>
          )}
        </>
      )}
    </div>
  );
}
