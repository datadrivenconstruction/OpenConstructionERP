// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The decisions on one commitment item that are not a release request:
// approving or rejecting the request that is waiting, asking to stop the item,
// and handing it over to another item. Each button reads the server's flag
// for it, and a refused click shows the server's own sentence.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Ban, Check, Clock, X } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { fmtDate } from '@/shared/lib/formatters';

import { UNAVAILABLE, itemVerdict } from './access';
import {
  commitmentErrorCode,
  commitmentKeys,
  decideRelease,
  listTransferTargets,
  previewAbort,
  requestAbort,
  transferItem,
  type AbortRecord,
  type CommitmentItem,
  type CommitmentMatrix,
  type Release,
} from './api';
import { Amount, FIELD_CLASS, Field, ReasonedButton, RefusalBox, reasonText, refusalText } from './CommitmentBits';
import { approverNames } from './ReleaseDialog';
import { ABORT_FOLLOW_UP, LINK_KIND, PRECONDITION_KIND, codeName, vocab, type LabelContext } from './labels';

type PersonName = (userId: string | null | undefined) => string | null;

export interface PendingRequestProps {
  projectId: string;
  item: CommitmentItem;
  /** The request that is waiting, once the history has loaded. */
  pending: Release | null;
  /** Where the history stands. Nobody decides a request they cannot see yet. */
  history: 'loading' | 'failed' | 'ready';
  matrix: CommitmentMatrix;
  labels: LabelContext;
  personName: PersonName;
  onChanged: () => void;
}

/**
 * The request that waits for a decision, with what the decider was shown when
 * it was made, and the two answers. Whoever may not decide sees why.
 */
export function PendingRequest({
  projectId,
  item,
  pending,
  history,
  matrix,
  labels,
  personName,
  onChanged,
}: PendingRequestProps) {
  const { t } = useTranslation();
  const [answer, setAnswer] = useState<'approved' | 'rejected' | null>(null);
  const [comment, setComment] = useState('');
  const [conditions, setConditions] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const decideV = itemVerdict(item, 'decide');
  const isAbort = item.pending_purpose === 'abort';

  const decide = useMutation({
    mutationFn: () =>
      decideRelease(projectId, item.id, {
        decision: answer as 'approved' | 'rejected',
        comment: comment.trim(),
        conditions: answer === 'approved' ? conditions.trim() : '',
        valid_until: answer === 'approved' && validUntil ? validUntil : null,
      }),
    onSuccess: () => {
      setAnswer(null);
      setComment('');
      setConditions('');
      setValidUntil('');
      onChanged();
    },
  });
  const start = (next: 'approved' | 'rejected') => {
    decide.reset();
    setAnswer(next);
  };

  const unknownPerson = t('commitment.unknown_person', { defaultValue: 'Project member' });
  const openPreconditions = (pending?.snapshot?.preconditions ?? []).filter((p) => p.state !== 'met');
  const tier = pending
    ? pending.escalate_outside
      ? t('commitment.schedule.escalate_outside', { defaultValue: 'Consent outside the schedule' })
      : codeName(labels, 'tier', pending.required_tier, matrix.tiers.find((x) => x.code === pending.required_tier)?.name)
    : '';
  // A rejection without a written reason is refused by the server (`rationale_required`).
  const reasonMissing = answer === 'rejected' && !comment.trim();

  return (
    <section className="space-y-3 rounded-lg border border-border-light bg-surface-secondary p-4" data-testid="item-pending">
      <div role="status" className="flex items-start gap-2 text-sm">
        <Clock size={16} className="mt-0.5 shrink-0 text-content-secondary" aria-hidden />
        <span className="font-medium text-content-primary">
          {isAbort
            ? t('commitment.decide.pending_abort', { defaultValue: 'A request to stop this item is waiting for a decision.' })
            : t('commitment.decide.pending_release', { defaultValue: 'A release request is waiting for a decision.' })}
        </span>
      </div>

      {history === 'loading' && (
        <p className="text-sm text-content-tertiary" data-testid="pending-loading">
          {t('commitment.decide.loading', { defaultValue: 'Loading what was asked' })}
        </p>
      )}
      {history === 'failed' && (
        <p className="text-sm text-content-secondary" data-testid="pending-failed">
          {t('commitment.decide.failed', {
            defaultValue: 'What was asked could not be loaded. Try again in the release history below, then decide.',
          })}
        </p>
      )}

      {pending && (
        <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2" data-testid="pending-summary">
          <div className="flex items-baseline justify-between gap-3">
            <dt className="text-content-secondary">
              {isAbort
                ? t('commitment.exposure.residual_loss', { defaultValue: 'Residual loss' })
                : t('commitment.release.amount', { defaultValue: 'Amount' })}
            </dt>
            <dd className="font-medium tabular-nums text-content-primary">
              <Amount value={pending.requested_amount} currency={pending.currency} />
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-3">
            <dt className="text-content-secondary">{t('commitment.grid.required_tier', { defaultValue: 'Required tier' })}</dt>
            <dd className="font-medium text-content-primary" data-testid="pending-tier">
              {tier}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-3">
            <dt className="text-content-secondary">{t('commitment.history.requested', { defaultValue: 'Requested' })}</dt>
            <dd className="text-content-primary">
              {t('commitment.history.decided', {
                defaultValue: '{{date}} by {{name}}',
                date: fmtDate(pending.created_at),
                name: personName(pending.requested_by) ?? unknownPerson,
              })}
            </dd>
          </div>
          {pending.tranche_note && (
            <div className="sm:col-span-2">
              <dt className="text-content-secondary">
                {isAbort
                  ? t('commitment.end.reason', { defaultValue: 'Reason' })
                  : t('commitment.release.tranche_note', { defaultValue: 'Tranche note' })}
              </dt>
              <dd className="text-content-primary">{pending.tranche_note}</dd>
            </div>
          )}
        </dl>
      )}

      {openPreconditions.length > 0 && (
        <div className="rounded-md border border-semantic-warning/40 bg-semantic-warning-bg p-2 text-sm" data-testid="pending-open-preconditions">
          <p className="font-medium text-content-primary">
            {t('commitment.decide.open_preconditions', {
              defaultValue: 'These preconditions were still open when the request was made:',
            })}
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-content-secondary">
            {openPreconditions.map((pre) => (
              <li key={pre.id}>{pre.text || vocab(t, PRECONDITION_KIND, pre.kind)}</li>
            ))}
          </ul>
        </div>
      )}

      {pending?.snapshot?.four_eyes && (
        <p className="text-xs text-content-tertiary" data-testid="pending-four-eyes">
          {t('commitment.decide.four_eyes_note', {
            defaultValue:
              'Four eyes applies to this tier: whoever made the request, owns the item or confirmed a precondition cannot decide it.',
          })}
        </p>
      )}

      {!answer && history === 'ready' && (
        <div className="flex flex-wrap items-start gap-3">
          <ReasonedButton
            size="sm"
            variant="primary"
            icon={<Check size={14} />}
            verdict={decideV}
            onClick={() => start('approved')}
            data-testid="decide-approve"
          >
            {t('commitment.decide.approve', { defaultValue: 'Approve' })}
          </ReasonedButton>
          {!decideV && (
            <Button size="sm" variant="secondary" icon={<X size={14} />} onClick={() => start('rejected')} data-testid="decide-reject">
              {t('commitment.decide.reject', { defaultValue: 'Reject' })}
            </Button>
          )}
        </div>
      )}

      {answer && (
        <div className="space-y-3 rounded-lg bg-surface-primary p-3" data-testid="decide-form">
          {decide.isError && <RefusalBox message={refusalText(t, decide.error)} />}
          <Field
            id="decide-comment"
            label={
              answer === 'rejected'
                ? t('commitment.decide.reason_reject', { defaultValue: 'Why the request is rejected' })
                : t('commitment.decide.comment', { defaultValue: 'Comment' })
            }
            hint={
              answer === 'rejected'
                ? t('commitment.item.reason_required', { defaultValue: 'Required, kept on the record' })
                : t('commitment.item.reason_optional', { defaultValue: 'Optional, shown in the history' })
            }
            required={answer === 'rejected'}
          >
            <textarea
              id="decide-comment"
              rows={2}
              maxLength={2000}
              className={FIELD_CLASS}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </Field>
          {answer === 'approved' && !isAbort && (
            <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <Field
                id="decide-conditions"
                label={t('commitment.decide.conditions', { defaultValue: 'Conditions' })}
                hint={t('commitment.decide.conditions_hint', {
                  defaultValue: 'Optional. What must hold for this release, in your words.',
                })}
              >
                <textarea
                  id="decide-conditions"
                  rows={2}
                  maxLength={4000}
                  className={FIELD_CLASS}
                  value={conditions}
                  onChange={(e) => setConditions(e.target.value)}
                />
              </Field>
              <Field id="decide-valid-until" label={t('commitment.decide.valid_until', { defaultValue: 'Valid until' })}>
                <input
                  id="decide-valid-until"
                  type="date"
                  className={FIELD_CLASS}
                  value={validUntil}
                  onChange={(e) => setValidUntil(e.target.value)}
                />
              </Field>
            </div>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={answer === 'approved' ? 'primary' : 'danger'}
              loading={decide.isPending}
              disabled={reasonMissing}
              onClick={() => decide.mutate()}
              data-testid="decide-send"
            >
              {answer === 'approved'
                ? isAbort
                  ? t('commitment.decide.approve_abort', { defaultValue: 'Approve the abort' })
                  : t('commitment.decide.approve_release', { defaultValue: 'Approve the release' })
                : t('commitment.decide.reject_send', { defaultValue: 'Reject the request' })}
            </Button>
            <Button size="sm" variant="ghost" disabled={decide.isPending} onClick={() => setAnswer(null)}>
              {t('commitment.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

/** What was decided when the item was stopped, and what is left to do by hand. */
export function AbortOutcome({ abort, item, personName }: { abort: AbortRecord; item: CommitmentItem; personName: PersonName }) {
  const { t } = useTranslation();
  const unknownPerson = t('commitment.unknown_person', { defaultValue: 'Project member' });
  return (
    <section className="space-y-2 rounded-lg border border-semantic-error/30 bg-semantic-error-bg p-4 text-sm" data-testid="abort-outcome">
      <h3 className="flex items-center gap-2 font-semibold text-content-primary">
        <Ban size={16} className="text-semantic-error" aria-hidden />
        {t('commitment.abort.title', { defaultValue: 'This item was stopped' })}
      </h3>
      {abort.decided_at && (
        <p className="text-content-secondary">
          {t('commitment.history.decided', {
            defaultValue: '{{date}} by {{name}}',
            date: fmtDate(abort.decided_at),
            name: personName(abort.decided_by) ?? unknownPerson,
          })}
        </p>
      )}
      {abort.reason && <p className="text-content-primary">{abort.reason}</p>}
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-content-secondary">
          {t('commitment.abort.residual_at_decision', { defaultValue: 'Residual loss when it was decided' })}
        </span>
        <span className="font-semibold tabular-nums text-content-primary" data-testid="abort-residual">
          <Amount value={abort.residual_loss} currency={abort.currency} />
        </span>
      </p>
      {abort.follow_up.length > 0 ? (
        <div data-testid="abort-follow-up">
          <p className="font-medium text-content-primary">
            {t('commitment.abort.follow_up_title', {
              defaultValue: 'Still to do by hand. Stopping the item ends no contract or order by itself:',
            })}
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-content-secondary">
            {abort.follow_up.map((f) => {
              const link = item.links.find((l) => l.document_id === f.document_id);
              return (
                <li key={`${f.kind}-${f.document_id}`} className="space-x-2">
                  <span>{vocab(t, ABORT_FOLLOW_UP, f.action)}</span>
                  <span className="text-content-tertiary">{vocab(t, LINK_KIND, f.kind)}</span>
                  {link && <Amount value={link.document_amount} currency={link.currency} />}
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <p className="text-content-secondary" data-testid="abort-nothing-left">
          {t('commitment.abort.nothing_left', { defaultValue: 'No linked contract or order is still running.' })}
        </p>
      )}
    </section>
  );
}

export interface EndItemProps {
  projectId: string;
  item: CommitmentItem;
  matrix: CommitmentMatrix;
  labels: LabelContext;
  personName: PersonName;
  onChanged: () => void;
}

type Ending = 'abort' | 'transfer' | null;

/**
 * Stopping the item or handing it over. Neither is the usual path, so both
 * sit at the end of the panel as secondary actions that explain themselves.
 *
 * Where an item may go is the server's answer: this project, and the
 * caller's other projects when it lists them. A project it lists but
 * refuses stays visible with the reason.
 */
export function EndItem({ projectId, item, matrix, labels, personName, onChanged }: EndItemProps) {
  const { t } = useTranslation();
  const [ending, setEnding] = useState<Ending>(null);
  const [reason, setReason] = useState('');
  const [targetProject, setTargetProject] = useState('');
  const [target, setTarget] = useState('');
  // Whether the loss is above every tier is what the preview says. A refusal
  // of the request itself can say it too, when the figures moved in between.
  const [outside, setOutside] = useState(false);
  const [externalRef, setExternalRef] = useState('');
  const abortV = itemVerdict(item, 'request_abort');
  const transferV = itemVerdict(item, 'transfer');

  // Asked only once the form is open, and only by somebody the server lets
  // hand over: the list is closed to everybody else.
  const targetsQ = useQuery({
    queryKey: commitmentKeys.transferTargets(projectId, item.id),
    queryFn: () => listTransferTargets(projectId, item.id),
    enabled: ending === 'transfer' && !transferV,
  });
  const projects = targetsQ.data ?? [];
  const chosen =
    projects.find((p) => p.project_id === targetProject) ?? projects.find((p) => p.same_project) ?? projects[0];
  const refused = projects.find((p) => !p.can.allowed);
  const candidates = chosen?.can.allowed ? chosen.items : [];

  // What the abort would be decided on today: the loss, the tier and who
  // holds it. Asked when the form opens, never kept from an earlier look.
  const previewQ = useQuery({
    queryKey: commitmentKeys.abortPreview(projectId, item.id),
    queryFn: () => previewAbort(projectId, item.id),
    enabled: ending === 'abort' && !abortV,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
  const preview = ending === 'abort' && previewQ.isSuccess ? previewQ.data : null;
  const needsRef = ending === 'abort' && (outside || !!preview?.external_approval_required);
  const unknownPerson = t('commitment.unknown_person', { defaultValue: 'Project member' });

  const run = useMutation({
    mutationFn: (): Promise<unknown> =>
      ending === 'abort'
        ? requestAbort(projectId, item.id, reason.trim(), needsRef ? externalRef.trim() : '')
        : transferItem(projectId, item.id, {
            target_item_id: target,
            reason: reason.trim(),
            ...(chosen && !chosen.same_project ? { target_project_id: chosen.project_id } : {}),
          }),
    onSuccess: () => {
      setEnding(null);
      setReason('');
      setTarget('');
      setTargetProject('');
      setOutside(false);
      setExternalRef('');
      onChanged();
    },
    onError: (err) => {
      const code = commitmentErrorCode(err);
      if (code === 'external_approval_required') setOutside(true);
      if (code === 'external_approval_not_required') setOutside(false);
    },
  });
  const start = (next: NonNullable<Ending>) => {
    run.reset();
    setReason('');
    setOutside(false);
    setExternalRef('');
    setEnding(next);
  };
  const ready =
    !!reason.trim() &&
    (ending !== 'transfer' || !!target) &&
    (ending !== 'abort' || !!preview) &&
    (!needsRef || !!externalRef.trim());

  return (
    <section data-testid="end-item">
      <h3 className="mb-1 text-sm font-semibold text-content-primary">
        {t('commitment.end.title', { defaultValue: 'Stop or hand over' })}
      </h3>
      <p className="mb-2 text-sm text-content-secondary">
        {t('commitment.end.intro', {
          defaultValue:
            'Stopping an item is a decision of its own: it goes to the tier that the residual loss calls for. Handing over moves the linked documents to another item and ends this one.',
        })}
      </p>
      {!ending && (
        <div className="flex flex-wrap items-start gap-3">
          <ReasonedButton size="sm" variant="secondary" verdict={abortV} onClick={() => start('abort')} data-testid="item-abort">
            {t('commitment.end.abort', { defaultValue: 'Request abort' })}
          </ReasonedButton>
          <ReasonedButton size="sm" variant="ghost" verdict={transferV} onClick={() => start('transfer')} data-testid="item-transfer">
            {t('commitment.end.transfer', { defaultValue: 'Hand over to another item' })}
          </ReasonedButton>
        </div>
      )}
      {ending && (
        <div className="space-y-3 rounded-lg bg-surface-secondary p-3" data-testid="end-form">
          {run.isError && <RefusalBox message={refusalText(t, run.error)} />}
          {ending === 'abort' && previewQ.isLoading && (
            <p className="text-sm text-content-tertiary" data-testid="abort-preview-loading">
              {t('commitment.end.preview_loading', { defaultValue: 'Working out who decides the abort' })}
            </p>
          )}
          {ending === 'abort' && previewQ.isError && (
            <RefusalBox message={refusalText(t, previewQ.error)}>
              <Button size="sm" variant="ghost" onClick={() => previewQ.refetch()} data-testid="abort-preview-retry">
                {t('common.retry', { defaultValue: 'Retry' })}
              </Button>
            </RefusalBox>
          )}
          {preview && (
            <dl className="space-y-1 text-sm" data-testid="abort-preview">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <dt className="text-content-secondary">
                  {t('commitment.end.residual_loss', { defaultValue: 'Residual loss if stopped today' })}
                </dt>
                <dd className="font-medium tabular-nums text-content-primary" data-testid="abort-preview-loss">
                  <Amount value={preview.residual_loss} currency={preview.schedule_currency} />
                </dd>
              </div>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <dt className="text-content-secondary">
                  {t('commitment.release.required_tier', { defaultValue: 'Required tier' })}
                </dt>
                <dd className="font-medium text-content-primary" data-testid="abort-preview-tier">
                  {preview.escalate_outside
                    ? t('commitment.release.escalate_outside', {
                        defaultValue: 'Above every tier: consent outside the schedule is required',
                      })
                    : codeName(
                        labels,
                        'tier',
                        preview.required_tier,
                        matrix.tiers.find((x) => x.code === preview.required_tier)?.name,
                      )}
                </dd>
              </div>
              {!preview.escalate_outside && (
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <dt className="text-content-secondary">{t('commitment.release.approvers', { defaultValue: 'Decided by' })}</dt>
                  <dd className="font-medium text-content-primary" data-testid="abort-preview-approvers">
                    {preview.approvers.length > 0
                      ? approverNames(preview.approvers, personName, unknownPerson)
                      : t('commitment.release.no_route', {
                          defaultValue:
                            'Nobody is assigned to this tier yet. A manager assigns the approvers on the Approval setup tab.',
                        })}
                  </dd>
                </div>
              )}
            </dl>
          )}
          {ending === 'transfer' && targetsQ.isLoading && (
            <p className="text-sm text-content-tertiary" data-testid="transfer-loading">
              {t('commitment.end.targets_loading', { defaultValue: 'Looking up where this item can go' })}
            </p>
          )}
          {ending === 'transfer' && targetsQ.isError && <RefusalBox message={refusalText(t, targetsQ.error)} />}
          {ending === 'transfer' && targetsQ.isSuccess && (
            <>
              {projects.length > 1 && (
                <Field id="end-project" label={t('commitment.end.project', { defaultValue: 'Project that takes over' })}>
                  <select
                    id="end-project"
                    className={FIELD_CLASS}
                    value={chosen?.project_id ?? ''}
                    onChange={(e) => {
                      setTargetProject(e.target.value);
                      setTarget('');
                    }}
                  >
                    {projects.map((p) => (
                      <option key={p.project_id} value={p.project_id} disabled={!p.can.allowed}>
                        {p.same_project
                          ? t('commitment.end.this_project', { defaultValue: '{{name}} (this project)', name: p.project_name })
                          : p.project_name}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
              {refused && (
                <p className="text-xs text-content-secondary" data-testid="transfer-project-refused" data-reason={refused.can.reason ?? UNAVAILABLE}>
                  {reasonText(t, refused.can.reason ?? UNAVAILABLE)}
                </p>
              )}
              {candidates.length === 0 ? (
                <p className="text-sm text-content-secondary" data-testid="transfer-no-target">
                  {!chosen || chosen.same_project
                    ? t('commitment.end.no_target', {
                        defaultValue: 'There is no other open item in this project. Add the item that takes over first.',
                      })
                    : t('commitment.end.no_target_there', {
                        defaultValue: 'That project has no open item. Add the item that takes over there first.',
                      })}
                </p>
              ) : (
                <Field id="end-target" label={t('commitment.end.target', { defaultValue: 'Item that takes over' })} required>
                  <select id="end-target" className={FIELD_CLASS} value={target} onChange={(e) => setTarget(e.target.value)}>
                    <option value="">{t('commitment.end.target_choose', { defaultValue: 'Choose an item' })}</option>
                    {candidates.map((x) => (
                      <option key={x.id} value={x.id}>
                        {t('commitment.end.target_option', { defaultValue: '{{code}} {{title}}', code: x.code, title: x.title })}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
            </>
          )}
          <Field
            id="end-reason"
            label={
              ending === 'abort'
                ? t('commitment.end.abort_reason', { defaultValue: 'Why the item should be stopped' })
                : t('commitment.end.transfer_reason', { defaultValue: 'Why the item is handed over' })
            }
            hint={t('commitment.item.reason_required', { defaultValue: 'Required, kept on the record' })}
            required
          >
            <textarea
              id="end-reason"
              rows={2}
              maxLength={4000}
              className={FIELD_CLASS}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          {needsRef && (
            <Field
              id="end-external-ref"
              label={t('commitment.release.external_ref', { defaultValue: 'External approval reference' })}
              hint={t('commitment.release.external_ref_hint', {
                defaultValue: 'The file number or date of the approval given by the body above the schedule.',
              })}
              required
            >
              <input
                id="end-external-ref"
                maxLength={255}
                className={FIELD_CLASS}
                value={externalRef}
                onChange={(e) => setExternalRef(e.target.value)}
              />
            </Field>
          )}
          <div className="flex gap-2">
            <Button size="sm" loading={run.isPending} disabled={!ready} onClick={() => run.mutate()} data-testid="end-send">
              {ending === 'abort'
                ? t('commitment.end.abort_send', { defaultValue: 'Send the abort request' })
                : t('commitment.end.transfer_send', { defaultValue: 'Hand over' })}
            </Button>
            <Button size="sm" variant="ghost" disabled={run.isPending} onClick={() => setEnding(null)}>
              {t('commitment.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
