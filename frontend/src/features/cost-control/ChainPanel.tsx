// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The chain from the bill to the invoice, checked. Two halves:
//
// * Suspense: every contract line, order item, contract, change order item
//   and supplier invoice line that carries money and sits on no cost line,
//   in one bucket per kind. Each row can be put on a cost line right here,
//   and one button gives every row that can inherit an account the account
//   it inherits from the bill or its contract line.
// * Checks: the chain rules (contract sum against its schedule, approved
//   changes, commitments within target, measured quantities and value,
//   supplier invoices without a commitment). The sentences come from the
//   server in the reader's language. A supplier invoice without a contract
//   can be recorded as a direct cost on one account from its check.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertOctagon, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, Wand2 } from 'lucide-react';

import { Badge, Button, Skeleton } from '@/shared/ui';
import { fmtCurrency } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useToastStore } from '@/stores/useToastStore';
import { CostLinePicker } from '@/features/costmodel/CostLinePicker';
import { OverrideReasonDialog } from '@/features/costmodel/OverrideReasonDialog';
import { problemMessage } from '@/features/costmodel/problemMessages';
import { problemOf } from '@/features/costmodel/structureApi';
import {
  costControlApi,
  type AssignBody,
  type AssignKind,
  type ChainFinding,
  type SuspenseBucket,
  type SuspenseItem,
} from './api';

/** Rows shown per bucket before "show all". */
const PREVIEW_ROWS = 8;

export function bucketLabel(t: TFunction, kind: AssignKind): string {
  switch (kind) {
    case 'contract_line':
      return t('cost_control.chain.bucket_contract_line', { defaultValue: 'Contract lines' });
    case 'contract':
      return t('cost_control.chain.bucket_contract', { defaultValue: 'Contracts without a schedule' });
    case 'po_item':
      return t('cost_control.chain.bucket_po_item', { defaultValue: 'Purchase order items' });
    case 'change_order_item':
      return t('cost_control.chain.bucket_change_order_item', { defaultValue: 'Change order items' });
    case 'invoice_line':
      return t('cost_control.chain.bucket_invoice_line', { defaultValue: 'Supplier invoice lines' });
    default:
      return kind;
  }
}

function errorText(t: TFunction, err: unknown): string {
  const problem = problemOf(err);
  return problem ? problemMessage(t, problem.problem, problem.params) : getErrorMessage(err);
}

function SeverityIcon({ severity }: { severity: ChainFinding['severity'] }) {
  if (severity === 'error') return <AlertOctagon size={16} className="mt-0.5 shrink-0 text-semantic-error" />;
  if (severity === 'warning') return <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-500" />;
  return <Info size={16} className="mt-0.5 shrink-0 text-sky-500" />;
}

function Bucket({
  bucket,
  projectId,
  currency,
  canEdit,
  busy,
  onPut,
}: {
  bucket: SuspenseBucket;
  projectId: string;
  currency: string;
  canEdit: boolean;
  busy: boolean;
  onPut: (item: SuspenseItem, costLineId: string) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? bucket.items : bucket.items.slice(0, PREVIEW_ROWS);
  return (
    <section className="rounded-xl border border-border-light" data-testid={`suspense-${bucket.kind}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-2 px-4 py-2.5 text-left hover:bg-surface-secondary/40"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="text-sm font-medium text-content-primary">{bucketLabel(t, bucket.kind)}</span>
        <Badge variant="neutral" size="sm">
          {bucket.count}
        </Badge>
        {bucket.inheritable > 0 && (
          <span className="text-xs text-content-tertiary">
            {t('cost_control.chain.inheritable', {
              defaultValue: '{{n}} can take an account from the bill',
              n: bucket.inheritable,
            })}
          </span>
        )}
        <span className="ms-auto text-sm tabular-nums text-content-secondary">{fmtCurrency(bucket.amount, currency)}</span>
      </button>
      {open && (
        <div className="border-t border-border-light">
          <p className="px-4 pt-2 text-xs text-content-tertiary">
            {bucket.in_report
              ? t('cost_control.chain.in_report', {
                  defaultValue: 'This money is in the "not on any cost line" row of the report.',
                })
              : t('cost_control.chain.not_in_report', {
                  defaultValue:
                    'Shown for completeness: this money reaches the report through the contract lines it is posted to.',
                })}
          </p>
          <ul className="divide-y divide-border-light">
            {rows.map((item) => (
              <li key={`${item.kind}-${item.id}`} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-content-primary">
                    {item.code && <span className="me-2 font-mono text-xs text-content-tertiary">{item.code}</span>}
                    {item.description || '-'}
                  </div>
                  <div className="truncate text-xs text-content-tertiary">
                    {`${item.group_code} ${item.group_title}`.trim()}
                  </div>
                </div>
                <span className="shrink-0 text-sm tabular-nums text-content-secondary">
                  {fmtCurrency(item.amount, currency)}
                </span>
                {canEdit && (
                  <div className="w-56 max-w-full">
                    <CostLinePicker
                      projectId={projectId}
                      value=""
                      onChange={(v) => v && onPut(item, v)}
                      disabled={busy}
                      data-testid={`suspense-put-${item.id}`}
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>
          {bucket.items.length > PREVIEW_ROWS && (
            <button
              type="button"
              className="px-4 pb-2.5 text-xs font-medium text-oe-blue hover:underline"
              onClick={() => setShowAll((v) => !v)}
            >
              {showAll
                ? t('cost_control.findings_less', { defaultValue: 'Show fewer' })
                : t('cost_control.findings_more', { defaultValue: 'Show all ({{n}})', n: bucket.items.length })}
            </button>
          )}
          {bucket.count > bucket.items.length && (
            <p className="px-4 pb-2.5 text-xs text-content-tertiary">
              {t('cost_control.chain.more_rows', {
                defaultValue: 'The first {{shown}} of {{total}} rows are listed. Put these on cost lines to see the rest.',
                shown: bucket.items.length,
                total: bucket.count,
              })}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function DirectCostAction({ projectId, finding, busy, onRecord }: {
  projectId: string;
  finding: ChainFinding;
  busy: boolean;
  onRecord: (invoiceId: string, costLineId: string) => void;
}) {
  const { t } = useTranslation();
  const invoiceId = finding.element_ref;
  if (!invoiceId) return null;
  return (
    <div className="mt-1.5 w-64 max-w-full">
      <CostLinePicker
        projectId={projectId}
        value=""
        onChange={(v) => v && onRecord(invoiceId, v)}
        disabled={busy}
        placeholder={t('cost_control.chain.direct_cost', { defaultValue: 'Record as direct cost on...' })}
        data-testid={`direct-cost-${invoiceId}`}
      />
    </div>
  );
}

export interface ChainPanelProps {
  projectId: string;
  currency: string;
  canEdit: boolean;
}

export function ChainPanel({ projectId, currency, canEdit }: ChainPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const canCreateContracts = useHasPermission('contracts.create');
  const [askReason, setAskReason] = useState<AssignBody | null>(null);

  const chain = useQuery({
    queryKey: ['cost-control', 'chain', projectId],
    queryFn: () => costControlApi.chain(projectId),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['cost-control'] });

  const assign = useMutation({
    mutationFn: (body: AssignBody) => costControlApi.assign(projectId, body),
    onSuccess: () => {
      setAskReason(null);
      refresh();
      addToast({ type: 'success', title: t('cost_control.assign_saved', { defaultValue: 'Put on the cost line' }) });
    },
    onError: (err, body) => {
      if (problemOf(err)?.problem === 'override_reason_required' && !body.reason) {
        setAskReason(body);
        return;
      }
      addToast({
        type: 'error',
        title: t('cost_control.assign_failed', { defaultValue: 'Could not put it on the cost line' }),
        message: errorText(t, err),
      });
    },
  });

  const inherit = useMutation({
    mutationFn: () => costControlApi.inheritAll(projectId),
    onSuccess: (res) => {
      refresh();
      const n = res.contract_line + res.change_order_item + res.invoice_line;
      addToast({
        type: 'success',
        title: t('cost_control.chain.inherited', {
          defaultValue: '{{n}} rows took their account from the bill',
          n,
        }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('cost_control.chain.inherit_failed', { defaultValue: 'Could not take the accounts over' }),
        message: errorText(t, err),
      }),
  });

  const direct = useMutation({
    mutationFn: ({ invoiceId, costLineId }: { invoiceId: string; costLineId: string }) =>
      costControlApi.directCost(projectId, invoiceId, costLineId),
    onSuccess: (res) => {
      refresh();
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      addToast({
        type: 'success',
        title: t('cost_control.chain.direct_cost_saved', {
          defaultValue: 'Recorded as direct cost contract {{code}}',
          code: res.contract_code,
        }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('cost_control.chain.direct_cost_failed', { defaultValue: 'Could not record the direct cost' }),
        message: errorText(t, err),
      }),
  });

  const busy = assign.isPending || inherit.isPending || direct.isPending;
  const buckets = (chain.data?.buckets ?? []).filter((b) => b.count > 0);
  const findings = chain.data?.findings ?? [];
  const inheritable = buckets.reduce((n, b) => n + b.inheritable, 0);

  return (
    <div className="space-y-4" data-testid="chain-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('cost_control.chain.title', { defaultValue: 'From the bill to the invoice' })}
          </h2>
          <p className="text-xs text-content-tertiary">
            {t('cost_control.chain.subtitle', {
              defaultValue:
                'Contracts, changes and invoices take their cost line from the bill. What is left on no cost line, and what does not add up, is listed here.',
            })}
          </p>
        </div>
        {canEdit && inheritable > 0 && (
          <Button
            variant="secondary"
            size="sm"
            icon={<Wand2 size={14} />}
            onClick={() => inherit.mutate()}
            disabled={busy}
            data-testid="chain-inherit-all"
          >
            {t('cost_control.chain.inherit_all', {
              defaultValue: 'Take accounts from the bill ({{n}})',
              n: inheritable,
            })}
          </Button>
        )}
      </div>

      {chain.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : chain.error ? (
        <p className="text-sm text-semantic-error">{getErrorMessage(chain.error)}</p>
      ) : buckets.length === 0 && findings.length === 0 ? (
        <div className="flex items-center gap-2 text-sm text-content-secondary">
          <CheckCircle2 size={16} className="text-semantic-success" />
          {t('cost_control.chain.all_clear', {
            defaultValue: 'Everything is on a cost line and the chain checks pass.',
          })}
        </div>
      ) : (
        <>
          {buckets.length > 0 && (
            <div className="space-y-2">
              {buckets.map((b) => (
                <Bucket
                  key={b.kind}
                  bucket={b}
                  projectId={projectId}
                  currency={currency}
                  canEdit={canEdit}
                  busy={busy}
                  onPut={(item, costLineId) =>
                    assign.mutate({ cost_line_id: costLineId, items: [{ kind: item.kind, id: item.id }] })
                  }
                />
              ))}
            </div>
          )}
          {findings.length > 0 && (
            <ul className="space-y-2" data-testid="chain-findings">
              {findings.map((f, i) => (
                <li key={`${f.rule_id}-${f.element_ref ?? i}-${f.details.problem ?? ''}`} className="flex gap-3 px-2 py-1">
                  <SeverityIcon severity={f.severity} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-content-primary">{f.message}</p>
                    {f.suggestion && <p className="text-xs text-content-tertiary">{f.suggestion}</p>}
                    {f.rule_id === 'cost_chain.invoice_has_contract' && canEdit && canCreateContracts && (
                      <DirectCostAction
                        projectId={projectId}
                        finding={f}
                        busy={busy}
                        onRecord={(invoiceId, costLineId) => direct.mutate({ invoiceId, costLineId })}
                      />
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <OverrideReasonDialog
        open={askReason !== null}
        busy={assign.isPending}
        onCancel={() => setAskReason(null)}
        onConfirm={(reason) => askReason && assign.mutate({ ...askReason, reason })}
      />
    </div>
  );
}
