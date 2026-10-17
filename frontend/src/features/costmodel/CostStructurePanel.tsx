// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CostStructurePanel - the project's cost structure as a tree with money.
//
// Each account shows the money planned on itself (own amount), what its cost
// lines carry (posted), and the total including its children. Money on cost
// lines that resolve to no postable account is listed below the tree as
// suspense, so the structure total never hides it. Findings of the structure
// rules arrive translated and are summarised as a traffic light.
//
// From here the structure is built (from a code list, or from a bill whose
// positions carry codes of a chosen list), custom code lists are uploaded,
// and an account's title, own amount and postability are edited.

import { Fragment, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronRight,
  FolderTree,
  Pencil,
  Upload,
  Trash2,
  ListTree,
  Check,
  X,
} from 'lucide-react';

import { Button, Card, ConfirmDialog, EmptyState, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { normalizeDecimalSeparators } from '@/shared/lib/parseDecimal';
import { useToastStore } from '@/stores/useToastStore';
import {
  costStructureApi,
  problemOf,
  type AccountPatch,
  type FindingSeverity,
  type StructureFinding,
  type StructureNode,
  type SuspenseBucket,
} from './structureApi';
import { problemMessage } from './problemMessages';
import { GenerateSpineButton } from './GenerateSpineButton';
import { CodeListImportModal } from './CodeListImportModal';

export interface CostStructurePanelProps {
  projectId: string;
  /** Project currency, used when the structure omits one. */
  currency?: string;
  /** Bill to generate from; omit for the project's latest bill. */
  boqId?: string;
}

const OWN_AMOUNT_RE = /^-?\d{1,16}(\.\d{1,2})?$/;

/** Deepest level the apply endpoint takes (`max_level` is at most 12). */
const MAX_APPLY_LEVEL = 12;

/** The worst severity among the findings, or null when there are none. */
export function worstSeverity(findings: readonly StructureFinding[]): FindingSeverity | null {
  if (findings.some((f) => f.severity === 'error')) return 'error';
  if (findings.some((f) => f.severity === 'warning')) return 'warning';
  if (findings.length > 0) return 'info';
  return null;
}

const LIGHT_CLASS: Record<FindingSeverity | 'ok', string> = {
  error: 'bg-semantic-error',
  warning: 'bg-amber-500',
  info: 'bg-oe-blue',
  ok: 'bg-semantic-success',
};

function TrafficLight({ findings }: { findings: StructureFinding[] }) {
  const { t } = useTranslation();
  const worst = worstSeverity(findings);
  const label =
    worst === 'error'
      ? t('costmodel.structure.light_error', { defaultValue: 'The structure has errors' })
      : worst === 'warning'
        ? t('costmodel.structure.light_warning', { defaultValue: 'The structure has warnings' })
        : worst === 'info'
          ? t('costmodel.structure.light_info', { defaultValue: 'The structure has notes' })
          : t('costmodel.structure.light_ok', { defaultValue: 'The structure passes its checks' });
  return (
    <div className="flex items-center gap-2" data-testid="structure-traffic-light" data-severity={worst ?? 'ok'}>
      <span className="flex items-center gap-1 rounded-full bg-surface-secondary px-1.5 py-1" aria-hidden="true">
        {(['error', 'warning', 'ok'] as const).map((slot) => {
          const lit = slot === 'ok' ? worst === null || worst === 'info' : worst === slot;
          return (
            <span
              key={slot}
              className={`h-2.5 w-2.5 rounded-full ${lit ? LIGHT_CLASS[slot] : 'bg-border'}`}
            />
          );
        })}
      </span>
      <span className="text-xs text-content-secondary">{label}</span>
    </div>
  );
}

function FindingsList({ findings }: { findings: StructureFinding[] }) {
  if (findings.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1" data-testid="structure-findings">
      {findings.map((f, i) => (
        <li key={`${f.rule_id}-${f.element_ref ?? ''}-${i}`} className="flex items-start gap-2 text-xs">
          <span
            className={`mt-1 h-2 w-2 shrink-0 rounded-full ${LIGHT_CLASS[f.severity]}`}
            aria-hidden="true"
          />
          <span className="text-content-primary">
            {f.message}
            {f.suggestion && <span className="ms-1 text-content-tertiary">{f.suggestion}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

interface EditState {
  id: string;
  title: string;
  ownAmount: string;
  postable: boolean;
}

function AccountEditor({
  edit,
  onChange,
  onSave,
  onCancel,
  saving,
  error,
}: {
  edit: EditState;
  onChange: (next: EditState) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  error: string | null;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-2 py-1">
      <input
        type="text"
        value={edit.title}
        maxLength={255}
        onChange={(e) => onChange({ ...edit, title: e.target.value })}
        aria-label={t('costmodel.structure.edit_title', { defaultValue: 'Title' })}
        className="h-7 min-w-[10rem] flex-1 rounded-md border border-border bg-surface-primary px-2 text-xs"
      />
      <input
        type="text"
        inputMode="decimal"
        value={edit.ownAmount}
        onChange={(e) => onChange({ ...edit, ownAmount: e.target.value })}
        aria-label={t('costmodel.structure.edit_own_amount', { defaultValue: 'Own amount' })}
        className="h-7 w-28 rounded-md border border-border bg-surface-primary px-2 text-end text-xs tabular-nums"
      />
      <label className="flex items-center gap-1 text-xs text-content-secondary">
        <input
          type="checkbox"
          checked={edit.postable}
          onChange={(e) => onChange({ ...edit, postable: e.target.checked })}
        />
        {t('costmodel.structure.edit_postable', { defaultValue: 'Cost lines may post here' })}
      </label>
      <Button size="sm" variant="primary" icon={<Check size={12} />} loading={saving} onClick={onSave}>
        {t('common.save', { defaultValue: 'Save' })}
      </Button>
      <Button size="sm" variant="ghost" icon={<X size={12} />} onClick={onCancel} disabled={saving}>
        {t('common.cancel', { defaultValue: 'Cancel' })}
      </Button>
      {error && (
        <span className="w-full text-xs text-semantic-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

function suspenseLabel(t: ReturnType<typeof useTranslation>['t'], bucket: SuspenseBucket): string {
  return bucket.kind === 'invalid_account'
    ? t('costmodel.structure.suspense_invalid_account', {
        defaultValue: 'Suspense: cost lines on a heading or closed account',
      })
    : t('costmodel.structure.suspense_no_account', {
        defaultValue: 'Suspense: cost lines on no account',
      });
}

export function CostStructurePanel({ projectId, currency, boqId }: CostStructurePanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const structureQuery = useQuery({
    queryKey: ['cost-structure', projectId],
    queryFn: () => costStructureApi.getStructure(projectId),
    enabled: !!projectId,
  });
  const listsQuery = useQuery({
    queryKey: ['code-lists', projectId],
    queryFn: () => costStructureApi.listCodeLists(projectId),
    enabled: !!projectId,
    staleTime: 5 * 60 * 1000,
  });

  const structure = structureQuery.data;
  // The server always lists both suspense buckets, empty ones included, so emptiness is
  // read from what they carry. An empty structure shows guidance, not a green light.
  const suspenseInUse = (structure?.suspense ?? []).filter((b) => b.line_count > 0 || Number(b.amount) !== 0);
  const structureEmpty = !structure || (structure.nodes.length === 0 && suspenseInUse.length === 0);
  const lists = useMemo(() => listsQuery.data ?? [], [listsQuery.data]);
  const resolvedCurrency = structure?.currency || currency || '';
  const money = (value: string) => formatCurrency(value, resolvedCurrency);

  // ── Build from code list / generate controls ──
  const [listKey, setListKey] = useState('');
  const [maxLevel, setMaxLevel] = useState('');
  const [importOpen, setImportOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const chosenKey = listKey || structure?.standards[0] || lists[0]?.key || '';
  const chosenList = lists.find((l) => l.key === chosenKey);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['cost-structure', projectId] });
    queryClient.invalidateQueries({ queryKey: ['spine', projectId] });
  };

  const failToast = (title: string, err: unknown) => {
    const problem = problemOf(err);
    addToast({
      type: 'error',
      title,
      message: problem ? problemMessage(t, problem.problem, problem.params) : getErrorMessage(err),
    });
  };

  const apply = useMutation({
    // The error is shown here in the user's language; the global toast would repeat it raw.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () =>
      costStructureApi.applyCodeList(projectId, chosenKey, maxLevel ? Number(maxLevel) : null),
    onSuccess: (result) => {
      addToast({
        type: 'success',
        title: t('costmodel.structure.applied_title', { defaultValue: 'Code list applied' }),
        message: t('costmodel.structure.applied_message', {
          defaultValue: 'Accounts added: {{accounts}}.',
          accounts: result.accounts_created,
        }),
      });
      invalidate();
    },
    onError: (err) =>
      failToast(t('costmodel.structure.apply_failed', { defaultValue: 'Could not apply the code list' }), err),
  });

  const removeList = useMutation({
    // The error is shown here in the user's language; the global toast would repeat it raw.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () => costStructureApi.deleteCodeList(projectId, chosenKey),
    onSuccess: () => {
      setConfirmDelete(false);
      setListKey('');
      queryClient.invalidateQueries({ queryKey: ['code-lists', projectId] });
      addToast({
        type: 'success',
        title: t('costmodel.structure.list_deleted', { defaultValue: 'Code list deleted' }),
      });
    },
    onError: (err) => {
      setConfirmDelete(false);
      failToast(t('costmodel.structure.list_delete_failed', { defaultValue: 'Could not delete the code list' }), err);
    },
  });

  // ── Tree expansion ──
  const childrenOf = useMemo(() => {
    const map = new Map<string | null, StructureNode[]>();
    const ids = new Set((structure?.nodes ?? []).map((n) => n.id));
    for (const n of structure?.nodes ?? []) {
      const parent = n.parent_id && ids.has(n.parent_id) ? n.parent_id : null;
      const bucket = map.get(parent);
      if (bucket) bucket.push(n);
      else map.set(parent, [n]);
    }
    return map;
  }, [structure?.nodes]);
  const [expanded, setExpanded] = useState<Set<string> | null>(null);
  const roots = childrenOf.get(null) ?? [];
  const openSet = expanded ?? new Set(roots.map((r) => r.id));
  const toggle = (id: string) => {
    const next = new Set(openSet);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  };
  const expandAll = () =>
    setExpanded(new Set((structure?.nodes ?? []).filter((n) => childrenOf.has(n.id)).map((n) => n.id)));
  const collapseAll = () => setExpanded(new Set());

  const visible: Array<{ node: StructureNode; depth: number }> = [];
  const seen = new Set<string>();
  const walk = (nodes: StructureNode[], depth: number) => {
    for (const node of nodes) {
      if (seen.has(node.id)) continue;
      seen.add(node.id);
      visible.push({ node, depth });
      if (openSet.has(node.id)) walk(childrenOf.get(node.id) ?? [], depth + 1);
    }
  };
  walk(roots, 0);

  // ── Account edit ──
  const [edit, setEdit] = useState<EditState | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const save = useMutation({
    // The error is shown here in the user's language; the global toast would repeat it raw.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: ({ id, patch }: { id: string; patch: AccountPatch }) =>
      costStructureApi.updateAccount(id, patch),
    onSuccess: () => {
      setEdit(null);
      setEditError(null);
      invalidate();
    },
    onError: (err) => {
      const problem = problemOf(err);
      setEditError(problem ? problemMessage(t, problem.problem, problem.params) : getErrorMessage(err));
    },
  });
  const startEdit = (node: StructureNode) => {
    setEditError(null);
    setEdit({
      id: node.id,
      title: node.title,
      ownAmount: node.own_amount,
      postable: node.is_leaf_postable,
    });
  };
  const submitEdit = () => {
    if (!edit) return;
    const raw = normalizeDecimalSeparators(edit.ownAmount.trim() || '0');
    if (!OWN_AMOUNT_RE.test(raw)) {
      setEditError(
        t('costmodel.structure.own_amount_invalid', {
          defaultValue: 'Enter the own amount as a number with at most two decimals.',
        }),
      );
      return;
    }
    save.mutate({
      id: edit.id,
      patch: { title: edit.title.trim(), own_amount: raw, is_leaf_postable: edit.postable },
    });
  };

  const columns = [
    t('costmodel.structure.col_code', { defaultValue: 'Code' }),
    t('costmodel.structure.col_title', { defaultValue: 'Title' }),
    t('costmodel.structure.col_own', { defaultValue: 'Own amount' }),
    t('costmodel.structure.col_posted', { defaultValue: 'Posted' }),
    t('costmodel.structure.col_total', { defaultValue: 'Total' }),
    t('costmodel.structure.col_lines', { defaultValue: 'Lines' }),
  ];

  const header = (
    <div className="flex flex-col gap-3 border-b border-border-light px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <FolderTree size={15} className="text-oe-blue" />
            {t('costmodel.structure.title', { defaultValue: 'Cost structure' })}
          </h3>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {t('costmodel.structure.subtitle', {
              defaultValue:
                'Accounts with their own amount, what their cost lines carry, and the total with children.',
            })}
          </p>
        </div>
        {structure && !structureEmpty && <TrafficLight findings={structure.findings} />}
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-2xs text-content-tertiary">
          {t('costmodel.structure.code_list', { defaultValue: 'Code list' })}
          <select
            value={chosenKey}
            onChange={(e) => {
              setListKey(e.target.value);
              // A level of one list means nothing in another.
              setMaxLevel('');
            }}
            className="h-8 min-w-[10rem] rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary"
            data-testid="structure-code-list"
          >
            {lists.length === 0 && !listsQuery.isLoading && !listsQuery.isError && (
              <option value="">{t('costmodel.structure.no_code_lists', { defaultValue: 'No code lists' })}</option>
            )}
            {lists.length === 0 && (listsQuery.isLoading || listsQuery.isError) && <option value="" />}
            {lists.map((l) => (
              <option key={l.key} value={l.key}>
                {l.name}
              </option>
            ))}
          </select>
          {listsQuery.isError && (
            <span className="flex items-center gap-1 text-semantic-error" role="alert" data-testid="structure-code-lists-error">
              {t('costmodel.structure.code_lists_failed', { defaultValue: 'The code lists could not be loaded.' })}
              <button type="button" className="text-oe-blue hover:underline" onClick={() => void listsQuery.refetch()}>
                {t('common.retry', { defaultValue: 'Retry' })}
              </button>
            </span>
          )}
        </label>
        <label className="flex flex-col gap-0.5 text-2xs text-content-tertiary">
          {t('costmodel.structure.max_level', { defaultValue: 'Down to level' })}
          <select
            value={maxLevel}
            onChange={(e) => setMaxLevel(e.target.value)}
            className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary"
          >
            <option value="">{t('costmodel.structure.all_levels', { defaultValue: 'All levels' })}</option>
            {Array.from({ length: Math.min(Math.max(chosenList?.depth ?? 0, 0), MAX_APPLY_LEVEL) }, (_, i) => i + 1).map((lvl) => (
              <option key={lvl} value={String(lvl)}>
                {lvl}
              </option>
            ))}
          </select>
        </label>
        <Button
          size="sm"
          variant="secondary"
          icon={<ListTree size={14} />}
          disabled={!chosenKey}
          loading={apply.isPending}
          onClick={() => apply.mutate()}
        >
          {t('costmodel.structure.apply_cta', { defaultValue: 'Build from code list' })}
        </Button>
        <GenerateSpineButton
          projectId={projectId}
          boqId={boqId}
          standard={chosenKey || undefined}
          currency={resolvedCurrency}
        />
        <Button size="sm" variant="ghost" icon={<Upload size={14} />} onClick={() => setImportOpen(true)}>
          {t('costmodel.structure.import_cta', { defaultValue: 'Import code list' })}
        </Button>
        {chosenList?.source === 'custom' && (
          <Button
            size="sm"
            variant="ghost"
            icon={<Trash2 size={14} />}
            onClick={() => setConfirmDelete(true)}
          >
            {t('costmodel.structure.delete_list_cta', { defaultValue: 'Delete code list' })}
          </Button>
        )}
      </div>
      {structure && <FindingsList findings={structure.findings} />}
    </div>
  );

  let body: React.ReactNode;
  if (structureQuery.isLoading) {
    body = (
      <div className="space-y-2 p-4">
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-2/3" />
      </div>
    );
  } else if (structureQuery.isError) {
    body = (
      <div className="p-4 text-sm text-semantic-error" role="alert">
        {getErrorMessage(structureQuery.error)}
      </div>
    );
  } else if (!structure || structureEmpty) {
    body = (
      <EmptyState
        icon={<FolderTree size={22} />}
        title={t('costmodel.structure.empty_title', { defaultValue: 'No cost structure yet' })}
        description={t('costmodel.structure.empty_body', {
          defaultValue: 'Build it from a code list, or generate it from a bill whose positions carry codes.',
        })}
      />
    );
  } else {
    body = (
      <div className="overflow-x-auto">
        <div className="flex justify-end gap-2 px-4 pt-2">
          <button type="button" className="text-2xs text-oe-blue hover:underline" onClick={expandAll}>
            {t('costmodel.structure.expand_all', { defaultValue: 'Expand all' })}
          </button>
          <button type="button" className="text-2xs text-oe-blue hover:underline" onClick={collapseAll}>
            {t('costmodel.structure.collapse_all', { defaultValue: 'Collapse all' })}
          </button>
        </div>
        <table className="w-full min-w-[720px] text-xs" data-testid="cost-structure-table">
          <thead>
            <tr className="border-b border-border-light text-2xs uppercase tracking-wide text-content-tertiary">
              {columns.map((c, i) => (
                <th key={c} className={`px-3 py-2 font-medium ${i >= 2 ? 'text-end' : 'text-start'}`}>
                  {c}
                </th>
              ))}
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {visible.map(({ node, depth }) => {
              const hasChildren = childrenOf.has(node.id);
              const isOpen = openSet.has(node.id);
              const editing = edit?.id === node.id;
              return (
                <Fragment key={node.id}>
                  <tr
                    className="border-b border-border-light/60 hover:bg-surface-secondary/50"
                    data-testid={`structure-row-${node.code}`}
                  >
                    <td className="whitespace-nowrap px-3 py-1.5 font-mono" style={{ paddingInlineStart: `${12 + depth * 16}px` }}>
                      {hasChildren ? (
                        <button
                          type="button"
                          onClick={() => toggle(node.id)}
                          aria-expanded={isOpen}
                          aria-label={
                            isOpen
                              ? t('costmodel.structure.collapse', { defaultValue: 'Collapse' })
                              : t('costmodel.structure.expand', { defaultValue: 'Expand' })
                          }
                          className="me-1 inline-flex h-4 w-4 items-center justify-center text-content-tertiary"
                        >
                          {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} className="rtl:rotate-180" />}
                        </button>
                      ) : (
                        <span className="me-1 inline-block w-4" />
                      )}
                      {node.code}
                    </td>
                    <td className="px-3 py-1.5 text-content-primary">
                      {editing && edit ? (
                        <AccountEditor
                          edit={edit}
                          onChange={setEdit}
                          onSave={submitEdit}
                          onCancel={() => {
                            setEdit(null);
                            setEditError(null);
                          }}
                          saving={save.isPending}
                          error={editError}
                        />
                      ) : (
                        <span className="inline-flex items-center gap-2">
                          {node.title || node.name}
                          {!node.is_leaf_postable && (
                            <span className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-tertiary">
                              {t('costmodel.structure.heading_badge', { defaultValue: 'Heading' })}
                            </span>
                          )}
                        </span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-end tabular-nums">{money(node.own_amount)}</td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-end tabular-nums">{money(node.posted)}</td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-end font-semibold tabular-nums">{money(node.total)}</td>
                    <td className="px-3 py-1.5 text-end tabular-nums text-content-secondary">{node.line_count}</td>
                    <td className="px-2 py-1.5">
                      {!editing && (
                        <button
                          type="button"
                          onClick={() => startEdit(node)}
                          aria-label={t('costmodel.structure.edit_account', { defaultValue: 'Edit account' })}
                          className="text-content-tertiary hover:text-oe-blue"
                        >
                          <Pencil size={12} />
                        </button>
                      )}
                    </td>
                  </tr>
                </Fragment>
              );
            })}
            {suspenseInUse.map((bucket) => (
              <tr
                key={bucket.kind}
                className="border-b border-border-light/60 bg-amber-50/60 dark:bg-amber-900/10"
                data-testid={`structure-suspense-${bucket.kind}`}
              >
                <td className="px-3 py-1.5 font-mono text-content-tertiary">-</td>
                <td className="px-3 py-1.5 font-medium text-amber-700 dark:text-amber-300">
                  {suspenseLabel(t, bucket)}
                </td>
                <td className="px-3 py-1.5" />
                <td className="whitespace-nowrap px-3 py-1.5 text-end tabular-nums">{money(bucket.amount)}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-end font-semibold tabular-nums">{money(bucket.amount)}</td>
                <td className="px-3 py-1.5 text-end tabular-nums text-content-secondary">{bucket.line_count}</td>
                <td />
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-border">
              <th colSpan={4} className="px-3 py-2 text-start text-xs font-semibold text-content-primary">
                {t('costmodel.structure.grand_total', { defaultValue: 'Total incl. suspense' })}
              </th>
              <td className="whitespace-nowrap px-3 py-2 text-end text-xs font-bold tabular-nums" data-testid="structure-total">
                {money(structure.total)}
              </td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>
    );
  }

  return (
    <Card padding="none" className="overflow-hidden" data-testid="cost-structure-panel">
      {header}
      {body}
      <CodeListImportModal
        open={importOpen}
        projectId={projectId}
        onClose={() => setImportOpen(false)}
        onImported={(key) => {
          setListKey(key);
          queryClient.invalidateQueries({ queryKey: ['code-lists', projectId] });
        }}
      />
      <ConfirmDialog
        open={confirmDelete}
        title={t('costmodel.structure.delete_list_title', { defaultValue: 'Delete this code list?' })}
        message={t('costmodel.structure.delete_list_message', {
          defaultValue: 'The list {{name}} is removed from this project. A list that accounts still use cannot be deleted.',
          name: chosenList?.name ?? chosenKey,
        })}
        confirmLabel={t('costmodel.structure.delete_list_cta', { defaultValue: 'Delete code list' })}
        loading={removeList.isPending}
        onConfirm={() => removeList.mutate()}
        onCancel={() => setConfirmDelete(false)}
      />
    </Card>
  );
}
