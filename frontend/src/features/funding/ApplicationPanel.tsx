// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ApplicationPanel - one funding application, from the decision to the
// receipts that close it.
//
// The register lists applications; this is the only place the money actually
// moves. The order of the sections is the order of the work, and it is not
// alphabetical or cosmetic: the decision comes first because recording it is
// what derives every deadline below it, the eligible cost split comes next
// because it decides what may be drawn at all, then the draws, then the proof
// of use that has to reach the authority before the retention clock starts.
//
// Everything renders from one request. `getApplication` returns the
// application, its programme, its draws, proofs, deadlines, cost split, the
// worked-out totals and the validation findings together, so the panel cannot
// show a total that disagrees with the rows underneath it.

import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowLeft,
  Banknote,
  CalendarClock,
  CheckCircle2,
  FileCheck2,
  Info,
  Layers,
  Plus,
} from 'lucide-react';

import { Badge, type BadgeVariant, Button, Card, EmptyState, Skeleton } from '@/shared/ui';
import { fmtDate } from '@/shared/lib/formatters';
import { formatCurrency } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';

import {
  acceptProofOfUse,
  confirmReceipt,
  createCostAllocation,
  createDisbursement,
  createProofOfUse,
  declaresAmount,
  fundingKeys,
  getApplication,
  localToday,
  percentText,
  recordAward,
  updateObligation,
} from './api';
import type {
  DisbursementStatus,
  Eligibility,
  FundingDisbursement,
  ProofKind,
  ProofStatus,
  ValidationFinding,
} from './api';
import { obligationLabel } from './obligationLabel';

const ELIGIBILITIES: Eligibility[] = ['eligible', 'partially_eligible', 'not_eligible', 'undecided'];
const PROOF_KINDS: ProofKind[] = ['interim', 'final'];

const BLANK_AWARD = {
  award_reference: '',
  approved_amount: '',
  award_period_start: '',
  award_period_end: '',
  conditions: '',
  rejection_reason: '',
};

const BLANK_ALLOCATION = {
  cost_group: '',
  description: '',
  amount: '',
  eligible_amount: '',
  eligibility: 'eligible' as Eligibility,
};

const BLANK_DRAW = {
  period_from: '',
  period_to: '',
  amount_requested: '',
  notes: '',
};

function drawVariant(status: DisbursementStatus): BadgeVariant {
  if (status === 'paid') return 'success';
  if (status === 'rejected') return 'error';
  if (status === 'approved') return 'blue';
  if (status === 'submitted') return 'warning';
  return 'neutral';
}

function proofVariant(status: ProofStatus): BadgeVariant {
  if (status === 'accepted') return 'success';
  if (status === 'rejected') return 'error';
  if (status === 'submitted') return 'blue';
  if (status === 'drafting') return 'warning';
  return 'neutral';
}

function eligibilityVariant(value: Eligibility): BadgeVariant {
  if (value === 'eligible') return 'success';
  if (value === 'not_eligible') return 'error';
  if (value === 'partially_eligible') return 'warning';
  return 'neutral';
}

/** A labelled control, so the label and the field it names cannot drift apart. */
function Field({
  label,
  value,
  onChange,
  type = 'text',
  mode,
  children,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  type?: 'text' | 'date';
  mode?: 'decimal' | 'numeric';
  children?: React.ReactNode;
}) {
  const id = useId();
  const shared =
    'w-full rounded border border-gray-300 px-2 py-1.5 dark:border-gray-600 dark:bg-gray-800';
  return (
    <div className="text-sm">
      <label htmlFor={id} className="mb-1 block text-gray-600 dark:text-gray-300">
        {label}
      </label>
      {children ? (
        children
      ) : (
        <input
          id={id}
          type={type}
          value={value}
          inputMode={mode}
          onChange={(e) => onChange(e.target.value)}
          className={mode ? `${shared} text-right tabular-nums` : shared}
        />
      )}
    </div>
  );
}

/** One worked-out figure, with the label above it and the unit beside it. */
function Figure({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded border border-gray-100 px-3 py-2 dark:border-gray-800">
      <div className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">{label}</div>
      <div className="mt-0.5 font-medium tabular-nums">{value}</div>
      {sub ? <div className="text-xs text-gray-500 dark:text-gray-400">{sub}</div> : null}
    </div>
  );
}

/** A section of the panel, headed so the reader can tell where they are. */
function Section({
  icon,
  title,
  hint,
  action,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-gray-100 pt-4 dark:border-gray-800">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            {icon}
            {title}
          </h3>
          {hint ? <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{hint}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export interface ApplicationPanelProps {
  applicationId: string;
  projectId: string;
  /** The project currency, used until the application declares its own. */
  currency: string;
  onBack: () => void;
}

export function ApplicationPanel({ applicationId, projectId, currency, onBack }: ApplicationPanelProps) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const today = localToday();

  const [awardDraft, setAwardDraft] = useState(BLANK_AWARD);
  const [awardApproved, setAwardApproved] = useState(true);
  const [allocationDraft, setAllocationDraft] = useState(BLANK_ALLOCATION);
  const [showAllocationForm, setShowAllocationForm] = useState(false);
  const [drawDraft, setDrawDraft] = useState(BLANK_DRAW);
  const [showDrawForm, setShowDrawForm] = useState(false);
  const [receiptFor, setReceiptFor] = useState<string | null>(null);
  const [receiptAmount, setReceiptAmount] = useState('');
  const [receiptOn, setReceiptOn] = useState(today);
  const [proofKind, setProofKind] = useState<ProofKind>('interim');
  const [proofDue, setProofDue] = useState('');
  const [showProofForm, setShowProofForm] = useState(false);

  // The language is part of the key: without it a language switch kept showing
  // the cached findings in the previous language until something refetched.
  const { data, isLoading, isError } = useQuery({
    queryKey: fundingKeys.applicationIn(applicationId, i18n.language),
    queryFn: () => getApplication(applicationId, { today, locale: i18n.language }),
    enabled: Boolean(applicationId),
  });

  /** Everything an award touches, because it derives deadlines and totals. */
  function refresh() {
    void qc.invalidateQueries({ queryKey: fundingKeys.application(applicationId) });
    void qc.invalidateQueries({ queryKey: fundingKeys.applications(projectId) });
    void qc.invalidateQueries({ queryKey: fundingKeys.obligations(projectId) });
    void qc.invalidateQueries({ queryKey: fundingKeys.projectSummary(projectId) });
  }

  function failed(err: unknown) {
    addToast({ type: 'error', title: err instanceof Error ? err.message : String(err) });
  }

  const awardMutation = useMutation({
    mutationFn: () =>
      recordAward(applicationId, {
        approved: awardApproved,
        decided_on: today,
        award_reference: awardDraft.award_reference.trim(),
        approved_amount: awardApproved ? awardDraft.approved_amount.trim() || '0' : '0',
        award_period_start: awardDraft.award_period_start || undefined,
        award_period_end: awardDraft.award_period_end || undefined,
        conditions: awardDraft.conditions.trim(),
        rejection_reason: awardApproved ? '' : awardDraft.rejection_reason.trim(),
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: awardApproved
          ? t('funding.award_recorded', { defaultValue: 'Award recorded, deadlines derived' })
          : t('funding.rejection_recorded', { defaultValue: 'Rejection recorded' }),
      });
      setAwardDraft(BLANK_AWARD);
      refresh();
    },
    onError: failed,
  });

  const allocationMutation = useMutation({
    mutationFn: () =>
      createCostAllocation(applicationId, {
        cost_group: allocationDraft.cost_group.trim(),
        description: allocationDraft.description.trim(),
        amount: allocationDraft.amount.trim() || '0',
        eligible_amount: allocationDraft.eligible_amount.trim() || '0',
        eligibility: allocationDraft.eligibility,
      }),
    onSuccess: () => {
      setAllocationDraft(BLANK_ALLOCATION);
      setShowAllocationForm(false);
      refresh();
    },
    onError: failed,
  });

  const drawMutation = useMutation({
    mutationFn: () =>
      createDisbursement(applicationId, {
        period_from: drawDraft.period_from || undefined,
        period_to: drawDraft.period_to || undefined,
        requested_on: today,
        amount_requested: drawDraft.amount_requested.trim() || '0',
        notes: drawDraft.notes.trim(),
      }),
    onSuccess: () => {
      setDrawDraft(BLANK_DRAW);
      setShowDrawForm(false);
      refresh();
    },
    onError: failed,
  });

  const receiptMutation = useMutation({
    mutationFn: (id: string) =>
      confirmReceipt(id, { received_on: receiptOn, amount_received: receiptAmount.trim() || undefined }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('funding.receipt_confirmed', { defaultValue: 'Receipt confirmed, the spend window starts' }),
      });
      setReceiptFor(null);
      setReceiptAmount('');
      refresh();
    },
    onError: failed,
  });

  const proofMutation = useMutation({
    mutationFn: () =>
      createProofOfUse(applicationId, { kind: proofKind, due_on: proofDue || undefined }),
    onSuccess: () => {
      setProofDue('');
      setShowProofForm(false);
      refresh();
    },
    onError: failed,
  });

  const acceptMutation = useMutation({
    mutationFn: (id: string) => acceptProofOfUse(id, today),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('funding.proof_accepted', { defaultValue: 'Proof of use accepted' }),
      });
      refresh();
    },
    onError: failed,
  });

  const obligationMutation = useMutation({
    mutationFn: (id: string) => updateObligation(id, { status: 'done', completed_on: today }),
    onSuccess: refresh,
    onError: failed,
  });

  if (isLoading) {
    return (
      <Card className="space-y-3 p-4">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card>
        <EmptyState
          icon={<AlertTriangle className="h-8 w-8" />}
          title={t('funding.load_failed', { defaultValue: 'Could not load applications' })}
          action={
            <Button variant="secondary" onClick={onBack}>
              <ArrowLeft className="h-4 w-4" />
              {t('common.back', { defaultValue: 'Back' })}
            </Button>
          }
        />
      </Card>
    );
  }

  const { application, programme, summary, disbursements, proofs_of_use, obligations, cost_allocations } = data;
  const unit = summary.currency || application.currency || currency;
  const decided = Boolean(application.decided_on);

  /**
   * An amount with its currency, never a bare number next to another one.
   *
   * Formatted rather than concatenated: the wire sends a plain decimal string,
   * and in German or Spanish the point in "100000.00" reads as a thousands
   * separator. The same trap as the percentages, and the same answer, which is
   * to let the reader's locale write the number.
   */
  function money(value: string | null | undefined): string {
    if (value === null || value === undefined || value === '') return '—';
    return formatCurrency(value, unit);
  }

  /**
   * A stored date as the reader reads dates.
   *
   * The value on the record is ISO-8601 and stays that way everywhere it is
   * a value rather than a label: in a date input, in the draft state behind
   * one, in the `today=` the queries send, and in anything sorted or keyed.
   * This is only for the ones that are read, where an ISO string is both a
   * foreign convention and, in a right-to-left page, a token the browser
   * breaks in the middle of.
   */
  function date(value: string | null | undefined): string {
    return value ? fmtDate(value) : '—';
  }

  const blocking = data.findings.filter((f: ValidationFinding) => !f.passed);
  const rate = percentText(summary.effective_funding_rate_percent);

  return (
    <Card className="space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <button
            type="button"
            onClick={onBack}
            className="mb-1 flex items-center gap-1 text-xs text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t('funding.back_to_register', { defaultValue: 'Back to the register' })}
          </button>
          <h2 className="text-lg font-semibold">
            {application.code}
            {application.title ? ` · ${application.title}` : ''}
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {programme ? programme.name || programme.code : t('funding.programme_gone', { defaultValue: 'The programme is no longer in the catalogue' })}
          </p>
        </div>
        <Badge variant={application.status === 'approved' ? 'success' : application.status === 'rejected' ? 'error' : 'blue'}>
          {t(`funding.status.${application.status}`, { defaultValue: application.status })}
        </Badge>
      </div>

      {blocking.length > 0 ? (
        <ul className="space-y-1.5">
          {blocking.map((finding: ValidationFinding) => (
            <li
              key={finding.rule_id}
              className="flex items-start gap-2 rounded border border-gray-100 px-3 py-2 text-sm dark:border-gray-800"
            >
              <Badge variant={finding.severity === 'error' ? 'error' : finding.severity === 'warning' ? 'warning' : 'neutral'} size="sm">
                {t(`funding.severity.${finding.severity}`, { defaultValue: finding.severity })}
              </Badge>
              <span className="min-w-0">
                <span className="block text-gray-700 dark:text-gray-200">{finding.message}</span>
                {finding.suggestion ? (
                  <span className="block text-xs text-gray-500 dark:text-gray-400">{finding.suggestion}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
          <CheckCircle2 className="h-4 w-4" />
          {t('funding.checks_pass', { defaultValue: 'Every check on this application passes' })}
        </p>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Figure label={t('funding.field.approved', { defaultValue: 'Approved' })} value={money(summary.approved_amount)} />
        <Figure label={t('funding.field.drawn', { defaultValue: 'Drawn' })} value={money(summary.drawn_amount)} />
        <Figure label={t('funding.field.received', { defaultValue: 'Received' })} value={money(summary.received_amount)} />
        <Figure label={t('funding.field.outstanding', { defaultValue: 'Still to draw' })} value={money(summary.outstanding_amount)} />
        <Figure
          label={t('funding.field.own_share', { defaultValue: 'Own contribution' })}
          value={money(summary.own_share_recorded)}
          sub={t('funding.own_share_required', {
            amount: money(summary.own_share_required),
            defaultValue: '{{amount}} required',
          })}
        />
        <Figure
          label={t('funding.field.effective_rate', { defaultValue: 'Effective rate' })}
          value={rate || '—'}
          sub={t('funding.effective_rate_of', {
            amount: money(summary.eligible_cost_base),
            defaultValue: 'of {{amount}} eligible',
          })}
        />
      </div>

      <Section
        icon={<FileCheck2 className="h-4 w-4" />}
        title={t('funding.decision', { defaultValue: 'Decision' })}
        hint={
          decided
            ? undefined
            : t('funding.decision_hint', {
                defaultValue:
                  'Recording the decision is what derives the deadlines below. Until then every date has to be entered by hand.',
              })
        }
      >
        {decided ? (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            <div className="flex justify-between gap-3">
              <dt className="text-gray-500 dark:text-gray-400">{t('funding.field.decided_on', { defaultValue: 'Decided on' })}</dt>
              <dd className="tabular-nums">{date(application.decided_on)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-gray-500 dark:text-gray-400">{t('funding.field.award_reference', { defaultValue: 'Award reference' })}</dt>
              <dd>{application.award_reference || '—'}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-gray-500 dark:text-gray-400">{t('funding.field.approved', { defaultValue: 'Approved' })}</dt>
              <dd className="tabular-nums">{money(application.approved_amount)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-gray-500 dark:text-gray-400">{t('funding.field.period', { defaultValue: 'Award period' })}</dt>
              {/* Two dates and a separator: keep the browser from choosing
                  the middle of one of them as the place to break. */}
              <dd className="whitespace-nowrap tabular-nums">
                {application.award_period_start || application.award_period_end
                  ? `${date(application.award_period_start)} … ${date(application.award_period_end)}`
                  : '—'}
              </dd>
            </div>
            {application.conditions ? (
              <div className="sm:col-span-2">
                <dt className="text-gray-500 dark:text-gray-400">{t('funding.field.conditions', { defaultValue: 'Conditions' })}</dt>
                <dd className="whitespace-pre-line">{application.conditions}</dd>
              </div>
            ) : null}
            {application.rejection_reason ? (
              <div className="sm:col-span-2">
                <dt className="text-gray-500 dark:text-gray-400">{t('funding.field.rejection_reason', { defaultValue: 'Reason for rejection' })}</dt>
                <dd className="whitespace-pre-line">{application.rejection_reason}</dd>
              </div>
            ) : null}
          </dl>
        ) : (
          <div className="space-y-3">
            <div className="flex gap-2">
              {[true, false].map((approved) => (
                <button
                  key={String(approved)}
                  type="button"
                  onClick={() => setAwardApproved(approved)}
                  className={
                    awardApproved === approved
                      ? 'rounded border border-blue-600 bg-blue-50 px-3 py-1 text-sm text-blue-700 dark:bg-blue-950 dark:text-blue-300'
                      : 'rounded border border-gray-300 px-3 py-1 text-sm text-gray-600 dark:border-gray-600 dark:text-gray-300'
                  }
                >
                  {approved
                    ? t('funding.decision_approved', { defaultValue: 'Approved' })
                    : t('funding.decision_rejected', { defaultValue: 'Rejected' })}
                </button>
              ))}
            </div>
            {awardApproved ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Field
                  label={t('funding.field.award_reference', { defaultValue: 'Award reference' })}
                  value={awardDraft.award_reference}
                  onChange={(v) => setAwardDraft((p) => ({ ...p, award_reference: v }))}
                />
                {/* Labelled "Amount" rather than "Approved", because the
                    control above it is already the word Approved and two of
                    them in a column read as one question asked twice. */}
                <Field
                  label={t('funding.field.amount', { defaultValue: 'Amount' })}
                  value={awardDraft.approved_amount}
                  onChange={(v) => setAwardDraft((p) => ({ ...p, approved_amount: v }))}
                  mode="decimal"
                />
                <Field
                  label={t('funding.field.period_start', { defaultValue: 'Award period from' })}
                  value={awardDraft.award_period_start}
                  onChange={(v) => setAwardDraft((p) => ({ ...p, award_period_start: v }))}
                  type="date"
                />
                <Field
                  label={t('funding.field.period_end', { defaultValue: 'Award period to' })}
                  value={awardDraft.award_period_end}
                  onChange={(v) => setAwardDraft((p) => ({ ...p, award_period_end: v }))}
                  type="date"
                />
                <div className="sm:col-span-2 lg:col-span-4">
                  <Field
                    label={t('funding.field.conditions', { defaultValue: 'Conditions' })}
                    value={awardDraft.conditions}
                    onChange={(v) => setAwardDraft((p) => ({ ...p, conditions: v }))}
                  />
                </div>
              </div>
            ) : (
              <Field
                label={t('funding.field.rejection_reason', { defaultValue: 'Reason for rejection' })}
                value={awardDraft.rejection_reason}
                onChange={(v) => setAwardDraft((p) => ({ ...p, rejection_reason: v }))}
              />
            )}
            <Button
              onClick={() => awardMutation.mutate()}
              disabled={
                awardMutation.isPending || (!awardApproved && !awardDraft.rejection_reason.trim())
              }
            >
              {awardApproved
                ? t('funding.record_award', { defaultValue: 'Record the award' })
                : t('funding.record_rejection', { defaultValue: 'Record the rejection' })}
            </Button>
          </div>
        )}
      </Section>

      <Section
        icon={<Layers className="h-4 w-4" />}
        title={t('funding.allocations', { defaultValue: 'Eligible cost' })}
        hint={t('funding.allocations_hint', {
          defaultValue: 'What the programme counts and what it does not, with the reason for each.',
        })}
        action={
          <Button variant="secondary" size="sm" onClick={() => setShowAllocationForm((v) => !v)}>
            <Plus className="h-4 w-4" />
            {t('funding.new_allocation', { defaultValue: 'Add cost' })}
          </Button>
        }
      >
        {showAllocationForm ? (
          <div className="mb-3 grid grid-cols-1 gap-3 rounded border border-gray-200 p-3 dark:border-gray-700 sm:grid-cols-5">
            <Field
              label={t('funding.field.cost_group', { defaultValue: 'Cost group' })}
              value={allocationDraft.cost_group}
              onChange={(v) => setAllocationDraft((p) => ({ ...p, cost_group: v }))}
            />
            <Field
              label={t('common.description', { defaultValue: 'Description' })}
              value={allocationDraft.description}
              onChange={(v) => setAllocationDraft((p) => ({ ...p, description: v }))}
            />
            <Field
              label={t('funding.field.amount', { defaultValue: 'Amount' })}
              value={allocationDraft.amount}
              onChange={(v) => setAllocationDraft((p) => ({ ...p, amount: v }))}
              mode="decimal"
            />
            <Field
              label={t('funding.field.eligible_amount', { defaultValue: 'Of which eligible' })}
              value={allocationDraft.eligible_amount}
              onChange={(v) => setAllocationDraft((p) => ({ ...p, eligible_amount: v }))}
              mode="decimal"
            />
            <Field
              label={t('funding.field.eligibility', { defaultValue: 'Eligibility' })}
              value={allocationDraft.eligibility}
              onChange={() => undefined}
            >
              <select
                value={allocationDraft.eligibility}
                onChange={(e) =>
                  setAllocationDraft((p) => ({ ...p, eligibility: e.target.value as Eligibility }))
                }
                aria-label={t('funding.field.eligibility', { defaultValue: 'Eligibility' })}
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
              >
                {ELIGIBILITIES.map((value) => (
                  <option key={value} value={value}>
                    {t(`funding.eligibility.${value}`, { defaultValue: value })}
                  </option>
                ))}
              </select>
            </Field>
            <div className="sm:col-span-5">
              <Button
                size="sm"
                onClick={() => allocationMutation.mutate()}
                disabled={!allocationDraft.cost_group.trim() || allocationMutation.isPending}
              >
                {t('common.add', { defaultValue: 'Add' })}
              </Button>
            </div>
          </div>
        ) : null}

        {cost_allocations.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {t('funding.no_allocations', {
              defaultValue: 'No cost is split yet, so the eligible base is the figure entered by hand.',
            })}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-2 py-1">{t('funding.field.cost_group', { defaultValue: 'Cost group' })}</th>
                <th className="px-2 py-1">{t('common.description', { defaultValue: 'Description' })}</th>
                <th className="px-2 py-1 text-right">{t('funding.field.amount', { defaultValue: 'Amount' })}</th>
                <th className="px-2 py-1 text-right">{t('funding.field.eligible_amount', { defaultValue: 'Of which eligible' })}</th>
                <th className="px-2 py-1">{t('funding.field.eligibility', { defaultValue: 'Eligibility' })}</th>
              </tr>
            </thead>
            <tbody>
              {cost_allocations.map((row) => (
                <tr key={row.id} className="border-t border-gray-100 dark:border-gray-800">
                  <td className="px-2 py-1 font-medium">{row.cost_group}</td>
                  <td className="px-2 py-1 text-gray-600 dark:text-gray-300">{row.description || '—'}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{money(row.amount)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{money(row.eligible_amount)}</td>
                  <td className="px-2 py-1">
                    <Badge variant={eligibilityVariant(row.eligibility)} size="sm">
                      {t(`funding.eligibility.${row.eligibility}`, { defaultValue: row.eligibility })}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-gray-200 font-medium dark:border-gray-700">
                <td className="px-2 py-1" colSpan={2}>
                  {t('common.total', { defaultValue: 'Total' })}
                </td>
                <td className="px-2 py-1 text-right tabular-nums">{money(summary.allocated_amount)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{money(summary.allocated_eligible_amount)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        )}
      </Section>

      <Section
        icon={<Banknote className="h-4 w-4" />}
        title={t('funding.draws', { defaultValue: 'Draws' })}
        hint={t('funding.draws_hint', {
          defaultValue: 'Money asked for against spending already done, and the day it arrived.',
        })}
        action={
          <Button variant="secondary" size="sm" onClick={() => setShowDrawForm((v) => !v)} disabled={!decided}>
            <Plus className="h-4 w-4" />
            {t('funding.new_draw', { defaultValue: 'New draw' })}
          </Button>
        }
      >
        {showDrawForm ? (
          <div className="mb-3 grid grid-cols-1 gap-3 rounded border border-gray-200 p-3 dark:border-gray-700 sm:grid-cols-4">
            <Field
              label={t('funding.field.period_from', { defaultValue: 'Spending from' })}
              value={drawDraft.period_from}
              onChange={(v) => setDrawDraft((p) => ({ ...p, period_from: v }))}
              type="date"
            />
            <Field
              label={t('funding.field.period_to', { defaultValue: 'Spending to' })}
              value={drawDraft.period_to}
              onChange={(v) => setDrawDraft((p) => ({ ...p, period_to: v }))}
              type="date"
            />
            <Field
              label={t('funding.field.requested', { defaultValue: 'Requested' })}
              value={drawDraft.amount_requested}
              onChange={(v) => setDrawDraft((p) => ({ ...p, amount_requested: v }))}
              mode="decimal"
            />
            <Field
              label={t('common.notes', { defaultValue: 'Notes' })}
              value={drawDraft.notes}
              onChange={(v) => setDrawDraft((p) => ({ ...p, notes: v }))}
            />
            <div className="sm:col-span-4">
              <Button size="sm" onClick={() => drawMutation.mutate()} disabled={drawMutation.isPending}>
                {t('common.add', { defaultValue: 'Add' })}
              </Button>
            </div>
          </div>
        ) : null}

        {disbursements.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {decided
              ? t('funding.no_draws', { defaultValue: 'Nothing drawn yet against this award.' })
              : t('funding.no_draws_undecided', {
                  defaultValue: 'Nothing can be drawn before the decision is recorded.',
                })}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-2 py-1">{t('funding.field.code', { defaultValue: 'Reference' })}</th>
                {/* The draw's own spending period, which is a window inside
                    the award period and not the award period itself. */}
                <th className="px-2 py-1">{t('funding.field.spend_period', { defaultValue: 'Spending period' })}</th>
                <th className="px-2 py-1 text-right">{t('funding.field.requested', { defaultValue: 'Requested' })}</th>
                <th className="px-2 py-1 text-right">{t('funding.field.received', { defaultValue: 'Received' })}</th>
                <th className="px-2 py-1">{t('funding.field.spend_deadline', { defaultValue: 'Spend by' })}</th>
                <th className="px-2 py-1">{t('funding.field.status', { defaultValue: 'Status' })}</th>
                <th className="px-2 py-1" />
              </tr>
            </thead>
            <tbody>
              {disbursements.map((row: FundingDisbursement) => (
                <tr key={row.id} className="border-t border-gray-100 align-top dark:border-gray-800">
                  <td className="px-2 py-1 font-medium">{row.code || `#${row.sequence}`}</td>
                  {/* A range is two dates and a separator, and the browser
                      is free to break it anywhere. In a right-to-left page it
                      picks the middle of a date. */}
                  <td className="whitespace-nowrap px-2 py-1 tabular-nums text-gray-600 dark:text-gray-300">
                    {row.period_from || row.period_to ? `${date(row.period_from)} … ${date(row.period_to)}` : '—'}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">{money(row.amount_requested)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{money(row.amount_received)}</td>
                  <td className="px-2 py-1 tabular-nums text-gray-600 dark:text-gray-300">{date(row.spend_deadline_on)}</td>
                  <td className="px-2 py-1">
                    <Badge variant={drawVariant(row.status)} size="sm">
                      {t(`funding.draw_status.${row.status}`, { defaultValue: row.status })}
                    </Badge>
                  </td>
                  <td className="px-2 py-1">
                    {row.received_on ? (
                      // The column header is blank because it holds a button.
                      // Once the button is gone the date underneath it has
                      // nothing naming it, so it carries its own label.
                      <span className="block text-xs text-gray-500 dark:text-gray-400">
                        <span className="block">
                          {t('funding.field.received_on', { defaultValue: 'Received on' })}
                        </span>
                        <span className="block whitespace-nowrap tabular-nums">{date(row.received_on)}</span>
                      </span>
                    ) : receiptFor === row.id ? (
                      <div className="flex flex-wrap items-end gap-2">
                        <Field
                          label={t('funding.field.received_on', { defaultValue: 'Received on' })}
                          value={receiptOn}
                          onChange={setReceiptOn}
                          type="date"
                        />
                        <Field
                          label={t('funding.field.received', { defaultValue: 'Received' })}
                          value={receiptAmount}
                          onChange={setReceiptAmount}
                          mode="decimal"
                        />
                        <Button size="sm" onClick={() => receiptMutation.mutate(row.id)} disabled={receiptMutation.isPending}>
                          {t('common.confirm', { defaultValue: 'Confirm' })}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setReceiptFor(null)}>
                          {t('common.cancel', { defaultValue: 'Cancel' })}
                        </Button>
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setReceiptFor(row.id);
                          setReceiptOn(today);
                          setReceiptAmount(
                            declaresAmount(row.amount_approved)
                              ? row.amount_approved
                              : row.amount_requested,
                          );
                        }}
                      >
                        {t('funding.confirm_receipt', { defaultValue: 'Confirm receipt' })}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section
        icon={<FileCheck2 className="h-4 w-4" />}
        title={t('funding.proofs', { defaultValue: 'Proof of use' })}
        hint={t('funding.proofs_hint', {
          defaultValue: 'What the money was spent on, in the form the authority asks for, before the date it asks for it.',
        })}
        action={
          <Button variant="secondary" size="sm" onClick={() => setShowProofForm((v) => !v)}>
            <Plus className="h-4 w-4" />
            {t('funding.new_proof', { defaultValue: 'New report' })}
          </Button>
        }
      >
        {showProofForm ? (
          <div className="mb-3 grid grid-cols-1 gap-3 rounded border border-gray-200 p-3 dark:border-gray-700 sm:grid-cols-3">
            <Field
              label={t('funding.field.kind', { defaultValue: 'Kind' })}
              value={proofKind}
              onChange={() => undefined}
            >
              <select
                value={proofKind}
                onChange={(e) => setProofKind(e.target.value as ProofKind)}
                aria-label={t('funding.field.kind', { defaultValue: 'Kind' })}
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
              >
                {PROOF_KINDS.map((value) => (
                  <option key={value} value={value}>
                    {t(`funding.proof_kind.${value}`, { defaultValue: value })}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label={t('funding.field.due_on', { defaultValue: 'Due on' })}
              value={proofDue}
              onChange={setProofDue}
              type="date"
            />
            <div className="flex items-end">
              <Button size="sm" onClick={() => proofMutation.mutate()} disabled={proofMutation.isPending}>
                {t('common.add', { defaultValue: 'Add' })}
              </Button>
            </div>
          </div>
        ) : null}

        {proofs_of_use.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {t('funding.no_proofs', {
              defaultValue: 'No report drafted yet. The final one is due after the award period ends.',
            })}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-2 py-1">{t('funding.field.kind', { defaultValue: 'Kind' })}</th>
                <th className="px-2 py-1">{t('funding.field.due_on', { defaultValue: 'Due on' })}</th>
                <th className="px-2 py-1 text-right">{t('funding.field.spent', { defaultValue: 'Eligible costs spent' })}</th>
                <th className="px-2 py-1">{t('funding.field.status', { defaultValue: 'Status' })}</th>
                <th className="px-2 py-1">{t('funding.field.retention_until', { defaultValue: 'Keep until' })}</th>
                <th className="px-2 py-1" />
              </tr>
            </thead>
            <tbody>
              {proofs_of_use.map((row) => (
                <tr key={row.id} className="border-t border-gray-100 dark:border-gray-800">
                  <td className="px-2 py-1 font-medium">
                    {t(`funding.proof_kind.${row.kind}`, { defaultValue: row.kind })}
                  </td>
                  <td className="px-2 py-1 tabular-nums text-gray-600 dark:text-gray-300">{date(row.due_on)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{money(row.total_eligible_spent)}</td>
                  <td className="px-2 py-1">
                    <Badge variant={proofVariant(row.status)} size="sm">
                      {t(`funding.proof_status.${row.status}`, { defaultValue: row.status })}
                    </Badge>
                  </td>
                  <td className="px-2 py-1 tabular-nums text-gray-600 dark:text-gray-300">{date(row.retention_until)}</td>
                  <td className="px-2 py-1">
                    {row.accepted_on ? (
                      // Same blank header, same problem: a bare date under a
                      // column with no name tells the reader nothing.
                      <span className="block text-xs text-gray-500 dark:text-gray-400">
                        <span className="block">
                          {t('funding.field.accepted_on', { defaultValue: 'Accepted on' })}
                        </span>
                        <span className="block whitespace-nowrap tabular-nums">{date(row.accepted_on)}</span>
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => acceptMutation.mutate(row.id)}
                        disabled={acceptMutation.isPending}
                      >
                        {t('funding.accept_proof', { defaultValue: 'Mark accepted' })}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section
        icon={<CalendarClock className="h-4 w-4" />}
        title={t('funding.obligations', { defaultValue: 'Deadlines' })}
        hint={t('funding.obligations_hint', {
          defaultValue: 'Derived from the programme terms and the award notice. Closing one records the day it was done.',
        })}
      >
        {obligations.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
            <Info className="h-4 w-4" />
            {t('funding.no_obligations', {
              defaultValue: 'None yet. Recording the decision derives them from the programme terms.',
            })}
          </p>
        ) : (
          <ul className="divide-y divide-gray-100 dark:divide-gray-800">
            {obligations.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                <span className="tabular-nums text-gray-600 dark:text-gray-300">{date(row.due_on)}</span>
                <span className="min-w-0 flex-1">{obligationLabel(row, t, disbursements)}</span>
                <Badge variant="neutral" size="sm">
                  {t(`funding.obligation_source.${row.source}`, { defaultValue: row.source })}
                </Badge>
                {row.overdue ? (
                  <Badge variant="error" size="sm">
                    {t('funding.obligation_overdue', { defaultValue: 'Overdue' })}
                  </Badge>
                ) : null}
                {row.status === 'open' ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => obligationMutation.mutate(row.id)}
                    disabled={obligationMutation.isPending}
                  >
                    {t('funding.mark_done', { defaultValue: 'Mark done' })}
                  </Button>
                ) : (
                  <Badge variant="success" size="sm">
                    {t(`funding.obligation_status.${row.status}`, { defaultValue: row.status })}
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </Card>
  );
}
