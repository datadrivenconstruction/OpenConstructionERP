import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Leaf,
  Target,
  FileText,
  Database,
  X,
  Plus,
  Loader2,
  TrendingDown,
  CheckCircle2,
  AlertTriangle,
  AlertOctagon,
  ChevronRight,
  Pencil,
  Trash2,
  FileSpreadsheet,
  Search,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  ConfirmDialog,
  DismissibleInfo,
  IntroRichText,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import {
  listInventories,
  getInventory,
  getInventoryTotals,
  listEmbodiedEntries,
  listScope1,
  listScope2,
  listScope3,
  listEPDs,
  listTargets,
  listReports,
  createInventory,
  updateInventory,
  deleteInventory,
  createTarget,
  updateTarget,
  deleteTarget,
  generateReport,
  deleteReport,
  getTargetProgress,
  getAlternatives,
  createEmbodiedEntry,
  updateEmbodiedEntry,
  deleteEmbodiedEntry,
  createScope1,
  updateScope1,
  deleteScope1,
  createScope2,
  updateScope2,
  deleteScope2,
  createScope3,
  updateScope3,
  deleteScope3,
  createEPD,
  updateEPD,
  deleteEPD,
  listMaterialFactors,
  assignBoqPosition,
  type CarbonInventory,
  type InventoryStatus,
  type EPDRecord,
  type EPDSource,
  type CarbonTarget,
  type TargetStatus,
  type SustainabilityReport,
  type EmbodiedEntry,
  type Stage,
  type Scope1Entry,
  type Scope2Entry,
  type Scope3Entry,
  type MaterialCarbonFactor,
} from './api';

type Tab = 'inventory' | 'epds' | 'targets' | 'reports';

interface Project {
  id: string;
  name: string;
  description?: string;
  currency?: string;
}

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  if (typeof v === 'number') return v;
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

function formatKg(kg: number): string {
  if (Math.abs(kg) >= 1_000_000) return `${(kg / 1_000_000).toFixed(2)} kt`;
  if (Math.abs(kg) >= 1_000) return `${(kg / 1_000).toFixed(2)} t`;
  return `${kg.toFixed(0)} kg`;
}

function todayIso(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

/** Close a drawer/modal when the user presses Escape (matches WideModal UX). */
function useEscapeToClose(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
}

/* ─── Page ─── */

export function CarbonPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('inventory');
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [inventoryDrawerId, setInventoryDrawerId] = useState<string | null>(null);
  const [createInvOpen, setCreateInvOpen] = useState(false);
  const [createTargetOpen, setCreateTargetOpen] = useState(false);
  const [generateReportOpen, setGenerateReportOpen] = useState(false);
  const [createEpdOpen, setCreateEpdOpen] = useState(false);

  const projectsQ = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/').catch(() => []),
    staleTime: 5 * 60_000,
  });
  const projects = projectsQ.data ?? [];
  // Project selection lives in the global top-bar selector. Fall back to the
  // first project only when nothing is active yet.
  const effectiveProjectId = activeProjectId || projects[0]?.id || '';
  const effectiveProject = projects.find((p) => p.id === effectiveProjectId);

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(effectiveProject
            ? [{ label: effectiveProject.name, to: `/projects/${effectiveProject.id}` }]
            : []),
          { label: t('nav.carbon', { defaultValue: 'Carbon & ESG' }) },
        ]}
      />

      <PageHeader
        srTitle={t('nav.carbon', { defaultValue: 'Carbon & ESG' })}
        subtitle={t('carbon.subtitle', {
          defaultValue:
            'Embodied + scope 1/2/3 emissions, EPDs, reduction targets and GHG reports.',
        })}
        actions={
          <>
            {tab === 'inventory' && (
              <Button
                variant="primary"
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setCreateInvOpen(true)}
                disabled={!effectiveProjectId}
              >
                {t('carbon.new_inventory', { defaultValue: 'New Inventory' })}
              </Button>
            )}
            {tab === 'targets' && (
              <Button
                variant="primary"
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setCreateTargetOpen(true)}
                disabled={!effectiveProjectId}
              >
                {t('carbon.new_target', { defaultValue: 'New Target' })}
              </Button>
            )}
            {tab === 'epds' && (
              <Button
                variant="primary"
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setCreateEpdOpen(true)}
              >
                {t('carbon.new_epd', { defaultValue: 'New EPD' })}
              </Button>
            )}
            {tab === 'reports' && (
              <Button
                variant="primary"
                size="sm"
                icon={<FileText size={14} />}
                onClick={() => setGenerateReportOpen(true)}
                disabled={!effectiveProjectId}
              >
                {t('carbon.generate_report', { defaultValue: 'Generate Report' })}
              </Button>
            )}
          </>
        }
      />

      <DismissibleInfo
        storageKey="carbon"
        title={t('carbon.intro_title', {
          defaultValue: 'Where carbon numbers come from',
        })}
        more={
          t('carbon.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('carbon.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('carbon.intro_link_sustainability', {
              defaultValue: 'Per-BOQ carbon (Sustainability)',
            }),
            onClick: () => navigate('/sustainability'),
          },
          {
            label: t('carbon.intro_link_boq', { defaultValue: 'Open BOQ editor' }),
            onClick: () => navigate('/boq'),
          },
          {
            label: t('carbon.intro_link_costs', { defaultValue: 'Cost database' }),
            onClick: () => navigate('/costs'),
          },
        ]}
      >
        {t('carbon.intro_body', {
          defaultValue:
            'Embodied carbon comes from your Bill of Quantities: each priced position is multiplied by a material carbon factor from EPD sources such as Okobaudat, ICE and EC3, or a manual override. Open an inventory and assign factors to positions to roll up A1 to D embodied emissions, track Scope 1, 2 and 3 operational carbon and reduction targets, then package it all as GHG Protocol, GRI or ISSB reports.',
        })}
      </DismissibleInfo>

      {/* Tabs */}
      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px">
          {(
            [
              {
                id: 'inventory',
                label: t('carbon.tab_inventory', { defaultValue: 'Inventory' }),
                icon: Leaf,
              },
              { id: 'epds', label: t('carbon.tab_epds', { defaultValue: 'EPDs' }), icon: Database },
              {
                id: 'targets',
                label: t('carbon.tab_targets', { defaultValue: 'Targets' }),
                icon: Target,
              },
              {
                id: 'reports',
                label: t('carbon.tab_reports', { defaultValue: 'Reports' }),
                icon: FileText,
              },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((tabItem) => {
            const Icon = tabItem.icon;
            return (
              <button
                key={tabItem.id}
                type="button"
                onClick={() => setTab(tabItem.id)}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                  tab === tabItem.id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {tabItem.label}
              </button>
            );
          })}
        </nav>
      </div>

      {!effectiveProjectId && tab !== 'epds' && (
        <EmptyState
          icon={<Leaf size={22} />}
          title={t('carbon.pick_project', { defaultValue: 'Pick a project' })}
          description={t('carbon.pick_project_desc', {
            defaultValue:
              'Carbon inventories, targets and reports are scoped to a single project. Use the project selector in the top bar to choose one.',
          })}
        />
      )}

      {tab === 'inventory' && effectiveProjectId && (
        <InventoryTab
          projectId={effectiveProjectId}
          onOpenDrawer={(id) => setInventoryDrawerId(id)}
        />
      )}
      {tab === 'epds' && <EPDsTab />}
      {tab === 'targets' && effectiveProjectId && (
        <TargetsTab projectId={effectiveProjectId} />
      )}
      {tab === 'reports' && effectiveProjectId && (
        <ReportsTab projectId={effectiveProjectId} />
      )}

      {inventoryDrawerId && (
        <InventoryDrawer
          inventoryId={inventoryDrawerId}
          onClose={() => setInventoryDrawerId(null)}
        />
      )}

      {createInvOpen && effectiveProjectId && (
        <CreateInventoryModal
          projectId={effectiveProjectId}
          onClose={() => setCreateInvOpen(false)}
        />
      )}
      {createTargetOpen && effectiveProjectId && (
        <CreateTargetModal
          projectId={effectiveProjectId}
          onClose={() => setCreateTargetOpen(false)}
        />
      )}
      {generateReportOpen && effectiveProjectId && (
        <GenerateReportModal
          projectId={effectiveProjectId}
          onClose={() => setGenerateReportOpen(false)}
        />
      )}
      {createEpdOpen && (
        <EPDModal onClose={() => setCreateEpdOpen(false)} />
      )}
    </div>
  );
}

/* ─── Inventory tab ─── */

function InventoryTab({
  projectId,
  onOpenDrawer,
}: {
  projectId: string;
  onOpenDrawer: (id: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, setLoading, ...confirmProps } = useConfirm();
  const [editTarget, setEditTarget] = useState<CarbonInventory | null>(null);
  const q = useQuery({
    queryKey: ['carbon', 'inventories', projectId],
    queryFn: () => listInventories(projectId),
  });
  const list = q.data ?? [];

  async function handleDelete(inv: CarbonInventory) {
    const ok = await confirm({
      title: t('carbon.confirm_delete_inv_title', {
        defaultValue: 'Delete this inventory?',
      }),
      message: t('carbon.confirm_delete_inv_msg', {
        defaultValue:
          'This permanently removes the inventory and all its embodied / scope entries. This cannot be undone.',
      }),
    });
    if (!ok) return;
    setLoading(true);
    try {
      await deleteInventory(inv.id);
      addToast({
        type: 'success',
        title: t('carbon.inv_deleted', { defaultValue: 'Inventory deleted' }),
      });
      qc.invalidateQueries({ queryKey: ['carbon', 'inventories', projectId] });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card padding="none">
        {q.isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={5} columns={5} />
          </div>
        ) : q.isError ? (
          <EmptyState
            icon={<AlertOctagon size={22} />}
            title={t('carbon.load_error', { defaultValue: 'Could not load carbon data' })}
            description={getErrorMessage(q.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => void q.refetch(),
            }}
          />
        ) : list.length === 0 ? (
          <EmptyState
            icon={<Leaf size={22} />}
            title={t('carbon.empty_inventories', {
              defaultValue: 'No carbon inventories yet',
            })}
            description={t('carbon.empty_inventories_desc', {
              defaultValue:
                'Create an inventory to track embodied + scope 1/2/3 emissions for this project.',
            })}
          />
        ) : (
          <InventoryTable
            rows={list}
            onSelect={onOpenDrawer}
            onEdit={(inv) => setEditTarget(inv)}
            onDelete={handleDelete}
          />
        )}
      </Card>
      {editTarget && (
        <CreateInventoryModal
          projectId={projectId}
          inventory={editTarget}
          onClose={() => setEditTarget(null)}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

function RowActions({
  onEdit,
  onDelete,
}: {
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  return (
    <span className="flex items-center justify-end gap-1">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onEdit();
        }}
        className="rounded p-1.5 text-content-tertiary hover:bg-surface-tertiary hover:text-content-primary"
        aria-label={t('common.edit', { defaultValue: 'Edit' })}
        title={t('common.edit', { defaultValue: 'Edit' })}
      >
        <Pencil size={14} />
      </button>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="rounded p-1.5 text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error"
        aria-label={t('common.delete', { defaultValue: 'Delete' })}
        title={t('common.delete', { defaultValue: 'Delete' })}
      >
        <Trash2 size={14} />
      </button>
    </span>
  );
}

function InventoryTable({
  rows,
  onSelect,
  onEdit,
  onDelete,
}: {
  rows: CarbonInventory[];
  onSelect: (id: string) => void;
  onEdit: (inv: CarbonInventory) => void;
  onDelete: (inv: CarbonInventory) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_name', { defaultValue: 'Inventory' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_scope', { defaultValue: 'Scope' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_as_of', { defaultValue: 'As of' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('carbon.col_total', { defaultValue: 'Total' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('carbon.col_actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const total = toNum(
              (r.totals as Record<string, unknown>)['total'] as
                | number
                | string
                | null
                | undefined,
            );
            return (
              <tr
                key={r.id}
                onClick={() => onSelect(r.id)}
                className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
              >
                <td className="px-4 py-2 font-medium text-content-primary">{r.name}</td>
                <td className="px-4 py-2 text-xs text-content-secondary">{r.scope}</td>
                <td className="px-4 py-2">
                  <Badge
                    variant={
                      r.status === 'baseline'
                        ? 'blue'
                        : r.status === 'current'
                          ? 'success'
                          : r.status === 'archived'
                            ? 'neutral'
                            : 'warning'
                    }
                    dot
                    size="sm"
                  >
                    {r.status}
                  </Badge>
                </td>
                <td className="px-4 py-2 text-xs text-content-secondary">
                  {r.as_of_date ? <DateDisplay value={r.as_of_date} /> : '—'}
                </td>
                <td className="px-4 py-2 text-right tabular-nums font-medium">
                  {total > 0 ? formatKg(total) : '—'}
                </td>
                <td className="px-4 py-2 text-right">
                  <RowActions
                    onEdit={() => onEdit(r)}
                    onDelete={() => onDelete(r)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ─── EPDs tab ─── */

function EPDsTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, setLoading, ...confirmProps } = useConfirm();
  const [materialClass, setMaterialClass] = useState('');
  const [region, setRegion] = useState('');
  const [editEpd, setEditEpd] = useState<EPDRecord | null>(null);
  const q = useQuery({
    queryKey: ['carbon', 'epds', materialClass, region],
    queryFn: () =>
      listEPDs({
        material_class: materialClass || undefined,
        region: region || undefined,
        limit: 200,
      }),
  });
  const list: EPDRecord[] = q.data ?? [];

  async function handleDelete(epd: EPDRecord) {
    const ok = await confirm({
      title: t('carbon.confirm_delete_epd_title', {
        defaultValue: 'Delete this EPD?',
      }),
      message: t('carbon.confirm_delete_epd_msg', {
        defaultValue:
          'The EPD record will be permanently removed. Material factors that reference it will lose this source.',
      }),
    });
    if (!ok) return;
    setLoading(true);
    try {
      await deleteEPD(epd.id);
      addToast({
        type: 'success',
        title: t('carbon.epd_deleted', { defaultValue: 'EPD deleted' }),
      });
      qc.invalidateQueries({ queryKey: ['carbon', 'epds'] });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="max-w-[220px]">
          <label className={labelCls}>
            {t('carbon.material_class', { defaultValue: 'Material class' })}
          </label>
          <input
            value={materialClass}
            onChange={(e) => setMaterialClass(e.target.value)}
            placeholder="concrete, steel…"
            className={inputCls}
          />
        </div>
        <div className="max-w-[140px]">
          <label className={labelCls}>
            {t('carbon.region', { defaultValue: 'Region' })}
          </label>
          <input
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            placeholder="DE, EU…"
            maxLength={8}
            className={inputCls}
          />
        </div>
      </div>
      <Card padding="none">
        {q.isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} columns={5} />
          </div>
        ) : q.isError ? (
          <EmptyState
            icon={<AlertOctagon size={22} />}
            title={t('carbon.load_error', { defaultValue: 'Could not load carbon data' })}
            description={getErrorMessage(q.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => void q.refetch(),
            }}
          />
        ) : list.length === 0 ? (
          <EmptyState
            icon={<Database size={22} />}
            title={t('carbon.empty_epds', { defaultValue: 'No EPDs match these filters' })}
            description={t('carbon.empty_epds_desc', {
              defaultValue:
                'Try broadening the material class or region. EPDs are sourced from Ökobaudat, ICE, EC3 and custom uploads.',
            })}
          />
        ) : (
          <EPDTable
            rows={list}
            onEdit={(epd) => setEditEpd(epd)}
            onDelete={handleDelete}
          />
        )}
      </Card>
      {editEpd && (
        <EPDModal epd={editEpd} onClose={() => setEditEpd(null)} />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

function EPDTable({
  rows,
  onEdit,
  onDelete,
}: {
  rows: EPDRecord[];
  onEdit: (epd: EPDRecord) => void;
  onDelete: (epd: EPDRecord) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_product', { defaultValue: 'Product' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_class', { defaultValue: 'Class' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_region', { defaultValue: 'Region' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_source', { defaultValue: 'Source' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('carbon.col_gwp', { defaultValue: 'GWP A1–A3' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_unit', { defaultValue: 'Unit' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('carbon.col_actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-border-light hover:bg-surface-secondary">
              <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[260px]">
                {r.product_name}
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">{r.material_class}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">{r.region || '—'}</td>
              <td className="px-4 py-2 text-xs">
                <Badge variant="neutral" size="sm">
                  {r.source}
                </Badge>
              </td>
              <td className="px-4 py-2 text-right tabular-nums font-medium">
                {toNum(r.gwp_a1a3).toFixed(3)}
              </td>
              <td className="px-4 py-2 text-xs text-content-tertiary">kg/{r.declared_unit}</td>
              <td className="px-4 py-2 text-right">
                <RowActions
                  onEdit={() => onEdit(r)}
                  onDelete={() => onDelete(r)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Targets tab ─── */

function TargetsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, setLoading, ...confirmProps } = useConfirm();
  const [editTarget, setEditTarget] = useState<CarbonTarget | null>(null);
  const q = useQuery({
    queryKey: ['carbon', 'targets', projectId],
    queryFn: () => listTargets(projectId),
  });
  const list = q.data ?? [];

  async function handleDelete(target: CarbonTarget) {
    const ok = await confirm({
      title: t('carbon.confirm_delete_target_title', {
        defaultValue: 'Delete this target?',
      }),
      message: t('carbon.confirm_delete_target_msg', {
        defaultValue: 'The reduction target will be permanently removed.',
      }),
    });
    if (!ok) return;
    setLoading(true);
    try {
      await deleteTarget(target.id);
      addToast({
        type: 'success',
        title: t('carbon.target_deleted', { defaultValue: 'Target deleted' }),
      });
      qc.invalidateQueries({ queryKey: ['carbon', 'targets', projectId] });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card padding="none">
      {q.isLoading ? (
        <div className="p-4">
          <SkeletonTable rows={4} columns={4} />
        </div>
      ) : q.isError ? (
        <EmptyState
          icon={<AlertOctagon size={22} />}
          title={t('carbon.load_error', { defaultValue: 'Could not load carbon data' })}
          description={getErrorMessage(q.error)}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void q.refetch(),
          }}
        />
      ) : list.length === 0 ? (
        <EmptyState
          icon={<Target size={22} />}
          title={t('carbon.empty_targets', { defaultValue: 'No targets set' })}
          description={t('carbon.empty_targets_desc', {
            defaultValue:
              'Define a reduction target (absolute or per m²) to track progress against a baseline year.',
          })}
        />
      ) : (
        <ul className="divide-y divide-border-light">
          {list.map((target) => (
            <TargetRow
              key={target.id}
              target={target}
              onEdit={() => setEditTarget(target)}
              onDelete={() => handleDelete(target)}
            />
          ))}
        </ul>
      )}
      {editTarget && (
        <CreateTargetModal
          projectId={projectId}
          target={editTarget}
          onClose={() => setEditTarget(null)}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}

function TargetRow({
  target,
  onEdit,
  onDelete,
}: {
  target: CarbonTarget;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const progressQ = useQuery({
    queryKey: ['carbon', 'target-progress', target.id],
    queryFn: () => getTargetProgress(target.id),
    staleTime: 30_000,
  });
  const p = progressQ.data;
  const pct = p ? Math.max(0, Math.min(100, p.progress_pct)) : 0;
  const met = p?.met ?? target.status === 'met';

  return (
    <li className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium text-content-primary">
            {target.name || `${target.target_type} ${target.target_year}`}
          </p>
          <p className="mt-0.5 text-xs text-content-secondary">
            {target.baseline_year} → {target.target_year} ·{' '}
            {target.target_type.replace('_', ' ')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant={
              met
                ? 'success'
                : target.status === 'missed'
                  ? 'error'
                  : target.status === 'abandoned'
                    ? 'neutral'
                    : 'blue'
            }
            dot
            size="sm"
          >
            {target.status}
          </Badge>
          <RowActions onEdit={onEdit} onDelete={onDelete} />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
        <div>
          <p className="text-content-tertiary uppercase tracking-wide">
            {t('carbon.baseline', { defaultValue: 'Baseline' })}
          </p>
          <p className="font-medium tabular-nums">
            {toNum(target.baseline_value).toFixed(0)}
          </p>
        </div>
        <div>
          <p className="text-content-tertiary uppercase tracking-wide">
            {t('carbon.current', { defaultValue: 'Current' })}
          </p>
          <p className="font-medium tabular-nums">
            {p ? toNum(p.current_value).toFixed(0) : '—'}
          </p>
        </div>
        <div>
          <p className="text-content-tertiary uppercase tracking-wide">
            {t('carbon.target_label', { defaultValue: 'Target' })}
          </p>
          <p className="font-medium tabular-nums">
            {toNum(target.target_value).toFixed(0)}
          </p>
        </div>
      </div>
      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-surface-secondary">
        <div
          className={clsx(
            'h-full rounded-full transition-all',
            met ? 'bg-semantic-success' : 'bg-oe-blue',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-1 text-xs text-content-tertiary tabular-nums">
        {pct.toFixed(0)}%
        {met && (
          <span className="ms-1 inline-flex items-center gap-0.5 text-semantic-success">
            <CheckCircle2 size={11} />
            {t('carbon.met', { defaultValue: 'Met' })}
          </span>
        )}
      </p>
    </li>
  );
}

/* ─── Reports tab ─── */

function ReportsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, setLoading, ...confirmProps } = useConfirm();
  const q = useQuery({
    queryKey: ['carbon', 'reports', projectId],
    queryFn: () => listReports(projectId),
  });
  const list = q.data ?? [];

  async function handleDelete(report: SustainabilityReport) {
    const ok = await confirm({
      title: t('carbon.confirm_delete_report_title', {
        defaultValue: 'Delete this report?',
      }),
      message: t('carbon.confirm_delete_report_msg', {
        defaultValue: 'The generated sustainability report will be permanently removed.',
      }),
    });
    if (!ok) return;
    setLoading(true);
    try {
      await deleteReport(report.id);
      addToast({
        type: 'success',
        title: t('carbon.report_deleted', { defaultValue: 'Report deleted' }),
      });
      qc.invalidateQueries({ queryKey: ['carbon', 'reports', projectId] });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card padding="none">
      {q.isLoading ? (
        <div className="p-4">
          <SkeletonTable rows={5} columns={4} />
        </div>
      ) : q.isError ? (
        <EmptyState
          icon={<AlertOctagon size={22} />}
          title={t('carbon.load_error', { defaultValue: 'Could not load carbon data' })}
          description={getErrorMessage(q.error)}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void q.refetch(),
          }}
        />
      ) : list.length === 0 ? (
        <EmptyState
          icon={<FileText size={22} />}
          title={t('carbon.empty_reports', { defaultValue: 'No sustainability reports yet' })}
          description={t('carbon.empty_reports_desc', {
            defaultValue:
              'Generate a GHG Protocol, GRI or ISSB report from the project’s current inventory.',
          })}
        />
      ) : (
        <ReportTable rows={list} onDelete={handleDelete} />
      )}
      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}

function ReportTable({
  rows,
  onDelete,
}: {
  rows: SustainabilityReport[];
  onDelete: (report: SustainabilityReport) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_period', { defaultValue: 'Period' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_framework', { defaultValue: 'Framework' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('carbon.col_generated', { defaultValue: 'Generated' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('carbon.col_total', { defaultValue: 'Total kg CO2e' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('carbon.col_actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const total = toNum(
              (r.totals as Record<string, unknown>)['total'] as
                | number
                | string
                | null
                | undefined,
            );
            return (
              <tr key={r.id} className="border-t border-border-light hover:bg-surface-secondary">
                <td className="px-4 py-2 text-xs text-content-secondary">
                  {r.period_start} → {r.period_end}
                </td>
                <td className="px-4 py-2">
                  <Badge variant="blue" size="sm">
                    {r.framework}
                  </Badge>
                </td>
                <td className="px-4 py-2 text-xs text-content-secondary">
                  {r.generated_at ? <DateDisplay value={r.generated_at} /> : '—'}
                </td>
                <td className="px-4 py-2 text-right tabular-nums font-medium">
                  {total > 0 ? formatKg(total) : '—'}
                </td>
                <td className="px-4 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => onDelete(r)}
                    className="rounded p-1.5 text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error"
                    aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    title={t('common.delete', { defaultValue: 'Delete' })}
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Inventory drawer ─── */

function InventoryDrawer({
  inventoryId,
  onClose,
}: {
  inventoryId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, setLoading, ...confirmProps } = useConfirm();
  useEscapeToClose(onClose);

  type ScopeKind = 's1' | 's2' | 's3';
  const [embodiedModal, setEmbodiedModal] = useState<
    { mode: 'create' } | { mode: 'edit'; entry: EmbodiedEntry } | null
  >(null);
  // CONN-60: assign a BOQ position to this inventory via a material factor.
  const [assignBoqOpen, setAssignBoqOpen] = useState(false);
  const [scopeModal, setScopeModal] = useState<
    | { kind: ScopeKind; mode: 'create' }
    | {
        kind: ScopeKind;
        mode: 'edit';
        entry: Scope1Entry | Scope2Entry | Scope3Entry;
      }
    | null
  >(null);

  function invalidateAll() {
    qc.invalidateQueries({ queryKey: ['carbon', 'totals', inventoryId] });
    qc.invalidateQueries({ queryKey: ['carbon', 'embodied', inventoryId] });
    qc.invalidateQueries({ queryKey: ['carbon', 's1', inventoryId] });
    qc.invalidateQueries({ queryKey: ['carbon', 's2', inventoryId] });
    qc.invalidateQueries({ queryKey: ['carbon', 's3', inventoryId] });
  }

  async function handleDeleteEmbodied(entry: EmbodiedEntry) {
    const ok = await confirm({
      title: t('carbon.confirm_delete_entry_title', {
        defaultValue: 'Delete this entry?',
      }),
      message: t('carbon.confirm_delete_entry_msg', {
        defaultValue: 'The embodied-carbon entry will be permanently removed.',
      }),
    });
    if (!ok) return;
    setLoading(true);
    try {
      await deleteEmbodiedEntry(entry.id);
      addToast({
        type: 'success',
        title: t('carbon.entry_deleted', { defaultValue: 'Entry deleted' }),
      });
      invalidateAll();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteScope(
    kind: ScopeKind,
    entry: Scope1Entry | Scope2Entry | Scope3Entry,
  ) {
    const ok = await confirm({
      title: t('carbon.confirm_delete_entry_title', {
        defaultValue: 'Delete this entry?',
      }),
      message: t('carbon.confirm_delete_scope_msg', {
        defaultValue: 'The scope emission entry will be permanently removed.',
      }),
    });
    if (!ok) return;
    setLoading(true);
    try {
      if (kind === 's1') await deleteScope1(entry.id);
      else if (kind === 's2') await deleteScope2(entry.id);
      else await deleteScope3(entry.id);
      addToast({
        type: 'success',
        title: t('carbon.entry_deleted', { defaultValue: 'Entry deleted' }),
      });
      invalidateAll();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setLoading(false);
    }
  }

  const inventoryQ = useQuery({
    queryKey: ['carbon', 'inventory', inventoryId],
    queryFn: () => getInventory(inventoryId),
    staleTime: 60_000,
  });
  const inventoryProjectId = inventoryQ.data?.project_id ?? '';

  const totalsQ = useQuery({
    queryKey: ['carbon', 'totals', inventoryId],
    queryFn: () => getInventoryTotals(inventoryId),
  });
  const embodiedQ = useQuery({
    queryKey: ['carbon', 'embodied', inventoryId],
    queryFn: () => listEmbodiedEntries(inventoryId, { limit: 200 }),
  });
  const s1Q = useQuery({
    queryKey: ['carbon', 's1', inventoryId],
    queryFn: () => listScope1(inventoryId).catch(() => []),
  });
  const s2Q = useQuery({
    queryKey: ['carbon', 's2', inventoryId],
    queryFn: () => listScope2(inventoryId).catch(() => []),
  });
  const s3Q = useQuery({
    queryKey: ['carbon', 's3', inventoryId],
    queryFn: () => listScope3(inventoryId).catch(() => []),
  });

  const totals = totalsQ.data;
  const scope1Kg = totals ? toNum(totals.scope1) : 0;
  const scope2Kg = totals ? toNum(totals.scope2) : 0;
  const scope3Kg = totals ? toNum(totals.scope3) : 0;
  const scopeTotal = scope1Kg + scope2Kg + scope3Kg;

  // Top emitters from embodied entries
  const topEmitters = useMemo(() => {
    const items = embodiedQ.data ?? [];
    return [...items]
      .sort((a, b) => toNum(b.carbon_kg) - toNum(a.carbon_kg))
      .slice(0, 8);
  }, [embodiedQ.data]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="carbon-inv-drawer-title"
        className="relative h-full w-full max-w-2xl overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <h2 id="carbon-inv-drawer-title" className="text-base font-semibold">
            {t('carbon.inventory_detail', { defaultValue: 'Inventory detail' })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-5 p-5">
          {totalsQ.isLoading ? (
            <SkeletonTable rows={3} columns={2} />
          ) : totalsQ.isError ? (
            <EmptyState
              icon={<AlertOctagon size={22} />}
              title={t('carbon.load_error', {
                defaultValue: 'Could not load carbon data',
              })}
              description={getErrorMessage(totalsQ.error)}
              action={{
                label: t('common.retry', { defaultValue: 'Retry' }),
                onClick: () => void totalsQ.refetch(),
              }}
            />
          ) : (
            totals && (
              <>
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('carbon.scope_breakdown', { defaultValue: 'Scope 1 / 2 / 3 breakdown' })}
                  </h3>
                  <ScopeBar
                    scope1={scope1Kg}
                    scope2={scope2Kg}
                    scope3={scope3Kg}
                  />
                  <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
                    <ScopeKpi
                      label="Scope 1"
                      kg={scope1Kg}
                      pct={scopeTotal > 0 ? (scope1Kg / scopeTotal) * 100 : 0}
                      color="bg-oe-blue"
                    />
                    <ScopeKpi
                      label="Scope 2"
                      kg={scope2Kg}
                      pct={scopeTotal > 0 ? (scope2Kg / scopeTotal) * 100 : 0}
                      color="bg-emerald-500"
                    />
                    <ScopeKpi
                      label="Scope 3"
                      kg={scope3Kg}
                      pct={scopeTotal > 0 ? (scope3Kg / scopeTotal) * 100 : 0}
                      color="bg-amber-500"
                    />
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-content-secondary">
                    <span>
                      {s1Q.data?.length ?? 0}{' '}
                      {t('carbon.entries', { defaultValue: 'entries' })}
                    </span>
                    <span>
                      {s2Q.data?.length ?? 0}{' '}
                      {t('carbon.entries', { defaultValue: 'entries' })}
                    </span>
                    <span>
                      {s3Q.data?.length ?? 0}{' '}
                      {t('carbon.entries', { defaultValue: 'entries' })}
                    </span>
                  </div>
                </div>

                <div>
                  <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    <TrendingDown size={12} />
                    {t('carbon.embodied_lifecycle', { defaultValue: 'Embodied (A1–D)' })}
                  </h3>
                  <div className="grid grid-cols-4 gap-2 text-xs">
                    <StageTile label="A1–A3" kg={toNum(totals.embodied_a1a3)} />
                    <StageTile label="A4" kg={toNum(totals.embodied_a4)} />
                    <StageTile label="A5" kg={toNum(totals.embodied_a5)} />
                    <StageTile label="B" kg={toNum(totals.embodied_b)} />
                    <StageTile label="C" kg={toNum(totals.embodied_c)} />
                    <StageTile label="D" kg={toNum(totals.embodied_d)} />
                  </div>
                </div>

                <div>
                  <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    <AlertTriangle size={12} />
                    {t('carbon.top_emitters', { defaultValue: 'Top emitters' })}
                  </h3>
                  {topEmitters.length === 0 ? (
                    <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
                      {t('carbon.no_entries_hint', {
                        defaultValue:
                          'No embodied entries yet - assign material carbon factors to BOQ positions to populate this inventory.',
                      })}
                    </p>
                  ) : (
                    <>
                      <p className="mb-2 text-xs text-content-tertiary">
                        {t('carbon.top_emitters_hint', {
                          defaultValue:
                            'Click an entry to see lower-carbon material alternatives and potential savings.',
                        })}
                      </p>
                      <ul className="divide-y divide-border-light rounded border border-border-light text-sm">
                        {topEmitters.map((e) => (
                          <TopEmitterRow key={e.id} inventoryId={inventoryId} entry={e} />
                        ))}
                      </ul>
                    </>
                  )}
                </div>

                {/* Embodied entries — full management */}
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                      {t('carbon.embodied_entries', {
                        defaultValue: 'Embodied entries',
                      })}
                    </h3>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<FileSpreadsheet size={13} />}
                        onClick={() => setAssignBoqOpen(true)}
                      >
                        {t('carbon.add_from_boq', { defaultValue: 'Add from BOQ' })}
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<Plus size={13} />}
                        onClick={() => setEmbodiedModal({ mode: 'create' })}
                      >
                        {t('carbon.add_entry', { defaultValue: 'Add entry' })}
                      </Button>
                    </div>
                  </div>
                  {(embodiedQ.data ?? []).length === 0 ? (
                    <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
                      {t('carbon.no_embodied_manual', {
                        defaultValue:
                          'No embodied entries. Add one manually or assign factors to BOQ positions.',
                      })}
                    </p>
                  ) : (
                    <ul className="divide-y divide-border-light rounded border border-border-light text-sm">
                      {(embodiedQ.data ?? []).map((e) => (
                        <li
                          key={e.id}
                          className="flex items-center justify-between gap-2 px-3 py-2"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-content-primary">
                              {e.description || e.element_ref || '—'}
                            </span>
                            <span className="text-xs text-content-tertiary">
                              {toNum(e.quantity)} {e.unit} · {e.stage} ·{' '}
                              {formatKg(toNum(e.carbon_kg))}
                            </span>
                          </span>
                          <RowActions
                            onEdit={() =>
                              setEmbodiedModal({ mode: 'edit', entry: e })
                            }
                            onDelete={() => handleDeleteEmbodied(e)}
                          />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* Scope 1 / 2 / 3 — full management */}
                <ScopeSection
                  title={t('carbon.scope1_entries', {
                    defaultValue: 'Scope 1 - direct fuel',
                  })}
                  rows={s1Q.data ?? []}
                  describe={(e) => {
                    const s = e as Scope1Entry;
                    return `${s.fuel_type} · ${toNum(s.litres_or_m3)} · ${formatKg(toNum(s.total_co2e_kg))}`;
                  }}
                  onAdd={() => setScopeModal({ kind: 's1', mode: 'create' })}
                  onEdit={(e) =>
                    setScopeModal({ kind: 's1', mode: 'edit', entry: e })
                  }
                  onDelete={(e) => handleDeleteScope('s1', e)}
                />
                <ScopeSection
                  title={t('carbon.scope2_entries', {
                    defaultValue: 'Scope 2 - purchased energy',
                  })}
                  rows={s2Q.data ?? []}
                  describe={(e) => {
                    const s = e as Scope2Entry;
                    return `${s.energy_type} · ${toNum(s.kwh)} kWh · ${formatKg(toNum(s.total_co2e_kg))}`;
                  }}
                  onAdd={() => setScopeModal({ kind: 's2', mode: 'create' })}
                  onEdit={(e) =>
                    setScopeModal({ kind: 's2', mode: 'edit', entry: e })
                  }
                  onDelete={(e) => handleDeleteScope('s2', e)}
                />
                <ScopeSection
                  title={t('carbon.scope3_entries', {
                    defaultValue: 'Scope 3 - value chain',
                  })}
                  rows={s3Q.data ?? []}
                  describe={(e) => {
                    const s = e as Scope3Entry;
                    return `${s.category} · ${toNum(s.activity_data)} ${s.activity_unit} · ${formatKg(toNum(s.total_co2e_kg))}`;
                  }}
                  onAdd={() => setScopeModal({ kind: 's3', mode: 'create' })}
                  onEdit={(e) =>
                    setScopeModal({ kind: 's3', mode: 'edit', entry: e })
                  }
                  onDelete={(e) => handleDeleteScope('s3', e)}
                />
              </>
            )
          )}
        </div>
      </div>

      {embodiedModal && (
        <EmbodiedEntryModal
          inventoryId={inventoryId}
          entry={
            embodiedModal.mode === 'edit' ? embodiedModal.entry : undefined
          }
          onClose={() => setEmbodiedModal(null)}
          onSaved={invalidateAll}
        />
      )}
      {scopeModal && (
        <ScopeEntryModal
          inventoryId={inventoryId}
          kind={scopeModal.kind}
          entry={scopeModal.mode === 'edit' ? scopeModal.entry : undefined}
          onClose={() => setScopeModal(null)}
          onSaved={invalidateAll}
        />
      )}
      {assignBoqOpen && (
        <AssignBoqModal
          inventoryId={inventoryId}
          projectId={inventoryProjectId}
          onClose={() => setAssignBoqOpen(false)}
          onSaved={invalidateAll}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

function ScopeSection({
  title,
  rows,
  describe,
  onAdd,
  onEdit,
  onDelete,
}: {
  title: string;
  rows: (Scope1Entry | Scope2Entry | Scope3Entry)[];
  describe: (e: Scope1Entry | Scope2Entry | Scope3Entry) => string;
  onAdd: () => void;
  onEdit: (e: Scope1Entry | Scope2Entry | Scope3Entry) => void;
  onDelete: (e: Scope1Entry | Scope2Entry | Scope3Entry) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {title}
        </h3>
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus size={13} />}
          onClick={onAdd}
        >
          {t('carbon.add_entry', { defaultValue: 'Add entry' })}
        </Button>
      </div>
      {rows.length === 0 ? (
        <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">
          {t('carbon.no_scope_entries', { defaultValue: 'No entries yet.' })}
        </p>
      ) : (
        <ul className="divide-y divide-border-light rounded border border-border-light text-sm">
          {rows.map((e) => (
            <li
              key={e.id}
              className="flex items-center justify-between gap-2 px-3 py-2"
            >
              <span className="min-w-0">
                <span className="block truncate text-content-primary text-xs">
                  {e.period_start} → {e.period_end}
                </span>
                <span className="text-xs text-content-tertiary">
                  {describe(e)}
                </span>
              </span>
              <RowActions
                onEdit={() => onEdit(e)}
                onDelete={() => onDelete(e)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * One top-emitter row that, when expanded, fetches and shows lower-carbon
 * material alternatives for that embodied entry (uses the existing
 * /inventories/{id}/alternatives endpoint — previously a dead "coming soon").
 */
function TopEmitterRow({
  inventoryId,
  entry,
}: {
  inventoryId: string;
  entry: EmbodiedEntry;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const altQ = useQuery({
    queryKey: ['carbon', 'alternatives', inventoryId, entry.id],
    queryFn: () => getAlternatives(inventoryId, entry.id),
    enabled: open,
    staleTime: 60_000,
  });

  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-surface-secondary transition-colors"
      >
        <span className="flex min-w-0 items-center gap-1.5">
          <ChevronRight
            size={13}
            className={clsx(
              'shrink-0 text-content-tertiary transition-transform',
              open && 'rotate-90',
            )}
          />
          <span className="truncate text-content-primary">
            {entry.description || entry.element_ref || '—'}
          </span>
        </span>
        <span className="shrink-0 font-medium tabular-nums">
          {formatKg(toNum(entry.carbon_kg))}
        </span>
      </button>
      {open && (
        <div className="border-t border-border-light bg-surface-secondary/40 px-3 py-2 text-xs animate-fade-in">
          {altQ.isLoading ? (
            <span className="flex items-center gap-1.5 text-content-tertiary">
              <Loader2 size={12} className="animate-spin" />
              {t('carbon.loading_alternatives', {
                defaultValue: 'Finding lower-carbon options…',
              })}
            </span>
          ) : altQ.isError ? (
            <span className="text-semantic-error">
              {t('carbon.alternatives_error', {
                defaultValue: 'Could not load alternatives.',
              })}
            </span>
          ) : !altQ.data || altQ.data.options.length === 0 ? (
            <span className="text-content-tertiary">
              {t('carbon.no_alternatives', {
                defaultValue:
                  'No lower-carbon alternative with a matching factor was found for this material.',
              })}
            </span>
          ) : (
            <ul className="space-y-1.5">
              {altQ.data.options.map((opt) => (
                <li
                  key={opt.factor_id}
                  className="flex items-center justify-between gap-2"
                >
                  <span className="flex items-center gap-1.5 text-content-secondary">
                    <Badge variant="neutral" size="sm">
                      {opt.confidence}
                    </Badge>
                    {formatKg(toNum(opt.carbon_kg))}
                  </span>
                  <span
                    className={clsx(
                      'font-medium tabular-nums',
                      toNum(opt.savings_kg) > 0
                        ? 'text-semantic-success'
                        : 'text-content-tertiary',
                    )}
                  >
                    {toNum(opt.savings_kg) > 0 ? '−' : ''}
                    {formatKg(Math.abs(toNum(opt.savings_kg)))}{' '}
                    ({Number(opt.savings_pct).toFixed(0)}%)
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

function ScopeBar({
  scope1,
  scope2,
  scope3,
}: {
  scope1: number;
  scope2: number;
  scope3: number;
}) {
  const total = scope1 + scope2 + scope3;
  if (total <= 0) {
    return (
      <div className="h-4 w-full rounded-full bg-surface-secondary" aria-label="empty" />
    );
  }
  const p1 = (scope1 / total) * 100;
  const p2 = (scope2 / total) * 100;
  const p3 = (scope3 / total) * 100;
  return (
    <div className="flex h-4 w-full overflow-hidden rounded-full bg-surface-secondary">
      <div className="bg-oe-blue" style={{ width: `${p1}%` }} title={`Scope 1: ${formatKg(scope1)}`} />
      <div
        className="bg-emerald-500"
        style={{ width: `${p2}%` }}
        title={`Scope 2: ${formatKg(scope2)}`}
      />
      <div
        className="bg-amber-500"
        style={{ width: `${p3}%` }}
        title={`Scope 3: ${formatKg(scope3)}`}
      />
    </div>
  );
}

function ScopeKpi({
  label,
  kg,
  pct,
  color,
}: {
  label: string;
  kg: number;
  pct: number;
  color: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5">
        <span className={clsx('inline-block h-2 w-2 rounded-full', color)} />
        <span className="text-xs uppercase tracking-wide text-content-tertiary">
          {label}
        </span>
      </div>
      <p className="mt-0.5 text-sm font-medium tabular-nums">{formatKg(kg)}</p>
      <p className="text-xs text-content-tertiary tabular-nums">{pct.toFixed(0)}%</p>
    </div>
  );
}

function StageTile({ label, kg }: { label: string; kg: number }) {
  return (
    <div className="rounded-md border border-border-light p-2">
      <p className="text-xs uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className="mt-0.5 font-medium tabular-nums">{formatKg(kg)}</p>
    </div>
  );
}

/* ─── Modals ─── */

function CreateInventoryModal({
  projectId,
  inventory,
  onClose,
}: {
  projectId: string;
  inventory?: CarbonInventory;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = !!inventory;
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: inventory?.name ?? 'Baseline inventory',
    scope: (inventory?.scope ?? 'cradle_to_gate') as
      | 'cradle_to_gate'
      | 'cradle_to_grave'
      | 'operational',
    as_of_date: inventory?.as_of_date ?? todayIso(),
    status: (inventory?.status ?? 'draft') as InventoryStatus,
    notes: inventory?.notes ?? '',
  });

  async function submit() {
    setBusy(true);
    try {
      if (isEdit && inventory) {
        await updateInventory(inventory.id, {
          name: form.name,
          scope: form.scope,
          as_of_date: form.as_of_date || null,
          status: form.status,
          notes: form.notes || null,
        });
        addToast({
          type: 'success',
          title: t('carbon.inv_updated', { defaultValue: 'Inventory updated' }),
        });
      } else {
        await createInventory({
          project_id: projectId,
          name: form.name,
          scope: form.scope,
          as_of_date: form.as_of_date,
          status: form.status,
          notes: form.notes || undefined,
        });
        addToast({
          type: 'success',
          title: t('carbon.inv_created', { defaultValue: 'Inventory created' }),
        });
      }
      qc.invalidateQueries({ queryKey: ['carbon', 'inventories', projectId] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      title={
        isEdit
          ? t('carbon.edit_inventory', { defaultValue: 'Edit Inventory' })
          : t('carbon.new_inventory', { defaultValue: 'New Inventory' })
      }
      onClose={onClose}
    >
      <div className="space-y-3">
        <div>
          <label className={labelCls}>
            {t('carbon.name', { defaultValue: 'Name' })}
          </label>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>
            {t('carbon.col_scope', { defaultValue: 'Scope' })}
          </label>
          <select
            value={form.scope}
            onChange={(e) =>
              setForm({
                ...form,
                scope: e.target.value as
                  | 'cradle_to_gate'
                  | 'cradle_to_grave'
                  | 'operational',
              })
            }
            className={inputCls}
          >
            <option value="cradle_to_gate">cradle_to_gate</option>
            <option value="cradle_to_grave">cradle_to_grave</option>
            <option value="operational">operational</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.col_status', { defaultValue: 'Status' })}
            </label>
            <select
              value={form.status}
              onChange={(e) =>
                setForm({ ...form, status: e.target.value as InventoryStatus })
              }
              className={inputCls}
            >
              <option value="draft">draft</option>
              <option value="baseline">baseline</option>
              <option value="current">current</option>
              <option value="archived">archived</option>
            </select>
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.col_as_of', { defaultValue: 'As of' })}
            </label>
            <input
              type="date"
              value={form.as_of_date ?? ''}
              onChange={(e) => setForm({ ...form, as_of_date: e.target.value })}
              className={inputCls}
            />
          </div>
        </div>
        <div>
          <label className={labelCls}>
            {t('carbon.notes', { defaultValue: 'Notes' })}
          </label>
          <textarea
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          loading={busy}
          icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
        >
          {isEdit
            ? t('common.save', { defaultValue: 'Save' })
            : t('common.create', { defaultValue: 'Create' })}
        </Button>
      </div>
    </ModalShell>
  );
}

function CreateTargetModal({
  projectId,
  target,
  onClose,
}: {
  projectId: string;
  target?: CarbonTarget;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = !!target;
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: target?.name ?? '',
    target_type: (target?.target_type ?? 'absolute') as
      | 'absolute'
      | 'intensity_per_m2'
      | 'intensity_per_unit',
    baseline_value: String(target?.baseline_value ?? '0'),
    target_value: String(target?.target_value ?? '0'),
    baseline_year: target?.baseline_year ?? 2020,
    target_year: target?.target_year ?? 2030,
    status: (target?.status ?? 'active') as TargetStatus,
  });

  async function submit() {
    setBusy(true);
    try {
      if (isEdit && target) {
        await updateTarget(target.id, {
          name: form.name,
          baseline_value: Number(form.baseline_value) || 0,
          target_value: Number(form.target_value) || 0,
          status: form.status,
        });
        addToast({
          type: 'success',
          title: t('carbon.target_updated', { defaultValue: 'Target updated' }),
        });
      } else {
        await createTarget({
          project_id: projectId,
          name: form.name,
          target_type: form.target_type,
          baseline_value: Number(form.baseline_value) || 0,
          target_value: Number(form.target_value) || 0,
          baseline_year: form.baseline_year,
          target_year: form.target_year,
        });
        addToast({
          type: 'success',
          title: t('carbon.target_created', { defaultValue: 'Target created' }),
        });
      }
      qc.invalidateQueries({ queryKey: ['carbon', 'targets', projectId] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      title={
        isEdit
          ? t('carbon.edit_target', { defaultValue: 'Edit Target' })
          : t('carbon.new_target', { defaultValue: 'New Target' })
      }
      onClose={onClose}
    >
      <div className="space-y-3">
        <div>
          <label className={labelCls}>
            {t('carbon.name', { defaultValue: 'Name' })}
          </label>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
            placeholder="e.g. Net-zero by 2030"
          />
        </div>
        <div>
          <label className={labelCls}>
            {t('carbon.target_type', { defaultValue: 'Type' })}
          </label>
          <select
            value={form.target_type}
            onChange={(e) =>
              setForm({
                ...form,
                target_type: e.target.value as
                  | 'absolute'
                  | 'intensity_per_m2'
                  | 'intensity_per_unit',
              })
            }
            className={inputCls}
            disabled={isEdit}
          >
            <option value="absolute">absolute (kg CO2e)</option>
            <option value="intensity_per_m2">intensity per m²</option>
            <option value="intensity_per_unit">intensity per unit</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.baseline', { defaultValue: 'Baseline' })}
            </label>
            <input
              type="number"
              value={form.baseline_value}
              onChange={(e) => setForm({ ...form, baseline_value: e.target.value })}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.target_label', { defaultValue: 'Target' })}
            </label>
            <input
              type="number"
              value={form.target_value}
              onChange={(e) => setForm({ ...form, target_value: e.target.value })}
              className={inputCls}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.baseline_year', { defaultValue: 'Baseline year' })}
            </label>
            <input
              type="number"
              value={form.baseline_year}
              onChange={(e) =>
                setForm({ ...form, baseline_year: Number(e.target.value) || 2020 })
              }
              className={inputCls}
              disabled={isEdit}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.target_year', { defaultValue: 'Target year' })}
            </label>
            <input
              type="number"
              value={form.target_year}
              onChange={(e) =>
                setForm({ ...form, target_year: Number(e.target.value) || 2030 })
              }
              className={inputCls}
              disabled={isEdit}
            />
          </div>
        </div>
        {isEdit && (
          <div>
            <label className={labelCls}>
              {t('carbon.col_status', { defaultValue: 'Status' })}
            </label>
            <select
              value={form.status}
              onChange={(e) =>
                setForm({ ...form, status: e.target.value as TargetStatus })
              }
              className={inputCls}
            >
              <option value="active">active</option>
              <option value="met">met</option>
              <option value="missed">missed</option>
              <option value="abandoned">abandoned</option>
            </select>
          </div>
        )}
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          loading={busy}
          icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
        >
          {isEdit
            ? t('common.save', { defaultValue: 'Save' })
            : t('common.create', { defaultValue: 'Create' })}
        </Button>
      </div>
    </ModalShell>
  );
}

function GenerateReportModal({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  const inventoriesQ = useQuery({
    queryKey: ['carbon', 'inventories', projectId],
    queryFn: () => listInventories(projectId).catch(() => []),
  });
  const inventories: CarbonInventory[] = inventoriesQ.data ?? [];

  const [form, setForm] = useState({
    inventory_id: '',
    period_start: todayIso(-365),
    period_end: todayIso(),
    framework: 'ghg_protocol' as 'ghg_protocol' | 'gri' | 'issb' | 'custom',
    project_area_m2: '',
  });

  const generateMut = useMutation({
    mutationFn: () =>
      generateReport({
        project_id: projectId,
        inventory_id: form.inventory_id || null,
        period_start: form.period_start,
        period_end: form.period_end,
        framework: form.framework,
        project_area_m2: form.project_area_m2 ? Number(form.project_area_m2) : undefined,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('carbon.report_generated', { defaultValue: 'Report generated' }),
      });
      qc.invalidateQueries({ queryKey: ['carbon', 'reports', projectId] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
    onSettled: () => setBusy(false),
  });

  return (
    <ModalShell
      title={t('carbon.generate_report', { defaultValue: 'Generate Report' })}
      onClose={onClose}
    >
      <div className="space-y-3">
        <div>
          <label className={labelCls}>
            {t('carbon.inventory', { defaultValue: 'Inventory' })}
          </label>
          <select
            value={form.inventory_id}
            onChange={(e) => setForm({ ...form, inventory_id: e.target.value })}
            className={inputCls}
          >
            <option value="">
              — {t('carbon.optional', { defaultValue: 'optional' })} —
            </option>
            {inventories.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>
            {t('carbon.col_framework', { defaultValue: 'Framework' })}
          </label>
          <select
            value={form.framework}
            onChange={(e) =>
              setForm({
                ...form,
                framework: e.target.value as 'ghg_protocol' | 'gri' | 'issb' | 'custom',
              })
            }
            className={inputCls}
          >
            <option value="ghg_protocol">GHG Protocol</option>
            <option value="gri">GRI</option>
            <option value="issb">ISSB</option>
            <option value="custom">custom</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.period_start', { defaultValue: 'Period start' })}
            </label>
            <input
              type="date"
              value={form.period_start}
              onChange={(e) => setForm({ ...form, period_start: e.target.value })}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.period_end', { defaultValue: 'Period end' })}
            </label>
            <input
              type="date"
              value={form.period_end}
              onChange={(e) => setForm({ ...form, period_end: e.target.value })}
              className={inputCls}
            />
          </div>
        </div>
        <div>
          <label className={labelCls}>
            {t('carbon.area_m2', { defaultValue: 'Project area (m²) - optional' })}
          </label>
          <input
            type="number"
            value={form.project_area_m2}
            onChange={(e) => setForm({ ...form, project_area_m2: e.target.value })}
            className={inputCls}
          />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={() => {
            setBusy(true);
            generateMut.mutate();
          }}
          loading={busy}
          icon={busy ? <Loader2 size={14} /> : <FileText size={14} />}
        >
          {t('carbon.generate', { defaultValue: 'Generate' })}
        </Button>
      </div>
    </ModalShell>
  );
}

function EmbodiedEntryModal({
  inventoryId,
  entry,
  onClose,
  onSaved,
}: {
  inventoryId: string;
  entry?: EmbodiedEntry;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = !!entry;
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    description: entry?.description ?? '',
    element_ref: entry?.element_ref ?? '',
    quantity: String(entry?.quantity ?? '0'),
    unit: entry?.unit ?? 'kg',
    factor_value_used: String(entry?.factor_value_used ?? '0'),
    carbon_kg: String(entry?.carbon_kg ?? '0'),
    stage: (entry?.stage ?? 'a1a3') as Stage,
  });

  // Auto-suggest carbon = quantity × factor when not manually overridden.
  const autoCarbon =
    (Number(form.quantity) || 0) * (Number(form.factor_value_used) || 0);

  async function submit() {
    setBusy(true);
    try {
      const carbon =
        form.carbon_kg.trim() === '' || Number(form.carbon_kg) === 0
          ? autoCarbon
          : Number(form.carbon_kg);
      if (isEdit && entry) {
        await updateEmbodiedEntry(entry.id, {
          description: form.description,
          element_ref: form.element_ref || null,
          quantity: Number(form.quantity) || 0,
          unit: form.unit,
          factor_value_used: Number(form.factor_value_used) || 0,
          carbon_kg: carbon,
          stage: form.stage,
        });
        addToast({
          type: 'success',
          title: t('carbon.entry_updated', { defaultValue: 'Entry updated' }),
        });
      } else {
        await createEmbodiedEntry(inventoryId, {
          inventory_id: inventoryId,
          description: form.description,
          element_ref: form.element_ref || null,
          quantity: Number(form.quantity) || 0,
          unit: form.unit,
          factor_value_used: Number(form.factor_value_used) || 0,
          carbon_kg: carbon,
          stage: form.stage,
        });
        addToast({
          type: 'success',
          title: t('carbon.entry_created', { defaultValue: 'Entry created' }),
        });
      }
      onSaved();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      title={
        isEdit
          ? t('carbon.edit_embodied', { defaultValue: 'Edit embodied entry' })
          : t('carbon.add_embodied', { defaultValue: 'Add embodied entry' })
      }
      onClose={onClose}
    >
      <div className="space-y-3">
        <div>
          <label className={labelCls}>
            {t('carbon.description', { defaultValue: 'Description' })}
          </label>
          <input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className={inputCls}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.element_ref', { defaultValue: 'Element ref' })}
            </label>
            <input
              value={form.element_ref}
              onChange={(e) =>
                setForm({ ...form, element_ref: e.target.value })
              }
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.stage', { defaultValue: 'Stage' })}
            </label>
            <select
              value={form.stage}
              onChange={(e) =>
                setForm({ ...form, stage: e.target.value as Stage })
              }
              className={inputCls}
            >
              <option value="a1a3">a1a3</option>
              <option value="a4">a4</option>
              <option value="a5">a5</option>
              <option value="b">b</option>
              <option value="c">c</option>
              <option value="d">d</option>
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.quantity', { defaultValue: 'Quantity' })}
            </label>
            <input
              type="number"
              step="any"
              value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: e.target.value })}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.col_unit', { defaultValue: 'Unit' })}
            </label>
            <input
              value={form.unit}
              onChange={(e) => setForm({ ...form, unit: e.target.value })}
              className={inputCls}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.factor_value', {
                defaultValue: 'Factor (kg CO2e / unit)',
              })}
            </label>
            <input
              type="number"
              step="any"
              value={form.factor_value_used}
              onChange={(e) =>
                setForm({ ...form, factor_value_used: e.target.value })
              }
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.carbon_kg', {
                defaultValue: 'Carbon kg (0 = auto)',
              })}
            </label>
            <input
              type="number"
              step="any"
              value={form.carbon_kg}
              onChange={(e) => setForm({ ...form, carbon_kg: e.target.value })}
              className={inputCls}
              placeholder={autoCarbon.toFixed(2)}
            />
          </div>
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          loading={busy}
          icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
        >
          {isEdit
            ? t('common.save', { defaultValue: 'Save' })
            : t('common.create', { defaultValue: 'Create' })}
        </Button>
      </div>
    </ModalShell>
  );
}

/* ─── Assign BOQ position → embodied carbon (CONN-60) ─── */

interface BoqListItem {
  id: string;
  name: string;
}
interface BoqPositionRow {
  id: string;
  boq_id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number | string;
}
interface BoqWithPositions {
  positions: BoqPositionRow[];
}

/** Human label for a material factor in the picker: EPD product name when
 *  the factor is EPD-backed, the manual override otherwise, plus unit /
 *  region / confidence so the estimator can tell two factors apart. */
function factorLabel(
  f: MaterialCarbonFactor,
  epdById: Map<string, EPDRecord>,
): string {
  const epd = f.epd_id ? epdById.get(f.epd_id) : undefined;
  const head = epd
    ? epd.product_name
    : f.manual_override_factor != null
      ? `Manual ${toNum(f.manual_override_factor)} kgCO2e/${f.unit_for_factor}`
      : (f.notes || 'Factor');
  const region = f.region ? ` · ${f.region}` : '';
  return `${head} · /${f.unit_for_factor}${region} · ${f.confidence}`;
}

function AssignBoqModal({
  inventoryId,
  projectId,
  onClose,
  onSaved,
}: {
  inventoryId: string;
  projectId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [boqId, setBoqId] = useState('');
  const [search, setSearch] = useState('');
  const [position, setPosition] = useState<BoqPositionRow | null>(null);
  const [factorId, setFactorId] = useState('');
  const [quantity, setQuantity] = useState('');
  const [quantityUnit, setQuantityUnit] = useState('');
  const [stage, setStage] = useState<Stage>('a1a3');
  const [density, setDensity] = useState('');
  const [busy, setBusy] = useState(false);

  const boqsQ = useQuery({
    queryKey: ['carbon', 'boqs', projectId],
    queryFn: () =>
      apiGet<BoqListItem[]>(`/v1/boq/boqs/?project_id=${projectId}`).catch(
        () => [] as BoqListItem[],
      ),
    enabled: !!projectId,
  });
  const boqs = boqsQ.data ?? [];

  const boqDetailQ = useQuery({
    queryKey: ['carbon', 'boq-positions', boqId],
    queryFn: () => apiGet<BoqWithPositions>(`/v1/boq/boqs/${boqId}`),
    enabled: !!boqId,
  });

  const positions = useMemo(() => {
    const rows = boqDetailQ.data?.positions ?? [];
    const q = search.trim().toLowerCase();
    const filtered = q
      ? rows.filter(
          (p) =>
            (p.description || '').toLowerCase().includes(q) ||
            (p.ordinal || '').toLowerCase().includes(q),
        )
      : rows;
    return filtered.slice(0, 300);
  }, [boqDetailQ.data, search]);

  // Material factors + EPDs to label them. Both degrade to empty so the
  // modal still renders (the assign button just stays disabled).
  const factorsQ = useQuery({
    queryKey: ['carbon', 'material-factors'],
    queryFn: () => listMaterialFactors({ limit: 300 }).catch(() => []),
  });
  const epdsQ = useQuery({
    queryKey: ['carbon', 'epds', '', ''],
    queryFn: () => listEPDs({ limit: 300 }).catch(() => []),
    staleTime: 60_000,
  });
  const factors = factorsQ.data ?? [];
  const epdById = useMemo(() => {
    const m = new Map<string, EPDRecord>();
    for (const e of epdsQ.data ?? []) m.set(e.id, e);
    return m;
  }, [epdsQ.data]);

  function pickPosition(p: BoqPositionRow) {
    setPosition(p);
    setQuantity(String(toNum(p.quantity)));
    setQuantityUnit(p.unit || 'kg');
  }

  const canSubmit =
    !!position && !!factorId && quantity.trim() !== '' && quantityUnit.trim() !== '';

  async function submit() {
    if (!position || !canSubmit) return;
    setBusy(true);
    try {
      await assignBoqPosition(inventoryId, {
        boq_position_id: position.id,
        material_factor_id: factorId,
        quantity: Number(quantity) || 0,
        quantity_unit: quantityUnit,
        stage,
        density_kg_per_m3: density.trim() !== '' ? Number(density) : null,
      });
      addToast({
        type: 'success',
        title: t('carbon.boq_assigned', {
          defaultValue: 'BOQ position added to inventory',
        }),
      });
      onSaved();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  const needsDensity = quantityUnit === 'm3' || quantityUnit === 'm2';

  return (
    <ModalShell
      title={t('carbon.add_from_boq', { defaultValue: 'Add from BOQ' })}
      onClose={onClose}
    >
      {!projectId ? (
        <p className="rounded-md bg-surface-secondary/60 p-3 text-sm text-content-tertiary">
          {t('carbon.boq_no_project', {
            defaultValue: 'This inventory has no project, so no BOQ is available.',
          })}
        </p>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-content-tertiary">
            {t('carbon.add_from_boq_hint', {
              defaultValue:
                'Pick a priced BOQ position and a material carbon factor. The factor (from an EPD or a manual override) is multiplied by the quantity to compute embodied kgCO2e.',
            })}
          </p>

          {/* BOQ selector */}
          <div>
            <label className={labelCls}>
              {t('carbon.boq', { defaultValue: 'BOQ' })}
            </label>
            <select
              value={boqId}
              onChange={(e) => {
                setBoqId(e.target.value);
                setPosition(null);
              }}
              disabled={boqsQ.isLoading}
              className={inputCls}
            >
              <option value="">
                {boqsQ.isLoading
                  ? t('common.loading', { defaultValue: 'Loading...' })
                  : boqs.length > 0
                    ? t('common.select_boq', { defaultValue: 'Select BOQ...' })
                    : t('boq.no_boqs', { defaultValue: 'No BOQs found' })}
              </option>
              {boqs.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>

          {/* Position picker */}
          {boqId && !position && (
            <div>
              <label className={labelCls}>
                {t('carbon.boq_position', { defaultValue: 'Position' })}
              </label>
              <div className="relative mb-2">
                <Search
                  size={13}
                  className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
                />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('carbon.boq_search_placeholder', {
                    defaultValue: 'Filter by description or ordinal…',
                  })}
                  className={clsx(inputCls, 'pl-8')}
                  autoComplete="off"
                />
              </div>
              {boqDetailQ.isLoading ? (
                <SkeletonTable rows={5} columns={2} />
              ) : positions.length === 0 ? (
                <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-content-tertiary">
                  {t('carbon.boq_picker_empty', {
                    defaultValue: 'No positions match. Pick another BOQ or clear the filter.',
                  })}
                </p>
              ) : (
                <div className="max-h-64 overflow-y-auto rounded-lg border border-border-light">
                  <table className="w-full text-sm">
                    <tbody>
                      {positions.map((p) => (
                        <tr
                          key={p.id}
                          onClick={() => pickPosition(p)}
                          className="cursor-pointer border-t border-border-light first:border-t-0 hover:bg-surface-secondary"
                        >
                          <td className="px-3 py-2 font-mono text-xs text-content-secondary whitespace-nowrap align-top">
                            {p.ordinal}
                          </td>
                          <td className="px-3 py-2 text-content-primary">
                            {p.description}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-content-secondary whitespace-nowrap align-top">
                            {toNum(p.quantity)} {p.unit}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Chosen position + factor + quantity */}
          {position && (
            <>
              <div className="flex items-start justify-between gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
                <span className="min-w-0">
                  <span className="block truncate text-sm text-content-primary">
                    <span className="font-mono text-xs text-content-secondary">
                      {position.ordinal}
                    </span>{' '}
                    {position.description}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => setPosition(null)}
                  className="shrink-0 text-xs text-oe-blue hover:underline"
                >
                  {t('common.change', { defaultValue: 'Change' })}
                </button>
              </div>

              <div>
                <label className={labelCls}>
                  {t('carbon.material_factor', { defaultValue: 'Material carbon factor' })}
                </label>
                <select
                  value={factorId}
                  onChange={(e) => setFactorId(e.target.value)}
                  disabled={factorsQ.isLoading}
                  className={inputCls}
                >
                  <option value="">
                    {factorsQ.isLoading
                      ? t('common.loading', { defaultValue: 'Loading...' })
                      : factors.length > 0
                        ? t('carbon.select_factor', { defaultValue: 'Select factor...' })
                        : t('carbon.no_factors', { defaultValue: 'No factors found' })}
                  </option>
                  {factors.map((f) => (
                    <option key={f.id} value={f.id}>
                      {factorLabel(f, epdById)}
                    </option>
                  ))}
                </select>
                {!factorsQ.isLoading && factors.length === 0 && (
                  <p className="mt-1 text-xs text-content-tertiary">
                    {t('carbon.no_factors_hint', {
                      defaultValue:
                        'Create a material factor (link it to an EPD or set a manual override) to assign BOQ positions.',
                    })}
                  </p>
                )}
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className={labelCls}>
                    {t('carbon.quantity', { defaultValue: 'Quantity' })}
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>
                    {t('carbon.col_unit', { defaultValue: 'Unit' })}
                  </label>
                  <select
                    value={quantityUnit}
                    onChange={(e) => setQuantityUnit(e.target.value)}
                    className={inputCls}
                  >
                    {['kg', 't', 'm3', 'm2', 'm', 'pcs'].map((u) => (
                      <option key={u} value={u}>
                        {u}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>
                    {t('carbon.stage', { defaultValue: 'Stage' })}
                  </label>
                  <select
                    value={stage}
                    onChange={(e) => setStage(e.target.value as Stage)}
                    className={inputCls}
                  >
                    {(['a1a3', 'a4', 'a5', 'b', 'c', 'd'] as Stage[]).map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {needsDensity && (
                <div>
                  <label className={labelCls}>
                    {t('carbon.density', {
                      defaultValue: 'Density (kg/m³) - for m³/m² ↔ kg conversion',
                    })}
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={density}
                    onChange={(e) => setDensity(e.target.value)}
                    className={inputCls}
                    placeholder="e.g. 2400"
                  />
                </div>
              )}
            </>
          )}
        </div>
      )}

      <div className="flex justify-end gap-2 mt-5">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          loading={busy}
          disabled={!canSubmit}
          icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
        >
          {t('carbon.assign_to_inventory', { defaultValue: 'Add to inventory' })}
        </Button>
      </div>
    </ModalShell>
  );
}

function ScopeEntryModal({
  inventoryId,
  kind,
  entry,
  onClose,
  onSaved,
}: {
  inventoryId: string;
  kind: 's1' | 's2' | 's3';
  entry?: Scope1Entry | Scope2Entry | Scope3Entry;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = !!entry;
  const [busy, setBusy] = useState(false);

  const s1 = entry as Scope1Entry | undefined;
  const s2 = entry as Scope2Entry | undefined;
  const s3 = entry as Scope3Entry | undefined;

  const [form, setForm] = useState({
    period_start: entry?.period_start ?? todayIso(-365),
    period_end: entry?.period_end ?? todayIso(),
    // scope 1
    fuel_type: s1?.fuel_type ?? 'diesel',
    litres_or_m3: String(s1?.litres_or_m3 ?? '0'),
    s1_factor: String(s1?.emission_factor_kg_co2e_per_unit ?? '0'),
    // scope 2
    energy_type: s2?.energy_type ?? 'grid_electricity',
    kwh: String(s2?.kwh ?? '0'),
    s2_factor: String(s2?.emission_factor_kg_co2e_per_kwh ?? '0'),
    market_or_location: s2?.market_or_location ?? 'location',
    supplier_name: s2?.supplier_name ?? '',
    // scope 3
    category: s3?.category ?? 'transport_upstream',
    description: s3?.description ?? '',
    activity_data: String(s3?.activity_data ?? '0'),
    activity_unit: s3?.activity_unit ?? 'tkm',
    s3_factor: String(s3?.emission_factor ?? '0'),
  });

  async function submit() {
    setBusy(true);
    try {
      if (kind === 's1') {
        const payload = {
          period_start: form.period_start,
          period_end: form.period_end,
          fuel_type: form.fuel_type,
          litres_or_m3: Number(form.litres_or_m3) || 0,
          emission_factor_kg_co2e_per_unit: Number(form.s1_factor) || 0,
        };
        if (isEdit && entry) await updateScope1(entry.id, payload);
        else await createScope1({ inventory_id: inventoryId, ...payload });
      } else if (kind === 's2') {
        const payload = {
          period_start: form.period_start,
          period_end: form.period_end,
          energy_type: form.energy_type,
          kwh: Number(form.kwh) || 0,
          emission_factor_kg_co2e_per_kwh: Number(form.s2_factor) || 0,
          market_or_location: form.market_or_location,
          supplier_name: form.supplier_name || null,
        };
        if (isEdit && entry) await updateScope2(entry.id, payload);
        else await createScope2({ inventory_id: inventoryId, ...payload });
      } else {
        const payload = {
          period_start: form.period_start,
          period_end: form.period_end,
          category: form.category,
          description: form.description,
          activity_data: Number(form.activity_data) || 0,
          activity_unit: form.activity_unit,
          emission_factor: Number(form.s3_factor) || 0,
        };
        if (isEdit && entry) await updateScope3(entry.id, payload);
        else await createScope3({ inventory_id: inventoryId, ...payload });
      }
      addToast({
        type: 'success',
        title: isEdit
          ? t('carbon.entry_updated', { defaultValue: 'Entry updated' })
          : t('carbon.entry_created', { defaultValue: 'Entry created' }),
      });
      onSaved();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  const title =
    kind === 's1'
      ? t('carbon.scope1_entry', { defaultValue: 'Scope 1 entry' })
      : kind === 's2'
        ? t('carbon.scope2_entry', { defaultValue: 'Scope 2 entry' })
        : t('carbon.scope3_entry', { defaultValue: 'Scope 3 entry' });

  return (
    <ModalShell
      title={`${isEdit ? t('common.edit', { defaultValue: 'Edit' }) : t('common.create', { defaultValue: 'Create' })} - ${title}`}
      onClose={onClose}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.period_start', { defaultValue: 'Period start' })}
            </label>
            <input
              type="date"
              value={form.period_start}
              onChange={(e) =>
                setForm({ ...form, period_start: e.target.value })
              }
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.period_end', { defaultValue: 'Period end' })}
            </label>
            <input
              type="date"
              value={form.period_end}
              onChange={(e) =>
                setForm({ ...form, period_end: e.target.value })
              }
              className={inputCls}
            />
          </div>
        </div>

        {kind === 's1' && (
          <>
            <div>
              <label className={labelCls}>
                {t('carbon.fuel_type', { defaultValue: 'Fuel type' })}
              </label>
              <select
                value={form.fuel_type}
                onChange={(e) =>
                  setForm({ ...form, fuel_type: e.target.value })
                }
                className={inputCls}
              >
                <option value="diesel">diesel</option>
                <option value="petrol">petrol</option>
                <option value="lpg">lpg</option>
                <option value="natural_gas">natural_gas</option>
                <option value="other">other</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>
                  {t('carbon.litres_or_m3', {
                    defaultValue: 'Litres or m³',
                  })}
                </label>
                <input
                  type="number"
                  step="any"
                  value={form.litres_or_m3}
                  onChange={(e) =>
                    setForm({ ...form, litres_or_m3: e.target.value })
                  }
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('carbon.emission_factor', {
                    defaultValue: 'Emission factor',
                  })}
                </label>
                <input
                  type="number"
                  step="any"
                  value={form.s1_factor}
                  onChange={(e) =>
                    setForm({ ...form, s1_factor: e.target.value })
                  }
                  className={inputCls}
                />
              </div>
            </div>
          </>
        )}

        {kind === 's2' && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>
                  {t('carbon.energy_type', { defaultValue: 'Energy type' })}
                </label>
                <select
                  value={form.energy_type}
                  onChange={(e) =>
                    setForm({ ...form, energy_type: e.target.value })
                  }
                  className={inputCls}
                >
                  <option value="grid_electricity">grid_electricity</option>
                  <option value="district_heating">district_heating</option>
                  <option value="cooling">cooling</option>
                </select>
              </div>
              <div>
                <label className={labelCls}>
                  {t('carbon.market_or_location', {
                    defaultValue: 'Market / location',
                  })}
                </label>
                <select
                  value={form.market_or_location}
                  onChange={(e) =>
                    setForm({ ...form, market_or_location: e.target.value })
                  }
                  className={inputCls}
                >
                  <option value="location">location</option>
                  <option value="market">market</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>kWh</label>
                <input
                  type="number"
                  step="any"
                  value={form.kwh}
                  onChange={(e) => setForm({ ...form, kwh: e.target.value })}
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('carbon.emission_factor', {
                    defaultValue: 'Emission factor',
                  })}
                </label>
                <input
                  type="number"
                  step="any"
                  value={form.s2_factor}
                  onChange={(e) =>
                    setForm({ ...form, s2_factor: e.target.value })
                  }
                  className={inputCls}
                />
              </div>
            </div>
            <div>
              <label className={labelCls}>
                {t('carbon.supplier_name', {
                  defaultValue: 'Supplier name',
                })}
              </label>
              <input
                value={form.supplier_name}
                onChange={(e) =>
                  setForm({ ...form, supplier_name: e.target.value })
                }
                className={inputCls}
              />
            </div>
          </>
        )}

        {kind === 's3' && (
          <>
            <div>
              <label className={labelCls}>
                {t('carbon.category', { defaultValue: 'Category' })}
              </label>
              <select
                value={form.category}
                onChange={(e) =>
                  setForm({ ...form, category: e.target.value })
                }
                className={inputCls}
              >
                <option value="transport_upstream">transport_upstream</option>
                <option value="transport_downstream">
                  transport_downstream
                </option>
                <option value="waste">waste</option>
                <option value="business_travel">business_travel</option>
                <option value="other">other</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>
                {t('carbon.description', { defaultValue: 'Description' })}
              </label>
              <input
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
                className={inputCls}
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className={labelCls}>
                  {t('carbon.activity_data', {
                    defaultValue: 'Activity data',
                  })}
                </label>
                <input
                  type="number"
                  step="any"
                  value={form.activity_data}
                  onChange={(e) =>
                    setForm({ ...form, activity_data: e.target.value })
                  }
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('carbon.activity_unit', {
                    defaultValue: 'Activity unit',
                  })}
                </label>
                <input
                  value={form.activity_unit}
                  onChange={(e) =>
                    setForm({ ...form, activity_unit: e.target.value })
                  }
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('carbon.emission_factor', {
                    defaultValue: 'Emission factor',
                  })}
                </label>
                <input
                  type="number"
                  step="any"
                  value={form.s3_factor}
                  onChange={(e) =>
                    setForm({ ...form, s3_factor: e.target.value })
                  }
                  className={inputCls}
                />
              </div>
            </div>
          </>
        )}
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          loading={busy}
          icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
        >
          {isEdit
            ? t('common.save', { defaultValue: 'Save' })
            : t('common.create', { defaultValue: 'Create' })}
        </Button>
      </div>
    </ModalShell>
  );
}

function EPDModal({
  epd,
  onClose,
}: {
  epd?: EPDRecord;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = !!epd;
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    epd_id: epd?.epd_id ?? '',
    source: (epd?.source ?? 'custom') as EPDSource,
    material_class: epd?.material_class ?? '',
    product_name: epd?.product_name ?? '',
    manufacturer: epd?.manufacturer ?? '',
    region: epd?.region ?? '',
    declared_unit: epd?.declared_unit ?? 'kg',
    gwp_a1a3: String(epd?.gwp_a1a3 ?? '0'),
    gwp_a4: epd?.gwp_a4 != null ? String(epd.gwp_a4) : '',
    gwp_a5: epd?.gwp_a5 != null ? String(epd.gwp_a5) : '',
    gwp_c_total: epd?.gwp_c_total != null ? String(epd.gwp_c_total) : '',
    gwp_d_credits: epd?.gwp_d_credits != null ? String(epd.gwp_d_credits) : '',
    validity_until: epd?.validity_until ?? '',
    document_url: epd?.document_url ?? '',
  });

  function num(v: string): number | null {
    if (v.trim() === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  async function submit() {
    if (!form.product_name.trim() || !form.material_class.trim()) {
      addToast({
        type: 'error',
        title: t('carbon.epd_required', {
          defaultValue: 'Product name and material class are required',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      if (isEdit && epd) {
        await updateEPD(epd.id, {
          source: form.source,
          material_class: form.material_class,
          product_name: form.product_name,
          manufacturer: form.manufacturer || null,
          region: form.region,
          declared_unit: form.declared_unit,
          gwp_a1a3: Number(form.gwp_a1a3) || 0,
          gwp_a4: num(form.gwp_a4),
          gwp_a5: num(form.gwp_a5),
          gwp_c_total: num(form.gwp_c_total),
          gwp_d_credits: num(form.gwp_d_credits),
          validity_until: form.validity_until || null,
          document_url: form.document_url || null,
        });
        addToast({
          type: 'success',
          title: t('carbon.epd_updated', { defaultValue: 'EPD updated' }),
        });
      } else {
        await createEPD({
          epd_id:
            form.epd_id.trim() ||
            `custom:${form.material_class}:${Date.now()}`,
          source: form.source,
          material_class: form.material_class,
          product_name: form.product_name,
          manufacturer: form.manufacturer || null,
          region: form.region,
          declared_unit: form.declared_unit,
          gwp_a1a3: Number(form.gwp_a1a3) || 0,
          gwp_a4: num(form.gwp_a4),
          gwp_a5: num(form.gwp_a5),
          gwp_c_total: num(form.gwp_c_total),
          gwp_d_credits: num(form.gwp_d_credits),
          validity_until: form.validity_until || null,
          document_url: form.document_url || null,
        });
        addToast({
          type: 'success',
          title: t('carbon.epd_created', { defaultValue: 'EPD created' }),
        });
      }
      qc.invalidateQueries({ queryKey: ['carbon', 'epds'] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      title={
        isEdit
          ? t('carbon.edit_epd', { defaultValue: 'Edit EPD' })
          : t('carbon.new_epd', { defaultValue: 'New EPD' })
      }
      onClose={onClose}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.epd_identifier', { defaultValue: 'EPD identifier' })}
            </label>
            <input
              value={form.epd_id}
              onChange={(e) => setForm({ ...form, epd_id: e.target.value })}
              className={inputCls}
              placeholder="oekobaudat:1.4.01"
              disabled={isEdit}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.col_source', { defaultValue: 'Source' })}
            </label>
            <select
              value={form.source}
              onChange={(e) =>
                setForm({ ...form, source: e.target.value as EPDSource })
              }
              className={inputCls}
            >
              <option value="custom">custom</option>
              <option value="oekobaudat">oekobaudat</option>
              <option value="ice">ice</option>
              <option value="ec3">ec3</option>
            </select>
          </div>
        </div>
        <div>
          <label className={labelCls}>
            {t('carbon.col_product', { defaultValue: 'Product' })}
          </label>
          <input
            value={form.product_name}
            onChange={(e) => setForm({ ...form, product_name: e.target.value })}
            className={inputCls}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.material_class', { defaultValue: 'Material class' })}
            </label>
            <input
              value={form.material_class}
              onChange={(e) =>
                setForm({ ...form, material_class: e.target.value })
              }
              className={inputCls}
              placeholder="concrete, steel…"
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.manufacturer', { defaultValue: 'Manufacturer' })}
            </label>
            <input
              value={form.manufacturer}
              onChange={(e) =>
                setForm({ ...form, manufacturer: e.target.value })
              }
              className={inputCls}
            />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.region', { defaultValue: 'Region' })}
            </label>
            <input
              value={form.region}
              onChange={(e) => setForm({ ...form, region: e.target.value })}
              className={inputCls}
              maxLength={8}
              placeholder="DE, EU…"
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.col_unit', { defaultValue: 'Unit' })}
            </label>
            <input
              value={form.declared_unit}
              onChange={(e) =>
                setForm({ ...form, declared_unit: e.target.value })
              }
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.validity_until', { defaultValue: 'Valid until' })}
            </label>
            <input
              type="date"
              value={form.validity_until ?? ''}
              onChange={(e) =>
                setForm({ ...form, validity_until: e.target.value })
              }
              className={inputCls}
            />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelCls}>
              {t('carbon.col_gwp', { defaultValue: 'GWP A1–A3' })}
            </label>
            <input
              type="number"
              step="any"
              value={form.gwp_a1a3}
              onChange={(e) => setForm({ ...form, gwp_a1a3: e.target.value })}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>GWP A4</label>
            <input
              type="number"
              step="any"
              value={form.gwp_a4}
              onChange={(e) => setForm({ ...form, gwp_a4: e.target.value })}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>GWP A5</label>
            <input
              type="number"
              step="any"
              value={form.gwp_a5}
              onChange={(e) => setForm({ ...form, gwp_a5: e.target.value })}
              className={inputCls}
            />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelCls}>GWP C</label>
            <input
              type="number"
              step="any"
              value={form.gwp_c_total}
              onChange={(e) =>
                setForm({ ...form, gwp_c_total: e.target.value })
              }
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>GWP D</label>
            <input
              type="number"
              step="any"
              value={form.gwp_d_credits}
              onChange={(e) =>
                setForm({ ...form, gwp_d_credits: e.target.value })
              }
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('carbon.document_url', { defaultValue: 'Document URL' })}
            </label>
            <input
              value={form.document_url ?? ''}
              onChange={(e) =>
                setForm({ ...form, document_url: e.target.value })
              }
              className={inputCls}
            />
          </div>
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          loading={busy}
          icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
        >
          {isEdit
            ? t('common.save', { defaultValue: 'Save' })
            : t('common.create', { defaultValue: 'Create' })}
        </Button>
      </div>
    </ModalShell>
  );
}

function ModalShell({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  useEscapeToClose(onClose);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="carbon-modal-title"
        className="relative w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-xl bg-surface-elevated p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 id="carbon-modal-title" className="text-lg font-semibold">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
