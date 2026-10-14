// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Asking for a release. The reader types the amount of this tranche and the
// server answers, before anything is sent, which tier that amount needs and
// who will decide. The tier follows the cumulative amount, so a second
// tranche can need a higher tier than the first; the dialog shows the sum it
// was judged on. The request itself starts the approval of that tier.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  commitmentErrorCode,
  commitmentViolations,
  previewRelease,
  requestRelease,
  type CommitmentItem,
  type CommitmentMatrix,
  type Precondition,
  type ReleasePreview,
} from './api';
import { Amount, FIELD_CLASS, Field, RefusalBox, refusalText } from './CommitmentBits';
import { FX_SOURCE, PRECONDITION_KIND, codeName, humanizeCode, vocab, type LabelContext } from './labels';
import {
  RELEASE_PROBLEM,
  isPositiveAmount,
  normalizeAmount,
  releaseProblems,
  releasedInForce,
  remainingToRelease,
  toReleaseInput,
  type ReleaseDraft,
} from './rules';

export interface ReleaseDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  item: CommitmentItem;
  matrix: CommitmentMatrix;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onRequested: () => void;
}

/** The people or roles of the route, as one readable list. */
export function approverNames(
  approvers: readonly string[],
  personName: (userId: string) => string | null,
  unknownPerson: string,
): string {
  return fmtList(
    approvers.map((a) => (a.startsWith('role:') ? humanizeCode(a.slice(5)) : personName(a) ?? unknownPerson)),
    'prose',
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

export function ReleaseDialog({
  open,
  onClose,
  projectId,
  item,
  matrix,
  labels,
  personName,
  onRequested,
}: ReleaseDialogProps) {
  const { t } = useTranslation();
  const remaining = remainingToRelease(item);
  const [draft, setDraft] = useState<ReleaseDraft>({
    // The whole remaining amount is offered when the item is in the schedule
    // currency; a tranche is a smaller figure the reader types over it.
    amount: remaining && isPositiveAmount(remaining) && item.planned.currency === item.schedule_currency ? remaining : '',
    currency: item.planned.currency || matrix.base_currency,
    trancheNote: '',
    externalRef: '',
  });
  const amount = normalizeAmount(draft.amount);
  const askable = amount !== null && isPositiveAmount(amount);
  const settledAmount = useDebounced(askable ? amount : null, 350);

  const previewQ = useQuery({
    queryKey: ['commitment-release', projectId, 'preview', item.id, settledAmount, draft.currency],
    queryFn: () =>
      previewRelease(projectId, item.id, toReleaseInput({ ...draft, amount: settledAmount as string })),
    enabled: open && !!settledAmount,
    retry: false,
    staleTime: 0,
  });
  const preview: ReleasePreview | null = askable && settledAmount === amount ? previewQ.data ?? null : null;
  const problems = releaseProblems(draft, preview);

  const send = useMutation({
    mutationFn: () => requestRelease(projectId, item.id, toReleaseInput(draft, !!preview?.escalate_outside)),
    onSuccess: () => {
      onRequested();
      onClose();
    },
  });

  const tierLabel = (code: string | null) =>
    codeName(labels, 'tier', code, matrix.tiers.find((x) => x.code === code)?.name);
  const preconditionLine = (pre: Pick<Precondition, 'kind' | 'text'>) =>
    pre.text || vocab(t, PRECONDITION_KIND, pre.kind);
  const openPreconditions = preview?.open_preconditions ?? [];
  const refusedPreconditions = send.isError && commitmentErrorCode(send.error) === 'preconditions_open'
    ? commitmentViolations(send.error)
    : [];
  const unknownPerson = t('commitment.unknown_person', { defaultValue: 'Project member' });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={send.isPending}
      size="lg"
      testId="release-dialog"
      title={t('commitment.release.dialog_title', { defaultValue: 'Request release' })}
      subtitle={t('commitment.release.dialog_subtitle', {
        defaultValue: '{{code}} {{title}}. The amount decides who approves; the request goes to them right away.',
        code: item.code,
        title: item.title,
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          {problems.length > 0 && draft.amount.trim() !== '' && (
            <ul className="mr-auto space-y-0.5 text-xs text-semantic-error" data-testid="release-problems">
              {problems.map((p) => (
                <li key={p} data-problem={p}>
                  {t(RELEASE_PROBLEM[p][0], { defaultValue: RELEASE_PROBLEM[p][1] })}
                </li>
              ))}
            </ul>
          )}
          <Button variant="ghost" onClick={onClose} disabled={send.isPending}>
            {t('commitment.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            loading={send.isPending}
            disabled={problems.length > 0}
            onClick={() => send.mutate()}
            data-testid="release-submit"
          >
            {t('commitment.release.submit', { defaultValue: 'Request release' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        {send.isError && (
          <RefusalBox message={refusalText(t, send.error)}>
            {refusedPreconditions.length > 0 && (
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-content-secondary">
                {refusedPreconditions.map((v, i) => {
                  const pre = item.preconditions.find((x) => x.id === v.ref);
                  return (
                    <li key={`${v.ref ?? ''}-${i}`}>
                      {pre ? preconditionLine(pre) : vocab(t, PRECONDITION_KIND, (v.kind ?? '') as Precondition['kind'])}
                    </li>
                  );
                })}
              </ul>
            )}
          </RefusalBox>
        )}

        <dl className="grid grid-cols-1 gap-3 rounded-lg bg-surface-secondary p-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-content-tertiary">{t('commitment.grid.planned', { defaultValue: 'Planned' })}</dt>
            <dd className="font-medium text-content-primary">
              <Amount value={item.planned.amount} currency={item.planned.currency} />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-content-tertiary">{t('commitment.grid.released', { defaultValue: 'Released' })}</dt>
            <dd className="font-medium text-content-primary">
              <Amount value={releasedInForce(item)} currency={item.schedule_currency} />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-content-tertiary">
              {t('commitment.release.remaining', { defaultValue: 'Still to release' })}
            </dt>
            <dd className="font-medium text-content-primary" data-testid="release-remaining">
              <Amount value={remaining} currency={item.schedule_currency} />
            </dd>
          </div>
        </dl>

        <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Field
            id="release-amount"
            label={t('commitment.release.amount', { defaultValue: 'Amount' })}
            hint={t('commitment.release.amount_hint', {
              defaultValue: 'The amount of this tranche, not the total. Earlier releases are added to it.',
            })}
            required
          >
            <input
              id="release-amount"
              inputMode="decimal"
              autoComplete="off"
              className={FIELD_CLASS}
              value={draft.amount}
              onChange={(e) => setDraft((d) => ({ ...d, amount: e.target.value }))}
            />
          </Field>
          <Field id="release-currency" label={t('commitment.release.currency', { defaultValue: 'Currency' })}>
            <input
              id="release-currency"
              maxLength={3}
              className={FIELD_CLASS}
              value={draft.currency}
              onChange={(e) => setDraft((d) => ({ ...d, currency: e.target.value.toUpperCase() }))}
            />
          </Field>
        </div>

        <section
          aria-live="polite"
          className="rounded-lg border border-border-light p-3 text-sm"
          data-testid="release-preview"
        >
          <h3 className="mb-2 text-sm font-semibold text-content-primary">
            {t('commitment.release.who_decides', { defaultValue: 'Who will decide' })}
          </h3>
          {!askable ? (
            <p className="text-content-tertiary">
              {t('commitment.release.preview_idle', {
                defaultValue: 'Enter an amount to see which tier it needs and who decides.',
              })}
            </p>
          ) : previewQ.isError ? (
            <RefusalBox message={refusalText(t, previewQ.error)}>
              <Button size="sm" variant="ghost" onClick={() => previewQ.refetch()} data-testid="preview-retry">
                {t('common.retry', { defaultValue: 'Retry' })}
              </Button>
            </RefusalBox>
          ) : !preview ? (
            <p className="text-content-tertiary">
              {t('commitment.release.preview_loading', { defaultValue: 'Working out the required tier' })}
            </p>
          ) : (
            <dl className="space-y-2">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <dt className="text-content-secondary">
                  {t('commitment.release.required_tier', { defaultValue: 'Required tier' })}
                </dt>
                <dd className="font-medium text-content-primary" data-testid="release-tier">
                  {preview.escalate_outside
                    ? t('commitment.release.escalate_outside', {
                        defaultValue: 'Above every tier: consent outside the schedule is required',
                      })
                    : tierLabel(preview.required_tier)}
                </dd>
              </div>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <dt className="text-content-secondary">
                  {t('commitment.release.approvers', { defaultValue: 'Decided by' })}
                </dt>
                <dd className="font-medium text-content-primary" data-testid="release-approvers">
                  {preview.approvers.length > 0
                    ? approverNames(preview.approvers, personName, unknownPerson)
                    : t('commitment.release.no_route', {
                        defaultValue: 'Nobody is assigned to this tier yet. A manager assigns the approvers on the Approval setup tab.',
                      })}
                </dd>
              </div>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <dt className="text-content-secondary">
                  {t('commitment.release.evaluated', { defaultValue: 'Judged on the sum of' })}
                </dt>
                <dd className="font-medium text-content-primary">
                  <Amount value={preview.evaluated_amount} currency={preview.schedule_currency} />
                </dd>
              </div>
              {preview.fx.source !== 'same_currency' && (
                <p className="text-xs text-content-tertiary" data-testid="release-fx">
                  {t('commitment.release.fx_used', {
                    defaultValue: 'Rate {{rate}} from {{source}}, {{date}}',
                    rate: preview.fx.rate,
                    source: vocab(t, FX_SOURCE, preview.fx.source),
                    date: preview.fx.as_of ? fmtDate(preview.fx.as_of) : '',
                  })}
                </p>
              )}
              {openPreconditions.length > 0 && (
                <div
                  className="rounded-md border border-semantic-warning/40 bg-semantic-warning-bg p-2"
                  data-testid="release-open-preconditions"
                >
                  <p className="font-medium text-content-primary">
                    {matrix.enforcement === 'block'
                      ? t('commitment.release.preconditions_block', {
                          defaultValue: 'These preconditions are still open. The request is refused until they are met.',
                        })
                      : t('commitment.release.preconditions_warn', {
                          defaultValue: 'These preconditions are still open. The approver will see them.',
                        })}
                  </p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-content-secondary">
                    {openPreconditions.map((pre) => (
                      <li key={pre.id}>{preconditionLine(pre)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </dl>
          )}
        </section>

        {preview?.escalate_outside && (
          <Field
            id="release-external-ref"
            label={t('commitment.release.external_ref', { defaultValue: 'External approval reference' })}
            hint={t('commitment.release.external_ref_hint', {
              defaultValue: 'The file number or date of the approval given by the body above the schedule.',
            })}
            required
          >
            <input
              id="release-external-ref"
              className={FIELD_CLASS}
              value={draft.externalRef}
              onChange={(e) => setDraft((d) => ({ ...d, externalRef: e.target.value }))}
            />
          </Field>
        )}

        <Field
          id="release-note"
          label={t('commitment.release.tranche_note', { defaultValue: 'Tranche note' })}
          hint={t('commitment.release.tranche_note_hint', {
            defaultValue: 'What this tranche covers. The approver reads it with the request.',
          })}
        >
          <textarea
            id="release-note"
            rows={2}
            className={FIELD_CLASS}
            value={draft.trancheNote}
            onChange={(e) => setDraft((d) => ({ ...d, trancheNote: e.target.value }))}
          />
        </Field>
      </div>
    </WideModal>
  );
}
