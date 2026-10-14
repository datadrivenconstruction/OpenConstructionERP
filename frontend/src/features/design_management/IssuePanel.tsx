// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issuing drawings. A release bundles revisions that go out together; the
// distribution matrix says who receives which drawings, for what and in which
// format. Before a release is issued the screen shows exactly who would get
// what, which revisions are left out and why, and which were sent before.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Send } from 'lucide-react';

import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  createDistributionRule,
  createRelease,
  deleteDistributionRule,
  designKeys,
  issueRelease,
  listDistributionRules,
  listReleases,
  moveRelease,
  previewRelease,
  updateDistributionRule,
  updateRelease,
  type DistributionRule,
  type DistributionRuleInput,
  type Release,
  type ReleaseInput,
} from './api';
import {
  CELL,
  CELL_MUTED,
  ListState,
  PanelHeader,
  RELEASE_TONE,
  SUITABILITY_OPTIONS,
  Table,
  ToneBadge,
  hasRows,
  phaseOptions,
  roleOptions,
  roleTitle,
  type DesignContext,
  StepButton,
  pickerField,
  wbsOptions,
  WriteButton,
} from './DesignBits';
import { FormDialog, flag, list, str, type FieldOption, type FieldSpec, type FormValues } from './FormDialog';
import { refusalText, useDesignAction, useDesignList, useDesignOptions } from './hooks';
import { DIST_FORMAT, PURPOSE, RELEASE_STATE, errorText, phaseName, ui, uiCount, vocab, vocabOptions, type TFn } from './labels';
import { STEP_LABEL, offered, changedFields, filledFields, recipientName, releasable, wholeNumber } from './rules';

type Dialog =
  | { kind: 'release'; release: Release | null }
  | { kind: 'issue'; release: Release }
  | { kind: 'rule'; rule: DistributionRule | null }
  | { kind: 'rule-delete'; rule: DistributionRule }
  | null;

function releaseValues(release: Release | null, purpose: string): FormValues {
  return {
    code: release?.code ?? '',
    title: release?.title ?? '',
    purpose: release?.purpose ?? purpose,
    revision_ids: release?.revision_ids ?? [],
  };
}

function ruleValues(rule: DistributionRule | null, purpose: string): FormValues {
  return {
    recipient_role_id: rule?.recipient_role_id ?? '',
    recipient_list_id: rule?.recipient_list_id ?? '',
    discipline_codes: rule?.discipline_codes ?? [],
    form_codes: rule?.form_codes ?? [],
    wbs_node_ids: rule?.wbs_node_ids ?? [],
    phase_codes: rule?.phase_codes ?? [],
    min_suitability: rule?.min_suitability ?? '',
    purpose: rule ? rule.purpose ?? '' : purpose,
    format: rule?.format ?? 'pdf',
    copies_paper: String(rule?.copies_paper ?? 0),
    ack_required: rule?.ack_required ?? false,
    active: rule?.active ?? true,
  };
}

function ruleBody(values: Record<string, unknown>): DistributionRuleInput {
  const body = { ...values };
  if (typeof body.copies_paper === 'string') body.copies_paper = wholeNumber(body.copies_paper) ?? 0;
  return body as DistributionRuleInput;
}

/** How the approval of a ready release stands. Approving happens on the approval routes screen. */
const APPROVAL_STATUS = {
  pending: 'design.ui.issue.approval_pending',
  approved: 'design.ui.issue.approval_approved',
  rejected: 'design.ui.issue.approval_rejected',
} as const;
const APPROVAL_TONE = { pending: 'warning', approved: 'success', rejected: 'error' } as const;

/** Who gets what if the release is issued now. The plan comes from the server; nothing is sent by looking. */
function IssuePlan({ ctx, release, onDuplicates }: { ctx: DesignContext; release: Release; onDuplicates: (n: number) => void }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const plan = useQuery({
    queryKey: designKeys.plan(ctx.projectId, release.id),
    queryFn: async () => {
      const rows = await previewRelease(ctx.projectId, release.id);
      onDuplicates(rows.reduce((sum, r) => sum + r.duplicates.length, 0));
      return rows;
    },
    retry: false,
  });
  if (plan.isLoading) return <p className="text-sm text-content-tertiary">{ui(t, 'design.ui.loading')}</p>;
  if (plan.isError) {
    return (
      <p role="alert" className="text-sm text-semantic-error" data-testid="issue-plan-failed">
        {refusalText(t, plan.error)}
      </p>
    );
  }
  const rows = plan.data ?? [];
  if (rows.length === 0) {
    return (
      <p role="alert" className="text-sm text-semantic-error" data-testid="issue-no-recipients">
        {errorText(t, 'release_no_recipients')}
      </p>
    );
  }
  return (
    <ul className="space-y-2" data-testid="issue-plan">
      {rows.map((row) => (
        <li key={row.recipient_key} className="rounded-md bg-surface-secondary p-2 text-sm">
          <p className="font-medium text-content-primary">
            {recipientName(row.recipient_key, ctx.roles) ?? ui(t, 'design.ui.issue.distribution_list')}
            <span className="ml-2 font-normal text-content-secondary">{vocab(t, PURPOSE, row.purpose)}</span>
          </p>
          <p className="text-xs text-content-secondary">{uiCount(t, 'design.ui.issue.plan_sends', row.revision_ids.length)}</p>
          {row.excluded.length > 0 && (
            <p className="text-xs text-semantic-warning">{uiCount(t, 'design.ui.issue.plan_excluded', row.excluded.length)}</p>
          )}
          {row.duplicates.length > 0 && (
            <p className="text-xs text-semantic-warning">{uiCount(t, 'design.ui.issue.plan_duplicates', row.duplicates.length)}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

export function IssuePanel({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const [dialog, setDialog] = useState<Dialog>(null);
  const [duplicates, setDuplicates] = useState(0);
  const action = useDesignAction(ctx.onChanged);
  const releases = useDesignList(ctx.projectId, 'releases', listReleases);
  const rules = useDesignList(ctx.projectId, 'distribution-rules', listDistributionRules);
  const recipientLists = useDesignOptions(ctx.projectId, 'recipient_lists', ctx.labels);
  const forms = useDesignOptions(ctx.projectId, 'forms', ctx.labels);
  const purpose = ctx.setup.default_distribution_purpose;
  const phases = ctx.setup.phases;

  const drawingChoices: FieldOption[] = releasable(ctx.drawings).map((d) => ({
    value: d.current_revision_id as string,
    label: ui(t, 'design.ui.issue.drawing_choice', { number: d.number, title: d.title, revision: d.revision_code ?? '' }),
  }));
  const disciplineChoices: FieldOption[] = [
    ...new Set([...ctx.roles.map((r) => r.discipline_code), ...ctx.drawings.map((d) => d.discipline_code)].filter((c): c is string => !!c)),
  ]
    .sort()
    .map((code) => ({ value: code, label: code }));

  const releaseFields: FieldSpec[] = [
    { name: 'title', label: ui(t, 'design.ui.issue.release_title'), type: 'text', required: true },
    { name: 'purpose', label: ui(t, 'design.ui.issue.purpose'), type: 'select', required: true, options: vocabOptions(t, PURPOSE) },
    { name: 'revision_ids', label: ui(t, 'design.ui.issue.drawings'), type: 'multi', options: drawingChoices, hint: ui(t, 'design.ui.issue.drawings_hint') },
    { name: 'code', label: ui(t, 'design.ui.field.code'), type: 'text', hint: ui(t, 'design.ui.field.code_hint') },
  ];
  const ruleFields: FieldSpec[] = [
    // A recipient is a design role or a distribution list; with no lists to choose from the role is required.
    { name: 'recipient_role_id', label: ui(t, 'design.ui.issue.recipient'), type: 'select', required: !recipientLists, options: roleOptions(ctx) },
    ...pickerField('recipient_list_id', ui(t, 'design.ui.issue.distribution_list'), recipientLists),
    { name: 'purpose', label: ui(t, 'design.ui.issue.purpose'), type: 'select', options: vocabOptions(t, PURPOSE), hint: ui(t, 'design.ui.issue.purpose_any_hint') },
    { name: 'format', label: ui(t, 'design.ui.issue.format'), type: 'select', required: true, options: vocabOptions(t, DIST_FORMAT) },
    { name: 'min_suitability', label: ui(t, 'design.ui.issue.min_status'), type: 'select', options: SUITABILITY_OPTIONS, hint: ui(t, 'design.ui.issue.min_status_hint') },
    { name: 'copies_paper', label: ui(t, 'design.ui.issue.paper_copies'), type: 'number' },
    { name: 'discipline_codes', label: ui(t, 'design.ui.issue.disciplines'), type: 'multi', options: disciplineChoices, hint: ui(t, 'design.ui.issue.all_when_empty') },
    ...(phases.length > 0
      ? [{ name: 'phase_codes', label: ui(t, 'design.ui.issue.phases'), type: 'multi' as const, options: phaseOptions(ctx), hint: ui(t, 'design.ui.issue.all_when_empty') }]
      : []),
    ...(forms ? [{ name: 'form_codes', label: ui(t, 'design.ui.issue.forms'), type: 'multi' as const, options: forms, hint: ui(t, 'design.ui.issue.all_when_empty') }] : []),
    ...(ctx.wbs.length > 0
      ? [{ name: 'wbs_node_ids', label: ui(t, 'design.ui.issue.wbs'), type: 'multi' as const, options: wbsOptions(ctx), hint: ui(t, 'design.ui.issue.all_when_empty') }]
      : []),
    { name: 'ack_required', label: ui(t, 'design.ui.issue.ack_required'), type: 'checkbox' },
    { name: 'active', label: ui(t, 'design.ui.issue.active'), type: 'checkbox' },
  ];
  const all = (codes: string[], name: (code: string) => string) =>
    codes.length === 0 ? ui(t, 'design.ui.issue.all') : fmtList(codes.map(name));
  const ruleProblems = (values: FormValues) =>
    str(values, 'recipient_role_id') || str(values, 'recipient_list_id') ? [] : [ui(t, 'design.ui.issue.recipient_required')];
  const recipientOf = (rule: DistributionRule) =>
    rule.recipient_role_id
      ? roleTitle(ctx, rule.recipient_role_id)
      : (recipientLists ?? []).find((o) => o.value === rule.recipient_list_id)?.label ?? ui(t, 'design.ui.issue.distribution_list');
  const newRelease = () => setDialog({ kind: 'release', release: null });

  return (
    <div className="space-y-4" data-testid="design-issue-panel">
      <PanelHeader
        title={ui(t, 'design.ui.issue.title')}
        hint={ui(t, 'design.ui.issue.hint')}
        action={
          <WriteButton onClick={newRelease} data-testid="release-add">
            {ui(t, 'design.ui.issue.release_add')}
          </WriteButton>
        }
      />
      <ListState
        query={releases}
        failedKey="design.ui.issue.load_failed"
        emptyIcon={<Send size={28} />}
        emptyTitle={ui(t, 'design.ui.issue.empty_title')}
        emptyBody={ui(t, 'design.ui.issue.empty_body')}
        emptyAction={{ label: ui(t, 'design.ui.issue.release_add'), onClick: newRelease }}
      />
      {hasRows(releases) && (
        <ul className="space-y-2" data-testid="releases-list">
          {(releases.data ?? []).map((release) => (
            <li key={release.id} className="rounded-lg border border-border-light p-3" data-testid="release-row">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-content-tertiary">{release.code}</span>
                <span className="font-medium text-content-primary">{release.title}</span>
                <ToneBadge tone={RELEASE_TONE[release.state]}>{vocab(t, RELEASE_STATE, release.state)}</ToneBadge>
                <span className="text-xs text-content-secondary">{vocab(t, PURPOSE, release.purpose)}</span>
                <span className="text-xs text-content-secondary">{uiCount(t, 'design.ui.issue.revision_count', release.revision_ids.length)}</span>
                {release.state === 'ready' && release.approval_status && release.approval_status !== 'none' && (
                  <ToneBadge tone={APPROVAL_TONE[release.approval_status]} testId="release-approval">
                    {ui(t, APPROVAL_STATUS[release.approval_status])}
                  </ToneBadge>
                )}
                {release.issued_at && (
                  <span className="text-xs text-content-secondary">
                    {ui(t, 'design.ui.issue.issued_on', {
                      date: fmtDate(release.issued_at),
                      name: ctx.personName(release.issued_by) ?? ui(t, 'design.ui.team.project_member'),
                    })}
                  </span>
                )}
                <span className="ml-auto flex flex-wrap gap-1">
                  {release.state === 'draft' && (
                    <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'release', release })}>
                      {ui(t, 'design.ui.action.edit')}
                    </WriteButton>
                  )}
                  {offered(release.can?.transitions, ['issued']).map(({ target, flag }) => (
                    <StepButton
                      key={target}
                      flag={flag}
                      label={ui(t, STEP_LABEL.release[target])}
                      busy={action.pending}
                      onClick={() => action.run(() => moveRelease(ctx.projectId, release.id, target))}
                      testId={`release-to-${target}`}
                    />
                  ))}
                  <StepButton
                    flag={release.can?.issue}
                    label={ui(t, STEP_LABEL.release.issued)}
                    variant="secondary"
                    onClick={() => {
                      setDuplicates(0);
                      setDialog({ kind: 'issue', release });
                    }}
                    testId="release-issue"
                  />
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      <PanelHeader
        title={ui(t, 'design.ui.issue.matrix_title')}
        hint={ui(t, 'design.ui.issue.matrix_hint')}
        action={
          <WriteButton need="manage" variant="secondary" onClick={() => setDialog({ kind: 'rule', rule: null })} data-testid="rule-add">
            {ui(t, 'design.ui.issue.rule_add')}
          </WriteButton>
        }
      />
      {(rules.data ?? []).length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-4 py-6 text-center text-sm text-content-tertiary">
          {rules.isLoading ? ui(t, 'design.ui.loading') : ui(t, 'design.ui.issue.matrix_empty')}
        </p>
      ) : (
        <Table
          testId="matrix-table"
          head={[
            ui(t, 'design.ui.issue.recipient'),
            ui(t, 'design.ui.issue.disciplines'),
            ui(t, 'design.ui.issue.phases'),
            ui(t, 'design.ui.issue.min_status'),
            ui(t, 'design.ui.issue.purpose'),
            ui(t, 'design.ui.issue.format'),
            '',
          ]}
        >
          {(rules.data ?? []).map((rule) => (
            <tr key={rule.id} data-testid="rule-row" className={rule.active ? undefined : 'opacity-60'}>
              <td className={CELL}>
                {recipientOf(rule)}
                {!rule.active && <span className="ml-2 text-xs text-content-tertiary">{ui(t, 'design.ui.issue.inactive')}</span>}
              </td>
              <td className={CELL_MUTED}>{all(rule.discipline_codes, (c) => c)}</td>
              <td className={CELL_MUTED}>{all(rule.phase_codes, (c) => phaseName(ctx.labels, phases, c))}</td>
              <td className={`${CELL_MUTED} font-mono`}>{rule.min_suitability ?? ''}</td>
              <td className={CELL_MUTED}>{rule.purpose ? vocab(t, PURPOSE, rule.purpose) : ui(t, 'design.ui.issue.any_purpose')}</td>
              <td className={CELL_MUTED}>
                {vocab(t, DIST_FORMAT, rule.format)}
                {rule.copies_paper > 0 && <p className="text-2xs">{uiCount(t, 'design.ui.issue.paper', rule.copies_paper)}</p>}
                {rule.ack_required && <p className="text-2xs">{ui(t, 'design.ui.issue.ack_required')}</p>}
              </td>
              <td className={`${CELL} whitespace-nowrap text-right`}>
                <WriteButton need="manage" size="sm" variant="ghost" onClick={() => setDialog({ kind: 'rule', rule })}>
                  {ui(t, 'design.ui.action.edit')}
                </WriteButton>
                <WriteButton need="manage" size="sm" variant="ghost" onClick={() => setDialog({ kind: 'rule-delete', rule })}>
                  {ui(t, 'design.ui.action.delete')}
                </WriteButton>
              </td>
            </tr>
          ))}
        </Table>
      )}

      {dialog?.kind === 'release' && (
        <FormDialog
          projectId={ctx.projectId}
          title={dialog.release ? ui(t, 'design.ui.issue.release_edit') : ui(t, 'design.ui.issue.release_add')}
          fields={releaseFields}
          initial={releaseValues(dialog.release, purpose)}
          submitLabel={dialog.release ? ui(t, 'design.ui.action.save') : ui(t, 'design.ui.issue.release_add')}
          submit={(values) =>
            dialog.release
              ? updateRelease(ctx.projectId, dialog.release.id, changedFields<ReleaseInput>(releaseValues(dialog.release, purpose), values))
              : createRelease(ctx.projectId, filledFields<ReleaseInput>(values))
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="release-form"
        />
      )}
      {dialog?.kind === 'issue' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.issue.issue_title', { code: dialog.release.code })}
          subtitle={ui(t, 'design.ui.issue.issue_body')}
          fields={[
            {
              name: 'duplicate_reason',
              label: ui(t, 'design.ui.issue.duplicate_reason'),
              type: 'textarea',
              required: duplicates > 0,
              showIf: () => duplicates > 0,
            },
          ]}
          initial={{ duplicate_reason: '' }}
          submitLabel={ui(t, STEP_LABEL.release.issued)}
          extra={() => <IssuePlan ctx={ctx} release={dialog.release} onDuplicates={setDuplicates} />}
          submit={(values) => issueRelease(ctx.projectId, dialog.release.id, str(values, 'duplicate_reason'))}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="issue-form"
        />
      )}
      {dialog?.kind === 'rule' && (
        <FormDialog
          projectId={ctx.projectId}
          title={dialog.rule ? ui(t, 'design.ui.issue.rule_edit') : ui(t, 'design.ui.issue.rule_add')}
          fields={ruleFields}
          problems={recipientLists ? ruleProblems : undefined}
          initial={ruleValues(dialog.rule, purpose)}
          submitLabel={dialog.rule ? ui(t, 'design.ui.action.save') : ui(t, 'design.ui.issue.rule_add')}
          submit={(values) =>
            dialog.rule
              ? updateDistributionRule(ctx.projectId, dialog.rule.id, ruleBody(changedFields(ruleValues(dialog.rule, purpose), values, ['min_suitability', 'purpose', 'recipient_role_id', 'recipient_list_id'])))
              : createDistributionRule(
                  ctx.projectId,
                  ruleBody({ ...filledFields(values), ack_required: flag(values, 'ack_required'), discipline_codes: list(values, 'discipline_codes') }),
                )
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="rule-form"
        />
      )}
      {dialog?.kind === 'rule-delete' && (
        <FormDialog
          projectId={ctx.projectId}
          danger
          title={ui(t, 'design.ui.issue.rule_delete_title')}
          subtitle={ui(t, 'design.ui.issue.rule_delete_body')}
          fields={[]}
          initial={{}}
          submitLabel={ui(t, 'design.ui.action.delete')}
          submit={() => deleteDistributionRule(ctx.projectId, dialog.rule.id)}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
    </div>
  );
}
