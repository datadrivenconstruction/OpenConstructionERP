// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One condition, opened in place: its wording, when it is due, who owns it,
// the evidence gathered so far and how it was closed. The steps on offer are
// the ones its state leaves open.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Trash2 } from 'lucide-react';

import { fmtList } from '@/shared/lib/formatters';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';

import { confirmProposal, removeEvidence, submitEvidence, type ConditionRow } from './api';
import { ConditionDialog, DischargeDialog, EvidenceDialog, LinkRequirementDialog, OngoingDialog } from './ConditionDialogs';
import { refusalText, useConditionDetail, useDocumentNames, usePermitAction } from './hooks';
import { CONDITION_KIND, CONDITION_STATE, DISCHARGE_MODE, EVIDENCE_KIND, TOPIC, TRIGGER, errorText, vocab, type TFn } from './labels';
import { CONDITION_TONE, Fact, GatedButton, PanelHeader, PersonChip, Refusal, RefusedActions, ToneBadge, dateText } from './PermitBits';
import { conditionActions, dischargeModes, gate, type ConditionAction } from './rules';

export interface ConditionPanelProps {
  projectId: string;
  conditionId: string;
  /** The register row, for what only the list knows: overdue, the permit reference. */
  row: ConditionRow | null;
  personName: (userId: string | null | undefined) => string | null;
  onBack: () => void;
}

type Dialog = 'edit' | 'evidence' | 'discharge' | 'breach' | 'in_compliance' | 'link' | null;

export function ConditionPanel({ projectId, conditionId, row, personName, onBack }: ConditionPanelProps) {
  const { t } = useTranslation();
  const detailQ = useConditionDetail(projectId, conditionId);
  const hasDocument = !!detailQ.data?.evidence.some((e) => e.kind === 'cde_revision' && !e.ref_title);
  const documentName = useDocumentNames(projectId, hasDocument);
  const [dialog, setDialog] = useState<Dialog>(null);
  const submit = usePermitAction(projectId, () => submitEvidence(projectId, conditionId));
  const confirm = usePermitAction(
    projectId,
    (accept: boolean) => confirmProposal(projectId, conditionId, accept),
    (result) => {
      if (!result.accepted) onBack();
    },
  );
  const unlink = usePermitAction(projectId, (evidenceId: string) => removeEvidence(projectId, conditionId, evidenceId));
  const back = t('permits.ui.back_to_conditions', { defaultValue: 'Back to the conditions' });
  const person = (id: string | null) =>
    id ? personName(id) ?? t('permits.ui.unknown_person', { defaultValue: 'Project member' }) : null;

  if (detailQ.isLoading) return <SkeletonTable rows={4} columns={4} />;
  if (detailQ.isError || !detailQ.data) {
    return (
      <div className="space-y-3">
        <Button variant="ghost" size="sm" onClick={onBack}>
          {back}
        </Button>
        <ErrorState
          title={t('permits.ui.condition.load_failed', { defaultValue: 'The condition could not be loaded' })}
          hint={refusalText(t as TFn, detailQ.error)}
          onRetry={() => detailQ.refetch()}
        />
      </div>
    );
  }

  const c = detailQ.data;
  const actions = conditionActions(c);
  const can = (a: ConditionAction) => actions.includes(a);
  const refusal = submit.error ?? confirm.error ?? unlink.error;
  const canUnlink = c.state === 'open' || c.state === 'evidence_submitted';
  // The server names who may close the condition; when it refuses every way, the button says why.
  const gates = c.can?.discharge;
  const openModes = dischargeModes(c).filter((m) => gates?.[m]?.applies !== false);
  const canDischarge = can('discharge') && openModes.length > 0;
  const refused = openModes.map((m) => gates?.[m]);
  // Tracking a limit follows the server alone; a proposal nobody confirmed counts nowhere, so it waits.
  const linkGate = gate(c.can?.link_requirement, can('link_requirement'));
  const dischargeRefusal =
    refused.length > 0 && refused.every((g) => g?.allowed === false) ? errorText(t as TFn, refused[0]?.reason ?? '', null) : null;

  return (
    <div className="space-y-5" data-testid="condition-panel">
      <PanelHeader
        title={t('permits.ui.condition.heading', { defaultValue: 'Condition {{number}}', number: c.number })}
        subtitle={
          row?.permit_reference
            ? t('permits.ui.conditions.of_permit', { defaultValue: 'Permit {{reference}}', reference: row.permit_reference })
            : undefined
        }
        badge={
          <>
            {c.confirmed ? (
              <ToneBadge tone={CONDITION_TONE[c.state]} testId="condition-state">
                {vocab(t, CONDITION_STATE, c.state)}
              </ToneBadge>
            ) : (
              <ToneBadge tone="warning" testId="condition-state">
                {t('permits.ui.conditions.proposal', { defaultValue: 'Proposal, to confirm' })}
              </ToneBadge>
            )}
            {row?.overdue && <ToneBadge tone="error">{t('permits.ui.conditions.overdue', { defaultValue: 'Overdue' })}</ToneBadge>}
          </>
        }
        onBack={onBack}
        backLabel={back}
        actions={
          <>
            {can('confirm') && (
              <>
                <GatedButton gate={gate(c.can?.confirm, true)} size="sm" loading={confirm.busy} onClick={() => confirm.run(true)} data-testid="condition-confirm">
                  {t('permits.ui.condition.confirm', { defaultValue: 'Confirm as a condition' })}
                </GatedButton>
                <GatedButton gate={gate(c.can?.confirm, true)} size="sm" variant="ghost" disabled={confirm.busy} onClick={() => confirm.run(false)} data-testid="condition-reject">
                  {t('permits.ui.condition.reject', { defaultValue: 'Discard the proposal' })}
                </GatedButton>
              </>
            )}
            {can('submit_evidence') && (
              <GatedButton gate={gate(c.can?.submit_evidence, true)}
                size="sm"
                variant={c.evidence.length === 0 ? 'secondary' : 'primary'}
                disabled={c.evidence.length === 0}
                loading={submit.busy}
                onClick={() => submit.run(undefined)}
                data-testid="condition-submit-evidence"
              >
                {t('permits.ui.condition.submit_evidence', { defaultValue: 'Submit the evidence for checking' })}
              </GatedButton>
            )}
            {can('in_compliance') && (
              <GatedButton gate={gate(c.can?.in_compliance, true)} size="sm" variant={c.state === 'breach' ? 'primary' : 'secondary'} onClick={() => setDialog('in_compliance')} data-testid="condition-in-compliance">
                {c.state === 'breach'
                  ? t('permits.ui.condition.remedied', { defaultValue: 'The breach is remedied' })
                  : t('permits.ui.ongoing.submit_compliance', { defaultValue: 'Record compliance' })}
              </GatedButton>
            )}
            {canDischarge && (
              <Button size="sm" variant={c.state === 'evidence_submitted' ? 'primary' : 'secondary'} disabled={!!dischargeRefusal} onClick={() => setDialog('discharge')} data-testid="condition-discharge">
                {t('permits.ui.discharge.submit', { defaultValue: 'Close condition' })}
              </Button>
            )}
            {can('breach') && (
              <GatedButton gate={gate(c.can?.breach, true)} size="sm" variant="danger" onClick={() => setDialog('breach')} data-testid="condition-breach">
                {t('permits.ui.ongoing.submit_breach', { defaultValue: 'Raise breach' })}
              </GatedButton>
            )}
            {can('edit') && (
              <GatedButton gate={gate(c.can?.edit, true)} size="sm" variant="ghost" onClick={() => setDialog('edit')} data-testid="condition-edit">
                {t('permits.ui.edit', { defaultValue: 'Edit' })}
              </GatedButton>
            )}
            {c.confirmed && (
              <GatedButton gate={linkGate} size="sm" variant="ghost" onClick={() => setDialog('link')} data-testid="condition-link">
                {t('permits.ui.link.open', { defaultValue: 'Track a limit' })}
              </GatedButton>
            )}
          </>
        }
      />
      <RefusedActions
        items={[
          can('confirm') && [t('permits.ui.condition.confirm', { defaultValue: 'Confirm as a condition' }), gate(c.can?.confirm, true)],
          can('submit_evidence') && [
            t('permits.ui.condition.submit_evidence', { defaultValue: 'Submit the evidence for checking' }),
            gate(c.can?.submit_evidence, true),
          ],
          can('in_compliance') && [t('permits.ui.ongoing.submit_compliance', { defaultValue: 'Record compliance' }), gate(c.can?.in_compliance, true)],
          can('breach') && [t('permits.ui.ongoing.submit_breach', { defaultValue: 'Raise breach' }), gate(c.can?.breach, true)],
          can('edit') && [t('permits.ui.edit', { defaultValue: 'Edit' }), gate(c.can?.edit, true)],
          can('add_evidence') && [t('permits.ui.evidence.submit', { defaultValue: 'Add evidence' }), gate(c.can?.add_evidence, true)],
          c.confirmed && [t('permits.ui.link.open', { defaultValue: 'Track a limit' }), linkGate],
        ]}
      />
      {refusal && <Refusal testId="condition-refusal">{refusal}</Refusal>}
      {canDischarge && dischargeRefusal && (
        <p role="status" className="rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-secondary" data-testid="discharge-refusal">
          {t('permits.ui.discharge.not_you', { defaultValue: 'You cannot close this condition: {{reason}}', reason: dischargeRefusal })}
        </p>
      )}

      {!c.confirmed && (
        <p role="status" className="rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm text-content-primary" data-testid="proposal-banner">
          {t('permits.ui.condition.proposal_banner', {
            defaultValue: 'This condition was read out of the notice automatically. Compare it with the notice. Until you confirm it, it counts nowhere.',
          })}
          {c.confidence && (
            <>
              {' '}
              {t('permits.ui.condition.confidence', {
                defaultValue: 'Confidence of the reading: {{percent}}%.',
                percent: Math.round(Number(c.confidence) * 100),
              })}
            </>
          )}
        </p>
      )}

      <blockquote className="rounded-lg border-l-4 border-border bg-surface-secondary px-4 py-3 text-sm text-content-primary" data-testid="condition-text">
        {c.text}
      </blockquote>

      {c.state === 'breach' && c.breach_note && (
        <Refusal testId="breach-note">
          {t('permits.ui.condition.breach_note', { defaultValue: 'Breach: {{note}}', note: c.breach_note })}
        </Refusal>
      )}

      <dl className="grid gap-4 rounded-lg border border-border bg-surface-elevated shadow-sm p-4 sm:grid-cols-2 lg:grid-cols-4">
        <Fact label={t('permits.ui.condition.kind', { defaultValue: 'Kind' })}>{vocab(t, CONDITION_KIND, c.kind)}</Fact>
        <Fact label={t('permits.ui.condition.trigger', { defaultValue: 'When it is due' })}>
          {vocab(t, TRIGGER, c.trigger) || '-'}
          {(c.stage_ref || c.event_text) && <span className="block text-xs text-content-tertiary">{c.stage_ref || c.event_text}</span>}
        </Fact>
        <Fact label={t('permits.ui.condition.due_date', { defaultValue: 'Due date' })}>{dateText(c.due_date)}</Fact>
        <Fact label={t('permits.ui.condition.topic', { defaultValue: 'Topic' })}>{vocab(t, TOPIC, c.topic)}</Fact>
        {c.kind !== 'information' && (
          <Fact label={t('permits.ui.condition.owner', { defaultValue: 'Owner' })}>
            <PersonChip name={person(c.owner_user_id)} />
          </Fact>
        )}
        {c.responsible_party && (
          <Fact label={t('permits.ui.condition.responsible_party', { defaultValue: 'Company that carries it out' })}>{c.responsible_party}</Fact>
        )}
        {c.evidence_required && (
          <Fact label={t('permits.ui.condition.evidence_required', { defaultValue: 'What will prove it is met' })}>{c.evidence_required}</Fact>
        )}
        {c.requires_authority_approval && (
          <Fact label={t('permits.ui.condition.closing', { defaultValue: 'Closing' })}>
            {t('permits.ui.condition.requires_authority', { defaultValue: 'Only the authority can discharge this condition' })}
          </Fact>
        )}
      </dl>

      {c.kind !== 'information' && (
        <section className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-content-primary">{t('permits.ui.evidence.heading', { defaultValue: 'Evidence' })}</h3>
            {can('add_evidence') && (
              <GatedButton gate={gate(c.can?.add_evidence, true)} size="sm" variant={c.evidence.length === 0 ? 'primary' : 'secondary'} onClick={() => setDialog('evidence')} data-testid="condition-add-evidence">
                {t('permits.ui.evidence.submit', { defaultValue: 'Add evidence' })}
              </GatedButton>
            )}
          </div>
          {c.evidence.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border-light p-4 text-sm text-content-tertiary" data-testid="evidence-empty">
              {t('permits.ui.evidence.none', {
                defaultValue: 'No evidence yet. Add what shows the condition is met, then submit it for checking by a second person.',
              })}
            </p>
          ) : (
            <ul className="space-y-1.5" data-testid="evidence-list">
              {c.evidence.map((e) => (
                <li key={e.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-3 text-sm">
                  <span className="font-medium text-content-primary">{vocab(t, EVIDENCE_KIND, e.kind)}</span>
                  {e.kind !== 'cde_revision' && e.ref_id && <span className="break-all text-content-secondary">{e.ref_id}</span>}
                  {e.kind === 'cde_revision' && (
                    <span className="text-content-secondary" data-testid="evidence-document">
                      {fmtList([e.ref_title ?? '', e.ref_revision ?? '']) ||
                        documentName(e.ref_id) ||
                        t('permits.ui.evidence.document_older', { defaultValue: 'An earlier revision of a project document' })}
                    </span>
                  )}
                  {e.note && <span className="text-content-secondary">{e.note}</span>}
                  <span className="ml-auto text-xs text-content-tertiary">
                    {fmtList([person(e.added_by) ?? '', e.added_at ? dateText(e.added_at) : ''])}
                  </span>
                  {canUnlink && (
                    <GatedButton gate={gate(c.can?.remove_evidence, true)}
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={14} />}
                      disabled={unlink.busy}
                      aria-label={t('permits.ui.evidence.remove', { defaultValue: 'Remove this evidence' })}
                      onClick={() => unlink.run(e.id)}
                      data-testid="evidence-remove"
                    />
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {c.discharges.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-content-primary">{t('permits.ui.discharge.heading', { defaultValue: 'How it was closed' })}</h3>
          <ul className="space-y-1.5" data-testid="discharge-list">
            {c.discharges.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-3 text-sm">
                <span className="font-medium text-content-primary">{vocab(t, DISCHARGE_MODE, d.mode)}</span>
                <span className="text-content-secondary">{dateText(d.date)}</span>
                {d.note && <span className="text-content-secondary">{d.note}</span>}
                {d.verifier_user_id && (
                  <span className="ml-auto text-xs text-content-tertiary">
                    {t('permits.ui.discharge.checked_by', { defaultValue: 'Checked by {{name}}', name: person(d.verifier_user_id) })}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <ConditionDialog
        open={dialog === 'edit'}
        onClose={() => setDialog(null)}
        projectId={projectId}
        permitId={c.permit_id}
        condition={c}
        personName={personName}
      />
      <EvidenceDialog open={dialog === 'evidence'} onClose={() => setDialog(null)} projectId={projectId} condition={c} />
      <DischargeDialog open={dialog === 'discharge'} onClose={() => setDialog(null)} projectId={projectId} condition={c} can={gates} />
      <OngoingDialog
        open={dialog === 'breach' || dialog === 'in_compliance'}
        onClose={() => setDialog(null)}
        projectId={projectId}
        condition={c}
        target={dialog === 'breach' ? 'breach' : 'in_compliance'}
      />
      <LinkRequirementDialog open={dialog === 'link'} onClose={() => setDialog(null)} projectId={projectId} condition={c} />
    </div>
  );
}
