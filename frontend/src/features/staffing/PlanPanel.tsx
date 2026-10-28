// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The staffing plan: its state and settings, what still blocks submission,
// the positions per phase with the people on them, and the planned handovers.
//
// The plan is approved at the governance gate of the personnel area, never
// here, so the only state changes this screen offers are "submit for review"
// and "return to draft".

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowRight, KeyRound, Pencil, Plus, Settings2, Trash2, UserPlus, Users } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate, fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import {
  confirmFill,
  deleteFill,
  deleteHandover,
  deletePosition,
  downloadExport,
  endFill,
  requestResource,
  approvePlan,
  returnPlan,
  setPositionStatus,
  staffingViolations,
  submitPlan,
  updateHandover,
  type Fill,
  type Finding,
  type Handover,
  type Phase,
  type Position,
  type SettablePositionStatus,
  type StaffingCatalogue,
  type StaffingPlan,
} from './api';
import {
  FILL_STATUS,
  HANDOVER_STATUS,
  PHASE,
  PLAN_STATUS,
  POSITION_STATUS,
  catalogueName,
  findingText,
  offered,
  positionName,
  vocab,
  whyNot,
  type LabelContext,
} from './labels';
import { ChangeCatalogueDialog, PlanSettingsDialog } from './PlanDialogs';
import { FillDialog, FromCatalogueDialog, HandoverDialog, PositionDialog } from './PositionDialogs';
import { allowedStatusMoves, fteDecimals, groupByPhase, phasesOf, planIsSubmittable } from './rules';
import {
  ClearedBadge,
  ExportButtons,
  FIELD_CLASS,
  FILL_TONE,
  PLAN_TONE,
  POSITION_TONE,
  Refusal,
  ToneBadge,
  personLabel,
  useStaffingAction,
} from './StaffingBits';

export interface PlanPanelProps {
  projectId: string;
  plan: StaffingPlan;
  catalogue: StaffingCatalogue;
  positions: Position[];
  handovers: Handover[];
  findings: Finding[];
  /** People the findings leave out because the reader may not open their file. */
  restrictedPeople?: number;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onChanged: () => void;
}

type Dialog =
  | { kind: 'settings' }
  | { kind: 'catalogue' }
  | { kind: 'position'; position: Position | null }
  | { kind: 'from-catalogue' }
  | { kind: 'fill'; position: Position }
  | { kind: 'handover'; handover: Handover | null }
  | { kind: 'delete-position'; position: Position }
  | null;

const fte = (value: string) => fmtNumber(value, fteDecimals(value));

/** Every finding as a sentence, errors first. Shown before submission and after a refused one. */
export function FindingList({
  findings,
  catalogue,
  labels,
}: {
  findings: Finding[];
  catalogue: StaffingCatalogue | null;
  labels: LabelContext;
}) {
  const sorted = [...findings].sort((a, b) => Number(a.severity !== 'error') - Number(b.severity !== 'error'));
  return (
    <ul className="space-y-1" data-testid="finding-list">
      {sorted.map((f, i) => (
        <li key={`${f.code}:${f.ref}:${i}`} className="flex items-start gap-2 text-sm text-content-primary" data-finding={f.code}>
          <AlertTriangle
            size={14}
            aria-hidden
            className={f.severity === 'error' ? 'mt-0.5 shrink-0 text-semantic-error' : 'mt-0.5 shrink-0 text-[#b45309]'}
          />
          {findingText(labels, catalogue, f)}
        </li>
      ))}
    </ul>
  );
}

export function PlanPanel({
  projectId,
  plan,
  catalogue,
  positions,
  handovers,
  findings,
  restrictedPeople = 0,
  labels,
  personName,
  onChanged,
}: PlanPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [refused, setRefused] = useState<Finding[]>([]);
  // One flag of the server covers everything a plan freezes or a reader may not do:
  // positions, settings, handovers and proposing a person.
  const locked = !plan.can.edit.allowed;
  const lockedReason = whyNot(labels.t, plan.can.edit) || undefined;
  // Submitting, returning and re-pinning the catalogue follow the server's flags, state and permission both.
  // The state only picks which control is on screen: nobody submits an approved plan.
  const maySubmit = plan.can.submit;
  const submittable = maySubmit.applies ?? planIsSubmittable(plan.status);
  const mayReturn = plan.can.return;
  // Offered only where the project uses no gates; with gates the server says the action does not apply.
  const mayApprove = plan.can.approve;
  const byHand = plan.gates_in_use === false;
  const mayRepin = plan.can.change_catalogue;

  const submit = useStaffingAction(
    async () => {
      setRefused([]);
      try {
        return await submitPlan(projectId);
      } catch (err) {
        // A refused submission lists every blocker; keep them on screen, not only in a toast.
        setRefused(staffingViolations(err));
        throw err;
      }
    },
    () => onChanged(),
  );
  const giveBack = useStaffingAction(() => returnPlan(projectId), () => onChanged());
  const approve = useStaffingAction(
    async () => {
      setRefused([]);
      try {
        return await approvePlan(projectId);
      } catch (err) {
        setRefused(staffingViolations(err));
        throw err;
      }
    },
    () => onChanged(),
  );
  const confirm = useStaffingAction(
    (fillId: string) => confirmFill(projectId, fillId),
    (result) => {
      for (const w of result.warnings ?? []) addToast({ type: 'warning', title: findingText(labels, catalogue, w) });
      onChanged();
    },
  );
  const end = useStaffingAction((fillId: string) => endFill(projectId, fillId), () => onChanged());
  const dropFill = useStaffingAction((fillId: string) => deleteFill(projectId, fillId), () => onChanged());
  const moveStatus = useStaffingAction(
    (a: { id: string; status: SettablePositionStatus }) => setPositionStatus(projectId, a.id, a.status),
    () => onChanged(),
  );
  const askResource = useStaffingAction((id: string) => requestResource(projectId, id), () => onChanged());
  const removePosition = useStaffingAction(
    (id: string) => deletePosition(projectId, id),
    () => {
      setDialog(null);
      onChanged();
    },
  );
  const handoverDone = useStaffingAction((id: string) => updateHandover(projectId, id, { status: 'done' }), () => onChanged());
  const handoverRemove = useStaffingAction((id: string) => deleteHandover(projectId, id), () => onChanged());

  const phases = phasesOf(catalogue, positions);
  const groups = groupByPhase(positions, phases);
  // A new position starts in the phase the plan is already furthest into, else in the catalogue's first one.
  const defaultPhase: Phase = groups[groups.length - 1]?.phase ?? phases[0] ?? '';
  const blockers = refused.length > 0 ? refused : findings.filter((f) => f.severity === 'error');
  const fillById = new Map<string, { fill: Fill; position: Position }>();
  for (const p of positions) for (const f of p.fills) fillById.set(f.id, { fill: f, position: p });
  const positionById = new Map(positions.map((p) => [p.id, p]));

  return (
    <div className="space-y-5" data-testid="plan-panel">
      <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="plan-header">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <ToneBadge tone={PLAN_TONE[plan.status]} testId="plan-status">
                {vocab(t, PLAN_STATUS, plan.status)}
              </ToneBadge>
              <span className="text-sm text-content-secondary">
                {catalogue.name_key && labels.exists(catalogue.name_key)
                  ? labels.t(catalogue.name_key)
                  : catalogueLabel(labels, catalogue)}
              </span>
            </div>
            <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <div className="flex gap-1.5">
                <dt className="text-content-tertiary">{t('staffing.plan.commissioning_date', { defaultValue: 'Planned commissioning' })}</dt>
                <dd className="text-content-primary" data-testid="plan-commissioning">
                  {plan.commissioning_date ? fmtDate(plan.commissioning_date) : t('staffing.not_set', { defaultValue: 'Not set' })}
                </dd>
              </div>
              {plan.requires_accommodation && (
                <div className="text-content-primary">
                  {t('staffing.plan.requires_accommodation', { defaultValue: 'Remote site, people need accommodation' })}
                </div>
              )}
            </dl>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ExportButtons download={(format) => downloadExport(projectId, 'plan', format)} />
            <Button
              variant="ghost"
              size="sm"
              icon={<Settings2 size={14} />}
              disabled={locked}
              title={lockedReason}
              onClick={() => setDialog({ kind: 'settings' })}
              data-testid="plan-settings"
            >
              {t('staffing.plan.settings', { defaultValue: 'Plan settings' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={!mayRepin.allowed}
              title={whyNot(labels.t, mayRepin) || undefined}
              onClick={() => setDialog({ kind: 'catalogue' })}
              data-testid="plan-change-catalogue"
            >
              {t('staffing.plan.change_catalogue', { defaultValue: 'Change catalogue' })}
            </Button>
            {submittable && positions.length > 0 && (
              <Button
                size="sm"
                loading={submit.isPending}
                disabled={!maySubmit.allowed}
                title={whyNot(labels.t, maySubmit) || undefined}
                onClick={() => submit.mutate()}
                data-testid="plan-submit"
              >
                {t('staffing.plan.submit', { defaultValue: 'Submit for review' })}
              </Button>
            )}
            {mayApprove && offered(mayApprove) && (
              <Button
                size="sm"
                loading={approve.isPending}
                disabled={!mayApprove.allowed}
                title={whyNot(labels.t, mayApprove) || undefined}
                onClick={() => approve.mutate()}
                data-testid="plan-approve"
              >
                {t('staffing.plan.approve', { defaultValue: 'Approve plan' })}
              </Button>
            )}
            {offered(mayReturn) && (
              <Button
                size="sm"
                variant="secondary"
                loading={giveBack.isPending}
                disabled={!mayReturn.allowed}
                title={whyNot(labels.t, mayReturn) || undefined}
                onClick={() => giveBack.mutate()}
                data-testid="plan-return"
              >
                {t('staffing.plan.return', { defaultValue: 'Return to draft' })}
              </Button>
            )}
          </div>
        </div>
        {plan.status === 'revising' && (
          <p className="mt-3 text-sm text-content-secondary" role="status" data-testid="plan-revising-hint">
            {t('staffing.plan.revising_hint', {
              defaultValue: 'You are editing a revision. The approved plan stays in force until the revision is approved.',
            })}
          </p>
        )}
        {locked && plan.status !== 'in_review' && lockedReason && (
          <p className="mt-3 text-sm text-content-secondary" role="status" data-testid="plan-edit-refused">
            {lockedReason}
          </p>
        )}
        {plan.status === 'in_review' && (
          <p className="mt-3 text-sm text-content-secondary" role="status" data-testid="plan-locked-hint">
            {byHand
              ? t('staffing.plan.in_review_hint_no_gates', {
                  defaultValue:
                    'The plan is in review and cannot be edited. This project does not use gates, so a second person with the staffing management permission approves it here. Return it to draft to change it.',
                })
              : t('staffing.plan.in_review_hint', {
                  defaultValue:
                    'The plan is in review and cannot be edited. It is approved at the governance gate of the personnel area. Return it to draft to change it.',
                })}
          </p>
        )}
        {(plan.status === 'approved' || plan.status === 'binding') && (
          <p className="mt-3 text-sm text-content-secondary" role="status">
            {t('staffing.plan.approved_hint', {
              defaultValue: 'This plan is approved. Any change opens a revision, and the approved plan stays in force until the revision is approved.',
            })}
          </p>
        )}
        {submittable && !maySubmit.allowed && positions.length > 0 && (
          <p className="mt-3 text-sm text-content-secondary" role="status" data-testid="plan-submit-refused">
            {whyNot(labels.t, maySubmit)}
          </p>
        )}
        {mayApprove && offered(mayApprove) && !mayApprove.allowed && (
          <p className="mt-3 text-sm text-content-secondary" role="status" data-testid="plan-approve-refused">
            {whyNot(labels.t, mayApprove)}
          </p>
        )}
        {offered(mayReturn) && !mayReturn.allowed && (
          <p className="mt-3 text-sm text-content-secondary" role="status" data-testid="plan-return-refused">
            {whyNot(labels.t, mayReturn)}
          </p>
        )}
        {submittable && blockers.length > 0 && (
          <div className="mt-3 rounded-md bg-surface-secondary p-3" data-testid="plan-blockers">
            <h3 className="mb-1.5 text-sm font-medium text-content-primary">
              {t('staffing.plan.findings', { defaultValue: 'Before you can submit' })}
            </h3>
            <FindingList findings={blockers} catalogue={catalogue} labels={labels} />
          </div>
        )}
        {submittable && restrictedPeople > 0 && (
          <p className="mt-3 text-xs text-content-tertiary" role="status" data-testid="findings-restricted">
            {t('staffing.plan.findings_restricted', {
              defaultValue: '{{count}} people are not included in these checks, because you may not open their personnel files.',
              count: restrictedPeople,
            })}
          </p>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-base font-semibold text-content-primary">
            {t('staffing.position.heading', { defaultValue: 'Positions' })}
          </h2>
          <Button
            variant="secondary"
            size="sm"
            disabled={locked}
            title={lockedReason}
            onClick={() => setDialog({ kind: 'from-catalogue' })}
            data-testid="add-from-catalogue"
          >
            {t('staffing.position.add_from_catalogue', { defaultValue: 'Add roles from catalogue' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            disabled={locked}
            title={lockedReason}
            onClick={() => setDialog({ kind: 'position', position: null })}
            data-testid="add-position"
          >
            {t('staffing.position.add', { defaultValue: 'Add position' })}
          </Button>
        </div>

        {positions.length === 0 ? (
          <EmptyState
            icon={<Users size={28} />}
            title={t('staffing.position.empty_title', { defaultValue: 'No positions yet' })}
            description={t('staffing.position.empty_body', {
              defaultValue:
                'A position is a role the project needs for a phase. Start with the roles the catalogue suggests for the phase, then put people on them.',
            })}
            action={
              locked
                ? undefined
                : {
                    label: t('staffing.position.add_from_catalogue', { defaultValue: 'Add roles from catalogue' }),
                    onClick: () => setDialog({ kind: 'from-catalogue' }),
                  }
            }
          />
        ) : (
          groups.map((group) => (
            <div key={group.phase} className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm" data-testid={`phase-${group.phase}`}>
              <table className="w-full min-w-[760px] text-sm">
                <caption className="border-b border-border-light bg-surface-secondary px-3 py-2 text-left text-sm font-medium text-content-primary">
                  {vocab(t, PHASE, group.phase)}
                </caption>
                <thead>
                  <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
                    <th scope="col" className="px-3 py-2 font-medium">{t('staffing.position.role', { defaultValue: 'Role' })}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('staffing.position.fte', { defaultValue: 'FTE' })}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('staffing.position.period', { defaultValue: 'Period' })}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('staffing.position.status', { defaultValue: 'Status' })}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t('staffing.position.people', { defaultValue: 'People' })}</th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      <span className="sr-only">{t('staffing.actions', { defaultValue: 'Actions' })}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {group.positions.map((p) => {
                    const moves = allowedStatusMoves(p);
                    const owner = personName(p.owner_user_id);
                    return (
                      <tr key={p.id} className="border-b border-border-light align-top last:border-b-0" data-testid="position-row">
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-1.5 font-medium text-content-primary">
                            {positionName(labels, catalogue, p)}
                            {p.key_role && (
                              <span title={t('staffing.position.key_role', { defaultValue: 'Key role' })} data-testid="key-role">
                                <KeyRound size={13} className="text-oe-blue-text" aria-label={t('staffing.position.key_role', { defaultValue: 'Key role' })} />
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-content-tertiary">
                            {catalogueName(labels, catalogue, 'organisation', p.organisation)}
                          </div>
                          {owner && (
                            <div className="text-xs text-content-tertiary">
                              {t('staffing.position.owner_named', { defaultValue: 'Line manager: {{name}}', name: owner })}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 tabular-nums text-content-primary">
                          {p.headcount > 1
                            ? t('staffing.position.fte_times', { defaultValue: '{{fte}} FTE x {{n}}', fte: fte(p.fte), n: p.headcount })
                            : fte(p.fte)}
                          <div className="text-xs text-content-tertiary">
                            {t('staffing.position.covered', { defaultValue: 'Covered {{fte}}', fte: fte(p.covered_fte) })}
                          </div>
                        </td>
                        <td className="px-3 py-2 text-content-secondary">
                          {p.entry_date ? fmtDate(p.entry_date) : t('staffing.not_set', { defaultValue: 'Not set' })}
                          {p.exit_date && (
                            <>
                              {' '}
                              <ArrowRight size={12} className="inline rtl:rotate-180" aria-hidden /> {fmtDate(p.exit_date)}
                            </>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <ToneBadge tone={POSITION_TONE[p.status]} testId="position-status">
                            {vocab(t, POSITION_STATUS, p.status)}
                          </ToneBadge>
                          {moves.length > 0 && (
                            <select
                              className={`${FIELD_CLASS} mt-1 !w-auto !py-0.5 text-xs`}
                              aria-label={t('staffing.position.change_status', { defaultValue: 'Change status' })}
                              value=""
                              onChange={(e) => {
                                if (e.target.value) moveStatus.mutate({ id: p.id, status: e.target.value as SettablePositionStatus });
                              }}
                            >
                              <option value="">{t('staffing.position.change_status', { defaultValue: 'Change status' })}</option>
                              {moves.map((s) => (
                                <option key={s} value={s}>
                                  {vocab(t, POSITION_STATUS, s)}
                                </option>
                              ))}
                            </select>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {p.fills.length === 0 ? (
                            <span className="text-content-tertiary" data-testid="position-vacant">
                              {t('staffing.vacant', { defaultValue: 'Vacant' })}
                            </span>
                          ) : (
                            <ul className="space-y-1.5">
                              {p.fills.map((f) => (
                                <li key={f.id} data-testid="fill-row">
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="text-content-primary">{personLabel(labels.t, f.name)}</span>
                                    <ToneBadge tone={FILL_TONE[f.status]}>{vocab(t, FILL_STATUS, f.status)}</ToneBadge>
                                    {f.status !== 'ended' && <ClearedBadge cleared={f.cleared_to_work} />}
                                  </div>
                                  <div className="flex flex-wrap items-center gap-x-2 text-xs text-content-tertiary">
                                    <span>
                                      {t('staffing.fill.share_from', {
                                        defaultValue: '{{fte}} FTE from {{date}}',
                                        fte: fte(f.fte_share),
                                        date: f.from_date ? fmtDate(f.from_date) : '',
                                      })}
                                    </span>
                                    {offered(f.can.confirm) && (
                                      <>
                                        <button
                                          type="button"
                                          className="text-oe-blue-text hover:underline disabled:cursor-not-allowed disabled:text-content-tertiary disabled:no-underline"
                                          disabled={!f.can.confirm.allowed}
                                          onClick={() => confirm.mutate(f.id)}
                                          data-testid="fill-confirm"
                                        >
                                          {t('staffing.fill.confirm', { defaultValue: 'Confirm' })}
                                        </button>
                                        <Refusal text={whyNot(labels.t, f.can.confirm)} testId="fill-confirm-refused" />
                                      </>
                                    )}
                                    {offered(f.can.delete) && (
                                      <>
                                        <button
                                          type="button"
                                          className="hover:underline disabled:cursor-not-allowed disabled:text-content-tertiary disabled:no-underline"
                                          disabled={!f.can.delete.allowed}
                                          onClick={() => dropFill.mutate(f.id)}
                                          data-testid="fill-remove"
                                        >
                                          {t('staffing.fill.remove', { defaultValue: 'Remove' })}
                                        </button>
                                        <Refusal text={whyNot(labels.t, f.can.delete)} testId="fill-remove-refused" />
                                      </>
                                    )}
                                    {offered(f.can.end) && (
                                      <>
                                        <button
                                          type="button"
                                          className="hover:underline disabled:cursor-not-allowed disabled:text-content-tertiary disabled:no-underline"
                                          disabled={!f.can.end.allowed}
                                          onClick={() => end.mutate(f.id)}
                                          data-testid="fill-end"
                                        >
                                          {t('staffing.fill.end', { defaultValue: 'End assignment' })}
                                        </button>
                                        <Refusal text={whyNot(labels.t, f.can.end)} testId="fill-end-refused" />
                                      </>
                                    )}
                                  </div>
                                </li>
                              ))}
                            </ul>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap items-center justify-end gap-1">
                            {p.resource_request_id && (
                              <span className="text-xs text-content-tertiary" data-testid="resource-requested">
                                {t('staffing.position.resource_requested', { defaultValue: 'Resource requested' })}
                              </span>
                            )}
                            <Refusal text={offered(p.can.request_resource) ? whyNot(labels.t, p.can.request_resource) : ''} testId="request-resource-refused" />
                            {offered(p.can.request_resource) && (
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={!p.can.request_resource.allowed}
                                loading={askResource.isPending}
                                onClick={() => askResource.mutate(p.id)}
                                data-testid="request-resource"
                              >
                                {t('staffing.position.request_resource', { defaultValue: 'Request resource' })}
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              icon={<UserPlus size={14} />}
                              disabled={locked || p.status === 'cancelled'}
                              title={lockedReason}
                              onClick={() => setDialog({ kind: 'fill', position: p })}
                              data-testid="assign-person"
                            >
                              {t('staffing.fill.add', { defaultValue: 'Assign person' })}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              icon={<Pencil size={14} />}
                              disabled={locked}
                              aria-label={t('staffing.position.edit', { defaultValue: 'Edit position' })}
                              title={lockedReason ?? t('staffing.position.edit', { defaultValue: 'Edit position' })}
                              onClick={() => setDialog({ kind: 'position', position: p })}
                            />
                            <Button
                              variant="ghost"
                              size="sm"
                              icon={<Trash2 size={14} />}
                              disabled={locked}
                              aria-label={t('staffing.position.delete', { defaultValue: 'Delete position' })}
                              title={lockedReason ?? t('staffing.position.delete', { defaultValue: 'Delete position' })}
                              onClick={() => setDialog({ kind: 'delete-position', position: p })}
                              data-testid="delete-position"
                            />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ))
        )}
      </section>

      {positions.length > 0 && (
        <section className="space-y-3" data-testid="handovers">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="mr-auto text-base font-semibold text-content-primary">
              {t('staffing.handover.heading', { defaultValue: 'Handovers' })}
            </h2>
            <Button variant="secondary" size="sm" disabled={locked} title={lockedReason} onClick={() => setDialog({ kind: 'handover', handover: null })} data-testid="add-handover">
              {t('staffing.handover.add', { defaultValue: 'Plan handover' })}
            </Button>
          </div>
          {handovers.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border-light px-4 py-5 text-sm text-content-secondary" data-testid="handovers-empty">
              {t('staffing.handover.empty', {
                defaultValue:
                  'No handover is planned. Plan one when a person leaves and somebody else takes over, for example from execution into operation.',
              })}
            </p>
          ) : (
            <ul className="space-y-2">
              {handovers.map((h) => {
                const from = fillById.get(h.from_fill_id);
                const to = positionById.get(h.to_position_id);
                return (
                  <li key={h.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="handover-row">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-medium text-content-primary">
                        {from
                          ? t('staffing.handover.person_on', {
                              defaultValue: '{{person}}, {{position}}',
                              person: personLabel(labels.t, from.fill.name),
                              position: positionName(labels, catalogue, from.position),
                            })
                          : personLabel(labels.t, null)}
                      </span>
                      <ArrowRight size={14} className="text-content-tertiary rtl:rotate-180" aria-hidden />
                      <span className="font-medium text-content-primary">
                        {to ? positionName(labels, catalogue, to) : t('staffing.handover.position_gone', { defaultValue: 'Removed position' })}
                      </span>
                      <ToneBadge tone={h.status === 'done' ? 'success' : 'blue'}>{vocab(t, HANDOVER_STATUS, h.status)}</ToneBadge>
                      <span className="text-xs text-content-tertiary">
                        {t('staffing.handover.overlap', { defaultValue: '{{count}} days overlap', count: h.overlap_days })}
                      </span>
                      {!locked && (
                        <span className="ml-auto flex gap-1">
                          {h.status === 'planned' && (
                            <Button variant="ghost" size="sm" onClick={() => handoverDone.mutate(h.id)} data-testid="handover-done">
                              {t('staffing.handover.mark_done', { defaultValue: 'Mark as done' })}
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={<Pencil size={14} />}
                            aria-label={t('staffing.handover.edit', { defaultValue: 'Edit handover' })}
                            title={t('staffing.handover.edit', { defaultValue: 'Edit handover' })}
                            onClick={() => setDialog({ kind: 'handover', handover: h })}
                          />
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={<Trash2 size={14} />}
                            aria-label={t('staffing.handover.delete', { defaultValue: 'Delete handover' })}
                            title={t('staffing.handover.delete', { defaultValue: 'Delete handover' })}
                            onClick={() => handoverRemove.mutate(h.id)}
                          />
                        </span>
                      )}
                    </div>
                    {h.scope && <p className="mt-1 text-sm text-content-secondary">{h.scope}</p>}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      <PlanSettingsDialog open={dialog?.kind === 'settings'} projectId={projectId} plan={plan} onClose={() => setDialog(null)} onDone={onChanged} />
      <ChangeCatalogueDialog
        open={dialog?.kind === 'catalogue'}
        projectId={projectId}
        plan={plan}
        catalogue={catalogue}
        labels={labels}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <PositionDialog
        open={dialog?.kind === 'position'}
        projectId={projectId}
        labels={labels}
        catalogue={catalogue}
        position={dialog?.kind === 'position' ? dialog.position : null}
        plan={plan}
        phases={phases}
        defaultPhase={defaultPhase}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <FromCatalogueDialog
        open={dialog?.kind === 'from-catalogue'}
        projectId={projectId}
        labels={labels}
        catalogue={catalogue}
        positions={positions}
        phases={phases}
        defaultPhase={defaultPhase}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <FillDialog
        open={dialog?.kind === 'fill'}
        projectId={projectId}
        labels={labels}
        catalogue={catalogue}
        position={dialog?.kind === 'fill' ? dialog.position : null}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <HandoverDialog
        open={dialog?.kind === 'handover'}
        projectId={projectId}
        labels={labels}
        catalogue={catalogue}
        positions={positions}
        handover={dialog?.kind === 'handover' ? dialog.handover : null}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <ConfirmDialog
        open={dialog?.kind === 'delete-position'}
        title={t('staffing.position.delete', { defaultValue: 'Delete position' })}
        message={t('staffing.position.delete_confirm', { defaultValue: 'Delete this position?' })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        variant="danger"
        loading={removePosition.isPending}
        onCancel={() => setDialog(null)}
        onConfirm={() => dialog?.kind === 'delete-position' && removePosition.mutate(dialog.position.id)}
      />
    </div>
  );
}

function catalogueLabel(labels: LabelContext, catalogue: StaffingCatalogue): string {
  const texts = catalogue.labels;
  const lang = labels.language.split('-')[0] ?? 'en';
  return texts?.[labels.language] ?? texts?.[lang] ?? texts?.en ?? catalogue.id;
}
