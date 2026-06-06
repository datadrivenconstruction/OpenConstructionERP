/**
 * Sub-entity CRUD tabs for Property-Development: Phases, Blocks,
 * Brokers, PriceMatrix, Escrow.
 *
 * Each tab is fully clickable: list → empty state CTA → create modal →
 * edit modal → delete confirm → toast → refresh. Cross-links (Phase →
 * Blocks, Block → Plots, Broker → KYC, PriceMatrix → Preview/Apply,
 * Escrow → Balance/Transactions) are inlined per the audit spec.
 *
 * Lives in its own file so the giant ``PropertyDevPage.tsx`` doesn't
 * suffer from concurrent-edit churn with the other sister-agent scopes.
 *
 * The global header "New X" CTA on PropertyDevPage broadcasts the
 * ``propdev:new-sub-entity`` window CustomEvent, picked up here by
 * ``useSubEntityCreateBroadcast``.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  ArrowRight,
  ArrowRightCircle,
  BedDouble,
  Boxes,
  Briefcase,
  Calculator,
  Check,
  Grid3X3,
  Landmark,
  Layers,
  Pencil,
  Plus,
  Trash2,
  Wallet,
} from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  SideDrawer,
  SkeletonTable,
} from '@/shared/ui';
import {
  WideModal,
  WideModalField,
  WideModalSection,
} from '@/shared/ui/WideModal';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  activatePriceMatrix,
  bulkRecomputePrices,
  createBlock,
  createBroker,
  createEscrowAccount,
  createEscrowTransaction,
  createPhase,
  createPriceMatrix,
  deleteBlock,
  deleteBroker,
  deleteEscrowAccount,
  deletePhase,
  deletePriceMatrix,
  getEscrowBalance,
  listBlocks,
  listBrokers,
  listEscrowAccounts,
  listEscrowTransactions,
  listPhases,
  listPriceMatrices,
  previewPriceOnPlot,
  reconcileEscrowTransaction,
  updateBlock,
  updateBroker,
  updateEscrowAccount,
  updatePhase,
  updatePlot,
  updatePriceMatrix,
  verifyBrokerKyc,
} from './api';
import type {
  Block,
  BlockStatus,
  Broker,
  EscrowAccount,
  EscrowDirection,
  EscrowSourceType,
  Phase,
  PhaseStatus,
  Plot,
  PlotStatus,
  PriceMatrix,
  PriceMatrixRule,
  PriceMatrixStatus,
  RegulatorRef,
} from './api';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

function toNumber(v: number | string | null | undefined): number {
  if (v == null) return 0;
  if (typeof v === 'number') return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

const PLOT_STATUS_VARIANT: Record<
  PlotStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  planned: 'neutral',
  reserved: 'warning',
  under_construction: 'blue',
  ready: 'blue',
  sold: 'success',
  handed_over: 'success',
  held: 'warning',
  blocked: 'error',
};

/**
 * Hook: listen for the global "create sub-entity" CTA broadcast.
 *
 * PropertyDevPage's top-right "New X" button dispatches a window
 * CustomEvent ``propdev:new-sub-entity`` with the current tab as detail.
 * Each tab subscribes and opens its own create modal when its tab is
 * the active one.
 */
function useSubEntityCreateBroadcast(
  matchTab: string,
  onCreate: () => void,
): void {
  useEffect(() => {
    function handler(ev: Event) {
      const detail = (ev as CustomEvent).detail as { tab?: string } | undefined;
      if (detail?.tab === matchTab) onCreate();
    }
    window.addEventListener('propdev:new-sub-entity', handler);
    return () =>
      window.removeEventListener('propdev:new-sub-entity', handler);
  }, [matchTab, onCreate]);
}

/* ───────────────────────────── Phases ───────────────────────────── */

const PHASE_STATUS_VARIANT: Record<
  PhaseStatus,
  'neutral' | 'blue' | 'success'
> = {
  planned: 'neutral',
  under_construction: 'blue',
  completed: 'success',
};

export function PhasesTab({
  developmentId,
  onJumpToBlocks,
}: {
  developmentId: string;
  onJumpToBlocks: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Phase | null>(null);
  const [deleting, setDeleting] = useState<Phase | null>(null);

  useSubEntityCreateBroadcast('phases', () => setCreateOpen(true));

  const phasesQ = useQuery({
    queryKey: ['propdev', 'phases', developmentId],
    queryFn: () => listPhases(developmentId),
    enabled: !!developmentId,
  });
  const phases = phasesQ.data ?? [];

  const blockCountsQ = useQuery({
    queryKey: [
      'propdev',
      'phases-block-counts',
      developmentId,
      phases.map((p) => p.id).join(','),
    ],
    queryFn: async () => {
      const counts: Record<string, number> = {};
      await Promise.all(
        phases.map(async (p) => {
          try {
            const blocks = await listBlocks(p.id);
            counts[p.id] = blocks.length;
          } catch {
            counts[p.id] = 0;
          }
        }),
      );
      return counts;
    },
    enabled: phases.length > 0,
  });
  const blockCounts = blockCountsQ.data ?? {};

  const deleteMu = useMutation({
    mutationFn: (id: string) => deletePhase(id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.phase_deleted', { defaultValue: 'Phase deleted' }),
      });
      qc.invalidateQueries({
        queryKey: ['propdev', 'phases', developmentId],
      });
      setDeleting(null);
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!developmentId) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Layers size={22} />}
          title={t('propdev.select_development', {
            defaultValue: 'Select a development',
          })}
          description={t('propdev.phases_select_dev_desc', {
            defaultValue: 'Pick a development above to see its phases.',
          })}
        />
      </Card>
    );
  }
  if (phasesQ.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={5} columns={5} />
      </Card>
    );
  }
  if (phases.length === 0) {
    return (
      <>
        <Card padding="md">
          <EmptyState
            icon={<Layers size={22} />}
            title={t('propdev.no_phases', { defaultValue: 'No phases yet' })}
            description={t('propdev.no_phases_desc', {
              defaultValue:
                'Carve a development into phases (Phase 1, Phase 2, …) to time-box construction and launch waves.',
            })}
            action={{
              label: t('propdev.new_phase', { defaultValue: 'New Phase' }),
              onClick: () => setCreateOpen(true),
            }}
          />
        </Card>
        {createOpen && (
          <PhaseFormModal
            developmentId={developmentId}
            onClose={() => setCreateOpen(false)}
            onSaved={() =>
              qc.invalidateQueries({
                queryKey: ['propdev', 'phases', developmentId],
              })
            }
          />
        )}
      </>
    );
  }

  return (
    <>
      <Card padding="md">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-content-tertiary border-b border-border-light">
              <tr>
                <th className="text-left py-2 pr-3">
                  {t('propdev.phase.sequence', { defaultValue: '#' })}
                </th>
                <th className="text-left py-2 pr-3">
                  {t('propdev.phase.code', { defaultValue: 'Code' })}
                </th>
                <th className="text-left py-2 pr-3">
                  {t('propdev.phase.name', { defaultValue: 'Name' })}
                </th>
                <th className="text-left py-2 pr-3">
                  {t('propdev.phase.status', { defaultValue: 'Status' })}
                </th>
                <th className="text-left py-2 pr-3">
                  {t('propdev.phase.planned', { defaultValue: 'Planned' })}
                </th>
                <th className="text-left py-2 pr-3">
                  {t('propdev.phase.blocks', { defaultValue: 'Blocks' })}
                </th>
                <th className="text-right py-2 pr-2">
                  {t('common.actions', { defaultValue: 'Actions' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {phases.map((p) => (
                <tr
                  key={p.id}
                  className="border-b border-border-light/60 hover:bg-surface-secondary/50"
                >
                  <td className="py-2 pr-3 text-content-tertiary">
                    {p.sequence}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs">{p.code}</td>
                  <td className="py-2 pr-3">{p.name || '—'}</td>
                  <td className="py-2 pr-3">
                    <Badge variant={PHASE_STATUS_VARIANT[p.status]} dot>
                      {t(`propdev.phase.status.${p.status}`, {
                        defaultValue: p.status.replace('_', ' '),
                      })}
                    </Badge>
                  </td>
                  <td className="py-2 pr-3 text-xs">
                    {p.planned_start ? (
                      <DateDisplay value={p.planned_start} />
                    ) : (
                      '—'
                    )}
                    {p.planned_end && (
                      <>
                        {' → '}
                        <DateDisplay value={p.planned_end} />
                      </>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    <button
                      type="button"
                      onClick={onJumpToBlocks}
                      className="inline-flex items-center gap-1 text-oe-blue hover:underline"
                    >
                      <Boxes size={12} />
                      {blockCounts[p.id] ?? 0}
                    </button>
                  </td>
                  <td className="py-2 pr-2 text-right">
                    <div className="inline-flex gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Pencil size={12} />}
                        onClick={() => setEditing(p)}
                        aria-label={t('common.edit', {
                          defaultValue: 'Edit',
                        })}
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Trash2 size={12} />}
                        onClick={() => setDeleting(p)}
                        aria-label={t('common.delete', {
                          defaultValue: 'Delete',
                        })}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {createOpen && (
        <PhaseFormModal
          developmentId={developmentId}
          onClose={() => setCreateOpen(false)}
          onSaved={() =>
            qc.invalidateQueries({
              queryKey: ['propdev', 'phases', developmentId],
            })
          }
        />
      )}
      {editing && (
        <PhaseFormModal
          developmentId={developmentId}
          phase={editing}
          onClose={() => setEditing(null)}
          onSaved={() =>
            qc.invalidateQueries({
              queryKey: ['propdev', 'phases', developmentId],
            })
          }
        />
      )}
      {deleting && (
        <ConfirmDialog
          open
          title={t('propdev.delete_phase', { defaultValue: 'Delete phase?' })}
          message={
            (blockCounts[deleting.id] ?? 0) > 0
              ? t('propdev.delete_phase_warn_blocks', {
                  defaultValue:
                    'This phase still has {{n}} block(s). They will be orphaned. Continue?',
                  n: blockCounts[deleting.id],
                })
              : t('propdev.delete_phase_confirm', {
                  defaultValue:
                    'Delete phase "{{code}}"? This cannot be undone.',
                  code: deleting.code,
                })
          }
          confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
          variant="danger"
          loading={deleteMu.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteMu.mutate(deleting.id)}
        />
      )}
    </>
  );
}

function PhaseFormModal({
  developmentId,
  phase,
  onClose,
  onSaved,
}: {
  developmentId: string;
  phase?: Phase;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const editing = !!phase;
  const [form, setForm] = useState({
    code: phase?.code ?? '',
    name: phase?.name ?? '',
    sequence: phase?.sequence ?? 0,
    planned_start: phase?.planned_start ?? '',
    planned_end: phase?.planned_end ?? '',
    status: (phase?.status ?? 'planned') as PhaseStatus,
  });

  const saveMu = useMutation({
    mutationFn: async () => {
      if (editing && phase) {
        return updatePhase(phase.id, {
          name: form.name,
          sequence: form.sequence,
          planned_start: form.planned_start || null,
          planned_end: form.planned_end || null,
          status: form.status,
        });
      }
      return createPhase({
        development_id: developmentId,
        code: form.code,
        name: form.name || undefined,
        sequence: form.sequence,
        planned_start: form.planned_start || undefined,
        planned_end: form.planned_end || undefined,
        status: form.status,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: editing
          ? t('propdev.phase_updated', { defaultValue: 'Phase updated' })
          : t('propdev.phase_created', { defaultValue: 'Phase created' }),
      });
      onSaved();
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const canSubmit = editing || form.code.trim().length > 0;

  return (
    <WideModal
      open
      onClose={onClose}
      title={
        editing
          ? t('propdev.edit_phase', { defaultValue: 'Edit phase' })
          : t('propdev.new_phase', { defaultValue: 'New phase' })
      }
      size="md"
      busy={saveMu.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saveMu.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => saveMu.mutate()}
            loading={saveMu.isPending}
            disabled={!canSubmit}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('propdev.phase.code', { defaultValue: 'Code' })}
          required={!editing}
        >
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            className={inputCls}
            disabled={editing}
            placeholder="P1"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.phase.sequence', { defaultValue: 'Sequence' })}
        >
          <input
            type="number"
            value={form.sequence}
            min={0}
            onChange={(e) =>
              setForm({ ...form, sequence: Number(e.target.value) || 0 })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.phase.name', { defaultValue: 'Name' })}
          span={2}
        >
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
            placeholder={t('propdev.phase.name_ph', {
              defaultValue: 'Phase 1 – Launch wave',
            })}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.phase.planned_start', {
            defaultValue: 'Planned start',
          })}
        >
          <input
            type="date"
            value={form.planned_start}
            onChange={(e) =>
              setForm({ ...form, planned_start: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.phase.planned_end', {
            defaultValue: 'Planned end',
          })}
        >
          <input
            type="date"
            value={form.planned_end}
            onChange={(e) => setForm({ ...form, planned_end: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.phase.status', { defaultValue: 'Status' })}
          span={2}
        >
          <select
            value={form.status}
            onChange={(e) =>
              setForm({ ...form, status: e.target.value as PhaseStatus })
            }
            className={inputCls}
          >
            <option value="planned">
              {t('propdev.phase.status.planned', { defaultValue: 'Planned' })}
            </option>
            <option value="under_construction">
              {t('propdev.phase.status.under_construction', {
                defaultValue: 'Under construction',
              })}
            </option>
            <option value="completed">
              {t('propdev.phase.status.completed', {
                defaultValue: 'Completed',
              })}
            </option>
          </select>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ───────────────────────────── Blocks ───────────────────────────── */

const BLOCK_STATUS_VARIANT: Record<
  BlockStatus,
  'neutral' | 'blue' | 'success'
> = {
  planned: 'neutral',
  under_construction: 'blue',
  handed_over: 'success',
};

export function BlocksTab({
  developmentId,
  plots,
  onJumpToPlots,
}: {
  developmentId: string;
  plots: Plot[];
  onJumpToPlots: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [phaseId, setPhaseId] = useState<string>('');
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Block | null>(null);
  const [deleting, setDeleting] = useState<Block | null>(null);
  const [assigningTo, setAssigningTo] = useState<Block | null>(null);

  const phasesQ = useQuery({
    queryKey: ['propdev', 'phases', developmentId],
    queryFn: () => listPhases(developmentId),
    enabled: !!developmentId,
  });
  const phases = phasesQ.data ?? [];

  useEffect(() => {
    if (!phaseId && phases.length > 0) {
      const first = phases[0];
      if (first) setPhaseId(first.id);
    }
  }, [phases, phaseId]);

  const blocksQ = useQuery({
    queryKey: ['propdev', 'blocks', phaseId],
    queryFn: () => listBlocks(phaseId),
    enabled: !!phaseId,
  });
  const blocks = blocksQ.data ?? [];

  useSubEntityCreateBroadcast('blocks', () => {
    if (!phaseId) {
      addToast({
        type: 'warning',
        title: t('propdev.blocks_need_phase', {
          defaultValue: 'Create a phase first, then add blocks to it.',
        }),
      });
      return;
    }
    setCreateOpen(true);
  });

  const deleteMu = useMutation({
    mutationFn: (id: string) => deleteBlock(id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.block_deleted', { defaultValue: 'Block deleted' }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'blocks', phaseId] });
      qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
      setDeleting(null);
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const plotsByBlock = useMemo(() => {
    const m: Record<string, Plot[]> = {};
    for (const p of plots) {
      const k = p.block_id ?? '__unassigned__';
      (m[k] ??= []).push(p);
    }
    return m;
  }, [plots]);

  if (!developmentId) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Boxes size={22} />}
          title={t('propdev.select_development', {
            defaultValue: 'Select a development',
          })}
          description={t('propdev.blocks_select_dev_desc', {
            defaultValue: 'Pick a development to see its blocks.',
          })}
        />
      </Card>
    );
  }
  if (phases.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Layers size={22} />}
          title={t('propdev.no_phases', { defaultValue: 'No phases yet' })}
          description={t('propdev.create_phase_first', {
            defaultValue: 'Blocks belong to phases - create a phase first.',
          })}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <label className="text-xs text-content-secondary">
          {t('propdev.phase', { defaultValue: 'Phase' })}
        </label>
        <select
          value={phaseId}
          onChange={(e) => setPhaseId(e.target.value)}
          className={clsx(inputCls, 'max-w-[280px]')}
        >
          {phases.map((p) => (
            <option key={p.id} value={p.id}>
              {p.code} —{' '}
              {p.name || t('propdev.untitled', { defaultValue: 'Untitled' })}
            </option>
          ))}
        </select>
      </div>

      {blocksQ.isLoading ? (
        <Card padding="md">
          <SkeletonTable rows={5} columns={6} />
        </Card>
      ) : blocks.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<Boxes size={22} />}
            title={t('propdev.no_blocks', {
              defaultValue: 'No blocks in this phase',
            })}
            description={t('propdev.no_blocks_desc', {
              defaultValue: 'Add blocks (A, B, C, …) to subdivide a phase.',
            })}
            action={{
              label: t('propdev.new_block', { defaultValue: 'New Block' }),
              onClick: () => setCreateOpen(true),
            }}
          />
        </Card>
      ) : (
        <Card padding="md">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-content-tertiary border-b border-border-light">
                <tr>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.block.code', { defaultValue: 'Code' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.block.name', { defaultValue: 'Name' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.block.layout', { defaultValue: 'Layout' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.block.orientation', {
                      defaultValue: 'Orient.',
                    })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.block.status', { defaultValue: 'Status' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.block.plots', { defaultValue: 'Plots' })}
                  </th>
                  <th className="text-right py-2 pr-2">
                    {t('common.actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {blocks.map((b) => (
                  <tr
                    key={b.id}
                    className="border-b border-border-light/60 hover:bg-surface-secondary/50"
                  >
                    <td className="py-2 pr-3 font-mono text-xs">{b.code}</td>
                    <td className="py-2 pr-3">{b.name || '—'}</td>
                    <td className="py-2 pr-3 text-xs text-content-secondary">
                      {b.levels_count}L × {b.units_per_level}u
                    </td>
                    <td className="py-2 pr-3 text-xs">{b.orientation || '—'}</td>
                    <td className="py-2 pr-3">
                      <Badge variant={BLOCK_STATUS_VARIANT[b.status]} dot>
                        {t(`propdev.block.status.${b.status}`, {
                          defaultValue: b.status.replace('_', ' '),
                        })}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <button
                        type="button"
                        onClick={onJumpToPlots}
                        className="inline-flex items-center gap-1 text-oe-blue hover:underline"
                      >
                        <Grid3X3 size={12} />
                        {(plotsByBlock[b.id] ?? []).length}
                      </button>
                    </td>
                    <td className="py-2 pr-2 text-right">
                      <div className="inline-flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Plus size={12} />}
                          onClick={() => setAssigningTo(b)}
                          aria-label={t('propdev.assign_plots', {
                            defaultValue: 'Assign plots',
                          })}
                          title={t('propdev.assign_plots', {
                            defaultValue: 'Assign plots',
                          })}
                        />
                        {/* CONN-16 (producer half): jump to the worker
                            housing units of this block - the consumer on
                            /accommodation filters by ?block=. */}
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<BedDouble size={12} />}
                          onClick={() => navigate(`/accommodation?block=${b.id}`)}
                          aria-label={t('propdev.worker_housing', {
                            defaultValue: 'Worker housing',
                          })}
                          title={t('propdev.worker_housing', {
                            defaultValue: 'Worker housing',
                          })}
                        />
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Pencil size={12} />}
                          onClick={() => setEditing(b)}
                          aria-label={t('common.edit', {
                            defaultValue: 'Edit',
                          })}
                        />
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Trash2 size={12} />}
                          onClick={() => setDeleting(b)}
                          aria-label={t('common.delete', {
                            defaultValue: 'Delete',
                          })}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {createOpen && phaseId && (
        <BlockFormModal
          phaseId={phaseId}
          onClose={() => setCreateOpen(false)}
          onSaved={() =>
            qc.invalidateQueries({ queryKey: ['propdev', 'blocks', phaseId] })
          }
        />
      )}
      {editing && (
        <BlockFormModal
          phaseId={editing.phase_id}
          block={editing}
          onClose={() => setEditing(null)}
          onSaved={() =>
            qc.invalidateQueries({
              queryKey: ['propdev', 'blocks', editing.phase_id],
            })
          }
        />
      )}
      {deleting && (
        <ConfirmDialog
          open
          title={t('propdev.delete_block', { defaultValue: 'Delete block?' })}
          message={
            (plotsByBlock[deleting.id] ?? []).length > 0
              ? t('propdev.delete_block_warn_plots', {
                  defaultValue:
                    'This block is linked to {{n}} plot(s). They will be unlinked (not deleted). Continue?',
                  n: (plotsByBlock[deleting.id] ?? []).length,
                })
              : t('propdev.delete_block_confirm', {
                  defaultValue: 'Delete block "{{code}}"?',
                  code: deleting.code,
                })
          }
          confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
          variant="danger"
          loading={deleteMu.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteMu.mutate(deleting.id)}
        />
      )}
      {assigningTo && (
        <AssignPlotsToBlockModal
          block={assigningTo}
          plots={plots}
          onClose={() => setAssigningTo(null)}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
            qc.invalidateQueries({
              queryKey: ['propdev', 'blocks', assigningTo.phase_id],
            });
          }}
        />
      )}
    </div>
  );
}

function BlockFormModal({
  phaseId,
  block,
  onClose,
  onSaved,
}: {
  phaseId: string;
  block?: Block;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const editing = !!block;
  const [form, setForm] = useState({
    code: block?.code ?? '',
    name: block?.name ?? '',
    levels_count: block?.levels_count ?? 1,
    units_per_level: block?.units_per_level ?? 1,
    orientation: block?.orientation ?? '',
    status: (block?.status ?? 'planned') as BlockStatus,
  });

  const saveMu = useMutation({
    mutationFn: async () => {
      if (editing && block) {
        return updateBlock(block.id, {
          name: form.name,
          levels_count: form.levels_count,
          units_per_level: form.units_per_level,
          orientation: form.orientation || null,
          status: form.status,
        });
      }
      return createBlock({
        phase_id: phaseId,
        code: form.code,
        name: form.name || undefined,
        levels_count: form.levels_count,
        units_per_level: form.units_per_level,
        orientation: form.orientation || undefined,
        status: form.status,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: editing
          ? t('propdev.block_updated', { defaultValue: 'Block updated' })
          : t('propdev.block_created', { defaultValue: 'Block created' }),
      });
      onSaved();
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const canSubmit = editing || form.code.trim().length > 0;

  return (
    <WideModal
      open
      onClose={onClose}
      title={
        editing
          ? t('propdev.edit_block', { defaultValue: 'Edit block' })
          : t('propdev.new_block', { defaultValue: 'New block' })
      }
      size="md"
      busy={saveMu.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={saveMu.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => saveMu.mutate()}
            loading={saveMu.isPending}
            disabled={!canSubmit}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('propdev.block.code', { defaultValue: 'Code' })}
          required={!editing}
        >
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            className={inputCls}
            disabled={editing}
            placeholder="A"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.block.name', { defaultValue: 'Name' })}
        >
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.block.levels_count', { defaultValue: 'Levels' })}
        >
          <input
            type="number"
            min={1}
            max={400}
            value={form.levels_count}
            onChange={(e) =>
              setForm({
                ...form,
                levels_count: Math.max(1, Number(e.target.value) || 1),
              })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.block.units_per_level', {
            defaultValue: 'Units per level',
          })}
        >
          <input
            type="number"
            min={1}
            max={200}
            value={form.units_per_level}
            onChange={(e) =>
              setForm({
                ...form,
                units_per_level: Math.max(1, Number(e.target.value) || 1),
              })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.block.orientation', {
            defaultValue: 'Orientation',
          })}
        >
          <select
            value={form.orientation ?? ''}
            onChange={(e) => setForm({ ...form, orientation: e.target.value })}
            className={inputCls}
          >
            <option value="">
              {t('common.none', { defaultValue: '- none -' })}
            </option>
            <option value="N">N</option>
            <option value="NE">NE</option>
            <option value="E">E</option>
            <option value="SE">SE</option>
            <option value="S">S</option>
            <option value="SW">SW</option>
            <option value="W">W</option>
            <option value="NW">NW</option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.block.status', { defaultValue: 'Status' })}
        >
          <select
            value={form.status}
            onChange={(e) =>
              setForm({ ...form, status: e.target.value as BlockStatus })
            }
            className={inputCls}
          >
            <option value="planned">
              {t('propdev.block.status.planned', { defaultValue: 'Planned' })}
            </option>
            <option value="under_construction">
              {t('propdev.block.status.under_construction', {
                defaultValue: 'Under construction',
              })}
            </option>
            <option value="handed_over">
              {t('propdev.block.status.handed_over', {
                defaultValue: 'Handed over',
              })}
            </option>
          </select>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

function AssignPlotsToBlockModal({
  block,
  plots,
  onClose,
  onSaved,
}: {
  block: Block;
  plots: Plot[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const candidates = useMemo(
    () => plots.filter((p) => !p.block_id || p.block_id === block.id),
    [plots, block.id],
  );
  const [selected, setSelected] = useState<Set<string>>(
    new Set(plots.filter((p) => p.block_id === block.id).map((p) => p.id)),
  );

  const saveMu = useMutation({
    mutationFn: async () => {
      const ops: Promise<unknown>[] = [];
      for (const id of selected) {
        const p = plots.find((x) => x.id === id);
        if (p && p.block_id !== block.id) {
          ops.push(updatePlot(id, { block_id: block.id }));
        }
      }
      for (const p of plots) {
        if (p.block_id === block.id && !selected.has(p.id)) {
          ops.push(
            updatePlot(p.id, { block_id: '' as unknown as undefined }),
          );
        }
      }
      await Promise.all(ops);
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.plots_assigned', {
          defaultValue: 'Plot assignments saved',
        }),
      });
      onSaved();
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const toggle = (id: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('propdev.assign_plots_to_block', {
        defaultValue: 'Assign plots to block {{code}}',
        code: block.code,
      })}
      size="lg"
      busy={saveMu.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={saveMu.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => saveMu.mutate()}
            loading={saveMu.isPending}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <p className="text-xs text-content-tertiary mb-2">
        {t('propdev.assign_plots_help', {
          defaultValue:
            'Check plots to link them to this block. Uncheck to unlink. Plots already linked to another block are hidden.',
        })}
      </p>
      {candidates.length === 0 ? (
        <EmptyState
          icon={<Grid3X3 size={20} />}
          title={t('propdev.no_assignable_plots', {
            defaultValue: 'No assignable plots',
          })}
          description={t('propdev.no_assignable_plots_desc', {
            defaultValue:
              'All plots are already linked to a different block.',
          })}
        />
      ) : (
        <ul className="max-h-[400px] overflow-y-auto divide-y divide-border-light">
          {candidates.map((p) => (
            <li key={p.id} className="flex items-center gap-3 py-1.5 px-1">
              <input
                type="checkbox"
                checked={selected.has(p.id)}
                onChange={() => toggle(p.id)}
                id={`assign-${p.id}`}
              />
              <label
                htmlFor={`assign-${p.id}`}
                className="flex-1 cursor-pointer text-sm"
              >
                <span className="font-mono">{p.plot_number}</span>
                {p.area_m2 && (
                  <span className="text-content-tertiary text-xs ml-2">
                    {toNumber(p.area_m2)} m²
                  </span>
                )}
              </label>
              <Badge variant={PLOT_STATUS_VARIANT[p.status]} dot>
                {p.status}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </WideModal>
  );
}

/* ───────────────────────────── Brokers ──────────────────────────── */

export function BrokersTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [activeOnly, setActiveOnly] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Broker | null>(null);
  const [deleting, setDeleting] = useState<Broker | null>(null);

  useSubEntityCreateBroadcast('brokers', () => setCreateOpen(true));

  const brokersQ = useQuery({
    queryKey: ['propdev', 'brokers', activeOnly],
    queryFn: () => listBrokers({ active_only: activeOnly, limit: 200 }),
  });
  const brokers = brokersQ.data ?? [];

  const deleteMu = useMutation({
    mutationFn: (id: string) => deleteBroker(id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.broker_deleted', {
          defaultValue: 'Broker deleted',
        }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'brokers'] });
      setDeleting(null);
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const toggleActiveMu = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      updateBroker(id, { active }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'brokers'] });
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const verifyKycMu = useMutation({
    mutationFn: (id: string) => verifyBrokerKyc(id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.broker_kyc_verified', {
          defaultValue: 'KYC verified',
        }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'brokers'] });
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (brokersQ.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={5} columns={6} />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="inline-flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
          />
          {t('propdev.broker.active_only', { defaultValue: 'Active only' })}
        </label>
      </div>

      {brokers.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<Briefcase size={22} />}
            title={t('propdev.no_brokers', { defaultValue: 'No brokers yet' })}
            description={t('propdev.no_brokers_desc', {
              defaultValue:
                'Brokers are external sales partners. Add a broker to track licence, jurisdiction, default commission % and KYC.',
            })}
            action={{
              label: t('propdev.new_broker', { defaultValue: 'New Broker' }),
              onClick: () => setCreateOpen(true),
            }}
          />
        </Card>
      ) : (
        <Card padding="md">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-content-tertiary border-b border-border-light">
                <tr>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.broker.name', { defaultValue: 'Name' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.broker.license', {
                      defaultValue: 'Licence #',
                    })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.broker.jurisdiction', {
                      defaultValue: 'Region',
                    })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.broker.email', { defaultValue: 'Email' })}
                  </th>
                  <th className="text-right py-2 pr-3">
                    {t('propdev.broker.commission', {
                      defaultValue: 'Commission %',
                    })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.broker.kyc', { defaultValue: 'KYC' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.broker.active', { defaultValue: 'Active' })}
                  </th>
                  <th className="text-right py-2 pr-2">
                    {t('common.actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {brokers.map((b) => (
                  <tr
                    key={b.id}
                    className="border-b border-border-light/60 hover:bg-surface-secondary/50"
                  >
                    <td className="py-2 pr-3 font-medium">{b.name}</td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {b.license_number}
                    </td>
                    <td className="py-2 pr-3 text-xs">
                      {b.jurisdiction || '—'}
                    </td>
                    <td className="py-2 pr-3 text-xs">
                      {b.contact_email || '—'}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {toNumber(b.default_commission_pct).toFixed(2)}%
                    </td>
                    <td className="py-2 pr-3">
                      <Badge
                        variant={
                          b.kyc_status === 'verified'
                            ? 'success'
                            : b.kyc_status === 'rejected' ||
                                b.kyc_status === 'expired'
                              ? 'error'
                              : 'warning'
                        }
                        dot
                      >
                        {b.kyc_status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <button
                        type="button"
                        onClick={() =>
                          toggleActiveMu.mutate({
                            id: b.id,
                            active: !b.active,
                          })
                        }
                        className={clsx(
                          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs',
                          b.active
                            ? 'bg-emerald-100 text-emerald-800'
                            : 'bg-slate-200 text-slate-700',
                        )}
                        title={t('propdev.broker.toggle_active', {
                          defaultValue: 'Toggle active',
                        })}
                      >
                        {b.active
                          ? t('common.yes', { defaultValue: 'Yes' })
                          : t('common.no', { defaultValue: 'No' })}
                      </button>
                    </td>
                    <td className="py-2 pr-2 text-right">
                      <div className="inline-flex gap-1">
                        {b.kyc_status !== 'verified' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            icon={<Check size={12} />}
                            onClick={() => verifyKycMu.mutate(b.id)}
                            aria-label={t('propdev.verify_kyc', {
                              defaultValue: 'Verify KYC',
                            })}
                            title={t('propdev.verify_kyc', {
                              defaultValue: 'Verify KYC',
                            })}
                          />
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Pencil size={12} />}
                          onClick={() => setEditing(b)}
                          aria-label={t('common.edit', {
                            defaultValue: 'Edit',
                          })}
                        />
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Trash2 size={12} />}
                          onClick={() => setDeleting(b)}
                          aria-label={t('common.delete', {
                            defaultValue: 'Delete',
                          })}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {createOpen && (
        <BrokerFormModal
          onClose={() => setCreateOpen(false)}
          onSaved={() =>
            qc.invalidateQueries({ queryKey: ['propdev', 'brokers'] })
          }
        />
      )}
      {editing && (
        <BrokerFormModal
          broker={editing}
          onClose={() => setEditing(null)}
          onSaved={() =>
            qc.invalidateQueries({ queryKey: ['propdev', 'brokers'] })
          }
        />
      )}
      {deleting && (
        <ConfirmDialog
          open
          title={t('propdev.delete_broker', {
            defaultValue: 'Delete broker?',
          })}
          message={t('propdev.delete_broker_confirm', {
            defaultValue:
              'Delete broker "{{name}}"? Linked commission agreements & accruals will be preserved but orphaned.',
            name: deleting.name,
          })}
          confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
          variant="danger"
          loading={deleteMu.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteMu.mutate(deleting.id)}
        />
      )}
    </div>
  );
}

function BrokerFormModal({
  broker,
  onClose,
  onSaved,
}: {
  broker?: Broker;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const editing = !!broker;
  const [form, setForm] = useState({
    name: broker?.name ?? '',
    license_number: broker?.license_number ?? '',
    jurisdiction: broker?.jurisdiction ?? '',
    contact_email: broker?.contact_email ?? '',
    contact_phone: broker?.contact_phone ?? '',
    default_commission_pct:
      broker?.default_commission_pct != null
        ? String(broker.default_commission_pct)
        : '0',
    active: broker?.active ?? true,
  });

  const saveMu = useMutation({
    mutationFn: async () => {
      const pct = Number(form.default_commission_pct);
      if (!Number.isFinite(pct) || pct < 0 || pct > 100) {
        throw new Error(
          t('propdev.broker.commission_invalid', {
            defaultValue: 'Commission % must be between 0 and 100',
          }),
        );
      }
      if (editing && broker) {
        return updateBroker(broker.id, {
          name: form.name,
          license_number: form.license_number,
          jurisdiction: form.jurisdiction,
          contact_email: form.contact_email,
          contact_phone: form.contact_phone,
          default_commission_pct: pct,
          active: form.active,
        });
      }
      return createBroker({
        name: form.name,
        license_number: form.license_number,
        jurisdiction: form.jurisdiction,
        contact_email: form.contact_email,
        contact_phone: form.contact_phone,
        default_commission_pct: pct,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: editing
          ? t('propdev.broker_updated', { defaultValue: 'Broker updated' })
          : t('propdev.broker_created', { defaultValue: 'Broker created' }),
      });
      onSaved();
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const canSubmit =
    form.name.trim().length > 0 && form.license_number.trim().length > 0;

  return (
    <WideModal
      open
      onClose={onClose}
      title={
        editing
          ? t('propdev.edit_broker', { defaultValue: 'Edit broker' })
          : t('propdev.new_broker', { defaultValue: 'New broker' })
      }
      size="md"
      busy={saveMu.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={saveMu.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => saveMu.mutate()}
            loading={saveMu.isPending}
            disabled={!canSubmit}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('propdev.broker.name', { defaultValue: 'Name' })}
          required
          span={2}
        >
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.broker.license', { defaultValue: 'Licence #' })}
          required
        >
          <input
            value={form.license_number}
            onChange={(e) =>
              setForm({ ...form, license_number: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.broker.jurisdiction', {
            defaultValue: 'Jurisdiction (ISO 3166-2)',
          })}
        >
          <input
            value={form.jurisdiction}
            onChange={(e) =>
              setForm({ ...form, jurisdiction: e.target.value })
            }
            className={inputCls}
            placeholder="AE-DU"
            maxLength={16}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.broker.email', { defaultValue: 'Contact email' })}
        >
          <input
            type="email"
            value={form.contact_email}
            onChange={(e) =>
              setForm({ ...form, contact_email: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.broker.phone', { defaultValue: 'Contact phone' })}
        >
          <input
            value={form.contact_phone ?? ''}
            onChange={(e) =>
              setForm({ ...form, contact_phone: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.broker.commission', {
            defaultValue: 'Default commission %',
          })}
        >
          <input
            type="number"
            min={0}
            max={100}
            step="0.01"
            value={form.default_commission_pct}
            onChange={(e) =>
              setForm({ ...form, default_commission_pct: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.broker.active', { defaultValue: 'Active' })}
        >
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(e) => setForm({ ...form, active: e.target.checked })}
            />
            {t('propdev.broker.active_help', {
              defaultValue: 'Eligible for new agreements & accruals',
            })}
          </label>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─────────────────────────── Price Matrix ───────────────────────── */

const PRICE_MATRIX_STATUS_VARIANT: Record<
  PriceMatrixStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  draft: 'neutral',
  active: 'success',
  expired: 'warning',
  archived: 'error',
};

export function PriceMatrixTab({
  developmentId,
  plots,
  defaultCurrency,
}: {
  developmentId: string;
  plots: Plot[];
  defaultCurrency?: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<PriceMatrix | null>(null);
  const [deleting, setDeleting] = useState<PriceMatrix | null>(null);
  const [previewing, setPreviewing] = useState<PriceMatrix | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  useSubEntityCreateBroadcast('price_matrix', () => setCreateOpen(true));

  const matricesQ = useQuery({
    queryKey: ['propdev', 'price-matrices', developmentId],
    queryFn: () => listPriceMatrices(developmentId),
    enabled: !!developmentId,
  });
  const matrices = matricesQ.data ?? [];

  const activateMu = useMutation({
    mutationFn: (id: string) => activatePriceMatrix(id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.matrix_activated', {
          defaultValue: 'Matrix activated',
        }),
      });
      qc.invalidateQueries({
        queryKey: ['propdev', 'price-matrices', developmentId],
      });
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMu = useMutation({
    mutationFn: (id: string) => deletePriceMatrix(id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.matrix_deleted', {
          defaultValue: 'Matrix deleted',
        }),
      });
      qc.invalidateQueries({
        queryKey: ['propdev', 'price-matrices', developmentId],
      });
      setDeleting(null);
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const recomputeMu = useMutation({
    mutationFn: (id: string) => bulkRecomputePrices(id),
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('propdev.matrix_recomputed', {
          defaultValue:
            'Recomputed: {{updated}} updated, {{unchanged}} unchanged',
          updated: res.plots_updated,
          unchanged: res.plots_unchanged,
        }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!developmentId) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Calculator size={22} />}
          title={t('propdev.select_development', {
            defaultValue: 'Select a development',
          })}
          description={t('propdev.matrix_select_dev_desc', {
            defaultValue:
              'Pick a development to manage its price matrices.',
          })}
        />
      </Card>
    );
  }

  if (matricesQ.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={5} />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {matrices.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<Calculator size={22} />}
            title={t('propdev.no_matrix', {
              defaultValue: 'No price matrix yet',
            })}
            description={t('propdev.no_matrix_desc', {
              defaultValue:
                'A Price Matrix sets a base €/m² rate and rules (floor premium, view, orientation, …) used to auto-suggest plot prices.',
            })}
            action={{
              label: t('propdev.new_price_matrix', {
                defaultValue: 'New Price Matrix',
              }),
              onClick: () => setCreateOpen(true),
            }}
          />
        </Card>
      ) : (
        <Card padding="md">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-content-tertiary border-b border-border-light">
                <tr>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.matrix.name', { defaultValue: 'Name' })}
                  </th>
                  <th className="text-right py-2 pr-3">
                    {t('propdev.matrix.base_price', {
                      defaultValue: 'Base €/m²',
                    })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.matrix.currency', {
                      defaultValue: 'Currency',
                    })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.matrix.effective', {
                      defaultValue: 'Effective',
                    })}
                  </th>
                  <th className="text-right py-2 pr-3">
                    {t('propdev.matrix.rules', { defaultValue: 'Rules' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.matrix.status', { defaultValue: 'Status' })}
                  </th>
                  <th className="text-right py-2 pr-2">
                    {t('common.actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {matrices.map((m) => (
                  <tr
                    key={m.id}
                    className="border-b border-border-light/60 hover:bg-surface-secondary/50"
                  >
                    <td className="py-2 pr-3 font-medium">{m.name}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {toNumber(m.base_price_per_m2).toFixed(2)}
                    </td>
                    <td className="py-2 pr-3 text-xs">{m.currency}</td>
                    <td className="py-2 pr-3 text-xs">
                      <DateDisplay value={m.effective_from} />
                      {m.effective_to && (
                        <>
                          {' → '}
                          <DateDisplay value={m.effective_to} />
                        </>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {m.rules.length}
                    </td>
                    <td className="py-2 pr-3">
                      <Badge
                        variant={PRICE_MATRIX_STATUS_VARIANT[m.status]}
                        dot
                      >
                        {m.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-2 text-right">
                      <div className="inline-flex gap-1 flex-wrap justify-end">
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Calculator size={12} />}
                          onClick={() => setPreviewing(m)}
                          aria-label={t('propdev.matrix.preview', {
                            defaultValue: 'Preview on plot',
                          })}
                          title={t('propdev.matrix.preview', {
                            defaultValue: 'Preview on plot',
                          })}
                        />
                        {m.status === 'draft' && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => activateMu.mutate(m.id)}
                            disabled={activateMu.isPending}
                            title={t('propdev.matrix.activate', {
                              defaultValue: 'Activate',
                            })}
                          >
                            {t('propdev.matrix.activate', {
                              defaultValue: 'Activate',
                            })}
                          </Button>
                        )}
                        {m.status === 'active' && (
                          <Button
                            size="sm"
                            variant="primary"
                            icon={<ArrowRightCircle size={12} />}
                            onClick={async () => {
                              const ok = await confirm({
                                title: t('propdev.matrix.apply_title', {
                                  defaultValue: 'Apply price matrix?',
                                }),
                                message: t('propdev.matrix.apply_confirm', {
                                  defaultValue:
                                    'Apply this matrix to every plot in the development? Plot prices will be overwritten.',
                                }),
                                confirmLabel: t('propdev.matrix.apply', {
                                  defaultValue: 'Apply to all plots',
                                }),
                                variant: 'warning',
                              });
                              if (!ok) return;
                              recomputeMu.mutate(m.id);
                            }}
                            disabled={recomputeMu.isPending}
                            loading={recomputeMu.isPending}
                            title={t('propdev.matrix.apply', {
                              defaultValue: 'Apply to all plots',
                            })}
                          >
                            {t('propdev.matrix.apply', {
                              defaultValue: 'Apply',
                            })}
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Pencil size={12} />}
                          onClick={() => setEditing(m)}
                          aria-label={t('common.edit', {
                            defaultValue: 'Edit',
                          })}
                        />
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Trash2 size={12} />}
                          onClick={() => setDeleting(m)}
                          aria-label={t('common.delete', {
                            defaultValue: 'Delete',
                          })}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {createOpen && (
        <PriceMatrixFormModal
          developmentId={developmentId}
          defaultCurrency={defaultCurrency}
          onClose={() => setCreateOpen(false)}
          onSaved={() =>
            qc.invalidateQueries({
              queryKey: ['propdev', 'price-matrices', developmentId],
            })
          }
        />
      )}
      {editing && (
        <PriceMatrixFormModal
          developmentId={developmentId}
          defaultCurrency={defaultCurrency}
          matrix={editing}
          onClose={() => setEditing(null)}
          onSaved={() =>
            qc.invalidateQueries({
              queryKey: ['propdev', 'price-matrices', developmentId],
            })
          }
        />
      )}
      {deleting && (
        <ConfirmDialog
          open
          title={t('propdev.delete_matrix', {
            defaultValue: 'Delete price matrix?',
          })}
          message={t('propdev.delete_matrix_confirm', {
            defaultValue:
              'Delete "{{name}}"? Existing computed plot prices will remain frozen at their last value.',
            name: deleting.name,
          })}
          confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
          variant="danger"
          loading={deleteMu.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteMu.mutate(deleting.id)}
        />
      )}
      {previewing && (
        <PriceMatrixPreviewModal
          matrix={previewing}
          plots={plots}
          onClose={() => setPreviewing(null)}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

function PriceMatrixFormModal({
  developmentId,
  matrix,
  defaultCurrency,
  onClose,
  onSaved,
}: {
  developmentId: string;
  matrix?: PriceMatrix;
  defaultCurrency?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const editing = !!matrix;
  const [form, setForm] = useState({
    name: matrix?.name ?? '',
    base_price_per_m2:
      matrix?.base_price_per_m2 != null
        ? String(matrix.base_price_per_m2)
        : '0',
    currency: matrix?.currency ?? defaultCurrency ?? '',
    effective_from: matrix?.effective_from ?? todayIso(),
    effective_to: matrix?.effective_to ?? '',
    status: (matrix?.status ?? 'draft') as PriceMatrixStatus,
  });
  const [rules, setRules] = useState<PriceMatrixRule[]>(
    (matrix?.rules as PriceMatrixRule[] | undefined) ?? [],
  );

  const saveMu = useMutation({
    mutationFn: async () => {
      const basePrice = Number(form.base_price_per_m2);
      if (!Number.isFinite(basePrice) || basePrice < 0) {
        throw new Error(
          t('propdev.matrix.base_price_invalid', {
            defaultValue: 'Base price must be a non-negative number',
          }),
        );
      }
      if (editing && matrix) {
        return updatePriceMatrix(matrix.id, {
          name: form.name,
          base_price_per_m2: basePrice,
          currency: form.currency,
          effective_from: form.effective_from,
          effective_to: form.effective_to || null,
          rules,
          status: form.status,
        });
      }
      return createPriceMatrix({
        development_id: developmentId,
        name: form.name,
        base_price_per_m2: basePrice,
        currency: form.currency,
        effective_from: form.effective_from,
        effective_to: form.effective_to || undefined,
        rules,
        status: form.status,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: editing
          ? t('propdev.matrix_updated', { defaultValue: 'Matrix updated' })
          : t('propdev.matrix_created', { defaultValue: 'Matrix created' }),
      });
      onSaved();
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  function updateRule(idx: number, patch: Partial<PriceMatrixRule>) {
    setRules((prev) =>
      prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)),
    );
  }

  function addRule() {
    setRules((prev) => [
      ...prev,
      {
        factor_type: 'floor',
        condition: { floor_min: 1, floor_max: 10 },
        multiplier: '1.0',
      },
    ]);
  }

  function removeRule(idx: number) {
    setRules((prev) => prev.filter((_, i) => i !== idx));
  }

  const canSubmit =
    form.name.trim().length > 0 && form.currency.length >= 3;

  return (
    <WideModal
      open
      onClose={onClose}
      title={
        editing
          ? t('propdev.edit_matrix', {
              defaultValue: 'Edit price matrix',
            })
          : t('propdev.new_price_matrix', {
              defaultValue: 'New price matrix',
            })
      }
      size="lg"
      busy={saveMu.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={saveMu.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => saveMu.mutate()}
            loading={saveMu.isPending}
            disabled={!canSubmit}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('propdev.matrix.name', { defaultValue: 'Name' })}
          required
          span={2}
        >
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
            placeholder="Launch wave 2026-Q3"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.matrix.base_price', {
            defaultValue: 'Base €/m²',
          })}
          required
        >
          <input
            type="number"
            min={0}
            step="0.01"
            value={form.base_price_per_m2}
            onChange={(e) =>
              setForm({ ...form, base_price_per_m2: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.matrix.currency', {
            defaultValue: 'Currency',
          })}
          required
        >
          <input
            value={form.currency}
            onChange={(e) =>
              setForm({
                ...form,
                currency: e.target.value.toUpperCase().slice(0, 3),
              })
            }
            className={inputCls}
            maxLength={3}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.matrix.effective_from', {
            defaultValue: 'Effective from',
          })}
          required
        >
          <input
            type="date"
            value={form.effective_from}
            onChange={(e) =>
              setForm({ ...form, effective_from: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.matrix.effective_to', {
            defaultValue: 'Effective to',
          })}
        >
          <input
            type="date"
            value={form.effective_to}
            onChange={(e) =>
              setForm({ ...form, effective_to: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.matrix.status', { defaultValue: 'Status' })}
          span={2}
        >
          <select
            value={form.status}
            onChange={(e) =>
              setForm({
                ...form,
                status: e.target.value as PriceMatrixStatus,
              })
            }
            className={inputCls}
          >
            <option value="draft">draft</option>
            <option value="active">active</option>
            <option value="expired">expired</option>
            <option value="archived">archived</option>
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        columns={1}
        title={t('propdev.matrix.rules_title', { defaultValue: 'Rules' })}
        description={t('propdev.matrix.rules_help', {
          defaultValue:
            'Multipliers applied on top of the base €/m² (e.g. floor premium 1.05, sea view 1.15). Multipliers compound.',
        })}
      >
        <div className="space-y-2">
          {rules.length === 0 && (
            <p className="text-xs text-content-tertiary italic">
              {t('propdev.matrix.no_rules', {
                defaultValue: 'No rules - every plot prices at the base rate.',
              })}
            </p>
          )}
          {rules.map((r, i) => (
            <div
              key={i}
              className="grid grid-cols-12 gap-2 items-center bg-surface-secondary/50 rounded-md p-2"
            >
              <select
                value={r.factor_type}
                onChange={(e) =>
                  updateRule(i, {
                    factor_type: e.target.value as PriceMatrixRule['factor_type'],
                  })
                }
                className={clsx(inputCls, 'col-span-3 h-8 text-xs')}
              >
                <option value="floor">floor</option>
                <option value="view">view</option>
                <option value="orientation">orientation</option>
                <option value="corner">corner</option>
                <option value="launch_discount">launch_discount</option>
                <option value="phase_escalator">phase_escalator</option>
              </select>
              <input
                value={JSON.stringify(r.condition ?? {})}
                onChange={(e) => {
                  try {
                    const obj = JSON.parse(e.target.value);
                    if (obj && typeof obj === 'object')
                      updateRule(i, { condition: obj });
                  } catch {
                    // ignore — partial JSON while typing
                  }
                }}
                className={clsx(
                  inputCls,
                  'col-span-6 h-8 text-xs font-mono',
                )}
                placeholder='{"floor_min":1,"floor_max":10}'
              />
              <input
                type="number"
                step="0.0001"
                min={0.0001}
                value={String(r.multiplier)}
                onChange={(e) =>
                  updateRule(i, { multiplier: e.target.value })
                }
                className={clsx(
                  inputCls,
                  'col-span-2 h-8 text-xs tabular-nums',
                )}
              />
              <button
                type="button"
                onClick={() => removeRule(i)}
                className="col-span-1 text-content-tertiary hover:text-red-600"
                aria-label={t('common.remove', { defaultValue: 'Remove' })}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <Button
            size="sm"
            variant="ghost"
            icon={<Plus size={12} />}
            onClick={addRule}
          >
            {t('propdev.matrix.add_rule', { defaultValue: 'Add rule' })}
          </Button>
        </div>
      </WideModalSection>
    </WideModal>
  );
}

function PriceMatrixPreviewModal({
  matrix,
  plots,
  onClose,
}: {
  matrix: PriceMatrix;
  plots: Plot[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [plotId, setPlotId] = useState<string>(plots[0]?.id ?? '');

  const previewQ = useQuery({
    queryKey: ['propdev', 'matrix-preview', matrix.id, plotId],
    queryFn: () => previewPriceOnPlot(matrix.id, plotId),
    enabled: !!plotId,
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('propdev.matrix.preview_title', {
        defaultValue: 'Preview matrix on plot',
      })}
      size="md"
      footer={
        <Button variant="primary" onClick={onClose}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('propdev.matrix.preview_plot', {
            defaultValue: 'Plot',
          })}
        >
          <select
            value={plotId}
            onChange={(e) => setPlotId(e.target.value)}
            className={inputCls}
          >
            {plots.length === 0 && <option value="">- no plots -</option>}
            {plots.map((p) => (
              <option key={p.id} value={p.id}>
                {p.plot_number} — {toNumber(p.area_m2)} m²
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection columns={1}>
        {!plotId ? (
          <p className="text-sm text-content-tertiary">
            {t('propdev.matrix.preview_no_plot', {
              defaultValue: 'Pick a plot to compute the suggested price.',
            })}
          </p>
        ) : previewQ.isLoading ? (
          <p className="text-sm text-content-tertiary">
            {t('common.loading', { defaultValue: 'Loading…' })}
          </p>
        ) : previewQ.isError ? (
          <p className="text-sm text-red-600">
            {getErrorMessage(previewQ.error)}
          </p>
        ) : previewQ.data ? (
          <div className="space-y-2 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <div className="text-content-tertiary">
                {t('propdev.matrix.preview.area', { defaultValue: 'Area' })}
              </div>
              <div className="text-right tabular-nums">
                {toNumber(previewQ.data.area_m2)} m²
              </div>
              <div className="text-content-tertiary">
                {t('propdev.matrix.preview.base_rate', {
                  defaultValue: 'Base €/m²',
                })}
              </div>
              <div className="text-right tabular-nums">
                {toNumber(previewQ.data.base_price_per_m2).toFixed(2)}{' '}
                {previewQ.data.currency}
              </div>
              <div className="text-content-tertiary">
                {t('propdev.matrix.preview.base_price', {
                  defaultValue: 'Base price',
                })}
              </div>
              <div className="text-right tabular-nums">
                {toNumber(previewQ.data.base_price).toFixed(2)}{' '}
                {previewQ.data.currency}
              </div>
              <div className="text-content-tertiary">
                {t('propdev.matrix.preview.multiplier', {
                  defaultValue: 'Combined multiplier',
                })}
              </div>
              <div className="text-right tabular-nums">
                ×{toNumber(previewQ.data.combined_multiplier).toFixed(4)}
              </div>
              <div className="font-semibold">
                {t('propdev.matrix.preview.final', {
                  defaultValue: 'Final price',
                })}
              </div>
              <div className="text-right font-semibold tabular-nums">
                <MoneyDisplay
                  amount={toNumber(previewQ.data.final_price)}
                  currency={previewQ.data.currency}
                />
              </div>
            </div>
            {previewQ.data.applied_rules.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-content-secondary">
                  {t('propdev.matrix.preview.applied_rules', {
                    defaultValue: 'Applied rules ({{n}})',
                    n: previewQ.data.applied_rules.length,
                  })}
                </summary>
                <ul className="mt-1 space-y-1 font-mono text-content-tertiary">
                  {previewQ.data.applied_rules.map((r, i) => (
                    <li key={i}>
                      {r.factor_type}: ×{r.multiplier}{' '}
                      {JSON.stringify(r.condition)}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        ) : null}
      </WideModalSection>
    </WideModal>
  );
}

/* ───────────────────────────── Escrow ───────────────────────────── */

export function EscrowTab({
  developmentId,
  defaultCurrency,
}: {
  developmentId: string;
  defaultCurrency?: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<EscrowAccount | null>(null);
  const [deleting, setDeleting] = useState<EscrowAccount | null>(null);
  const [activeAccountId, setActiveAccountId] = useState<string | null>(null);

  useSubEntityCreateBroadcast('escrow', () => setCreateOpen(true));

  const accountsQ = useQuery({
    queryKey: ['propdev', 'escrow-accounts', developmentId],
    queryFn: () => listEscrowAccounts(developmentId),
    enabled: !!developmentId,
  });
  const accounts = accountsQ.data ?? [];

  const deleteMu = useMutation({
    mutationFn: (id: string) => deleteEscrowAccount(id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.escrow_deleted', {
          defaultValue: 'Escrow account deleted',
        }),
      });
      qc.invalidateQueries({
        queryKey: ['propdev', 'escrow-accounts', developmentId],
      });
      setDeleting(null);
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!developmentId) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Landmark size={22} />}
          title={t('propdev.select_development', {
            defaultValue: 'Select a development',
          })}
          description={t('propdev.escrow_select_dev_desc', {
            defaultValue:
              'Pick a development to manage its escrow accounts.',
          })}
        />
      </Card>
    );
  }

  if (accountsQ.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={3} columns={5} />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {accounts.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<Landmark size={22} />}
            title={t('propdev.no_escrow', {
              defaultValue: 'No escrow accounts yet',
            })}
            description={t('propdev.no_escrow_desc', {
              defaultValue:
                'Buyer deposits and installments must be held in a regulator-supervised escrow account (RERA, MahaRERA, 214-FZ, …).',
            })}
            action={{
              label: t('propdev.new_escrow_account', {
                defaultValue: 'New Escrow Account',
              }),
              onClick: () => setCreateOpen(true),
            }}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {accounts.map((a) => (
            <EscrowAccountCard
              key={a.id}
              account={a}
              onEdit={() => setEditing(a)}
              onDelete={() => setDeleting(a)}
              onOpenTransactions={() => setActiveAccountId(a.id)}
            />
          ))}
        </div>
      )}

      {createOpen && (
        <EscrowAccountFormModal
          developmentId={developmentId}
          defaultCurrency={defaultCurrency}
          onClose={() => setCreateOpen(false)}
          onSaved={() =>
            qc.invalidateQueries({
              queryKey: ['propdev', 'escrow-accounts', developmentId],
            })
          }
        />
      )}
      {editing && (
        <EscrowAccountFormModal
          developmentId={developmentId}
          defaultCurrency={defaultCurrency}
          account={editing}
          onClose={() => setEditing(null)}
          onSaved={() =>
            qc.invalidateQueries({
              queryKey: ['propdev', 'escrow-accounts', developmentId],
            })
          }
        />
      )}
      {deleting && (
        <ConfirmDialog
          open
          title={t('propdev.delete_escrow', {
            defaultValue: 'Delete escrow account?',
          })}
          message={t('propdev.delete_escrow_confirm', {
            defaultValue:
              'Delete escrow account at "{{bank}}"? All recorded transactions will also be removed.',
            bank:
              deleting.bank_name ||
              deleting.iban ||
              deleting.regulator_account_number,
          })}
          confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
          variant="danger"
          loading={deleteMu.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteMu.mutate(deleting.id)}
        />
      )}
      {activeAccountId && (
        <EscrowTransactionsDrawer
          accountId={activeAccountId}
          account={accounts.find((a) => a.id === activeAccountId)}
          onClose={() => setActiveAccountId(null)}
        />
      )}
    </div>
  );
}

function EscrowAccountCard({
  account,
  onEdit,
  onDelete,
  onOpenTransactions,
}: {
  account: EscrowAccount;
  onEdit: () => void;
  onDelete: () => void;
  onOpenTransactions: () => void;
}) {
  const { t } = useTranslation();
  const balanceQ = useQuery({
    queryKey: ['propdev', 'escrow-balance', account.id],
    queryFn: () => getEscrowBalance(account.id),
    staleTime: 30_000,
  });
  return (
    <Card padding="md">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Landmark size={14} className="text-content-tertiary" />
            <h3 className="font-semibold truncate">
              {account.bank_name ||
                account.iban ||
                account.regulator_account_number}
            </h3>
            <Badge variant={account.is_active ? 'success' : 'neutral'} dot>
              {account.is_active
                ? t('propdev.escrow.active', { defaultValue: 'Active' })
                : t('propdev.escrow.closed', { defaultValue: 'Closed' })}
            </Badge>
          </div>
          <p className="text-xs text-content-tertiary font-mono">
            {account.iban || '—'}
          </p>
          <p className="text-xs text-content-tertiary">
            {account.regulator_ref.toUpperCase()} · {account.currency}
          </p>
        </div>
        <div className="flex gap-1 flex-shrink-0">
          <Button
            size="sm"
            variant="ghost"
            icon={<Pencil size={12} />}
            onClick={onEdit}
          />
          <Button
            size="sm"
            variant="ghost"
            icon={<Trash2 size={12} />}
            onClick={onDelete}
          />
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="bg-surface-secondary rounded-md p-2">
          <div className="text-content-tertiary">
            {t('propdev.escrow.credit', { defaultValue: 'Credit' })}
          </div>
          <div className="font-semibold tabular-nums">
            {balanceQ.data
              ? toNumber(balanceQ.data.credit_total).toFixed(2)
              : '—'}
          </div>
        </div>
        <div className="bg-surface-secondary rounded-md p-2">
          <div className="text-content-tertiary">
            {t('propdev.escrow.debit', { defaultValue: 'Debit' })}
          </div>
          <div className="font-semibold tabular-nums">
            {balanceQ.data
              ? toNumber(balanceQ.data.debit_total).toFixed(2)
              : '—'}
          </div>
        </div>
        <div className="bg-oe-blue/10 rounded-md p-2">
          <div className="text-content-tertiary">
            {t('propdev.escrow.balance', { defaultValue: 'Balance' })}
          </div>
          <div className="font-bold tabular-nums text-oe-blue">
            {balanceQ.data ? toNumber(balanceQ.data.balance).toFixed(2) : '—'}
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs">
        <span className="text-content-tertiary">
          {balanceQ.data?.transaction_count ?? 0}{' '}
          {t('propdev.escrow.transactions', { defaultValue: 'transactions' })}
          {balanceQ.data && balanceQ.data.unreconciled_count > 0 && (
            <span className="text-amber-600 ml-2">
              · {balanceQ.data.unreconciled_count}{' '}
              {t('propdev.escrow.unreconciled', {
                defaultValue: 'unreconciled',
              })}
            </span>
          )}
        </span>
        <Button
          size="sm"
          variant="secondary"
          icon={<ArrowRight size={12} />}
          onClick={onOpenTransactions}
        >
          {t('propdev.escrow.view_transactions', {
            defaultValue: 'Transactions',
          })}
        </Button>
      </div>
    </Card>
  );
}

function EscrowAccountFormModal({
  developmentId,
  account,
  defaultCurrency,
  onClose,
  onSaved,
}: {
  developmentId: string;
  account?: EscrowAccount;
  defaultCurrency?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const editing = !!account;
  const [form, setForm] = useState({
    regulator_ref: (account?.regulator_ref ?? 'other') as RegulatorRef,
    regulator_account_number: account?.regulator_account_number ?? '',
    bank_name: account?.bank_name ?? '',
    iban: account?.iban ?? '',
    swift_bic: account?.swift_bic ?? '',
    currency: account?.currency ?? defaultCurrency ?? '',
    opened_at: account?.opened_at ?? todayIso(),
    is_active: account?.is_active ?? true,
  });

  const saveMu = useMutation({
    mutationFn: async () => {
      if (editing && account) {
        return updateEscrowAccount(account.id, {
          regulator_account_number: form.regulator_account_number,
          bank_name: form.bank_name,
          iban: form.iban,
          swift_bic: form.swift_bic,
          is_active: form.is_active,
        });
      }
      return createEscrowAccount({
        development_id: developmentId,
        regulator_ref: form.regulator_ref,
        regulator_account_number: form.regulator_account_number,
        bank_name: form.bank_name,
        iban: form.iban,
        swift_bic: form.swift_bic,
        currency: form.currency,
        opened_at: form.opened_at,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: editing
          ? t('propdev.escrow_updated', { defaultValue: 'Account updated' })
          : t('propdev.escrow_created', { defaultValue: 'Account created' }),
      });
      onSaved();
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={
        editing
          ? t('propdev.edit_escrow_account', {
              defaultValue: 'Edit escrow account',
            })
          : t('propdev.new_escrow_account', {
              defaultValue: 'New escrow account',
            })
      }
      size="md"
      busy={saveMu.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={saveMu.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => saveMu.mutate()}
            loading={saveMu.isPending}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('propdev.escrow.regulator', { defaultValue: 'Regulator' })}
          required
        >
          <select
            value={form.regulator_ref}
            onChange={(e) =>
              setForm({
                ...form,
                regulator_ref: e.target.value as RegulatorRef,
              })
            }
            className={inputCls}
            disabled={editing}
          >
            <option value="rera_dubai">RERA Dubai</option>
            <option value="rera_abu_dhabi">RERA Abu Dhabi</option>
            <option value="maharera">MahaRERA</option>
            <option value="214_FZ_RU">214-FZ (RU)</option>
            <option value="cma_saudi">CMA Saudi</option>
            <option value="section32_au">Section 32 (AU)</option>
            <option value="other">Other</option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.account_number', {
            defaultValue: 'Regulator acct #',
          })}
        >
          <input
            value={form.regulator_account_number}
            onChange={(e) =>
              setForm({
                ...form,
                regulator_account_number: e.target.value,
              })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.bank', { defaultValue: 'Bank name' })}
          span={2}
        >
          <input
            value={form.bank_name}
            onChange={(e) => setForm({ ...form, bank_name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.iban', { defaultValue: 'IBAN' })}
        >
          <input
            value={form.iban}
            onChange={(e) =>
              setForm({ ...form, iban: e.target.value.toUpperCase() })
            }
            className={clsx(inputCls, 'font-mono')}
            maxLength={40}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.swift', { defaultValue: 'SWIFT/BIC' })}
        >
          <input
            value={form.swift_bic}
            onChange={(e) =>
              setForm({ ...form, swift_bic: e.target.value.toUpperCase() })
            }
            className={inputCls}
            maxLength={11}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.currency', { defaultValue: 'Currency' })}
          required
        >
          <input
            value={form.currency}
            onChange={(e) =>
              setForm({
                ...form,
                currency: e.target.value.toUpperCase().slice(0, 3),
              })
            }
            className={inputCls}
            maxLength={3}
            disabled={editing}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.opened_at', { defaultValue: 'Opened at' })}
          required
        >
          <input
            type="date"
            value={form.opened_at}
            onChange={(e) =>
              setForm({ ...form, opened_at: e.target.value })
            }
            className={inputCls}
            disabled={editing}
          />
        </WideModalField>
        {editing && (
          <WideModalField
            label={t('propdev.escrow.active', { defaultValue: 'Active' })}
            span={2}
          >
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) =>
                  setForm({ ...form, is_active: e.target.checked })
                }
              />
              {t('propdev.escrow.active_help', {
                defaultValue: 'Open & accepting deposits',
              })}
            </label>
          </WideModalField>
        )}
      </WideModalSection>
    </WideModal>
  );
}

function EscrowTransactionsDrawer({
  accountId,
  account,
  onClose,
}: {
  accountId: string;
  account: EscrowAccount | undefined;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [addOpen, setAddOpen] = useState(false);

  const txQ = useQuery({
    queryKey: ['propdev', 'escrow-transactions', accountId],
    queryFn: () => listEscrowTransactions({ escrow_account_id: accountId }),
  });
  const txs = txQ.data ?? [];

  const reconcileMu = useMutation({
    mutationFn: ({ id, ref }: { id: string; ref: string }) =>
      reconcileEscrowTransaction(id, ref),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.escrow.reconciled', {
          defaultValue: 'Reconciled',
        }),
      });
      qc.invalidateQueries({
        queryKey: ['propdev', 'escrow-transactions', accountId],
      });
      qc.invalidateQueries({
        queryKey: ['propdev', 'escrow-balance', accountId],
      });
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={t('propdev.escrow.transactions_title', {
        defaultValue: 'Escrow transactions',
      })}
      widthClass="max-w-2xl"
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-content-tertiary">
            {account?.bank_name || account?.iban} · {account?.currency}
          </p>
          <Button
            size="sm"
            variant="primary"
            icon={<Plus size={12} />}
            onClick={() => setAddOpen(true)}
          >
            {t('propdev.escrow.new_tx', { defaultValue: 'New transaction' })}
          </Button>
        </div>

        {txQ.isLoading ? (
          <SkeletonTable rows={5} columns={4} />
        ) : txs.length === 0 ? (
          <EmptyState
            icon={<Wallet size={20} />}
            title={t('propdev.escrow.no_tx', {
              defaultValue: 'No transactions yet',
            })}
            description={t('propdev.escrow.no_tx_desc', {
              defaultValue:
                'Record buyer installments, bank charges, and developer draw requests against this account.',
            })}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-content-tertiary border-b border-border-light">
                <tr>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.escrow.tx_date', { defaultValue: 'Date' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.escrow.tx_dir', { defaultValue: 'Dir' })}
                  </th>
                  <th className="text-right py-2 pr-3">
                    {t('propdev.escrow.tx_amount', { defaultValue: 'Amount' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.escrow.tx_source', { defaultValue: 'Source' })}
                  </th>
                  <th className="text-left py-2 pr-3">
                    {t('propdev.escrow.tx_state', {
                      defaultValue: 'Reconciled',
                    })}
                  </th>
                  <th className="text-right py-2 pr-2"></th>
                </tr>
              </thead>
              <tbody>
                {txs.map((tx) => (
                  <tr key={tx.id} className="border-b border-border-light/60">
                    <td className="py-2 pr-3 text-xs">
                      <DateDisplay value={tx.transaction_date} />
                    </td>
                    <td className="py-2 pr-3">
                      <Badge
                        variant={
                          tx.direction === 'credit' ? 'success' : 'warning'
                        }
                        dot
                      >
                        {tx.direction}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {toNumber(tx.amount).toFixed(2)} {tx.currency}
                    </td>
                    <td className="py-2 pr-3 text-xs">{tx.source_type}</td>
                    <td className="py-2 pr-3 text-xs">
                      <Badge
                        variant={
                          tx.reconciliation_state === 'matched'
                            ? 'success'
                            : tx.reconciliation_state === 'disputed'
                              ? 'error'
                              : 'neutral'
                        }
                        dot
                      >
                        {tx.reconciliation_state}
                      </Badge>
                    </td>
                    <td className="py-2 pr-2 text-right">
                      {tx.reconciliation_state === 'unreconciled' && (
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Check size={12} />}
                          onClick={() => {
                            const ref = window.prompt(
                              t('propdev.escrow.bank_ref_prompt', {
                                defaultValue:
                                  'Bank reference for this transaction:',
                              }),
                              tx.bank_reference ?? '',
                            );
                            if (ref && ref.trim()) {
                              reconcileMu.mutate({
                                id: tx.id,
                                ref: ref.trim(),
                              });
                            }
                          }}
                          title={t('propdev.escrow.reconcile', {
                            defaultValue: 'Reconcile',
                          })}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {addOpen && account && (
          <EscrowTransactionFormModal
            account={account}
            onClose={() => setAddOpen(false)}
            onSaved={() => {
              qc.invalidateQueries({
                queryKey: ['propdev', 'escrow-transactions', accountId],
              });
              qc.invalidateQueries({
                queryKey: ['propdev', 'escrow-balance', accountId],
              });
            }}
          />
        )}
      </div>
    </SideDrawer>
  );
}

function EscrowTransactionFormModal({
  account,
  onClose,
  onSaved,
}: {
  account: EscrowAccount;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    direction: 'credit' as EscrowDirection,
    amount: '0',
    source_type: 'instalment' as EscrowSourceType,
    source_reference: '',
    transaction_date: todayIso(),
  });

  const saveMu = useMutation({
    mutationFn: async () => {
      const amount = Number(form.amount);
      if (!Number.isFinite(amount) || amount <= 0) {
        throw new Error(
          t('propdev.escrow.amount_invalid', {
            defaultValue: 'Amount must be greater than 0',
          }),
        );
      }
      return createEscrowTransaction({
        escrow_account_id: account.id,
        direction: form.direction,
        amount,
        currency: account.currency,
        source_type: form.source_type,
        source_reference: form.source_reference || undefined,
        transaction_date: form.transaction_date,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.escrow_tx_created', {
          defaultValue: 'Transaction recorded',
        }),
      });
      onSaved();
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('propdev.escrow.new_tx', { defaultValue: 'New transaction' })}
      size="md"
      busy={saveMu.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={saveMu.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => saveMu.mutate()}
            loading={saveMu.isPending}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('propdev.escrow.tx_dir', { defaultValue: 'Direction' })}
        >
          <select
            value={form.direction}
            onChange={(e) =>
              setForm({
                ...form,
                direction: e.target.value as EscrowDirection,
              })
            }
            className={inputCls}
          >
            <option value="credit">
              {t('propdev.escrow.dir.credit', {
                defaultValue: 'Credit (in)',
              })}
            </option>
            <option value="debit">
              {t('propdev.escrow.dir.debit', {
                defaultValue: 'Debit (out)',
              })}
            </option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.tx_source', { defaultValue: 'Source' })}
        >
          <select
            value={form.source_type}
            onChange={(e) =>
              setForm({
                ...form,
                source_type: e.target.value as EscrowSourceType,
              })
            }
            className={inputCls}
          >
            <option value="instalment">instalment</option>
            <option value="refund">refund</option>
            <option value="draw_request">draw_request</option>
            <option value="bank_charge">bank_charge</option>
            <option value="interest">interest</option>
            <option value="transfer">transfer</option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.tx_amount', { defaultValue: 'Amount' })}
          required
        >
          <input
            type="number"
            min={0.01}
            step="0.01"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.currency', { defaultValue: 'Currency' })}
        >
          <input value={account.currency} className={inputCls} disabled />
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.tx_date', {
            defaultValue: 'Transaction date',
          })}
          required
        >
          <input
            type="date"
            value={form.transaction_date}
            onChange={(e) =>
              setForm({ ...form, transaction_date: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.escrow.tx_ref', { defaultValue: 'Reference' })}
        >
          <input
            value={form.source_reference}
            onChange={(e) =>
              setForm({ ...form, source_reference: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
