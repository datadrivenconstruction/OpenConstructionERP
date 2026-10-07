// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// RetentionReleasePanel — the retention held on a contract, and the way it
// goes back.
//
// Retention was a number on a tile. The contract said "release on practical
// completion", the ledger said how much was held, and there was no way to act
// on either: the one endpoint that released anything appended a line to the
// contract metadata, counted the money as paid the moment it was written, and
// never reached a payment application. Line 5 of the G702 stayed where it was
// for ever.
//
// A release now walks the way the money does. Preview says what the event
// pays before anyone commits to it, sized by the project's national pack
// (in the US, all of what is held less 1.5 times the open punch items).
// Proposing writes a row that pays nothing. Approving it needs the documents
// the event asks for, which is why the required roles are listed with the
// registered documents next to them. Billing it on a draft claim is what
// finally takes line 5 down and adds the release to what that claim pays.
//
// Every figure shown here comes from the server, including the withholding:
// the panel never sizes a release itself, because the amount a person
// confirms has to be the amount the ledger will write.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TFunction } from 'i18next';
import { Banknote, Check, FileCheck2, Plus, Undo2 } from 'lucide-react';

import { Badge, Button } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  approveRetentionRelease,
  billRetentionRelease,
  createContractDocument,
  createRetentionRelease,
  getRetentionSummary,
  listContractDocuments,
  listProgressClaims,
  previewRetentionRelease,
  voidRetentionRelease,
  type ContractDocument,
  type ProgressClaimItem,
  type RetentionRelease,
  type RetentionReleasePreview,
  type RetentionReleaseRowEvent,
  type RetentionSummary,
} from './api';
import type { Page } from '@/shared/lib/api';

/* ── Vocabulary ───────────────────────────────────────────────────────── */

// The events a person can start a release from. rate_step_down is not here:
// the server proposes that one itself when a recompute-mode policy lowers the
// rate, and it carries the claim it was worked out on.
const RELEASE_EVENTS: RetentionReleaseRowEvent[] = [
  'substantial_completion',
  'final_completion',
  'defects_period_end',
];

// Last-resort English, worded as en.ts words it. Every value is a key, so
// these should not render; they exist because each t() carries a defaultValue.
const EVENT_LABELS: Record<string, string> = {
  substantial_completion: 'Substantial completion',
  final_completion: 'Final completion',
  defects_period_end: 'End of the defects period',
  rate_step_down: 'Retention rate reduction',
  security_substituted: 'Security substituted',
};

const STATUS_LABELS: Record<string, string> = {
  proposed: 'Proposed',
  approved: 'Approved',
  billed: 'Billed',
  void: 'Void',
};

const DOCUMENT_LABELS: Record<string, string> = {
  certificate_substantial_completion: 'Certificate of substantial completion',
  acceptance_protocol: 'Acceptance protocol',
  affidavit_payment_of_debts: 'Affidavit of payment of debts and claims',
  affidavit_release_of_liens: 'Affidavit of release of liens',
  consent_of_surety: 'Consent of surety',
  final_lien_waiver: 'Final lien waiver',
  final_invoice: 'Final invoice',
};

const RULE_SOURCE_LABELS: Record<string, string> = {
  retention_schedule: "This contract's retention schedule",
  regional_pack: "The project's national pack",
  request: 'The schedule sent with the request',
  default: 'The built-in default, not a national rule',
};

/** The label for a release event, shared with the contract drawer. */
export function retentionEventLabel(t: TFunction, value: string): string {
  return t(`contracts.retention_event.${value}`, {
    defaultValue: EVENT_LABELS[value] ?? value.replace(/_/g, ' '),
  });
}

function statusLabel(t: TFunction, value: string): string {
  return t(`contracts.retention_release_status.${value}`, {
    defaultValue: STATUS_LABELS[value] ?? value,
  });
}

function documentLabel(t: TFunction, value: string): string {
  return t(`contracts.retention_document.${value}`, {
    defaultValue: DOCUMENT_LABELS[value] ?? value.replace(/_/g, ' '),
  });
}

function statusTone(
  status: string,
): 'neutral' | 'blue' | 'success' | 'warning' {
  if (status === 'billed') return 'success';
  if (status === 'approved') return 'blue';
  if (status === 'proposed') return 'warning';
  return 'neutral';
}

function toNum(value: string | number | null | undefined): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

/* ── Panel ────────────────────────────────────────────────────────────── */

interface RetentionReleasePanelProps {
  contractId: string;
  /** The contract's currency; every figure in the ledger is held in it. */
  currency: string;
  /** Releasing is offered on a live contract, not on a draft or a dead one. */
  contractStatus: string;
}

export function RetentionReleasePanel({
  contractId,
  currency,
  contractStatus,
}: RetentionReleasePanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [event, setEvent] = useState<RetentionReleaseRowEvent>(
    'substantial_completion',
  );
  const [amount, setAmount] = useState('');
  const [preview, setPreview] = useState<RetentionReleasePreview | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  // The release whose documents are being attached, and the claim picked for
  // the release being billed.
  const [approving, setApproving] = useState<RetentionRelease | null>(null);
  const [attached, setAttached] = useState<string[]>([]);
  const [billing, setBilling] = useState<string | null>(null);

  const summaryQ = useQuery<RetentionSummary>({
    queryKey: ['contracts', 'retention', contractId],
    queryFn: () => getRetentionSummary(contractId),
  });
  const documentsQ = useQuery<ContractDocument[]>({
    queryKey: ['contracts', 'documents', contractId],
    queryFn: () => listContractDocuments(contractId),
  });
  // A release is billed on a claim that can still be edited. Same key and
  // same call as the claim history above this drawer, so the two read one
  // cached answer rather than two lists that can disagree.
  const claimsQ = useQuery<Page<ProgressClaimItem>>({
    queryKey: ['contracts', 'claim-history', contractId],
    queryFn: () => listProgressClaims({ contract_id: contractId, limit: 50 }),
  });
  const claims = claimsQ.data?.items ?? [];

  const summary = summaryQ.data;
  const releases = useMemo(
    () => (summary?.releases ?? []).filter((r) => r.status !== 'void'),
    [summary],
  );
  const billableClaims = useMemo(
    () =>
      claims.filter((c) => c.status === 'draft' || c.status === 'submitted'),
    [claims],
  );

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['contracts', 'retention', contractId] });
    // Billing a release re-rolls the claim it is billed on, and the dashboard
    // and the close-out checklist both count what is still held.
    qc.invalidateQueries({ queryKey: ['contracts', 'claims'] });
    qc.invalidateQueries({ queryKey: ['contracts', 'claim-history', contractId] });
    qc.invalidateQueries({ queryKey: ['contracts', 'dashboard', contractId] });
    // The close-out checklist reads what is still held, and the schedule of
    // values carries per-line retention; both are keyed as the panels below
    // key them, not as this panel would have guessed.
    qc.invalidateQueries({
      queryKey: ['contracts', 'final-account-checklist', contractId],
    });
    qc.invalidateQueries({ queryKey: ['contracts', 'sov-status', contractId] });
  };

  const closeForm = () => {
    setFormOpen(false);
    setPreview(null);
    setAmount('');
  };

  const previewMut = useMutation({
    mutationFn: () =>
      previewRetentionRelease(contractId, {
        event,
        ...(amount.trim() ? { amount: amount.trim() } : {}),
      }),
    onSuccess: (data) => setPreview(data),
    onError: (err) => {
      setPreview(null);
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  const createMut = useMutation({
    mutationFn: () =>
      createRetentionRelease(contractId, {
        event,
        ...(amount.trim() ? { amount: amount.trim() } : {}),
      }),
    onSuccess: () => {
      invalidate();
      closeForm();
      addToast({
        type: 'success',
        title: t('contracts.retention_release_proposed', {
          defaultValue: 'Release proposed',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const approveMut = useMutation({
    mutationFn: (releaseId: string) =>
      approveRetentionRelease(releaseId, attached),
    onSuccess: () => {
      invalidate();
      setApproving(null);
      setAttached([]);
      addToast({
        type: 'success',
        title: t('contracts.retention_release_approved', {
          defaultValue: 'Release approved',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const registerMut = useMutation({
    mutationFn: (role: string) =>
      createContractDocument(contractId, {
        doc_role: role,
        title: documentLabel(t, role),
      }),
    onSuccess: (doc) => {
      qc.invalidateQueries({ queryKey: ['contracts', 'documents', contractId] });
      setAttached((prev) => [...prev, doc.id]);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const billMut = useMutation({
    mutationFn: ({ releaseId, claimId }: { releaseId: string; claimId: string }) =>
      billRetentionRelease(releaseId, claimId),
    onSuccess: () => {
      invalidate();
      setBilling(null);
      addToast({
        type: 'success',
        title: t('contracts.retention_release_billed', {
          defaultValue: 'Release billed on the claim',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const voidMut = useMutation({
    mutationFn: (releaseId: string) => voidRetentionRelease(releaseId),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('contracts.retention_release_voided', {
          defaultValue: 'Release voided',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const money = (value: string | number | null | undefined) => (
    <MoneyDisplay amount={toNum(value)} currency={currency || undefined} />
  );

  const releasable =
    contractStatus === 'active' ||
    contractStatus === 'suspended' ||
    contractStatus === 'completed';

  const inputCls =
    'rounded-md border border-border-light bg-surface-elevated px-2 py-1.5 text-sm';
  const labelCls = 'text-xs text-content-tertiary';

  // The documents registered on the contract, by the role they were filed
  // under, so a required role can show what is already there.
  const documentsByRole = useMemo(() => {
    const map: Record<string, ContractDocument[]> = {};
    (documentsQ.data ?? []).forEach((doc) => {
      (map[doc.doc_role] ??= []).push(doc);
    });
    return map;
  }, [documentsQ.data]);

  const approvingRequired: string[] = useMemo(() => {
    const meta = (approving?.metadata ?? {}) as Record<string, unknown>;
    const required = [
      ...((meta.required_documents as string[] | undefined) ?? []),
      ...((meta.required_documents_when_bonded as string[] | undefined) ?? []),
    ];
    return [...new Set(required)];
  }, [approving]);

  return (
    <div className="rounded-lg border border-border-light">
      <header className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Banknote size={15} className="text-content-tertiary" />
          <span className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('contracts.retention_ledger', { defaultValue: 'Retention ledger' })}
          </span>
        </div>
        {releasable && !formOpen && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setFormOpen(true);
              setPreview(null);
            }}
          >
            <Plus size={13} className="me-1" aria-hidden />
            {t('contracts.release_retainage', {
              defaultValue: 'Release retainage',
            })}
          </Button>
        )}
      </header>

      <div className="px-4 py-3">
        {summaryQ.isError && (
          <p className="text-sm text-content-tertiary">
            {t('contracts.retention_ledger_unavailable', {
              defaultValue: 'Retention ledger is unavailable right now.',
            })}
          </p>
        )}

        {summary && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-4">
            <div>
              <dt className={labelCls}>
                {t('contracts.retention_accrued', { defaultValue: 'Accrued' })}
              </dt>
              <dd>{money(summary.accrued)}</dd>
            </div>
            <div>
              <dt className={labelCls}>
                {t('contracts.retention_released_total', {
                  defaultValue: 'Paid back',
                })}
              </dt>
              <dd>{money(summary.released)}</dd>
            </div>
            <div>
              <dt className={labelCls}>
                {t('contracts.retention_held', { defaultValue: 'Retention held' })}
              </dt>
              <dd className="font-semibold">{money(summary.held)}</dd>
            </div>
            <div>
              <dt className={labelCls}>
                {t('contracts.retention_available', {
                  defaultValue: 'Free to release',
                })}
              </dt>
              <dd>{money(summary.available_for_release)}</dd>
            </div>
          </dl>
        )}

        {summary && toNum(summary.pending_release) > 0 && (
          <p className="mt-2 text-xs text-content-tertiary">
            {t('contracts.retention_pending_release', {
              defaultValue: 'Committed to a release that is not paid yet',
            })}
            : {money(summary.pending_release)}
          </p>
        )}

        {/* Preview, then the human confirm. Nothing is written until the
            second button, and the figures on the button are the server's. */}
        {formOpen && (
          <div className="mt-3 rounded-md border border-border-light p-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.release_event', { defaultValue: 'Retention release' })}
                </span>
                <select
                  value={event}
                  onChange={(e) => {
                    setEvent(e.target.value as RetentionReleaseRowEvent);
                    setPreview(null);
                  }}
                  className={inputCls}
                >
                  {RELEASE_EVENTS.map((value) => (
                    <option key={value} value={value}>
                      {retentionEventLabel(t, value)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.release_amount_optional', {
                    defaultValue: 'Amount (optional)',
                  })}
                </span>
                <input
                  value={amount}
                  onChange={(e) => {
                    setAmount(e.target.value);
                    setPreview(null);
                  }}
                  inputMode="decimal"
                  className={`${inputCls} w-36`}
                />
              </label>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => previewMut.mutate()}
                disabled={previewMut.isPending}
              >
                {t('contracts.preview_release', { defaultValue: 'Preview' })}
              </Button>
              <Button size="sm" variant="ghost" onClick={closeForm}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>

            {preview && (
              <div className="mt-3 border-t border-border-light pt-3 text-sm">
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
                  <div>
                    <dt className={labelCls}>
                      {t('contracts.retention_held', {
                        defaultValue: 'Retention held',
                      })}
                    </dt>
                    <dd>{money(preview.held)}</dd>
                  </div>
                  <div>
                    <dt className={labelCls}>
                      {t('contracts.release_withheld_open_items', {
                        defaultValue: 'Withheld for open items',
                      })}
                    </dt>
                    <dd>{money(preview.withheld_for_open_items)}</dd>
                  </div>
                  <div>
                    <dt className={labelCls}>
                      {t('finance.amount', { defaultValue: 'Amount' })}
                    </dt>
                    <dd className="font-semibold">{money(preview.amount)}</dd>
                  </div>
                  <div>
                    <dt className={labelCls}>
                      {t('contracts.release_remaining', {
                        defaultValue: 'Still held after this',
                      })}
                    </dt>
                    <dd>{money(preview.remaining)}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className={labelCls}>
                      {t('contracts.release_rule_source', {
                        defaultValue: 'Worked out from',
                      })}
                    </dt>
                    <dd>
                      {t(`contracts.release_rule_source.${preview.rule_source}`, {
                        defaultValue:
                          RULE_SOURCE_LABELS[preview.rule_source] ??
                          preview.rule_source,
                      })}
                      {preview.statute_reference ? ` · ${preview.statute_reference}` : ''}
                    </dd>
                  </div>
                </dl>

                {/* What the withholding could and could not see. An item with
                    no cost on it is not a zero. */}
                <p className="mt-2 text-xs text-content-tertiary">
                  {preview.open_items_source === 'unavailable'
                    ? t('contracts.release_open_items_unavailable', {
                        defaultValue:
                          'The punch list is not installed, so no open items were counted.',
                      })
                    : t('contracts.release_open_items_counted', {
                        defaultValue:
                          '{{count}} open items on the project, {{without}} of them without a cost.',
                        count: preview.open_items_count,
                        without: preview.open_items_without_cost,
                      })}
                </p>

                {preview.required_documents.length > 0 && (
                  <p className="mt-1 text-xs text-content-tertiary">
                    {t('contracts.release_documents_needed', {
                      defaultValue: 'Approval needs',
                    })}
                    :{' '}
                    {fmtList(preview.required_documents.map((role) => documentLabel(t, role)))}
                  </p>
                )}

                <div className="mt-3">
                  <Button
                    size="sm"
                    onClick={() => createMut.mutate()}
                    disabled={createMut.isPending || toNum(preview.amount) <= 0}
                  >
                    {t('contracts.propose_release', {
                      defaultValue: 'Propose this release',
                    })}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* The rows themselves. Void ones are left out: they are history, and
            the ledger figures above already exclude them. */}
        {releases.length > 0 && (
          <ul className="mt-3 divide-y divide-border-light border-t border-border-light">
            {releases.map((row) => {
              const claim = claims.find((c) => c.id === row.progress_claim_id);
              return (
                <li key={row.id} className="py-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Badge variant={statusTone(row.status)} size="sm">
                        {statusLabel(t, row.status)}
                      </Badge>
                      <span className="text-sm">{retentionEventLabel(t, row.event)}</span>
                      <span className="text-sm font-semibold">
                        {money(row.amount)}
                      </span>
                      {claim && (
                        <span className="text-xs text-content-tertiary">
                          {t('contracts.release_billed_on', {
                            defaultValue: 'Billed on {{claim}}',
                            claim: claim.claim_number,
                          })}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5">
                      {row.status === 'proposed' && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setApproving(row);
                            setAttached([...row.document_ids]);
                          }}
                        >
                          <FileCheck2 size={13} className="me-1" aria-hidden />
                          {t('contracts.approve_release', {
                            defaultValue: 'Approve',
                          })}
                        </Button>
                      )}
                      {row.status === 'approved' && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setBilling(row.id)}
                        >
                          <Check size={13} className="me-1" aria-hidden />
                          {t('contracts.bill_release', {
                            defaultValue: 'Bill on a claim',
                          })}
                        </Button>
                      )}
                      {/* A release billed on a claim that was already paid is
                          refused by the server, with the claim named. */}
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => voidMut.mutate(row.id)}
                        disabled={voidMut.isPending}
                      >
                        <Undo2 size={13} className="me-1" aria-hidden />
                        {t('contracts.void_release', { defaultValue: 'Void' })}
                      </Button>
                    </div>
                  </div>

                  {/* Approval: the roles the event asks for, each with what is
                      registered under it. A role with nothing behind it can be
                      registered here, so the gate names a document that
                      exists rather than one somebody promised. */}
                  {approving?.id === row.id && (
                    <div className="mt-2 rounded-md border border-border-light p-3">
                      {approvingRequired.length === 0 && (
                        <p className="text-xs text-content-tertiary">
                          {t('contracts.release_no_documents_needed', {
                            defaultValue:
                              'This event needs no documents on this contract.',
                          })}
                        </p>
                      )}
                      {approvingRequired.map((role) => {
                        const docs = documentsByRole[role] ?? [];
                        return (
                          <div key={role} className="mb-2">
                            <p className="text-xs font-medium">
                              {documentLabel(t, role)}
                            </p>
                            {docs.length === 0 ? (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => registerMut.mutate(role)}
                                disabled={registerMut.isPending}
                              >
                                {t('contracts.register_document', {
                                  defaultValue: 'Register it on the contract',
                                })}
                              </Button>
                            ) : (
                              docs.map((doc) => (
                                <label
                                  key={doc.id}
                                  className="flex items-center gap-2 text-xs"
                                >
                                  <input
                                    type="checkbox"
                                    checked={attached.includes(doc.id)}
                                    onChange={(e) =>
                                      setAttached((prev) =>
                                        e.target.checked
                                          ? [...prev, doc.id]
                                          : prev.filter((id) => id !== doc.id),
                                      )
                                    }
                                  />
                                  {doc.title || doc.doc_role}
                                </label>
                              ))
                            )}
                          </div>
                        );
                      })}
                      <div className="mt-2 flex gap-2">
                        <Button
                          size="sm"
                          onClick={() => approveMut.mutate(row.id)}
                          disabled={approveMut.isPending}
                        >
                          {t('contracts.confirm_approve_release', {
                            defaultValue: 'Approve the release',
                          })}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            setApproving(null);
                            setAttached([]);
                          }}
                        >
                          {t('common.cancel', { defaultValue: 'Cancel' })}
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* Billing: the claim that will carry it. Only a claim that
                      can still be edited is offered, which is the same rule
                      the server applies. */}
                  {billing === row.id && (
                    <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-border-light p-3">
                      {billableClaims.length === 0 ? (
                        <p className="text-xs text-content-tertiary">
                          {t('contracts.release_no_open_claim', {
                            defaultValue:
                              'A release is billed on a draft or submitted claim; this contract has none.',
                          })}
                        </p>
                      ) : (
                        billableClaims.map((claimRow) => (
                          <Button
                            key={claimRow.id}
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              billMut.mutate({
                                releaseId: row.id,
                                claimId: claimRow.id,
                              })
                            }
                            disabled={billMut.isPending}
                          >
                            {claimRow.claim_number}
                          </Button>
                        ))
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setBilling(null)}
                      >
                        {t('common.cancel', { defaultValue: 'Cancel' })}
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {summary && releases.length === 0 && !formOpen && (
          <p className="mt-2 text-xs text-content-tertiary">
            {t('contracts.retention_no_releases', {
              defaultValue: 'Nothing has been released on this contract yet.',
            })}
          </p>
        )}
      </div>
    </div>
  );
}
