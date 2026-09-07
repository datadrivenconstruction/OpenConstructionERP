// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The form that registers a legal entity with one country platform.
 *
 * The module's first step had no way in. The page explained that a registration
 * has to exist before anything else can happen, the list below it said there
 * were none, and there was no control anywhere that would make one. Everything
 * downstream was therefore unreachable on a new installation, which is what a
 * reader means when they say they cannot tell what to do here.
 *
 * The form is built from /meta rather than from a list in this file. A country
 * names the registration fields it needs in `profile_fields`, so Mexico asks
 * for a certificate reference, Germany asks for a network participant id, and
 * neither is shown a box the other one needs. A country added to the backend
 * registry appears here with the right fields and no frontend change.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { compareNames } from '@/shared/lib/collator';

import type { ClearanceMeta, ClearanceProfile, CountryRegime, ProfileWriteBody } from './api';

/** The three registration fields any country can ask for, in a fixed order. */
const PROFILE_FIELD_ORDER = [
  'tax_registration_id',
  'network_participant_id',
  'certificate_reference',
] as const;

type ProfileField = (typeof PROFILE_FIELD_ORDER)[number];

function isProfileField(name: string): name is ProfileField {
  return (PROFILE_FIELD_ORDER as readonly string[]).includes(name);
}

export function ClearanceRegistrationForm({
  meta,
  initial,
  pending,
  onSubmit,
  onCancel,
}: {
  meta: ClearanceMeta | undefined;
  /** Null creates, a profile edits. Country and company are still editable. */
  initial: ClearanceProfile | null;
  pending: boolean;
  onSubmit: (body: ProfileWriteBody) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();

  const [companyKey, setCompanyKey] = useState(initial?.company_key ?? '');
  const [country, setCountry] = useState(initial?.country ?? '');
  const [taxId, setTaxId] = useState(initial?.tax_registration_id ?? '');
  const [participantId, setParticipantId] = useState(initial?.network_participant_id ?? '');
  const [certificate, setCertificate] = useState(initial?.certificate_reference ?? '');
  const [adapterKey, setAdapterKey] = useState(initial?.adapter_key ?? '');
  // Defaults to a rehearsal. Turning this off makes the next submission a real
  // filing with a tax authority, so it is a deliberate act and never a default.
  const [sandbox, setSandbox] = useState(initial ? initial.sandbox : true);
  const [isActive, setIsActive] = useState(initial ? initial.is_active : true);
  const [notes, setNotes] = useState(initial?.notes ?? '');

  const countries = meta?.countries ?? [];

  /** Countries grouped by regime, so the list reads as three kinds of thing. */
  const grouped = useMemo(() => {
    const byRegime = new Map<string, CountryRegime[]>();
    for (const entry of countries) {
      const list = byRegime.get(entry.regime) ?? [];
      list.push(entry);
      byRegime.set(entry.regime, list);
    }
    for (const list of byRegime.values()) {
      list.sort((a, b) => compareNames(a.label, b.label));
    }
    return [...byRegime.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [countries]);

  const selected = countries.find((c) => c.country === country) ?? null;

  /** Only the fields this country actually registers with. */
  const fields = useMemo<ProfileField[]>(() => {
    const wanted = (selected?.profile_fields ?? []).filter(isProfileField);
    return PROFILE_FIELD_ORDER.filter((f) => wanted.includes(f));
  }, [selected]);

  /** Adapters that serve this country. `*` serves every one. */
  const adapters = useMemo(
    () =>
      (meta?.adapters ?? []).filter(
        (a) => a.countries.includes('*') || (country !== '' && a.countries.includes(country)),
      ),
    [meta, country],
  );

  const values: Record<ProfileField, string> = {
    tax_registration_id: taxId,
    network_participant_id: participantId,
    certificate_reference: certificate,
  };
  const setters: Record<ProfileField, (v: string) => void> = {
    tax_registration_id: setTaxId,
    network_participant_id: setParticipantId,
    certificate_reference: setCertificate,
  };
  const fieldLabels: Record<ProfileField, string> = {
    tax_registration_id: t('einvoice_clearance.field_tax_registration_id', {
      defaultValue: 'Tax registration number',
    }),
    network_participant_id: t('einvoice_clearance.field_network_participant_id', {
      defaultValue: 'Network participant id',
    }),
    certificate_reference: t('einvoice_clearance.field_certificate_reference', {
      defaultValue: 'Certificate reference',
    }),
  };

  // Every field the country names is required. A registration missing one is
  // accepted by the server and then refused by the platform at submission time,
  // which is the worst place to find out.
  const ready =
    companyKey.trim().length > 0 &&
    country !== '' &&
    fields.every((f) => values[f].trim().length > 0);

  return (
    <form
      className="space-y-3 rounded-lg border border-border-light p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready || pending) return;
        onSubmit({
          company_key: companyKey.trim(),
          country,
          tax_registration_id: taxId.trim(),
          network_participant_id: participantId.trim(),
          certificate_reference: certificate.trim(),
          adapter_key: adapterKey,
          sandbox,
          is_active: isActive,
          notes: notes.trim(),
        });
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        {t('einvoice_clearance.field_company_key', { defaultValue: 'Legal entity' })}
        <input
          value={companyKey}
          onChange={(e) => setCompanyKey(e.target.value)}
          maxLength={120}
          required
          className="rounded border border-border-light bg-surface-primary p-2"
          placeholder={t('einvoice_clearance.field_company_key_hint', {
            defaultValue: 'The entity that issues the invoices, as your finance records name it',
          })}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        {t('einvoice_clearance.field_country', { defaultValue: 'Country platform' })}
        <select
          value={country}
          onChange={(e) => {
            setCountry(e.target.value);
            setAdapterKey('');
          }}
          required
          className="rounded border border-border-light bg-surface-primary p-2"
        >
          <option value="">
            {t('einvoice_clearance.field_country_none', { defaultValue: 'Choose a country' })}
          </option>
          {grouped.map(([regime, entries]) => (
            <optgroup
              key={regime}
              label={t(`einvoice_clearance.regime.${regime}`, { defaultValue: regime })}
            >
              {entries.map((entry) => (
                <option key={entry.country} value={entry.country}>
                  {entry.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>

      {/* What this country does, said before anything is typed rather than
          discovered at submission time. The three regimes mean three different
          things by acceptance and the reader should not have to know which. */}
      {selected && (
        <div className="rounded border border-border-light bg-surface-secondary p-2 text-xs text-content-tertiary">
          <p>
            <span className="font-medium text-content-secondary">{selected.platform}</span>
            {' · '}
            {t('einvoice_clearance.returns_identifier', {
              defaultValue: 'Returns: {{identifier}}',
              identifier: selected.identifier_label,
            })}
          </p>
          <p className="mt-1">
            {selected.is_cancellable
              ? selected.cancellation_window_days === null
                ? t('einvoice_clearance.cancellable_no_window', {
                    defaultValue: 'A sent document can be withdrawn. Corrections: {{mechanism}}',
                    mechanism: selected.correction_mechanism,
                  })
                : /* `count`, not `days`: this is a real quantity, and i18next
                     resolves plural forms off `count` and nothing else. Named
                     anything else it would print one English form to every
                     language that needs more than one. */
                  t('einvoice_clearance.cancellable_window', {
                    defaultValue:
                      'A sent document can be withdrawn within {{count}} day. Corrections: {{mechanism}}',
                    count: selected.cancellation_window_days,
                    mechanism: selected.correction_mechanism,
                  })
              : /* This key already exists, translated into every locale, and it
                   already says exactly this. It interpolates `platform` as well
                   as `mechanism`, so both have to be passed: reusing the name
                   with only half the variables would print the word "undefined"
                   into forty-one languages. Reusing beats minting a near-copy. */
                t('einvoice_clearance.not_cancellable', {
                  platform: selected.platform,
                  mechanism: selected.correction_mechanism,
                })}
          </p>
          {selected.notes && <p className="mt-1">{selected.notes}</p>}
        </div>
      )}

      {fields.map((field) => (
        <label key={field} className="flex flex-col gap-1 text-sm">
          {fieldLabels[field]}
          <input
            value={values[field]}
            onChange={(e) => setters[field](e.target.value)}
            maxLength={255}
            required
            className="rounded border border-border-light bg-surface-primary p-2 font-mono"
          />
        </label>
      ))}

      <label className="flex flex-col gap-1 text-sm">
        {t('einvoice_clearance.field_adapter', { defaultValue: 'Adapter' })}
        <select
          value={adapterKey}
          onChange={(e) => setAdapterKey(e.target.value)}
          className="rounded border border-border-light bg-surface-primary p-2"
        >
          <option value="">
            {t('einvoice_clearance.field_adapter_none', { defaultValue: 'None' })}
          </option>
          {adapters.map((a) => (
            <option key={a.key} value={a.key}>
              {a.label}
            </option>
          ))}
        </select>
        {/* The list already says "No adapter" in red on a saved registration.
            Say why here, while it can still be chosen. */}
        {adapterKey === '' && (
          <span className="text-xs text-content-tertiary">
            {t('einvoice_clearance.field_adapter_hint', {
              defaultValue:
                'Without one a document under this registration can be prepared and checked, but not sent.',
            })}
          </span>
        )}
      </label>

      <label className="flex items-start gap-2 rounded border border-border-light p-2 text-sm">
        <input
          type="checkbox"
          checked={sandbox}
          onChange={(e) => setSandbox(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          {t('einvoice_clearance.field_sandbox', { defaultValue: 'Rehearsal only (sandbox)' })}
          <span className="mt-0.5 block text-xs text-content-tertiary">
            {t('einvoice_clearance.field_sandbox_hint', {
              defaultValue:
                'Leave this on until the registration is proven. With it off, sending a document is a real filing with the authority and cannot be taken back.',
            })}
          </span>
        </span>
      </label>

      {!sandbox && (
        <p className="flex items-start gap-2 rounded border border-semantic-warning bg-semantic-warning-bg p-2 text-xs">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {t('einvoice_clearance.live_warning', {
            defaultValue:
              'This registration will file for real. Anything submitted under it goes to the authority itself.',
          })}
        </p>
      )}

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={isActive}
          onChange={(e) => setIsActive(e.target.checked)}
        />
        {t('einvoice_clearance.field_is_active', { defaultValue: 'Active' })}
      </label>

      <label className="flex flex-col gap-1 text-sm">
        {t('einvoice_clearance.field_notes', { defaultValue: 'Notes' })}
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          maxLength={1000}
          rows={2}
          className="rounded border border-border-light bg-surface-primary p-2"
        />
      </label>

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!ready || pending}>
          {initial
            ? t('einvoice_clearance.registration_save', { defaultValue: 'Save registration' })
            : t('einvoice_clearance.registration_create', { defaultValue: 'Register' })}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </form>
  );
}
