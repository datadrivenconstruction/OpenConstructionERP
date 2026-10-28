// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Conditions that were read out of a permit notice automatically and still
// wait for a person. Each one is compared with the notice, corrected where the
// reading is off, and then accepted or dismissed. Until then it counts nowhere.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';

import { Button } from '@/shared/ui/Button';

import { confirmProposal, extractConditions, type ConditionRow, type ExtractResult, type Permit } from './api';
import { ConditionDialog } from './ConditionDialogs';
import { usePermitAction } from './hooks';
import { CONDITION_KIND, TRIGGER, errorText, vocab, type TFn } from './labels';
import { Refusal, ToneBadge } from './PermitBits';
import { gate } from './rules';

function ProposalRow({
  projectId,
  proposal,
  onEdit,
}: {
  projectId: string;
  proposal: ConditionRow;
  onEdit: (proposal: ConditionRow) => void;
}) {
  const { t } = useTranslation();
  const decide = usePermitAction(projectId, (accept: boolean) => confirmProposal(projectId, proposal.id, accept));
  const due = vocab(t, TRIGGER, proposal.trigger);

  return (
    <li className="space-y-2 rounded-md border border-border-light bg-surface-primary p-3" data-testid="condition-proposal">
      <div className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
        <span className="font-medium text-content-primary" data-testid="proposal-number">
          {t('permits.ui.proposals.number', { defaultValue: 'Condition {{number}}', number: proposal.number })}
        </span>
        <ToneBadge tone="neutral">{vocab(t, CONDITION_KIND, proposal.kind)}</ToneBadge>
        {due && <span>{due}</span>}
        {proposal.confidence && (
          <span data-testid="proposal-confidence">
            {t('permits.ui.condition.confidence', {
              defaultValue: 'Confidence of the reading: {{percent}}%.',
              percent: Math.round(Number(proposal.confidence) * 100),
            })}
          </span>
        )}
      </div>
      <blockquote className="border-l-4 border-border pl-3 text-sm text-content-primary" data-testid="proposal-text">
        {proposal.text}
      </blockquote>
      {proposal.passage && (
        <figure className="rounded-md bg-surface-secondary px-3 py-2 text-xs text-content-secondary" data-testid="proposal-passage">
          <figcaption className="mb-1 font-medium">
            {t('permits.ui.proposals.passage', { defaultValue: 'Quoted from the notice' })}
          </figcaption>
          <q>{proposal.passage}</q>
        </figure>
      )}
      {proposal.text_span && (
        <p className="text-xs text-content-tertiary" data-testid="proposal-source">
          {t('permits.ui.proposals.source', { defaultValue: 'Place in the notice: {{place}}', place: proposal.text_span })}
        </p>
      )}
      {decide.error && <Refusal testId="proposal-refusal">{decide.error}</Refusal>}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" disabled={decide.busy} onClick={() => decide.run(true)} data-testid="proposal-accept">
          {t('permits.ui.proposals.accept', { defaultValue: 'Accept' })}
        </Button>
        <Button size="sm" variant="secondary" disabled={decide.busy} onClick={() => onEdit(proposal)} data-testid="proposal-edit">
          {t('permits.ui.proposals.edit', { defaultValue: 'Correct' })}
        </Button>
        <Button size="sm" variant="ghost" disabled={decide.busy} onClick={() => decide.run(false)} data-testid="proposal-dismiss">
          {t('permits.ui.proposals.dismiss', { defaultValue: 'Dismiss' })}
        </Button>
      </div>
    </li>
  );
}

export interface ConditionProposalsProps {
  projectId: string;
  /** The unconfirmed proposals of one permit. */
  proposals: ConditionRow[];
  personName: (userId: string | null | undefined) => string | null;
}

export function ConditionProposals({ projectId, proposals, personName }: ConditionProposalsProps) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<ConditionRow | null>(null);
  // The list refreshes after a save, so the dialog reads the row as it is now.
  const current = editing ? proposals.find((p) => p.id === editing.id) ?? editing : null;

  if (proposals.length === 0) return null;

  return (
    <section className="space-y-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg p-3" data-testid="condition-proposals">
      <h4 className="flex items-center gap-2 text-sm font-medium text-content-primary">
        <Sparkles size={16} className="shrink-0 text-semantic-warning" aria-hidden />
        {t('permits.ui.proposals.title', {
          count: proposals.length,
          defaultValue_one: '{{count}} condition read out of the notice, waiting for you',
          defaultValue_other: '{{count}} conditions read out of the notice, waiting for you',
        })}
      </h4>
      <p className="text-xs text-content-secondary">
        {t('permits.ui.proposals.body', {
          defaultValue:
            'Compare each one with the notice. Correct what was read wrongly, then accept it or dismiss it. A proposal counts nowhere until you accept it.',
        })}
      </p>
      <ul className="space-y-2">
        {proposals.map((p) => (
          <ProposalRow key={p.id} projectId={projectId} proposal={p} onEdit={setEditing} />
        ))}
      </ul>
      {current && (
        <ConditionDialog
          open
          onClose={() => setEditing(null)}
          projectId={projectId}
          permitId={current.permit_id}
          condition={current}
          personName={personName}
        />
      )}
    </section>
  );
}

/* ── Reading the notice ───────────────────────────────────────────────── */

/**
 * The action that reads the conditions out of the permit's decision notice.
 * It is offered only when the server says so, and says in words why not: no
 * AI provider configured, or no notice document on the decision.
 */
export function ExtractConditions({ projectId, permit }: { projectId: string; permit: Permit }) {
  const { t } = useTranslation();
  const [result, setResult] = useState<ExtractResult | null>(null);
  const read = usePermitAction(projectId, () => extractConditions(projectId, permit.id), setResult);
  const offer = gate(permit.can?.propose_conditions, false);
  if (!offer.show) return null;

  return (
    <div className="space-y-2" data-testid="extract-conditions">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="sm"
          variant="secondary"
          icon={<Sparkles size={14} />}
          loading={read.busy}
          disabled={!offer.enabled}
          onClick={() => {
            setResult(null);
            read.run(undefined);
          }}
          data-testid="permit-propose"
        >
          {t('permits.ui.extract.submit', { defaultValue: 'Read conditions from the notice' })}
        </Button>
        <span className="text-xs text-content-tertiary">
          {read.busy
            ? t('permits.ui.extract.busy', { defaultValue: 'Reading the notice. This can take a minute.' })
            : t('permits.ui.extract.hint', {
                defaultValue: 'What is found comes as proposals. A proposal counts nowhere until you accept it.',
              })}
        </span>
      </div>
      {!offer.enabled && offer.reason && (
        <p
          role="status"
          className="rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-secondary"
          data-testid="extract-unavailable"
        >
          {errorText(t as TFn, offer.reason, null)}
        </p>
      )}
      {read.error && <Refusal testId="extract-refusal">{read.error}</Refusal>}
      {result && (
        <div role="status" className="space-y-1 rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-primary" data-testid="extract-result">
          <p>
            {result.items.length > 0
              ? t('permits.ui.extract.found', {
                  count: result.items.length,
                  defaultValue_one: '{{count}} condition found. Check it below.',
                  defaultValue_other: '{{count}} conditions found. Check them below.',
                })
              : t('permits.ui.extract.none', { defaultValue: 'No new condition was found in the notice.' })}
          </p>
          {result.already_known > 0 && (
            <p className="text-content-secondary">
              {t('permits.ui.extract.already_known', {
                count: result.already_known,
                defaultValue_one: '{{count}} condition is already on the permit and was left out.',
                defaultValue_other: '{{count}} conditions are already on the permit and were left out.',
              })}
            </p>
          )}
          {result.rejected > 0 && (
            <p className="text-content-secondary">
              {t('permits.ui.extract.rejected', {
                count: result.rejected,
                defaultValue_one: '{{count}} item of the answer could not be read as a condition and was left out.',
                defaultValue_other: '{{count}} items of the answer could not be read as conditions and were left out.',
              })}
            </p>
          )}
          {result.document_cut && (
            <p className="text-content-secondary">
              {t('permits.ui.extract.document_cut', {
                defaultValue: 'The notice is long, so only its first part was read. Check the rest by hand.',
              })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
