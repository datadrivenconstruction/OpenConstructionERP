// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Create / edit form for one requirement.
 *
 * A requirement is what makes a *missing* credential detectable: the register
 * on its own can only report what someone bothered to enter. So the two fields
 * that carry consequence - whether a gap stops work, and how long a lapse is
 * tolerated - are given their own section and spelled out in words rather than
 * left as a bare checkbox and a number.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Ban, Info } from 'lucide-react';
import clsx from 'clsx';
import {
  Button,
  Input,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import {
  APPLIES_TO_ALL,
  type CredentialsMeta,
  type HolderKind,
  type Requirement,
  type RequirementCreatePayload,
} from './api';
import { holderKindLabel, typeLabel } from './labels';

const SELECT_CLASS =
  'h-9 w-full rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer';

const HOLDER_KINDS: HolderKind[] = ['person', 'company'];

export interface RequirementFormModalProps {
  open: boolean;
  onClose: () => void;
  requirement: Requirement | null;
  meta: CredentialsMeta | undefined;
  busy: boolean;
  onSubmit: (payload: Omit<RequirementCreatePayload, 'project_id'>) => void;
}

interface FormState {
  credential_type: string;
  everyone: boolean;
  discipline: string;
  holder_kind: HolderKind;
  is_blocking: boolean;
  grace_days: string;
  description: string;
  is_active: boolean;
}

const EMPTY: FormState = {
  credential_type: '',
  everyone: true,
  discipline: '',
  holder_kind: 'person',
  is_blocking: true,
  grace_days: '0',
  description: '',
  is_active: true,
};

function fromRequirement(r: Requirement): FormState {
  const everyone = r.applies_to === APPLIES_TO_ALL;
  return {
    credential_type: r.credential_type,
    everyone,
    discipline: everyone ? '' : r.applies_to,
    holder_kind: r.holder_kind,
    is_blocking: r.is_blocking,
    grace_days: String(r.grace_days),
    description: r.description,
    is_active: r.is_active,
  };
}

export function RequirementFormModal({
  open,
  onClose,
  requirement,
  meta,
  busy,
  onSubmit,
}: RequirementFormModalProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [touched, setTouched] = useState(false);

  const typeOptions = meta?.credential_types ?? [];

  useEffect(() => {
    if (!open) return;
    setForm(requirement ? fromRequirement(requirement) : EMPTY);
    setTouched(false);
  }, [open, requirement]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const typeError =
    touched && form.credential_type === ''
      ? t('credentials.form.err_type_required', { defaultValue: 'Pick a credential type.' })
      : undefined;
  // `applies_to` is min_length=1 on the API, so an empty discipline would be a
  // 422. It is also meaningless: a rule aimed at nobody in particular.
  const disciplineError =
    touched && !form.everyone && form.discipline.trim() === ''
      ? t('credentials.form.err_discipline_required', {
          defaultValue: 'Name the discipline this applies to, or aim it at everyone.',
        })
      : undefined;

  const invalid =
    form.credential_type === '' || (!form.everyone && form.discipline.trim() === '');

  function handleSubmit() {
    setTouched(true);
    if (invalid) return;
    const graceRaw = Number(form.grace_days.trim());
    onSubmit({
      credential_type: form.credential_type,
      applies_to: form.everyone ? APPLIES_TO_ALL : form.discipline.trim(),
      holder_kind: form.holder_kind,
      is_blocking: form.is_blocking,
      grace_days: Number.isFinite(graceRaw) ? Math.max(0, Math.trunc(graceRaw)) : 0,
      description: form.description.trim(),
      is_active: form.is_active,
    });
  }

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      title={
        requirement
          ? t('credentials.req_form.edit_title', { defaultValue: 'Edit requirement' })
          : t('credentials.req_form.create_title', { defaultValue: 'Add a requirement' })
      }
      subtitle={t('credentials.req_form.subtitle', {
        defaultValue:
          'What this project demands, of whom. Without a requirement a credential nobody entered is simply absent from the register; with one it is reported as missing.',
      })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button onClick={handleSubmit} disabled={busy}>
            {requirement
              ? t('common.save', { defaultValue: 'Save' })
              : t('credentials.req_form.create_submit', { defaultValue: 'Add requirement' })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('credentials.req_form.sec_what', { defaultValue: 'What is required, of whom' })}
        columns={2}
      >
        <WideModalField
          label={t('credentials.field.credential_type', { defaultValue: 'Credential type' })}
          required
          error={typeError}
          htmlFor="req-type"
        >
          <select
            id="req-type"
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
          label={t('credentials.field.holder_kind', { defaultValue: 'Held by' })}
          htmlFor="req-holder-kind"
        >
          <select
            id="req-holder-kind"
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
          label={t('credentials.field.applies_to', { defaultValue: 'Applies to' })}
          htmlFor="req-applies"
        >
          <select
            id="req-applies"
            className={SELECT_CLASS}
            value={form.everyone ? 'all' : 'discipline'}
            onChange={(e) => set('everyone', e.target.value === 'all')}
          >
            <option value="all">
              {t('credentials.req_form.applies_all', { defaultValue: 'Everyone on the register' })}
            </option>
            <option value="discipline">
              {t('credentials.req_form.applies_discipline', { defaultValue: 'One discipline only' })}
            </option>
          </select>
        </WideModalField>

        <WideModalField
          label={t('credentials.req_form.discipline_label', { defaultValue: 'Which discipline' })}
          error={disciplineError}
          hint={t('credentials.req_form.discipline_hint', {
            defaultValue: "Matched against the discipline written on each holder's credential.",
          })}
          htmlFor="req-discipline"
        >
          <Input
            id="req-discipline"
            value={form.discipline}
            onChange={(e) => set('discipline', e.target.value)}
            disabled={form.everyone}
            maxLength={64}
            autoComplete="off"
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('credentials.req_form.sec_consequence', { defaultValue: 'What a gap means' })}
        description={t('credentials.req_form.sec_consequence_desc', {
          defaultValue:
            'This is the difference between a warning and someone being sent home, so it is worth being deliberate about.',
        })}
        columns={1}
      >
        <WideModalField>
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => set('is_blocking', true)}
              aria-pressed={form.is_blocking}
              className={clsx(
                'rounded-lg border p-3 text-start transition-colors',
                form.is_blocking
                  ? 'border-semantic-error bg-semantic-error-bg'
                  : 'border-border-light bg-surface-primary hover:bg-surface-secondary',
              )}
            >
              <span className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
                <Ban size={14} className="text-semantic-error" />
                {t('credentials.req_form.blocking_title', { defaultValue: 'Stops work' })}
              </span>
              <span className="mt-1 block text-2xs leading-relaxed text-content-tertiary">
                {t('credentials.req_form.blocking_desc', {
                  defaultValue:
                    'A holder without it is reported as blocked and should not be on site until it is in place.',
                })}
              </span>
            </button>
            <button
              type="button"
              onClick={() => set('is_blocking', false)}
              aria-pressed={!form.is_blocking}
              className={clsx(
                'rounded-lg border p-3 text-start transition-colors',
                !form.is_blocking
                  ? 'border-oe-blue bg-oe-blue-subtle'
                  : 'border-border-light bg-surface-primary hover:bg-surface-secondary',
              )}
            >
              <span className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
                <Info size={14} className="text-oe-blue" />
                {t('credentials.req_form.advisory_title', { defaultValue: 'Worth knowing' })}
              </span>
              <span className="mt-1 block text-2xs leading-relaxed text-content-tertiary">
                {t('credentials.req_form.advisory_desc', {
                  defaultValue:
                    'A gap is listed and chased, but nobody is stopped from working over it.',
                })}
              </span>
            </button>
          </div>
        </WideModalField>
      </WideModalSection>

      <WideModalSection columns={2}>
        <WideModalField
          label={t('credentials.field.grace_days', { defaultValue: 'Grace period, days' })}
          hint={t('credentials.req_form.grace_hint', {
            defaultValue:
              'How long a lapse is tolerated after the expiry date. Within it the gap is reported but does not stop work.',
          })}
          htmlFor="req-grace"
        >
          <Input
            id="req-grace"
            type="number"
            min={0}
            max={365}
            value={form.grace_days}
            onChange={(e) => set('grace_days', e.target.value)}
          />
        </WideModalField>

        <WideModalField
          label={t('credentials.field.is_active', { defaultValue: 'In force' })}
          hint={t('credentials.req_form.active_hint', {
            defaultValue: 'Turn off to park a rule without deleting the history behind it.',
          })}
        >
          <label className="mt-1 inline-flex cursor-pointer items-center gap-2 text-sm text-content-secondary">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => set('is_active', e.target.checked)}
              className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
            />
            {t('credentials.req_form.active_label', { defaultValue: 'This requirement applies now' })}
          </label>
        </WideModalField>

        <WideModalField
          label={t('credentials.field.description', { defaultValue: 'Why it is required' })}
          span={2}
          htmlFor="req-description"
        >
          <textarea
            id="req-description"
            rows={3}
            maxLength={10000}
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
            className="w-full rounded-md border border-border bg-surface-primary px-2.5 py-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
