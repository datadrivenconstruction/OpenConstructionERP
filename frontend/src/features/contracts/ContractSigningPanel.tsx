// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ContractSigningPanel — the e-signature half of the compliance gate modal.
//
// The gate modal already answers "may this contract be signed". This answers
// "who is signing it, and has anyone signed paper that has since changed".
//
// It lives inside the gate rather than on a tab of its own on purpose. Putting a
// contract up for signature IS the act the gate guards, and the backend runs the
// same compliance check at session initiation, so a user who is told "blocked"
// here has been told before anybody was asked to sign rather than after everyone
// has. Two separate screens would let them find that out in the wrong order.
//
// The signing module owns the vocabulary of capabilities and session statuses,
// so their labels come from the `signing.*` keys rather than from a second list
// in this file that would drift away from the first.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  PenLine,
  Send,
  CheckCircle2,
  Clock,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react';
import clsx from 'clsx';

import { Button, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listContractSigningSessions,
  openContractSigningSession,
  syncContractFromSigning,
  type ContractSigningSession,
} from './api';
import { fmtList } from '@/shared/lib/formatters';

// Last-resort English for the signing module's own vocabularies, reached only
// if a bundle is missing the key. Both families are in all 29 locale files, so
// these strings should never render. They are kept because every t() call in
// this tree carries a defaultValue, and they are worded exactly as en.ts words
// them: a fallback that disagrees with the bundle it stands in for is worse
// than no fallback, because the difference only ever shows up on the one
// install where something is already wrong.
const CAPABILITY_LABELS: Record<string, string> = {
  qualified_electronic: 'Qualified electronic',
  advanced_electronic: 'Advanced electronic',
  simple_electronic: 'Simple electronic',
  digital_certificate: 'Digital certificate',
};

const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  awaiting_signatures: 'Awaiting signatures',
  partially_signed: 'Partially signed',
  fully_signed: 'Fully signed',
  declined: 'Declined',
  expired: 'Expired',
};

/** Sessions that are still collecting signatures. */
const LIVE_STATUSES = new Set([
  'draft',
  'awaiting_signatures',
  'partially_signed',
]);

function statusVariant(status: string): 'success' | 'warning' | 'error' | 'blue' {
  if (status === 'fully_signed') return 'success';
  if (status === 'declined' || status === 'expired') return 'error';
  if (status === 'partially_signed') return 'warning';
  return 'blue';
}

interface ContractSigningPanelProps {
  contractId: string;
  /**
   * The contract's status as the gate reported it, or undefined while the gate
   * is still running. Undefined is not draft: it means we do not know yet, and
   * the action stays disabled until we do. Defaulting it to draft would put a
   * live button in front of the user before the check that decides whether
   * pressing it is allowed at all has answered, which is the ordering this
   * whole panel exists to prevent.
   */
  contractStatus: string | undefined;
  /** True when the compliance gate is currently blocking. */
  blocked: boolean;
  /** Called after the contract's own status changed, so the parent can refresh. */
  onContractChanged: () => void;
}

export function ContractSigningPanel({
  contractId,
  contractStatus,
  blocked,
  onContractChanged,
}: ContractSigningPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const sessionsQ = useQuery<ContractSigningSession[]>({
    queryKey: ['contracts', 'signing-sessions', contractId],
    queryFn: () => listContractSigningSessions(contractId),
    refetchOnWindowFocus: false,
  });

  const sessions = useMemo(() => sessionsQ.data ?? [], [sessionsQ.data]);
  // The list arrives newest first and at most one session is ever live, so the
  // live one is the head when there is one. Falling back to the head keeps a
  // declined-only history visible instead of showing the empty state over it.
  const current = useMemo(
    () => sessions.find((s) => LIVE_STATUSES.has(s.status)) ?? sessions[0],
    [sessions],
  );
  const earlier = useMemo(
    () => sessions.filter((s) => s.id !== current?.id),
    [sessions, current],
  );

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['contracts', 'signing-sessions', contractId] });
  };

  const openMut = useMutation({
    mutationFn: () => openContractSigningSession(contractId),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('contracts.esign.opened_toast', {
          defaultValue: 'Contract is out for signature',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const syncMut = useMutation({
    mutationFn: () => syncContractFromSigning(contractId),
    onSuccess: (contract) => {
      invalidate();
      qc.invalidateQueries({ queryKey: ['contracts', 'list'] });
      if (contract.status === 'draft') {
        addToast({
          type: 'info',
          title: t('contracts.esign.sync_pending', {
            defaultValue:
              'Not everyone has signed yet, so the contract stays in draft.',
          }),
        });
        return;
      }
      addToast({
        type: 'success',
        title: t('contracts.esign.sync_activated', {
          defaultValue: 'Contract activated',
        }),
      });
      onContractChanged();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const gateAnswered = contractStatus !== undefined;
  const isDraft = contractStatus === 'draft';
  const sessionIsLive = current !== undefined && LIVE_STATUSES.has(current.status);
  const signedRoles = new Set(current?.signed_roles ?? []);
  const staleNames = current?.stale_signatories ?? [];
  const signatories = current?.signatory_map ?? [];
  const signedCount = signatories.filter((s) => signedRoles.has(s.role)).length;

  return (
    <section className="rounded-lg border border-border-light">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light px-4 py-2.5">
        <div className="flex items-center gap-2">
          <PenLine size={15} className="text-content-tertiary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('contracts.esign.heading', {
              defaultValue: 'Electronic signature',
            })}
          </h3>
          {current && (
            <Badge variant={statusVariant(current.status)}>
              {t(`signing.status_${current.status}`, {
                defaultValue: STATUS_LABELS[current.status] ?? current.status,
              })}
            </Badge>
          )}
        </div>
        {sessionIsLive && (
          <span className="text-xs text-content-secondary">
            {t('contracts.esign.progress', {
              defaultValue: '{{signed}} of {{total}} signed',
              signed: signedCount,
              total: signatories.length,
            })}
          </span>
        )}
      </header>

      <div className="space-y-3 px-4 py-3">
        {sessionsQ.isLoading && (
          <p className="flex items-center gap-2 text-sm text-content-tertiary">
            <RefreshCw size={14} className="animate-spin" />
            {t('common.loading', { defaultValue: 'Loading…' })}
          </p>
        )}

        {!sessionsQ.isLoading && !current && (
          <div className="space-y-2">
            <p className="text-sm text-content-secondary">
              {t('contracts.esign.empty', {
                defaultValue: 'Nobody has been asked to sign this contract yet.',
              })}
            </p>
            <p className="text-xs text-content-tertiary">
              {t('contracts.esign.empty_hint', {
                defaultValue:
                  'Putting it up for signature collects a signature from every party on the contract register, and records what each of them signed.',
              })}
            </p>
          </div>
        )}

        {current && (
          <>
            {/* The banner that is the reason the session carries a hash at all. */}
            {staleNames.length > 0 && (
              <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 dark:border-amber-800 dark:bg-amber-950/40">
                <AlertTriangle
                  size={18}
                  className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400"
                />
                <div>
                  <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">
                    {t('contracts.esign.stale_title', {
                      defaultValue: 'The contract changed after these signatures',
                    })}
                  </p>
                  <p className="mt-0.5 text-sm text-amber-700 dark:text-amber-400">
                    {t('contracts.esign.stale_body', {
                      defaultValue:
                        '{{names}} signed an earlier version. Ask them to sign again before the contract is activated.',
                      names: fmtList(staleNames),
                    })}
                  </p>
                </div>
              </div>
            )}

            <ul className="divide-y divide-border-light rounded-lg border border-border-light">
              {signatories.map((s) => {
                const hasSigned = signedRoles.has(s.role);
                const isStale = staleNames.includes(s.name);
                return (
                  <li
                    key={`${s.role}-${s.name}`}
                    className="flex items-center justify-between gap-3 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm text-content-primary">{s.name}</p>
                      <p className="text-xs capitalize text-content-tertiary">
                        {s.role.replace(/_/g, ' ')}
                      </p>
                    </div>
                    <span
                      className={clsx(
                        'inline-flex shrink-0 items-center gap-1 text-xs',
                        hasSigned
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-content-tertiary',
                      )}
                    >
                      {hasSigned && (
                        <>
                          <CheckCircle2 size={14} />
                          {t('contracts.esign.signed_label', { defaultValue: 'Signed' })}
                        </>
                      )}
                      {/* Only a live session is waiting on anybody. On a declined or
                          expired one the party did not sign, and saying "awaiting"
                          would name a pending action that nobody can take. */}
                      {!hasSigned && sessionIsLive && (
                        <>
                          <Clock size={14} />
                          {t('contracts.esign.awaiting', {
                            defaultValue: 'Awaiting signature',
                          })}
                        </>
                      )}
                      {isStale && (
                        <Badge variant="warning" size="sm">
                          {t('signing.stale_badge', { defaultValue: 'Stale' })}
                        </Badge>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>

            <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
              <div className="flex items-center gap-1.5">
                <dt className="text-content-tertiary">
                  {t('signing.field_capability', {
                    defaultValue: 'Required capability',
                  })}
                </dt>
                <dd className="text-content-secondary">
                  {t(`signing.capability_${current.provider_capability}`, {
                    defaultValue:
                      CAPABILITY_LABELS[current.provider_capability] ??
                      current.provider_capability,
                  })}
                </dd>
              </div>
              {/* Shown beside the requirement, always, and never falling back
                  to it. The platform resolves a session to whatever provider
                  is registered for the required capability, and core ships one
                  that performs no cryptography - so the two can differ, and a
                  reader who only ever sees the requirement would take it for
                  what was done. A null value means no derivation recorded one;
                  it renders as that rather than borrowing the line above. */}
              <div className="flex items-center gap-1.5">
                <dt className="text-content-tertiary">
                  {t('signing.field_delivered_capability', {
                    defaultValue: 'Delivered capability',
                  })}
                </dt>
                <dd className="text-content-secondary">
                  {current.delivered_capability
                    ? t(`signing.capability_${current.delivered_capability}`, {
                        defaultValue:
                          CAPABILITY_LABELS[current.delivered_capability] ??
                          current.delivered_capability,
                      })
                    : t('signing.capability_not_recorded', {
                        defaultValue: 'Not recorded',
                      })}
                </dd>
              </div>
              <div className="flex items-center gap-1.5">
                <dt className="text-content-tertiary">
                  {t('signing.label_content_hash', { defaultValue: 'Content hash' })}
                </dt>
                <dd className="font-mono text-content-secondary">
                  {current.document_content_hash.slice(0, 12)}…
                </dd>
              </div>
            </dl>
          </>
        )}

        {earlier.length > 0 && (
          <p className="text-xs text-content-tertiary">
            {/* Deliberately `n` and not `count`: `count` would put i18next into
                plural resolution and every locale would owe a form per CLDR
                category for a number that only ever labels a footnote. */}
            {t('contracts.esign.earlier', {
              defaultValue: 'Earlier attempts: {{n}}',
              n: earlier.length,
            })}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          {!sessionIsLive && (
            <Button
              variant="secondary"
              icon={<Send size={14} />}
              onClick={() => openMut.mutate()}
              loading={openMut.isPending}
              disabled={!gateAnswered || !isDraft || blocked}
              title={
                gateAnswered && !isDraft
                  ? t('contracts.esign.only_draft', {
                      defaultValue:
                        'Only a draft contract can be put up for signature.',
                    })
                  : undefined
              }
            >
              {t('contracts.esign.open', { defaultValue: 'Put up for signature' })}
            </Button>
          )}
          {sessionIsLive && (
            <Button
              variant="secondary"
              icon={<CheckCircle2 size={14} />}
              onClick={() => syncMut.mutate()}
              loading={syncMut.isPending}
            >
              {t('contracts.esign.sync', { defaultValue: 'Apply signing outcome' })}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
