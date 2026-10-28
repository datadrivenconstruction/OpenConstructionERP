// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Evidence preservation: the condition of what stands near the site, recorded
// before the works can affect it, and the expert reports the project orders.
// A survey that has been recorded is evidence and can no longer be deleted.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Camera, Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  createExpertReport,
  createSurvey,
  deleteExpertReport,
  deleteSurvey,
  pairSurvey,
  patchExpertReport,
  patchSurvey,
  surveyAction,
  type ExpertReport,
  type ExpertReportState,
  type Finding,
  type Survey,
  type SurveyAction,
} from './api';
import { EvidenceLinks } from './EvidenceLinks';
import { ExportButtons } from './ExportButtons';
import { useExpertReports, useQcWrite, useSurveys } from './hooks';
import { ClosedReasons, SharedReasons } from './ClosedReasons';
import { OptionPicker } from './OptionPicker';
import {
  EXPERT_FREQUENCY,
  EXPERT_STATE,
  EXPERT_TRIGGER,
  INFLUENCE_TRIGGER,
  SURVEY_ACTION,
  SURVEY_METHOD,
  SURVEY_PHASE,
  SURVEY_STATE,
  gate,
  nameIn,
  vocab,
  vocabOrRaw,
  type TFn,
} from './labels';
import type { PanelProps } from './panel';
import {
  EXPERT_TONE,
  Field,
  FindingList,
  FormDialog,
  Hint,
  RefusalNote,
  SURVEY_TONE,
  Section,
  StateBadge,
  VocabChecks,
  VocabSelect,
  inputCls,
} from './QualityBits';
import { SURVEY_ACTIONS, needsRationale, planRowActions, refChange, sharedReasons } from './rules';

const PHASES = ['before', 'during', 'after', 'on_complaint'] as const;
const METHODS = ['photo', 'crack_mapping', 'level_survey', 'vibration_monitoring', 'reality_capture'] as const;
const TRIGGERS = ['excavation', 'piling', 'dewatering', 'vibration', 'crane_oversail', 'demolition'] as const;
const EXPERT_STATES = ['planned', 'commissioned', 'reporting', 'completed', 'cancelled'] as const;

type Dialog =
  | { kind: 'survey'; survey: Survey | null }
  | { kind: 'action'; survey: Survey; action: SurveyAction }
  | { kind: 'pair'; survey: Survey }
  | { kind: 'report'; report: ExpertReport | null }
  | null;

const surveyActions = (s: Survey): string[] => ['edit', 'delete', 'pair', ...(SURVEY_ACTIONS[s.state] ?? [])];

export function PreservationPanel(props: PanelProps) {
  const { projectId, catalogue, labels } = props;
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const surveys = useSurveys(projectId);
  const reports = useExpertReports(projectId);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [removing, setRemoving] = useState<{ survey?: Survey; report?: ExpertReport } | null>(null);
  const [linksOf, setLinksOf] = useState<string | null>(null);

  if (surveys.isLoading) return <SkeletonTable rows={4} columns={5} />;
  if (surveys.isError) {
    return (
      <ErrorState
        title={t('qualityConcept.preservation.load_failed', { defaultValue: 'The surveys could not be loaded' })}
        hint={getErrorMessage(surveys.error)}
        onRetry={() => surveys.refetch()}
      />
    );
  }
  const rows = surveys.data?.items ?? [];
  const subjectName = (s: Survey) => nameIn(labels, catalogue?.preservation_subjects, s.subject_kind);
  const findingRef = (f: Finding) => f.ref;

  return (
    <div className="space-y-4" data-testid="preservation-panel">
      <RefusalNote refusal={write.refusal} violations={write.violations} />

      {rows.length === 0 ? (
        <EmptyState
          icon={<Camera size={28} />}
          title={t('qualityConcept.preservation.empty_title', { defaultValue: 'No condition survey planned yet' })}
          description={t('qualityConcept.preservation.empty_body', {
            defaultValue:
              'Before excavation, piling or demolition starts, record the condition of what stands nearby: neighbouring buildings, roads, utilities. A survey taken in time answers a later damage claim.',
          })}
          action={{
            label: t('qualityConcept.preservation.add', { defaultValue: 'Plan a survey' }),
            onClick: () => setDialog({ kind: 'survey', survey: null }),
          }}
        />
      ) : (
        <Section
          testId="survey-section"
          title={t('qualityConcept.preservation.title', { defaultValue: 'Condition surveys' })}
          description={t('qualityConcept.preservation.body', {
            defaultValue: 'What stands near the site, how its condition is recorded and whether its owner has acknowledged the record.',
          })}
          action={
            <div className="flex flex-wrap items-center gap-2">
              <ExportButtons projectId={projectId} what="preservation" />
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setDialog({ kind: 'survey', survey: null })} data-testid="survey-add">
                {t('qualityConcept.preservation.add', { defaultValue: 'Plan a survey' })}
              </Button>
            </div>
          }
        >
          <FindingList findings={surveys.data?.findings ?? []} refName={findingRef} className="mb-3" />
          <SharedReasons codes={sharedReasons(rows, surveyActions)} />
          <ul className="divide-y divide-border-light">
            {rows.map((s) => (
              <li key={s.id} className="py-2" data-testid="survey-entry">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium text-content-primary">{subjectName(s)}</span>
                  <span className="text-content-tertiary">{s.subject_ref}</span>
                  <StateBadge map={SURVEY_STATE} tones={SURVEY_TONE} code={s.state} testId="survey-state" />
                  <span className="text-xs text-content-secondary">{vocab(t as TFn, SURVEY_PHASE, s.phase)}</span>
                  {(s.survey_date || s.planned_date) && (
                    <span className="text-xs text-content-secondary">
                      {s.survey_date
                        ? t('qualityConcept.preservation.surveyed_on', { defaultValue: 'Surveyed on {{date}}', date: fmtDate(s.survey_date) })
                        : t('qualityConcept.preservation.planned_for', {
                            defaultValue: 'Planned for {{date}}',
                            date: fmtDate(s.planned_date as string),
                          })}
                    </span>
                  )}
                </div>
                {s.address && <p className="mt-0.5 text-sm text-content-secondary">{s.address}</p>}
                <p className="mt-0.5 text-xs text-content-tertiary">
                  {fmtList([
                    ...s.influence_triggers.map((x) => vocab(t as TFn, INFLUENCE_TRIGGER, x)),
                    ...s.methods.map((x) => vocab(t as TFn, SURVEY_METHOD, x)),
                  ])}
                </p>
                {s.owner_acknowledged !== null && (
                  <p className="mt-0.5 text-xs text-content-secondary" data-testid="survey-acknowledged">
                    {s.owner_acknowledged
                      ? t('qualityConcept.preservation.acknowledged', { defaultValue: 'The owner acknowledged the record.' })
                      : t('qualityConcept.preservation.not_acknowledged', { defaultValue: 'The owner has not acknowledged the record.' })}
                  </p>
                )}
                {s.state === 'access_refused' && (
                  <p className="mt-0.5 text-xs text-content-primary">
                    {t('qualityConcept.preservation.access_refused', {
                      defaultValue: 'Access was refused: {{note}}',
                      note: s.access_refusal_note,
                    })}
                  </p>
                )}
                <div className="mt-1 flex flex-wrap gap-1">
                  {(SURVEY_ACTIONS[s.state] ?? []).map((action) => (
                    <Button
                      key={action}
                      size="sm"
                      variant={action === 'refuse_access' ? 'ghost' : 'secondary'}
                      loading={write.pending}
                      {...gate(t as TFn, s, action)}
                      onClick={() =>
                        action === 'close'
                          ? write.send(() => surveyAction(projectId, s.id, { action }))
                          : setDialog({ kind: 'action', survey: s, action })
                      }
                      data-testid={`survey-action-${action}`}
                    >
                      {vocab(t as TFn, SURVEY_ACTION, action)}
                    </Button>
                  ))}
                  {s.phase === 'after' && !s.paired_with_id && (
                    <Button size="sm" variant="secondary" {...gate(t as TFn, s, 'pair')} onClick={() => setDialog({ kind: 'pair', survey: s })} data-testid="survey-pair">
                      {t('qualityConcept.preservation.pair', { defaultValue: 'Pair with the before survey' })}
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => setLinksOf(linksOf === s.id ? null : s.id)} aria-expanded={linksOf === s.id}>
                    {t('qualityConcept.evidence.title', { defaultValue: 'Linked records' })}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Pencil size={14} />}
                    aria-label={t('qualityConcept.common.edit', { defaultValue: 'Edit' })}
                    {...gate(t as TFn, s, 'edit')}
                    onClick={() => setDialog({ kind: 'survey', survey: s })}
                  />
                  {s.state === 'planned' && (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={14} />}
                      aria-label={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
                      {...gate(t as TFn, s, 'delete')}
                      onClick={() => setRemoving({ survey: s })}
                    />
                  )}
                  <ClosedReasons row={s} actions={surveyActions(s)} skip={sharedReasons(rows, surveyActions)} />
                </div>
                {linksOf === s.id && (
                  <div className="mt-2">
                    <EvidenceLinks projectId={projectId} ownerKind="preservation" ownerId={s.id} row={s} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section
        testId="expert-section"
        title={t('qualityConcept.expert.title', { defaultValue: 'Expert reports' })}
        description={t('qualityConcept.expert.body', {
          defaultValue: 'Reports the project orders from an independent expert, with the dates they are due.',
        })}
        action={
          <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setDialog({ kind: 'report', report: null })} data-testid="report-add">
            {t('qualityConcept.expert.add', { defaultValue: 'Plan an expert report' })}
          </Button>
        }
      >
        {(reports.data ?? []).length === 0 ? (
          <Hint testId="reports-empty">
            {t('qualityConcept.expert.empty', {
              defaultValue: 'No expert report planned. Add one when the project needs an independent opinion, for example on the facade or the fire protection.',
            })}
          </Hint>
        ) : (
          <ul className="divide-y divide-border-light" data-testid="report-list">
            {sharedReasons(reports.data ?? [], planRowActions).length > 0 && (
              <li>
                <SharedReasons codes={sharedReasons(reports.data ?? [], planRowActions)} />
              </li>
            )}
            {(reports.data ?? []).map((r) => (
              <li key={r.id} className="py-2" data-testid="report-entry">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium text-content-primary">{r.subject}</span>
                  <StateBadge map={EXPERT_STATE} tones={EXPERT_TONE} code={r.state} />
                  {r.frequency && (
                    <span className="text-xs text-content-secondary">{vocabOrRaw(t as TFn, EXPERT_FREQUENCY, r.frequency)}</span>
                  )}
                  {r.due_dates.length > 0 && (
                    <span className="text-xs text-content-secondary">
                      {t('qualityConcept.expert.due', { defaultValue: 'Due: {{dates}}', dates: fmtList(r.due_dates.map((d) => fmtDate(d))) })}
                    </span>
                  )}
                  <span className="ml-auto flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setLinksOf(linksOf === r.id ? null : r.id)} aria-expanded={linksOf === r.id}>
                      {t('qualityConcept.evidence.title', { defaultValue: 'Linked records' })}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Pencil size={14} />}
                      aria-label={t('qualityConcept.common.edit', { defaultValue: 'Edit' })}
                      {...gate(t as TFn, r, 'edit')}
                      onClick={() => setDialog({ kind: 'report', report: r })}
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={14} />}
                      aria-label={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
                      {...gate(t as TFn, r, 'delete')}
                      onClick={() => setRemoving({ report: r })}
                    />
                  </span>
                </div>
                {r.trigger && (
                  <p className="mt-0.5 text-xs text-content-tertiary">{vocabOrRaw(t as TFn, EXPERT_TRIGGER, r.trigger)}</p>
                )}
                <ClosedReasons row={r} actions={planRowActions()} skip={sharedReasons(reports.data ?? [], planRowActions)} />
                {linksOf === r.id && (
                  <div className="mt-2">
                    <EvidenceLinks projectId={projectId} ownerKind="expert_report" ownerId={r.id} row={r} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {dialog?.kind === 'survey' && <SurveyDialog {...props} survey={dialog.survey} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'action' && (
        <SurveyActionDialog {...props} survey={dialog.survey} action={dialog.action} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === 'pair' && <PairDialog {...props} survey={dialog.survey} all={rows} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'report' && <ReportDialog {...props} report={dialog.report} onClose={() => setDialog(null)} />}
      <ConfirmDialog
        open={!!removing}
        variant="danger"
        loading={write.pending}
        title={
          removing?.report
            ? t('qualityConcept.expert.remove_title', { defaultValue: 'Remove this expert report?' })
            : t('qualityConcept.preservation.remove_title', { defaultValue: 'Remove this planned survey?' })
        }
        message={
          removing?.report
            ? t('qualityConcept.expert.remove_body', { defaultValue: 'The planned report is removed from the project.' })
            : t('qualityConcept.preservation.remove_body', {
                defaultValue: 'Only a survey that has not been recorded yet can be removed.',
              })
        }
        confirmLabel={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
        cancelLabel={t('qualityConcept.common.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const row = removing;
          setRemoving(null);
          if (row?.report) write.send(() => deleteExpertReport(projectId, row.report!.id));
          else if (row?.survey) write.send(() => deleteSurvey(projectId, row.survey!.id));
        }}
      />
    </div>
  );
}

function SurveyDialog({
  projectId,
  catalogue,
  labels,
  survey,
  onClose,
}: PanelProps & { survey: Survey | null; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const subjects = catalogue?.preservation_subjects ?? [];
  const [pickedSubject, setSubject] = useState(survey?.subject_kind ?? '');
  const subject = pickedSubject || subjects[0]?.code || '';
  const [ref, setRef] = useState(survey?.subject_ref ?? '');
  const [address, setAddress] = useState(survey?.address ?? '');
  const [phase, setPhase] = useState(survey?.phase ?? 'before');
  const [triggers, setTriggers] = useState<string[]>(survey?.influence_triggers ?? []);
  const [methods, setMethods] = useState<string[]>(survey?.methods ?? ['photo']);
  const [planned, setPlanned] = useState(survey?.planned_date ?? '');
  const [owner, setOwner] = useState(survey?.owner_contact_id ?? '');
  const [surveyor, setSurveyor] = useState(survey?.surveyor_contact_id ?? '');
  const problem = !subject
    ? t('qualityConcept.preservation.problem_subject', { defaultValue: 'Choose what is surveyed' })
    : !ref.trim()
      ? t('qualityConcept.preservation.problem_ref', { defaultValue: 'Give the subject a short reference' })
      : null;

  return (
    <FormDialog
      open
      testId="survey-dialog"
      title={
        survey
          ? t('qualityConcept.preservation.edit_title', { defaultValue: 'Edit survey' })
          : t('qualityConcept.preservation.add', { defaultValue: 'Plan a survey' })
      }
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={problem}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(
          () =>
            survey
              ? patchSurvey(projectId, survey.id, {
                  address: address.trim(),
                  influence_triggers: triggers,
                  methods,
                  planned_date: planned || null,
                  ...refChange('owner_contact_id', survey.owner_contact_id, owner),
                  ...refChange('surveyor_contact_id', survey.surveyor_contact_id, surveyor),
                })
              : createSurvey(projectId, {
                  subject_kind: subject,
                  subject_ref: ref.trim(),
                  address: address.trim(),
                  influence_triggers: triggers,
                  phase,
                  methods,
                  planned_date: planned || null,
                  ...refChange('owner_contact_id', null, owner),
                  ...refChange('surveyor_contact_id', null, surveyor),
                }),
          onClose,
        )
      }
    >
      <div className="grid gap-3 md:grid-cols-3">
        <Field required label={t('qualityConcept.preservation.subject', { defaultValue: 'What is surveyed' })}>
          <select className={inputCls} value={subject} disabled={!!survey} onChange={(e) => setSubject(e.target.value)} data-testid="survey-subject">
            {subjects.map((s) => (
              <option key={s.code} value={s.code}>
                {nameIn(labels, subjects, s.code)}
              </option>
            ))}
          </select>
        </Field>
        <Field required label={t('qualityConcept.packages.ref', { defaultValue: 'Reference' })}>
          <input className={inputCls} value={ref} disabled={!!survey} onChange={(e) => setRef(e.target.value)} data-testid="survey-ref" />
        </Field>
        <Field label={t('qualityConcept.preservation.phase', { defaultValue: 'When' })}>
          {survey ? (
            <p className="py-1.5 text-sm text-content-primary">{vocab(t as TFn, SURVEY_PHASE, survey.phase)}</p>
          ) : (
            <VocabSelect map={SURVEY_PHASE} codes={PHASES} value={phase} onChange={setPhase} />
          )}
        </Field>
      </div>
      <Field label={t('qualityConcept.preservation.address', { defaultValue: 'Address or location' })}>
        <input className={inputCls} value={address} onChange={(e) => setAddress(e.target.value)} />
      </Field>
      <div>
        <p className="mb-1 text-xs font-medium text-content-secondary">
          {t('qualityConcept.preservation.triggers', { defaultValue: 'Works that can affect it' })}
        </p>
        <VocabChecks map={INFLUENCE_TRIGGER} codes={TRIGGERS} value={triggers} onChange={setTriggers} />
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-content-secondary">
          {t('qualityConcept.preservation.methods', { defaultValue: 'How the condition is recorded' })}
        </p>
        <VocabChecks map={SURVEY_METHOD} codes={METHODS} value={methods} onChange={setMethods} />
      </div>
      <Field label={t('qualityConcept.acceptance.planned_date', { defaultValue: 'Planned date' })}>
        <input type="date" className={`${inputCls} w-auto`} value={planned} onChange={(e) => setPlanned(e.target.value)} />
      </Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={t('qualityConcept.preservation.owner', { defaultValue: 'Owner of the neighbouring property' })}>
          <OptionPicker projectId={projectId} kind="contact" value={owner} onChange={setOwner} currentLabel={survey?.owner_contact_label} testId="survey-owner" />
        </Field>
        <Field label={t('qualityConcept.preservation.surveyor', { defaultValue: 'Surveyor' })}>
          <OptionPicker projectId={projectId} kind="contact" value={surveyor} onChange={setSurveyor} currentLabel={survey?.surveyor_contact_label} testId="survey-surveyor" />
        </Field>
      </div>
    </FormDialog>
  );
}

function SurveyActionDialog({
  projectId,
  survey,
  action,
  onClose,
}: PanelProps & { survey: Survey; action: SurveyAction; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [on, setOn] = useState('');
  const [note, setNote] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const wantsReason = needsRationale('preservation', action);
  const asksAcknowledgment = action === 'record_survey' || action === 'issue_report';

  return (
    <FormDialog
      open
      size="sm"
      testId="survey-action-dialog"
      title={vocab(t as TFn, SURVEY_ACTION, action)}
      subtitle={survey.subject_ref}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={wantsReason && !note.trim() ? t('qualityConcept.common.problem_reason', { defaultValue: 'Write down the reason' }) : null}
      submitLabel={vocab(t as TFn, SURVEY_ACTION, action)}
      onSubmit={() =>
        write.send(
          () =>
            surveyAction(projectId, survey.id, {
              action,
              on: on || null,
              note: note.trim(),
              ...(asksAcknowledgment ? { owner_acknowledged: acknowledged } : {}),
            }),
          onClose,
        )
      }
    >
      <Field
        label={t('qualityConcept.common.date', { defaultValue: 'Date' })}
        hint={t('qualityConcept.common.date_today_hint', { defaultValue: 'Leave empty for today.' })}
      >
        <input type="date" className={inputCls} value={on} onChange={(e) => setOn(e.target.value)} />
      </Field>
      {asksAcknowledgment && (
        <label className="flex items-start gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.target.checked)}
            data-testid="survey-acknowledge"
          />
          {t('qualityConcept.preservation.acknowledge', { defaultValue: 'The owner has acknowledged the record' })}
        </label>
      )}
      <Field
        required={wantsReason}
        label={
          wantsReason
            ? t('qualityConcept.common.reason', { defaultValue: 'Reason' })
            : t('qualityConcept.common.note', { defaultValue: 'Note' })
        }
      >
        <textarea rows={2} className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} data-testid="survey-action-note" />
      </Field>
    </FormDialog>
  );
}

function PairDialog({ projectId, survey, all, onClose }: PanelProps & { survey: Survey; all: Survey[]; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const befores = all.filter((s) => s.phase === 'before' && s.subject_ref === survey.subject_ref && s.id !== survey.id);
  const [picked, setPicked] = useState('');
  const beforeId = picked || befores[0]?.id || '';

  return (
    <FormDialog
      open
      size="sm"
      testId="survey-pair-dialog"
      title={t('qualityConcept.preservation.pair', { defaultValue: 'Pair with the before survey' })}
      subtitle={t('qualityConcept.preservation.pair_body', {
        defaultValue: 'An after survey is compared with the before survey of the same subject.',
      })}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={
        beforeId
          ? null
          : t('qualityConcept.preservation.pair_none', { defaultValue: 'There is no before survey of this subject yet' })
      }
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() => write.send(() => pairSurvey(projectId, survey.id, beforeId), onClose)}
    >
      <Field label={t('qualityConcept.preservation.before_survey', { defaultValue: 'Before survey' })}>
        <select className={inputCls} value={beforeId} onChange={(e) => setPicked(e.target.value)}>
          {befores.map((b) => (
            <option key={b.id} value={b.id}>
              {b.survey_date ? fmtDate(b.survey_date) : b.planned_date ? fmtDate(b.planned_date) : b.subject_ref}
            </option>
          ))}
        </select>
      </Field>
    </FormDialog>
  );
}

function ReportDialog({ projectId, report, onClose }: PanelProps & { report: ExpertReport | null; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [subject, setSubject] = useState(report?.subject ?? '');
  const [trigger, setTrigger] = useState(report?.trigger ?? '');
  const [frequency, setFrequency] = useState(report?.frequency ?? '');
  const [dates, setDates] = useState<string[]>(report?.due_dates ?? []);
  const [day, setDay] = useState('');
  const [state, setState] = useState<ExpertReportState>(report?.state ?? 'planned');
  const [expert, setExpert] = useState(report?.expert_contact_id ?? '');
  const body = {
    subject: subject.trim(),
    trigger: trigger.trim(),
    frequency: frequency.trim(),
    due_dates: dates,
    state,
    ...refChange('expert_contact_id', report?.expert_contact_id, expert),
  };

  return (
    <FormDialog
      open
      testId="report-dialog"
      title={
        report
          ? t('qualityConcept.expert.edit_title', { defaultValue: 'Edit expert report' })
          : t('qualityConcept.expert.add', { defaultValue: 'Plan an expert report' })
      }
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={subject.trim() ? null : t('qualityConcept.expert.problem_subject', { defaultValue: 'Say what the report is about' })}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(() => (report ? patchExpertReport(projectId, report.id, body) : createExpertReport(projectId, body)), onClose)
      }
    >
      <Field required label={t('qualityConcept.expert.subject', { defaultValue: 'What the report is about' })}>
        <input className={inputCls} value={subject} onChange={(e) => setSubject(e.target.value)} data-testid="report-subject" />
      </Field>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={t('qualityConcept.expert.trigger', { defaultValue: 'What sets it off' })}>
          <select className={inputCls} value={trigger} onChange={(e) => setTrigger(e.target.value)} data-testid="report-trigger">
            <option value="">{t('qualityConcept.common.none', { defaultValue: 'None' })}</option>
            {/* A value an older record holds as free text stays selectable until it is replaced. */}
            {trigger && !EXPERT_TRIGGER[trigger] && <option value={trigger}>{trigger}</option>}
            {Object.keys(EXPERT_TRIGGER).map((code) => (
              <option key={code} value={code}>
                {vocab(t as TFn, EXPERT_TRIGGER, code)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('qualityConcept.expert.frequency', { defaultValue: 'How often' })}>
          <select className={inputCls} value={frequency} onChange={(e) => setFrequency(e.target.value)} data-testid="report-frequency">
            <option value="">{t('qualityConcept.common.none', { defaultValue: 'None' })}</option>
            {/* A value an older record holds as free text stays selectable until it is replaced. */}
            {frequency && !EXPERT_FREQUENCY[frequency] && <option value={frequency}>{frequency}</option>}
            {Object.keys(EXPERT_FREQUENCY).map((code) => (
              <option key={code} value={code}>
                {vocab(t as TFn, EXPERT_FREQUENCY, code)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('qualityConcept.expert.state', { defaultValue: 'Status' })}>
          <VocabSelect map={EXPERT_STATE} codes={EXPERT_STATES} value={state} onChange={(v) => setState(v as ExpertReportState)} />
        </Field>
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-content-secondary">
          {t('qualityConcept.expert.due_dates', { defaultValue: 'Due dates' })}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            className={`${inputCls} w-auto`}
            value={day}
            aria-label={t('qualityConcept.expert.due_dates', { defaultValue: 'Due dates' })}
            onChange={(e) => setDay(e.target.value)}
          />
          <Button
            variant="secondary"
            size="sm"
            disabled={!day || dates.includes(day)}
            onClick={() => {
              setDates((all) => [...all, day].sort());
              setDay('');
            }}
          >
            {t('qualityConcept.common.add', { defaultValue: 'Add' })}
          </Button>
          {dates.map((d) => (
            <button
              key={d}
              type="button"
              className="rounded-full border border-border-light px-2 py-0.5 text-xs text-content-secondary"
              title={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
              onClick={() => setDates((all) => all.filter((x) => x !== d))}
            >
              {fmtDate(d)}
            </button>
          ))}
        </div>
      </div>
      <Field label={t('qualityConcept.expert.expert', { defaultValue: 'Expert' })}>
        <OptionPicker projectId={projectId} kind="contact" value={expert} onChange={setExpert} currentLabel={report?.expert_contact_label} testId="report-expert" />
      </Field>
    </FormDialog>
  );
}
