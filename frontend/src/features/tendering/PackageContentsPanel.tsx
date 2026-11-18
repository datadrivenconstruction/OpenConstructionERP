// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What a tender package contains, before it goes out: the lines the bidders
 * price with the budget beside each, the cost components of every line (which
 * of them the package covers and which the owner supplies), the package budget
 * (computed sum and a hand-entered figure), the documents and the invited firms.
 */

import { Fragment, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ChevronDown, ChevronRight, FileText, Users } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import { fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  SCOPE_KINDS,
  getPackagePreview,
  packagePreviewQueryKey,
  patchPackageBudget,
  type PackagePreview,
  type PackagePreviewLine,
  type ScopeKind,
} from './api';

type Translate = (k: string, o?: Record<string, unknown>) => string;

export function scopeKindLabel(kind: string, t: Translate): string {
  switch (kind) {
    case 'labor':
      return t('tendering.contents.kind_labor', { defaultValue: 'Labour' });
    case 'material':
      return t('tendering.contents.kind_material', { defaultValue: 'Material' });
    case 'machinery':
      return t('tendering.contents.kind_machinery', { defaultValue: 'Machinery' });
    case 'equipment':
      return t('tendering.contents.kind_equipment', { defaultValue: 'Equipment' });
    case 'subcontractor':
      return t('tendering.contents.kind_subcontractor', { defaultValue: 'Subcontract' });
    default:
      return t('tendering.contents.kind_other', { defaultValue: 'Other' });
  }
}

/** The excluded component keys per line, as the preview reports them. */
export function excludedFromPreview(preview: PackagePreview): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const line of preview.lines) {
    const keys = line.components
      .filter((c) => !c.included && preview.scope_kinds.includes(c.kind))
      .map((c) => c.key);
    if (keys.length) out[line.id] = keys;
  }
  return out;
}

/** Whether a decimal string is a usable, non-negative amount. */
export function isBudgetInput(value: string): boolean {
  const v = value.trim().replace(',', '.');
  return v !== '' && /^\d+(\.\d+)?$/.test(v);
}

export function PackageContentsPanel({
  packageId,
  editable,
}: {
  packageId: string;
  /** False once the package is awarded or closed: budget and scope are fixed. */
  editable: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [overrideText, setOverrideText] = useState('');
  const [kinds, setKinds] = useState<Set<ScopeKind>>(new Set(SCOPE_KINDS));
  const [excluded, setExcluded] = useState<Record<string, string[]>>({});
  const [scopeDirty, setScopeDirty] = useState(false);

  const previewQ = useQuery({
    queryKey: packagePreviewQueryKey(packageId),
    queryFn: () => getPackagePreview(packageId),
  });
  const preview = previewQ.data;

  useEffect(() => {
    if (!preview) return;
    setOverrideText(preview.budget_override ?? '');
    setKinds(new Set(preview.scope_kinds));
    setExcluded(excludedFromPreview(preview));
    setScopeDirty(false);
  }, [preview]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: packagePreviewQueryKey(packageId) });
    queryClient.invalidateQueries({ queryKey: ['tendering-comparison', packageId] });
    queryClient.invalidateQueries({ queryKey: ['tendering-package', packageId] });
  };

  const budgetMutation = useMutation({
    mutationFn: (value: string | null) => patchPackageBudget(packageId, { budget_override: value }),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('tendering.contents.budget_saved', { defaultValue: 'Budget saved' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const scopeMutation = useMutation({
    mutationFn: () =>
      patchPackageBudget(packageId, {
        resource_scope: { kinds: SCOPE_KINDS.filter((k) => kinds.has(k)), excluded },
      }),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('tendering.contents.scope_saved', { defaultValue: 'Scope saved' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const kindCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const line of preview?.lines ?? []) {
      for (const c of line.components) counts.set(c.kind, (counts.get(c.kind) ?? 0) + 1);
    }
    return counts;
  }, [preview]);

  if (previewQ.isLoading) return <SkeletonTable rows={5} columns={5} />;
  if (previewQ.isError || !preview) {
    return (
      <Card className="py-10">
        <EmptyState
          icon={<AlertTriangle size={24} strokeWidth={1.5} />}
          title={t('common.error', { defaultValue: 'Error' })}
          description={t('tendering.contents.load_error', {
            defaultValue: 'Failed to load the package contents. Please try again.',
          })}
        />
      </Card>
    );
  }

  const currency = preview.currency;
  const money = (v: string | null | undefined) => (v == null ? '' : formatCurrency(v, currency));

  const toggleKind = (kind: ScopeKind) => {
    const next = new Set(kinds);
    if (next.has(kind)) next.delete(kind);
    else next.add(kind);
    if (next.size === 0) return;
    setKinds(next);
    setScopeDirty(true);
  };

  const toggleComponent = (lineId: string, key: string) => {
    const current = new Set(excluded[lineId] ?? []);
    if (current.has(key)) current.delete(key);
    else current.add(key);
    const next = { ...excluded };
    if (current.size) next[lineId] = [...current];
    else delete next[lineId];
    setExcluded(next);
    setScopeDirty(true);
  };

  const toggleOpen = (lineId: string) => {
    const next = new Set(open);
    if (next.has(lineId)) next.delete(lineId);
    else next.add(lineId);
    setOpen(next);
  };

  const componentIncluded = (line: PackagePreviewLine, key: string, kind: string) =>
    kinds.has(kind as ScopeKind) && !(excluded[line.id] ?? []).includes(key);

  return (
    <div className="space-y-4" data-testid="package-contents">
      {preview.validation.length > 0 && (
        <Card className="border border-semantic-warning/30 bg-semantic-warning-bg/20">
          <ul className="space-y-1 text-xs text-content-secondary" data-testid="package-contents-issues">
            {preview.validation.map((v, i) => (
              <li key={`${v.rule_id}-${i}`} className="flex items-start gap-2">
                <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
                <span>
                  {v.message}
                  {v.suggestion ? ` - ${v.suggestion}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Budget: the computed sum stays visible beside the figure in force. */}
      <Card>
        <div className="flex flex-wrap items-end gap-6">
          <div>
            <p className="text-xs text-content-tertiary">
              {t('tendering.contents.budget_computed', { defaultValue: 'Computed from the lines' })}
            </p>
            <p className="text-lg font-semibold tabular-nums text-content-primary" data-testid="budget-computed">
              {money(preview.budget_computed)}
            </p>
          </div>
          <div>
            <p className="text-xs text-content-tertiary">
              {t('tendering.contents.budget_in_force', { defaultValue: 'Budget in force' })}
            </p>
            <p className="text-lg font-semibold tabular-nums text-content-primary" data-testid="budget-in-force">
              {money(preview.budget_total)}
              {preview.budget_override != null && (
                <Badge variant="blue" size="sm" className="ml-2 align-middle">
                  {t('tendering.contents.budget_entered', { defaultValue: 'Entered by hand' })}
                </Badge>
              )}
            </p>
          </div>
          {editable && (
            <div className="flex items-end gap-2">
              <label className="block">
                <span className="mb-1 block text-xs text-content-secondary">
                  {t('tendering.contents.budget_override', { defaultValue: 'Enter a budget' })}
                  {currency ? ` (${currency})` : ''}
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={overrideText}
                  onChange={(e) => setOverrideText(e.target.value)}
                  className="oe-input oe-input-sm w-40 tabular-nums"
                  data-testid="budget-override-input"
                />
              </label>
              <Button
                size="sm"
                variant="secondary"
                disabled={!isBudgetInput(overrideText)}
                loading={budgetMutation.isPending}
                onClick={() => budgetMutation.mutate(overrideText.trim().replace(',', '.'))}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
              {preview.budget_override != null && (
                <Button
                  size="sm"
                  variant="ghost"
                  loading={budgetMutation.isPending}
                  onClick={() => budgetMutation.mutate(null)}
                  title={t('tendering.contents.budget_clear_hint', {
                    defaultValue: 'Use the sum of the lines again',
                  })}
                >
                  {t('tendering.contents.budget_clear', { defaultValue: 'Use computed' })}
                </Button>
              )}
            </div>
          )}
        </div>
      </Card>

      {/* Scope by cost kind: what the subcontractor prices on each line. */}
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-content-primary">
            {t('tendering.contents.scope_title', { defaultValue: 'Cost components in this package' })}
          </span>
          {SCOPE_KINDS.map((kind) => (
            <label
              key={kind}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2 py-1 text-xs text-content-secondary"
            >
              <input
                type="checkbox"
                checked={kinds.has(kind)}
                disabled={!editable}
                onChange={() => toggleKind(kind)}
                data-testid={`scope-kind-${kind}`}
              />
              {scopeKindLabel(kind, t)}
              <span className="text-content-tertiary">{kindCounts.get(kind) ?? 0}</span>
            </label>
          ))}
          {editable && (
            <Button
              size="sm"
              variant="primary"
              disabled={!scopeDirty}
              loading={scopeMutation.isPending}
              onClick={() => scopeMutation.mutate()}
              data-testid="scope-save"
            >
              {t('tendering.contents.scope_save', { defaultValue: 'Save scope' })}
            </Button>
          )}
        </div>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('tendering.contents.scope_hint', {
            defaultValue:
              'Untick a kind, or open a line and untick a component, when someone else supplies it (for example materials the owner buys). The bidder sees what is supplied by others, and the budget keeps only what the package covers.',
          })}
        </p>
      </Card>

      {/* The lines, as the bidder link shows them, with the budget beside each. */}
      <Card padding="none">
        <div className="flex items-center justify-between px-4 py-3">
          <h4 className="text-sm font-semibold text-content-primary">
            {t('tendering.contents.lines_title', {
              defaultValue: 'Lines to price: {{n}}',
              n: preview.item_count,
            })}
          </h4>
        </div>
        {preview.lines.length === 0 ? (
          <div className="px-4 pb-4 text-sm text-content-tertiary">
            {t('tendering.contents.no_lines', { defaultValue: 'This package has no lines to price yet.' })}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-y border-border-light text-left text-xs text-content-tertiary">
                  <th className="w-8 px-2 py-2" />
                  <th className="px-2 py-2">{t('tendering.contents.col_ordinal', { defaultValue: 'No.' })}</th>
                  <th className="px-2 py-2">{t('tendering.contents.col_text', { defaultValue: 'Description' })}</th>
                  <th className="px-2 py-2 text-right">{t('tendering.contents.col_qty', { defaultValue: 'Quantity' })}</th>
                  <th className="px-2 py-2">{t('tendering.contents.col_unit', { defaultValue: 'Unit' })}</th>
                  <th className="px-2 py-2 text-right">
                    {t('tendering.contents.col_budget_rate', { defaultValue: 'Budget rate' })}
                  </th>
                  <th className="px-2 py-2 text-right">
                    {t('tendering.contents.col_budget_total', { defaultValue: 'Budget total' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {preview.lines.map((line) =>
                  line.kind === 'section' ? (
                    <tr key={line.id} className="bg-surface-secondary/50">
                      <td />
                      <td className="px-2 py-1.5 text-xs font-semibold text-content-secondary">{line.ordinal}</td>
                      <td colSpan={5} className="px-2 py-1.5 text-xs font-semibold text-content-secondary">
                        {line.short_text}
                      </td>
                    </tr>
                  ) : (
                    <Fragment key={line.id}>
                      <tr className="border-b border-border-light/60">
                        <td className="px-2 py-1.5">
                          {line.components.length > 0 && (
                            <button
                              type="button"
                              onClick={() => toggleOpen(line.id)}
                              className="rounded p-0.5 text-content-tertiary hover:text-content-primary"
                              aria-label={t('tendering.contents.show_components', { defaultValue: 'Show components' })}
                              aria-expanded={open.has(line.id)}
                              data-testid={`line-toggle-${line.id}`}
                            >
                              {open.has(line.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            </button>
                          )}
                        </td>
                        <td className="px-2 py-1.5 tabular-nums text-content-secondary">{line.ordinal}</td>
                        <td className="px-2 py-1.5 text-content-primary">
                          {line.short_text}
                          {line.supplied_by_others.length > 0 && (
                            <span className="block text-xs text-content-tertiary">
                              {t('tendering.contents.supplied_by_others', {
                                defaultValue: 'Supplied by others: {{items}}',
                                items: line.supplied_by_others.join(', '),
                              })}
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{fmtNumber(Number(line.quantity || 0))}</td>
                        <td className="px-2 py-1.5 text-content-secondary">{line.unit}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{money(line.budget_rate)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums font-medium">{money(line.budget_total)}</td>
                      </tr>
                      {open.has(line.id) &&
                        line.components.map((c) => (
                          <tr key={`${line.id}-${c.key}`} className="text-xs text-content-secondary">
                            <td />
                            <td />
                            <td className="px-2 py-1" colSpan={3}>
                              <label className="inline-flex items-center gap-2">
                                <input
                                  type="checkbox"
                                  checked={componentIncluded(line, c.key, c.kind)}
                                  disabled={!editable || !kinds.has(c.kind)}
                                  onChange={() => toggleComponent(line.id, c.key)}
                                  data-testid={`component-${line.id}-${c.key}`}
                                />
                                <Badge variant="neutral" size="sm">
                                  {scopeKindLabel(c.kind, t)}
                                </Badge>
                                <span>{c.name}</span>
                                <span className="text-content-tertiary">
                                  {fmtNumber(Number(c.quantity || 0))} {c.unit}
                                </span>
                              </label>
                            </td>
                            <td className="px-2 py-1 text-right tabular-nums">{money(c.unit_cost)}</td>
                            <td />
                          </tr>
                        ))}
                    </Fragment>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Users size={16} className="text-oe-blue" />
            {t('tendering.contents.recipients_title', { defaultValue: 'Invited firms' })}
          </h4>
          {preview.recipients.length === 0 ? (
            <p className="text-xs text-content-tertiary">
              {t('tendering.contents.no_recipients', {
                defaultValue: 'Nobody is invited yet. Add firms on the Distribution tab.',
              })}
            </p>
          ) : (
            <ul className="space-y-1 text-sm">
              {preview.recipients.map((r) => (
                <li key={r.email} className="flex items-center justify-between gap-2">
                  <span className="truncate">
                    {r.company_name} <span className="text-xs text-content-tertiary">{r.email}</span>
                  </span>
                  <Badge variant={r.status === 'sent' ? 'success' : 'neutral'} size="sm">
                    {r.status === 'sent'
                      ? t('tendering.recipient_sent', { defaultValue: 'Sent' })
                      : t('tendering.contents.not_sent', { defaultValue: 'Not sent' })}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-content-primary">
            <FileText size={16} className="text-oe-blue" />
            {t('tendering.contents.documents_title', { defaultValue: 'Documents' })}
          </h4>
          {preview.documents.length === 0 ? (
            <p className="text-xs text-content-tertiary">
              {t('tendering.contents.no_documents', {
                defaultValue:
                  'No documents issued yet. The bill goes out as Excel, GAEB or PDF from the buttons above; drawings and specifications are issued with an addendum.',
              })}
            </p>
          ) : (
            <ul className="space-y-1 text-sm">
              {preview.documents.map((d, i) => (
                <li key={`${d.addendum_revision}-${d.document_id ?? i}`} className="flex items-center justify-between gap-2">
                  <span className="truncate">
                    {[d.drawing_number, d.title].filter(Boolean).join(' ')}
                    {d.revision ? ` (${d.revision})` : ''}
                  </span>
                  <span className="shrink-0 text-xs text-content-tertiary">
                    {t('tendering.contents.document_addendum', {
                      defaultValue: 'Addendum {{n}}',
                      n: d.addendum_revision,
                    })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
