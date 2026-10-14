// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The commitments register: every promise the project made to a stakeholder,
// who delivers it, by when, and where it stands. Each row offers the moves its
// state allows. Whether the reader may make a move is the server's call: each
// commitment carries a flag per move, and a move that is off stays visible
// with the server's reason next to it.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Handshake, Hourglass, Pencil, Plus } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate, fmtList } from '@/shared/lib/formatters';
import { formatCurrency } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';

import type { Commitment, CommitmentStatus, CommitmentTarget, EngagementEvent, Stakeholder } from './api';
import { CommitmentDialog, TransitionDialog } from './CommitmentDialog';
import { CommitmentLinks, useCommitmentLinkNames } from './CommitmentLinks';
import { COMMITMENT_TONE, FOCUS_CLASS, GatedButton, ToneBadge, useFocusRow } from './StakeholderBits';
import { COMMITMENT_ACTION, COMMITMENT_BLOCK, COMMITMENT_CATEGORY, COMMITMENT_STATUS, WRITE_NOTE, vocab, type TFn } from './labels';
import { datedName } from './links';
import { COMMITMENT_MOVES } from './rules';
import { namesOf, type Screen } from './screen';

type Filter = 'open' | 'overdue' | 'closed' | 'all';

const OPEN: CommitmentStatus[] = ['proposed', 'agreed', 'in_progress', 'breached', 'fulfilled'];

export interface CommitmentsPanelProps {
  screen: Screen;
  commitments: Commitment[];
  stakeholders: Stakeholder[];
  events: EngagementEvent[];
  /** The commitment a link pointed at: shown whatever its state, marked and scrolled to. */
  focusId?: string | null;
}

type Dialog =
  | { kind: 'edit'; commitment: Commitment | null }
  | { kind: 'move'; commitment: Commitment; target: CommitmentTarget }
  | null;

export function CommitmentsPanel({ screen, commitments, stakeholders, events, focusId = null }: CommitmentsPanelProps) {
  const { t } = useTranslation();
  const { projectId, settings, personName, onChanged } = screen;
  const can = settings.can.edit;
  const linkNames = useCommitmentLinkNames(projectId, commitments);
  const addToast = useToastStore((s) => s.addToast);
  const focused = focusId ? commitments.find((c) => c.id === focusId) : undefined;
  // A link to a closed commitment opens the list that holds it.
  const [filter, setFilter] = useState<Filter>(focused && !OPEN.includes(focused.status) ? 'all' : 'open');
  const focusRef = useFocusRow<HTMLLIElement>(focusId, !!focused);
  const [dialog, setDialog] = useState<Dialog>(null);

  const counts = useMemo(
    () => ({
      open: commitments.filter((c) => OPEN.includes(c.status)).length,
      overdue: commitments.filter((c) => c.overdue).length,
      closed: commitments.filter((c) => !OPEN.includes(c.status)).length,
      all: commitments.length,
    }),
    [commitments],
  );
  const shown = commitments.filter((c) => {
    if (filter === 'open') return OPEN.includes(c.status);
    if (filter === 'overdue') return c.overdue;
    if (filter === 'closed') return !OPEN.includes(c.status);
    return true;
  });

  const add = (
    <GatedButton
      allowed={can}
      capability="edit"
      icon={<Plus size={14} />}
      onClick={() => setDialog({ kind: 'edit', commitment: null })}
      data-testid="commitment-add"
    >
      {t('stakeholders.ui.commitment.add_title', { defaultValue: 'Record a commitment' })}
    </GatedButton>
  );

  const moved = (result: Commitment) => {
    setDialog(null);
    onChanged();
    if (result.pending_target) {
      addToast({
        type: 'info',
        title: t('stakeholders.ui.commitment.sent_for_approval', {
          defaultValue: 'Sent for approval. The commitment changes once the approval is complete.',
        }),
      });
    }
    for (const note of result.warnings ?? []) {
      addToast({ type: 'warning', title: vocab(t, WRITE_NOTE, note) });
    }
  };

  const dialogs = (
    <>
      {dialog?.kind === 'edit' && (
        <CommitmentDialog
          screen={screen}
          commitment={dialog.commitment}
          stakeholders={stakeholders}
          events={events}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            onChanged();
          }}
        />
      )}
      {dialog?.kind === 'move' && (
        <TransitionDialog
          screen={screen}
          commitment={dialog.commitment}
          target={dialog.target}
          onClose={() => setDialog(null)}
          onDone={moved}
        />
      )}
    </>
  );

  if (commitments.length === 0) {
    return (
      <>
        <EmptyState
          icon={<Handshake size={28} />}
          title={t('stakeholders.ui.commitment.empty_title', { defaultValue: 'No commitments yet' })}
          description={t('stakeholders.ui.commitment.empty_body', {
            defaultValue: 'Write down what the project promises a stakeholder: quiet hours, a noise barrier, a monthly update. Each promise gets an owner and a due date, so none is forgotten.',
          })}
          action={add}
        />
        {dialogs}
      </>
    );
  }

  const filters: Array<[Filter, string]> = [
    ['open', t('stakeholders.ui.commitment.filter_open', { defaultValue: 'Open' })],
    ['overdue', t('stakeholders.ui.overdue', { defaultValue: 'Overdue' })],
    ['closed', t('stakeholders.ui.commitment.filter_closed', { defaultValue: 'Closed' })],
    ['all', t('stakeholders.ui.commitment.filter_all', { defaultValue: 'All' })],
  ];

  return (
    <div className="space-y-4" data-testid="commitments-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div
          className="flex flex-wrap gap-1.5"
          role="group"
          aria-label={t('stakeholders.ui.commitment.filter', { defaultValue: 'Filter commitments' })}
        >
          {filters.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
              data-testid={`commitment-filter-${id}`}
              className={clsx(
                'rounded-full border px-3 py-1 text-xs',
                filter === id ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text' : 'border-border-light text-content-secondary',
              )}
            >
              {label} <span className="text-content-tertiary">{counts[id]}</span>
            </button>
          ))}
        </div>
        {add}
      </div>

      {shown.length === 0 ? (
        <p className="py-6 text-center text-sm text-content-tertiary">
          {t('stakeholders.ui.commitment.none_in_filter', { defaultValue: 'No commitment in this group.' })}
        </p>
      ) : (
        <ul className="space-y-2" data-testid="commitment-list">
          {shown.map((c) => {
            // The moves this state has, as the server sees it. One that does not apply is not offered at all;
            // one that applies but is refused stays visible, switched off, with the reason written out below.
            const moves = COMMITMENT_MOVES[c.status].filter((m) => c.can[m].applies);
            const blocked: Array<CommitmentTarget | 'edit'> = moves.filter((m) => !c.can[m].allowed && c.can[m].reason);
            const edit = c.can.edit;
            if (edit.applies && !edit.allowed && edit.reason) blocked.push('edit');
            return (
            <li
              key={c.id}
              ref={c.id === focusId ? focusRef : undefined}
              className={clsx('rounded-lg border border-border-light p-3', c.id === focusId && FOCUS_CLASS)}
              data-testid="commitment-entry"
              data-status={c.status}
              data-focused={c.id === focusId || undefined}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-content-tertiary">{c.code}</span>
                <ToneBadge tone={COMMITMENT_TONE[c.status]} testId="commitment-status">
                  {vocab(t, COMMITMENT_STATUS, c.status)}
                </ToneBadge>
                <span className="text-xs text-content-tertiary">{vocab(t, COMMITMENT_CATEGORY, c.category)}</span>
                {c.overdue && (
                  <span className="flex items-center gap-1 text-xs font-medium text-semantic-error" data-testid="commitment-overdue">
                    <AlertTriangle size={12} aria-hidden />
                    {t('stakeholders.ui.overdue', { defaultValue: 'Overdue' })}
                  </span>
                )}
                <span className="ml-auto flex flex-wrap items-center gap-3 text-xs text-content-secondary">
                  <span>{personName(c.owner_user_id) ?? t('stakeholders.ui.commitment.no_owner', { defaultValue: 'No owner yet' })}</span>
                  <span className={c.overdue ? 'font-medium text-semantic-error' : undefined}>
                    {c.due_date
                      ? t('stakeholders.ui.commitment.due_line', { defaultValue: 'Due {{date}}', date: fmtDate(c.due_date) })
                      : t('stakeholders.ui.commitment.no_due', { defaultValue: 'No due date' })}
                  </span>
                </span>
              </div>
              <p className="mt-1 whitespace-pre-line text-sm text-content-primary">{c.text}</p>
              <p className="mt-1 text-xs text-content-secondary">
                {t('stakeholders.ui.commitment.to_line', {
                  defaultValue: 'Promised to: {{names}}',
                  names: fmtList(namesOf(t, stakeholders, c.stakeholder_ids)),
                })}
              </p>
              {c.source_snapshot.title && (
                <p className="text-xs text-content-tertiary" data-testid="commitment-source-line">
                  {t('stakeholders.ui.commitment.source_line', {
                    defaultValue: 'Promised at: {{title}}',
                    title: datedName(t as TFn, c.source_snapshot.title, c.source_snapshot.date),
                  })}
                </p>
              )}
              {c.cost_estimate && (
                <p className="text-xs text-content-secondary">
                  {t('stakeholders.ui.commitment.cost_line', {
                    defaultValue: 'Estimated cost: {{amount}}',
                    amount: formatCurrency(c.cost_estimate, c.currency),
                  })}
                </p>
              )}
              <CommitmentLinks projectId={projectId} commitment={c} names={linkNames} />
              {c.breach_rationale && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('stakeholders.ui.commitment.breach_line', { defaultValue: 'Not kept because: {{reason}}', reason: c.breach_rationale })}
                </p>
              )}
              {c.withdraw_rationale && (
                <p className="mt-1 text-xs text-content-secondary">
                  {t('stakeholders.ui.commitment.withdraw_line', { defaultValue: 'Withdrawn because: {{reason}}', reason: c.withdraw_rationale })}
                </p>
              )}

              {c.pending_target ? (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-content-secondary" data-testid="commitment-pending">
                  <Hourglass size={12} aria-hidden />
                  {t('stakeholders.ui.commitment.pending', {
                    defaultValue: 'Waiting for approval to become: {{status}}',
                    status: vocab(t, COMMITMENT_STATUS, c.pending_target),
                  })}
                </p>
              ) : (
                (moves.length > 0 || edit.applies) && (
                  <>
                    <div className="mt-2 flex flex-wrap items-center gap-2" data-testid="commitment-moves">
                      {moves.map((target, i) => (
                        <Button
                          key={target}
                          size="sm"
                          variant={i === 0 ? 'secondary' : 'ghost'}
                          disabled={!c.can[target].allowed}
                          onClick={() => setDialog({ kind: 'move', commitment: c, target })}
                          data-testid={`commitment-move-${target}`}
                        >
                          {vocab(t, COMMITMENT_ACTION, target)}
                        </Button>
                      ))}
                      {edit.applies && (
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Pencil size={13} />}
                          disabled={!edit.allowed}
                          onClick={() => setDialog({ kind: 'edit', commitment: c })}
                          data-testid="commitment-edit"
                        >
                          {t('stakeholders.ui.edit', { defaultValue: 'Edit' })}
                        </Button>
                      )}
                    </div>
                    {blocked.length > 0 && (
                      <ul className="mt-1 space-y-0.5 text-2xs text-content-tertiary" data-testid="commitment-blocked">
                        {blocked.map((target) => (
                          <li key={target} data-move={target} data-reason={c.can[target].reason ?? undefined}>
                            {t('stakeholders.ui.commitment.blocked_line', {
                              defaultValue: '{{action}}: {{reason}}',
                              action: target === 'edit' ? t('stakeholders.ui.edit', { defaultValue: 'Edit' }) : vocab(t, COMMITMENT_ACTION, target),
                              reason: vocab(t, COMMITMENT_BLOCK, c.can[target].reason),
                            })}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )
              )}
            </li>
            );
          })}
        </ul>
      )}
      {dialogs}
    </div>
  );
}
