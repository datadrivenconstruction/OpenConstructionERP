// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BranchControls — the branch switcher of the BOQ editor.
 *
 * A toolbar button names the branch being edited and opens a drawer with the
 * whole branch tree (author, date, total and delta against the parent). From
 * there the user switches branch, forks a new one, compares two, carries
 * changes across, merges into main, links a design option or archives.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Archive,
  ArchiveRestore,
  GitBranch,
  GitCompare,
  GitMerge,
  GitPullRequestArrow,
  Loader2,
  Lock,
  Plus,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import { Badge, Button } from '@/shared/ui';
import { fmtDate, fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { branchApi, type BranchNode } from './branchApi';
import { deltaSign, flattenTree } from './branchHelpers';
import { CreateBranchDialog } from './CreateBranchDialog';
import { BranchCompareDrawer } from './BranchCompareDrawer';
import { CherryPickDialog, type CherryPickMode } from './CherryPickDialog';

export interface BranchControlsProps {
  boqId: string;
  boqName: string;
  /** Set when the open bill is itself a branch. */
  branchOfId?: string | null;
  onNavigate: (boqId: string) => void;
  /** Refresh the open bill after changes were written into it. */
  onChanged: () => void;
}

function StatusBadge({ node }: { node: BranchNode }) {
  const { t } = useTranslation();
  if (node.is_main) {
    return (
      <Badge variant="blue" size="sm">
        {t('boq.branch.main', { defaultValue: 'main' })}
      </Badge>
    );
  }
  if (node.status === 'open') return null;
  return (
    <Badge variant={node.status === 'merged' ? 'purple' : 'neutral'} size="sm">
      {node.status === 'merged'
        ? t('boq.branch.status_merged', { defaultValue: 'merged' })
        : t('boq.branch.status_archived', { defaultValue: 'archived' })}
    </Badge>
  );
}

export function BranchControls({ boqId, boqName, branchOfId, onNavigate, onChanged }: BranchControlsProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [panelOpen, setPanelOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [pickMode, setPickMode] = useState<CherryPickMode | null>(null);

  const { data: tree, isLoading } = useQuery({
    queryKey: ['boq-branches', boqId],
    queryFn: () => branchApi.tree(boqId),
    enabled: !!boqId,
    staleTime: 15_000,
  });

  const nodes = tree?.nodes ?? [];
  const rows = flattenTree(nodes);
  const current = nodes.find((n) => n.boq_id === boqId);
  const branchCount = Math.max(nodes.length - 1, 0);
  const isBranch = !!branchOfId || (!!current && !current.is_main);
  const currentOpen = !current || current.is_main || current.status === 'open';

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['boq-branches'] });

  const statusMutation = useMutation({
    mutationFn: (status: 'open' | 'archived') => branchApi.update(boqId, { status }),
    onSuccess: () => refresh(),
    onError: (err: Error) => addToast({ type: 'error', title: err.message }),
  });

  const optionMutation = useMutation({
    mutationFn: (optionId: string | null) => branchApi.linkDesignOption(boqId, optionId),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('boq.branch.option_linked', { defaultValue: 'Design option updated' }) });
    },
    onError: (err: Error) => addToast({ type: 'error', title: err.message }),
  });

  const label = isBranch ? current?.name ?? boqName : t('boq.branch.button', { defaultValue: 'Branches' });

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setPanelOpen(true)}
        title={t('boq.branch.button_hint', {
          defaultValue: 'Variants of this estimate: switch, compare, carry changes, merge',
        })}
        data-testid="branch-switcher"
      >
        <GitBranch size={14} className="mr-1" />
        <span className="max-w-[160px] truncate">{label}</span>
        {!isBranch && branchCount > 0 && (
          <span className="ml-1 rounded-full bg-oe-blue-subtle px-1.5 text-2xs text-oe-blue-text">{branchCount}</span>
        )}
      </Button>

      {panelOpen && (
        <div className="fixed inset-y-0 right-0 z-50 flex">
          <div className="fixed inset-0 bg-black/20" onClick={() => setPanelOpen(false)} aria-hidden="true" />
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t('boq.branch.panel_title', { defaultValue: 'Estimate branches' })}
            className="relative ml-auto flex h-full w-[460px] max-w-full flex-col border-l border-border bg-surface-elevated shadow-2xl animate-slide-in-right"
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <div className="flex items-center gap-2">
                <GitBranch size={16} className="text-oe-blue" />
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('boq.branch.panel_title', { defaultValue: 'Estimate branches' })}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setPanelOpen(false)}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex flex-wrap gap-1.5 border-b border-border px-4 py-3">
              <Button size="sm" variant="secondary" onClick={() => setCreateOpen(true)} disabled={!currentOpen}>
                <Plus size={13} className="mr-1" />
                {t('boq.branch.new', { defaultValue: 'New branch' })}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setCompareOpen(true)} disabled={nodes.length < 2}>
                <GitCompare size={13} className="mr-1" />
                {t('boq.branch.compare', { defaultValue: 'Compare' })}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setPickMode('cherry-pick')}
                disabled={nodes.length < 2 || !currentOpen || (!!current?.is_main && !tree?.can_merge)}
              >
                <GitPullRequestArrow size={13} className="mr-1" />
                {t('boq.branch.carry', { defaultValue: 'Carry changes here' })}
              </Button>
              {isBranch && current?.status === 'open' && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setPickMode('merge')}
                  disabled={!tree?.can_merge}
                  title={
                    tree?.can_merge
                      ? undefined
                      : t('boq.branch.merge_needs_permission', {
                          defaultValue: 'Merging into the main estimate needs the merge permission',
                        })
                  }
                >
                  <GitMerge size={13} className="mr-1" />
                  {t('boq.branch.merge', { defaultValue: 'Merge into main' })}
                </Button>
              )}
              {isBranch && current && current.status !== 'merged' && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => statusMutation.mutate(current.status === 'archived' ? 'open' : 'archived')}
                  disabled={statusMutation.isPending}
                >
                  {current.status === 'archived' ? (
                    <ArchiveRestore size={13} className="mr-1" />
                  ) : (
                    <Archive size={13} className="mr-1" />
                  )}
                  {current.status === 'archived'
                    ? t('boq.branch.reopen', { defaultValue: 'Reopen' })
                    : t('boq.branch.archive', { defaultValue: 'Archive' })}
                </Button>
              )}
            </div>

            {(tree?.design_options.length ?? 0) > 0 && (
              <label className="block border-b border-border px-4 py-3">
                <span className="block text-2xs font-medium text-content-secondary mb-1">
                  {t('boq.branch.design_option', { defaultValue: 'Design option priced by this estimate' })}
                </span>
                <select
                  value={current?.design_option?.id ?? ''}
                  disabled={optionMutation.isPending}
                  onChange={(e) => optionMutation.mutate(e.target.value || null)}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                >
                  <option value="">{t('boq.branch.design_option_none', { defaultValue: 'None' })}</option>
                  {tree?.design_options.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.set_name ? `${o.set_name} / ${o.name}` : o.name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <div className="flex-1 overflow-y-auto">
              {isLoading ? (
                <div className="flex justify-center py-10">
                  <Loader2 size={20} className="animate-spin text-content-tertiary" />
                </div>
              ) : rows.length <= 1 ? (
                <p className="px-6 py-10 text-center text-sm text-content-secondary">
                  {t('boq.branch.empty', {
                    defaultValue:
                      'No branches yet. Create one to price an alternative (for example precast instead of cast in place) without touching this estimate.',
                  })}
                </p>
              ) : (
                <ul className="divide-y divide-border-light" data-testid="branch-tree">
                  {rows.map(({ node, depth }) => {
                    const sign = deltaSign(node.delta_vs_parent);
                    const isCurrent = node.boq_id === boqId;
                    return (
                      <li key={node.boq_id}>
                        <button
                          type="button"
                          onClick={() => {
                            if (!isCurrent) {
                              setPanelOpen(false);
                              onNavigate(node.boq_id);
                            }
                          }}
                          aria-current={isCurrent ? 'true' : undefined}
                          className={clsx(
                            'flex w-full items-start gap-2 px-4 py-2.5 text-left transition-colors',
                            isCurrent ? 'bg-oe-blue-subtle/60' : 'hover:bg-surface-secondary/60',
                          )}
                          style={{ paddingLeft: 16 + Math.min(depth, 6) * 16 }}
                        >
                          <GitBranch size={13} className="mt-0.5 shrink-0 text-content-tertiary" />
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              <span className="truncate text-sm font-medium text-content-primary">{node.name}</span>
                              <StatusBadge node={node} />
                              {node.is_locked && <Lock size={11} className="text-content-tertiary" />}
                            </div>
                            <p className="mt-0.5 text-2xs text-content-tertiary">
                              {[node.author, node.created_at ? fmtDate(node.created_at) : '']
                                .filter(Boolean)
                                .join(' · ')}
                              {node.design_option && (
                                <>
                                  {' · '}
                                  {t('boq.branch.prices_option', {
                                    defaultValue: 'prices {{name}}',
                                    name: node.design_option.name,
                                  })}
                                </>
                              )}
                            </p>
                          </div>
                          <div className="shrink-0 text-right">
                            <div className="font-mono text-xs text-content-primary">
                              {fmtNumber(node.grand_total)} {tree?.currency}
                            </div>
                            {!node.is_main && node.delta_vs_parent !== null && (
                              <div
                                className={clsx(
                                  'font-mono text-2xs',
                                  sign > 0 && 'text-red-600 dark:text-red-400',
                                  sign < 0 && 'text-emerald-600 dark:text-emerald-400',
                                  sign === 0 && 'text-content-tertiary',
                                )}
                              >
                                {sign > 0 ? '+' : ''}
                                {fmtNumber(node.delta_vs_parent)}
                              </div>
                            )}
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      <CreateBranchDialog
        sourceBoqId={boqId}
        sourceName={current?.name ?? boqName}
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(id) => {
          setCreateOpen(false);
          setPanelOpen(false);
          onNavigate(id);
        }}
      />
      <BranchCompareDrawer
        nodes={nodes}
        currentBoqId={boqId}
        isOpen={compareOpen}
        onClose={() => setCompareOpen(false)}
      />
      {pickMode && (
        <CherryPickDialog
          mode={pickMode}
          nodes={nodes}
          currentBoqId={boqId}
          isOpen
          onClose={() => setPickMode(null)}
          onApplied={(targetId) => {
            const merged = pickMode === 'merge';
            setPickMode(null);
            refresh();
            if (merged) {
              setPanelOpen(false);
              onNavigate(targetId);
            } else {
              onChanged();
            }
          }}
        />
      )}
    </>
  );
}
