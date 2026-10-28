// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Create / edit form for one credential.
 *
 * The type and status pickers are built from the ``/meta`` payload rather than
 * from a list in this file, so they cannot drift from the server's whitelist
 * and the option labels arrive already translated.
 *
 * The status picker offers only the three statuses a caller may actually set.
 * `expiring_soon` and `expired` are derived from the validity window on every
 * read, so offering them here would produce a 422 and, worse, suggest that a
 * lapse is something you declare rather than something the calendar decides.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Button,
  Input,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import {
  MANUAL_STATUSES,
  type Credential,
  type CredentialCreatePayload,
  type CredentialsMeta,
  type HolderKind,
  type ManualCredentialStatus,
} from './api';
import { holderKindLabel, statusLabel, typeLabel } from './labels';

const SELECT_CLASS =
  'h-9 w-full rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer';

const HOLDER_KINDS: HolderKind[] = ['person', 'company'];

export interface CredentialFormModalProps {
  open: boolean;
  onClose: () => void;
  /** Null when creating; the record being amended otherwise. */
  credential: Credential | null;
  meta: CredentialsMeta | undefined;
  busy: boolean;
  onSubmit: (payload: Omit<CredentialCreatePayload, 'project_id'>) => void;
}

interface FormState {
  holder_name: string;
  holder_kind: HolderKind;
  credential_type: string;
  discipline: string;
  authority: string;
  identifier: string;
  jurisdiction: string;
  issued_at: string;
  valid_until: string;
  notify_days_before: string;
  notification_obligation_days: string;
  notification_trigger: string;
  status: '' | ManualCredentialStatus;
  notes: string;
}

const EMPTY: FormState = {
  holder_name: '',
  holder_kind: 'person',
  credential_type: '',
  discipline: '',
  authority: '',
  identifier: '',
  jurisdiction: '',
  issued_at: '',
  valid_until: '',
  notify_days_before: '30',
  notification_obligation_days: '',
  notification_trigger: '',
  status: '',
  notes: '',
};

/** A stored status the caller may not re-send (it is derived) collapses to ''. */
function settableStatus(status: string): '' | ManualCredentialStatus {
  return (MANUAL_STATUSES as string[]).includes(status) ? (status as ManualCredentialStatus) : '';
}

function fromCredential(c: Credential): FormState {
  return {
    holder_name: c.holder_name,
    holder_kind: c.holder_kind,
    credential_type: c.credential_type,
    discipline: c.discipline ?? '',
    authority: c.authority ?? '',
    identifier: c.identifier ?? '',
    jurisdiction: c.jurisdiction ?? '',
    issued_at: c.issued_at ?? '',
    valid_until: c.valid_until ?? '',
    notify_days_before: String(c.notify_days_before),
    notification_obligation_days:
      c.notification_obligation_days === null ? '' : String(c.notification_obligation_days),
    notification_trigger: c.notification_trigger ?? '',
    status: settableStatus(c.status),
    notes: c.notes,
  };
}

/** Optional free text: '' means "not recorded", which the API takes as null. */
function orNull(value: string): string | null {
  const v = value.trim();
  return v === '' ? null : v;
}

function intOrNull(value: string): number | null {
  const v = value.trim();
  if (v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}

export function CredentialFormModal({
  open,
  onClose,
  credential,
  meta,
  busy,
  onSubmit,
}: CredentialFormModalProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [touched, setTouched] = useState(false);

  const typeOptions = meta?.credential_types ?? [];
  // Only the three writable statuses, labelled with the server's own words.
  const statusOptions = useMemo(
    () =>
      (meta?.statuses ?? []).filter((s) =>
        (MANUAL_STATUSES as string[]).includes(s.code),
      ),
    [meta],
  );

  // Reset whenever the modal is (re-)opened, so a cancelled edit does not leak
  // into the next one.
  useEffect(() => {
    if (!open) return;
    setForm(credential ? fromCredential(credential) : EMPTY);
    setTouched(false);
  }, [open, credential]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const nameError =
    touched && form.holder_name.trim() === ''
      ? t('credentials.form.err_holder_required', { defaultValue: 'Give the holder a name.' })
      : undefined;
  const typeError =
    touched && form.credential_type === ''
      ? t('credentials.form.err_type_required', { defaultValue: 'Pick a credential type.' })
      : undefined;
  // Mirrors the server's own check, so the user sees it before the round trip.
  const dateError =
    form.issued_at !== '' && form.valid_until !== '' && form.valid_until < form.issued_at
      ? t('credentials.form.err_dates', {
          defaultValue: 'The valid-until date cannot be before the issue date.',
        })
      : undefined;

  const invalid =
    form.holder_name.trim() === '' || form.credential_type === '' || dateError !== undefined;

  function handleSubmit() {
    setTouched(true);
    if (invalid) return;
    onSubmit({
      holder_name: form.holder_name.trim(),
      holder_kind: form.holder_kind,
      credential_type: form.credential_type,
      discipline: orNull(form.discipline),
      authority: orNull(form.authority),
      identifier: orNull(form.identifier),
      jurisdiction: orNull(form.jurisdiction),
      issued_at: orNull(form.issued_at),
      valid_until: orNull(form.valid_until),
      notify_days_before: intOrNull(form.notify_days_before) ?? 30,
      notification_obligation_days: intOrNull(form.notification_obligation_days),
      notification_trigger: orNull(form.notification_trigger),
      status: form.status === '' ? null : form.status,
      notes: form.notes.trim(),
    });
  }

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      title={
        credential
          ? t('credentials.form.edit_title', { defaultValue: 'Edit credential' })
          : t('credentials.form.create_title', { defaultValue: 'Add a credential' })
      }
      subtitle={t('credentials.form.subtitle', {
        defaultValue:
          'What the holder holds, who issued it and how long it runs. The register works out expiry from these dates, so a credential with no valid-until date is treated as never expiring.',
      })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button onClick={handleSubmit} disabled={busy}>
            {credential
              ? t('common.save', { defaultValue: 'Save' })
              : t('credentials.form.create_submit', { defaultValue: 'Add credential' })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('credentials.form.sec_holder', { defaultValue: 'Holder' })}
        columns={2}
      >
        <WideModalField
          label={t('credentials.field.holder_name', { defaultValue: 'Holder name' })}
          required
          error={nameError}
          htmlFor="cred-holder-name"
        >
          <Input
            id="cred-holder-name"
            value={form.holder_name}
            onChange={(e) => set('holder_name', e.target.value)}
            maxLength={255}
            autoComplete="off"
          />
        </WideModalField>

        <WideModalField
          label={t('credentials.field.holder_kind', { defaultValue: 'Held by' })}
          htmlFor="cred-holder-kind"
        >
          <select
            id="cred-holder-kind"
            className={SELECT_CLASS}
            value={form.holder_kind}
            onChange={(e) => set('holder_kind', e.target.value as HolderKind)}
          >
            {HOLDER_KINDS.map((k) => (
              <option key={k} value={k}>
                {holderKindLabel(k, t)}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('credentials.field.discipline', { defaultValue: 'Discipline' })}
          hint={t('credentials.form.discipline_hint', {
            defaultValue:
              'A requirement can be aimed at one discipline instead of everyone, and it matches on this word.',
          })}
          htmlFor="cred-discipline"
        >
          <Input
            id="cred-discipline"
            value={form.discipline}
            onChange={(e) => set('discipline', e.target.value)}
            maxLength={64}
            autoComplete="off"
          />
        </WideModalField>

        <WideModalField
          label={t('credentials.field.status', { defaultValue: 'Standing' })}
          hint={t('credentials.form.status_hint', {
            defaultValue: 'Leave on automatic unless the authority has suspended or revoked it.',
          })}
          htmlFor="cred-status"
        >
          <select
            id="cred-status"
            className={SELECT_CLASS}
            value={form.status}
            onChange={(e) => set('status', e.target.value as '' | ManualCredentialStatus)}
          >
            <option value="">
              {t('credentials.form.status_auto', { defaultValue: 'Automatic, from the dates' })}
            </option>
            {statusOptions.map((s) => (
              <option key={s.code} value={s.code}>
                {statusLabel(s.code, meta, t)}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('credentials.form.sec_credential', { defaultValue: 'The credential' })}
        columns={2}
      >
        <WideModalField
          label={t('credentials.field.credential_type', { defaultValue: 'Credential type' })}
          required
          error={typeError}
          htmlFor="cred-type"
        >
          <select
            id="cred-type"
            className={SELECT_CLASS}
            value={form.credential_type}
            onChange={(e) => set('credential_type', e.target.value)}
          >
            <option value="">
              {t('credentials.form.pick_type', { defaultValue: 'Choose a type...' })}
            </option>
            {typeOptions.map((o) => (
              <option key={o.code} value={o.code}>
                {typeLabel(o.code, meta, t)}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('credentials.field.authority', { defaultValue: 'Issuing authority' })}
          htmlFor="cred-authority"
        >
          <Input
            id="cred-authority"
            value={form.authority}
            onChange={(e) => set('authority', e.target.value)}
            maxLength={255}
            autoComplete="off"
          />
        </WideModalField>

        <WideModalField
          label={t('credentials.field.identifier', { defaultValue: 'Reference number' })}
          htmlFor="cred-identifier"
        >
          <Input
            id="cred-identifier"
            value={form.identifier}
            onChange={(e) => set('identifier', e.target.value)}
            maxLength={120}
            autoComplete="off"
          />
        </WideModalField>

        <WideModalField
          label={t('credentials.field.jurisdiction', { defaultValue: 'Jurisdiction' })}
          htmlFor="cred-jurisdiction"
        >
          <Input
            id="cred-jurisdiction"
            value={form.jurisdiction}
            onChange={(e) => set('jurisdiction', e.target.value)}
            maxLength={64}
            autoComplete="off"
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('credentials.form.sec_validity', { defaultValue: 'Validity and reminders' })}
        columns={2}
      >
        <WideModalField
          label={t('credentials.field.issued_at', { defaultValue: 'Issued on' })}
          htmlFor="cred-issued"
        >
          <Input
            id="cred-issued"
            type="date"
            value={form.issued_at}
            onChange={(e) => set('issued_at', e.target.value)}
          />
        </WideModalField>

        <WideModalField
          label={t('credentials.field.valid_until', { defaultValue: 'Valid until' })}
          error={dateError}
          hint={t('credentials.form.valid_until_hint', {
            defaultValue: 'Leave empty for a credential that does not expire.',
          })}
          htmlFor="cred-valid-until"
        >
          <Input
            id="cred-valid-until"
            type="date"
            value={form.valid_until}
            onChange={(e) => set('valid_until', e.target.value)}
          />
        </WideModalField>

        <WideModalField
          label={t('credentials.field.notify_days_before', { defaultValue: 'Warn this many days ahead' })}
          hint={t('credentials.form.notify_hint', {
            defaultValue: 'How early the register starts calling this one expiring soon.',
          })}
          htmlFor="cred-notify"
        >
          <Input
            id="cred-notify"
            type="number"
            min={0}
            max={365}
            value={form.notify_days_before}
            onChange={(e) => set('notify_days_before', e.target.value)}
          />
        </WideModalField>

        <WideModalField
          label={t('credentials.field.notification_obligation_days', {
            defaultValue: 'Authority must be told, days ahead',
          })}
          hint={t('credentials.form.obligation_hint', {
            defaultValue:
              'Only where a rule obliges you to notify someone before this lapses. Leave empty otherwise.',
          })}
          htmlFor="cred-obligation"
        >
          <Input
            id="cred-obligation"
            type="number"
            min={0}
            max={365}
            value={form.notification_obligation_days}
            onChange={(e) => set('notification_obligation_days', e.target.value)}
          />
        </WideModalField>

        <WideModalField
          label={t('credentials.field.notification_trigger', { defaultValue: 'What triggers that notice' })}
          span={2}
          htmlFor="cred-trigger"
        >
          <Input
            id="cred-trigger"
            value={form.notification_trigger}
            onChange={(e) => set('notification_trigger', e.target.value)}
            maxLength={64}
            autoComplete="off"
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection columns={1}>
        <WideModalField
          label={t('credentials.field.notes', { defaultValue: 'Notes' })}
          htmlFor="cred-notes"
        >
          <textarea
            id="cred-notes"
            rows={3}
            maxLength={10000}
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            className="w-full rounded-md border border-border bg-surface-primary px-2.5 py-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
