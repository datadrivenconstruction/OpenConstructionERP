// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The "Product and procurement" group of the submittal form: what is being
 * proposed (discipline, maker, model, origin, supplier) and the three numbers
 * the register needs to say whether the item will arrive in time (required on
 * site, lead time, the contract's review period).
 *
 * Kept beside the form rather than inside it so the payload builders can be
 * tested on their own, the way `buildSubmittalPatch` is. Two rules hold
 * throughout:
 *
 * - The discipline list is the vocabulary route's. Nothing is offered until
 *   it answers, and a code outside it stays typeable, as the column allows.
 * - No date is worked out here. The approval deadline shown in edit mode is
 *   the one the server derived from the saved values, and it steps aside for
 *   a plain "recalculated on save" the moment one of its inputs is edited.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ChevronDown } from 'lucide-react';

import { CountryCombobox, DateDisplay, WideModalField, WideModalSection } from '@/shared/ui';
import type { Submittal, SubmittalType, SubmittalVocabulary, UpdateSubmittalPayload } from './api';
import { vocabularyEntry } from './registerView';

export interface ProcurementFormData {
  /** Lower-case code, '' for unset. */
  discipline: string;
  manufacturer: string;
  model_reference: string;
  /** ISO 3166-1 alpha-2, '' for unset. */
  country_of_origin: string;
  supplier: string;
  required_on_site_date: string;
  long_lead: boolean;
  /** Whole weeks as typed; '' for unset. */
  lead_time_weeks: string;
  /** Whole calendar days as typed; '' for unknown. There is no default. */
  review_period_days: string;
}

export const EMPTY_PROCUREMENT_FORM: ProcurementFormData = {
  discipline: '',
  manufacturer: '',
  model_reference: '',
  country_of_origin: '',
  supplier: '',
  required_on_site_date: '',
  long_lead: false,
  lead_time_weeks: '',
  review_period_days: '',
};

// The bounds the schema puts on the two numbers (`_MAX_LEAD_TIME_WEEKS`,
// `_MAX_REVIEW_PERIOD_DAYS` in backend/app/modules/submittals/schemas.py).
// Past them the server answers 422, so the form says so first.
export const MAX_LEAD_TIME_WEEKS = 260;
export const MAX_REVIEW_PERIOD_DAYS = 365;

// `DISCIPLINE_PATTERN` of the same schema, applied after the same
// normalisation the server does (trim, lower case, spaces and hyphens to "_").
const DISCIPLINE_CODE = /^[a-z][a-z0-9_]{0,49}$/;

/** The types for which a submittal with no manufacturer is flagged at validation. */
const MATERIAL_TYPES: ReadonlySet<string> = new Set(['product_data', 'sample']);

/** A typed discipline as the server would store it. */
export function normaliseDiscipline(text: string): string {
  return text.trim().toLowerCase().replace(/[-\s]/g, '_');
}

/** A typed whole number: the number, `null` for empty, `'invalid'` otherwise. */
function parseWhole(text: string, max: number): number | null | 'invalid' {
  const trimmed = text.trim();
  if (trimmed === '') return null;
  if (!/^\d+$/.test(trimmed)) return 'invalid';
  const value = Number(trimmed);
  return value <= max ? value : 'invalid';
}

/**
 * The group's form state for a submittal being edited.
 *
 * The supplier is shown by its resolved name. When it is a contact id the
 * name is what a person can read, and because an untouched field is left out
 * of the save, the stored id survives an edit that does not concern it.
 */
export function procurementFormData(existing?: Submittal): ProcurementFormData {
  if (!existing) return EMPTY_PROCUREMENT_FORM;
  return {
    discipline: existing.discipline ?? '',
    manufacturer: existing.manufacturer ?? '',
    model_reference: existing.model_reference ?? '',
    country_of_origin: existing.country_of_origin ?? '',
    supplier: existing.supplier_name ?? existing.supplier ?? '',
    required_on_site_date: existing.required_on_site_date ?? '',
    long_lead: existing.long_lead,
    lead_time_weeks: existing.lead_time_weeks === null ? '' : String(existing.lead_time_weeks),
    review_period_days: existing.review_period_days === null ? '' : String(existing.review_period_days),
  };
}

export interface ProcurementErrors {
  discipline: boolean;
  /** `required`: a long-lead item must say how long the lead is. */
  lead_time_weeks: 'required' | 'range' | null;
  review_period_days: boolean;
}

/** What stops the group from being saved. */
export function procurementErrors(form: ProcurementFormData): ProcurementErrors {
  const discipline = normaliseDiscipline(form.discipline);
  const lead = parseWhole(form.lead_time_weeks, MAX_LEAD_TIME_WEEKS);
  return {
    discipline: discipline !== '' && !DISCIPLINE_CODE.test(discipline),
    lead_time_weeks: lead === 'invalid' ? 'range' : form.long_lead && lead === null ? 'required' : null,
    review_period_days: parseWhole(form.review_period_days, MAX_REVIEW_PERIOD_DAYS) === 'invalid',
  };
}

export function hasProcurementErrors(form: ProcurementFormData): boolean {
  const errors = procurementErrors(form);
  return errors.discipline || errors.lead_time_weeks !== null || errors.review_period_days;
}

export type ProcurementPayload = Pick<
  UpdateSubmittalPayload,
  | 'discipline'
  | 'manufacturer'
  | 'model_reference'
  | 'country_of_origin'
  | 'supplier'
  | 'review_period_days'
  | 'required_on_site_date'
  | 'long_lead'
  | 'lead_time_weeks'
>;

function wholeOrNull(text: string, max: number): number | null {
  const value = parseWhole(text, max);
  return value === 'invalid' ? null : value;
}

/**
 * The group's part of an edit: only what the user changed, like the rest of
 * the form. A cleared value goes as `null`, which is the only thing the
 * patterns on the dates and the numbers accept for "none".
 */
export function buildProcurementPatch(form: ProcurementFormData, base: ProcurementFormData): ProcurementPayload {
  const data: ProcurementPayload = {};
  if (normaliseDiscipline(form.discipline) !== normaliseDiscipline(base.discipline)) {
    data.discipline = normaliseDiscipline(form.discipline) || null;
  }
  if (form.manufacturer !== base.manufacturer) data.manufacturer = form.manufacturer.trim() || null;
  if (form.model_reference !== base.model_reference) data.model_reference = form.model_reference.trim() || null;
  if (form.country_of_origin !== base.country_of_origin) data.country_of_origin = form.country_of_origin || null;
  if (form.supplier !== base.supplier) data.supplier = form.supplier.trim() || null;
  if (form.required_on_site_date !== base.required_on_site_date) {
    data.required_on_site_date = form.required_on_site_date || null;
  }
  if (form.long_lead !== base.long_lead) data.long_lead = form.long_lead;
  if (form.lead_time_weeks.trim() !== base.lead_time_weeks.trim()) {
    data.lead_time_weeks = wholeOrNull(form.lead_time_weeks, MAX_LEAD_TIME_WEEKS);
  }
  if (form.review_period_days.trim() !== base.review_period_days.trim()) {
    data.review_period_days = wholeOrNull(form.review_period_days, MAX_REVIEW_PERIOD_DAYS);
  }
  return data;
}

/** The group's part of a create: only the fields that were filled in. */
export function buildProcurementCreate(form: ProcurementFormData): ProcurementPayload {
  const data: ProcurementPayload = {};
  const discipline = normaliseDiscipline(form.discipline);
  if (discipline) data.discipline = discipline;
  if (form.manufacturer.trim()) data.manufacturer = form.manufacturer.trim();
  if (form.model_reference.trim()) data.model_reference = form.model_reference.trim();
  if (form.country_of_origin) data.country_of_origin = form.country_of_origin;
  if (form.supplier.trim()) data.supplier = form.supplier.trim();
  if (form.required_on_site_date) data.required_on_site_date = form.required_on_site_date;
  if (form.long_lead) data.long_lead = true;
  const lead = wholeOrNull(form.lead_time_weeks, MAX_LEAD_TIME_WEEKS);
  if (lead !== null) data.lead_time_weeks = lead;
  const period = wholeOrNull(form.review_period_days, MAX_REVIEW_PERIOD_DAYS);
  if (period !== null) data.review_period_days = period;
  return data;
}

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const invalidCls = ' border-semantic-error focus:ring-semantic-error/30';

/**
 * The message under a field that cannot be saved as typed.
 *
 * Drawn here instead of through the field wrapper's `error` prop: the wrapper
 * re-keys its child when an error appears or clears, which remounts the input
 * and drops the caret in the middle of typing the value that clears it.
 */
function FieldError({ message }: { message: string | undefined }) {
  if (!message) return null;
  return (
    <p role="alert" className="mt-1 text-xs text-semantic-error">
      {message}
    </p>
  );
}

// The select's entry that switches the discipline to a typed code.
const OTHER_DISCIPLINE = '__other__';

export function SubmittalProcurementFields({
  idPrefix,
  form,
  type,
  onChange,
  vocabulary,
  existing,
}: {
  idPrefix: string;
  form: ProcurementFormData;
  type: SubmittalType;
  onChange: <K extends keyof ProcurementFormData>(key: K, value: ProcurementFormData[K]) => void;
  vocabulary: SubmittalVocabulary | null;
  /** The submittal being edited; carries the dates the server derived. */
  existing?: Submittal;
}) {
  const { t } = useTranslation();
  const disciplines = vocabulary?.disciplines ?? [];
  const offered = vocabularyEntry(disciplines, form.discipline) !== undefined;
  // A code outside the offered list opens the form in "typed" mode, so a
  // project's own discipline is shown as it is instead of as an empty select.
  const [typedDiscipline, setTypedDiscipline] = useState(form.discipline !== '' && !offered);
  const errors = procurementErrors(form);
  const isMaterial = MATERIAL_TYPES.has(type);
  // The lead time belongs to a long-lead item. It also stays on screen for a
  // row that carries one without the flag, so stored data is never hidden.
  const showLeadTime = form.long_lead || form.lead_time_weeks.trim() !== '';

  const base = procurementFormData(existing);
  const deadlineInputsUntouched =
    form.required_on_site_date === base.required_on_site_date &&
    form.lead_time_weeks.trim() === base.lead_time_weeks.trim() &&
    form.review_period_days.trim() === base.review_period_days.trim();
  const late = (existing?.approval_late_days ?? 0) > 0;

  const rangeError = (max: number) =>
    t('submittals.whole_number_range', {
      defaultValue: 'Enter a whole number from 0 to {{max}}',
      max,
    });

  return (
    <WideModalSection
      columns={2}
      title={t('submittals.group_product', { defaultValue: 'Product and procurement' })}
      description={t('submittals.group_product_hint', {
        defaultValue:
          'What is proposed and when the site needs it. All optional; the dates and the lead time are what tell you whether an approval is running late.',
      })}
    >
      <WideModalField
        label={t('submittals.field_discipline', { defaultValue: 'Discipline' })}
        htmlFor={`${idPrefix}-discipline`}
      >
        {disciplines.length > 0 && !typedDiscipline ? (
          <div className="relative">
            <select
              id={`${idPrefix}-discipline`}
              value={form.discipline}
              onChange={(e) => {
                if (e.target.value === OTHER_DISCIPLINE) {
                  setTypedDiscipline(true);
                  onChange('discipline', '');
                } else {
                  onChange('discipline', e.target.value);
                }
              }}
              className={inputCls + ' appearance-none pr-9'}
            >
              <option value="">{t('submittals.discipline_none', { defaultValue: 'No discipline' })}</option>
              {disciplines.map((entry) => (
                <option key={entry.code} value={entry.code}>
                  {entry.short_code ? `${entry.short_code} - ${entry.label}` : entry.label}
                </option>
              ))}
              <option value={OTHER_DISCIPLINE}>
                {t('submittals.discipline_other', { defaultValue: 'Other (type a code)' })}
              </option>
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <input
              id={`${idPrefix}-discipline`}
              value={form.discipline}
              onChange={(e) => onChange('discipline', e.target.value)}
              placeholder={t('submittals.discipline_placeholder', { defaultValue: 'e.g. hvac' })}
              aria-invalid={errors.discipline || undefined}
              className={inputCls + (errors.discipline ? invalidCls : '')}
            />
            {disciplines.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  setTypedDiscipline(false);
                  onChange('discipline', '');
                }}
                className="shrink-0 text-xs font-medium text-oe-blue-text hover:underline"
              >
                {t('submittals.discipline_pick', { defaultValue: 'Pick from the list' })}
              </button>
            )}
          </div>
        )}
        <FieldError
          message={
            errors.discipline
              ? t('submittals.discipline_invalid', {
                  defaultValue: 'Use a short code: letters, digits and underscores, starting with a letter',
                })
              : undefined
          }
        />
      </WideModalField>

      <WideModalField
        label={t('submittals.field_manufacturer', { defaultValue: 'Manufacturer / brand' })}
        htmlFor={`${idPrefix}-manufacturer`}
        hint={
          isMaterial && form.manufacturer.trim() === ''
            ? t('submittals.manufacturer_prompt', {
                defaultValue:
                  'Name who makes the product. A material submittal without a manufacturer gives the reviewer nothing to approve and is flagged when it is checked.',
              })
            : undefined
        }
      >
        <input
          id={`${idPrefix}-manufacturer`}
          value={form.manufacturer}
          onChange={(e) => onChange('manufacturer', e.target.value)}
          maxLength={255}
          className={clsx(
            inputCls,
            isMaterial && form.manufacturer.trim() === '' && 'border-amber-400 dark:border-amber-600',
          )}
        />
      </WideModalField>

      <WideModalField
        label={t('submittals.field_model_reference', { defaultValue: 'Model / reference' })}
        htmlFor={`${idPrefix}-model-reference`}
      >
        <input
          id={`${idPrefix}-model-reference`}
          value={form.model_reference}
          onChange={(e) => onChange('model_reference', e.target.value)}
          maxLength={255}
          className={inputCls}
        />
      </WideModalField>

      <WideModalField
        label={t('submittals.field_country_of_origin', { defaultValue: 'Country of origin' })}
        htmlFor={`${idPrefix}-country-of-origin`}
      >
        <CountryCombobox
          id={`${idPrefix}-country-of-origin`}
          value={form.country_of_origin}
          onChange={(next) => onChange('country_of_origin', next)}
          allowEmpty
          allowCustom={false}
        />
      </WideModalField>

      <WideModalField
        label={t('submittals.field_supplier', { defaultValue: 'Supplier' })}
        span={2}
        htmlFor={`${idPrefix}-supplier`}
        hint={t('submittals.supplier_hint', {
          defaultValue: 'The company the item is bought from, when it is not the manufacturer.',
        })}
      >
        <input
          id={`${idPrefix}-supplier`}
          value={form.supplier}
          onChange={(e) => onChange('supplier', e.target.value)}
          maxLength={255}
          className={inputCls}
        />
      </WideModalField>

      <WideModalField
        label={t('submittals.field_required_on_site', { defaultValue: 'Required on site' })}
        htmlFor={`${idPrefix}-required-on-site`}
        hint={t('submittals.required_on_site_hint', {
          defaultValue: 'When the item has to be on site. Not the date the review answer is due.',
        })}
      >
        <input
          id={`${idPrefix}-required-on-site`}
          type="date"
          value={form.required_on_site_date}
          onChange={(e) => onChange('required_on_site_date', e.target.value)}
          className={inputCls}
        />
      </WideModalField>

      <WideModalField
        label={t('submittals.field_review_period_days', { defaultValue: 'Review period (days)' })}
        htmlFor={`${idPrefix}-review-period`}
        hint={t('submittals.review_period_hint', {
          defaultValue:
            'Calendar days the contract gives the reviewer. Leave empty if the contract does not say: a review is only called overdue against this number.',
        })}
      >
        <input
          id={`${idPrefix}-review-period`}
          type="number"
          inputMode="numeric"
          min={0}
          max={MAX_REVIEW_PERIOD_DAYS}
          step={1}
          value={form.review_period_days}
          onChange={(e) => onChange('review_period_days', e.target.value)}
          placeholder={t('submittals.review_period_placeholder', { defaultValue: 'As per contract' })}
          aria-invalid={errors.review_period_days || undefined}
          className={inputCls + (errors.review_period_days ? invalidCls : '')}
        />
        <FieldError message={errors.review_period_days ? rangeError(MAX_REVIEW_PERIOD_DAYS) : undefined} />
      </WideModalField>

      <WideModalField span={showLeadTime ? 1 : 2}>
        <label className="flex h-10 cursor-pointer items-center gap-2 text-sm text-content-primary">
          <input
            id={`${idPrefix}-long-lead`}
            type="checkbox"
            checked={form.long_lead}
            onChange={(e) => {
              onChange('long_lead', e.target.checked);
              // Unticking takes the lead time with it, so no value stays
              // behind in a field the form no longer shows.
              if (!e.target.checked) onChange('lead_time_weeks', '');
            }}
            className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
          />
          <span>{t('submittals.field_long_lead', { defaultValue: 'Long-lead item' })}</span>
        </label>
        <p className="text-xs text-content-tertiary">
          {t('submittals.long_lead_hint', {
            defaultValue: 'Tick when the item takes weeks to arrive, so a late approval moves the delivery.',
          })}
        </p>
      </WideModalField>

      {showLeadTime && (
        <WideModalField
          label={t('submittals.field_lead_time_weeks', { defaultValue: 'Lead time (weeks)' })}
          required={form.long_lead}
          htmlFor={`${idPrefix}-lead-time`}
          hint={t('submittals.lead_time_hint', {
            defaultValue: 'Weeks from order to delivery on site. The approval is needed by required on site less this.',
          })}
        >
          <input
            id={`${idPrefix}-lead-time`}
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_LEAD_TIME_WEEKS}
            step={1}
            value={form.lead_time_weeks}
            onChange={(e) => onChange('lead_time_weeks', e.target.value)}
            aria-invalid={errors.lead_time_weeks !== null || undefined}
            className={inputCls + (errors.lead_time_weeks !== null ? invalidCls : '')}
          />
          <FieldError
            message={
              errors.lead_time_weeks === 'required'
                ? t('submittals.lead_time_required', {
                    defaultValue: 'A long-lead item needs its lead time',
                  })
                : errors.lead_time_weeks === 'range'
                  ? rangeError(MAX_LEAD_TIME_WEEKS)
                  : undefined
            }
          />
        </WideModalField>
      )}

      {existing && (existing.approval_needed_by || existing.submit_by_date) && (
        <WideModalField span={2}>
          {deadlineInputsUntouched ? (
            <p
              data-testid={`${idPrefix}-deadlines`}
              className={clsx('text-xs', late ? 'font-medium text-semantic-error' : 'text-content-secondary')}
            >
              {existing.approval_needed_by && (
                <span className="me-4">
                  {t('submittals.col_approval_needed_by', { defaultValue: 'Approval needed by' })}:{' '}
                  <DateDisplay value={existing.approval_needed_by} className="text-xs" />
                </span>
              )}
              {existing.submit_by_date && (
                <span>
                  {t('submittals.label_submit_by', { defaultValue: 'Submit by' })}:{' '}
                  <DateDisplay value={existing.submit_by_date} className="text-xs" />
                </span>
              )}
            </p>
          ) : (
            <p data-testid={`${idPrefix}-deadlines`} className="text-xs text-content-tertiary">
              {t('submittals.deadlines_on_save', {
                defaultValue: 'The approval and submission deadlines are recalculated when you save.',
              })}
            </p>
          )}
        </WideModalField>
      )}
    </WideModalSection>
  );
}
