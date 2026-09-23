// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SubRollupPanel — the subcontractor pay applications behind one GC progress
// claim, line by line against the GC's schedule of values.
//
// What it shows, per SOV line: what the subs were approved for this period and
// to date, next to what the GC bills on the line, with one chip per pay
// application for the three things a lender's draw inspector asks about:
// approved, lien waiver in, certificates valid at the period end.
//
// What it lets a person do: include open pay applications in this claim,
// exclude them again, re-map a pay-application line that lands on no billable
// SOV line, and open the preview of claim lines derived from the subs'
// approved amounts. It never writes the claim's lines itself: the preview's
// own commit route does, after a person has read it (AI-augmented and
// rollup-suggested alike, a human confirms).
//
// The data comes from the subcontractors module. When that module is not
// installed, or the viewer may not read it, the panel renders nothing rather
// than an error: the claim page is complete without it.

import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, HardHat, Plus, X, AlertTriangle, Info, ListTree, Download } from 'lucide-react';
import type { TFunction } from 'i18next';

import { Badge, Button, Card } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { fmtList } from '@/shared/lib/formatters';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import {
  excludePayApplicationFromClaim,
  getClaimSubRollup,
  getSuggestedClaimLines,
  includePayApplicationsInClaim,
  listPaymentApplicationLines,
  listWorkPackages,
  updatePaymentApplicationLine,
  type ClaimSubRollup,
  type SubRollupPayApp,
  type SubRollupRow,
  type SubRollupUnmappedLine,
} from '@/features/subcontractors/api';
import { billableLines } from '@/features/subcontractors/WorkPackageSovPicker';
import { listContractLines, type ProgressClaimPopulatePreview } from './api';
import { PopulatePreviewModal } from './PopulatePreviewModal';

function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

export interface SubRollupPanelProps {
  claimId: string;
  contractId: string;
  currency: string;
  /** Whether the claim is still draft or submitted, the only states whose make-up may change. */
  editable: boolean;
}

export const subRollupQueryKey = (claimId: string) => ['subcontractors', 'claim-rollup', claimId];

/**
 * The subs' suggestion in the preview modal's shape.
 *
 * ``skipped_unlinked`` here counts subcontract lines that land on no billable
 * SOV line, but the modal words that counter as "not linked to a BOQ
 * position", which would send the reader looking in the wrong place. So it is
 * zeroed for the modal, and the count travels in the subtitle in this panel's
 * own words instead, next to the re-map controls that fix it.
 *
 * A line suggested from sub billing has no BOQ position behind it. The modal
 * neither shows nor commits that field, so the empty string only satisfies the
 * progress preview's type.
 */
export async function loadSubSuggestion(claimId: string): Promise<ProgressClaimPopulatePreview> {
  const suggestion = await getSuggestedClaimLines(claimId);
  return {
    ...suggestion,
    items: suggestion.items.map((item) => ({ ...item, boq_position_id: item.boq_position_id ?? '' })),
    skipped_unlinked: 0,
  };
}

/** The claim page's words for the refusal codes the include route answers with. */
function refusalMessage(err: unknown, t: TFunction): string {
  const detail =
    err instanceof ApiError && err.body && typeof err.body === 'object'
      ? (err.body as { detail?: { code?: string } }).detail
      : undefined;
  switch (detail?.code) {
    case 'claim_not_editable':
      return t('subcontractors.rollup_err_claim_not_editable', {
        defaultValue: 'This claim is past editing, so its subcontract make-up can no longer change.',
      });
    case 'pay_application_in_other_claim':
      return t('subcontractors.rollup_err_in_other_claim', {
        defaultValue: 'That pay application is already billed on another claim.',
      });
    case 'pay_application_rejected':
      return t('subcontractors.rollup_err_rejected', {
        defaultValue: 'A rejected pay application cannot be billed to the owner.',
      });
    case 'currency_mismatch':
      return t('subcontractors.rollup_err_currency', {
        defaultValue: 'That pay application is in a different currency than this claim. Currencies are never blended.',
      });
    case 'pay_application_other_project':
    case 'pay_application_other_prime_contract':
      return t('subcontractors.rollup_err_other_contract', {
        defaultValue: 'That pay application belongs to a subcontract under a different prime contract.',
      });
    default:
      return getErrorMessage(err);
  }
}

export function SubRollupPanel({ claimId, contractId, currency, editable }: SubRollupPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [suggesting, setSuggesting] = useState(false);

  const rollupQ = useQuery({
    queryKey: subRollupQueryKey(claimId),
    queryFn: () => getClaimSubRollup(claimId),
    retry: false,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: subRollupQueryKey(claimId) });
    // The claim's validation findings read the same rollup.
    qc.invalidateQueries({ queryKey: ['contracts', 'claim', claimId] });
  };

  const includeMut = useMutation({
    mutationFn: (ids: string[]) => includePayApplicationsInClaim(claimId, ids),
    onSuccess: () => {
      setPicked(new Set());
      refresh();
      addToast({
        type: 'success',
        title: t('subcontractors.rollup_included_toast', {
          defaultValue: 'Pay applications included in this claim',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: refusalMessage(err, t) }),
  });

  const excludeMut = useMutation({
    mutationFn: (paymentId: string) => excludePayApplicationFromClaim(paymentId),
    onSuccess: refresh,
    onError: (err) => addToast({ type: 'error', title: refusalMessage(err, t) }),
  });

  const rollup = rollupQ.data;

  if (rollupQ.isError) {
    const status = rollupQ.error instanceof ApiError ? rollupQ.error.status : 0;
    // Not installed (404) or not readable by this viewer (403): the claim
    // page is whole without the panel. Anything else is a real failure.
    if (status === 404 || status === 403) return null;
    return (
      <Card padding="sm">
        <p className="text-xs text-rose-600" role="alert">
          {getErrorMessage(rollupQ.error)}
        </p>
      </Card>
    );
  }

  if (rollupQ.isLoading || !rollup) {
    return (
      <Card padding="sm">
        <p className="py-3 text-center text-sm text-content-tertiary">
          <Loader2 size={14} className="mr-2 inline animate-spin" />
          {t('common.loading', { defaultValue: 'Loading…' })}
        </p>
      </Card>
    );
  }

  const nothingYet =
    rollup.included.length === 0 && rollup.candidates.length === 0 && rollup.unmapped_lines.length === 0;
  if (nothingYet && rollup.agreements.length === 0) return null;

  const money = (v: number | string) => (
    <MoneyDisplay amount={toNum(v)} currency={rollup.currency || currency || undefined} />
  );

  return (
    <Card padding="sm" data-testid="sub-rollup-panel">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary">
          <HardHat size={14} aria-hidden />
          {t('subcontractors.rollup_title', { defaultValue: 'Subcontractor billing' })}
        </p>
        <p className="text-xs text-content-secondary" data-testid="sub-rollup-totals">
          {t('subcontractors.rollup_subs_approved', { defaultValue: 'Subs approved this period' })}:{' '}
          {money(rollup.sub_period_approved_total)}
          {' · '}
          {t('subcontractors.rollup_gc_billed', { defaultValue: 'GC bills this period' })}:{' '}
          {money(rollup.gc_period_total)}
        </p>
      </div>

      <RollupHints rollup={rollup} />

      {rollup.lines.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="sub-rollup-lines">
            <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
              <tr>
                <th className="px-2 py-1.5 text-left">{t('contracts.line', { defaultValue: 'Line' })}</th>
                <th className="px-2 py-1.5 text-right">
                  {t('subcontractors.rollup_col_scheduled', { defaultValue: 'Scheduled' })}
                </th>
                <th className="px-2 py-1.5 text-right">
                  {t('subcontractors.rollup_col_gc_period', { defaultValue: 'GC this period' })}
                </th>
                <th className="px-2 py-1.5 text-right">
                  {t('subcontractors.rollup_col_sub_period', { defaultValue: 'Subs this period' })}
                </th>
                <th className="px-2 py-1.5 text-right">
                  {t('subcontractors.rollup_col_sub_to_date', { defaultValue: 'Subs to date' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {rollup.lines.map((line) => (
                <tr key={line.contract_line_id} className="border-t border-border-light align-top">
                  <td className="px-2 py-1.5">
                    <div className="font-mono text-content-secondary">{line.code || '—'}</div>
                    <div className="max-w-[260px] truncate text-content-primary">{line.description}</div>
                    <div className="mt-1 flex flex-col gap-1">
                      {line.subs.map((row) => (
                        <SubRowChips key={row.payment_application_id} row={row} />
                      ))}
                    </div>
                  </td>
                  <td className="px-2 py-1.5 text-right">{money(line.scheduled_value)}</td>
                  <td className="px-2 py-1.5 text-right">{money(line.gc_period_value)}</td>
                  <td className="px-2 py-1.5 text-right font-medium">{money(line.sub_period_approved)}</td>
                  <td className="px-2 py-1.5 text-right">
                    {money(line.sub_approved_to_date)}
                    {line.exceeds_scheduled_value && (
                      <div className="mt-0.5">
                        <Badge variant="warning" size="sm">
                          {t('subcontractors.rollup_over_scheduled', { defaultValue: 'Above scheduled value' })}
                        </Badge>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rollup.included.length > 0 && (
        <section className="mt-3" aria-label={t('subcontractors.rollup_included', { defaultValue: 'Included in this claim' })}>
          <div className="mb-1 flex items-center justify-between gap-2">
            <p className="text-xs font-medium text-content-secondary">
              {t('subcontractors.rollup_included', { defaultValue: 'Included in this claim' })}
            </p>
            {editable && (
              // Opens a preview only. The claim's lines change when a person
              // commits it there, through the same route as field progress.
              <Button
                variant="secondary"
                size="sm"
                icon={<Download size={12} />}
                onClick={() => setSuggesting(true)}
                data-testid="sub-rollup-suggest"
              >
                {t('subcontractors.rollup_suggest_button', { defaultValue: "Use subs' approved amounts" })}
              </Button>
            )}
          </div>
          <ul className="space-y-1">
            {rollup.included.map((pa) => (
              <IncludedPayApp
                key={pa.payment_application_id}
                payApp={pa}
                contractId={contractId}
                currency={rollup.currency || currency}
                editable={editable}
                excluding={excludeMut.isPending && excludeMut.variables === pa.payment_application_id}
                onExclude={() => excludeMut.mutate(pa.payment_application_id)}
                onChanged={refresh}
              />
            ))}
          </ul>
        </section>
      )}

      {editable && rollup.candidates.length > 0 && (
        <section className="mt-3" aria-label={t('subcontractors.rollup_candidates', { defaultValue: 'Open pay applications' })}>
          <div className="mb-1 flex items-center justify-between gap-2">
            <p className="text-xs font-medium text-content-secondary">
              {t('subcontractors.rollup_candidates', { defaultValue: 'Open pay applications' })}
            </p>
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={12} />}
              disabled={picked.size === 0}
              loading={includeMut.isPending}
              onClick={() => includeMut.mutate([...picked])}
              data-testid="sub-rollup-include"
            >
              {t('subcontractors.rollup_include_selected', {
                count: picked.size,
                defaultValue: 'Include {{count}} selected',
              })}
            </Button>
          </div>
          <ul className="space-y-1">
            {rollup.candidates.map((pa) => (
              <PayAppRow
                key={pa.payment_application_id}
                payApp={pa}
                currency={rollup.currency || currency}
                leading={
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-border accent-oe-blue"
                    checked={picked.has(pa.payment_application_id)}
                    disabled={pa.foreign_currency}
                    onChange={() =>
                      setPicked((prev) => {
                        const next = new Set(prev);
                        if (next.has(pa.payment_application_id)) next.delete(pa.payment_application_id);
                        else next.add(pa.payment_application_id);
                        return next;
                      })
                    }
                    aria-label={t('subcontractors.rollup_pick', {
                      number: pa.application_number,
                      defaultValue: 'Include pay application {{number}}',
                    })}
                  />
                }
              />
            ))}
          </ul>
        </section>
      )}

      {rollup.unmapped_lines.length > 0 && (
        <UnmappedLines
          lines={rollup.unmapped_lines}
          contractId={contractId}
          currency={rollup.currency || currency}
          editable={editable}
          onChanged={refresh}
        />
      )}

      {suggesting && (
        <PopulatePreviewModal
          claimId={claimId}
          currency={rollup.currency || currency}
          loadPreview={loadSubSuggestion}
          title={t('subcontractors.rollup_suggest_title', {
            defaultValue: "Claim lines from the subs' approved amounts",
          })}
          subtitle={
            rollup.unmapped_lines.length > 0
              ? t('subcontractors.rollup_suggest_subtitle_unmapped', {
                  count: rollup.unmapped_lines.length,
                  defaultValue:
                    'Each line carries what the included pay applications approved on it, next to the lines this claim already has. Only the lines you leave selected are written; the rest of the claim stays as it is. {{count}} subcontract line(s) land on no billable line and are left out; re-map them in the panel first if they belong here.',
                })
              : t('subcontractors.rollup_suggest_subtitle', {
                  defaultValue:
                    'Each line carries what the included pay applications approved on it, next to the lines this claim already has. Only the lines you leave selected are written; the rest of the claim stays as it is.',
                })
          }
          successText={t('subcontractors.rollup_suggest_committed', {
            defaultValue: "Claim lines updated from the subs' approved amounts",
          })}
          emptyText={t('subcontractors.rollup_suggest_empty', {
            defaultValue:
              'No included pay application lands on a billable line of this contract yet. Link the work packages to schedule-of-values lines, then try again.',
          })}
          onClose={() => setSuggesting(false)}
          onCommitted={refresh}
        />
      )}
    </Card>
  );
}

function RollupHints({ rollup }: { rollup: ClaimSubRollup }) {
  const { t } = useTranslation();
  const hints: string[] = [];
  if (rollup.period_matching === 'explicit_only') {
    hints.push(
      t('subcontractors.rollup_hint_no_period', {
        defaultValue:
          'This claim has no period dates, so pay applications are not matched to it by date. Every open one is offered; include the ones this claim bills.',
      }),
    );
  }
  if (rollup.skipped_foreign_currency > 0) {
    hints.push(
      t('subcontractors.rollup_hint_currency', {
        count: rollup.skipped_foreign_currency,
        defaultValue: '{{count}} pay application line(s) left out: a different currency than this claim (never blended).',
      }),
    );
  }
  if (rollup.agreements.some((a) => a.resolution === 'ambiguous')) {
    hints.push(
      t('subcontractors.rollup_hint_ambiguous', {
        defaultValue:
          'Some subcontracts do not name their prime contract and this project has several. Name it on the agreement so its pay applications are offered on the right claim.',
      }),
    );
  }
  hints.push(
    rollup.requirements.source === 'pack'
      ? t('subcontractors.rollup_hint_requirements_pack', {
          reference: rollup.requirements.reference || '—',
          defaultValue: 'Certificates and waivers are checked against the national pack ({{reference}}).',
        })
      : t('subcontractors.rollup_hint_requirements_fallback', {
          defaultValue:
            'No national pack states what a subcontractor must hold before payment here, so the built-in list (insurance and license) is checked.',
        }),
  );
  return (
    <div className="mb-2 flex flex-col gap-1 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs text-content-secondary" role="status">
      {hints.map((h) => (
        <span key={h} className="flex items-start gap-1.5">
          <Info size={12} className="mt-0.5 shrink-0" aria-hidden />
          {h}
        </span>
      ))}
    </div>
  );
}

/** The three chips a draw inspector reads: approved, waiver in, certificates. */
function StatusChips({
  status,
  waiverState,
  waiverCovers,
  waiverRequired,
  certificatesOk,
  pendingPayment,
}: {
  status: string;
  waiverState: string;
  waiverCovers: boolean;
  waiverRequired: boolean;
  certificatesOk: boolean | null;
  /** A certificate the pack reads on the payment date, and the payment is still to come. */
  pendingPayment?: boolean | null;
}) {
  const { t } = useTranslation();
  const approved = status === 'foreman_approved' || status === 'finance_approved' || status === 'paid';
  return (
    <span className="flex flex-wrap items-center gap-1">
      {approved ? (
        <Badge variant="success" size="sm">
          {status === 'paid'
            ? t('subcontractors.rollup_chip_paid', { defaultValue: 'Paid' })
            : t('subcontractors.rollup_chip_approved', { defaultValue: 'Approved' })}
        </Badge>
      ) : status === 'rejected' ? (
        <Badge variant="error" size="sm">
          {t('subcontractors.rollup_chip_rejected', { defaultValue: 'Rejected' })}
        </Badge>
      ) : (
        <Badge variant="warning" size="sm">
          {t('subcontractors.rollup_chip_received', { defaultValue: 'Received, not approved' })}
        </Badge>
      )}
      {waiverCovers ? (
        <Badge variant="success" size="sm">
          {waiverState === 'unconditional'
            ? t('subcontractors.rollup_chip_waiver_unconditional', { defaultValue: 'Unconditional waiver in' })
            : t('subcontractors.rollup_chip_waiver_conditional', { defaultValue: 'Conditional waiver in' })}
        </Badge>
      ) : (
        <Badge variant={waiverRequired ? 'error' : 'neutral'} size="sm">
          {waiverState === 'none'
            ? t('subcontractors.rollup_chip_waiver_none', { defaultValue: 'No waiver' })
            : t('subcontractors.rollup_chip_waiver_short', { defaultValue: 'Waiver short of net' })}
        </Badge>
      )}
      {certificatesOk === true ? (
        <Badge variant="success" size="sm">
          {t('subcontractors.rollup_chip_certs_ok', { defaultValue: 'Certificates valid' })}
        </Badge>
      ) : certificatesOk === false ? (
        <Badge variant="error" size="sm">
          {t('subcontractors.rollup_chip_certs_lapsed', { defaultValue: 'Certificate lapsed' })}
        </Badge>
      ) : pendingPayment ? (
        // Not "valid" and not "unchecked": the law reads this certificate on
        // the day of payment, and that day has not come yet.
        <Badge variant="warning" size="sm">
          {t('subcontractors.rollup_chip_certs_on_payment', { defaultValue: 'Certificate checked on the payment date' })}
        </Badge>
      ) : (
        <Badge variant="neutral" size="sm">
          {t('subcontractors.rollup_chip_certs_unchecked', { defaultValue: 'Certificates not checked: no period end' })}
        </Badge>
      )}
    </span>
  );
}

function SubRowChips({ row }: { row: SubRollupRow }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <span className="text-content-secondary">
        {row.application_number}
        {row.subcontractor_name ? ` · ${row.subcontractor_name}` : ''}
      </span>
      <StatusChips
        status={row.status}
        waiverState={row.waiver_state}
        waiverCovers={row.waiver_covers_net}
        waiverRequired={false}
        certificatesOk={row.certificates_ok}
        pendingPayment={row.certificates_pending_payment}
      />
    </span>
  );
}

/** An included pay application: its row, and on request its lines with an SOV override each. */
function IncludedPayApp({
  payApp,
  contractId,
  currency,
  editable,
  excluding,
  onExclude,
  onChanged,
}: {
  payApp: SubRollupPayApp;
  contractId: string;
  currency: string;
  editable: boolean;
  excluding: boolean;
  onExclude: () => void;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <PayAppRow
      payApp={payApp}
      currency={currency}
      action={
        editable ? (
          <span className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              icon={<ListTree size={12} />}
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
            >
              {t('subcontractors.rollup_lines_toggle', { defaultValue: 'Lines' })}
            </Button>
            <Button variant="ghost" size="sm" icon={<X size={12} />} onClick={onExclude} loading={excluding}>
              {t('subcontractors.rollup_exclude', { defaultValue: 'Exclude' })}
            </Button>
          </span>
        ) : null
      }
      footer={
        open ? (
          <PayAppLines payApp={payApp} contractId={contractId} currency={currency} onChanged={onChanged} />
        ) : null
      }
    />
  );
}

/**
 * The lines of one pay application, each with the SOV line it bills on.
 *
 * Empty means "the work package's default"; choosing a line overrides it for
 * this pay-application line only. The server refuses a line that is not on a
 * client contract of the project, and refuses any change once the claim is
 * past editing.
 */
function PayAppLines({
  payApp,
  contractId,
  currency,
  onChanged,
}: {
  payApp: SubRollupPayApp;
  contractId: string;
  currency: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const linesKey = ['subcontractors', 'pay-app-lines', payApp.payment_application_id];

  const linesQ = useQuery({
    queryKey: linesKey,
    queryFn: () => listPaymentApplicationLines(payApp.payment_application_id),
  });
  const packagesQ = useQuery({
    queryKey: ['subcontractors', 'workPackages', payApp.agreement_id],
    queryFn: () => listWorkPackages(payApp.agreement_id),
  });
  const sovQ = useQuery({
    queryKey: ['subcontractors', 'prime-contract-lines', contractId],
    queryFn: () => listContractLines(contractId),
  });

  const options = useMemo(() => billableLines(sovQ.data ?? []), [sovQ.data]);
  const codeOf = useMemo(() => {
    const byId = new Map((sovQ.data ?? []).map((ln) => [ln.id, ln.code || ln.description] as const));
    return (id: string | null | undefined) => (id ? byId.get(id) : undefined);
  }, [sovQ.data]);
  const packages = useMemo(
    () => new Map((packagesQ.data ?? []).map((wp) => [wp.id, wp] as const)),
    [packagesQ.data],
  );

  const remap = useMutation({
    mutationFn: ({ lineId, target }: { lineId: string; target: string | null }) =>
      updatePaymentApplicationLine(lineId, { contract_line_id: target }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: linesKey });
      onChanged();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (linesQ.isLoading) {
    return (
      <p className="w-full py-1 text-content-tertiary">
        <Loader2 size={12} className="mr-1 inline animate-spin" />
        {t('common.loading', { defaultValue: 'Loading…' })}
      </p>
    );
  }

  return (
    <ul className="w-full space-y-1 border-t border-border-light pt-1.5" data-testid="sub-rollup-pay-app-lines">
      {(linesQ.data ?? []).map((line) => {
        const pkg = packages.get(line.work_package_id);
        const packageDefault = codeOf(pkg?.contract_line_id);
        return (
          <li key={line.id} className="flex flex-wrap items-center gap-2">
            <span className="min-w-[120px] text-content-primary">{pkg?.name || '—'}</span>
            <MoneyDisplay amount={toNum(line.approved_amount)} currency={currency || undefined} />
            <select
              value={line.contract_line_id ?? ''}
              onChange={(e) => remap.mutate({ lineId: line.id, target: e.target.value || null })}
              disabled={remap.isPending || sovQ.isLoading}
              className="ml-auto h-7 max-w-[260px] truncate rounded-md border border-border-light bg-surface-primary px-1.5 text-xs"
              aria-label={t('subcontractors.rollup_line_override_label', {
                name: pkg?.name || '—',
                defaultValue: 'SOV line for the {{name}} line',
              })}
              data-testid="sub-rollup-line-override"
            >
              <option value="">
                {packageDefault
                  ? t('subcontractors.rollup_line_package_default', {
                      line: packageDefault,
                      defaultValue: 'Work package default ({{line}})',
                    })
                  : t('subcontractors.rollup_line_package_default_none', {
                      defaultValue: 'Work package default (not linked)',
                    })}
              </option>
              {options.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.code ? `${opt.code} · ${opt.description}` : opt.description}
                </option>
              ))}
            </select>
          </li>
        );
      })}
    </ul>
  );
}

function PayAppRow({
  payApp,
  currency,
  leading,
  action,
  footer,
}: {
  payApp: SubRollupPayApp;
  currency: string;
  leading?: ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
}) {
  const { t } = useTranslation();
  const lapsed = fmtList([
    ...payApp.certificate_findings.map((f) => f.document_type),
    // A payment-date certificate that did not cover a payment already made.
    // One still waiting for its payment is not lapsed, and the chip says so.
    ...(payApp.payment_date_findings ?? [])
      .filter((f) => !f.state.startsWith('pending'))
      .map((f) => f.document_type),
  ]);
  return (
    <li
      className="flex flex-wrap items-center gap-2 rounded-md border border-border-light px-2 py-1.5 text-xs"
      data-testid="sub-rollup-pay-app"
    >
      {leading}
      <span className="font-medium text-content-primary">{payApp.application_number}</span>
      <span className="text-content-secondary">{payApp.subcontractor_name}</span>
      {payApp.period_end && (
        <span className="text-content-tertiary">
          <DateDisplay value={payApp.period_end} />
        </span>
      )}
      {payApp.in_period === false && (
        <Badge variant="neutral" size="sm">
          {t('subcontractors.rollup_out_of_period', { defaultValue: 'Outside this period' })}
        </Badge>
      )}
      {payApp.foreign_currency && (
        <Badge variant="warning" size="sm">
          {t('subcontractors.rollup_foreign_currency', {
            currency: payApp.currency,
            defaultValue: 'In {{currency}}',
          })}
        </Badge>
      )}
      {payApp.line_count === 0 ? (
        // The claim bills through lines, so a pay application without any
        // bills nothing here, whatever its gross; a bare zero would hide why.
        <span data-testid="sub-rollup-no-lines">
          <Badge variant="neutral" size="sm">
            {t('subcontractors.rollup_no_lines', { defaultValue: 'No lines, not billed' })}
          </Badge>
        </span>
      ) : (
        <span className="font-medium">
          <MoneyDisplay amount={toNum(payApp.approved_amount)} currency={currency || undefined} />
        </span>
      )}
      <StatusChips
        status={payApp.status}
        waiverState={payApp.waiver.state}
        waiverCovers={payApp.waiver.covers_net}
        waiverRequired={payApp.requires_lien_waiver}
        certificatesOk={payApp.certificates_ok}
        pendingPayment={payApp.certificates_pending_payment}
      />
      {lapsed && (
        <span className="text-rose-600" title={lapsed}>
          {lapsed}
        </span>
      )}
      <span className="ml-auto">{action}</span>
      {footer}
    </li>
  );
}

function UnmappedLines({
  lines,
  contractId,
  currency,
  editable,
  onChanged,
}: {
  lines: SubRollupUnmappedLine[];
  contractId: string;
  currency: string;
  editable: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const sovQ = useQuery({
    queryKey: ['subcontractors', 'prime-contract-lines', contractId],
    queryFn: () => listContractLines(contractId),
    enabled: editable,
  });
  const options = useMemo(() => billableLines(sovQ.data ?? []), [sovQ.data]);

  const remap = useMutation({
    mutationFn: ({ lineId, target }: { lineId: string; target: string }) =>
      updatePaymentApplicationLine(lineId, { contract_line_id: target }),
    onSuccess: onChanged,
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const reasonLabel = (reason: string) =>
    reason === 'foreign_line'
      ? t('subcontractors.rollup_unmapped_foreign', { defaultValue: 'Linked to another contract' })
      : reason === 'parent_line'
        ? t('subcontractors.rollup_unmapped_parent', { defaultValue: 'Linked to a grouping line' })
        : t('subcontractors.rollup_unmapped_none', { defaultValue: 'Not linked' });

  return (
    <section
      className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 dark:border-amber-800 dark:bg-amber-950/40"
      aria-label={t('subcontractors.rollup_unmapped_title', { defaultValue: 'Lines not on the schedule of values' })}
      data-testid="sub-rollup-unmapped"
    >
      <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-amber-800 dark:text-amber-300">
        <AlertTriangle size={12} aria-hidden />
        {t('subcontractors.rollup_unmapped_title', { defaultValue: 'Lines not on the schedule of values' })}
      </p>
      <ul className="space-y-1">
        {lines.map((ln) => (
          <li key={ln.line_id} className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
            <span className="font-medium text-content-primary">{ln.application_number}</span>
            <span>{ln.work_package_name}</span>
            <MoneyDisplay amount={toNum(ln.approved_amount)} currency={currency || undefined} />
            <Badge variant="warning" size="sm">
              {reasonLabel(ln.reason)}
            </Badge>
            {editable && (
              <select
                value=""
                onChange={(e) => e.target.value && remap.mutate({ lineId: ln.line_id, target: e.target.value })}
                disabled={remap.isPending || sovQ.isLoading}
                className="ml-auto h-7 max-w-[240px] truncate rounded-md border border-border-light bg-surface-primary px-1.5 text-xs"
                aria-label={t('subcontractors.rollup_remap_label', {
                  number: ln.application_number,
                  defaultValue: 'Bill this line of {{number}} on',
                })}
                data-testid="sub-rollup-remap"
              >
                <option value="">
                  {t('subcontractors.rollup_remap_placeholder', { defaultValue: 'Choose an SOV line' })}
                </option>
                {options.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.code ? `${opt.code} · ${opt.description}` : opt.description}
                  </option>
                ))}
              </select>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
