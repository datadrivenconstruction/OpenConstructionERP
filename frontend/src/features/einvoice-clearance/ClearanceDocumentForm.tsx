// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The form that prepares one invoice for one country platform.
 *
 * The second thing this module could not do from its own screen. The list of
 * documents had a filter, a count and an empty state describing what a document
 * is, and nothing that would produce one.
 *
 * The national fields are the point of the form. A country format asks for
 * things the EN 16931 semantic model has nowhere to put, `codice_destinatario`
 * in Italy and `uso_cfdi` in Mexico and a buyer reference in Germany, and the
 * backend registry names them per country in `document_fields`. They are read
 * from there and rendered as they come, so the form is right for a country
 * nobody wrote a form for.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/Button';

import type { ClearanceMeta, ClearanceProfile, DocumentCreateBody } from './api';
import { documentInput } from './mentionFields';

/**
 * `partita_iva_issuer` reads as a field name. `Partita iva issuer` reads as a
 * label. The registry is the authority on which fields exist, so the label is
 * derived from the name rather than kept in a second list that would drift.
 */
function humanise(field: string): string {
  const spaced = field.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function ClearanceDocumentForm({
  meta,
  profiles,
  projectId,
  pending,
  onSubmit,
  onCancel,
}: {
  meta: ClearanceMeta | undefined;
  /** Already filtered to the ones a document can actually be filed under. */
  profiles: ClearanceProfile[];
  projectId: string;
  pending: boolean;
  onSubmit: (body: DocumentCreateBody) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();

  // With exactly one registration there is nothing to choose between, so the
  // form starts on it rather than making the operator pick the only option.
  const [profileId, setProfileId] = useState(profiles.length === 1 ? (profiles[0]?.id ?? '') : '');
  const [invoiceNumber, setInvoiceNumber] = useState('');
  const [invoiceDate, setInvoiceDate] = useState('');
  const [currencyCode, setCurrencyCode] = useState('');
  const [totalAmount, setTotalAmount] = useState('');
  const [countryFields, setCountryFields] = useState<Record<string, string>>({});

  const profile = profiles.find((p) => p.id === profileId) ?? null;
  const country = useMemo(
    () => (meta?.countries ?? []).find((c) => c.country === profile?.country) ?? null,
    [meta, profile],
  );
  const nationalFields = country?.document_fields ?? [];
  const mentionFields = country?.optional_document_fields ?? [];

  const ready =
    profileId !== '' &&
    invoiceNumber.trim().length > 0 &&
    invoiceDate !== '' &&
    currencyCode.trim().length > 0 &&
    totalAmount.trim().length > 0;

  if (profiles.length === 0) {
    return (
      <div className="rounded-lg border border-border-light p-3 text-sm text-content-secondary">
        {t('einvoice_clearance.document_needs_profile', {
          defaultValue:
            'A document is filed under a registration, and there is no active one with an adapter yet. Register a country below first.',
        })}
      </div>
    );
  }

  return (
    <form
      className="space-y-3 rounded-lg border border-border-light p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready || pending) return;
        onSubmit({
          project_id: projectId,
          profile_id: profileId,
          invoice_number: invoiceNumber.trim(),
          invoice_date: invoiceDate,
          currency_code: currencyCode.trim().toUpperCase(),
          // Sent as a string all the way. A tax authority's arithmetic is exact
          // and a binary float cannot hold 0.10.
          total_amount: totalAmount.trim(),
          country_fields: Object.fromEntries(
            Object.entries(countryFields).filter(([, v]) => v.trim() !== ''),
          ),
        });
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        {t('einvoice_clearance.field_profile', { defaultValue: 'File it under' })}
        <select
          value={profileId}
          onChange={(e) => {
            setProfileId(e.target.value);
            // The national fields belong to the country, so a different
            // registration means a different set and the old answers do not
            // carry over.
            setCountryFields({});
          }}
          required
          className="rounded border border-border-light bg-surface-primary p-2"
        >
          <option value="">
            {t('einvoice_clearance.field_profile_none', {
              defaultValue: 'Choose a registration',
            })}
          </option>
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.company_key} · {p.country} · {p.platform}
              {p.sandbox
                ? ` · ${t('einvoice_clearance.sandbox', { defaultValue: 'Sandbox' })}`
                : ''}
            </option>
          ))}
        </select>
      </label>

      {profile && !profile.sandbox && (
        <p className="rounded border border-semantic-warning bg-semantic-warning-bg p-2 text-xs">
          {t('einvoice_clearance.live_profile_warning', {
            defaultValue:
              'This registration files for real. Preparing and checking a document still sends nothing; submitting it does.',
          })}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          {t('einvoice_clearance.field_invoice_number', { defaultValue: 'Invoice number' })}
          <input
            value={invoiceNumber}
            onChange={(e) => setInvoiceNumber(e.target.value)}
            maxLength={64}
            required
            className="rounded border border-border-light bg-surface-primary p-2 font-mono"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          {t('einvoice_clearance.field_invoice_date', { defaultValue: 'Invoice date' })}
          <input
            type="date"
            value={invoiceDate}
            onChange={(e) => setInvoiceDate(e.target.value)}
            required
            className="rounded border border-border-light bg-surface-primary p-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          {t('einvoice_clearance.field_currency', { defaultValue: 'Currency' })}
          <input
            value={currencyCode}
            onChange={(e) => setCurrencyCode(e.target.value)}
            maxLength={3}
            required
            placeholder="EUR"
            className="rounded border border-border-light bg-surface-primary p-2 font-mono uppercase"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          {t('einvoice_clearance.field_total_amount', { defaultValue: 'Total' })}
          <input
            value={totalAmount}
            onChange={(e) => setTotalAmount(e.target.value)}
            inputMode="decimal"
            required
            placeholder="0.00"
            className="rounded border border-border-light bg-surface-primary p-2 text-right font-mono"
          />
        </label>
      </div>

      {country && nationalFields.length > 0 && (
        <fieldset className="space-y-2 rounded border border-border-light p-2">
          <legend className="px-1 text-xs font-medium text-content-secondary">
            {t('einvoice_clearance.national_fields_title', {
              defaultValue: 'What {{platform}} asks for on top',
              platform: country.platform,
            })}
          </legend>
          <p className="text-xs text-content-tertiary">
            {t('einvoice_clearance.national_fields_note', {
              defaultValue:
                'These belong to the country format and have no place in the shared invoice model. A missing one is found by the check, not at your desk three minutes before the month closes.',
            })}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {nationalFields.map((field) => (
              <label key={field} className="flex flex-col gap-1 text-sm">
                {t(`einvoice_clearance.country_field.${field}`, { defaultValue: humanise(field) })}
                <input
                  value={countryFields[field] ?? ''}
                  onChange={(e) =>
                    setCountryFields((prev) => ({ ...prev, [field]: e.target.value }))
                  }
                  maxLength={255}
                  className="rounded border border-border-light bg-surface-primary p-2 font-mono"
                />
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {country && mentionFields.length > 0 && (
        <fieldset className="space-y-2 rounded border border-border-light p-2">
          <legend className="px-1 text-xs font-medium text-content-secondary">
            {t('einvoice_clearance.mentions_title', {
              defaultValue: 'Mentions the invoice should carry',
            })}
          </legend>
          <p className="text-xs text-content-tertiary">
            {t('einvoice_clearance.mentions_note', {
              defaultValue:
                'Optional here. The check tells you which of them the law requires on this invoice date.',
            })}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {mentionFields.map((field) => {
              const input = documentInput(field);
              const label = t(`einvoice_clearance.country_field.${field}`, {
                defaultValue: humanise(field),
              });
              if (input.kind === 'checkbox') {
                return (
                  <label key={field} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={countryFields[field] === 'true'}
                      onChange={(e) =>
                        setCountryFields((prev) => ({
                          ...prev,
                          [field]: e.target.checked ? 'true' : '',
                        }))
                      }
                    />
                    {label}
                  </label>
                );
              }
              return (
                <label key={field} className="flex flex-col gap-1 text-sm">
                  {label}
                  {input.kind === 'select' ? (
                    <select
                      value={countryFields[field] ?? ''}
                      onChange={(e) =>
                        setCountryFields((prev) => ({ ...prev, [field]: e.target.value }))
                      }
                      className="rounded border border-border-light bg-surface-primary p-2"
                    >
                      <option value="">
                        {t('einvoice_clearance.option_unset', { defaultValue: 'Not set' })}
                      </option>
                      {input.options.map((o) => (
                        <option key={o} value={o}>
                          {t(`einvoice_clearance.option.${field}.${o}`, { defaultValue: humanise(o) })}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      value={countryFields[field] ?? ''}
                      onChange={(e) =>
                        setCountryFields((prev) => ({ ...prev, [field]: e.target.value }))
                      }
                      maxLength={255}
                      className="rounded border border-border-light bg-surface-primary p-2"
                    />
                  )}
                </label>
              );
            })}
          </div>
        </fieldset>
      )}

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!ready || pending}>
          {t('einvoice_clearance.document_create', { defaultValue: 'Prepare document' })}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>

      <p className="text-xs text-content-tertiary">
        {t('einvoice_clearance.document_create_hint', {
          defaultValue:
            'Preparing a document sends nothing. It is checked against the country rules on the way in, and what is missing is listed here.',
        })}
      </p>
    </form>
  );
}
