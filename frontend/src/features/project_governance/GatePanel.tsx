// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One gate: what blocks it, how ready each area is and on what evidence, and
// every attempt decided so far with the snapshot it froze. A decided gate can
// be reopened from here, and one passed with conditions can take a further
// condition.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  CircleDashed,
  ExternalLink,
  History,
  Paperclip,
  Plus,
  Undo2,
  XCircle,
} from 'lucide-react';

import { ApprovalInstanceDetailDrawer } from '@/features/approval-routes/ApprovalInstanceDetailDrawer';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import {
  confirmCheck,
  decideGate,
  governanceErrorCode,
  governanceViolations,
  localToday,
  markCheckNotApplicable,
  prepareGate,
  reopenGate,
  resumeGate,
  submitGate,
  type CheckStatus,
  type DecisionInput,
  type EvidenceState,
  type GateArea,
  type GateDecision,
  type GateDetail,
  type GovernanceModel,
  type Rag,
  type Violation,
} from './api';
import {
  canAddCondition,
  canConfirmCheck,
  canManage,
  canDecide,
  canReopen,
  canResume,
  canSubmitGate,
  reasonOfCode,
  type Verdict,
  type Viewer,
} from './access';
import { DecisionDialog } from './DecisionDialog';
import { GateConditionForm } from './GateConditionForm';
import { ReadinessCriteria } from './ReadinessCriteria';
import {
  CHECK_TONE,
  DOCUMENT_TONE,
  GATE_STATUS_TONE,
  OUTCOME_TONE,
  PersonChip,
  ReasonedButton,
  ToneBadge,
} from './GovernanceBits';
import { useGateDetail, useInvalidateGovernance } from './hooks';
import { ReopenDialog } from './ReopenDialog';
import {
  CHECK_STATUS,
  DOCUMENT_STATUS,
  GATE_STATUS,
  OUTCOME,
  catalogueIdOf,
  catalogueName,
  errorText,
  evidenceDetail,
  evidenceMark,
  evidenceText,
  refusalText,
  vocab,
  type LabelContext,
} from './labels';

export interface GatePanelProps {
  projectId: string;
  gateId: string;
  model: GovernanceModel;
  viewer: Viewer;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onBack: () => void;
  onOpenArea: (areaId: string) => void;
  /** Opens the phase model settings, where the approval route is chosen. */
  onOpenModel?: () => void;
}

const CONFIRMABLE: Array<Exclude<CheckStatus, 'not_applicable'>> = ['ready', 'ready_with_risks', 'not_ready'];

/**
 * Refusals of a decision that are about who decides, not about what the
 * decision says. Only these close the dialog's door; a missing rationale or
 * an open blocker is fixed inside the dialog.
 */
const PERSON_REFUSALS = new Set(['decider_is_area_owner', 'decider_not_entitled', 'missing_permission']);

/** A refusal the button shows until the server's own flags arrive again. */
interface Refusal {
  verdict: Verdict;
  /** `dataUpdatedAt` of the gate detail the refused request was made on. */
  seenAt: number;
}

export function BlockerList({
  blockers,
  areaName,
}: {
  blockers: Violation[];
  areaName: (code: string) => string;
}) {
  const { t } = useTranslation();
  if (blockers.length === 0) {
    return (
      <p className="flex items-center gap-2 text-sm text-semantic-success" data-testid="no-blockers">
        <CheckCircle2 size={15} aria-hidden />
        {t('governance.project.gate.no_blockers', { defaultValue: 'Nothing blocks this gate.' })}
      </p>
    );
  }
  return (
    <ul className="space-y-1.5" data-testid="blocker-list">
      {blockers.map((b, i) => (
        <li key={`${b.code}-${b.area_code ?? ''}-${b.ref ?? ''}-${i}`} className="flex items-start gap-2 text-sm">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[#b45309]" aria-hidden />
          <span>
            <span className="text-content-primary">{errorText(t, b.code, b.message)}</span>
            {b.area_code && <span className="ml-1 text-content-tertiary">({areaName(b.area_code)})</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function EvidenceIcon({ state }: { state: EvidenceState }) {
  if (state === 'warning') return <AlertTriangle size={13} className="text-[#b45309]" aria-hidden />;
  if (state === 'met') return <CheckCircle2 size={13} className="text-semantic-success" aria-hidden />;
  if (state === 'not_met') return <XCircle size={13} className="text-semantic-error" aria-hidden />;
  return <CircleDashed size={13} className="text-content-tertiary" aria-hidden />;
}

function AreaReadiness({
  projectId,
  gateId,
  area,
  model,
  viewer,
  labels,
  catalogueId,
  personName,
  onOpenArea,
  onChanged,
  detailCan,
}: {
  detailCan: Pick<GateDetail, 'can'>;
  projectId: string;
  gateId: string;
  area: GateArea;
  model: GovernanceModel;
  viewer: Viewer;
  labels: LabelContext;
  catalogueId: string;
  personName: GatePanelProps['personName'];
  onOpenArea: (areaId: string) => void;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState<Exclude<CheckStatus, 'not_applicable'>>('ready');
  const [note, setNote] = useState('');
  const [naMode, setNaMode] = useState(false);
  const verdict = canConfirmCheck(viewer, model, area, detailCan);
  const check = area.check;
  const checkStatus: CheckStatus = !area.applicable ? 'not_applicable' : check?.status ?? 'not_assessed';
  const name = catalogueName(labels, { kind: 'area', code: area.code, catalogueId, label: area.name });

  const save = useMutation({
    mutationFn: () =>
      naMode
        ? markCheckNotApplicable(projectId, gateId, area.area_id, note.trim())
        : confirmCheck(projectId, gateId, area.area_id, { status, rag: ragOf(status), note: note.trim() }),
    onSuccess: () => {
      setEditing(false);
      setNote('');
      onChanged();
    },
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
  });
  // The form opens on what was confirmed last, so saving again never wipes the note by accident.
  const openForm = () => {
    const last = area.check;
    setNaMode(last?.status === 'not_applicable');
    setStatus(last && last.status !== 'not_applicable' && last.status !== 'not_assessed' ? last.status : 'ready');
    setNote(last?.status === 'not_applicable' ? last.na_rationale : last?.note ?? '');
    setEditing(true);
  };

  const ownerName = area.owner_user_id
    ? personName(area.owner_user_id) ?? t('governance.project.unknown_person', { defaultValue: 'Project member' })
    : null;

  return (
    <div className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="gate-area">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onOpenArea(area.area_id)}
          className="text-sm font-semibold text-content-primary hover:text-oe-blue"
        >
          {name}
        </button>
        <ToneBadge tone={check?.stale ? 'warning' : CHECK_TONE[checkStatus]}>
          {check?.stale
            ? t('governance.project.check_stale', { defaultValue: 'Confirm again' })
            : vocab(t, CHECK_STATUS, checkStatus)}
        </ToneBadge>
        <span className="ml-auto">
          <PersonChip name={ownerName} />
        </span>
      </div>
      {check?.note && <p className="mt-1 text-xs text-content-secondary">{check.note}</p>}
      {check?.confirmed_at && (
        <p className="mt-0.5 text-2xs text-content-tertiary">
          {t('governance.project.gate.confirmed_by', {
            defaultValue: 'Confirmed by {{name}} on {{date}}',
            name: personName(check.confirmed_by) ?? t('governance.project.unknown_person', { defaultValue: 'Project member' }),
            date: fmtDate(check.confirmed_at),
          })}
        </p>
      )}

      {area.documents.length > 0 && (
        <ul className="mt-2 space-y-1">
          {area.documents.map((d) => (
            <li key={d.document_id} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-content-primary">{catalogueName(labels, { kind: 'doc', code: d.doc_type, catalogueId, label: d.name })}</span>
              <ToneBadge tone={DOCUMENT_TONE[d.status]}>{vocab(t, DOCUMENT_STATUS, d.status)}</ToneBadge>
              {d.required && (
                <span className="text-2xs text-content-tertiary">
                  {t('governance.project.gate.required_here', { defaultValue: 'Required at this gate' })}
                </span>
              )}
              {!d.container_id && (
                <button
                  type="button"
                  onClick={() => onOpenArea(area.area_id)}
                  className="inline-flex items-center gap-1 text-2xs font-medium text-semantic-error underline-offset-2 hover:underline"
                  data-testid="gate-document-attach"
                >
                  <Paperclip size={11} aria-hidden />
                  {t('governance.project.gate.attach_file', { defaultValue: 'No file yet: attach one' })}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {area.evidence.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-border-light pt-2" data-testid="evidence-list">
          {area.evidence.map((e) => (
            <li key={e.code} className="flex items-start gap-1.5 text-xs text-content-secondary">
              <EvidenceIcon state={e.state} />
              <span>
                {e.link?.href ? (
                  <Link to={e.link.href} className="text-oe-blue hover:underline" data-testid="evidence-link">
                    {evidenceText(t, labels, e)}
                  </Link>
                ) : (
                  evidenceText(t, labels, e)
                )}
                {evidenceDetail(t, labels, e) && (
                  <span className="text-content-tertiary"> - {evidenceDetail(t, labels, e)}</span>
                )}
                {e.blocking && e.state === 'not_met' && (
                  <span className="ml-1 font-medium text-semantic-error">
                    {t('governance.project.gate.evidence_blocking', { defaultValue: 'blocking' })}
                  </span>
                )}
                {e.state === 'warning' && (
                  <span className="ml-1 font-medium text-[#b45309]" data-testid="evidence-warning">
                    {evidenceMark(t, e.state)}
                  </span>
                )}
                {e.needs_acknowledgement && (
                  <span className="ml-1 font-medium text-[#b45309]" data-testid="evidence-needs-acknowledgement">
                    {t('governance.project.gate.evidence_needs_acknowledgement', {
                      defaultValue: 'to confirm at the decision',
                    })}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      <ReadinessCriteria
        projectId={projectId}
        gateId={gateId}
        area={area}
        labels={labels}
        catalogueId={catalogueId}
        personName={personName}
        onChanged={onChanged}
      />

      <div className="mt-2">
        {!editing ? (
          <ReasonedButton size="sm" variant="secondary" verdict={verdict} onClick={openForm}>
            {t('governance.project.gate.confirm_readiness', { defaultValue: 'Confirm readiness' })}
          </ReasonedButton>
        ) : (
          <div className="space-y-2 rounded-md bg-surface-secondary p-2">
            <div className="flex flex-wrap gap-3 text-sm">
              {CONFIRMABLE.map((s) => (
                <label key={s} className="inline-flex items-center gap-1.5">
                  <input type="radio" checked={!naMode && status === s} onChange={() => { setNaMode(false); setStatus(s); }} />
                  {vocab(t, CHECK_STATUS, s)}
                </label>
              ))}
              <label className="inline-flex items-center gap-1.5">
                <input type="radio" checked={naMode} onChange={() => setNaMode(true)} />
                {vocab(t, CHECK_STATUS, 'not_applicable')}
              </label>
            </div>
            <textarea
              rows={2}
              className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
              aria-label={t('governance.project.gate.check_note', { defaultValue: 'Note' })}
              placeholder={
                naMode
                  ? t('governance.project.gate.na_reason', { defaultValue: 'Why this area does not apply at this gate (required)' })
                  : t('governance.project.gate.check_note_placeholder', { defaultValue: 'What the assessment rests on' })
              }
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <div className="flex gap-2">
              <Button size="sm" loading={save.isPending} disabled={naMode && !note.trim()} onClick={() => save.mutate()}>
                {t('governance.project.save', { defaultValue: 'Save' })}
              </Button>
              <Button size="sm" variant="ghost" disabled={save.isPending} onClick={() => setEditing(false)}>
                {t('governance.project.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ragOf(status: CheckStatus): Rag {
  if (status === 'ready') return 'green';
  if (status === 'ready_with_risks') return 'amber';
  if (status === 'not_ready') return 'red';
  return '';
}

export function SnapshotView({
  decision,
  labels,
  catalogueId,
}: {
  decision: GateDecision;
  labels: LabelContext;
  catalogueId: string;
}) {
  const { t } = useTranslation();
  const docs = decision.snapshot.documents ?? [];
  const checks = decision.snapshot.checks ?? [];
  const acknowledged = decision.snapshot.acknowledged_evidence ?? [];
  return (
    <div className="mt-2 space-y-2 rounded-md bg-surface-secondary p-3 text-xs" data-testid="snapshot-view">
      {docs.length === 0 && checks.length === 0 && (
        <p className="text-content-tertiary">
          {t('governance.project.gate.snapshot_empty', { defaultValue: 'This decision froze no documents or checks.' })}
        </p>
      )}
      {docs.length > 0 && (
        <table className="w-full">
          <thead>
            <tr className="text-left text-content-tertiary">
              <th className="py-0.5 font-medium">{t('governance.project.gate.snapshot_document', { defaultValue: 'Frame document' })}</th>
              <th className="py-0.5 font-medium">{t('governance.project.gate.snapshot_state', { defaultValue: 'State' })}</th>
              <th className="py-0.5 font-medium">{t('governance.project.gate.snapshot_revision', { defaultValue: 'Revision' })}</th>
              <th className="py-0.5 font-medium">{t('governance.project.gate.snapshot_hash', { defaultValue: 'Content hash' })}</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.document_id} className="border-t border-border-light">
                <td className="py-0.5">
                  {catalogueName(labels, { kind: 'area', code: d.area_code, catalogueId })} /{' '}
                  {catalogueName(labels, { kind: 'doc', code: d.doc_type, catalogueId })}
                </td>
                <td className="py-0.5">{vocab(t, DOCUMENT_STATUS, d.status as never)}</td>
                <td className="py-0.5 font-mono">{d.revision_id ? d.revision_id.slice(0, 8) : '-'}</td>
                <td className="py-0.5 font-mono">{d.content_hash ? d.content_hash.slice(0, 12) : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {checks.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {checks.map((c) => (
            <li key={c.area_code}>
              {catalogueName(labels, { kind: 'area', code: c.area_code, catalogueId })}:{' '}
              {vocab(t, CHECK_STATUS, c.status as never)}
            </li>
          ))}
        </ul>
      )}
      {acknowledged.length > 0 && (
        <div data-testid="snapshot-acknowledged">
          <p className="font-medium text-content-secondary">
            {t('governance.project.gate.snapshot_acknowledged', {
              defaultValue: 'Confirmed as seen without an answer from the module',
            })}
          </p>
          <ul className="mt-0.5 space-y-0.5">
            {acknowledged.map((e) => (
              <li key={[e.area_code, e.code].join(' ')}>
                {catalogueName(labels, { kind: 'area', code: e.area_code, catalogueId })}: {evidenceText(t, labels, e)}{' '}
                <span className="text-content-tertiary">({evidenceMark(t, e.state)})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function GatePanel({
  projectId,
  gateId,
  model,
  viewer,
  labels,
  personName,
  onBack,
  onOpenArea,
  onOpenModel,
}: GatePanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const query = useGateDetail(projectId, gateId);
  const invalidate = useInvalidateGovernance(projectId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [openSnapshot, setOpenSnapshot] = useState<string | null>(null);
  const [serverViolations, setServerViolations] = useState<Violation[]>([]);
  const [serverError, setServerError] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [reopenError, setReopenError] = useState<string | null>(null);
  const [conditionOpen, setConditionOpen] = useState(false);
  const [routeMissing, setRouteMissing] = useState(false);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const today = localToday();

  const onFail = (err: unknown) => addToast({ type: 'error', title: refusalText(t, err) });
  const prepare = useMutation({ mutationFn: () => prepareGate(projectId, gateId), onSuccess: invalidate, onError: onFail });
  const submit = useMutation({
    mutationFn: () => submitGate(projectId, gateId),
    onSuccess: () => {
      setRouteMissing(false);
      invalidate();
    },
    onError: (err) => {
      // Nothing is wrong with the gate: the project has no route chosen yet,
      // so the answer stays on screen and leads to where one is chosen.
      if (governanceErrorCode(err) === 'no_decision_route') {
        setRouteMissing(true);
        return;
      }
      onFail(err);
    },
  });
  const resume = useMutation({
    mutationFn: () => resumeGate(projectId, gateId),
    onSuccess: invalidate,
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
  });
  const reopen = useMutation({
    mutationFn: (body: { rationale: string }) => reopenGate(projectId, gateId, body),
    onSuccess: () => {
      setReopenOpen(false);
      setReopenError(null);
      addToast({ type: 'success', title: t('governance.project.reopen.done', { defaultValue: 'Gate reopened' }) });
      invalidate();
    },
    onError: (err) => setReopenError(refusalText(t, err)),
  });
  const closeDecision = () => {
    setDialogOpen(false);
    setServerViolations([]);
    setServerError(null);
  };
  const decide = useMutation({
    mutationFn: (input: DecisionInput) => decideGate(projectId, gateId, input),
    onSuccess: () => {
      setDialogOpen(false);
      setServerViolations([]);
      setServerError(null);
      addToast({ type: 'success', title: t('governance.project.decision.recorded', { defaultValue: 'Decision recorded' }) });
      invalidate();
    },
    onError: (err) => {
      const code = governanceErrorCode(err);
      setServerViolations(governanceViolations(err));
      setServerError(code ? errorText(t, code, getErrorMessage(err)) : getErrorMessage(err));
      if (code && PERSON_REFUSALS.has(code)) {
        // The server knows better than the flags this screen holds. Show its
        // reason on the button, and ask for the flags again: the refusal lasts
        // only until they arrive, so one refused try never locks the button.
        setRefusal({ verdict: reasonOfCode(code), seenAt: query.dataUpdatedAt });
        invalidate();
      }
    },
  });

  // Only a gate that never arrived replaces the screen. A refetch that fails
  // after a write keeps what is shown, and an open dialog with its draft.
  if (!query.data) {
    return (
      <div className="space-y-4" data-testid="gate-unavailable">
        <Button size="sm" variant="ghost" icon={<ArrowLeft size={14} />} onClick={onBack}>
          {t('governance.project.back_to_matrix', { defaultValue: 'Back to matrix' })}
        </Button>
        {query.isError ? (
          <ErrorState
            title={t('governance.project.gate.load_failed', { defaultValue: 'The gate could not be loaded' })}
            hint={getErrorMessage(query.error)}
            onRetry={() => query.refetch()}
          />
        ) : (
          <SkeletonTable rows={6} columns={3} />
        )}
      </div>
    );
  }
  const detail: GateDetail = query.data;
  const gate = detail.gate;
  const catalogueId = catalogueIdOf(gate.catalogue_id) ?? model.catalogue_id;
  const areaName = (code: string) => catalogueName(labels, { kind: 'area', code, catalogueId });
  const liveRefusal = refusal && refusal.seenAt === query.dataUpdatedAt ? refusal.verdict : null;
  const decideVerdict = liveRefusal ?? canDecide(model, detail);
  const submitVerdict = canSubmitGate(model, detail);
  // The server names each frame document in the project's catalogue; a pack catalogue has no locale keys.
  const documentLabels = new Map(detail.areas.flatMap((a) => a.documents.map((d) => [d.doc_type, d.name] as const)));
  const documentName = (code: string) =>
    catalogueName(labels, { kind: 'doc', code, catalogueId, label: documentLabels.get(code) });
  const gateName = catalogueName(labels, { kind: 'gate', code: gate.code, catalogueId, label: gate.name });
  const fromPhase = model.phases.find((ph) => ph.code === gate.from_phase);
  const fromPhaseName = catalogueName(labels, { kind: 'phase', code: gate.from_phase, catalogueId, label: fromPhase?.name });
  const passedWithConditions = detail.decisions.some((d) => d.outcome === 'go_with_conditions');

  return (
    <div className="space-y-5" data-testid="gate-panel">
      {query.isError && (
        <p className="flex flex-wrap items-center gap-2 text-sm text-semantic-error" role="alert" data-testid="gate-refresh-failed">
          {t('governance.project.gate.refresh_failed', {
            defaultValue: 'The gate could not be refreshed, so what is shown may be out of date.',
          })}
          <Button size="sm" variant="ghost" onClick={() => query.refetch()}>
            {t('governance.project.retry', { defaultValue: 'Try again' })}
          </Button>
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="ghost" icon={<ArrowLeft size={14} />} onClick={onBack}>
          {t('governance.project.back_to_matrix', { defaultValue: 'Back to matrix' })}
        </Button>
        <h2 className="text-lg font-semibold text-content-primary">
          {gateName}
        </h2>
        <ToneBadge tone={GATE_STATUS_TONE[gate.status]}>{vocab(t, GATE_STATUS, gate.status)}</ToneBadge>
        <span className="text-xs text-content-tertiary">
          {t('governance.project.gate.attempt', { defaultValue: 'Attempt {{n}}', n: gate.attempt_no })}
        </span>
        {gate.status === 'on_hold' && gate.hold_resume_date && (
          <span className="text-xs text-content-secondary">
            {t('governance.project.gate.resumes_on', { defaultValue: 'Resumes on {{date}}', date: fmtDate(gate.hold_resume_date) })}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-start gap-3">
        {gate.status === 'not_started' && (
          <ReasonedButton
            variant="secondary"
            verdict={detail.can.edit ? (model.stopped ? 'project_stopped' : null) : 'role_edit'}
            loading={prepare.isPending}
            onClick={() => prepare.mutate()}
          >
            {t('governance.project.gate.prepare', { defaultValue: 'Start preparation' })}
          </ReasonedButton>
        )}
        {(gate.status === 'in_preparation' || gate.status === 'not_started') && (
          <ReasonedButton variant="secondary" verdict={submitVerdict} loading={submit.isPending} onClick={() => submit.mutate()}>
            {t('governance.project.gate.submit', { defaultValue: 'Submit for review' })}
          </ReasonedButton>
        )}
        {gate.status === 'in_review' && gate.approval_instance_id && (
          <Button variant="secondary" onClick={() => setApprovalOpen(true)} data-testid="open-approval">
            {t('governance.project.gate.open_approval', { defaultValue: 'Open the approval' })}
          </Button>
        )}
        {gate.status === 'on_hold' && (
          <ReasonedButton
            variant="secondary"
            verdict={canResume(detail)}
            loading={resume.isPending}
            onClick={() => resume.mutate()}
            data-testid="resume-gate"
          >
            {t('governance.project.gate.resume', { defaultValue: 'Resume gate' })}
          </ReasonedButton>
        )}
        {/* A gate on hold is resumed first; the decision button comes back with the review. */}
        {gate.status !== 'decided' && gate.status !== 'on_hold' && (
          <ReasonedButton verdict={decideVerdict} onClick={() => setDialogOpen(true)} data-testid="open-decision">
            {t('governance.project.gate.decide', { defaultValue: 'Record decision' })}
          </ReasonedButton>
        )}
        {gate.status === 'decided' && (
          <ReasonedButton
            variant="secondary"
            icon={<Undo2 size={14} />}
            verdict={canReopen(detail)}
            onClick={() => {
              setReopenError(null);
              setReopenOpen(true);
            }}
            data-testid="open-reopen"
          >
            {t('governance.project.gate.reopen', { defaultValue: 'Reopen gate' })}
          </ReasonedButton>
        )}
        {gate.status === 'decided' && passedWithConditions && !conditionOpen && (
          <ReasonedButton
            variant="secondary"
            icon={<Plus size={14} />}
            verdict={canAddCondition(detail)}
            onClick={() => setConditionOpen(true)}
            data-testid="open-add-condition"
          >
            {t('governance.project.gate.add_condition', { defaultValue: 'Add a condition' })}
          </ReasonedButton>
        )}
      </div>

      {routeMissing && (
        <div
          role="alert"
          data-testid="gate-no-route"
          className="flex flex-wrap items-center gap-3 rounded-lg border border-[#f59e0b]/40 bg-[#f59e0b]/10 p-3 text-sm text-content-primary"
        >
          <span>
            {t('governance.project.gate.no_route', {
              defaultValue:
                'This gate cannot go to review yet: no approval route is chosen for the gate decisions of this project.',
            })}{' '}
            {canManage(model) !== null &&
              t('governance.project.gate.no_route_ask', {
                defaultValue: 'A governance manager chooses it in the phase model settings.',
              })}
          </span>
          {canManage(model) === null && onOpenModel && (
            <Button size="sm" variant="secondary" onClick={onOpenModel} data-testid="gate-open-route">
              {t('governance.project.gate.choose_route', { defaultValue: 'Choose the approval route' })}
            </Button>
          )}
        </div>
      )}

      {conditionOpen && (
        <GateConditionForm
          projectId={projectId}
          gateId={gateId}
          areas={detail.areas}
          areaName={areaName}
          documentName={documentName}
          onCancel={() => setConditionOpen(false)}
          onDone={() => {
            setConditionOpen(false);
            invalidate();
          }}
        />
      )}

      <section>
        <h3 className="mb-2 text-sm font-semibold text-content-primary">
          {t('governance.project.gate.blockers_title', { defaultValue: 'Blockers' })}
        </h3>
        <BlockerList blockers={detail.blockers} areaName={areaName} />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-content-primary">
          {t('governance.project.gate.readiness_title', { defaultValue: 'Readiness per area' })}
        </h3>
        {detail.areas.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('governance.project.gate.no_areas', { defaultValue: 'This gate has no management areas yet.' })}
          </p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {detail.areas.map((a) => (
              <AreaReadiness
                key={a.area_id}
                projectId={projectId}
                gateId={gateId}
                area={a}
                model={model}
                viewer={viewer}
                labels={labels}
                catalogueId={catalogueId}
                personName={personName}
                onOpenArea={onOpenArea}
                onChanged={invalidate}
                detailCan={detail}
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-content-primary">
          <History size={15} aria-hidden />
          {t('governance.project.gate.history_title', { defaultValue: 'Decisions and attempts' })}
        </h3>
        {detail.decisions.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('governance.project.gate.history_empty', {
              defaultValue: 'No decision yet. Once the gate is in review, the decider records it here.',
            })}
          </p>
        ) : (
          <ol className="space-y-2">
            {[...detail.decisions]
              .sort((a, b) => b.attempt_no - a.attempt_no)
              .map((d) => (
                <li key={d.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="decision-entry">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-xs text-content-tertiary">
                      {t('governance.project.gate.attempt', { defaultValue: 'Attempt {{n}}', n: d.attempt_no })}
                    </span>
                    <ToneBadge tone={OUTCOME_TONE[d.outcome]}>{vocab(t, OUTCOME, d.outcome)}</ToneBadge>
                    <span className="text-xs text-content-secondary">
                      {t('governance.project.gate.decided_by', {
                        defaultValue: '{{name}}, {{date}}',
                        name: personName(d.decided_by) ?? t('governance.project.unknown_person', { defaultValue: 'Project member' }),
                        date: fmtDate(d.decided_at),
                      })}
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ml-auto"
                      icon={<ExternalLink size={13} />}
                      onClick={() => setOpenSnapshot(openSnapshot === d.id ? null : d.id)}
                      aria-expanded={openSnapshot === d.id}
                    >
                      {t('governance.project.gate.show_snapshot', { defaultValue: 'Snapshot' })}
                    </Button>
                  </div>
                  {d.rationale && <p className="mt-1 text-sm text-content-secondary">{d.rationale}</p>}
                  {d.proceed_at_risk_areas.length > 0 && (
                    <p className="mt-1 text-xs text-[#b45309]">
                      {t('governance.project.gate.at_risk', {
                        defaultValue: 'Proceeding at risk: {{areas}}',
                        areas: fmtList(d.proceed_at_risk_areas.map(areaName)),
                      })}
                    </p>
                  )}
                  {openSnapshot === d.id && <SnapshotView decision={d} labels={labels} catalogueId={catalogueId} />}
                </li>
              ))}
          </ol>
        )}
      </section>

      {dialogOpen && (
        <DecisionDialog
          open={dialogOpen}
          onClose={closeDecision}
          projectId={projectId}
          detail={detail}
          catalogueId={catalogueId}
          labels={labels}
          today={today}
          busy={decide.isPending}
          serverViolations={serverViolations}
          serverError={serverError}
          onSubmit={(input) => decide.mutate(input)}
          onOpenApproval={
            gate.approval_instance_id
              ? () => {
                  closeDecision();
                  setApprovalOpen(true);
                }
              : undefined
          }
        />
      )}
      <ApprovalInstanceDetailDrawer
        instanceId={approvalOpen ? gate.approval_instance_id : null}
        onClose={() => {
          // A step approved in the drawer changes what this gate allows.
          setApprovalOpen(false);
          invalidate();
        }}
      />
      {reopenOpen && (
        <ReopenDialog
          open={reopenOpen}
          onClose={() => setReopenOpen(false)}
          gate={gate}
          gateName={gateName}
          fromPhaseName={fromPhaseName}
          busy={reopen.isPending}
          serverError={reopenError}
          onSubmit={(body) => reopen.mutate(body)}
        />
      )}
    </div>
  );
}
