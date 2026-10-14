// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The design schedule: what each designer delivers in each phase, counted
// against the drawings that exist, and the approval points where the design
// needs somebody's decision. The state of a schedule line is worked out by
// the server from its drawings; only waiving is done by hand, with a reason.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CalendarCheck } from 'lucide-react';

import { EmptyState } from '@/shared/ui/EmptyState';

import {
  createApprovalPoint,
  createDeliverable,
  deleteDeliverable,
  listApprovalPoints,
  reopenApprovalPoint,
  submitApprovalPoint,
  updateApprovalPoint,
  updateDeliverable,
  type ApprovalPoint,
  type ApprovalPointInput,
  type Deliverable,
  type DeliverableInput,
} from './api';
import {
  APPROVAL_TONE,
  CELL,
  CELL_MUTED,
  DELIVERABLE_TONE,
  PanelHeader,
  SUITABILITY_OPTIONS,
  Table,
  ToneBadge,
  phaseField,
  roleOptions,
  roleTitle,
  wbsOptions,
  type DesignContext,
  StepButton,
  pickerField,
  WriteButton,
} from './DesignBits';
import { FormDialog, flag, str, type FieldSpec, type FormValues } from './FormDialog';
import { useDesignAction, useDesignList, useDesignOptions } from './hooks';
import { APPROVAL_KIND, APPROVAL_STATE, DELIVERABLE_STATE, phaseName, ui, vocab, vocabOptions, type TFn } from './labels';
import { DRAFT_PROBLEM, applies, changedFields, deliverableProblems, deliverableProgress, filledFields, wholeNumber } from './rules';

type Dialog =
  | { kind: 'line'; line: Deliverable | null }
  | { kind: 'delete'; line: Deliverable }
  | { kind: 'point'; point: ApprovalPoint | null }
  | null;

function lineValues(line: Deliverable | null): FormValues {
  return {
    code: line?.code ?? '',
    title: line?.title ?? '',
    phase_code: line?.phase_code ?? '',
    role_id: line?.role_id ?? '',
    discipline_code: line?.discipline_code ?? '',
    form_code: line?.form_code ?? '',
    wbs_node_id: line?.wbs_node_id ?? '',
    planned_count: String(line?.planned_count ?? 1),
    planned_count_rationale: line?.planned_count_rationale ?? '',
    target_suitability: line?.target_suitability ?? '',
    required: line?.required ?? true,
    waived: line?.waived ?? false,
    waived_rationale: line?.waived_rationale ?? '',
  };
}

function lineBody(values: Record<string, unknown>): DeliverableInput {
  const body = { ...values } as Record<string, unknown>;
  if (typeof body.planned_count === 'string') body.planned_count = wholeNumber(body.planned_count) ?? 0;
  return body as DeliverableInput;
}

function pointValues(point: ApprovalPoint | null): FormValues {
  return {
    code: point?.code ?? '',
    title: point?.title ?? '',
    phase_code: point?.phase_code ?? '',
    kind: point?.kind ?? '',
    approver_role_id: point?.approver_role_id ?? '',
    governance_gate_id: point?.governance_gate_id ?? '',
    note: point?.note ?? '',
  };
}

export function SchedulePanel({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const [dialog, setDialog] = useState<Dialog>(null);
  const action = useDesignAction(ctx.onChanged);
  const points = useDesignList(ctx.projectId, 'approval-points', listApprovalPoints);
  const forms = useDesignOptions(ctx.projectId, 'forms', ctx.labels);
  const gates = useDesignOptions(ctx.projectId, 'governance_gates', ctx.labels);
  const noGates = ctx.setup.gates_in_use === false;
  const phases = ctx.setup.phases;
  const linePhase = phaseField(ctx, t, true);

  const lineFields = (line: Deliverable | null): FieldSpec[] => [
    { name: 'title', label: ui(t, 'design.ui.schedule.line_title'), type: 'text', required: true },
    linePhase,
    { name: 'role_id', label: ui(t, 'design.ui.schedule.by'), type: 'select', options: roleOptions(ctx) },
    { name: 'planned_count', label: ui(t, 'design.ui.schedule.planned_count'), type: 'number', required: true },
    ...(line
      ? [{ name: 'planned_count_rationale', label: ui(t, 'design.ui.schedule.count_reason'), type: 'textarea' as const }]
      : []),
    { name: 'code', label: ui(t, 'design.ui.field.code'), type: 'text', hint: ui(t, 'design.ui.field.code_hint') },
    { name: 'discipline_code', label: ui(t, 'design.ui.field.discipline'), type: 'text' },
    ...pickerField('form_code', ui(t, 'design.ui.schedule.form'), forms),
    { name: 'wbs_node_id', label: ui(t, 'design.ui.field.wbs'), type: 'select', options: wbsOptions(ctx) },
    {
      name: 'target_suitability',
      label: ui(t, 'design.ui.schedule.target_status'),
      type: 'select',
      options: SUITABILITY_OPTIONS,
      hint: ui(t, 'design.ui.schedule.target_status_hint'),
    },
    { name: 'required', label: ui(t, 'design.ui.schedule.required'), type: 'checkbox' },
    // Waiving a line, and taking a waiver back, are actions the server offers or not.
    ...(line && applies(line.waived ? line.can?.unwaive : line.can?.waive)
      ? [
          { name: 'waived', label: ui(t, 'design.ui.schedule.waived'), type: 'checkbox' as const },
          {
            name: 'waived_rationale',
            label: ui(t, 'design.ui.schedule.waiver_reason'),
            type: 'textarea' as const,
            showIf: (v: FormValues) => flag(v, 'waived'),
          },
        ]
      : []),
  ];

  // The dialog already names an empty required field, so title and phase are
  // passed as filled here and only the two reasons are checked.
  const lineProblems = (line: Deliverable | null) => (values: FormValues) =>
    deliverableProblems(
      {
        title: str(values, 'title') || 'x',
        phase_code: str(values, 'phase_code') || 'x',
        planned_count: wholeNumber(str(values, 'planned_count')) ?? 0,
        planned_count_rationale: str(values, 'planned_count_rationale'),
        waived: flag(values, 'waived'),
        waived_rationale: str(values, 'waived_rationale'),
      },
      line,
    ).map((problem) => ui(t, DRAFT_PROBLEM[problem]));

  const pointFields: FieldSpec[] = [
    { name: 'title', label: ui(t, 'design.ui.schedule.point_title'), type: 'text', required: true },
    { name: 'kind', label: ui(t, 'design.ui.schedule.point_kind'), type: 'select', required: true, options: vocabOptions(t, APPROVAL_KIND) },
    phaseField(ctx, t),
    { name: 'approver_role_id', label: ui(t, 'design.ui.schedule.approver'), type: 'select', options: roleOptions(ctx) },
    ...(noGates ? [] : pickerField('governance_gate_id', ui(t, 'design.ui.schedule.gate'), gates)),
    { name: 'code', label: ui(t, 'design.ui.field.code'), type: 'text', hint: ui(t, 'design.ui.field.code_hint') },
    { name: 'note', label: ui(t, 'design.ui.field.note'), type: 'textarea' },
  ];

  const openLine = () => setDialog({ kind: 'line', line: null });

  return (
    <div className="space-y-4" data-testid="design-schedule-panel">
      <PanelHeader
        title={ui(t, 'design.ui.schedule.title')}
        hint={ui(t, 'design.ui.schedule.hint')}
        action={
          <WriteButton onClick={openLine} data-testid="line-add">
            {ui(t, 'design.ui.schedule.add')}
          </WriteButton>
        }
      />
      {ctx.deliverables.length === 0 ? (
        <EmptyState
          icon={<CalendarCheck size={28} />}
          title={ui(t, 'design.ui.schedule.empty_title')}
          description={ui(t, 'design.ui.schedule.empty_body')}
          action={{ label: ui(t, 'design.ui.schedule.add'), onClick: openLine }}
        />
      ) : (
        <Table
          testId="schedule-table"
          head={[
            ui(t, 'design.ui.field.code'),
            ui(t, 'design.ui.schedule.line_title'),
            ui(t, 'design.ui.field.phase'),
            ui(t, 'design.ui.schedule.by'),
            ui(t, 'design.ui.schedule.drawings'),
            ui(t, 'design.ui.field.state'),
            '',
          ]}
        >
          {ctx.deliverables.map((line) => {
            const progress = deliverableProgress(line, ctx.drawings);
            return (
              <tr key={line.id} data-testid="schedule-row">
                <td className={`${CELL_MUTED} font-mono`}>{line.code}</td>
                <td className={CELL}>
                  <span className="font-medium">{line.title}</span>
                  {line.waived && line.waived_rationale && (
                    <p className="text-xs text-content-secondary">
                      {ui(t, 'design.ui.schedule.waived_because', { reason: line.waived_rationale })}
                    </p>
                  )}
                </td>
                <td className={CELL_MUTED}>{phaseName(ctx.labels, phases, line.phase_code)}</td>
                <td className={CELL_MUTED}>{roleTitle(ctx, line.role_id)}</td>
                <td className={CELL_MUTED} data-testid="schedule-progress">
                  {ui(t, 'design.ui.schedule.progress', { linked: progress.linked, planned: progress.planned })}
                </td>
                <td className={CELL}>
                  <ToneBadge tone={DELIVERABLE_TONE[line.state]}>{vocab(t, DELIVERABLE_STATE, line.state)}</ToneBadge>
                </td>
                <td className={`${CELL} whitespace-nowrap text-right`}>
                  <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'line', line })}>
                    {ui(t, 'design.ui.action.edit')}
                  </WriteButton>
                  <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'delete', line })}>
                    {ui(t, 'design.ui.action.delete')}
                  </WriteButton>
                </td>
              </tr>
            );
          })}
        </Table>
      )}

      <PanelHeader
        title={ui(t, 'design.ui.schedule.points_title')}
        hint={ui(t, 'design.ui.schedule.points_hint')}
        action={
          <WriteButton variant="secondary" onClick={() => setDialog({ kind: 'point', point: null })} data-testid="point-add">
            {ui(t, 'design.ui.schedule.point_add')}
          </WriteButton>
        }
      />
      {(points.data ?? []).length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-4 py-6 text-center text-sm text-content-tertiary">
          {points.isLoading ? ui(t, 'design.ui.loading') : ui(t, 'design.ui.schedule.points_empty')}
        </p>
      ) : (
        <Table
          testId="points-table"
          head={[
            ui(t, 'design.ui.field.code'),
            ui(t, 'design.ui.schedule.point_title'),
            ui(t, 'design.ui.schedule.point_kind'),
            ui(t, 'design.ui.field.phase'),
            ui(t, 'design.ui.schedule.approver'),
            ui(t, 'design.ui.field.state'),
            '',
          ]}
        >
          {(points.data ?? []).map((point) => (
            <tr key={point.id} data-testid="point-row">
              <td className={`${CELL_MUTED} font-mono`}>{point.code}</td>
              <td className={CELL}>{point.title}</td>
              <td className={CELL_MUTED}>{vocab(t, APPROVAL_KIND, point.kind)}</td>
              <td className={CELL_MUTED}>{phaseName(ctx.labels, phases, point.phase_code)}</td>
              <td className={CELL_MUTED}>{roleTitle(ctx, point.approver_role_id)}</td>
              <td className={CELL}>
                <ToneBadge tone={APPROVAL_TONE[point.state]}>{vocab(t, APPROVAL_STATE, point.state)}</ToneBadge>
              </td>
              <td className={`${CELL} whitespace-nowrap text-right`}>
                <span className="inline-flex flex-wrap justify-end gap-1">
                  {point.state === 'open' && (
                    <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'point', point })}>
                      {ui(t, 'design.ui.action.edit')}
                    </WriteButton>
                  )}
                  <StepButton
                    flag={point.can?.reopen}
                    label={ui(t, 'design.ui.schedule.point_reopen')}
                    busy={action.pending}
                    onClick={() => action.run(() => reopenApprovalPoint(ctx.projectId, point.id))}
                    testId="point-reopen"
                  />
                  <StepButton
                    flag={point.can?.submit}
                    label={ui(t, 'design.ui.schedule.point_submit')}
                    variant="secondary"
                    busy={action.pending}
                    onClick={() => action.run(() => submitApprovalPoint(ctx.projectId, point.id))}
                    testId="point-submit"
                  />
                </span>
              </td>
            </tr>
          ))}
        </Table>
      )}

      {dialog?.kind === 'line' && (
        <FormDialog
          projectId={ctx.projectId}
          title={dialog.line ? ui(t, 'design.ui.schedule.edit') : ui(t, 'design.ui.schedule.add')}
          fields={lineFields(dialog.line)}
          initial={lineValues(dialog.line)}
          submitLabel={dialog.line ? ui(t, 'design.ui.action.save') : ui(t, 'design.ui.schedule.add')}
          problems={lineProblems(dialog.line)}
          submit={(values) =>
            dialog.line
              ? updateDeliverable(
                  ctx.projectId,
                  dialog.line.id,
                  lineBody(changedFields(lineValues(dialog.line), values, ['phase_code', 'role_id', 'discipline_code', 'form_code', 'wbs_node_id', 'target_suitability'])),
                )
              : createDeliverable(ctx.projectId, lineBody(filledFields(values)))
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
      {dialog?.kind === 'delete' && (
        <FormDialog
          projectId={ctx.projectId}
          danger
          title={ui(t, 'design.ui.schedule.delete_title')}
          subtitle={ui(t, 'design.ui.schedule.delete_body', { code: dialog.line.code })}
          fields={[]}
          initial={{}}
          submitLabel={ui(t, 'design.ui.action.delete')}
          submit={() => deleteDeliverable(ctx.projectId, dialog.line.id)}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
      {dialog?.kind === 'point' && (
        <FormDialog
          projectId={ctx.projectId}
          title={dialog.point ? ui(t, 'design.ui.schedule.point_edit') : ui(t, 'design.ui.schedule.point_add')}
          subtitle={noGates ? ui(t, 'design.ui.no_gates') : undefined}
          fields={pointFields}
          initial={pointValues(dialog.point)}
          submitLabel={dialog.point ? ui(t, 'design.ui.action.save') : ui(t, 'design.ui.schedule.point_add')}
          submit={(values) =>
            dialog.point
              ? updateApprovalPoint(
                  ctx.projectId,
                  dialog.point.id,
                  changedFields<ApprovalPointInput>(pointValues(dialog.point), values, ['phase_code', 'approver_role_id', 'governance_gate_id']),
                )
              : createApprovalPoint(ctx.projectId, filledFields<ApprovalPointInput>(values))
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
    </div>
  );
}
