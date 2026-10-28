// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The writes on a permit application short of its decision: opening one,
// correcting what the authority told us, moving it a step and recording what
// happened to the decision clock.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { fmtList } from '@/shared/lib/formatters';

import {
  addClockEvent,
  createApplication,
  localToday,
  transitionApplication,
  updateApplication,
  type Application,
  type ApplicationInput,
  type ApplicationKind,
  type ApplicationPatch,
  type ApplicationTarget,
  type Clock,
  type ClockEventKind,
  type ClockUnit,
  type ConditionRow,
  type Permit,
} from './api';
import { usePermitAction } from './hooks';
import { APPLICATION_KIND, APPLICATION_STEP, CLOCK_EVENT, CLOCK_UNIT, typeName, vocab, type LabelContext } from './labels';
import { Field, FormDialog, fieldClass } from './PermitBits';
import {
  CLOCK_EVENT_PROBLEM,
  changedOnly,
  clockEventKinds,
  clockEventProblems,
  isExtension,
  toClockEventInput,
  type ClockEventDraft,
} from './rules';

const CHILD_KINDS: ApplicationKind[] = [
  'variation',
  'amendment_non_material',
  'extension_of_validity',
  'discharge_of_conditions',
];
const UNITS: ClockUnit[] = ['calendar_days', 'working_days', 'weeks', 'months', 'years'];

/* ── Open or correct an application ───────────────────────────────────── */

export interface ApplicationDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  requirementId: string;
  /** The application being corrected, or null to open a new one. */
  application: Application | null;
  /** Whether a first application can still be opened: none of the row is open. */
  canOpenNew: boolean;
  /** The permits this roadmap row already holds, which a follow-up application refers to. */
  permits: Permit[];
  /** The open conditions of those permits, for a discharge application. */
  conditions: ConditionRow[];
  labels: LabelContext;
  onCreated?: (application: Application) => void;
}

export function ApplicationDialog({
  open,
  onClose,
  projectId,
  requirementId,
  application,
  canOpenNew,
  permits,
  conditions,
  labels,
  onCreated,
}: ApplicationDialogProps) {
  const { t } = useTranslation();
  const kinds: ApplicationKind[] = [...(canOpenNew ? (['new'] as ApplicationKind[]) : []), ...(permits.length > 0 ? CHILD_KINDS : [])];
  const [kind, setKind] = useState<ApplicationKind>('new');
  const [parent, setParent] = useState('');
  const [discharges, setDischarges] = useState<string[]>([]);
  const [authority, setAuthority] = useState('');
  const [reference, setReference] = useState('');
  const [received, setReceived] = useState('');
  const [validated, setValidated] = useState('');
  const [appeal, setAppeal] = useState('');

  useEffect(() => {
    if (!open) return;
    setKind(application?.kind ?? kinds[0] ?? 'new');
    setParent(application?.parent_permit_id ?? permits[0]?.id ?? '');
    setDischarges([]);
    setAuthority(application?.authority_name ?? '');
    setReference(application?.authority_reference ?? '');
    setReceived(application?.received_at ?? '');
    setValidated(application?.validated_at ?? '');
    setAppeal(application?.appeal_note ?? '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, application]);

  const child = CHILD_KINDS.includes(kind);
  const dischargeable = conditions.filter(
    (c) => c.permit_id === parent && c.confirmed && (c.state === 'open' || c.state === 'evidence_submitted'),
  );

  const create = usePermitAction(
    projectId,
    (body: ApplicationInput) => createApplication(projectId, body),
    (created) => {
      onClose();
      onCreated?.(created);
    },
  );
  const update = usePermitAction(
    projectId,
    (body: ApplicationPatch) => updateApplication(projectId, (application as Application).id, body),
    onClose,
  );
  const action = application ? update : create;
  useEffect(() => {
    if (open) return;
    create.reset();
    update.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const problems: string[] = [];
  if (!application) {
    if (kinds.length === 0) {
      problems.push(
        t('permits.ui.application.problem_open', { defaultValue: 'An application for this permit is still open. Decide or withdraw it first.' }),
      );
    }
    if (child && !parent) {
      problems.push(t('permits.ui.application.problem_parent', { defaultValue: 'Choose the permit this application refers to.' }));
    }
    if (kind === 'discharge_of_conditions' && discharges.length === 0) {
      problems.push(
        t('permits.ui.application.problem_conditions', { defaultValue: 'Tick the conditions the authority is asked to discharge.' }),
      );
    }
  }

  const send = () => {
    if (application) {
      // An emptied date is sent as null; an untouched one does not travel at all.
      const draft: ApplicationPatch = {
        authority_name: authority.trim(),
        authority_reference: reference.trim(),
        appeal_note: appeal.trim(),
        received_at: received || null,
        validated_at: validated || null,
      };
      update.run(changedOnly(application, draft));
      return;
    }
    create.run({
      requirement_id: requirementId,
      kind,
      parent_permit_id: child ? parent : null,
      discharges_condition_ids: kind === 'discharge_of_conditions' ? discharges : [],
      authority_name: authority.trim(),
      authority_reference: reference.trim(),
    });
  };
  const closed = application?.state === 'decided' || application?.state === 'withdrawn';

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="application-dialog"
      title={
        application
          ? t('permits.ui.application.title_edit', { defaultValue: 'Application details' })
          : t('permits.ui.application.title_new', { defaultValue: 'Open an application' })
      }
      subtitle={
        application
          ? undefined
          : t('permits.ui.application.subtitle_new', {
              defaultValue: 'It starts as planned. Record each step as it happens: preparing, submitted, decided.',
            })
      }
      submitLabel={
        application
          ? t('permits.ui.save', { defaultValue: 'Save' })
          : t('permits.ui.application.submit_new', { defaultValue: 'Open application' })
      }
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={send}
    >
      {!application && kinds.length > 1 && (
        <Field label={t('permits.ui.application.kind', { defaultValue: 'Kind of application' })}>
          {(id) => (
            <select id={id} className={fieldClass} value={kind} onChange={(e) => setKind(e.target.value as ApplicationKind)}>
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {vocab(t, APPLICATION_KIND, k)}
                </option>
              ))}
            </select>
          )}
        </Field>
      )}
      {!application && child && (
        <Field label={t('permits.ui.application.parent', { defaultValue: 'Permit it refers to' })} required>
          {(id) => (
            <select
              id={id}
              className={fieldClass}
              value={parent}
              onChange={(e) => {
                setParent(e.target.value);
                setDischarges([]);
              }}
            >
              {permits.map((p) => (
                <option key={p.id} value={p.id}>
                  {fmtList([p.reference, typeName(labels, p.permit_type_code)])}
                </option>
              ))}
            </select>
          )}
        </Field>
      )}
      {!application && kind === 'discharge_of_conditions' && (
        <fieldset>
          <legend className="mb-1 text-sm font-medium text-content-primary">
            {t('permits.ui.application.conditions', { defaultValue: 'Conditions to discharge' })}
          </legend>
          {dischargeable.length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('permits.ui.application.conditions_none', { defaultValue: 'This permit has no open condition.' })}
            </p>
          ) : (
            dischargeable.map((c) => (
              <label key={c.id} className="flex items-start gap-2 py-0.5 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={discharges.includes(c.id)}
                  onChange={() => setDischarges((l) => (l.includes(c.id) ? l.filter((x) => x !== c.id) : [...l, c.id]))}
                />
                <span>
                  <span className="font-medium">{c.number}</span> {c.text}
                </span>
              </label>
            ))
          )}
        </fieldset>
      )}
      {!closed && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('permits.ui.application.authority', { defaultValue: 'Authority' })}>
            {(id) => <input id={id} className={fieldClass} value={authority} onChange={(e) => setAuthority(e.target.value)} />}
          </Field>
          <Field
            label={t('permits.ui.application.reference', { defaultValue: 'Authority reference' })}
            hint={t('permits.ui.application.reference_hint', { defaultValue: 'The number the authority gave the application.' })}
          >
            {(id) => <input id={id} className={fieldClass} value={reference} onChange={(e) => setReference(e.target.value)} />}
          </Field>
        </div>
      )}
      {application && !closed && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label={t('permits.ui.application.received', { defaultValue: 'Received by the authority' })}
            hint={t('permits.ui.application.received_hint', { defaultValue: 'The decision period usually counts from this day.' })}
          >
            {(id) => <input id={id} type="date" className={fieldClass} value={received} onChange={(e) => setReceived(e.target.value)} />}
          </Field>
          <Field label={t('permits.ui.application.validated', { defaultValue: 'Accepted as complete' })}>
            {(id) => <input id={id} type="date" className={fieldClass} value={validated} onChange={(e) => setValidated(e.target.value)} />}
          </Field>
        </div>
      )}
      {application && (
        <Field
          label={t('permits.ui.application.appeal_note', { defaultValue: 'Appeal note' })}
          hint={t('permits.ui.application.appeal_note_hint', {
            defaultValue: 'Whether an appeal is planned or lodged, and by whom.',
          })}
        >
          {(id) => <textarea id={id} rows={2} className={fieldClass} value={appeal} onChange={(e) => setAppeal(e.target.value)} />}
        </Field>
      )}
    </FormDialog>
  );
}

/* ── Move an application one step ─────────────────────────────────────── */

export interface TransitionDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  application: Application;
  target: ApplicationTarget | null;
}

export function TransitionDialog({ open, onClose, projectId, application, target }: TransitionDialogProps) {
  const { t } = useTranslation();
  const [onDate, setOnDate] = useState('');
  const [reason, setReason] = useState('');
  useEffect(() => {
    if (!open) return;
    setOnDate(localToday());
    setReason('');
  }, [open, target]);
  const action = usePermitAction(
    projectId,
    () =>
      transitionApplication(projectId, application.id, {
        target: target as ApplicationTarget,
        on_date: onDate || null,
        reason: reason.trim(),
      }),
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const withdraw = target === 'withdrawn';
  const dated = target === 'submitted' || target === 'validated';
  const problems: string[] = [];
  if (withdraw && !reason.trim()) {
    problems.push(t('permits.ui.transition.problem_reason', { defaultValue: 'Say why the application is withdrawn.' }));
  }
  if (dated && onDate > localToday()) {
    problems.push(t('permits.ui.transition.problem_future', { defaultValue: 'The date cannot be in the future.' }));
  }

  return (
    <FormDialog
      open={open && !!target}
      onClose={onClose}
      testId="transition-dialog"
      danger={withdraw}
      title={target ? vocab(t, APPLICATION_STEP, target) : ''}
      subtitle={
        target === 'submitted'
          ? t('permits.ui.transition.subtitle_submitted', {
              defaultValue: 'From the submission date the decision period is counted. Prerequisite permits are checked now.',
            })
          : undefined
      }
      submitLabel={t('permits.ui.transition.submit', { defaultValue: 'Record step' })}
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={() => action.run(undefined)}
    >
      {dated && (
        <Field
          label={
            target === 'submitted'
              ? t('permits.ui.transition.filed_on', { defaultValue: 'Submitted on' })
              : t('permits.ui.transition.complete_on', { defaultValue: 'Accepted as complete on' })
          }
        >
          {(id) => (
            <input id={id} type="date" max={localToday()} className={`${fieldClass} max-w-xs`} value={onDate} onChange={(e) => setOnDate(e.target.value)} />
          )}
        </Field>
      )}
      <Field label={t('permits.ui.transition.reason', { defaultValue: 'Reason or note' })} required={withdraw}>
        {(id) => <textarea id={id} rows={2} className={fieldClass} value={reason} onChange={(e) => setReason(e.target.value)} />}
      </Field>
    </FormDialog>
  );
}

/* ── The decision clock ───────────────────────────────────────────────── */

export interface ClockEventDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  applicationId: string;
  clock: Clock;
}

export function ClockEventDialog({ open, onClose, projectId, applicationId, clock }: ClockEventDialogProps) {
  const { t } = useTranslation();
  const kinds = clockEventKinds(clock);
  const blank = (): ClockEventDraft => ({
    kind: kinds[0] ?? 'stop',
    at: localToday(),
    period: '',
    unit: clock.unit ?? 'calendar_days',
    reason: '',
  });
  const [draft, setDraft] = useState<ClockEventDraft>(blank);
  useEffect(() => {
    if (open) setDraft(blank());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const action = usePermitAction(projectId, () => addClockEvent(projectId, applicationId, toClockEventInput(draft)), onClose);
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const set = (patch: Partial<ClockEventDraft>) => setDraft((d) => ({ ...d, ...patch }));
  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="clock-event-dialog"
      title={t('permits.ui.clock.event_title', { defaultValue: 'Record a change to the decision period' })}
      subtitle={
        clock.stopped_now
          ? t('permits.ui.clock.event_subtitle_stopped', {
              defaultValue: 'The period is stopped. Record the day the authority had what it asked for, and it runs again.',
            })
          : t('permits.ui.clock.event_subtitle', {
              defaultValue: 'A stop holds the period while the authority waits for information. An extension moves the due date.',
            })
      }
      submitLabel={t('permits.ui.clock.event_submit', { defaultValue: 'Record' })}
      busy={action.busy}
      error={action.error}
      problems={clockEventProblems(draft).map((p) => vocab(t, CLOCK_EVENT_PROBLEM, p))}
      onSubmit={() => action.run(undefined)}
    >
      <Field label={t('permits.ui.clock.event_kind', { defaultValue: 'What happened' })}>
        {(id) => (
          <select id={id} className={fieldClass} value={draft.kind} onChange={(e) => set({ kind: e.target.value as ClockEventKind })}>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {vocab(t, CLOCK_EVENT, k)}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label={t('permits.ui.clock.event_at', { defaultValue: 'On' })} required>
        {(id) => (
          <input id={id} type="date" className={`${fieldClass} max-w-xs`} value={draft.at} onChange={(e) => set({ at: e.target.value })} />
        )}
      </Field>
      {isExtension(draft.kind) && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('permits.ui.clock.event_period', { defaultValue: 'Extended by' })} required>
            {(id) => (
              <input id={id} inputMode="numeric" className={fieldClass} value={draft.period} onChange={(e) => set({ period: e.target.value })} />
            )}
          </Field>
          <Field
            label={t('permits.ui.clock.event_unit', { defaultValue: 'Unit' })}
            hint={t('permits.ui.clock.event_unit_hint', { defaultValue: 'Use the unit the law uses for this period.' })}
          >
            {(id) => (
              <select id={id} className={fieldClass} value={draft.unit} onChange={(e) => set({ unit: e.target.value as ClockUnit })}>
                {UNITS.map((u) => (
                  <option key={u} value={u}>
                    {vocab(t, CLOCK_UNIT, u)}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>
      )}
      <Field label={t('permits.ui.clock.event_reason', { defaultValue: 'Reason' })} required={draft.kind === 'extension_by_authority'}>
        {(id) => <textarea id={id} rows={2} className={fieldClass} value={draft.reason} onChange={(e) => set({ reason: e.target.value })} />}
      </Field>
    </FormDialog>
  );
}
