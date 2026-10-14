// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Internal design reviews. A review covers schedule lines of one phase; the
// reviewers write comments, the designer answers each one, the reviewer
// closes it. A review is concluded with an outcome once its comments are
// closed, and an open major comment keeps the phase from being ready.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { MessageSquareText } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  addReviewComment,
  concludeReview,
  createReview,
  designKeys,
  listReviewComments,
  listReviews,
  moveComment,
  moveReview,
  type CommentSeverity,
  type CommentState,
  type Review,
  type ReviewComment,
  type ReviewOutcome,
} from './api';
import {
  COMMENT_TONE,
  ListState,
  PanelHeader,
  REVIEW_TONE,
  SEVERITY_TONE,
  ToneBadge,
  deliverableOptions,
  hasRows,
  phaseField,
  roleOptions,
  roleTitle,
  type DesignContext,
  InlineQueryState,
  StepButton,
  WriteButton,
} from './DesignBits';
import { FormDialog, list, str, type FieldSpec } from './FormDialog';
import { useDesignAction, useDesignList } from './hooks';
import { COMMENT_STATE, REVIEW_OUTCOME, REVIEW_STATE, SEVERITY, phaseName, ui, uiCount, vocab, vocabOptions, type TFn } from './labels';
import { STEP_LABEL, commentMoveNeedsAnswer, offered, releasable } from './rules';

type Dialog =
  | { kind: 'create' }
  | { kind: 'conclude'; review: Review }
  | { kind: 'comment'; review: Review }
  | { kind: 'answer'; comment: ReviewComment }
  | null;

function Comments({ ctx, review, onAnswer }: { ctx: DesignContext; review: Review; onAnswer: (c: ReviewComment) => void }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const action = useDesignAction(ctx.onChanged);
  const comments = useQuery({
    queryKey: designKeys.comments(ctx.projectId, review.id),
    queryFn: () => listReviewComments(ctx.projectId, review.id),
  });
  if (comments.isLoading || comments.isError) return <InlineQueryState query={comments} />;
  const rows = comments.data ?? [];
  if (rows.length === 0) return <p className="text-sm text-content-tertiary">{ui(t, 'design.ui.reviews.no_comments')}</p>;
  const move = (comment: ReviewComment, target: CommentState) =>
    commentMoveNeedsAnswer(target) ? onAnswer(comment) : action.run(() => moveComment(ctx.projectId, comment.id, { target }));
  return (
    <ul className="space-y-2" data-testid="comments-list">
      {rows.map((comment) => {
        const drawing = ctx.drawings.find((d) => d.current_revision_id === comment.revision_id);
        return (
          <li key={comment.id} className="rounded-md bg-surface-secondary p-2" data-testid="comment-row">
            <div className="flex flex-wrap items-center gap-2">
              <ToneBadge tone={SEVERITY_TONE[comment.severity]}>{vocab(t, SEVERITY, comment.severity)}</ToneBadge>
              <ToneBadge tone={COMMENT_TONE[comment.state]}>{vocab(t, COMMENT_STATE, comment.state)}</ToneBadge>
              {drawing && <span className="font-mono text-xs text-content-secondary">{drawing.number}</span>}
              <span className="ml-auto flex flex-wrap gap-1">
                {offered(comment.can?.transitions).map(({ target, flag }) => (
                  <StepButton
                    key={target}
                    flag={flag}
                    label={ui(t, STEP_LABEL.comment[target])}
                    busy={action.pending}
                    onClick={() => move(comment, target)}
                    testId={`comment-to-${target}`}
                  />
                ))}
              </span>
            </div>
            <p className="mt-1 text-sm text-content-primary">{comment.text}</p>
            {comment.answer && (
              <p className="mt-1 text-xs text-content-secondary">
                {ui(t, 'design.ui.reviews.answer_shown', {
                  answer: comment.answer,
                  role: roleTitle(ctx, comment.answered_by_role_id) || ui(t, 'design.ui.reviews.designer'),
                })}
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function ReviewsPanel({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const [dialog, setDialog] = useState<Dialog>(null);
  const [open, setOpen] = useState<string | null>(null);
  const action = useDesignAction(ctx.onChanged);
  const reviews = useDesignList(ctx.projectId, 'reviews', listReviews);
  const phases = ctx.setup.phases;

  const createFields: FieldSpec[] = [
    { name: 'title', label: ui(t, 'design.ui.reviews.review_title'), type: 'text', required: true },
    phaseField(ctx, t, true),
    { name: 'deliverable_ids', label: ui(t, 'design.ui.reviews.lines'), type: 'multi', options: deliverableOptions(ctx) },
    { name: 'reviewer_role_ids', label: ui(t, 'design.ui.reviews.reviewers'), type: 'multi', options: roleOptions(ctx) },
    { name: 'code', label: ui(t, 'design.ui.field.code'), type: 'text', hint: ui(t, 'design.ui.field.code_hint') },
  ];
  const create = () => setDialog({ kind: 'create' });

  return (
    <div className="space-y-4" data-testid="design-reviews-panel">
      <PanelHeader
        title={ui(t, 'design.ui.reviews.title')}
        hint={ui(t, 'design.ui.reviews.hint')}
        action={
          <WriteButton onClick={create} data-testid="review-add">
            {ui(t, 'design.ui.reviews.add')}
          </WriteButton>
        }
      />
      <ListState
        query={reviews}
        failedKey="design.ui.reviews.load_failed"
        emptyIcon={<MessageSquareText size={28} />}
        emptyTitle={ui(t, 'design.ui.reviews.empty_title')}
        emptyBody={ui(t, 'design.ui.reviews.empty_body')}
        emptyAction={{ label: ui(t, 'design.ui.reviews.add'), onClick: create }}
      />
      {hasRows(reviews) && (
        <ul className="space-y-2" data-testid="reviews-list">
          {(reviews.data ?? []).map((review) => {
            const expanded = open === review.id;
            return (
              <li key={review.id} className="rounded-lg border border-border-light p-3" data-testid="review-row">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-content-tertiary">{review.code}</span>
                  <span className="font-medium text-content-primary">{review.title}</span>
                  <ToneBadge tone={REVIEW_TONE[review.state]}>{vocab(t, REVIEW_STATE, review.state)}</ToneBadge>
                  {review.outcome && <span className="text-xs text-content-secondary">{vocab(t, REVIEW_OUTCOME, review.outcome)}</span>}
                  <span className="text-xs text-content-secondary">{phaseName(ctx.labels, phases, review.phase_code)}</span>
                  <span className={review.comments_major_open > 0 ? 'text-xs font-medium text-semantic-error' : 'text-xs text-content-secondary'} data-testid="review-open-count">
                    {review.comments_major_open > 0
                      ? ui(t, 'design.ui.reviews.open_with_major', { open: review.comments_open, major: review.comments_major_open })
                      : uiCount(t, 'design.ui.reviews.open_comments', review.comments_open)}
                  </span>
                  <span className="ml-auto flex flex-wrap gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-expanded={expanded}
                      onClick={() => setOpen(expanded ? null : review.id)}
                      data-testid="review-toggle"
                    >
                      {expanded ? ui(t, 'design.ui.reviews.hide_comments') : ui(t, 'design.ui.reviews.show_comments')}
                    </Button>
                    {review.state === 'open' && (
                      <WriteButton size="sm" variant="secondary" onClick={() => setDialog({ kind: 'comment', review })} data-testid="comment-add">
                        {ui(t, 'design.ui.reviews.comment_add')}
                      </WriteButton>
                    )}
                    {offered(review.can?.transitions, ['concluded']).map(({ target, flag }) => (
                      <StepButton
                        key={target}
                        flag={flag}
                        label={ui(t, STEP_LABEL.review[target])}
                        busy={action.pending}
                        onClick={() => action.run(() => moveReview(ctx.projectId, review.id, target))}
                        testId={`review-to-${target}`}
                      />
                    ))}
                    <StepButton
                      flag={review.can?.conclude}
                      label={ui(t, STEP_LABEL.review.concluded)}
                      variant="secondary"
                      onClick={() => setDialog({ kind: 'conclude', review })}
                      testId="review-conclude"
                    />
                  </span>
                </div>
                {(review.reviewer_role_ids.length > 0 || review.concluded_at) && (
                  <p className="mt-1 text-xs text-content-secondary">
                    {review.reviewer_role_ids.length > 0 &&
                      ui(t, 'design.ui.reviews.reviewed_by', {
                        roles: fmtList(review.reviewer_role_ids.map((id) => roleTitle(ctx, id)).filter(Boolean)),
                      })}{' '}
                    {review.concluded_at && ui(t, 'design.ui.reviews.concluded_on', { date: fmtDate(review.concluded_at) })}
                  </p>
                )}
                {expanded && (
                  <div className="mt-2">
                    <Comments ctx={ctx} review={review} onAnswer={(comment) => setDialog({ kind: 'answer', comment })} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {dialog?.kind === 'create' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.reviews.add')}
          fields={createFields}
          initial={{ title: '', phase_code: '', deliverable_ids: [], reviewer_role_ids: [], code: '' }}
          submitLabel={ui(t, 'design.ui.reviews.add')}
          submit={(values) =>
            createReview(ctx.projectId, {
              ...(str(values, 'code') ? { code: str(values, 'code') } : {}),
              title: str(values, 'title'),
              ...(str(values, 'phase_code') ? { phase_code: str(values, 'phase_code') } : {}),
              deliverable_ids: list(values, 'deliverable_ids'),
              reviewer_role_ids: list(values, 'reviewer_role_ids'),
            })
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="review-form"
        />
      )}
      {dialog?.kind === 'conclude' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.reviews.conclude_title', { code: dialog.review.code })}
          subtitle={ui(t, 'design.ui.reviews.conclude_body')}
          fields={[{ name: 'outcome', label: ui(t, 'design.ui.reviews.outcome'), type: 'select', required: true, options: vocabOptions(t, REVIEW_OUTCOME) }]}
          initial={{ outcome: '' }}
          submitLabel={ui(t, STEP_LABEL.review.concluded)}
          submit={(values) => concludeReview(ctx.projectId, dialog.review.id, str(values, 'outcome') as ReviewOutcome)}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="conclude-form"
        />
      )}
      {dialog?.kind === 'comment' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.reviews.comment_add')}
          fields={[
            { name: 'text', label: ui(t, 'design.ui.reviews.comment_text'), type: 'textarea', required: true },
            { name: 'severity', label: ui(t, 'design.ui.reviews.severity'), type: 'select', required: true, options: vocabOptions(t, SEVERITY), hint: ui(t, 'design.ui.reviews.severity_hint') },
            {
              name: 'revision_id',
              label: ui(t, 'design.ui.reviews.on_drawing'),
              type: 'select',
              options: releasable(ctx.drawings).map((d) => ({ value: d.current_revision_id as string, label: `${d.number} ${d.title}` })),
            },
          ]}
          initial={{ text: '', severity: 'minor', revision_id: '' }}
          submitLabel={ui(t, 'design.ui.reviews.comment_add')}
          submit={(values) =>
            addReviewComment(ctx.projectId, dialog.review.id, {
              text: str(values, 'text'),
              severity: str(values, 'severity') as CommentSeverity,
              ...(str(values, 'revision_id') ? { revision_id: str(values, 'revision_id') } : {}),
            })
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="comment-form"
        />
      )}
      {dialog?.kind === 'answer' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.reviews.answer_title')}
          subtitle={dialog.comment.text}
          fields={[
            { name: 'answer', label: ui(t, 'design.ui.reviews.answer'), type: 'textarea', required: true },
            { name: 'role_id', label: ui(t, 'design.ui.reviews.answer_role'), type: 'select', options: roleOptions(ctx) },
          ]}
          initial={{ answer: '', role_id: '' }}
          submitLabel={ui(t, STEP_LABEL.comment.answered)}
          submit={(values) =>
            moveComment(ctx.projectId, dialog.comment.id, {
              target: 'answered',
              answer: str(values, 'answer'),
              ...(str(values, 'role_id') ? { role_id: str(values, 'role_id') } : {}),
            })
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="answer-form"
        />
      )}
    </div>
  );
}
