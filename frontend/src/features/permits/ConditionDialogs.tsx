// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The writes on a permit condition: entering or correcting it, attaching
// evidence, closing it, raising a breach, handing it to an owner and turning
// a measurable limit into a tracked requirement.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import { fetchCDEContainers } from '@/features/cde/api';
import { fmtList } from '@/shared/lib/formatters';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';

import {
  addEvidence,
  assignOwner,
  conditionToRequirement,
  createCondition,
  dischargeCondition,
  localToday,
  markInCompliance,
  raiseBreach,
  updateCondition,
  type Condition,
  type ConditionInput,
  type ConditionKind,
  type ConditionPurpose,
  type DischargeCan,
  type DischargeMode,
  type EvidenceKind,
  type Topic,
  type Trigger,
} from './api';
import { refusalText, usePermitAction } from './hooks';
import {
  CONDITION_KIND,
  CONDITION_KIND_HINT,
  DISCHARGE_MODE,
  DISCHARGE_MODE_HINT,
  EVIDENCE_KIND,
  TOPIC,
  TRIGGER,
  errorText,
  vocab,
  type TFn,
} from './labels';
import { Field, FormDialog, Refusal, fieldClass } from './PermitBits';
import {
  CONDITION_PROBLEM,
  changedOnly,
  conditionProblems,
  dischargeModes,
  dischargeNeedsDocument,
  draftOfCondition,
  newConditionDraft,
  toConditionInput,
  type ConditionDraft,
} from './rules';

const KINDS: ConditionKind[] = [
  'obligation',
  'suspensive',
  'time_limit',
  'revocation_reserve',
  'reserved_obligation',
  'information',
];
const TRIGGERS: Trigger[] = [
  'before_start',
  'before_stage',
  'before_occupation',
  'ongoing',
  'by_date',
  'on_event',
  'after_completion',
  'before_application_x',
];
const TOPICS: Topic[] = [
  'structural',
  'fire',
  'hse',
  'environment',
  'noise',
  'traffic',
  'heritage',
  'drainage',
  'ecology',
  'design',
  'admin',
  'other',
];
/** The evidence kinds this screen can attach. The others need a record picked from another module. */
const EVIDENCE_KINDS: EvidenceKind[] = ['report', 'photo', 'external_url', 'cde_revision'];

/** The current revision of a project document, picked by the document's name. */
export function DocumentRevisionSelect({
  id,
  projectId,
  value,
  onChange,
  enabled,
}: {
  id?: string;
  projectId: string;
  value: string;
  onChange: (revisionId: string) => void;
  enabled: boolean;
}) {
  const { t } = useTranslation();
  const containersQ = useQuery({
    queryKey: ['permits', projectId, 'cde-containers'],
    queryFn: () => fetchCDEContainers({ project_id: projectId }),
    enabled: enabled && !!projectId,
    staleTime: 60_000,
  });
  const options = (containersQ.data ?? []).filter((c) => !!c.current_revision_id);
  return (
    <>
      <select id={id} className={fieldClass} value={value} disabled={containersQ.isLoading} onChange={(e) => onChange(e.target.value)}>
        <option value="">
          {containersQ.isLoading
            ? t('permits.ui.loading', { defaultValue: 'Loading...' })
            : t('permits.ui.document.choose', { defaultValue: 'Choose a document' })}
        </option>
        {options.map((c) => (
          <option key={c.id} value={c.current_revision_id as string}>
            {fmtList([c.container_code, c.title])}
          </option>
        ))}
      </select>
      {containersQ.isError && <Refusal testId="document-error">{refusalText(t as TFn, containersQ.error)}</Refusal>}
      {containersQ.isSuccess && options.length === 0 && (
        <p className="mt-1 text-xs text-content-tertiary" data-testid="document-none">
          {t('permits.ui.document.none', {
            defaultValue: 'No document with a revision yet. Store the document in the project documents first.',
          })}
        </p>
      )}
    </>
  );
}

/* ── The fields of one condition ──────────────────────────────────────── */

export interface ConditionFieldsProps {
  projectId: string;
  draft: ConditionDraft;
  onChange: (patch: Partial<ConditionDraft>) => void;
  personName: (userId: string | null | undefined) => string | null;
  /** The number comes from the notice and cannot change once the condition exists. */
  numberLocked?: boolean;
  /** The wording is frozen once the condition has moved on from open. */
  textLocked?: boolean;
}

export function ConditionFields({ projectId, draft, onChange, personName, numberLocked, textLocked }: ConditionFieldsProps) {
  const { t } = useTranslation();
  const duty = draft.kind !== 'information';
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-[7rem_1fr]">
        <Field label={t('permits.ui.condition.number', { defaultValue: 'Number' })} required>
          {(id) => (
            <input
              id={id}
              className={fieldClass}
              value={draft.number}
              disabled={numberLocked}
              onChange={(e) => onChange({ number: e.target.value })}
            />
          )}
        </Field>
        <Field label={t('permits.ui.condition.kind', { defaultValue: 'Kind' })} hint={vocab(t, CONDITION_KIND_HINT, draft.kind)}>
          {(id) => (
            <select
              id={id}
              className={fieldClass}
              value={draft.kind}
              onChange={(e) => onChange({ kind: e.target.value as ConditionKind })}
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {vocab(t, CONDITION_KIND, k)}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>
      <Field
        label={t('permits.ui.condition.text', { defaultValue: 'Wording from the notice' })}
        required
        hint={
          textLocked
            ? t('permits.ui.condition.text_locked', { defaultValue: 'The wording can only change while the condition is open.' })
            : undefined
        }
      >
        {(id) => (
          <textarea
            id={id}
            rows={3}
            className={fieldClass}
            value={draft.text}
            disabled={textLocked}
            onChange={(e) => onChange({ text: e.target.value })}
          />
        )}
      </Field>
      {duty && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={t('permits.ui.condition.trigger', { defaultValue: 'When it is due' })}>
              {(id) => (
                <select
                  id={id}
                  className={fieldClass}
                  value={draft.trigger}
                  onChange={(e) => onChange({ trigger: e.target.value as Trigger })}
                >
                  {TRIGGERS.map((x) => (
                    <option key={x} value={x}>
                      {vocab(t, TRIGGER, x)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label={t('permits.ui.condition.due_date', { defaultValue: 'Due date' })} required={draft.trigger === 'by_date'}>
              {(id) => (
                <input
                  id={id}
                  type="date"
                  className={fieldClass}
                  value={draft.due_date}
                  onChange={(e) => onChange({ due_date: e.target.value })}
                />
              )}
            </Field>
            <Field label={t('permits.ui.condition.topic', { defaultValue: 'Topic' })}>
              {(id) => (
                <select id={id} className={fieldClass} value={draft.topic} onChange={(e) => onChange({ topic: e.target.value as Topic })}>
                  {TOPICS.map((x) => (
                    <option key={x} value={x}>
                      {vocab(t, TOPIC, x)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </div>
          {draft.trigger === 'before_stage' && (
            <Field label={t('permits.ui.condition.stage', { defaultValue: 'Which stage' })} required>
              {(id) => (
                <input id={id} className={fieldClass} value={draft.stage_ref} onChange={(e) => onChange({ stage_ref: e.target.value })} />
              )}
            </Field>
          )}
          {draft.trigger === 'on_event' && (
            <Field label={t('permits.ui.condition.event', { defaultValue: 'Which event' })} required>
              {(id) => (
                <input id={id} className={fieldClass} value={draft.event_text} onChange={(e) => onChange({ event_text: e.target.value })} />
              )}
            </Field>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('permits.ui.condition.owner', { defaultValue: 'Owner' })}>
              {(id) => (
                <ProjectPeopleSelect
                  id={id}
                  projectId={projectId}
                  value={draft.owner_user_id}
                  displayValue={personName(draft.owner_user_id) ?? undefined}
                  onChange={(userId) => onChange({ owner_user_id: userId })}
                  placeholder={t('permits.ui.condition.owner', { defaultValue: 'Owner' })}
                />
              )}
            </Field>
            <Field label={t('permits.ui.condition.responsible_party', { defaultValue: 'Company that carries it out' })}>
              {(id) => (
                <input
                  id={id}
                  className={fieldClass}
                  value={draft.responsible_party}
                  onChange={(e) => onChange({ responsible_party: e.target.value })}
                />
              )}
            </Field>
          </div>
          <Field label={t('permits.ui.condition.evidence_required', { defaultValue: 'What will prove it is met' })}>
            {(id) => (
              <input
                id={id}
                className={fieldClass}
                value={draft.evidence_required}
                onChange={(e) => onChange({ evidence_required: e.target.value })}
              />
            )}
          </Field>
          {draft.kind === 'obligation' && (
            <Field
              label={t('permits.ui.condition.purpose', { defaultValue: 'Purpose, for an early start only' })}
              hint={t('permits.ui.condition.purpose_hint', {
                defaultValue: 'An early start is granted only with the duty to restore the site and, where the law allows, a security.',
              })}
            >
              {(id) => (
                <select
                  id={id}
                  className={fieldClass}
                  value={draft.purpose}
                  onChange={(e) => onChange({ purpose: e.target.value as ConditionPurpose })}
                >
                  <option value="">{t('permits.ui.condition.purpose_none', { defaultValue: 'No special purpose' })}</option>
                  <option value="restoration">
                    {t('permits.ui.condition.purpose_restoration', { defaultValue: 'Restore the site if the permit is refused' })}
                  </option>
                  <option value="security">
                    {t('permits.ui.condition.purpose_security', { defaultValue: 'Provide the security' })}
                  </option>
                </select>
              )}
            </Field>
          )}
          <label className="flex items-start gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              className="mt-1"
              checked={draft.requires_authority_approval}
              onChange={(e) => onChange({ requires_authority_approval: e.target.checked })}
            />
            {t('permits.ui.condition.requires_authority', {
              defaultValue: 'Only the authority can discharge this condition',
            })}
          </label>
        </>
      )}
    </div>
  );
}

/* ── Add or edit one condition ────────────────────────────────────────── */

export interface ConditionDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** The permit the new condition is attached to; ignored when editing. */
  permitId: string;
  /** The condition being corrected, or null to add one. */
  condition: Condition | null;
  personName: (userId: string | null | undefined) => string | null;
}

export function ConditionDialog({ open, onClose, projectId, permitId, condition, personName }: ConditionDialogProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<ConditionDraft>(() => newConditionDraft());
  useEffect(() => {
    if (open) setDraft(condition ? draftOfCondition(condition) : newConditionDraft());
  }, [open, condition]);

  const action = usePermitAction(
    projectId,
    (input: ConditionInput) => {
      if (!condition) return createCondition(projectId, permitId, input);
      // The number is not part of an edit, and only what changed travels.
      const { number: _number, ...rest } = input;
      return updateCondition(projectId, condition.id, changedOnly(condition, rest));
    },
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="condition-dialog"
      size="lg"
      title={
        condition
          ? t('permits.ui.condition.title_edit', { defaultValue: 'Correct condition {{number}}', number: condition.number })
          : t('permits.ui.condition.title_new', { defaultValue: 'Add a condition' })
      }
      subtitle={t('permits.ui.condition.subtitle', {
        defaultValue: 'Copy the condition as the notice words it, then say when it is due and who owns it.',
      })}
      submitLabel={
        condition
          ? t('permits.ui.save', { defaultValue: 'Save' })
          : t('permits.ui.condition.submit_new', { defaultValue: 'Add condition' })
      }
      busy={action.busy}
      error={action.error}
      problems={conditionProblems(draft).map((p) => vocab(t, CONDITION_PROBLEM, p))}
      onSubmit={() => action.run(toConditionInput(draft))}
    >
      <ConditionFields
        projectId={projectId}
        draft={draft}
        onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
        personName={personName}
        numberLocked={!!condition}
        textLocked={!!condition && condition.state !== 'open'}
      />
    </FormDialog>
  );
}

/* ── Evidence ─────────────────────────────────────────────────────────── */

export interface ConditionActionDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  condition: Condition;
}

export function EvidenceDialog({ open, onClose, projectId, condition }: ConditionActionDialogProps) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<EvidenceKind>('report');
  const [ref, setRef] = useState('');
  const [note, setNote] = useState('');
  useEffect(() => {
    if (!open) return;
    setKind('report');
    setRef('');
    setNote('');
  }, [open]);

  const action = usePermitAction(
    projectId,
    () => addEvidence(projectId, condition.id, { kind, ref_id: ref.trim(), note: note.trim() }),
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const problems: string[] = [];
  if (kind === 'cde_revision' && !ref) {
    problems.push(t('permits.ui.evidence.problem_document', { defaultValue: 'Choose the document that is the evidence.' }));
  } else if (!ref.trim() && !note.trim()) {
    problems.push(
      t('permits.ui.evidence.problem_empty', { defaultValue: 'Give a reference or write a note, so the evidence can be found.' }),
    );
  }

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="evidence-dialog"
      title={t('permits.ui.evidence.title', { defaultValue: 'Add evidence for condition {{number}}', number: condition.number })}
      subtitle={condition.evidence_required || undefined}
      submitLabel={t('permits.ui.evidence.submit', { defaultValue: 'Add evidence' })}
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={() => action.run(undefined)}
    >
      <Field label={t('permits.ui.evidence.kind', { defaultValue: 'Kind of evidence' })}>
        {(id) => (
          <select
            id={id}
            className={fieldClass}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as EvidenceKind);
              setRef('');
            }}
          >
            {EVIDENCE_KINDS.map((k) => (
              <option key={k} value={k}>
                {vocab(t, EVIDENCE_KIND, k)}
              </option>
            ))}
          </select>
        )}
      </Field>
      {kind === 'cde_revision' ? (
        <Field label={t('permits.ui.evidence.document', { defaultValue: 'Document' })} required>
          {(id) => <DocumentRevisionSelect id={id} projectId={projectId} value={ref} onChange={setRef} enabled={open} />}
        </Field>
      ) : (
        <Field
          label={
            kind === 'external_url'
              ? t('permits.ui.evidence.url', { defaultValue: 'Web address' })
              : t('permits.ui.evidence.reference', { defaultValue: 'Reference' })
          }
          hint={
            kind === 'external_url'
              ? undefined
              : t('permits.ui.evidence.reference_hint', { defaultValue: 'A report number, a file name or where the photo is kept.' })
          }
        >
          {(id) => <input id={id} className={fieldClass} value={ref} onChange={(e) => setRef(e.target.value)} />}
        </Field>
      )}
      <Field label={t('permits.ui.note', { defaultValue: 'Note' })}>
        {(id) => <textarea id={id} rows={2} className={fieldClass} value={note} onChange={(e) => setNote(e.target.value)} />}
      </Field>
    </FormDialog>
  );
}

/* ── Closing a condition ──────────────────────────────────────────────── */

export function DischargeDialog({
  open,
  onClose,
  projectId,
  condition,
  can,
}: ConditionActionDialogProps & { can?: DischargeCan }) {
  const { t } = useTranslation();
  const modes = dischargeModes(condition).filter((m) => can?.[m]?.applies !== false);
  // The server says which ways are open to this reader; without its word every way the state allows is offered.
  const blocked = (m: DischargeMode) => can?.[m]?.allowed === false;
  const free = modes.filter((m) => !blocked(m));
  const [mode, setMode] = useState<DischargeMode | ''>('');
  const [onDate, setOnDate] = useState('');
  const [doc, setDoc] = useState('');
  const [note, setNote] = useState('');
  useEffect(() => {
    if (!open) return;
    setMode(free.length === 1 ? free[0]! : '');
    setOnDate(localToday());
    setDoc('');
    setNote('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, condition.id]);

  const action = usePermitAction(
    projectId,
    () =>
      dischargeCondition(projectId, condition.id, {
        mode: mode as DischargeMode,
        on_date: onDate || null,
        document_revision_id: doc || null,
        note: note.trim(),
      }),
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const problems: string[] = [];
  if (!mode) problems.push(t('permits.ui.discharge.problem_mode', { defaultValue: 'Choose how the condition is closed.' }));
  const needsProof = mode === 'not_triggered' && dischargeNeedsDocument(condition, mode);
  if (needsProof && !doc) {
    problems.push(
      t('permits.ui.discharge.problem_proof', {
        defaultValue: 'Add the document that shows the trigger did not occur.',
      }),
    );
  }
  if (mode === 'waived_by_authority' && !doc) {
    problems.push(
      t('permits.ui.discharge.problem_document', { defaultValue: 'A waiver needs the letter of the authority as a document.' }),
    );
  }

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="discharge-dialog"
      title={t('permits.ui.discharge.title', { defaultValue: 'Close condition {{number}}', number: condition.number })}
      subtitle={t('permits.ui.discharge.subtitle', {
        defaultValue:
          'A second person closes a condition: not its owner, and nobody who added or submitted its evidence. Discharge by the authority is recorded through a discharge application.',
      })}
      submitLabel={t('permits.ui.discharge.submit', { defaultValue: 'Close condition' })}
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={() => action.run(undefined)}
    >
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium text-content-primary">
          {t('permits.ui.discharge.mode', { defaultValue: 'How it is closed' })}
        </legend>
        {modes.map((m) => (
          <label key={m} className="flex items-start gap-2 rounded-md border border-border-light bg-surface-elevated p-2.5 text-sm">
            <input
              type="radio"
              name="discharge-mode"
              className="mt-1"
              checked={mode === m}
              disabled={blocked(m)}
              onChange={() => setMode(m)}
              data-testid={`discharge-mode-${m}`}
            />
            <span>
              <span className="font-medium text-content-primary">{vocab(t, DISCHARGE_MODE, m)}</span>
              <span className="block text-xs text-content-secondary">{vocab(t, DISCHARGE_MODE_HINT, m)}</span>
              {blocked(m) && (
                <span className="block text-xs text-semantic-error" data-testid={`discharge-blocked-${m}`}>
                  {errorText(t as TFn, can?.[m]?.reason ?? '', null)}
                </span>
              )}
            </span>
          </label>
        ))}
      </fieldset>
      <Field label={t('permits.ui.discharge.on_date', { defaultValue: 'Closed on' })}>
        {(id) => (
          <input id={id} type="date" max={localToday()} className={`${fieldClass} max-w-xs`} value={onDate} onChange={(e) => setOnDate(e.target.value)} />
        )}
      </Field>
      {needsProof && (
        <Field label={t('permits.ui.discharge.proof', { defaultValue: 'Document that shows it' })} required>
          {(id) => <DocumentRevisionSelect id={id} projectId={projectId} value={doc} onChange={setDoc} enabled={open} />}
        </Field>
      )}
      {mode === 'waived_by_authority' && (
        <Field label={t('permits.ui.discharge.document', { defaultValue: 'Letter of the authority' })} required>
          {(id) => <DocumentRevisionSelect id={id} projectId={projectId} value={doc} onChange={setDoc} enabled={open} />}
        </Field>
      )}
      <Field label={t('permits.ui.note', { defaultValue: 'Note' })}>
        {(id) => <textarea id={id} rows={2} className={fieldClass} value={note} onChange={(e) => setNote(e.target.value)} />}
      </Field>
    </FormDialog>
  );
}

/* ── Ongoing conditions: breach and back in compliance ────────────────── */

export function OngoingDialog({
  open,
  onClose,
  projectId,
  condition,
  target,
}: ConditionActionDialogProps & { target: 'breach' | 'in_compliance' }) {
  const { t } = useTranslation();
  const [note, setNote] = useState('');
  useEffect(() => {
    if (open) setNote('');
  }, [open]);
  const action = usePermitAction(
    projectId,
    () =>
      target === 'breach'
        ? raiseBreach(projectId, condition.id, note.trim())
        : markInCompliance(projectId, condition.id, note.trim()),
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const breach = target === 'breach';
  const problems =
    breach && !note.trim()
      ? [t('permits.ui.ongoing.problem_note', { defaultValue: 'Describe what was breached, when and where.' })]
      : [];
  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="ongoing-dialog"
      danger={breach}
      title={
        breach
          ? t('permits.ui.ongoing.title_breach', { defaultValue: 'Raise a breach of condition {{number}}', number: condition.number })
          : t('permits.ui.ongoing.title_compliance', {
              defaultValue: 'Condition {{number}} is complied with',
              number: condition.number,
            })
      }
      subtitle={
        breach
          ? t('permits.ui.ongoing.subtitle_breach', {
              defaultValue: 'The owner of the condition is told. A breach stays open until someone records that it is remedied.',
            })
          : undefined
      }
      submitLabel={
        breach
          ? t('permits.ui.ongoing.submit_breach', { defaultValue: 'Raise breach' })
          : t('permits.ui.ongoing.submit_compliance', { defaultValue: 'Record compliance' })
      }
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={() => action.run(undefined)}
    >
      <Field
        label={
          breach
            ? t('permits.ui.ongoing.note_breach', { defaultValue: 'What happened' })
            : t('permits.ui.ongoing.note_compliance', { defaultValue: 'What shows it is complied with' })
        }
        required={breach}
      >
        {(id) => <textarea id={id} rows={3} className={fieldClass} value={note} onChange={(e) => setNote(e.target.value)} />}
      </Field>
    </FormDialog>
  );
}

/* ── Hand conditions to an owner ──────────────────────────────────────── */

export interface AssignDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  conditions: Array<Pick<Condition, 'id' | 'number'>>;
}

export function AssignDialog({ open, onClose, projectId, conditions }: AssignDialogProps) {
  const { t } = useTranslation();
  const [owner, setOwner] = useState('');
  const [ownerName, setOwnerName] = useState('');
  useEffect(() => {
    if (!open) return;
    setOwner('');
    setOwnerName('');
  }, [open]);
  const action = usePermitAction(
    projectId,
    () =>
      assignOwner(
        projectId,
        conditions.map((c) => c.id),
        owner,
      ),
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="assign-dialog"
      title={t('permits.ui.assign.title', { defaultValue: 'Assign an owner' })}
      subtitle={t('permits.ui.assign.subtitle', {
        defaultValue: 'Conditions to hand over: {{n}}. The owner is told and keeps the evidence.',
        n: conditions.length,
      })}
      submitLabel={t('permits.ui.assign.submit', { defaultValue: 'Assign owner' })}
      busy={action.busy}
      error={action.error}
      problems={owner ? [] : [t('permits.ui.assign.problem_owner', { defaultValue: 'Choose the person who owns these conditions.' })]}
      onSubmit={() => action.run(undefined)}
    >
      <Field label={t('permits.ui.condition.owner', { defaultValue: 'Owner' })} required>
        {(id) => (
          <ProjectPeopleSelect
            id={id}
            projectId={projectId}
            value={owner}
            displayValue={ownerName}
            onChange={(userId, name) => {
              setOwner(userId);
              setOwnerName(name);
            }}
            placeholder={t('permits.ui.condition.owner', { defaultValue: 'Owner' })}
          />
        )}
      </Field>
    </FormDialog>
  );
}

/* ── A measurable limit becomes a tracked requirement ─────────────────── */

export function LinkRequirementDialog({ open, onClose, projectId, condition }: ConditionActionDialogProps) {
  const { t } = useTranslation();
  const [entity, setEntity] = useState('');
  const [attribute, setAttribute] = useState('');
  const [constraint, setConstraint] = useState('max');
  const [value, setValue] = useState('');
  const [unit, setUnit] = useState('');
  useEffect(() => {
    if (!open) return;
    setEntity('');
    setAttribute('');
    setConstraint('max');
    setValue('');
    setUnit('');
  }, [open]);
  const action = usePermitAction(
    projectId,
    () =>
      conditionToRequirement(projectId, condition.id, {
        entity: entity.trim(),
        attribute: attribute.trim(),
        constraint_type: constraint,
        constraint_value: value.trim(),
        unit: unit.trim(),
      }),
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const problems =
    entity.trim() && attribute.trim()
      ? []
      : [t('permits.ui.link.problem', { defaultValue: 'Say what is limited and which property of it.' })];
  const constraints: Array<[string, string, string]> = [
    ['max', 'permits.ui.link.max', 'At most'],
    ['min', 'permits.ui.link.min', 'At least'],
    ['equals', 'permits.ui.link.equals', 'Exactly'],
  ];
  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="link-requirement-dialog"
      title={t('permits.ui.link.title', { defaultValue: 'Track the limit of condition {{number}}', number: condition.number })}
      subtitle={t('permits.ui.link.subtitle', {
        defaultValue: 'A limit with a number, such as a noise level or working hours, becomes a requirement the design and site checks can test. The wording stays with the condition.',
      })}
      submitLabel={t('permits.ui.link.submit', { defaultValue: 'Create requirement' })}
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={() => action.run(undefined)}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label={t('permits.ui.link.entity', { defaultValue: 'What is limited' })}
          hint={t('permits.ui.link.entity_hint', { defaultValue: 'For example: site works, basement wall.' })}
          required
        >
          {(id) => <input id={id} className={fieldClass} value={entity} onChange={(e) => setEntity(e.target.value)} />}
        </Field>
        <Field
          label={t('permits.ui.link.attribute', { defaultValue: 'Which property' })}
          hint={t('permits.ui.link.attribute_hint', { defaultValue: 'For example: noise level, working hours.' })}
          required
        >
          {(id) => <input id={id} className={fieldClass} value={attribute} onChange={(e) => setAttribute(e.target.value)} />}
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t('permits.ui.link.constraint', { defaultValue: 'Limit' })}>
          {(id) => (
            <select id={id} className={fieldClass} value={constraint} onChange={(e) => setConstraint(e.target.value)}>
              {constraints.map(([code, key, english]) => (
                <option key={code} value={code}>
                  {t(key, { defaultValue: english })}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t('permits.ui.link.value', { defaultValue: 'Value' })}>
          {(id) => <input id={id} className={fieldClass} value={value} onChange={(e) => setValue(e.target.value)} />}
        </Field>
        <Field label={t('permits.ui.link.unit', { defaultValue: 'Unit' })}>
          {(id) => <input id={id} className={fieldClass} value={unit} onChange={(e) => setUnit(e.target.value)} />}
        </Field>
      </div>
    </FormDialog>
  );
}
