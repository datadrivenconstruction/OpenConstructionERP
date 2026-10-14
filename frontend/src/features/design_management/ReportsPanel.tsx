// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Expert reports and proofs: which ones the design needs, who writes each,
// whether an independent check applies and how far it is. The catalogue's
// country hints are shown as hints with their source; they are never
// enforced, because whether a check is required is decided by the authority.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileCheck2, Info } from 'lucide-react';


import {
  createReport,
  listReportHints,
  listReports,
  moveReport,
  syncReport,
  updateReport,
  type Report,
  type ReportInput,
  type ReportState,
} from './api';
import {
  CELL,
  CELL_MUTED,
  ListState,
  PanelHeader,
  REPORT_TONE,
  Table,
  ToneBadge,
  hasRows,
  phaseField,
  roleOptions,
  roleTitle,
  type DesignContext,
  StepButton,
  pickerField,
  WriteButton,
} from './DesignBits';
import { FormDialog, str, type FieldSpec, type FormValues } from './FormDialog';
import { useDesignAction, useDesignList, useDesignOptions } from './hooks';
import { INDEPENDENT_CHECK, REPORT_STATE, errorText, phaseName, reportKindName, ui, vocab, vocabOptions, type TFn } from './labels';
import { STEP_LABEL, changedFields, filledFields, offered, reportMoveNeedsReason } from './rules';

type Dialog = { kind: 'report'; report: Report | null } | { kind: 'not-required'; report: Report } | null;

function reportValues(report: Report | null): FormValues {
  return {
    kind_code: report?.kind_code ?? '',
    title: report?.title ?? '',
    phase_code: report?.phase_code ?? '',
    author_role_id: report?.author_role_id ?? '',
    checker_role_id: report?.checker_role_id ?? '',
    external_check: report?.external_check ?? false,
    review_cycle_id: report?.review_cycle_id ?? '',
    independent_check: report?.independent_check ?? '',
    rationale: report?.rationale ?? '',
    conditions_text: report?.conditions_text ?? '',
    code: report?.code ?? '',
  };
}

export function ReportsPanel({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const [dialog, setDialog] = useState<Dialog>(null);
  const action = useDesignAction(ctx.onChanged);
  const reports = useDesignList(ctx.projectId, 'reports', listReports);
  const cycles = useDesignOptions(ctx.projectId, 'review_cycles', ctx.labels);
  const hints = useDesignList(ctx.projectId, 'report-hints', listReportHints);
  const catalogue = ctx.setup.reports_catalogue;
  const phases = ctx.setup.phases;
  const kindName = (code: string) => reportKindName(ctx.labels, catalogue, code);

  const fields = (editing: boolean, gate = true): FieldSpec[] => [
    ...(editing
      ? []
      : [
          {
            name: 'kind_code',
            label: ui(t, 'design.ui.reports.kind'),
            type: 'select' as const,
            required: true,
            options: catalogue.report_kinds.map((k) => ({ value: k.code, label: kindName(k.code) })),
          },
        ]),
    { name: 'title', label: ui(t, 'design.ui.field.title'), type: 'text', hint: editing ? undefined : ui(t, 'design.ui.reports.title_hint') },
    phaseField(ctx, t),
    // Who writes and who checks a report are gate fields: the server says whether this user may still change them.
    ...(gate ? [{ name: 'author_role_id', label: ui(t, 'design.ui.reports.author'), type: 'select' as const, options: roleOptions(ctx) }] : []),
    {
      name: 'independent_check',
      label: ui(t, 'design.ui.reports.check'),
      type: 'select',
      options: vocabOptions(t, INDEPENDENT_CHECK),
      hint: ui(t, 'design.ui.reports.check_hint'),
    },
    ...(gate
      ? [
          { name: 'checker_role_id', label: ui(t, 'design.ui.reports.checker'), type: 'select' as const, options: roleOptions(ctx), hint: ui(t, 'design.ui.reports.checker_hint') },
          { name: 'external_check', label: ui(t, 'design.ui.reports.external_check'), type: 'checkbox' as const },
          ...pickerField('review_cycle_id', ui(t, 'design.ui.reports.review_cycle'), cycles),
        ]
      : []),
    { name: 'rationale', label: ui(t, 'design.ui.reports.rationale'), type: 'textarea', hint: ui(t, 'design.ui.reports.rationale_hint') },
    ...(editing ? [{ name: 'conditions_text', label: ui(t, 'design.ui.reports.conditions'), type: 'textarea' as const }] : []),
    { name: 'code', label: ui(t, 'design.ui.field.code'), type: 'text', hint: ui(t, 'design.ui.field.code_hint') },
  ];
  const add = () => setDialog({ kind: 'report', report: null });
  const move = (report: Report, target: ReportState) =>
    reportMoveNeedsReason(target)
      ? setDialog({ kind: 'not-required', report })
      : action.run(() => moveReport(ctx.projectId, report.id, target));

  return (
    <div className="space-y-4" data-testid="design-reports-panel">
      <PanelHeader
        title={ui(t, 'design.ui.reports.title')}
        hint={ui(t, 'design.ui.reports.hint')}
        action={
          <WriteButton onClick={add} data-testid="report-add">
            {ui(t, 'design.ui.reports.add')}
          </WriteButton>
        }
      />

      {(hints.data ?? []).length > 0 && (
        <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-sm" data-testid="report-hints">
          <p className="flex items-center gap-2 font-medium text-content-primary">
            <Info size={14} aria-hidden />
            {ui(t, 'design.ui.reports.hints_title')}
          </p>
          <ul className="ml-6 mt-1 list-disc space-y-1 text-xs text-content-secondary">
            {(hints.data ?? []).map((hint) => (
              <li key={`${hint.kind_code}-${hint.text_key}-${hint.region ?? ''}`}>
                <span className="font-medium">{kindName(hint.kind_code)}: </span>
                {ctx.labels.exists(hint.text_key) ? ctx.labels.t(hint.text_key) : ui(t, 'design.ui.reports.hint_generic')}
                {hint.condition_key && ctx.labels.exists(hint.condition_key) && <span className="ml-1">{ctx.labels.t(hint.condition_key)}</span>}
                {hint.source_url && (
                  <a className="ml-1 text-oe-blue-text underline" href={hint.source_url} target="_blank" rel="noreferrer noopener">
                    {ui(t, 'design.ui.source')}
                  </a>
                )}
                {hint.review_status !== 'verified' && <span className="ml-1 italic">{ui(t, 'design.ui.unconfirmed')}</span>}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-2xs text-content-tertiary">{ui(t, 'design.ui.reports.hints_note')}</p>
        </div>
      )}

      <ListState
        query={reports}
        failedKey="design.ui.reports.load_failed"
        emptyIcon={<FileCheck2 size={28} />}
        emptyTitle={ui(t, 'design.ui.reports.empty_title')}
        emptyBody={ui(t, 'design.ui.reports.empty_body')}
        emptyAction={{ label: ui(t, 'design.ui.reports.add'), onClick: add }}
      />
      {hasRows(reports) && (
        <Table
          testId="reports-table"
          head={[
            ui(t, 'design.ui.field.code'),
            ui(t, 'design.ui.reports.kind'),
            ui(t, 'design.ui.field.phase'),
            ui(t, 'design.ui.reports.author'),
            ui(t, 'design.ui.reports.check'),
            ui(t, 'design.ui.field.state'),
            '',
          ]}
        >
          {(reports.data ?? []).map((report) => (
            <tr key={report.id} data-testid="report-row">
              <td className={`${CELL_MUTED} font-mono`}>{report.code}</td>
              <td className={CELL}>
                <span className="font-medium">{kindName(report.kind_code)}</span>
                {report.title && <p className="text-xs text-content-secondary">{report.title}</p>}
                {report.rationale && (
                  <p className="text-xs text-content-secondary">{ui(t, 'design.ui.reports.reason_shown', { reason: report.rationale })}</p>
                )}
              </td>
              <td className={CELL_MUTED}>{phaseName(ctx.labels, phases, report.phase_code)}</td>
              <td className={CELL_MUTED}>{roleTitle(ctx, report.author_role_id)}</td>
              <td className={CELL_MUTED}>
                {vocab(t, INDEPENDENT_CHECK, report.independent_check)}
                {report.checker_role_id && <p className="text-2xs">{roleTitle(ctx, report.checker_role_id)}</p>}
                {report.hint_overridden && <p className="text-2xs italic">{ui(t, 'design.ui.reports.overridden')}</p>}
              </td>
              <td className={CELL}>
                <ToneBadge tone={REPORT_TONE[report.state]}>{vocab(t, REPORT_STATE, report.state)}</ToneBadge>
              </td>
              <td className={`${CELL} text-right`}>
                <span className="inline-flex flex-wrap justify-end gap-1">
                  <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'report', report })}>
                    {ui(t, 'design.ui.action.edit')}
                  </WriteButton>
                  {report.review_cycle_id ? (
                    <WriteButton
                      size="sm"
                      variant="ghost"
                      disabled={action.pending}
                      onClick={() => action.run(() => syncReport(ctx.projectId, report.id))}
                      data-testid="report-sync"
                    >
                      {ui(t, 'design.ui.reports.sync')}
                    </WriteButton>
                  ) : (
                    offered(report.can?.transitions).map(({ target, flag }) => (
                      <StepButton
                        key={target}
                        flag={flag}
                        label={ui(t, STEP_LABEL.report[target])}
                        busy={action.pending}
                        onClick={() => move(report, target)}
                        testId={`report-to-${target}`}
                      />
                    ))
                  )}
                </span>
              </td>
            </tr>
          ))}
        </Table>
      )}

      {dialog?.kind === 'report' && (
        <FormDialog
          projectId={ctx.projectId}
          title={dialog.report ? ui(t, 'design.ui.reports.edit') : ui(t, 'design.ui.reports.add')}
          subtitle={
            dialog.report?.can?.edit_gate_fields && !dialog.report.can.edit_gate_fields.allowed && dialog.report.can.edit_gate_fields.reason
              ? errorText(t, dialog.report.can.edit_gate_fields.reason)
              : undefined
          }
          fields={fields(!!dialog.report, dialog.report?.can?.edit_gate_fields?.allowed ?? true)}
          initial={reportValues(dialog.report)}
          submitLabel={dialog.report ? ui(t, 'design.ui.action.save') : ui(t, 'design.ui.reports.add')}
          submit={(values) =>
            dialog.report
              ? updateReport(
                  ctx.projectId,
                  dialog.report.id,
                  changedFields<ReportInput>(reportValues(dialog.report), values, ['phase_code', 'author_role_id', 'checker_role_id', 'review_cycle_id']),
                )
              : createReport(ctx.projectId, { ...filledFields<ReportInput>(values), from_catalogue: true })
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="report-form"
        />
      )}
      {dialog?.kind === 'not-required' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.reports.not_required_title', { name: kindName(dialog.report.kind_code) })}
          subtitle={ui(t, 'design.ui.reports.not_required_body')}
          fields={[{ name: 'rationale', label: ui(t, 'design.ui.reports.rationale'), type: 'textarea', required: true }]}
          initial={{ rationale: '' }}
          submitLabel={ui(t, STEP_LABEL.report.not_required)}
          submit={(values) => moveReport(ctx.projectId, dialog.report.id, 'not_required', str(values, 'rationale'))}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="not-required-form"
        />
      )}
    </div>
  );
}
