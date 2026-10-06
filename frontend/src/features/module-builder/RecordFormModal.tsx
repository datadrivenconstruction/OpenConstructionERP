// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The form for one record of a module that was built at runtime.
 *
 * There is no compiled screen for a module the user invented an hour ago, so
 * this form is assembled from the specification the module serves. Every input
 * here is chosen by a field's declared type, and the labels are the module
 * author's own words: they are data, not platform strings, so they are rendered
 * as written and never passed through i18n. Only the chrome around them - the
 * buttons, the errors the platform itself raises - is translated.
 *
 * Money and quantities use a text input rather than `type="number"`. The value
 * has to reach the server as the exact decimal string it was typed as, and a
 * numeric input hands its parsing to the browser, which does it differently per
 * locale. Typing something that is not a number is answered by the draft check
 * with a message in the reader's own language, which is more useful than an
 * input that silently blanks itself.
 */
import { useEffect, useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, MessageSquare } from 'lucide-react';
import clsx from 'clsx';

import { Button, Input, WideModal } from '@/shared/ui';
import { CommentThread } from '@/shared/ui/CommentThread';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import {
  createModuleRecord,
  findingsFromError,
  updateModuleRecord,
  type GeneratedRecord,
  type ModuleFieldSpec,
  type ModuleUiSpec,
} from './api';
import {
  NOT_A_NUMBER_CODE,
  REQUIRED_CODE,
  STATUS_KEY,
  blankValues,
  canSubmit,
  evaluateDraft,
  statusStates,
  toCreatePayload,
  toUpdatePayload,
  valuesFromRecord,
  type DraftFinding,
  type FormValues,
} from './fields';
import { LinkPicker } from './LinkPicker';
import { statusVariant } from './StatusBadge';

/**
 * The collaboration module's entity type for a record of a generated module.
 * The server resolves `built.<key>` to the record's project and checks access
 * there, so a comment thread here is exactly as private as the record.
 */
export function commentEntityType(key: string): string {
  return `built.${key}`;
}

export interface RecordFormModalProps {
  open: boolean;
  spec: ModuleUiSpec;
  /** Where the module answers. Comes from the server; never rebuilt from the key. */
  basePath: string;
  /** Required when the entity is project-scoped, ignored otherwise. */
  projectId: string | null;
  /** The record being edited, or null to create one. */
  record: GeneratedRecord | null;
  onClose: () => void;
  onSaved: () => void;
}

export function RecordFormModal({
  open,
  spec,
  basePath,
  projectId,
  record,
  onClose,
  onSaved,
}: RecordFormModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [values, setValues] = useState<FormValues>(() => blankValues(spec));
  const [saving, setSaving] = useState(false);
  /** Findings the server sent back. Cleared as soon as the user edits anything. */
  const [refused, setRefused] = useState<DraftFinding[]>([]);
  const [showAll, setShowAll] = useState(false);

  // Reopening the form must not show the previous record's values, and editing
  // a different row must not keep the last one's.
  useEffect(() => {
    if (!open) return;
    setValues(record ? valuesFromRecord(spec, record) : blankValues(spec));
    setRefused([]);
    setShowAll(false);
  }, [open, record, spec]);

  const drafted = useMemo(() => evaluateDraft(spec, values), [spec, values]);
  const findings = useMemo(() => [...drafted, ...refused], [drafted, refused]);
  const submittable = canSubmit(drafted);
  const states = statusStates(spec);
  const statusLabelId = useId();

  const set = (name: string, value: string | boolean) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setRefused([]);
  };

  /**
   * Wording for a finding the platform raised. A finding from one of the
   * module's own rules already carries its author's message.
   */
  const messageFor = (finding: DraftFinding): string => {
    if (finding.message) return finding.message;
    if (finding.code === REQUIRED_CODE) {
      return t('runtime_module.field_required', { defaultValue: 'This cannot be left empty.' });
    }
    if (finding.code === NOT_A_NUMBER_CODE) {
      return t('runtime_module.field_not_a_number', {
        defaultValue: 'Enter a number, using a dot for the decimal point.',
      });
    }
    return finding.code;
  };

  // Nothing is marked wrong until the user has tried to save or the server has
  // refused: a form that turns red the moment it opens is telling the user off
  // for not having filled it in yet.
  const errorsFor = (name: string) =>
    (showAll ? findings : refused).filter((f) => f.field === name);

  const handleSubmit = async () => {
    if (!submittable) {
      // Reveal everything at once rather than one field at a time: the point of
      // checking before the round trip is that the whole list is visible.
      setShowAll(true);
      return;
    }
    setSaving(true);
    try {
      if (record) {
        const payload = toUpdatePayload(spec, values, record);
        // Nothing changed. Saving would still be a write and still bump
        // updated_at, so treat it as a close.
        if (Object.keys(payload).length === 0) {
          onClose();
          return;
        }
        await updateModuleRecord(basePath, record.id, payload);
      } else {
        await createModuleRecord(basePath, toCreatePayload(spec, values, projectId));
      }
      addToast({
        type: 'success',
        title: record
          ? t('common.saved', { defaultValue: 'Saved' })
          : t('common.created', { defaultValue: 'Created' }),
      });
      onSaved();
    } catch (err) {
      // A 422 from the module's own validator names the rules that refused the
      // write. Those are the author's messages and are shown on the fields they
      // belong to; anything else falls back to one toast.
      const fromModule = err instanceof ApiError ? findingsFromError(err.body) : [];
      if (fromModule.length > 0) {
        setRefused(
          fromModule.map((f) => ({
            field: f.field,
            code: f.code,
            message: f.message,
            severity: 'error' as const,
          })),
        );
        setShowAll(true);
      } else {
        addToast({ type: 'error', title: getErrorMessage(err) });
      }
    } finally {
      setSaving(false);
    }
  };

  const title = record
    ? t('runtime_module.edit_record', {
        entity: spec.entity.display_name,
        defaultValue: 'Edit {{entity}}',
      })
    : t('runtime_module.new_record', {
        entity: spec.entity.display_name,
        defaultValue: 'New {{entity}}',
      });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={title}
      subtitle={spec.display_name}
      busy={saving}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => void handleSubmit()}
            loading={saving}
            data-testid="runtime-module-save"
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {spec.entity.project_scoped && !projectId && (
          <p className="flex items-start gap-2 rounded-lg bg-semantic-warning-bg px-3 py-2 text-xs text-semantic-warning">
            <AlertTriangle size={14} className="mt-px shrink-0" />
            {t('runtime_module.needs_project', {
              defaultValue: 'These records belong to a project. Choose one before saving.',
            })}
          </p>
        )}
        {states.length > 0 && (
          <div>
            <p id={statusLabelId} className="mb-1.5 text-sm font-medium text-content-secondary">
              {t('runtime_module.status', { defaultValue: 'Status' })}
            </p>
            {/* All stages in one row of buttons rather than a dropdown: moving
                a record on is the most common edit, and this makes it one
                click. The stage names are the module author's own. */}
            <div
              role="radiogroup"
              aria-labelledby={statusLabelId}
              className="flex flex-wrap gap-1.5"
              data-testid="runtime-module-status-picker"
            >
              {states.map((state) => {
                const on = values[STATUS_KEY] === state.code;
                const variant = statusVariant(states, state.code);
                return (
                  <button
                    key={state.code}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    onClick={() => set(STATUS_KEY, state.code)}
                    className={clsx(
                      'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                      !on && 'border-border-light text-content-secondary hover:bg-surface-secondary',
                      on && variant === 'success' && 'border-semantic-success bg-semantic-success-bg text-semantic-success',
                      on && variant === 'blue' && 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text',
                      on && variant === 'neutral' && 'border-content-tertiary bg-surface-secondary text-content-primary',
                    )}
                  >
                    {state.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {spec.entity.fields.map((field) => (
          <FieldInput
            key={field.name}
            field={field}
            value={values[field.name] ?? ''}
            errors={errorsFor(field.name).map(messageFor)}
            onChange={(next) => set(field.name, next)}
            projectId={projectId}
          />
        ))}

        {/* Only on a record that exists: a comment needs something to hang on,
            and a thread on a form that is never saved would be lost with it. */}
        {record && spec.features?.comments && (
          <section
            className="border-t border-border-light pt-4"
            data-testid="runtime-module-comments"
          >
            <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-content-primary">
              <MessageSquare size={14} className="text-content-tertiary" />
              {t('runtime_module.comments', { defaultValue: 'Comments' })}
            </h3>
            <CommentThread entityType={commentEntityType(spec.key)} entityId={record.id} />
          </section>
        )}
      </div>
    </WideModal>
  );
}

interface FieldInputProps {
  field: ModuleFieldSpec;
  value: string | boolean;
  errors: string[];
  onChange: (value: string | boolean) => void;
  /** The record's project; a link picker searches inside it. */
  projectId: string | null;
}

/**
 * One input, chosen by the field's declared type.
 *
 * The label and the help text are the module author's own words and are
 * rendered as they were written.
 */
function FieldInput({ field, value, errors, onChange, projectId }: FieldInputProps) {
  const { t } = useTranslation();
  const id = `runtime-field-${field.name}`;
  const error = errors[0];
  const text = typeof value === 'string' ? value : '';

  if (field.type === 'link' && field.target) {
    return (
      <div>
        <label htmlFor={id} className="mb-1 block text-sm font-medium text-content-secondary">
          {field.label}
          {field.required && <span className="ml-0.5 text-semantic-error">*</span>}
        </label>
        <LinkPicker
          id={id}
          target={field.target}
          projectId={projectId}
          value={text}
          onChange={onChange}
          label={field.label}
          invalid={Boolean(error)}
        />
        <FieldFooter help={field.help_text} error={error} />
      </div>
    );
  }

  if (field.type === 'boolean') {
    return (
      <label className="flex items-start gap-2.5" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-border-light text-oe-blue focus:ring-oe-blue/40"
        />
        <span className="min-w-0">
          <span className="block text-sm text-content-primary">{field.label}</span>
          {field.help_text && (
            <span className="block text-xs text-content-tertiary">{field.help_text}</span>
          )}
        </span>
      </label>
    );
  }

  if (field.type === 'select') {
    return (
      <div>
        <label htmlFor={id} className="mb-1 block text-sm font-medium text-content-secondary">
          {field.label}
          {field.required && <span className="ml-0.5 text-semantic-error">*</span>}
        </label>
        <select
          id={id}
          value={text}
          onChange={(e) => onChange(e.target.value)}
          className={clsx(
            'w-full rounded-lg border bg-surface-primary px-3 py-2 text-sm text-content-primary',
            'focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
            error ? 'border-semantic-error' : 'border-border-light',
          )}
        >
          <option value="">{t('common.select', { defaultValue: 'Select…' })}</option>
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <FieldFooter help={field.help_text} error={error} />
      </div>
    );
  }

  if (field.type === 'long_text') {
    return (
      <div>
        <label htmlFor={id} className="mb-1 block text-sm font-medium text-content-secondary">
          {field.label}
          {field.required && <span className="ml-0.5 text-semantic-error">*</span>}
        </label>
        <textarea
          id={id}
          value={text}
          rows={4}
          onChange={(e) => onChange(e.target.value)}
          className={clsx(
            'w-full rounded-lg border bg-surface-primary px-3 py-2 text-sm text-content-primary',
            'focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
            error ? 'border-semantic-error' : 'border-border-light',
          )}
        />
        <FieldFooter help={field.help_text} error={error} />
      </div>
    );
  }

  // The remaining types are all one-line inputs; only the keyboard differs.
  const inputType =
    field.type === 'date' ? 'date' : field.type === 'datetime' ? 'datetime-local' : field.type === 'integer' ? 'number' : 'text';

  return (
    <Input
      id={id}
      label={field.required ? `${field.label} *` : field.label}
      hint={field.help_text || undefined}
      error={error}
      type={inputType}
      step={field.type === 'integer' ? 1 : undefined}
      inputMode={field.type === 'money' || field.type === 'number' ? 'decimal' : undefined}
      suffix={field.unit || undefined}
      value={text}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function FieldFooter({ help, error }: { help: string; error?: string }) {
  if (error) return <p className="mt-1 text-xs text-semantic-error">{error}</p>;
  if (help) return <p className="mt-1 text-xs text-content-tertiary">{help}</p>;
  return null;
}
