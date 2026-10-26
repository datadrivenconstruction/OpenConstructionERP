// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ProposalReviewList - the human-confirm step for minutes built from a
// recording. Every proposal (summary, decision, action, open question,
// spelling correction) shows its confidence, can be edited, and is confirmed
// or rejected one by one. Nothing is applied until a person confirms it; a
// confirmed action becomes a tracked meeting action and, optionally, a task.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Link2, X } from 'lucide-react';
import { Badge, Button, ConfidenceBadge } from '@/shared/ui';
import type { Proposal, ProposalEdit, ProposalSet } from './audioApi';
import {
  actionProblems,
  canConfirm,
  draftFor,
  groupProposals,
  resolveOwner,
  reviewEntry,
  type ProposalDraft,
} from './audioLogic';

export interface ReviewPerson {
  name: string;
  contact_id: string | null;
}

interface ProposalReviewListProps {
  proposals: ProposalSet;
  people: ReviewPerson[];
  busy: boolean;
  onReview: (entry: ProposalEdit, createTask: boolean) => void;
}

const fieldCls =
  'w-full rounded-md border border-border bg-surface-primary px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function ProposalReviewList({ proposals, people, busy, onReview }: ProposalReviewListProps) {
  const { t } = useTranslation();
  const items = proposals.items ?? [];
  const [drafts, setDrafts] = useState<Record<string, ProposalDraft>>({});
  const [createTasks, setCreateTasks] = useState(true);
  const pending = items.filter((i) => i.status === 'pending');
  const reviewed = items.filter((i) => i.status !== 'pending');

  const draft = (p: Proposal): ProposalDraft => drafts[p.id] ?? draftFor(p);
  const patch = (p: Proposal, change: Partial<ProposalDraft>) =>
    setDrafts((prev) => ({ ...prev, [p.id]: { ...draft(p), ...change } }));

  const kindLabel = (kind: Proposal['kind']) =>
    t(`meetings.audio.kind_${kind}`, {
      defaultValue: {
        summary: 'Summary',
        decision: 'Decision',
        action: 'Action item',
        question: 'Open question',
        correction: 'Spelling correction',
      }[kind],
    });

  if (!items.length) {
    return (
      <p className="text-xs text-content-tertiary" data-testid="proposals-empty">
        {t('meetings.audio.proposals_none', {
          defaultValue: 'Nothing was found to propose. Edit the transcript or write the minutes by hand.',
        })}
      </p>
    );
  }

  return (
    <div className="space-y-3" data-testid="proposal-review">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs text-content-secondary">
          {proposals.ai_generated
            ? t('meetings.audio.proposals_ai_note', {
                defaultValue: 'Proposed by AI. Check each item, edit it if needed, then confirm or reject it.',
              })
            : t('meetings.audio.proposals_heuristic_note', {
                defaultValue:
                  'No AI is configured, so these come from simple keyword rules and are rough. Check each one carefully.',
              })}
        </p>
        <label className="flex items-center gap-1.5 text-xs text-content-secondary">
          <input
            type="checkbox"
            checked={createTasks}
            onChange={(e) => setCreateTasks(e.target.checked)}
            data-testid="proposal-create-tasks"
          />
          {t('meetings.audio.create_tasks', { defaultValue: 'Also create a task for each confirmed action' })}
        </label>
      </div>

      {groupProposals(pending).map((group) => (
        <div key={group.kind} className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
            {kindLabel(group.kind)}
          </p>
          {group.items.map((p) => {
            const d = draft(p);
            const problems = p.kind === 'action' ? actionProblems(d) : [];
            return (
              <div
                key={p.id}
                className="rounded-lg border border-border-light bg-surface-primary p-2.5 space-y-2"
                data-testid={`proposal-${p.id}`}
              >
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    {p.kind === 'correction' ? (
                      <div className="flex items-center gap-1.5 flex-wrap text-sm">
                        <input
                          className={`${fieldCls} max-w-[40%]`}
                          value={d.heard}
                          onChange={(e) => patch(p, { heard: e.target.value })}
                          aria-label={t('meetings.audio.correction_heard', { defaultValue: 'Heard as' })}
                        />
                        <span className="text-content-tertiary">&rarr;</span>
                        <input
                          className={`${fieldCls} max-w-[40%]`}
                          value={d.term}
                          onChange={(e) => patch(p, { term: e.target.value })}
                          aria-label={t('meetings.audio.correction_term', { defaultValue: 'Correct spelling' })}
                        />
                      </div>
                    ) : (
                      <textarea
                        className={`${fieldCls} resize-vertical`}
                        rows={p.kind === 'summary' ? 4 : 2}
                        value={d.text}
                        onChange={(e) => patch(p, { text: e.target.value })}
                        aria-label={kindLabel(p.kind)}
                      />
                    )}
                  </div>
                  <ConfidenceBadge score={p.confidence} showScore />
                </div>

                {p.kind === 'action' && (
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <label className="text-xs text-content-secondary space-y-0.5">
                      <span>{t('meetings.audio.owner', { defaultValue: 'Owner' })}</span>
                      <input
                        className={fieldCls}
                        list={`owners-${p.id}`}
                        value={d.owner_name}
                        onChange={(e) => patch(p, resolveOwner(e.target.value, people))}
                        data-testid={`proposal-owner-${p.id}`}
                      />
                      <datalist id={`owners-${p.id}`}>
                        {people.map((person) => (
                          <option key={`${person.name}-${person.contact_id ?? ''}`} value={person.name} />
                        ))}
                      </datalist>
                    </label>
                    <label className="text-xs text-content-secondary space-y-0.5">
                      <span>{t('meetings.audio.due_date', { defaultValue: 'Due date' })}</span>
                      <input
                        type="date"
                        className={fieldCls}
                        value={d.due_date}
                        onChange={(e) => patch(p, { due_date: e.target.value })}
                        data-testid={`proposal-due-${p.id}`}
                      />
                      {p.due_hint && !d.due_date && (
                        <span className="block text-2xs text-content-tertiary">
                          {t('meetings.audio.due_hint', { defaultValue: 'Said: {{hint}}', hint: p.due_hint })}
                        </span>
                      )}
                    </label>
                    <div className="text-xs text-content-secondary space-y-0.5">
                      <span>{t('meetings.audio.linked_record', { defaultValue: 'Linked record' })}</span>
                      {d.linked_entity ? (
                        <div className="flex items-center gap-1">
                          <Badge variant="neutral" size="sm">
                            <Link2 size={10} className="mr-1" />
                            {d.linked_entity.label || d.linked_entity.type}
                          </Badge>
                          <button
                            type="button"
                            className="text-content-tertiary hover:text-semantic-error"
                            onClick={() => patch(p, { linked_entity: null })}
                            aria-label={t('meetings.audio.unlink', { defaultValue: 'Remove link' })}
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ) : (
                        <span className="block text-content-tertiary">
                          {t('meetings.audio.no_link', { defaultValue: 'None' })}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {p.source_quote && (
                  <p className="text-xs italic text-content-tertiary line-clamp-2">&ldquo;{p.source_quote}&rdquo;</p>
                )}

                {problems.length > 0 && (
                  <p className="text-xs text-semantic-warning" data-testid={`proposal-problems-${p.id}`}>
                    {problems
                      .map((pr) =>
                        t(`meetings.audio.problem_${pr}`, {
                          defaultValue: {
                            text: 'Describe the action.',
                            owner: 'Set an owner.',
                            due: 'Set a due date.',
                          }[pr],
                        }),
                      )
                      .join(' ')}
                  </p>
                )}

                <div className="flex items-center justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onReview(reviewEntry(p, d, 'reject'), createTasks)}
                    data-testid={`proposal-reject-${p.id}`}
                  >
                    <X size={14} className="mr-1" />
                    {t('meetings.audio.reject', { defaultValue: 'Reject' })}
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={busy || !canConfirm(p, d)}
                    onClick={() => onReview(reviewEntry(p, d, 'confirm'), createTasks)}
                    data-testid={`proposal-confirm-${p.id}`}
                  >
                    <Check size={14} className="mr-1" />
                    {t('meetings.audio.confirm', { defaultValue: 'Confirm' })}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      ))}

      {reviewed.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('meetings.audio.reviewed', { defaultValue: 'Reviewed' })}
          </p>
          {reviewed.map((p) => (
            <div key={p.id} className="flex items-start gap-2 text-xs text-content-secondary">
              <Badge variant={p.status === 'confirmed' ? 'success' : 'neutral'} size="sm">
                {p.status === 'confirmed'
                  ? t('meetings.audio.status_confirmed', { defaultValue: 'Confirmed' })
                  : t('meetings.audio.status_rejected', { defaultValue: 'Rejected' })}
              </Badge>
              <span className="text-content-tertiary shrink-0">{kindLabel(p.kind)}</span>
              <span className="truncate">{p.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
