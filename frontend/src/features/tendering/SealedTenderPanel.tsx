// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sealed submission mode for one tender package.
 *
 * Informal mode shows prices as they arrive. In sealed mode the server keeps
 * every price hidden until an authorised opening after the deadline; each
 * submission gets a receipt hash so a bidder and the buyer can later check
 * that nothing changed. Deadlines are shown in the viewer's local time and sent
 * with an explicit offset.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Lock, LockOpen, ShieldCheck, ShieldAlert } from 'lucide-react';

import { Badge, Button, Card, type BadgeVariant } from '@/shared/ui';
import { apiPatch } from '@/shared/lib/api';
import { copyToClipboard } from '@/shared/lib/browser';
import { useToastStore } from '@/stores/useToastStore';

import {
  getBidIntegrity,
  getSealedStatus,
  openSealedBids,
  sealedErrorCode,
  setSubmissionMode,
  type BidIntegrity,
  type SealedInfo,
  type SealedState,
  type SubmissionMode,
} from './api';

/** Local date and time of an ISO instant, in the viewer's time zone. */
export function localDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** ISO instant -> value of a datetime-local input (local wall clock). */
function toInputValue(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

const STATE_VARIANT: Record<SealedState, BadgeVariant> = {
  sealed: 'warning',
  awaiting_second: 'blue',
  opened: 'success',
};

export function SealedStateBadge({ state }: { state: SealedState }) {
  const { t } = useTranslation();
  const label =
    state === 'opened'
      ? t('tendering.sealed.badge_opened', { defaultValue: 'Opened' })
      : state === 'awaiting_second'
        ? t('tendering.sealed.badge_awaiting_second', { defaultValue: 'Awaiting second opener' })
        : t('tendering.sealed.badge_sealed', { defaultValue: 'Sealed' });
  return (
    <Badge variant={STATE_VARIANT[state]} size="sm" data-testid="sealed-state-badge">
      {state === 'opened' ? <LockOpen size={11} className="mr-1 inline" /> : <Lock size={11} className="mr-1 inline" />}
      {label}
    </Badge>
  );
}

/** Translated message for a backend error of the sealed endpoints. */
export function useSealedErrorMessage() {
  const { t } = useTranslation();
  return (err: unknown): string => {
    const code = sealedErrorCode(err);
    const status = (err as { status?: number } | null)?.status;
    switch (code) {
      case 'sealed_bids_exist':
        return t('tendering.sealed.err_sealed_bids_exist', { defaultValue: 'Bids already exist, so the mode cannot be changed.' });
      case 'sealed_deadline_required':
        return t('tendering.sealed.err_sealed_deadline_required', { defaultValue: 'Sealed mode needs a deadline.' });
      case 'sealed_deadline_needs_time_and_zone':
        return t('tendering.sealed.err_sealed_deadline_needs_time_and_zone', { defaultValue: 'The deadline needs a date and a time.' });
      case 'sealed_deadline_in_past':
        return t('tendering.sealed.err_sealed_deadline_in_past', { defaultValue: 'The deadline is in the past.' });
      case 'package_decided':
        return t('tendering.sealed.err_package_decided', { defaultValue: 'This package is already decided.' });
      case 'sealed_already_opened':
        return t('tendering.sealed.err_sealed_already_opened', { defaultValue: 'The bids are already opened.' });
      case 'not_sealed':
        return t('tendering.sealed.err_not_sealed', { defaultValue: 'This package is not in sealed mode.' });
      case 'sealed_deadline_not_passed':
        return t('tendering.sealed.err_sealed_deadline_not_passed', { defaultValue: 'The deadline has not passed yet.' });
      case 'sealed_second_opener_must_differ':
        return t('tendering.sealed.err_sealed_second_opener_must_differ', { defaultValue: 'The second opener must be a different user.' });
      default:
        if (status === 403) {
          return t('tendering.sealed.err_forbidden', { defaultValue: 'You do not have permission to open sealed bids.' });
        }
        return t('tendering.sealed.err_generic', { defaultValue: 'The request failed. Please try again.' });
    }
  };
}

/** True when an error is the "bids are sealed until opening" refusal. */
export function isSealedNotOpened(err: unknown): boolean {
  return sealedErrorCode(err) === 'sealed_not_opened';
}

export function SealedEmptyState() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center" data-testid="sealed-empty-state">
      <Lock size={28} strokeWidth={1.5} className="text-content-tertiary" aria-hidden />
      <p className="text-sm font-medium text-content-primary">
        {t('tendering.sealed.empty_title', { defaultValue: 'Bids are sealed until opening' })}
      </p>
      <p className="max-w-md text-xs text-content-secondary">
        {t('tendering.sealed.empty_desc', {
          defaultValue: 'Prices, comparison and award tools become available after an authorised opening.',
        })}
      </p>
    </div>
  );
}

/** Lock marker for a bid row whose content is still hidden. */
export function SealedBidMark() {
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center gap-1 text-sm font-medium text-content-secondary" data-testid="sealed-bid-mark">
      <Lock size={13} aria-hidden />
      {t('tendering.sealed.sealed_label', { defaultValue: 'Sealed' })}
    </span>
  );
}

/** Integrity check of one bid against its receipt hash. */
export function BidIntegrityButton({ bidId }: { bidId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const errorMessage = useSealedErrorMessage();
  const [result, setResult] = useState<BidIntegrity | null>(null);
  const mutation = useMutation({
    mutationFn: () => getBidIntegrity(bidId),
    onSuccess: setResult,
    onError: (err) => addToast({ type: 'error', title: errorMessage(err) }),
  });
  return (
    <span className="inline-flex items-center gap-2">
      <Button
        variant="ghost"
        size="sm"
        icon={<ShieldCheck size={14} />}
        loading={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {t('tendering.sealed.check_integrity', { defaultValue: 'Check integrity' })}
      </Button>
      {result && (
        <span
          className={`inline-flex items-center gap-1 text-xs ${result.intact ? 'text-semantic-success' : 'text-semantic-error'}`}
          role="status"
          data-testid="bid-integrity-result"
        >
          {result.intact ? <ShieldCheck size={13} aria-hidden /> : <ShieldAlert size={13} aria-hidden />}
          {result.intact
            ? t('tendering.sealed.integrity_intact', { defaultValue: 'Unchanged since receipt' })
            : t('tendering.sealed.integrity_changed', { defaultValue: 'Changed after receipt' })}
        </span>
      )}
    </span>
  );
}

function HashCell({ hash }: { hash: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  return (
    <span className="inline-flex items-center gap-1 font-mono text-xs">
      <span title={hash}>{hash.slice(0, 12)}</span>
      <button
        type="button"
        className="rounded p-1 text-content-tertiary hover:text-content-primary"
        aria-label={t('tendering.sealed.copy', { defaultValue: 'Copy' })}
        onClick={async () => {
          if (await copyToClipboard(hash)) {
            addToast({ type: 'success', title: t('tendering.sealed.copied', { defaultValue: 'Copied' }) });
          }
        }}
      >
        <Copy size={12} />
      </button>
    </span>
  );
}

interface PanelPackage {
  status: string;
  deadline: string | null;
  submission_mode?: SubmissionMode;
  sealed?: SealedInfo | null;
}

export function sealedPackageQueryKeys(packageId: string) {
  return [['tendering-package', packageId], ['tendering-comparison', packageId], ['tendering-sealed', packageId]] as const;
}

export function SealedTenderPanel({ packageId, pkg }: { packageId: string; pkg: PanelPackage }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const errorMessage = useSealedErrorMessage();

  const mode: SubmissionMode = pkg.submission_mode ?? 'informal';
  const isSealed = mode === 'sealed';
  const serverDeadline = pkg.sealed?.deadline_utc ?? pkg.deadline;

  const [draftMode, setDraftMode] = useState<SubmissionMode>(mode);
  const [dual, setDual] = useState<boolean>(pkg.sealed?.dual_opening ?? false);
  const [deadline, setDeadline] = useState<string>(toInputValue(serverDeadline));
  const [formError, setFormError] = useState('');
  const [showOpen, setShowOpen] = useState(false);

  useEffect(() => {
    setDraftMode(mode);
    setDual(pkg.sealed?.dual_opening ?? false);
    setDeadline(toInputValue(serverDeadline));
  }, [mode, pkg.sealed?.dual_opening, serverDeadline]);

  const refresh = () => {
    for (const key of sealedPackageQueryKeys(packageId)) queryClient.invalidateQueries({ queryKey: key });
  };

  const statusQ = useQuery({
    queryKey: ['tendering-sealed', packageId],
    queryFn: () => getSealedStatus(packageId),
    enabled: isSealed,
    refetchInterval: isSealed ? 30_000 : false,
  });
  const status = statusQ.data;

  const saveMutation = useMutation({
    mutationFn: async () => {
      const iso = deadline ? new Date(deadline).toISOString() : null;
      const currentIso = serverDeadline ? new Date(serverDeadline).toISOString() : null;
      if (draftMode === 'sealed' && iso !== currentIso) {
        await apiPatch(`/v1/tendering/packages/${packageId}`, { deadline: iso });
      }
      return setSubmissionMode(packageId, { mode: draftMode, dual_opening: draftMode === 'sealed' && dual });
    },
    onSuccess: () => {
      setFormError('');
      addToast({ type: 'success', title: t('tendering.sealed.saved', { defaultValue: 'Submission mode saved' }) });
      refresh();
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  const openMutation = useMutation({
    mutationFn: () => openSealedBids(packageId),
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title:
          res.state === 'opened'
            ? t('tendering.sealed.open_done', { defaultValue: 'Bids opened' })
            : t('tendering.sealed.open_first_done', { defaultValue: 'First approval recorded' }),
      });
      setShowOpen(false);
      refresh();
      queryClient.invalidateQueries({ queryKey: ['tendering-packages'] });
    },
    onError: (err) => {
      addToast({ type: 'error', title: errorMessage(err) });
      refresh();
    },
  });

  const decided = pkg.status === 'awarded' || pkg.status === 'closed';
  const dirty =
    draftMode !== mode ||
    (draftMode === 'sealed' && (dual !== (pkg.sealed?.dual_opening ?? false) || deadline !== toInputValue(serverDeadline)));
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const state: SealedState = status?.state ?? pkg.sealed?.state ?? 'sealed';
  const canOpen = isSealed && state !== 'opened';
  const deadlinePassed = status?.deadline_passed === true;

  return (
    <Card data-testid="sealed-tender-panel">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Lock size={15} className="text-oe-blue" aria-hidden />
            {t('tendering.sealed.mode_title', { defaultValue: 'Submission mode' })}
          </h4>
          {isSealed && <SealedStateBadge state={state} />}
        </div>

        <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t('tendering.sealed.mode_title', { defaultValue: 'Submission mode' })}>
          {(['informal', 'sealed'] as const).map((m) => (
            <label
              key={m}
              className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm ${
                draftMode === m ? 'border-oe-blue bg-oe-blue/5' : 'border-border-light'
              }`}
            >
              <input
                type="radio"
                name={`submission-mode-${packageId}`}
                checked={draftMode === m}
                disabled={decided || saveMutation.isPending}
                onChange={() => setDraftMode(m)}
                className="mt-1"
              />
              <span>
                <span className="block font-medium text-content-primary">
                  {m === 'sealed'
                    ? t('tendering.sealed.mode_sealed', { defaultValue: 'Sealed' })
                    : t('tendering.sealed.mode_informal', { defaultValue: 'Informal' })}
                </span>
                <span className="block text-xs text-content-secondary">
                  {m === 'sealed'
                    ? t('tendering.sealed.mode_sealed_hint', {
                        defaultValue: 'Prices stay hidden until an authorised opening after the deadline.',
                      })
                    : t('tendering.sealed.mode_informal_hint', { defaultValue: 'Prices are visible as soon as they arrive.' })}
                </span>
              </span>
            </label>
          ))}
        </div>

        {draftMode === 'sealed' && (
          <div className="flex flex-wrap items-end gap-4">
            <label className="text-xs text-content-secondary">
              <span className="mb-1 block">{t('tendering.sealed.deadline', { defaultValue: 'Deadline' })}</span>
              <input
                type="datetime-local"
                value={deadline}
                disabled={decided || saveMutation.isPending}
                onChange={(e) => setDeadline(e.target.value)}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
                data-testid="sealed-deadline-input"
              />
              <span className="mt-1 block">
                {t('tendering.sealed.deadline_local', { defaultValue: 'Shown in your local time ({{zone}})', zone })}
              </span>
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-content-primary">
              <input
                type="checkbox"
                checked={dual}
                disabled={decided || saveMutation.isPending}
                onChange={(e) => setDual(e.target.checked)}
              />
              {t('tendering.sealed.dual_opening', { defaultValue: 'Two-person opening' })}
            </label>
          </div>
        )}

        {formError && (
          <p className="text-xs text-semantic-error" role="alert">
            {formError}
          </p>
        )}

        {dirty && (
          <Button size="sm" loading={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            {t('tendering.sealed.save', { defaultValue: 'Save' })}
          </Button>
        )}

        {isSealed && (
          <div className="space-y-2 border-t border-border-light pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h5 className="text-sm font-semibold text-content-primary">
                {t('tendering.sealed.panel_title', { defaultValue: 'Sealed submissions' })}
              </h5>
              {canOpen && (
                <Button size="sm" icon={<LockOpen size={14} />} onClick={() => setShowOpen(true)}>
                  {t('tendering.sealed.open_bids', { defaultValue: 'Open bids' })}
                </Button>
              )}
            </div>
            {status && (
              <p className="text-xs text-content-secondary">
                {t('tendering.sealed.server_deadline', { defaultValue: 'Server deadline' })}:{' '}
                {status.deadline_utc ? localDateTime(status.deadline_utc) : t('tendering.sealed.deadline_none', { defaultValue: 'No deadline set' })}
                {' · '}
                {deadlinePassed
                  ? t('tendering.sealed.deadline_passed', { defaultValue: 'The deadline has passed.' })
                  : t('tendering.sealed.deadline_not_passed', { defaultValue: 'The deadline has not passed yet.' })}
                {status.opened_at && (
                  <>
                    {' · '}
                    {t('tendering.sealed.opened_at', { defaultValue: 'Opened {{date}}', date: localDateTime(status.opened_at) })}
                  </>
                )}
              </p>
            )}
            {status && status.submissions.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('tendering.sealed.no_submissions', { defaultValue: 'No submissions received yet.' })}
              </p>
            ) : status ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-content-tertiary">
                      <th className="py-1 pr-3 font-medium">{t('tendering.sealed.col_company', { defaultValue: 'Company' })}</th>
                      <th className="py-1 pr-3 font-medium">{t('tendering.sealed.col_received', { defaultValue: 'Received' })}</th>
                      <th className="py-1 font-medium">{t('tendering.sealed.col_hash', { defaultValue: 'SHA-256' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.submissions.map((s) => (
                      <tr key={s.bid_id} className="border-t border-border-light">
                        <td className="py-1.5 pr-3 text-content-primary">{s.company_name}</td>
                        <td className="py-1.5 pr-3 text-content-secondary">{localDateTime(s.received_at)}</td>
                        <td className="py-1.5">
                          <HashCell hash={s.sha256} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {showOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-md space-y-3 rounded-xl bg-surface-primary p-5 shadow-xl" data-testid="sealed-open-dialog">
            <h3 className="text-base font-semibold text-content-primary">
              {t('tendering.sealed.open_title', { defaultValue: 'Open sealed bids' })}
            </h3>
            <p className="text-sm text-content-secondary">
              {state === 'awaiting_second'
                ? t('tendering.sealed.open_second', {
                    defaultValue: 'First approval recorded {{date}}. A different user must give the second approval.',
                    date: localDateTime(status?.first_approved_at ?? pkg.sealed?.first_approved_at),
                  })
                : status?.dual_opening
                  ? t('tendering.sealed.open_first', {
                      defaultValue: 'You are the first opener. A second, different user must confirm before the prices are shown.',
                    })
                  : t('tendering.sealed.open_single', {
                      defaultValue: 'Opening makes every price visible. This cannot be undone.',
                    })}
            </p>
            {!deadlinePassed && (
              <p className="text-xs text-semantic-warning">
                {t('tendering.sealed.open_wait_deadline', { defaultValue: 'Opening is possible only after the deadline.' })}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={() => setShowOpen(false)}>
                {t('tendering.sealed.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                size="sm"
                disabled={!deadlinePassed}
                loading={openMutation.isPending}
                onClick={() => openMutation.mutate()}
                data-testid="sealed-open-confirm"
              >
                {t('tendering.sealed.open_bids', { defaultValue: 'Open bids' })}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
