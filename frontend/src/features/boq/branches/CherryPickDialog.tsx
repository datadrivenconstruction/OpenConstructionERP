// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CherryPickDialog — carry changed positions from one branch into another, or
 * merge a branch back into its main estimate.
 *
 * The server previews the plan; a position the target changed too is shown
 * with all three versions (fork point, source, target) and must be decided
 * before anything is written. The target is snapshotted first, so the
 * version history can undo the whole operation.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, GitMerge, GitPullRequestArrow, Loader2, X } from 'lucide-react';
import clsx from 'clsx';
import { Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { branchApi, type BranchNode, type PlanItem, type Resolution } from './branchApi';
import { planValueText, resolutionsFor, undecidedConflicts, withRequiredParents } from './branchHelpers';

export type CherryPickMode = 'cherry-pick' | 'merge';

export interface CherryPickDialogProps {
  mode: CherryPickMode;
  nodes: BranchNode[];
  /** The bill that receives the changes (cherry-pick) or the branch being merged (merge). */
  currentBoqId: string;
  isOpen: boolean;
  onClose: () => void;
  onApplied: (targetBoqId: string) => void;
}

export function CherryPickDialog({ mode, nodes, currentBoqId, isOpen, onClose, onApplied }: CherryPickDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isMerge = mode === 'merge';
  const mainId = nodes.find((n) => n.is_main)?.boq_id ?? '';
  const [sourceId, setSourceId] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [resolutions, setResolutions] = useState<Record<string, Resolution>>({});
  const [includeMarkups, setIncludeMarkups] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const targetId = isMerge ? mainId : currentBoqId;
  const effectiveSource = isMerge ? currentBoqId : sourceId;

  useEffect(() => {
    if (!isOpen) return;
    setSourceId('');
    setResolutions({});
    setIncludeMarkups(false);
    setConfirmed(false);
  }, [isOpen, mode]);

  useEffect(() => {
    if (!isOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener('keydown', onKey, { capture: true });
    return () => document.removeEventListener('keydown', onKey, { capture: true });
  }, [isOpen, onClose]);

  const enabled = isOpen && !!effectiveSource && !!targetId && effectiveSource !== targetId;
  const { data: plan, isLoading, isError, error } = useQuery({
    queryKey: ['boq-branch-plan', effectiveSource, targetId],
    queryFn: () => branchApi.plan(targetId, effectiveSource),
    enabled,
    retry: false,
  });

  useEffect(() => {
    setSelected(new Set((plan?.items ?? []).map((i) => i.key)));
    setResolutions({});
  }, [plan]);

  const items = plan?.items ?? [];
  const pending = useMemo(() => undecidedConflicts(items, selected, resolutions), [items, selected, resolutions]);

  const toggle = (item: PlanItem) => {
    // A merge carries every change; only a cherry-pick chooses lines.
    if (isMerge) return;
    setSelected((prev) => {
      if (prev.has(item.key)) {
        const next = new Set(prev);
        next.delete(item.key);
        // A child that needs this new section cannot stay without it.
        for (const other of items) if (other.parent_key === item.key && item.action === 'add') next.delete(other.key);
        return next;
      }
      return new Set([...prev, ...withRequiredParents(items, [item.key])]);
    });
  };

  const mutation = useMutation({
    mutationFn: () =>
      isMerge
        ? branchApi.merge(currentBoqId, resolutionsFor(selected, resolutions), includeMarkups)
        : branchApi.cherryPick(targetId, effectiveSource, [...selected], resolutionsFor(selected, resolutions)),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['boq-branches'] });
      queryClient.invalidateQueries({ queryKey: ['boq', result.target_boq_id] });
      queryClient.invalidateQueries({ queryKey: ['boq-snapshots', result.target_boq_id] });
      addToast({
        type: 'success',
        title: isMerge
          ? t('boq.branch.merged_toast', { defaultValue: 'Branch merged into the main estimate' })
          : t('boq.branch.applied_toast', { defaultValue: 'Changes applied' }),
        message: t('boq.branch.applied_counts', {
          defaultValue: '{{added}} added, {{updated}} updated, {{removed}} removed. A snapshot was saved before.',
          added: result.added,
          updated: result.updated,
          removed: result.removed,
        }),
      });
      onApplied(result.target_boq_id);
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('boq.branch.apply_failed', { defaultValue: 'Could not apply the changes' }),
        message: err.message,
      });
    },
  });

  if (!isOpen) return null;

  const sources = nodes.filter((n) => n.boq_id !== currentBoqId);
  const canApply =
    !!plan &&
    (isMerge || selected.size > 0) &&
    pending.length === 0 &&
    !mutation.isPending &&
    (!isMerge || confirmed);
  const sourceName = nodes.find((n) => n.boq_id === effectiveSource)?.name ?? '';
  const targetName = nodes.find((n) => n.boq_id === targetId)?.name ?? '';
  const fieldLabel = (field: string) => {
    switch (field) {
      case 'ordinal':
        return t('boq.branch.field_ordinal', { defaultValue: 'Position number' });
      case 'description':
        return t('boq.branch.field_description', { defaultValue: 'Text' });
      case 'unit':
        return t('boq.branch.field_unit', { defaultValue: 'Unit' });
      case 'quantity':
        return t('boq.branch.field_quantity', { defaultValue: 'Quantity' });
      case 'unit_rate':
        return t('boq.branch.field_unit_rate', { defaultValue: 'Unit rate' });
      case 'classification':
        return t('boq.branch.field_classification', { defaultValue: 'Classification' });
      default:
        return field;
    }
  };
  const actionLabel = (item: PlanItem) =>
    item.action === 'add'
      ? t('boq.branch.action_add', { defaultValue: 'Add' })
      : item.action === 'remove'
        ? t('boq.branch.action_remove', { defaultValue: 'Remove' })
        : t('boq.branch.action_update', { defaultValue: 'Update' });

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={
          isMerge
            ? t('boq.branch.merge_title', { defaultValue: 'Merge into the main estimate' })
            : t('boq.branch.pick_title', { defaultValue: 'Carry changes into this estimate' })
        }
        className="relative z-10 flex max-h-[88vh] w-full max-w-3xl mx-4 flex-col rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in"
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
              {isMerge ? <GitMerge size={16} /> : <GitPullRequestArrow size={16} />}
            </span>
            <h2 className="text-base font-semibold text-content-primary">
              {isMerge
                ? t('boq.branch.merge_title', { defaultValue: 'Merge into the main estimate' })
                : t('boq.branch.pick_title', { defaultValue: 'Carry changes into this estimate' })}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3 border-b border-border-light px-6 py-3">
          {isMerge ? (
            <p className="text-xs text-content-secondary">
              {t('boq.branch.merge_intro', {
                defaultValue:
                  'Every change of "{{source}}" is written into "{{target}}". A snapshot of the main estimate is saved first, and the branch is locked afterwards.',
                source: sourceName,
                target: targetName,
              })}
            </p>
          ) : (
            <label className="block">
              <span className="text-xs font-medium text-content-secondary">
                {t('boq.branch.pick_from', { defaultValue: 'Take changes from' })}
              </span>
              <select
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
                className="mt-1 w-full h-9 rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              >
                <option value="">{t('boq.branch.pick', { defaultValue: '- Select -' })}</option>
                {sources.map((n) => (
                  <option key={n.boq_id} value={n.boq_id}>
                    {n.is_main ? `${n.name} (${t('boq.branch.main', { defaultValue: 'main' })})` : n.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {plan && !plan.base_known && (
            <p className="flex items-start gap-1.5 rounded-md bg-semantic-warning-bg px-2 py-1.5 text-2xs text-semantic-warning">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              {t('boq.branch.base_unknown', {
                defaultValue:
                  'The branch point snapshot is gone, so changes made on both sides cannot be told apart. Check each line before applying.',
              })}
            </p>
          )}
          {plan && (
            <div className="flex flex-wrap items-center gap-1.5 text-2xs">
              <Badge variant="blue" size="sm">
                {t('boq.branch.selected_count', {
                  defaultValue: '{{count}} of {{total}} selected',
                  count: selected.size,
                  total: items.length,
                })}
              </Badge>
              {plan.conflicts > 0 && (
                <Badge variant={pending.length ? 'error' : 'success'} size="sm">
                  {t('boq.branch.conflicts_open', {
                    defaultValue: '{{open}} of {{total}} conflicts undecided',
                    open: pending.length,
                    total: plan.conflicts,
                  })}
                </Badge>
              )}
              {!isMerge && (
                <>
                  <button
                    type="button"
                    className="ml-auto text-oe-blue hover:underline"
                    onClick={() => setSelected(new Set(items.map((i) => i.key)))}
                  >
                    {t('boq.branch.select_all', { defaultValue: 'Select all' })}
                  </button>
                  <button type="button" className="text-oe-blue hover:underline" onClick={() => setSelected(new Set())}>
                    {t('boq.branch.select_none', { defaultValue: 'Select none' })}
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-3">
          {!enabled ? (
            <p className="py-10 text-center text-sm text-content-secondary">
              {t('boq.branch.pick_hint', { defaultValue: 'Choose the branch to take changes from.' })}
            </p>
          ) : isLoading ? (
            <div className="flex justify-center py-10">
              <Loader2 size={20} className="animate-spin text-content-tertiary" />
            </div>
          ) : isError ? (
            <p className="py-10 text-center text-sm text-semantic-error">{error instanceof Error ? error.message : ''}</p>
          ) : items.length === 0 ? (
            <p className="py-10 text-center text-sm text-content-secondary">
              {t('boq.branch.nothing_to_apply', { defaultValue: 'Nothing to carry over: both hold the same positions.' })}
            </p>
          ) : (
            <ul className="space-y-2">
              {items.map((item) => {
                const isSelected = selected.has(item.key);
                return (
                  <li
                    key={item.key}
                    data-testid="plan-item"
                    className={clsx(
                      'rounded-lg border px-3 py-2',
                      item.conflict ? 'border-semantic-warning/60 bg-semantic-warning-bg/40' : 'border-border-light',
                    )}
                    style={{ marginLeft: Math.min(item.depth, 6) * 12 }}
                  >
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={isMerge}
                        onChange={() => toggle(item)}
                        className="accent-oe-blue"
                        aria-label={`${item.ordinal} ${item.description}`}
                      />
                      <Badge
                        variant={item.action === 'add' ? 'success' : item.action === 'remove' ? 'error' : 'warning'}
                        size="sm"
                      >
                        {actionLabel(item)}
                      </Badge>
                      <span className="font-medium text-content-primary">{item.ordinal}</span>
                      <span className="truncate text-content-secondary">{item.description}</span>
                      {item.conflict && (
                        <Badge variant="error" size="sm">
                          {t('boq.branch.conflict', { defaultValue: 'Conflict' })}
                        </Badge>
                      )}
                    </label>
                    {Object.keys(item.fields).length > 0 && (
                      <table className="mt-1.5 w-full text-2xs">
                        <thead>
                          <tr className="text-content-tertiary">
                            <th className="w-32 py-0.5 text-left font-medium" />
                            <th className="py-0.5 text-left font-medium">
                              {t('boq.branch.col_base', { defaultValue: 'At branch point' })}
                            </th>
                            <th className="py-0.5 text-left font-medium">
                              {t('boq.branch.col_source', { defaultValue: 'Incoming' })}
                            </th>
                            <th className="py-0.5 text-left font-medium">
                              {t('boq.branch.col_target', { defaultValue: 'Here now' })}
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(item.fields).map(([field, values]) => {
                            return (
                              <tr key={field}>
                                <td className="py-0.5 text-content-tertiary">{fieldLabel(field)}</td>
                                <td className="py-0.5 font-mono text-content-tertiary">{planValueText(values.base)}</td>
                                <td className="py-0.5 font-mono text-content-primary">{planValueText(values.source)}</td>
                                <td className="py-0.5 font-mono text-content-secondary">{planValueText(values.target)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    )}
                    {item.conflict && isSelected && (
                      <div className="mt-1.5 flex flex-wrap gap-3 text-xs" role="radiogroup">
                        {(['source', 'target'] as Resolution[]).map((choice) => (
                          <label key={choice} className="flex items-center gap-1.5">
                            <input
                              type="radio"
                              name={`resolve-${item.key}`}
                              checked={resolutions[item.key] === choice}
                              onChange={() => setResolutions((prev) => ({ ...prev, [item.key]: choice }))}
                              className="accent-oe-blue"
                            />
                            {choice === 'source'
                              ? t('boq.branch.take_incoming', { defaultValue: 'Take the incoming version' })
                              : t('boq.branch.keep_here', { defaultValue: 'Keep the version here' })}
                          </label>
                        ))}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="space-y-2 border-t border-border-light px-6 py-4">
          {isMerge && (
            <>
              <label className="flex items-center gap-2 text-xs text-content-secondary">
                <input
                  type="checkbox"
                  checked={includeMarkups}
                  onChange={(e) => setIncludeMarkups(e.target.checked)}
                  className="accent-oe-blue"
                />
                {t('boq.branch.include_markups', { defaultValue: "Also replace the main estimate's markups with the branch's" })}
              </label>
              <label className="flex items-center gap-2 text-xs font-medium text-content-primary">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                  className="accent-oe-blue"
                />
                {t('boq.branch.merge_confirm', {
                  defaultValue: 'I understand this rewrites the main estimate "{{target}}".',
                  target: targetName,
                })}
              </label>
            </>
          )}
          <div className="flex gap-3">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium bg-surface-primary text-content-primary border border-border hover:bg-surface-secondary transition-all"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button
              type="button"
              disabled={!canApply}
              onClick={() => mutation.mutate()}
              className="flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isMerge ? <GitMerge size={15} /> : <GitPullRequestArrow size={15} />}
              {mutation.isPending
                ? t('boq.branch.applying', { defaultValue: 'Applying...' })
                : isMerge
                  ? t('boq.branch.merge_button', { defaultValue: 'Merge' })
                  : t('boq.branch.apply_button', { defaultValue: 'Apply selected' })}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
