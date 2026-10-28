// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ChecklistRunnerCompact - a lighter, embeddable FormFiller. It runs a
// checklist template inline (inside an issue panel, a drawer, a card) rather
// than in the full-page Forms workspace: it starts a submission, renders the
// frozen template fields with the same controls as FormFiller, lets the user
// add a per-item note on a checklist item, and completes the submission with
// the existing helpers. A failed pass/fail check can raise a tracked issue on
// the spot, mirroring the "raise inspection from submission" pattern.
//
// It is self-contained inside the forms module and safe for other modules
// (punch list, BCF topics) to import and mount.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Check,
  Loader2,
  CircleAlert,
  TriangleAlert,
  ClipboardCheck,
  Flag,
  RotateCcw,
} from 'lucide-react';
import clsx from 'clsx';
import { Button, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import {
  createSubmission,
  completeSubmission,
  fetchSubmission,
  updateSubmission,
  type AnswerMap,
  type AnswerValue,
  type FieldIssue,
  type FormFieldDef,
  type FormResult,
  type SubmissionDetail,
} from './api';
import { LAYOUT_TYPES, isAnswerEmpty, missingRequiredKeys, requiredCount } from './fieldTypes';
import { FieldControl } from './FormFiller';
import { createPunchItem } from '../punchlist/api';

const inputCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* -- Public types ---------------------------------------------------------- */

/** A reference to the tracked issue a checklist run is attached to. */
export interface ChecklistIssueContext {
  /** The kind of tracked issue, e.g. `'punch'` or `'bcf_topic'`. */
  issueType: string;
  /** The id of the issue the run is attached to. */
  issueId: string;
  /** Optional human label for the issue, surfaced in prefilled sub-issues. */
  issueTitle?: string;
}

/** One failed checklist item, handed back so the host can act on failures. */
export interface ChecklistFailedItem {
  key: string;
  label: string;
  note: string;
  /** True when the failed field was required (a critical fail). */
  critical: boolean;
}

/** The outcome of a completed run, passed to `onComplete`. */
export interface ChecklistRunResult {
  submission: SubmissionDetail;
  /** Backend-derived roll-up: `'fail'` if any check failed, else pass/na/null. */
  result: FormResult;
  failedItems: ChecklistFailedItem[];
  /** Ids of tracked issues raised during the run (in item order raised). */
  raisedIssueIds: string[];
}

export interface ChecklistRunnerCompactProps {
  /** Project the submission belongs to. */
  projectId: string;
  /** Template to run: its id, or any object carrying an `id` (summary/detail). */
  template: string | { id: string };
  /** Issue this run is attached to; stored in the submission metadata. */
  issueContext?: ChecklistIssueContext;
  /** Resume an existing submission instead of starting a fresh one. */
  submissionId?: string | null;
  /** Reference/title prefilled onto the submission. */
  title?: string;
  /** Location prefilled onto the submission. */
  location?: string;
  /** Offer "raise issue" on failed checks. Defaults to `true`. */
  allowRaiseIssue?: boolean;
  /** Fired once, after the submission is completed. */
  onComplete?: (result: ChecklistRunResult) => void;
  /** Fired whenever a tracked issue is raised from a failed check. */
  onIssueRaised?: (issueId: string, item: { key: string; label: string }) => void;
  /** Optional cancel affordance (e.g. "Back" to the template picker). */
  onCancel?: () => void;
  className?: string;
}

/* -- Metadata linkage ------------------------------------------------------ */

/**
 * Build the metadata that links a submission to a site issue. Kept flat under
 * `issueType` / `issueId` (plus a `source` marker) so it is trivially
 * discoverable when reading the submission back from the issue side.
 */
export function issueLinkageMetadata(ctx?: ChecklistIssueContext): Record<string, unknown> {
  if (!ctx || !ctx.issueId) return {};
  return {
    source: 'checklist_runner',
    issueType: ctx.issueType,
    issueId: ctx.issueId,
    ...(ctx.issueTitle ? { issueTitle: ctx.issueTitle } : {}),
  };
}

/* -- Component ------------------------------------------------------------- */

export function ChecklistRunnerCompact({
  projectId,
  template,
  issueContext,
  submissionId,
  title,
  location,
  allowRaiseIssue = true,
  onComplete,
  onIssueRaised,
  onCancel,
  className,
}: ChecklistRunnerCompactProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const templateId = typeof template === 'string' ? template : template.id;

  const [submission, setSubmission] = useState<SubmissionDetail | null>(null);
  const [answers, setAnswers] = useState<AnswerMap>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [invalidKeys, setInvalidKeys] = useState<Set<string>>(new Set());
  const [raisedIssueIds, setRaisedIssueIds] = useState<string[]>([]);
  const [raisedByKey, setRaisedByKey] = useState<Record<string, string>>({});
  const startedRef = useRef(false);
  const completedRef = useRef(false);

  const readOnly = submission?.status === 'completed';
  const fields = submission?.template_snapshot ?? [];

  /* -- Start / resume ------------------------------------------------------ */

  const startMut = useMutation({
    mutationFn: async (): Promise<SubmissionDetail> => {
      if (submissionId) return fetchSubmission(submissionId);
      return createSubmission({
        project_id: projectId,
        template_id: templateId,
        title: title ?? null,
        location: location ?? null,
        metadata: issueLinkageMetadata(issueContext),
      });
    },
    onSuccess: (sub) => {
      setSubmission(sub);
      setAnswers({ ...sub.answers });
      const meta = sub.metadata as { item_notes?: Record<string, string> } | undefined;
      if (meta?.item_notes && typeof meta.item_notes === 'object') {
        setNotes({ ...meta.item_notes });
      }
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  // Start exactly once, when the project + template are known. A ref guards
  // against React double-invoke and background re-renders creating duplicate
  // draft submissions.
  useEffect(() => {
    if (startedRef.current || !projectId || !templateId) return;
    startedRef.current = true;
    startMut.mutate();
  }, [projectId, templateId]); // eslint-disable-line react-hooks/exhaustive-deps

  /* -- Answers + notes ----------------------------------------------------- */

  const setAnswer = (key: string, value: AnswerValue) =>
    setAnswers((prev) => ({ ...prev, [key]: value }));

  const setNote = (key: string, value: string) =>
    setNotes((prev) => ({ ...prev, [key]: value }));

  const missing = useMemo(() => missingRequiredKeys(fields, answers), [fields, answers]);
  const totalRequired = useMemo(() => requiredCount(fields), [fields]);
  const answeredRequired = totalRequired - missing.length;

  const failedItems = useMemo(() => collectFailedItems(fields, answers, notes), [fields, answers, notes]);
  const hasCriticalFail = failedItems.some((f) => f.critical);

  /* -- Complete ------------------------------------------------------------ */

  const completeMut = useMutation({
    mutationFn: async (): Promise<SubmissionDetail> => {
      const id = submission!.id;
      // Persist answers + the per-item notes / raised issues into metadata
      // first, then run the gated completion. Mirrors FormFiller.completeMut so
      // a last-second edit is never lost.
      await updateSubmission(id, {
        title: title ?? undefined,
        location: location ?? undefined,
        answers,
        metadata: { item_notes: notes, raised_issue_ids: raisedIssueIds },
      });
      return completeSubmission(id, answers);
    },
    onSuccess: (updated) => {
      setSubmission(updated);
      setInvalidKeys(new Set());
      addToast({ type: 'success', title: t('forms.checklist_completed', { defaultValue: 'Checklist completed' }) });
      qc.invalidateQueries({ queryKey: ['forms', 'submissions'] });
      if (!completedRef.current) {
        completedRef.current = true;
        onComplete?.({
          submission: updated,
          result: updated.result,
          failedItems: collectFailedItems(updated.template_snapshot ?? fields, answers, notes),
          raisedIssueIds,
        });
      }
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

  const onCompleteClick = () => {
    if (!submission) return;
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

  /* -- Raise issue from a failed check ------------------------------------- */

  const raiseMut = useMutation({
    mutationFn: async (field: FormFieldDef): Promise<{ key: string; id: string }> => {
      const note = (notes[field.key] ?? '').trim();
      const lines = [
        t('forms.raised_from_checklist', {
          defaultValue: 'Raised from checklist: {{name}}',
          name: submission?.template_name ?? '',
        }),
      ];
      if (note) lines.push(note);
      if (issueContext?.issueTitle) {
        lines.push(
          t('forms.related_to_issue', {
            defaultValue: 'Related issue: {{title}}',
            title: issueContext.issueTitle,
          }),
        );
      }
      const punch = await createPunchItem({
        project_id: projectId,
        title: (field.label || t('forms.failed_check', { defaultValue: 'Failed check' })).slice(0, 300),
        description: lines.join('\n\n'),
        // A required (critical) check failing is a high-priority defect.
        priority: field.required ? 'high' : 'medium',
      });
      return { key: field.key, id: punch.id };
    },
    onSuccess: ({ key, id }) => {
      setRaisedIssueIds((prev) => [...prev, id]);
      setRaisedByKey((prev) => ({ ...prev, [key]: id }));
      addToast({ type: 'success', title: t('forms.issue_raised', { defaultValue: 'Issue raised' }) });
      const field = fields.find((f) => f.key === key);
      if (field) onIssueRaised?.(id, { key, label: field.label });
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  /* -- Render -------------------------------------------------------------- */

  if (startMut.isError && !submission) {
    return (
      <div className={clsx('rounded-xl border border-border p-6 text-center', className)}>
        <p className="mb-3 text-sm text-content-secondary">
          {t('forms.checklist_start_failed', { defaultValue: 'Could not start this checklist.' })}
        </p>
        <Button
          variant="secondary"
          size="sm"
          icon={<RotateCcw size={14} />}
          onClick={() => startMut.mutate()}
          loading={startMut.isPending}
        >
          {t('common.retry', { defaultValue: 'Retry' })}
        </Button>
      </div>
    );
  }

  if (!submission) {
    return (
      <div className={clsx('flex items-center justify-center rounded-xl border border-border p-8 text-content-tertiary', className)}>
        <Loader2 className="animate-spin" size={18} />
      </div>
    );
  }

  return (
    <div className={clsx('flex flex-col overflow-hidden rounded-xl border border-border bg-surface-primary', className)}>
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border-light px-3 py-2.5">
        <ClipboardCheck size={16} className="shrink-0 text-oe-blue" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-content-primary">{submission.template_name}</div>
          <div className="truncate text-xs text-content-tertiary">
            {submission.submission_number}
            {title ? ` · ${title}` : ''}
          </div>
        </div>
        <ResultBadge status={submission.status} result={submission.result} />
      </div>

      {/* Required-fields meter */}
      {!readOnly && totalRequired > 0 && (
        <div className="border-b border-border-light px-3 py-2">
          <div className="mb-1 flex items-center justify-between text-xs text-content-tertiary">
            <span>{t('forms.required_progress', { defaultValue: 'Required fields' })}</span>
            <span>
              {answeredRequired}/{totalRequired}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-tertiary">
            <div
              className={clsx('h-full rounded-full transition-all', missing.length === 0 ? 'bg-semantic-success' : 'bg-oe-blue')}
              style={{ width: `${totalRequired ? (answeredRequired / totalRequired) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      {/* Fail banner on a completed run */}
      {readOnly && hasCriticalFail && (
        <div className="flex items-start gap-2 border-b border-border-light bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error">
          <TriangleAlert size={14} className="mt-0.5 shrink-0" />
          <span>
            {t('forms.checklist_failed_hint', {
              defaultValue: 'This checklist has failed checks. Raise an issue for each one that needs fixing.',
            })}
          </span>
        </div>
      )}

      {/* Items */}
      <div className="max-h-[60vh] flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {fields.map((field, idx) => (
          <ChecklistItem
            key={field.key || idx}
            field={field}
            value={answers[field.key] ?? null}
            note={notes[field.key] ?? ''}
            readOnly={readOnly}
            invalid={invalidKeys.has(field.key)}
            allowRaiseIssue={allowRaiseIssue}
            raisedIssueId={raisedByKey[field.key] ?? null}
            raising={raiseMut.isPending && raiseMut.variables?.key === field.key}
            onAnswer={(v) => setAnswer(field.key, v)}
            onNote={(v) => setNote(field.key, v)}
            onRaise={() => raiseMut.mutate(field)}
          />
        ))}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-2 border-t border-border-light bg-surface-elevated px-3 py-2.5">
        {onCancel ? (
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {readOnly ? t('common.close', { defaultValue: 'Close' }) : t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        ) : (
          <span />
        )}
        {!readOnly && (
          <Button size="sm" icon={<Check size={14} />} loading={completeMut.isPending} onClick={onCompleteClick}>
            {t('forms.complete', { defaultValue: 'Complete' })}
          </Button>
        )}
      </div>
    </div>
  );
}

/* -- Item row -------------------------------------------------------------- */

interface ChecklistItemProps {
  field: FormFieldDef;
  value: AnswerValue;
  note: string;
  readOnly: boolean;
  invalid: boolean;
  allowRaiseIssue: boolean;
  raisedIssueId: string | null;
  raising: boolean;
  onAnswer: (value: AnswerValue) => void;
  onNote: (value: string) => void;
  onRaise: () => void;
}

function ChecklistItem({
  field,
  value,
  note,
  readOnly,
  invalid,
  allowRaiseIssue,
  raisedIssueId,
  raising,
  onAnswer,
  onNote,
  onRaise,
}: ChecklistItemProps) {
  const { t } = useTranslation();

  if (LAYOUT_TYPES.has(field.type)) {
    return (
      <div className="pt-1">
        <h4 className="border-b border-border-light pb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {field.label}
        </h4>
      </div>
    );
  }

  const isCheck = field.type === 'pass_fail_na';
  const answered = value !== null && value !== undefined && value !== '';
  const isFail = isCheck && value === 'fail';
  const showMissing = invalid && field.required && isAnswerEmpty(field.type, value);
  // A checklist item reveals its note + raise-issue affordances once it has
  // been answered (or already carries a note); other field types stay lean.
  // Once completed (read-only) only show the row when there is something to
  // show - a captured note, or a failed check that can still raise an issue.
  const showNoteRow =
    isCheck &&
    (readOnly ? note.trim().length > 0 || (isFail && allowRaiseIssue) : answered || note.trim().length > 0);

  return (
    <div className="rounded-lg border border-border-light p-2.5">
      <label className="mb-1.5 flex items-start gap-1 text-sm font-medium text-content-secondary">
        <span>{field.label}</span>
        {field.required && <span className="text-semantic-error">*</span>}
      </label>
      {field.help_text && <p className="mb-1.5 text-xs text-content-tertiary">{field.help_text}</p>}

      <FieldControl field={field} value={value} readOnly={readOnly} onChange={onAnswer} />

      {showMissing && (
        <p className="mt-1 inline-flex items-center gap-1 text-xs text-semantic-error">
          <CircleAlert size={12} />
          {t('forms.this_required', { defaultValue: 'This field is required.' })}
        </p>
      )}

      {showNoteRow && (
        <div className="mt-2 space-y-1.5">
          {readOnly ? (
            note.trim() ? (
              <p className="text-xs text-content-tertiary">
                <span className="font-medium text-content-secondary">
                  {t('forms.note', { defaultValue: 'Note' })}:
                </span>{' '}
                {note}
              </p>
            ) : null
          ) : (
            <textarea
              className={clsx(inputCls, 'min-h-[38px] resize-y')}
              value={note}
              onChange={(e) => onNote(e.target.value)}
              placeholder={t('forms.item_note_ph', { defaultValue: 'Add a note (optional)' })}
            />
          )}

          {isFail && allowRaiseIssue && (
            <div className="flex items-center gap-2">
              {raisedIssueId ? (
                <Badge variant="warning" size="sm">
                  {t('forms.issue_raised', { defaultValue: 'Issue raised' })}
                </Badge>
              ) : (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Flag size={13} />}
                  loading={raising}
                  onClick={onRaise}
                >
                  {t('forms.raise_issue', { defaultValue: 'Raise issue' })}
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* -- Small bits ------------------------------------------------------------ */

function ResultBadge({ status, result }: { status: SubmissionDetail['status']; result: FormResult }) {
  const { t } = useTranslation();
  if (status !== 'completed') {
    return (
      <Badge variant="warning" size="sm">
        {t('forms.draft', { defaultValue: 'Draft' })}
      </Badge>
    );
  }
  if (result === 'fail') {
    return (
      <Badge variant="error" size="sm">
        {t('forms.result_fail', { defaultValue: 'Fail' })}
      </Badge>
    );
  }
  if (result === 'pass') {
    return (
      <Badge variant="success" size="sm">
        {t('forms.result_pass', { defaultValue: 'Pass' })}
      </Badge>
    );
  }
  return (
    <Badge variant="success" size="sm">
      {t('forms.completed', { defaultValue: 'Completed' })}
    </Badge>
  );
}

/* -- Helpers --------------------------------------------------------------- */

/** Mirror of the backend `_derive_result` failure test, item by item. */
function collectFailedItems(
  fields: FormFieldDef[],
  answers: AnswerMap,
  notes: Record<string, string>,
): ChecklistFailedItem[] {
  const out: ChecklistFailedItem[] = [];
  for (const f of fields) {
    if (f.type !== 'pass_fail_na') continue;
    if ((answers[f.key] ?? null) === 'fail') {
      out.push({ key: f.key, label: f.label, note: (notes[f.key] ?? '').trim(), critical: !!f.required });
    }
  }
  return out;
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
