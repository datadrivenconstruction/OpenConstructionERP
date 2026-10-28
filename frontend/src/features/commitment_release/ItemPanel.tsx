// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One commitment item, opened from the matrix: how much is planned, released
// and committed, what is still open before the next release, every release
// that was asked for, and what an abort would cost today.
//
// The one primary action is "Request release". Everything else (withdraw,
// hold, defer, edit, abort, hand over) is secondary. Every button reads the
// server's flag for it and says why when it is not available.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, ArrowLeft, ArrowRight, Pencil } from 'lucide-react';
import clsx from 'clsx';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtPercent } from '@/shared/lib/formatters';

import { AbortTermsDialog } from './AbortTermsDialog';
import {
  holdItem,
  updateItem,
  withdrawRelease,
  type CommitmentItem,
  type CommitmentMatrix,
  type Exposure,
  type Release,
} from './api';
import { holdVerdict, itemVerdict } from './access';
import {
  Amount,
  FIELD_CLASS,
  ITEM_STATUS_TONE,
  OUTCOME_TONE,
  ReasonedButton,
  RefusalBox,
  ToneBadge,
  refusalText,
} from './CommitmentBits';
import { useAbortBases, useAbortTerms, useReleaseHistory } from './hooks';
import { AbortOutcome, EndItem, PendingRequest } from './ItemDecisions';
import { ItemDialog } from './ItemDialog';
import { LinkList } from './ItemLinks';
import { PreconditionList } from './ItemParts';
import {
  DATE_BASIS,
  EXPOSURE_LINE,
  EXPOSURE_REASON,
  ITEM_STATUS,
  RELEASE_OUTCOME,
  RELEASE_PURPOSE,
  LEAD_TIME_SOURCE,
  TRANSFERABLE,
  catalogueName,
  codeName,
  rationaleText,
  vocab,
  type LabelContext,
} from './labels';
import { ReleaseDialog } from './ReleaseDialog';
import {
  nothingCommitted,
  overRelease,
  releasedInForce,
  releasedLapsed,
  remainingToRelease,
  shownExposureLines,
} from './rules';

export interface ItemPanelProps {
  projectId: string;
  item: CommitmentItem;
  matrix: CommitmentMatrix;
  /** The other items of the project, for a hand-over and to name the item this one went to. */
  otherItems: ReadonlyArray<Pick<CommitmentItem, 'id' | 'code' | 'title' | 'status'>>;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onBack: () => void;
  onOpenItem: (itemId: string) => void;
  onChanged: () => void;
}

type InlineAction = 'withdraw' | 'hold' | 'resume' | 'defer' | null;

function Figure({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
      <dt className="text-xs text-content-tertiary">{label}</dt>
      <dd className="mt-0.5 text-base font-semibold tabular-nums text-content-primary">{children}</dd>
      {hint && <p className="mt-0.5 text-xs text-content-tertiary">{hint}</p>}
    </div>
  );
}

/** What an abort would cost today, or in words why that is not known. */
export function ExposureBlock({ exposure, labels }: { exposure: Exposure; labels: LabelContext }) {
  const { t } = labels;
  const currency = exposure.currency;
  if (nothingCommitted(exposure)) {
    return (
      <p className="text-sm text-content-secondary" data-testid="exposure-nothing">
        {t('commitment.exposure.nothing_committed_item', {
          defaultValue: 'Nothing is committed yet, so an abort today costs nothing on this item.',
        })}
      </p>
    );
  }
  const lines = shownExposureLines(exposure);
  const rows: Array<[string, string | null | undefined]> = [
    [t('commitment.exposure.sunk', { defaultValue: 'Already spent' }), exposure.sunk],
    [t('commitment.exposure.committed_not_spent', { defaultValue: 'Committed, not yet spent' }), exposure.committed_not_spent],
    [t('commitment.exposure.cancellation_charge', { defaultValue: 'Cancellation charge' }), exposure.cancellation_charge],
    [t('commitment.exposure.recoverable', { defaultValue: 'Recoverable (transfer and salvage)' }), exposure.recoverable],
  ];
  return (
    <div className="space-y-2 text-sm" data-testid="exposure-block">
      <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3">
            <dt className="text-content-secondary">{label}</dt>
            <dd className="tabular-nums text-content-primary">
              <Amount value={value} currency={currency} />
            </dd>
          </div>
        ))}
      </dl>
      <div className="flex items-baseline justify-between gap-3 border-t border-border-light pt-2">
        <span className="font-semibold text-content-primary">
          {t('commitment.exposure.residual_loss', { defaultValue: 'Residual loss' })}
        </span>
        <span className="text-base font-semibold tabular-nums text-content-primary" data-testid="exposure-residual">
          <Amount
            value={exposure.residual_loss}
            currency={currency}
            unknownLabel={
              exposure.reason
                ? vocab(t, EXPOSURE_REASON, exposure.reason)
                : t('commitment.exposure.incomplete', { defaultValue: 'Unknown: a contract figure is missing' })
            }
          />
        </span>
      </div>
      {lines.length > 0 && (
        <ul className="space-y-0.5 text-xs text-content-tertiary" data-testid="exposure-lines">
          {lines.map((line, i) => (
            <li key={`${line.code}-${i}`} className="flex flex-wrap gap-x-2">
              <span>{vocab(t, EXPOSURE_LINE, line.code)}</span>
              {line.milestone && <span>{line.milestone}</span>}
              {line.pct && <span>{fmtPercent(Number(line.pct) * 100)}</span>}
              {line.amount && <Amount value={line.amount} currency={currency} />}
            </li>
          ))}
        </ul>
      )}
      {exposure.basis_review_status && exposure.basis_review_status !== 'verified' && (
        <p className="flex items-start gap-2 text-xs text-content-secondary" data-testid="exposure-unconfirmed">
          <Badge variant="warning" size="sm">
            {t('commitment.abort_form.unconfirmed', { defaultValue: 'Unconfirmed' })}
          </Badge>
          {t('commitment.exposure.basis_unconfirmed', {
            defaultValue: 'Statutory basis not yet confirmed by a domain expert',
          })}
        </p>
      )}
    </div>
  );
}

export function ReleaseHistory({
  releases,
  matrix,
  labels,
  personName,
}: {
  releases: Release[];
  matrix: CommitmentMatrix;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
}) {
  const { t } = labels;
  if (releases.length === 0) {
    return (
      <p className="text-sm text-content-tertiary" data-testid="history-empty">
        {t('commitment.history.empty', {
          defaultValue: 'No release was asked for yet. The first request appears here with its tier and its decision.',
        })}
      </p>
    );
  }
  const unknownPerson = t('commitment.unknown_person', { defaultValue: 'Project member' });
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
      <table className="w-full text-sm" data-testid="history-table">
        <thead>
          <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
            <th className="py-1.5 pr-3 font-medium">{t('commitment.history.requested', { defaultValue: 'Requested' })}</th>
            <th className="py-1.5 pr-3 font-medium">{t('commitment.history.purpose', { defaultValue: 'Asked for' })}</th>
            <th className="py-1.5 pr-3 text-right font-medium">{t('commitment.release.amount', { defaultValue: 'Amount' })}</th>
            <th className="py-1.5 pr-3 font-medium">{t('commitment.grid.required_tier', { defaultValue: 'Required tier' })}</th>
            <th className="py-1.5 pr-3 font-medium">{t('commitment.history.outcome', { defaultValue: 'Decision' })}</th>
            <th className="py-1.5 font-medium">{t('commitment.history.note', { defaultValue: 'Note' })}</th>
          </tr>
        </thead>
        <tbody>
          {releases.map((r) => (
            <tr key={r.id} className="border-b border-border-light/60 align-top" data-testid="history-row">
              <td className="py-2 pr-3 text-content-secondary">
                <p>{fmtDate(r.created_at)}</p>
                <p className="text-xs text-content-tertiary">{personName(r.requested_by) ?? unknownPerson}</p>
              </td>
              <td className="py-2 pr-3 text-content-secondary" data-testid="history-purpose">
                {vocab(t, RELEASE_PURPOSE, r.purpose ?? 'release')}
              </td>
              <td className="py-2 pr-3 text-right tabular-nums text-content-primary">
                <Amount value={r.requested_amount} currency={r.currency} />
              </td>
              <td className="py-2 pr-3 text-content-secondary">
                {r.escalate_outside
                  ? t('commitment.schedule.escalate_outside', { defaultValue: 'Consent outside the schedule' })
                  : codeName(labels, 'tier', r.required_tier, matrix.tiers.find((x) => x.code === r.required_tier)?.name)}
              </td>
              <td className="py-2 pr-3">
                <ToneBadge tone={OUTCOME_TONE[r.outcome] ?? 'neutral'}>{vocab(t, RELEASE_OUTCOME, r.outcome)}</ToneBadge>
                {r.decided_at && (
                  <p className="mt-0.5 text-xs text-content-tertiary">
                    {t('commitment.history.decided', {
                      defaultValue: '{{date}} by {{name}}',
                      date: fmtDate(r.decided_at),
                      name: personName(r.decided_by) ?? unknownPerson,
                    })}
                  </p>
                )}
              </td>
              <td className="py-2 text-content-secondary">
                {r.tranche_note && <p>{r.tranche_note}</p>}
                {r.rationale && <p className="text-xs text-content-tertiary">{rationaleText(t, r.rationale)}</p>}
                {/* One line per approver of a multi-step tier. */}
                {r.conditions && (
                  <p className="whitespace-pre-line text-xs text-content-tertiary" data-testid="history-conditions">
                    {r.conditions}
                  </p>
                )}
                {r.valid_until && (
                  <p className="text-xs text-content-tertiary" data-testid="history-valid-until">
                    {t('commitment.history.valid_until', {
                      defaultValue: 'Valid until {{date}}',
                      date: fmtDate(r.valid_until),
                    })}
                  </p>
                )}
                {r.external_approval_ref && (
                  <p className="text-xs text-content-tertiary">
                    {t('commitment.history.external_ref', {
                      defaultValue: 'External approval: {{ref}}',
                      ref: r.external_approval_ref,
                    })}
                  </p>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ItemPanel({
  projectId,
  item,
  matrix,
  otherItems,
  labels,
  personName,
  onBack,
  onOpenItem,
  onChanged,
}: ItemPanelProps) {
  const { t } = useTranslation();
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [termsOpen, setTermsOpen] = useState(false);
  const [action, setAction] = useState<InlineAction>(null);
  const [reason, setReason] = useState('');

  const historyQ = useReleaseHistory(projectId, item.id);
  const termsQ = useAbortTerms(projectId, item.id);
  const basesQ = useAbortBases(termsOpen);
  const itemTerms = (termsQ.data ?? []).find((x) => x.scope === 'item') ?? null;

  const releaseV = itemVerdict(item, 'request_release');
  const editV = itemVerdict(item, 'edit');
  const linkV = itemVerdict(item, 'link');
  const holdV = holdVerdict(item);
  const deferV = itemVerdict(item, 'defer');
  const withdrawV = itemVerdict(item, 'withdraw');
  const pending = (historyQ.data ?? []).find((r) => r.outcome === 'pending') ?? null;
  const ended = item.status === 'aborted' || item.status === 'transferred';
  // A part of the released sum that lapsed with its date stays on the record after a renewal too.
  const lapsed = releasedLapsed(item);
  // The latest validity date that has passed, when the server names one.
  const expiredOn = item.expired_release_dates?.[item.expired_release_dates.length - 1] ?? null;
  // The server names the item that took over. Inside this project it opens
  // here; in another project it is a link, and only when the reader may open
  // that project. Without the names nothing is linked.
  const takenBy = item.transferred_to ?? null;
  const successor = takenBy
    ? takenBy.same_project && takenBy.can_open
      ? { id: takenBy.item_id, code: takenBy.code ?? '', title: takenBy.title ?? '' }
      : null
    : item.transferred_to_item_id
      ? otherItems.find((x) => x.id === item.transferred_to_item_id) ?? null
      : null;
  const elsewhere = takenBy && !takenBy.same_project && takenBy.can_open ? takenBy : null;

  const remaining = remainingToRelease(item);
  const over = overRelease(item);
  const onHold = item.status === 'on_hold';

  const run = useMutation({
    mutationFn: (kind: NonNullable<InlineAction>): Promise<unknown> => {
      const text = reason.trim();
      if (kind === 'withdraw') return withdrawRelease(projectId, item.id, text);
      if (kind === 'defer') return updateItem(projectId, item.id, { deferred: true, deferred_reason: text });
      return holdItem(projectId, item.id, kind === 'hold', text);
    },
    onSuccess: () => {
      setAction(null);
      setReason('');
      onChanged();
    },
  });
  const undefer = useMutation({
    mutationFn: () => updateItem(projectId, item.id, { deferred: false }),
    onSuccess: onChanged,
  });
  const start = (kind: NonNullable<InlineAction>) => {
    run.reset();
    setReason('');
    setAction(kind);
  };
  // Only a deferral must carry a reason (`deferral_needs_reason`); the others may.
  const needsReason = action === 'defer';

  const actionCopy: Record<NonNullable<InlineAction>, { label: string; placeholder: string; send: string }> = {
    withdraw: {
      label: t('commitment.item.withdraw_reason', { defaultValue: 'Why the request is withdrawn' }),
      placeholder: t('commitment.item.reason_optional', { defaultValue: 'Optional, shown in the history' }),
      send: t('commitment.release.withdraw', { defaultValue: 'Withdraw request' }),
    },
    hold: {
      label: t('commitment.item.hold_reason', { defaultValue: 'Why the item is put on hold' }),
      placeholder: t('commitment.item.reason_on_record', { defaultValue: 'Optional, kept on the record' }),
      send: t('commitment.item.hold', { defaultValue: 'Put on hold' }),
    },
    resume: {
      label: t('commitment.item.resume_reason', { defaultValue: 'Why the item is resumed' }),
      placeholder: t('commitment.item.reason_on_record', { defaultValue: 'Optional, kept on the record' }),
      send: t('commitment.item.resume', { defaultValue: 'Resume item' }),
    },
    defer: {
      label: t('commitment.item.defer_reason', { defaultValue: 'Why the decision is deferred' }),
      placeholder: t('commitment.item.reason_required', { defaultValue: 'Required, kept on the record' }),
      send: t('commitment.item.defer', { defaultValue: 'Defer decision' }),
    },
  };

  return (
    <div className="space-y-5" data-testid="item-panel">
      <div className="flex flex-wrap items-start gap-3">
        <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} />} onClick={onBack} data-testid="item-back">
          {t('commitment.item.back', { defaultValue: 'All commitments' })}
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-content-tertiary">{item.code}</span>
            <ToneBadge tone={ITEM_STATUS_TONE[item.status] ?? 'neutral'} testId="item-status">
              {vocab(t, ITEM_STATUS, item.status)}
            </ToneBadge>
            {item.deferred && (
              <Badge variant="warning" size="sm">
                {t('commitment.item.deferred', { defaultValue: 'Decision deferred' })}
              </Badge>
            )}
          </div>
          <h2 className="text-lg font-semibold text-content-primary">{item.title}</h2>
          <p className="flex flex-wrap gap-x-3 text-sm text-content-secondary">
            <span>
              {codeName(labels, 'type', item.commitment_type, matrix.commitment_types.find((x) => x.code === item.commitment_type)?.name)}
            </span>
            {item.owner_user_id && (
              <span>
                {t('commitment.item.owner', {
                  defaultValue: 'Owner: {{name}}',
                  name: personName(item.owner_user_id) ?? t('commitment.unknown_person', { defaultValue: 'Project member' }),
                })}
              </span>
            )}
            {item.flags.map((flag) => (
              <span key={flag}>{codeName(labels, 'flag', flag, matrix.novelty_flags.find((x) => x.code === flag)?.name)}</span>
            ))}
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <ReasonedButton
            variant="secondary"
            size="sm"
            icon={<Pencil size={14} />}
            verdict={editV}
            onClick={() => setEditOpen(true)}
            data-testid="item-edit"
          >
            {t('commitment.item.edit', { defaultValue: 'Edit' })}
          </ReasonedButton>
          <ReasonedButton
            variant="primary"
            verdict={releaseV}
            onClick={() => setReleaseOpen(true)}
            data-testid="item-request-release"
          >
            {t('commitment.release.submit', { defaultValue: 'Request release' })}
          </ReasonedButton>
        </div>
      </div>

      {item.pending_release_id && (
        <PendingRequest
          projectId={projectId}
          item={item}
          pending={pending}
          history={historyQ.isLoading ? 'loading' : historyQ.isError ? 'failed' : 'ready'}
          matrix={matrix}
          labels={labels}
          personName={personName}
          onChanged={onChanged}
        />
      )}
      {item.abort && <AbortOutcome abort={item.abort} item={item} personName={personName} />}
      {item.status === 'transferred' && (
        <div role="status" className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary px-4 py-2 text-sm" data-testid="item-transferred">
          <ArrowRight size={16} className="shrink-0 text-content-secondary" aria-hidden />
          <span className="text-content-primary">
            {successor || !item.transferred_to_item_id
              ? t('commitment.item.transferred_notice', {
                  defaultValue: 'This item was handed over. Its linked documents now count in the item that took over.',
                })
              : elsewhere
                ? t('commitment.item.transferred_to_project', {
                    defaultValue: 'This item was handed over to the project {{project}}.',
                    project: elsewhere.project_name ?? '',
                  })
                : t('commitment.item.transferred_elsewhere', {
                    defaultValue: 'This item was handed over to an item that is not in the matrix of this project.',
                  })}
          </span>
          {elsewhere && (
            <a
              href={`/projects/${elsewhere.project_id}/commitments?item=${elsewhere.item_id}`}
              className="font-medium text-oe-blue hover:underline"
              data-testid="item-successor-elsewhere"
            >
              {t('commitment.end.target_option', {
                defaultValue: '{{code}} {{title}}',
                code: elsewhere.code ?? '',
                title: elsewhere.title ?? '',
              })}
            </a>
          )}
          {successor && (
            <Button size="sm" variant="ghost" onClick={() => onOpenItem(successor.id)} data-testid="item-successor">
              {t('commitment.end.target_option', { defaultValue: '{{code}} {{title}}', code: successor.code, title: successor.title })}
            </Button>
          )}
        </div>
      )}
      {item.decision_overdue && (
        <div role="status" className="flex items-start gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error-bg px-4 py-2 text-sm" data-testid="item-overdue">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />
          <span className="text-content-primary">
            {t('commitment.item.overdue_notice', {
              defaultValue: 'The latest decision date has passed. Request the release, or defer the decision with a reason.',
            })}
          </span>
        </div>
      )}
      {item.over_release && (
        <div role="status" className="flex items-start gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error-bg px-4 py-2 text-sm" data-testid="item-over-release">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />
          <span className="text-content-primary">
            {t('commitment.item.over_release_notice', {
              defaultValue: 'The linked documents bind more than was released. Request a further release for the difference.',
            })}{' '}
            {over && <Amount value={over} currency={item.schedule_currency} />}
          </span>
        </div>
      )}
      {item.plant_item_missing && (
        <div role="status" className="flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg px-4 py-2 text-sm" data-testid="item-plant-missing">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
          <span className="text-content-primary">
            {t('commitment.item.plant_item_missing_notice', {
              defaultValue:
                'This item names a plant item that the plant register no longer knows. Its lead time and latest order date are not used: the dates here come from the figures entered on this item. Link it to a current plant item or remove the link.',
            })}
          </span>
        </div>
      )}
      {item.plant_item_cancelled && !item.plant_item_missing && (
        <div role="status" className="flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg px-4 py-2 text-sm" data-testid="item-plant-cancelled">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
          <span className="text-content-primary">
            {item.plant_item_code
              ? t('commitment.item.plant_item_cancelled_notice', {
                  defaultValue:
                    'The linked plant item {{code}} is cancelled in the plant register. Its dates are still the ones used here.',
                  code: item.plant_item_code,
                })
              : t('commitment.item.plant_item_cancelled_notice_unnamed', {
                  defaultValue:
                    'The linked plant item is cancelled in the plant register. Its dates are still the ones used here.',
                })}
          </span>
        </div>
      )}
      {item.release_expired && (
        <div role="status" className="flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg px-4 py-2 text-sm" data-testid="item-release-expired">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
          <span className="text-content-primary">
            {expiredOn
              ? t('commitment.item.release_expired_notice', {
                  defaultValue:
                    'A release of this item was valid until {{date}}. What is bound under it stays bound, but nothing new can be bound until a new release is requested.',
                  date: fmtDate(expiredOn),
                })
              : t('commitment.item.release_expired_notice_undated', {
                  defaultValue:
                    'A release of this item has passed its validity date. What is bound under it stays bound, but nothing new can be bound until a new release is requested.',
                })}
          </span>
        </div>
      )}
      {item.deferred && item.deferred_reason && (
        <p className="text-sm text-content-secondary" data-testid="item-deferred-reason">
          {t('commitment.item.deferred_because', { defaultValue: 'Deferred because: {{reason}}', reason: item.deferred_reason })}
        </p>
      )}

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Figure
          label={t('commitment.grid.planned', { defaultValue: 'Planned' })}
          hint={
            item.required_tier_for_planned
              ? item.required_tier_for_planned === 'escalate_outside'
                ? t('commitment.schedule.escalate_outside', { defaultValue: 'Consent outside the schedule' })
                : codeName(
                    labels,
                    'tier',
                    item.required_tier_for_planned,
                    matrix.tiers.find((x) => x.code === item.required_tier_for_planned)?.name,
                  )
              : undefined
          }
        >
          <Amount value={item.planned.amount} currency={item.planned.currency} />
        </Figure>
        <Figure
          label={t('commitment.grid.released', { defaultValue: 'Released' })}
          hint={
            lapsed ? (
              <span data-testid="item-released-lapsed">
                {t('commitment.released_lapsed', { defaultValue: 'Lapsed, no longer available' })} <Amount value={lapsed} currency={item.schedule_currency} />
              </span>
            ) : undefined
          }
        >
          <span data-testid="item-released">
            <Amount value={releasedInForce(item)} currency={item.schedule_currency} />
          </span>
        </Figure>
        <Figure
          label={t('commitment.grid.committed', { defaultValue: 'Committed' })}
          hint={
            item.committed == null && item.committed_reason
              ? vocab(t, EXPOSURE_REASON, item.committed_reason)
              : undefined
          }
        >
          <Amount value={item.committed} currency={item.schedule_currency} />
        </Figure>
        <Figure label={t('commitment.release.remaining', { defaultValue: 'Still to release' })}>
          <Amount value={remaining} currency={item.schedule_currency} />
        </Figure>
        <Figure
          label={t('commitment.grid.latest_decision_date', { defaultValue: 'Latest decision date' })}
          hint={vocab(t, DATE_BASIS, item.date_basis)}
        >
          <span className={clsx(item.decision_overdue && 'text-semantic-error')}>
            {item.latest_decision_date
              ? fmtDate(item.latest_decision_date)
              : t('commitment.item.no_date', { defaultValue: 'Not set' })}
          </span>
        </Figure>
        {item.lead_time_in_force_days != null && (
          <Figure
            label={t('commitment.item_form.lead_time', { defaultValue: 'Lead time, days' })}
            hint={
              item.lead_time_source === 'plant_item' && item.plant_item_code
                ? t('commitment.lead_time_source.plant_item_named', {
                    defaultValue: 'From plant item {{code}}',
                    code: item.plant_item_code,
                  })
                : item.lead_time_source
                  ? vocab(t, LEAD_TIME_SOURCE, item.lead_time_source)
                  : undefined
            }
          >
            <span data-testid="item-lead-time">{item.lead_time_in_force_days}</span>
          </Figure>
        )}
      </dl>

      <div className="flex flex-wrap items-start gap-3">
        {item.pending_release_id && (
          <ReasonedButton size="sm" variant="secondary" verdict={withdrawV} onClick={() => start('withdraw')} data-testid="item-withdraw">
            {t('commitment.release.withdraw', { defaultValue: 'Withdraw request' })}
          </ReasonedButton>
        )}
        {item.deferred ? (
          <ReasonedButton size="sm" variant="ghost" verdict={deferV} loading={undefer.isPending} onClick={() => undefer.mutate()}>
            {t('commitment.item.undefer', { defaultValue: 'End deferral' })}
          </ReasonedButton>
        ) : (
          <ReasonedButton size="sm" variant="ghost" verdict={deferV} onClick={() => start('defer')} data-testid="item-defer">
            {t('commitment.item.defer', { defaultValue: 'Defer decision' })}
          </ReasonedButton>
        )}
        <ReasonedButton
          size="sm"
          variant="ghost"
          verdict={holdV}
          onClick={() => start(onHold ? 'resume' : 'hold')}
          data-testid="item-hold"
        >
          {onHold
            ? t('commitment.item.resume', { defaultValue: 'Resume item' })
            : t('commitment.item.hold', { defaultValue: 'Put on hold' })}
        </ReasonedButton>
      </div>
      {undefer.isError && <RefusalBox message={refusalText(t, undefer.error)} />}

      {action && (
        <div className="space-y-2 rounded-lg bg-surface-secondary p-3" data-testid="item-action-form">
          {run.isError && <RefusalBox message={refusalText(t, run.error)} />}
          <label htmlFor="item-action-reason" className="block text-sm font-medium text-content-primary">
            {actionCopy[action].label}
          </label>
          <textarea
            id="item-action-reason"
            rows={2}
            className={FIELD_CLASS}
            placeholder={actionCopy[action].placeholder}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              loading={run.isPending}
              disabled={needsReason && !reason.trim()}
              onClick={() => run.mutate(action)}
              data-testid="item-action-send"
            >
              {actionCopy[action].send}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAction(null)}>
              {t('commitment.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <PreconditionList projectId={projectId} item={item} editVerdict={editV} personName={personName} onChanged={onChanged} />
        <LinkList projectId={projectId} item={item} editVerdict={linkV} onChanged={onChanged} />
      </div>

      <section data-testid="history">
        <h3 className="mb-2 text-sm font-semibold text-content-primary">
          {t('commitment.drawer.history', { defaultValue: 'Release history' })}
        </h3>
        {historyQ.isLoading ? (
          <p className="text-sm text-content-tertiary">{t('commitment.loading', { defaultValue: 'Loading' })}</p>
        ) : historyQ.isError ? (
          <ErrorState
            title={t('commitment.history.load_failed', { defaultValue: 'The release history could not be loaded' })}
            hint={getErrorMessage(historyQ.error)}
            onRetry={() => historyQ.refetch()}
          />
        ) : (
          <ReleaseHistory releases={historyQ.data ?? []} matrix={matrix} labels={labels} personName={personName} />
        )}
      </section>

      <section data-testid="exposure">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('commitment.drawer.exposure', { defaultValue: 'Abort exposure' })}
          </h3>
          {/* Offered only once the stored terms are known: a form opened blank would overwrite them. */}
          {termsQ.isSuccess && (
            <ReasonedButton
              size="sm"
              variant="secondary"
              verdict={editV}
              loading={termsOpen && basesQ.isLoading}
              onClick={() => setTermsOpen(true)}
              data-testid="item-abort-terms"
            >
              {itemTerms
                ? t('commitment.item.edit_abort_terms', { defaultValue: 'Edit abort terms' })
                : t('commitment.item.add_abort_terms', { defaultValue: 'Enter abort terms' })}
            </ReasonedButton>
          )}
        </div>
        {termsQ.isLoading && (
          <p className="mb-2 text-sm text-content-tertiary" data-testid="abort-terms-loading">
            {t('commitment.item.abort_terms_loading', { defaultValue: 'Loading the abort terms' })}
          </p>
        )}
        {termsQ.isError && (
          <ErrorState
            compact
            title={t('commitment.item.abort_terms_failed', { defaultValue: 'The abort terms could not be loaded' })}
            hint={getErrorMessage(termsQ.error)}
            onRetry={() => termsQ.refetch()}
          />
        )}
        {termsOpen && basesQ.isError && (
          <ErrorState
            compact
            title={t('commitment.item.abort_bases_failed', {
              defaultValue: 'The list of abort bases could not be loaded, so the terms cannot be edited yet',
            })}
            hint={getErrorMessage(basesQ.error)}
            onRetry={() => basesQ.refetch()}
          />
        )}
        {item.exposure ? (
          <ExposureBlock exposure={item.exposure} labels={labels} />
        ) : (
          <p className="text-sm text-content-tertiary">{t('commitment.loading', { defaultValue: 'Loading' })}</p>
        )}
        {itemTerms && (
          <p className="mt-2 flex flex-wrap gap-x-3 text-xs text-content-tertiary" data-testid="abort-terms-summary">
            {itemTerms.basis_code && <span>{catalogueName(labels, itemTerms.basis_code)}</span>}
            <span>{vocab(t, TRANSFERABLE, itemTerms.transferable)}</span>
            {itemTerms.source_note && <span>{itemTerms.source_note}</span>}
          </p>
        )}
      </section>

      {!ended && (
        <EndItem projectId={projectId} item={item} matrix={matrix} labels={labels} personName={personName} onChanged={onChanged} />
      )}

      {releaseOpen && (
        <ReleaseDialog
          open
          onClose={() => setReleaseOpen(false)}
          projectId={projectId}
          item={item}
          matrix={matrix}
          labels={labels}
          personName={personName}
          onRequested={onChanged}
        />
      )}
      {editOpen && (
        <ItemDialog
          open
          onClose={() => setEditOpen(false)}
          projectId={projectId}
          matrix={matrix}
          item={item}
          ownerVerdict={itemVerdict(item, 'edit_gate_fields')}
          labels={labels}
          personName={personName}
          onSaved={onChanged}
        />
      )}
      {termsOpen && termsQ.isSuccess && basesQ.isSuccess && (
        <AbortTermsDialog
          open
          onClose={() => setTermsOpen(false)}
          projectId={projectId}
          item={item}
          terms={itemTerms}
          bases={basesQ.data ?? []}
          labels={labels}
          onSaved={onChanged}
        />
      )}
    </div>
  );
}
