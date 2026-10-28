// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// FormFiller - fill a submission on a phone or tablet: render the frozen
// template snapshot as inputs, save a draft, complete it (required fields
// enforced), then export to PDF or raise a QA inspection. Read-only once
// completed.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Check,
  X,
  Camera,
  PenLine,
  Download,
  ShieldCheck,
  CircleAlert,
  Loader2,
  Trash2,
} from 'lucide-react';
import clsx from 'clsx';
import { Button, Badge, SideDrawer } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import {
  fetchSubmission,
  updateSubmission,
  completeSubmission,
  deleteSubmission,
  downloadSubmissionPdf,
  createInspectionFromSubmission,
  type AnswerMap,
  type AnswerValue,
  type FieldIssue,
  type FormFieldDef,
  type SignatureValue,
  type SubmissionDetail,
} from './api';
import {
  LAYOUT_TYPES,
  COMPUTED_TYPES,
  missingRequiredKeys,
  requiredCount,
  isAnswerEmpty,
  resolveVisibility,
  computeFormulas,
  applyDefaults,
} from './fieldTypes';
import { getIntlLocale } from '@/shared/lib/formatters';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export interface FormFillerProps {
  open: boolean;
  onClose: () => void;
  submissionId: string | null;
  onChanged?: () => void;
}

export function FormFiller({ open, onClose, submissionId, onChanged }: FormFillerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data: submission, isLoading } = useQuery({
    queryKey: ['forms', 'submission', submissionId],
    queryFn: () => fetchSubmission(submissionId as string),
    enabled: open && !!submissionId,
  });

  const [answers, setAnswers] = useState<AnswerMap>({});
  const [title, setTitle] = useState('');
  const [location, setLocation] = useState('');
  const [invalidKeys, setInvalidKeys] = useState<Set<string>>(new Set());

  // Load answers + meta when a (different) submission arrives; never clobber
  // edits on a background refetch of the same submission.
  useEffect(() => {
    if (submission) {
      // A draft prefills configured defaults for blank fields; a completed
      // submission is shown exactly as stored (no default seeding).
      const base = { ...submission.answers };
      setAnswers(
        submission.status === 'completed'
          ? base
          : applyDefaults(submission.template_snapshot ?? [], base),
      );
      setTitle(submission.title ?? '');
      setLocation(submission.location ?? '');
    }
    setInvalidKeys(new Set());
  }, [submission?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const readOnly = submission?.status === 'completed';
  const fields = submission?.template_snapshot ?? [];

  // Live conditional state + computed formula values, recomputed as answers change.
  const visibility = useMemo(() => resolveVisibility(fields, answers), [fields, answers]);
  const computed = useMemo(() => computeFormulas(fields, answers), [fields, answers]);

  const setAnswer = (key: string, value: AnswerValue) =>
    setAnswers((prev) => ({ ...prev, [key]: value }));

  const missing = useMemo(() => missingRequiredKeys(fields, answers), [fields, answers]);
  const totalRequired = useMemo(() => requiredCount(fields, answers), [fields, answers]);
  const answeredRequired = totalRequired - missing.length;

  const afterChange = () => {
    qc.invalidateQueries({ queryKey: ['forms', 'submissions'] });
    onChanged?.();
  };

  const saveDraftMut = useMutation({
    mutationFn: () => updateSubmission(submissionId as string, { title, location, answers }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('forms.draft_saved', { defaultValue: 'Draft saved' }) });
      afterChange();
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const completeMut = useMutation({
    mutationFn: async () => {
      // Persist the meta + answers first, then run the gated completion so a
      // last-second title/location edit is never lost.
      await updateSubmission(submissionId as string, { title, location, answers });
      return completeSubmission(submissionId as string, answers);
    },
    onSuccess: (updated) => {
      qc.setQueryData(['forms', 'submission', submissionId], updated);
      addToast({ type: 'success', title: t('forms.form_completed', { defaultValue: 'Form completed' }) });
      afterChange();
    },
    onError: (e: unknown) => {
      const issues = extractIssues(e);
      if (issues.length) setInvalidKeys(new Set(issues.map((i) => i.field_key ?? '').filter(Boolean)));
      addToast({
        type: 'error',
        title: t('forms.not_complete', { defaultValue: 'Form is not complete' }),
        message: issues.length ? issues[0]!.message : getErrorMessage(e),
      });
    },
  });

  const onComplete = () => {
    if (missing.length > 0) {
      setInvalidKeys(new Set(missing));
      addToast({
        type: 'warning',
        title: t('forms.missing_required', {
          defaultValue: '{{count}} required field(s) to fill',
          count: missing.length,
        }),
      });
      return;
    }
    completeMut.mutate();
  };

  const exportMut = useMutation({
    mutationFn: () =>
      downloadSubmissionPdf(submissionId as string, `${submission?.submission_number ?? 'form'}.pdf`),
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const inspectionMut = useMutation({
    mutationFn: () => createInspectionFromSubmission(submissionId as string),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['forms', 'submission', submissionId] });
      addToast({
        type: 'success',
        title: res.created
          ? t('forms.inspection_created', { defaultValue: 'Inspection raised' })
          : t('forms.inspection_exists', { defaultValue: 'Inspection already linked' }),
        message: res.inspection_number,
      });
      afterChange();
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const canRaiseInspection =
    readOnly &&
    !submission?.linked_inspection_id &&
    ['inspection', 'quality', 'handover'].includes(submission?.template_category ?? '');

  const busy = saveDraftMut.isPending || completeMut.isPending;

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      busy={busy}
      backdropCloses={false}
      widthClass="max-w-2xl"
      title={submission?.template_name ?? t('forms.form', { defaultValue: 'Form' })}
      subtitle={
        submission
          ? `${submission.submission_number} · v${submission.template_version}`
          : undefined
      }
      headerActions={
        submission ? (
          <div className="flex items-center gap-1.5">
            <StatusBadge status={submission.status} result={submission.result} />
          </div>
        ) : undefined
      }
    >
      {isLoading || !submission ? (
        <div className="flex items-center justify-center p-10 text-content-tertiary">
          <Loader2 className="animate-spin" size={20} />
        </div>
      ) : (
        <div className="flex h-full flex-col">
          {/* Meta */}
          <div className="border-b border-border-light px-4 py-3">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <ReadRow label={t('forms.reference', { defaultValue: 'Reference / title' })}>
                {readOnly ? (
                  submission.title || '-'
                ) : (
                  <input
                    className={clsx(inputCls, 'h-8')}
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder={t('forms.title_ph', { defaultValue: 'e.g. Level 2, grid B/4' })}
                  />
                )}
              </ReadRow>
              <ReadRow label={t('forms.location', { defaultValue: 'Location' })}>
                {readOnly ? (
                  submission.location || '-'
                ) : (
                  <input
                    className={clsx(inputCls, 'h-8')}
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                    placeholder={t('forms.location_ph', { defaultValue: 'Where on site?' })}
                  />
                )}
              </ReadRow>
            </div>
          </div>

          {/* Completion meter */}
          {!readOnly && totalRequired > 0 && (
            <div className="border-b border-border-light px-4 py-2">
              <div className="mb-1 flex items-center justify-between text-xs text-content-tertiary">
                <span>{t('forms.required_progress', { defaultValue: 'Required fields' })}</span>
                <span>
                  {answeredRequired}/{totalRequired}
                </span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-tertiary">
                <div
                  className={clsx(
                    'h-full rounded-full transition-all',
                    missing.length === 0 ? 'bg-semantic-success' : 'bg-oe-blue',
                  )}
                  style={{ width: `${totalRequired ? (answeredRequired / totalRequired) * 100 : 0}%` }}
                />
              </div>
            </div>
          )}

          {/* Fields */}
          <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
            {fields.map((field, idx) => {
              const state = field.key ? visibility[field.key] : undefined;
              if (state && !state.visible) return null;
              const isFormula = COMPUTED_TYPES.has(field.type);
              const shownValue = isFormula ? (computed[field.key] ?? null) : answers[field.key] ?? null;
              return (
                <FieldInput
                  key={field.key || idx}
                  field={field}
                  value={shownValue}
                  requiredOverride={state?.required}
                  readOnly={readOnly}
                  invalid={invalidKeys.has(field.key)}
                  onChange={(v) => setAnswer(field.key, v)}
                />
              );
            })}
          </div>

          {/* Footer actions */}
          <div className="sticky bottom-0 border-t border-border-light bg-surface-elevated px-4 py-3">
            {readOnly ? (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  icon={<Download size={15} />}
                  loading={exportMut.isPending}
                  onClick={() => exportMut.mutate()}
                >
                  {t('forms.export_pdf', { defaultValue: 'Export PDF' })}
                </Button>
                {canRaiseInspection && (
                  <Button
                    variant="secondary"
                    icon={<ShieldCheck size={15} />}
                    loading={inspectionMut.isPending}
                    onClick={() => inspectionMut.mutate()}
                  >
                    {t('forms.raise_inspection', { defaultValue: 'Raise inspection' })}
                  </Button>
                )}
                {submission.linked_inspection_id && (
                  <Badge variant="blue" size="sm">
                    {t('forms.inspection_linked', { defaultValue: 'Inspection linked' })}
                  </Badge>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-between gap-2">
                <Button
                  variant="secondary"
                  onClick={() => saveDraftMut.mutate()}
                  loading={saveDraftMut.isPending}
                >
                  {t('forms.save_draft', { defaultValue: 'Save draft' })}
                </Button>
                <Button
                  icon={<Check size={15} />}
                  loading={completeMut.isPending}
                  onClick={onComplete}
                >
                  {t('forms.complete', { defaultValue: 'Complete' })}
                </Button>
              </div>
            )}
          </div>
        </div>
      )}
    </SideDrawer>
  );
}

/* -- Field renderers ------------------------------------------------------- */

export interface FieldInputProps {
  field: FormFieldDef;
  value: AnswerValue;
  readOnly?: boolean;
  invalid?: boolean;
  /** Live required state (from conditional logic); falls back to field.required. */
  requiredOverride?: boolean;
  onChange: (value: AnswerValue) => void;
}

function FieldInput({ field, value, readOnly, invalid, requiredOverride, onChange }: FieldInputProps) {
  const { t } = useTranslation();

  if (LAYOUT_TYPES.has(field.type)) {
    return (
      <div className="pt-2">
        <h3 className="border-b border-border-light pb-1 text-sm font-semibold text-content-primary">
          {field.label}
        </h3>
      </div>
    );
  }

  const required = requiredOverride ?? field.required;
  const showMissing = invalid && required && isAnswerEmpty(field.type, value);

  return (
    <div>
      <label className="mb-1 flex items-start gap-1 text-sm font-medium text-content-secondary">
        <span>{field.label}</span>
        {required && <span className="text-semantic-error">*</span>}
      </label>
      {field.help_text && <p className="mb-1.5 text-xs text-content-tertiary">{field.help_text}</p>}

      <FieldControl field={field} value={value} readOnly={readOnly} onChange={onChange} />

      {showMissing && (
        <p className="mt-1 inline-flex items-center gap-1 text-xs text-semantic-error">
          <CircleAlert size={12} />
          {t('forms.this_required', { defaultValue: 'This field is required.' })}
        </p>
      )}
    </div>
  );
}

// Exported so the compact checklist runner can reuse the exact field controls
// (a lighter FormFiller) without duplicating every field type. Rendering is
// identical; only the surrounding layout differs.
export function FieldControl({ field, value, readOnly, onChange }: FieldInputProps) {
  const { t } = useTranslation();
  const disabled = !!readOnly;

  switch (field.type) {
    case 'short_text':
      return (
        <input
          className={inputCls}
          disabled={disabled}
          placeholder={field.placeholder ?? undefined}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case 'long_text':
      return (
        <textarea
          className={clsx(inputCls, 'h-auto min-h-[80px] py-2')}
          disabled={disabled}
          placeholder={field.placeholder ?? undefined}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case 'number':
      return (
        <div className="flex items-center gap-2">
          <input
            type="number"
            inputMode="decimal"
            className={inputCls}
            disabled={disabled}
            placeholder={field.placeholder ?? undefined}
            min={field.min ?? undefined}
            max={field.max ?? undefined}
            value={typeof value === 'number' || typeof value === 'string' ? String(value) : ''}
            onChange={(e) => onChange(e.target.value)}
          />
          {field.unit && <span className="shrink-0 text-sm text-content-tertiary">{field.unit}</span>}
        </div>
      );
    case 'formula': {
      // Computed, never user-entered: show the derived value read-only.
      const shown =
        value == null || value === '' ? '-' : typeof value === 'number' ? String(value) : String(value);
      return (
        <div className="flex items-center gap-2">
          <div className="inline-flex h-10 min-w-[6rem] items-center rounded-lg border border-border bg-surface-secondary px-3 text-sm font-medium tabular-nums text-content-primary">
            {shown}
          </div>
          {field.unit && <span className="shrink-0 text-sm text-content-tertiary">{field.unit}</span>}
        </div>
      );
    }
    case 'date':
      return (
        <input
          type="date"
          className={inputCls}
          disabled={disabled}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case 'checkbox':
      return (
        <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            disabled={disabled}
            checked={value === true}
            onChange={(e) => onChange(e.target.checked)}
            className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
          />
          {t('forms.confirm', { defaultValue: 'Confirm' })}
        </label>
      );
    case 'single_choice':
      return (
        <div className="flex flex-wrap gap-1.5">
          {(field.options ?? []).map((opt) => (
            <ChoiceChip
              key={opt}
              label={opt}
              active={value === opt}
              disabled={disabled}
              onClick={() => onChange(opt)}
            />
          ))}
        </div>
      );
    case 'multi_choice': {
      const picked = Array.isArray(value) ? (value as string[]) : [];
      const toggle = (opt: string) =>
        onChange(picked.includes(opt) ? picked.filter((o) => o !== opt) : [...picked, opt]);
      return (
        <div className="flex flex-wrap gap-1.5">
          {(field.options ?? []).map((opt) => (
            <ChoiceChip
              key={opt}
              label={opt}
              active={picked.includes(opt)}
              disabled={disabled}
              onClick={() => toggle(opt)}
            />
          ))}
        </div>
      );
    }
    case 'pass_fail_na':
      return (
        <div className="flex gap-1.5">
          {(['pass', 'fail', 'na'] as const).map((v) => (
            <PassFailButton
              key={v}
              value={v}
              active={value === v}
              disabled={disabled}
              onClick={() => onChange(v)}
            />
          ))}
        </div>
      );
    case 'rating':
      return (
        <RatingInput
          max={field.max_rating ?? 5}
          value={typeof value === 'number' ? value : Number(value) || 0}
          disabled={disabled}
          onChange={(n) => onChange(n)}
        />
      );
    case 'photo':
      return <PhotoInput value={Array.isArray(value) ? (value as string[]) : []} disabled={disabled} onChange={onChange} />;
    case 'signature':
      return <SignatureInput value={value} disabled={disabled} onChange={onChange} />;
    default:
      return null;
  }
}

function ChoiceChip({
  label,
  active,
  disabled,
  onClick,
}: {
  label: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={clsx(
        'inline-flex h-9 items-center rounded-lg border px-3 text-sm transition-colors disabled:opacity-60',
        active
          ? 'border-oe-blue bg-oe-blue-subtle font-medium text-oe-blue-text'
          : 'border-border text-content-secondary hover:bg-surface-secondary',
      )}
    >
      {label}
    </button>
  );
}

function PassFailButton({
  value,
  active,
  disabled,
  onClick,
}: {
  value: 'pass' | 'fail' | 'na';
  active: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  const cfg = {
    pass: { label: t('forms.pass', { defaultValue: 'Pass' }), on: 'border-semantic-success bg-semantic-success-bg text-semantic-success', icon: <Check size={14} /> },
    fail: { label: t('forms.fail', { defaultValue: 'Fail' }), on: 'border-semantic-error bg-semantic-error-bg text-semantic-error', icon: <X size={14} /> },
    na: { label: t('forms.na', { defaultValue: 'N/A' }), on: 'border-border bg-surface-secondary text-content-secondary', icon: null },
  }[value];
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={clsx(
        'inline-flex h-9 flex-1 items-center justify-center gap-1 rounded-lg border text-sm font-medium transition-colors disabled:opacity-60',
        active ? cfg.on : 'border-border text-content-tertiary hover:bg-surface-secondary',
      )}
    >
      {cfg.icon}
      {cfg.label}
    </button>
  );
}

function RatingInput({
  max,
  value,
  disabled,
  onChange,
}: {
  max: number;
  value: number;
  disabled: boolean;
  onChange: (n: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {Array.from({ length: max }, (_, i) => i + 1).map((n) => (
        <button
          key={n}
          type="button"
          disabled={disabled}
          onClick={() => onChange(n)}
          aria-label={`${n}`}
          className={clsx(
            'inline-flex h-9 w-9 items-center justify-center rounded-lg border text-sm font-medium transition-colors disabled:opacity-60',
            value >= n
              ? 'border-oe-blue bg-oe-blue text-content-inverse'
              : 'border-border text-content-tertiary hover:bg-surface-secondary',
          )}
        >
          {n}
        </button>
      ))}
    </div>
  );
}

function PhotoInput({
  value,
  disabled,
  onChange,
}: {
  value: string[];
  disabled: boolean;
  onChange: (value: AnswerValue) => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    try {
      const urls: string[] = [];
      for (const file of Array.from(files)) {
        urls.push(await readFileAsDataUrl(file));
      }
      onChange([...value, ...urls]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map((src, i) => (
            <div key={i} className="relative">
              <img src={src} alt="" className="h-16 w-16 rounded-lg border border-border object-cover" />
              {!disabled && (
                <button
                  type="button"
                  aria-label={t('forms.remove_photo', { defaultValue: 'Remove photo' })}
                  onClick={() => onChange(value.filter((_, idx) => idx !== i))}
                  className="absolute -right-1.5 -top-1.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-semantic-error text-white shadow"
                >
                  <X size={11} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {!disabled && (
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-2 text-sm text-content-secondary hover:bg-surface-secondary">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Camera size={15} />}
          {t('forms.add_photo', { defaultValue: 'Add photo' })}
          <input
            type="file"
            accept="image/*"
            capture="environment"
            multiple
            className="hidden"
            onChange={(e) => void onFiles(e.target.files)}
          />
        </label>
      )}
      {disabled && value.length === 0 && <span className="text-sm text-content-tertiary">-</span>}
    </div>
  );
}

function SignatureInput({
  value,
  disabled,
  onChange,
}: {
  value: AnswerValue;
  disabled: boolean;
  onChange: (value: AnswerValue) => void;
}) {
  const { t } = useTranslation();
  const sig: SignatureValue = value && typeof value === 'object' && !Array.isArray(value) ? (value as SignatureValue) : {};
  const name = sig.name ?? '';

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <PenLine size={15} className="shrink-0 text-content-tertiary" />
        <input
          className={inputCls}
          disabled={disabled}
          value={name}
          onChange={(e) => onChange({ ...sig, name: e.target.value })}
          placeholder={t('forms.signer_name', { defaultValue: 'Type full name to sign' })}
        />
      </div>
      {name.trim() && !disabled && !sig.signed_at && (
        <button
          type="button"
          onClick={() => onChange({ ...sig, name, signed_at: new Date().toISOString() })}
          className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
        >
          <Check size={12} />
          {t('forms.sign_now', { defaultValue: 'Confirm signature' })}
        </button>
      )}
      {sig.signed_at && (
        <p className="inline-flex items-center gap-1 text-xs text-semantic-success">
          <Check size={12} />
          {t('forms.signed_on', { defaultValue: 'Signed {{date}}', date: new Date(sig.signed_at).toLocaleString(getIntlLocale()) })}
          {!disabled && (
            <button
              type="button"
              aria-label={t('forms.clear_signature', { defaultValue: 'Clear signature' })}
              onClick={() => onChange({ name })}
              className="ml-1 text-content-tertiary hover:text-semantic-error"
            >
              <Trash2 size={12} />
            </button>
          )}
        </p>
      )}
    </div>
  );
}

/* -- Small bits ------------------------------------------------------------ */

function ReadRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="mb-0.5 block text-xs font-medium text-content-tertiary">{label}</span>
      <div className="text-sm text-content-primary">{children}</div>
    </div>
  );
}

function StatusBadge({ status, result }: { status: SubmissionDetail['status']; result: SubmissionDetail['result'] }) {
  const { t } = useTranslation();
  if (status === 'completed') {
    if (result === 'fail') return <Badge variant="error" size="sm">{t('forms.result_fail', { defaultValue: 'Fail' })}</Badge>;
    if (result === 'pass') return <Badge variant="success" size="sm">{t('forms.result_pass', { defaultValue: 'Pass' })}</Badge>;
    return <Badge variant="success" size="sm">{t('forms.completed', { defaultValue: 'Completed' })}</Badge>;
  }
  return <Badge variant="warning" size="sm">{t('forms.draft', { defaultValue: 'Draft' })}</Badge>;
}

/* -- Helpers --------------------------------------------------------------- */

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error ?? new Error('read failed'));
    reader.readAsDataURL(file);
  });
}

function extractIssues(err: unknown): FieldIssue[] {
  if (err instanceof ApiError && err.body && typeof err.body === 'object') {
    const detail = (err.body as { detail?: unknown }).detail;
    if (detail && typeof detail === 'object' && Array.isArray((detail as { issues?: unknown }).issues)) {
      return (detail as { issues: FieldIssue[] }).issues;
    }
  }
  return [];
}

// Re-exported so callers can reuse the same delete mutation surface if needed.
export { deleteSubmission };
