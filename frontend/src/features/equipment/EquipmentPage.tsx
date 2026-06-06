import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  Truck,
  Plus,
  Search,
  X,
  Loader2,
  Activity,
  Wrench,
  ShieldCheck,
  AlertTriangle,
  MapPin,
  Pencil,
  Trash2,
  Save,
  Info,
  Tags,
  Gauge,
  HeartPulse,
  Users,
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
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import {
  listEquipment,
  getEquipment,
  getEquipmentDashboard,
  createEquipment,
  updateEquipment,
  deleteEquipment,
  listTelemetry,
  recordTelemetry,
  listMaintenanceWorkOrders,
  deleteWorkOrder,
  completeWorkOrder,
  listInspections,
  deleteInspection,
  listDamageReports,
  deleteDamageReport,
  listTypes,
  deleteType,
  type Equipment,
  type EquipmentStatus,
  type WorkOrderStatus,
  type InspectionResult,
  type DamageSeverity,
  type Ownership,
  type CreateEquipmentPayload,
  type MaintenanceWorkOrder as ApiWorkOrder,
  type Inspection as ApiInspection,
  type DamageReport as ApiDamage,
  type EquipmentType as ApiEquipmentType,
} from './api';
import { WorkOrderFormModal } from './modals/WorkOrderFormModal';
import { InspectionFormModal } from './modals/InspectionFormModal';
import { DamageReportFormModal } from './modals/DamageReportFormModal';
import { TypeFormModal } from './modals/TypeFormModal';
import { EquipmentHealthDashboard } from './components/EquipmentHealthDashboard';
import { FleetOptimizationPanel } from './components/FleetOptimizationPanel';

type DrawerTab =
  | 'utilization'
  | 'health'
  | 'maintenance'
  | 'certifications'
  | 'damage';
const EQUIPMENT_TAB_IDS = ['assets', 'types'] as const;
type PageTab = (typeof EQUIPMENT_TAB_IDS)[number];

const STATUS_VARIANT: Record<
  EquipmentStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  active: 'success',
  under_maintenance: 'warning',
  decommissioned: 'neutral',
  reserved: 'blue',
};

const WO_STATUS_VARIANT: Record<
  WorkOrderStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  scheduled: 'blue',
  in_progress: 'warning',
  completed: 'success',
  cancelled: 'neutral',
};

const INSPECTION_VARIANT: Record<
  InspectionResult,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  pass: 'success',
  fail: 'error',
  conditional: 'warning',
};

const DAMAGE_VARIANT: Record<
  DamageSeverity,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  minor: 'neutral',
  major: 'warning',
  critical: 'error',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

function toNum(n: number | string | null | undefined): number {
  if (n === null || n === undefined) return 0;
  return typeof n === 'number' ? n : Number(n) || 0;
}

export function EquipmentPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [pageTab, setPageTab] = useState<PageTab>('assets');
  const onTabKeyDown = useTabKeyboardNav<PageTab>({
    ids: EQUIPMENT_TAB_IDS,
    activeId: pageTab,
    onChange: setPageTab,
    orientation: 'horizontal',
  });
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [ownershipFilter, setOwnershipFilter] = useState<string>('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const eqQ = useQuery({
    queryKey: ['equipment', 'list', statusFilter, ownershipFilter],
    queryFn: () =>
      listEquipment({
        limit: 200,
        status: statusFilter || undefined,
        ownership: ownershipFilter || undefined,
      }),
  });

  // The fleet is not single-currency; use the most common configured
  // currency among loaded units so the Fleet Intelligence money cells render
  // in something meaningful rather than an em-dash.
  const fleetCurrency = useMemo(() => {
    const items = eqQ.data ?? [];
    const counts = new Map<string, number>();
    for (const it of items) {
      const c = (it.currency || '').trim();
      if (c) counts.set(c, (counts.get(c) ?? 0) + 1);
    }
    let best: string | undefined;
    let bestN = 0;
    for (const [c, n] of counts) {
      if (n > bestN) {
        best = c;
        bestN = n;
      }
    }
    return best;
  }, [eqQ.data]);

  const filtered = useMemo(() => {
    const items = eqQ.data ?? [];
    const s = search.toLowerCase();
    if (!s) return items;
    return items.filter(
      (it) =>
        it.code.toLowerCase().includes(s) ||
        it.name.toLowerCase().includes(s) ||
        (it.manufacturer || '').toLowerCase().includes(s) ||
        (it.model || '').toLowerCase().includes(s) ||
        (it.serial || '').toLowerCase().includes(s),
    );
  }, [eqQ.data, search]);

  return (
    <div className="space-y-5">
      <Breadcrumb
        items={[
          {
            label: t('nav.equipment', { defaultValue: 'Equipment & Fleet' }),
          },
        ]}
      />

      <PageHeader
        srTitle={t('equipment.title', { defaultValue: 'Equipment & Fleet' })}
        subtitle={t('equipment.subtitle', {
          defaultValue:
            'Track equipment assets, utilization, maintenance and certifications.',
        })}
        actions={
          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setCreateOpen(true)}
          >
            {t('equipment.new', { defaultValue: 'New Asset' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="equipment"
        title={t('equipment.intro_title', {
          defaultValue: 'Keep unsafe plant off the site',
        })}
        more={
          t('equipment.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('equipment.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('equipment.intro_link_resources', { defaultValue: 'Resources' }),
            onClick: () => navigate('/resources'),
          },
          {
            label: t('equipment.intro_link_finance', { defaultValue: 'Finance' }),
            onClick: () => navigate('/finance'),
          },
          {
            label: t('equipment.intro_link_building_assets', {
              defaultValue: 'Building Assets (FM)',
            }),
            onClick: () => navigate('/assets'),
          },
        ]}
      >
        {t('equipment.intro_body', {
          defaultValue:
            'Register every owned, rented or leased machine, then open an asset to see utilisation, month-to-date fuel cost, open maintenance work orders and certification expiry. An asset that is not active, or whose required inspection has lapsed, is automatically blocked from new resource assignments, and its running cost flows through to Finance.',
        })}
      </DismissibleInfo>

      <div className="border-b border-border-light">
        <nav
          className="flex gap-1 -mb-px"
          role="tablist"
          aria-label={t('equipment.tabs_aria', { defaultValue: 'Equipment sections' })}
          onKeyDown={onTabKeyDown}
        >
          {(
            [
              { id: 'assets', label: t('equipment.tab_assets', { defaultValue: 'Assets' }), icon: Truck },
              { id: 'types', label: t('equipment.tab_types', { defaultValue: 'Types' }), icon: Tags },
            ] as { id: PageTab; label: string; icon: React.ElementType }[]
          ).map((pt) => {
            const Icon = pt.icon;
            const active = pageTab === pt.id;
            return (
              <button
                key={pt.id}
                type="button"
                role="tab"
                id={`equipment-tab-${pt.id}`}
                aria-selected={active}
                aria-controls={`equipment-panel-${pt.id}`}
                tabIndex={active ? 0 : -1}
                onClick={() => setPageTab(pt.id)}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                  active
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {pt.label}
              </button>
            );
          })}
        </nav>
      </div>

      {pageTab === 'types' ? (
        <TypesPage />
      ) : (
      <>
      <FleetOptimizationPanel
        currency={fleetCurrency}
        onSelect={setSelectedId}
      />
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="text"
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={clsx(inputCls, 'pl-8')}
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={clsx(inputCls, 'max-w-[180px]')}
        >
          <option value="">
            {t('common.all_statuses', { defaultValue: 'All statuses' })}
          </option>
          {(
            ['active', 'under_maintenance', 'decommissioned', 'reserved'] as EquipmentStatus[]
          ).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          value={ownershipFilter}
          onChange={(e) => setOwnershipFilter(e.target.value)}
          className={clsx(inputCls, 'max-w-[160px]')}
        >
          <option value="">
            {t('equipment.all_ownership', { defaultValue: 'All ownership' })}
          </option>
          {(['owned', 'rented', 'leased'] as Ownership[]).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>

      <Card padding="none">
        {eqQ.isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} columns={5} />
          </div>
        ) : eqQ.isError ? (
          <EmptyState
            icon={<AlertTriangle size={22} />}
            title={t('equipment.load_error', {
              defaultValue: 'Could not load equipment',
            })}
            description={getErrorMessage(eqQ.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => {
                void eqQ.refetch();
              },
            }}
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Truck size={22} />}
            title={t('equipment.empty', { defaultValue: 'No equipment yet' })}
            description={t('equipment.empty_desc', {
              defaultValue:
                'Register equipment to track utilization, maintenance schedules and certifications.',
            })}
            action={{
              label: t('equipment.new', { defaultValue: 'New Asset' }),
              onClick: () => setCreateOpen(true),
            }}
          />
        ) : (
          <AssetTable rows={filtered} onSelect={setSelectedId} />
        )}
      </Card>
      </>
      )}

      {selectedId && (
        <DetailDrawer id={selectedId} onClose={() => setSelectedId(null)} />
      )}

      {createOpen && (
        <EquipmentFormModal
          mode="create"
          onClose={() => setCreateOpen(false)}
        />
      )}
    </div>
  );
}

/* ─── Table ─── */

function AssetTable({
  rows,
  onSelect,
}: {
  rows: Equipment[];
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('equipment.col_code', { defaultValue: 'Code' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('equipment.col_name', { defaultValue: 'Name' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('equipment.col_type', { defaultValue: 'Type' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('equipment.col_status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('equipment.col_location', { defaultValue: 'Location' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('equipment.col_hours', { defaultValue: 'Hours' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">
                {r.code}
              </td>
              <td className="px-4 py-2">
                <div className="font-medium text-content-primary truncate max-w-[280px]">
                  {r.name}
                </div>
                {(r.manufacturer || r.model) && (
                  <div className="text-xs text-content-tertiary truncate max-w-[280px]">
                    {[r.manufacturer, r.model].filter(Boolean).join(' · ')}
                  </div>
                )}
              </td>
              <td className="px-4 py-2 text-content-secondary text-xs">
                {r.type_code}
              </td>
              <td className="px-4 py-2">
                <Badge variant={STATUS_VARIANT[r.status]} dot>
                  {r.status}
                </Badge>
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.location_lat !== null &&
                r.location_lng !== null &&
                r.location_lat !== undefined &&
                r.location_lng !== undefined ? (
                  <span className="inline-flex items-center gap-1">
                    <MapPin size={11} className="text-content-tertiary" />
                    {r.location_lat.toFixed(2)}, {r.location_lng.toFixed(2)}
                  </span>
                ) : (
                  '—'
                )}
              </td>
              <td className="px-4 py-2 text-right text-xs tabular-nums">
                {toNum(r.hour_meter).toFixed(0)} h
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Detail Drawer ─── */

function DetailDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [tab, setTab] = useState<DrawerTab>('utilization');
  // Edit + delete UI state — both gated to the loaded equipment so the
  // header buttons can't fire stale operations against a different id.
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Fetch the single record via the dedicated endpoint. The previous
  // implementation listed up to 500 units and `.find()`-ed the row, which
  // (a) silently returned "asset no longer exists" for any fleet larger
  // than 500 units and (b) refetched the whole list on every drawer open.
  // A 404 here is a genuine "not found"; React Query keeps it in `error`.
  const eqQ = useQuery({
    queryKey: ['equipment', 'detail', id],
    queryFn: () => getEquipment(id),
  });
  const eq = eqQ.data;

  // Per-unit KPI rollup (utilization %, fuel cost MTD, open work orders,
  // expiring inspections, and the assignment-blocked flag). These are
  // computed server-side but were never surfaced — most importantly the
  // `blocked` state, which is invisible to dispatchers without this.
  const dashQ = useQuery({
    queryKey: ['equipment', 'unitDashboard', id],
    queryFn: () => getEquipmentDashboard(id),
    enabled: !!eq,
  });

  // Close on Escape — symmetric with EquipmentFormModal so keyboard
  // users get a predictable dismissal. Skipped while a destructive
  // confirm/delete is in flight so we don't tear the drawer out from
  // under an in-progress request, and while a child modal is open
  // (that modal handles its own Escape).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.key === 'Escape' &&
        !deleting &&
        !editOpen &&
        !deleteOpen
      ) {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [deleting, editOpen, deleteOpen, onClose]);

  const handleDelete = async () => {
    if (!eq) return;
    setDeleting(true);
    try {
      await deleteEquipment(eq.id);
      addToast({
        type: 'success',
        title: t('equipment.deleted', {
          defaultValue: '{{name}} deleted',
          name: eq.name,
        }),
      });
      // Invalidate every cached query that referenced this asset so the
      // list page, the dashboard and any open child drawers (telemetry,
      // work orders, inspections, damage) drop their stale rows.
      qc.invalidateQueries({ queryKey: ['equipment'] });
      setDeleteOpen(false);
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setDeleting(false);
    }
  };

  const telemetryQ = useQuery({
    queryKey: ['equipment', 'telemetry', id],
    queryFn: () => listTelemetry(id, { limit: 50 }),
    enabled: !!id && tab === 'utilization',
  });

  const wosQ = useQuery({
    queryKey: ['equipment', 'workOrders', id],
    queryFn: () => listMaintenanceWorkOrders({ equipment_id: id }),
    enabled: !!id && tab === 'maintenance',
  });

  const insQ = useQuery({
    queryKey: ['equipment', 'inspections', id],
    queryFn: () => listInspections(id),
    enabled: !!id && tab === 'certifications',
  });

  const damQ = useQuery({
    queryKey: ['equipment', 'damage', id],
    queryFn: () => listDamageReports({ equipment_id: id }),
    enabled: !!id && tab === 'damage',
  });

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="equipment-drawer-title"
    >
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative h-full w-full max-w-2xl overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3 gap-3">
          <div className="min-w-0 flex-1">
            <h2
              id="equipment-drawer-title"
              className="text-base font-semibold truncate"
            >
              {eq ? `${eq.code} · ${eq.name}` : t('common.loading', { defaultValue: 'Loading…' })}
            </h2>
            {eq?.serial && (
              <p className="text-xs text-content-tertiary">SN: {eq.serial}</p>
            )}
          </div>
          {/* Action toolbar — Edit + Delete + Close. Disabled while the
              equipment is still loading so the buttons cannot fire
              against an undefined id. Each control is its own
              accessible button with aria-label rather than a tooltip-
              only icon, so screen-reader users get the same affordance. */}
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={() => navigate('/resources')}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:text-oe-blue-text hover:border-oe-blue hover:bg-oe-blue-subtle transition-colors"
              aria-label={t('equipment.view_assignments', {
                defaultValue: 'View assignments',
              })}
              title={t('equipment.view_assignments_hint', {
                defaultValue: 'Open the crew and resource assignments for this fleet',
              })}
            >
              <Users size={12} />
              {t('equipment.view_assignments', {
                defaultValue: 'View assignments',
              })}
            </button>
            <button
              type="button"
              onClick={() => setEditOpen(true)}
              disabled={!eq}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:text-oe-blue-text hover:border-oe-blue hover:bg-oe-blue-subtle transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label={t('common.edit', { defaultValue: 'Edit' })}
              title={t('equipment.edit_hint', {
                defaultValue: 'Edit equipment details',
              })}
            >
              <Pencil size={12} />
              {t('common.edit', { defaultValue: 'Edit' })}
            </button>
            <button
              type="button"
              onClick={() => setDeleteOpen(true)}
              disabled={!eq}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:text-rose-600 hover:border-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label={t('common.delete', { defaultValue: 'Delete' })}
              title={t('equipment.delete_hint', {
                defaultValue: 'Permanently remove this asset',
              })}
            >
              <Trash2 size={12} />
              {t('common.delete', { defaultValue: 'Delete' })}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="ml-1 rounded p-1 hover:bg-surface-secondary"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {!eq && eqQ.isLoading && (
          <div className="p-5">
            <SkeletonTable rows={6} columns={3} />
          </div>
        )}

        {!eq && !eqQ.isLoading && (
          <div className="p-5">
            <EmptyState
              icon={<AlertTriangle size={20} />}
              title={
                eqQ.isError
                  ? t('equipment.detail_error', {
                      defaultValue: 'Could not load this asset',
                    })
                  : t('equipment.detail_not_found', {
                      defaultValue: 'This asset no longer exists',
                    })
              }
              description={
                eqQ.isError ? getErrorMessage(eqQ.error) : undefined
              }
              action={
                eqQ.isError
                  ? {
                      label: t('common.retry', { defaultValue: 'Retry' }),
                      onClick: () => {
                        void eqQ.refetch();
                      },
                    }
                  : {
                      label: t('common.close', { defaultValue: 'Close' }),
                      onClick: onClose,
                    }
              }
            />
          </div>
        )}

        {eq && (
          <>
            <div className="grid grid-cols-2 gap-3 p-5 text-sm border-b border-border-light sm:grid-cols-4">
              <KV
                label={t('equipment.col_status', { defaultValue: 'Status' })}
                value={
                  <Badge variant={STATUS_VARIANT[eq.status]} dot>
                    {eq.status}
                  </Badge>
                }
              />
              <KV
                label={t('equipment.col_type', { defaultValue: 'Type' })}
                value={eq.type_code}
              />
              <KV
                label={t('equipment.ownership', { defaultValue: 'Ownership' })}
                value={eq.ownership}
              />
              <KV
                label={t('equipment.col_hours', { defaultValue: 'Hours' })}
                value={`${toNum(eq.hour_meter).toFixed(0)} h`}
              />
            </div>

            {dashQ.data?.blocked && (
              <div
                role="alert"
                className="mx-5 mt-3 flex items-start gap-2 rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error"
              >
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <span>
                  {t('equipment.blocked_banner', {
                    defaultValue:
                      'This unit is blocked from new assignments - its status is not active or a required inspection has expired.',
                  })}{' '}
                  <button
                    type="button"
                    onClick={() => navigate('/resources')}
                    className="font-medium underline underline-offset-2 hover:no-underline"
                  >
                    {t('equipment.blocked_banner_resources_link', {
                      defaultValue: 'Review crew assignments in Resources',
                    })}
                  </button>
                </span>
              </div>
            )}

            <div className="border-b border-border-light px-5">
              <nav className="flex gap-1 -mb-px">
                {(
                  [
                    {
                      id: 'utilization',
                      label: t('equipment.tab_utilization', {
                        defaultValue: 'Utilization',
                      }),
                      icon: Activity,
                    },
                    {
                      id: 'health',
                      label: t('equipment.tab_health', {
                        defaultValue: 'Health & Analytics',
                      }),
                      icon: HeartPulse,
                    },
                    {
                      id: 'maintenance',
                      label: t('equipment.tab_maintenance', {
                        defaultValue: 'Maintenance',
                      }),
                      icon: Wrench,
                    },
                    {
                      id: 'certifications',
                      label: t('equipment.tab_certifications', {
                        defaultValue: 'Certifications',
                      }),
                      icon: ShieldCheck,
                    },
                    {
                      id: 'damage',
                      label: t('equipment.tab_damage', {
                        defaultValue: 'Damage',
                      }),
                      icon: AlertTriangle,
                    },
                  ] as { id: DrawerTab; label: string; icon: React.ElementType }[]
                ).map((ti) => {
                  const Icon = ti.icon;
                  return (
                    <button
                      key={ti.id}
                      type="button"
                      onClick={() => setTab(ti.id)}
                      className={clsx(
                        'flex items-center gap-2 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors',
                        tab === ti.id
                          ? 'border-oe-blue text-oe-blue'
                          : 'border-transparent text-content-secondary hover:text-content-primary',
                      )}
                    >
                      <Icon size={12} />
                      {ti.label}
                    </button>
                  );
                })}
              </nav>
            </div>

            <div className="p-5 space-y-3">
              {tab === 'utilization' && (
                <UtilizationTab
                  equipment={eq}
                  telemetry={telemetryQ.data ?? []}
                  loading={telemetryQ.isLoading}
                  dashboard={dashQ.data ?? null}
                />
              )}
              {tab === 'health' && (
                <EquipmentHealthDashboard equipmentId={eq.id} />
              )}
              {tab === 'maintenance' && (
                <MaintenanceTab
                  equipmentId={eq.id}
                  rows={wosQ.data ?? []}
                  loading={wosQ.isLoading}
                />
              )}
              {tab === 'certifications' && (
                <CertificationsTab
                  equipmentId={eq.id}
                  rows={insQ.data ?? []}
                  loading={insQ.isLoading}
                />
              )}
              {tab === 'damage' && (
                <DamageTab
                  equipmentId={eq.id}
                  rows={damQ.data ?? []}
                  loading={damQ.isLoading}
                />
              )}
            </div>
          </>
        )}
      </div>

      {/* Edit modal — only mounts when the user clicks "Edit" AND the
          equipment record has finished loading. The modal is portalled
          to fixed positioning so it escapes the drawer's overflow-y. */}
      {editOpen && eq && (
        <EquipmentFormModal
          mode="edit"
          existing={eq}
          onClose={() => setEditOpen(false)}
        />
      )}
      {/* Delete confirmation — destructive action, intentionally requires
          a second click. The danger-variant ConfirmDialog already
          handles focus trapping + Escape. */}
      <ConfirmDialog
        open={deleteOpen}
        title={t('equipment.delete_title', {
          defaultValue: 'Delete equipment?',
        })}
        message={
          eq
            ? t('equipment.delete_message', {
                defaultValue:
                  'Delete "{{name}}" ({{code}})? This removes all telemetry, work orders, inspections and damage reports linked to this asset. This action cannot be undone.',
                name: eq.name,
                code: eq.code,
              })
            : ''
        }
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteOpen(false)}
        loading={deleting}
      />
    </div>
  );
}

/* ── Section header with tooltip + Add button ─────────────────────────── */

function SectionHeader({
  title,
  tooltip,
  addLabel,
  onAdd,
}: {
  title: string;
  tooltip: string;
  addLabel: string;
  onAdd: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-1.5">
        <h3 className="text-sm font-semibold text-content-primary">{title}</h3>
        <button
          type="button"
          className="inline-flex items-center justify-center rounded-full p-0.5 text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/10"
          title={tooltip}
          aria-label={t('common.info', { defaultValue: 'Info' })}
        >
          <Info size={13} strokeWidth={2} />
        </button>
      </div>
      <button
        type="button"
        onClick={onAdd}
        className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary hover:text-oe-blue-text hover:border-oe-blue hover:bg-oe-blue-subtle transition-colors"
      >
        <Plus size={12} />
        {addLabel}
      </button>
    </div>
  );
}

/* ── Hover-revealed row action icons (Pencil + Trash) ─────────────────── */

function RowActions({
  onEdit,
  onDelete,
  editLabel,
  deleteLabel,
}: {
  onEdit?: () => void;
  onDelete?: () => void;
  editLabel: string;
  deleteLabel: string;
}) {
  return (
    <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      {onEdit && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onEdit();
          }}
          className="rounded p-1 text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/10"
          aria-label={editLabel}
          title={editLabel}
        >
          <Pencil size={12} />
        </button>
      )}
      {onDelete && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="rounded p-1 text-content-tertiary hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30"
          aria-label={deleteLabel}
          title={deleteLabel}
        >
          <Trash2 size={12} />
        </button>
      )}
    </div>
  );
}

function UtilizationTab({
  equipment,
  telemetry,
  loading,
  dashboard,
}: {
  equipment: Equipment;
  telemetry: { id: string; recorded_at: string; fuel_level?: number | string | null; hour_meter?: number | string | null; odometer_km?: number | string | null; engine_status?: string | null }[];
  loading: boolean;
  dashboard: {
    utilization_pct: number;
    fuel_cost_mtd: number | string;
    open_work_orders: number;
    expiring_inspections: number;
  } | null;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [meterOpen, setMeterOpen] = useState(false);
  return (
    <div className="space-y-3">
      <SectionHeader
        title={t('equipment.utilization.title', {
          defaultValue: 'Utilization & telemetry',
        })}
        tooltip={t('equipment.utilization.tooltip', {
          defaultValue:
            'Live hour-meter, odometer and fuel-level readings. Each new reading rolls forward the asset state and can auto-fire a maintenance work order when a schedule is within 50 hours of due.',
        })}
        addLabel={t('equipment.utilization.add_meter', {
          defaultValue: 'Log meter reading',
        })}
        onAdd={() => setMeterOpen(true)}
      />
      {dashboard && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Card padding="sm">
            <p className="text-xs text-content-tertiary">
              {t('equipment.utilization_mtd', {
                defaultValue: 'Utilization (MTD)',
              })}
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {dashboard.utilization_pct.toFixed(0)}%
            </p>
          </Card>
          <Card padding="sm">
            <p className="text-xs text-content-tertiary">
              {t('equipment.fuel_cost_mtd', {
                defaultValue: 'Fuel cost (MTD)',
              })}
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              <MoneyDisplay
                amount={toNum(dashboard.fuel_cost_mtd)}
                currency={equipment.currency || undefined}
              />
            </p>
          </Card>
          <Card padding="sm">
            <p className="text-xs text-content-tertiary">
              {t('equipment.open_work_orders', {
                defaultValue: 'Open work orders',
              })}
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {dashboard.open_work_orders}
            </p>
          </Card>
          <Card padding="sm">
            <p className="text-xs text-content-tertiary">
              {t('equipment.expiring_inspections', {
                defaultValue: 'Expiring inspections',
              })}
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {dashboard.expiring_inspections}
            </p>
          </Card>
        </div>
      )}
      <div className="grid grid-cols-3 gap-2">
        <Card padding="sm">
          <p className="text-xs text-content-tertiary">
            {t('equipment.hour_meter', { defaultValue: 'Hour meter' })}
          </p>
          <p className="mt-1 text-lg font-semibold tabular-nums">
            {toNum(equipment.hour_meter).toFixed(0)} h
          </p>
        </Card>
        <Card padding="sm">
          <p className="text-xs text-content-tertiary">
            {t('equipment.odometer', { defaultValue: 'Odometer' })}
          </p>
          <p className="mt-1 text-lg font-semibold tabular-nums">
            {toNum(equipment.odometer_km).toFixed(0)} km
          </p>
        </Card>
        <Card padding="sm">
          <p className="text-xs text-content-tertiary">
            {t('equipment.last_telemetry', { defaultValue: 'Last reading' })}
          </p>
          <p className="mt-1 text-xs">
            {equipment.last_telemetry_at ? (
              <DateDisplay value={equipment.last_telemetry_at} />
            ) : (
              '—'
            )}
          </p>
        </Card>
      </div>

      {loading && <SkeletonTable rows={4} columns={4} />}
      {!loading && telemetry.length === 0 && (
        <EmptyState
          icon={<Activity size={20} />}
          title={t('equipment.no_telemetry', {
            defaultValue: 'No telemetry recorded',
          })}
        />
      )}
      {!loading && telemetry.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border-light">
          <table className="w-full text-xs">
            <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
              <tr>
                <th className="px-3 py-2 text-left">
                  {t('equipment.recorded_at', { defaultValue: 'Recorded at' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('equipment.col_hours', { defaultValue: 'Hours' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('equipment.km', { defaultValue: 'km' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('equipment.fuel_level', { defaultValue: 'Fuel %' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('equipment.engine_status', {
                    defaultValue: 'Engine',
                  })}
                </th>
              </tr>
            </thead>
            <tbody>
              {telemetry.map((r) => (
                <tr key={r.id} className="border-t border-border-light">
                  <td className="px-3 py-2 text-content-secondary">
                    <DateDisplay value={r.recorded_at} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {r.hour_meter !== null && r.hour_meter !== undefined
                      ? toNum(r.hour_meter).toFixed(0)
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {r.odometer_km !== null && r.odometer_km !== undefined
                      ? toNum(r.odometer_km).toFixed(0)
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {r.fuel_level !== null && r.fuel_level !== undefined
                      ? `${toNum(r.fuel_level).toFixed(0)}%`
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {r.engine_status || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {meterOpen && (
        <MeterReadingModal
          equipmentId={equipment.id}
          onClose={() => setMeterOpen(false)}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ['equipment'] });
            addToast({
              type: 'success',
              title: t('equipment.telemetry.recorded', {
                defaultValue: 'Reading recorded',
              }),
            });
          }}
        />
      )}
    </div>
  );
}

/* ── MeterReadingModal — single-shot telemetry POST ─────────────────── */

function MeterReadingModal({
  equipmentId,
  onClose,
  onSaved,
}: {
  equipmentId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  const [recordedAt, setRecordedAt] = useState(() =>
    new Date().toISOString().slice(0, 16),
  );
  const [hourMeter, setHourMeter] = useState('');
  const [odometer, setOdometer] = useState('');
  const [fuelLevel, setFuelLevel] = useState('');
  const [engineStatus, setEngineStatus] = useState('');

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', h, { capture: true });
    return () =>
      document.removeEventListener('keydown', h, { capture: true });
  }, [busy, onClose]);

  const submit = async () => {
    setBusy(true);
    try {
      const toNumOpt = (v: string): number | undefined => {
        if (v.trim() === '') return undefined;
        const n = Number(v.replace(',', '.'));
        return Number.isFinite(n) ? n : undefined;
      };
      await recordTelemetry(equipmentId, {
        recorded_at: new Date(recordedAt).toISOString(),
        hour_meter: toNumOpt(hourMeter),
        odometer_km: toNumOpt(odometer),
        fuel_level: toNumOpt(fuelLevel),
        engine_status: engineStatus.trim() || undefined,
      });
      onSaved();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-3"
      onClick={() => !busy && onClose()}
      role="dialog"
      aria-modal="true"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
      <div
        className="relative w-full max-w-md rounded-xl bg-surface-elevated p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('equipment.telemetry.new_title', {
              defaultValue: 'Log meter reading',
            })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded p-1 hover:bg-surface-secondary disabled:opacity-50"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>
        <div className="space-y-3">
          <div>
            <label className={labelCls}>
              {t('equipment.telemetry.recorded_at', {
                defaultValue: 'Recorded at',
              })}
            </label>
            <input
              type="datetime-local"
              value={recordedAt}
              onChange={(e) => setRecordedAt(e.target.value)}
              className={inputCls}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>
                {t('equipment.hour_meter', { defaultValue: 'Hour meter' })}
              </label>
              <input
                type="text"
                inputMode="decimal"
                value={hourMeter}
                onChange={(e) => setHourMeter(e.target.value)}
                className={inputCls}
                placeholder="1234"
              />
            </div>
            <div>
              <label className={labelCls}>
                {t('equipment.odometer', { defaultValue: 'Odometer (km)' })}
              </label>
              <input
                type="text"
                inputMode="decimal"
                value={odometer}
                onChange={(e) => setOdometer(e.target.value)}
                className={inputCls}
                placeholder="42000"
              />
            </div>
            <div>
              <label className={labelCls}>
                {t('equipment.fuel_level', { defaultValue: 'Fuel %' })}
              </label>
              <input
                type="text"
                inputMode="decimal"
                value={fuelLevel}
                onChange={(e) => setFuelLevel(e.target.value)}
                className={inputCls}
                placeholder="80"
              />
            </div>
            <div>
              <label className={labelCls}>
                {t('equipment.engine_status', { defaultValue: 'Engine' })}
              </label>
              <input
                value={engineStatus}
                onChange={(e) => setEngineStatus(e.target.value)}
                className={inputCls}
                placeholder="idle, running, off"
              />
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <Gauge size={14} />}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

function MaintenanceTab({
  equipmentId,
  rows,
  loading,
}: {
  equipmentId: string;
  rows: ApiWorkOrder[];
  loading: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ApiWorkOrder | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ['equipment', 'workOrders', equipmentId] });

  const handleDelete = async (id: string) => {
    try {
      await deleteWorkOrder(id);
      addToast({
        type: 'success',
        title: t('equipment.workorder.deleted', {
          defaultValue: 'Work order deleted',
        }),
      });
      invalidate();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setConfirmDeleteId(null);
    }
  };

  const handleComplete = async (id: string) => {
    try {
      await completeWorkOrder(id);
      addToast({
        type: 'success',
        title: t('equipment.workorder.completed', {
          defaultValue: 'Work order completed',
        }),
      });
      invalidate();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    }
  };

  return (
    <div className="space-y-3">
      <SectionHeader
        title={t('equipment.workorder.section_title', {
          defaultValue: 'Maintenance work orders',
        })}
        tooltip={t('equipment.workorder.tooltip', {
          defaultValue:
            'Scheduled, in-progress and completed work orders against this asset. Costs roll up into project Finance via the active rental.',
        })}
        addLabel={t('equipment.workorder.add', { defaultValue: 'Add work order' })}
        onAdd={() => setCreateOpen(true)}
      />

      {loading && <SkeletonTable rows={4} columns={4} />}
      {!loading && rows.length === 0 && (
        <EmptyState
          icon={<Wrench size={20} />}
          title={t('equipment.no_workorders', {
            defaultValue: 'No maintenance work orders',
          })}
        />
      )}
      {!loading && rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border-light">
          <table className="w-full text-xs">
            <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
              <tr>
                <th className="px-3 py-2 text-left">
                  {t('equipment.scheduled_for', { defaultValue: 'Scheduled' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('equipment.technician', { defaultValue: 'Technician' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('equipment.summary', { defaultValue: 'Summary' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('equipment.cost', { defaultValue: 'Cost' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('equipment.col_status', { defaultValue: 'Status' })}
                </th>
                <th className="px-3 py-2 w-[88px]" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  className="group border-t border-border-light hover:bg-surface-secondary"
                >
                  <td className="px-3 py-2 text-content-secondary">
                    {r.scheduled_for ? <DateDisplay value={r.scheduled_for} /> : '—'}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {r.technician_id || '—'}
                  </td>
                  <td className="px-3 py-2 truncate max-w-[200px]">
                    {r.work_summary || '—'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <MoneyDisplay
                      amount={toNum(r.cost)}
                      currency={r.currency || undefined}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={WO_STATUS_VARIANT[r.status]} dot>
                      {r.status}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      {(r.status === 'scheduled' || r.status === 'in_progress') && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleComplete(r.id);
                          }}
                          className="rounded p-1 text-content-tertiary hover:text-green-600 hover:bg-green-50 dark:hover:bg-green-950/30"
                          aria-label={t('equipment.workorder.complete', {
                            defaultValue: 'Mark complete',
                          })}
                          title={t('equipment.workorder.complete', {
                            defaultValue: 'Mark complete',
                          })}
                        >
                          <ShieldCheck size={12} />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditing(r);
                        }}
                        className="rounded p-1 text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/10"
                        aria-label={t('common.edit', { defaultValue: 'Edit' })}
                        title={t('common.edit', { defaultValue: 'Edit' })}
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteId(r.id);
                        }}
                        className="rounded p-1 text-content-tertiary hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30"
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        title={t('common.delete', { defaultValue: 'Delete' })}
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {createOpen && (
        <WorkOrderFormModal
          mode="create"
          equipmentId={equipmentId}
          onClose={() => setCreateOpen(false)}
          onSaved={invalidate}
        />
      )}
      {editing && (
        <WorkOrderFormModal
          mode="edit"
          equipmentId={equipmentId}
          existing={editing}
          onClose={() => setEditing(null)}
          onSaved={invalidate}
        />
      )}
      <ConfirmDialog
        open={confirmDeleteId !== null}
        title={t('equipment.workorder.delete_title', {
          defaultValue: 'Delete work order?',
        })}
        message={t('equipment.workorder.delete_message', {
          defaultValue:
            'This permanently deletes the work order and its parts log links.',
        })}
        variant="danger"
        onConfirm={() => confirmDeleteId && handleDelete(confirmDeleteId)}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}

function CertificationsTab({
  equipmentId,
  rows,
  loading,
}: {
  equipmentId: string;
  rows: ApiInspection[];
  loading: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ApiInspection | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ['equipment', 'inspections', equipmentId] });

  const handleDelete = async (id: string) => {
    try {
      await deleteInspection(id);
      addToast({
        type: 'success',
        title: t('equipment.inspection.deleted', {
          defaultValue: 'Inspection deleted',
        }),
      });
      invalidate();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setConfirmDeleteId(null);
    }
  };

  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="space-y-3">
      <SectionHeader
        title={t('equipment.inspection.section_title', {
          defaultValue: 'Inspections & certifications',
        })}
        tooltip={t('equipment.inspection.tooltip', {
          defaultValue:
            'Statutory inspections, lift certificates, annual safety checks. If the latest valid-until date has passed, the asset is automatically blocked from new project assignments.',
        })}
        addLabel={t('equipment.inspection.add', {
          defaultValue: 'Add inspection',
        })}
        onAdd={() => setCreateOpen(true)}
      />

      {loading && <SkeletonTable rows={3} columns={4} />}
      {!loading && rows.length === 0 && (
        <EmptyState
          icon={<ShieldCheck size={20} />}
          title={t('equipment.no_certifications', {
            defaultValue: 'No inspections recorded',
          })}
        />
      )}
      {!loading && rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border-light">
          <table className="w-full text-xs">
            <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
              <tr>
                <th className="px-3 py-2 text-left">
                  {t('equipment.inspection_type', { defaultValue: 'Type' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('equipment.inspected_at', { defaultValue: 'Inspected' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('equipment.valid_until', { defaultValue: 'Valid until' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('equipment.inspector', { defaultValue: 'Inspector' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('equipment.result', { defaultValue: 'Result' })}
                </th>
                <th className="px-3 py-2 w-[60px]" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const expired = r.valid_until < today;
                return (
                  <tr
                    key={r.id}
                    className="group border-t border-border-light hover:bg-surface-secondary"
                  >
                    <td className="px-3 py-2">{r.inspection_type}</td>
                    <td className="px-3 py-2 text-content-secondary">
                      <DateDisplay value={r.inspected_at} />
                    </td>
                    <td
                      className={clsx(
                        'px-3 py-2',
                        expired
                          ? 'text-status-error font-medium'
                          : 'text-content-secondary',
                      )}
                    >
                      <DateDisplay value={r.valid_until} />
                      {expired && (
                        <span className="ml-1 text-[10px] uppercase">
                          {t('equipment.expired', { defaultValue: 'expired' })}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-content-secondary">
                      {r.inspector_name || '—'}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={INSPECTION_VARIANT[r.result]} dot>
                        {r.result}
                      </Badge>
                    </td>
                    <td className="px-3 py-2">
                      <RowActions
                        onEdit={() => setEditing(r)}
                        onDelete={() => setConfirmDeleteId(r.id)}
                        editLabel={t('common.edit', { defaultValue: 'Edit' })}
                        deleteLabel={t('common.delete', {
                          defaultValue: 'Delete',
                        })}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {createOpen && (
        <InspectionFormModal
          mode="create"
          equipmentId={equipmentId}
          onClose={() => setCreateOpen(false)}
          onSaved={invalidate}
        />
      )}
      {editing && (
        <InspectionFormModal
          mode="edit"
          equipmentId={equipmentId}
          existing={editing}
          onClose={() => setEditing(null)}
          onSaved={invalidate}
        />
      )}
      <ConfirmDialog
        open={confirmDeleteId !== null}
        title={t('equipment.inspection.delete_title', {
          defaultValue: 'Delete inspection?',
        })}
        message={t('equipment.inspection.delete_message', {
          defaultValue:
            'This permanently removes the inspection record. The asset compliance status will recompute against the remaining inspections.',
        })}
        variant="danger"
        onConfirm={() => confirmDeleteId && handleDelete(confirmDeleteId)}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}

function DamageTab({
  equipmentId,
  rows,
  loading,
}: {
  equipmentId: string;
  rows: ApiDamage[];
  loading: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ApiDamage | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ['equipment', 'damage', equipmentId] });

  const handleDelete = async (id: string) => {
    try {
      await deleteDamageReport(id);
      addToast({
        type: 'success',
        title: t('equipment.damage.deleted', {
          defaultValue: 'Damage report deleted',
        }),
      });
      invalidate();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setConfirmDeleteId(null);
    }
  };

  return (
    <div className="space-y-3">
      <SectionHeader
        title={t('equipment.damage.section_title', {
          defaultValue: 'Damage & incident reports',
        })}
        tooltip={t('equipment.damage.tooltip', {
          defaultValue:
            'Damage records, severity and repair-cost estimates. Filing a new report automatically creates a linked maintenance work order so the repair is tracked.',
        })}
        addLabel={t('equipment.damage.add', { defaultValue: 'Report damage' })}
        onAdd={() => setCreateOpen(true)}
      />

      {loading && <SkeletonTable rows={3} columns={4} />}
      {!loading && rows.length === 0 && (
        <EmptyState
          icon={<AlertTriangle size={20} />}
          title={t('equipment.no_damage', { defaultValue: 'No damage reports' })}
        />
      )}
      {!loading &&
        rows.length > 0 &&
        rows.map((r) => (
          <Card key={r.id} padding="sm" className="group">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-xs text-content-tertiary">
                  <DateDisplay value={r.reported_at} />
                </p>
                <p className="mt-1 text-sm text-content-primary whitespace-pre-wrap">
                  {r.description || '—'}
                </p>
              </div>
              <div className="flex flex-col items-end gap-1">
                <Badge variant={DAMAGE_VARIANT[r.severity]} dot>
                  {r.severity}
                </Badge>
                <Badge variant="neutral">{r.status}</Badge>
              </div>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2">
              {r.repair_cost_estimate !== null &&
              r.repair_cost_estimate !== undefined ? (
                <p className="text-xs text-content-secondary">
                  {t('equipment.repair_estimate', {
                    defaultValue: 'Repair estimate',
                  })}
                  :{' '}
                  <MoneyDisplay
                    amount={toNum(r.repair_cost_estimate)}
                    currency={r.currency || undefined}
                  />
                </p>
              ) : (
                <span />
              )}
              <RowActions
                onEdit={() => setEditing(r)}
                onDelete={() => setConfirmDeleteId(r.id)}
                editLabel={t('common.edit', { defaultValue: 'Edit' })}
                deleteLabel={t('common.delete', { defaultValue: 'Delete' })}
              />
            </div>
          </Card>
        ))}

      {createOpen && (
        <DamageReportFormModal
          mode="create"
          equipmentId={equipmentId}
          onClose={() => setCreateOpen(false)}
          onSaved={invalidate}
        />
      )}
      {editing && (
        <DamageReportFormModal
          mode="edit"
          equipmentId={equipmentId}
          existing={editing}
          onClose={() => setEditing(null)}
          onSaved={invalidate}
        />
      )}
      <ConfirmDialog
        open={confirmDeleteId !== null}
        title={t('equipment.damage.delete_title', {
          defaultValue: 'Delete damage report?',
        })}
        message={t('equipment.damage.delete_message', {
          defaultValue:
            'This permanently removes the damage record. The auto-created maintenance work order is kept; delete it separately if needed.',
        })}
        variant="danger"
        onConfirm={() => confirmDeleteId && handleDelete(confirmDeleteId)}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}

function KV({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
        {label}
      </p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
    </div>
  );
}

/* ─── Types page — flat catalogue of EquipmentType ───────────────── */

function TypesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ApiEquipmentType | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const typesQ = useQuery({
    queryKey: ['equipment', 'types'],
    queryFn: () => listTypes(),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['equipment', 'types'] });

  const handleDelete = async (id: string) => {
    try {
      await deleteType(id);
      addToast({
        type: 'success',
        title: t('equipment.type.deleted', { defaultValue: 'Type deleted' }),
      });
      invalidate();
    } catch (err) {
      // 409 from server when the type is still referenced — show the
      // detail so the user knows which assets are blocking deletion.
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setConfirmDeleteId(null);
    }
  };

  const rows = typesQ.data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <h2 className="text-base font-semibold text-content-primary">
            {t('equipment.type.page_title', {
              defaultValue: 'Equipment types',
            })}
          </h2>
          <button
            type="button"
            className="inline-flex items-center justify-center rounded-full p-0.5 text-content-tertiary hover:text-oe-blue hover:bg-oe-blue/10"
            title={t('equipment.type.page_tooltip', {
              defaultValue:
                'Catalogue of equipment categories used to classify assets (excavator, crane, generator, …). Each asset references a type by code, so a type cannot be deleted while any asset still uses it.',
            })}
            aria-label={t('common.info', { defaultValue: 'Info' })}
          >
            <Info size={13} strokeWidth={2} />
          </button>
        </div>
        <Button
          variant="primary"
          icon={<Plus size={14} />}
          onClick={() => setCreateOpen(true)}
        >
          {t('equipment.type.add', { defaultValue: 'New type' })}
        </Button>
      </div>

      <Card padding="none">
        {typesQ.isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={6} columns={3} />
          </div>
        ) : typesQ.isError ? (
          <EmptyState
            icon={<AlertTriangle size={22} />}
            title={t('equipment.type.load_error', {
              defaultValue: 'Could not load equipment types',
            })}
            description={getErrorMessage(typesQ.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => {
                void typesQ.refetch();
              },
            }}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Tags size={22} />}
            title={t('equipment.type.empty', {
              defaultValue: 'No equipment types yet',
            })}
            description={t('equipment.type.empty_desc', {
              defaultValue:
                'Define the categories you use to classify assets (excavator, crane, generator, …). Types drive default service intervals and inspection cadence.',
            })}
            action={{
              label: t('equipment.type.add', { defaultValue: 'New type' }),
              onClick: () => setCreateOpen(true),
            }}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-2.5 text-left">
                    {t('equipment.type.code', { defaultValue: 'Code' })}
                  </th>
                  <th className="px-4 py-2.5 text-left">
                    {t('equipment.type.name', { defaultValue: 'Name' })}
                  </th>
                  <th className="px-4 py-2.5 text-left">
                    {t('equipment.type.category', { defaultValue: 'Category' })}
                  </th>
                  <th className="px-4 py-2.5 w-[80px]" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    className="group border-t border-border-light hover:bg-surface-secondary"
                  >
                    <td className="px-4 py-2 font-mono text-xs text-content-secondary">
                      {r.code}
                    </td>
                    <td className="px-4 py-2 text-content-primary">{r.name}</td>
                    <td className="px-4 py-2 text-content-secondary text-xs">
                      {r.category}
                    </td>
                    <td className="px-4 py-2">
                      <RowActions
                        onEdit={() => setEditing(r)}
                        onDelete={() => setConfirmDeleteId(r.id)}
                        editLabel={t('common.edit', { defaultValue: 'Edit' })}
                        deleteLabel={t('common.delete', {
                          defaultValue: 'Delete',
                        })}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {createOpen && (
        <TypeFormModal
          mode="create"
          onClose={() => setCreateOpen(false)}
          onSaved={invalidate}
        />
      )}
      {editing && (
        <TypeFormModal
          mode="edit"
          existing={editing}
          onClose={() => setEditing(null)}
          onSaved={invalidate}
        />
      )}
      <ConfirmDialog
        open={confirmDeleteId !== null}
        title={t('equipment.type.delete_title', {
          defaultValue: 'Delete equipment type?',
        })}
        message={t('equipment.type.delete_message', {
          defaultValue:
            'Delete this type? Equipment that references it must be reassigned first.',
        })}
        variant="danger"
        onConfirm={() => confirmDeleteId && handleDelete(confirmDeleteId)}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}

/* ─── Equipment form modal (create + edit) ────────────────────────────
 *
 * Single component used for both new-asset registration and editing an
 * existing record. Centralising create + edit in one form keeps the
 * field list, validation rules and UX in lock-step — when a senior
 * reviewer adds a new property (warranty_expiry, GPS provider, …)
 * they only touch one component.
 *
 * Mode semantics:
 *   • mode="create" — POST /api/v1/equipment/equipment/. ``existing`` MUST be omitted.
 *   • mode="edit"   — PATCH /api/v1/equipment/equipment/{id}. ``existing`` is required;
 *                     fields are pre-filled from it and only changed
 *                     fields end up in the PATCH body (avoids touching
 *                     server-managed columns like depreciation_method
 *                     when the user only edits the name).
 *
 * All numeric inputs accept blank strings to mean "no value"; converted
 * to ``number | undefined`` on submit so the backend's Decimal columns
 * receive nulls instead of zeros when the field is intentionally empty.
 */

interface EquipmentFormState {
  code: string;
  name: string;
  type_code: string;
  manufacturer: string;
  model: string;
  serial: string;
  ownership: Ownership;
  status: EquipmentStatus;
  year: string;                   // text input — empty = unset
  purchase_date: string;          // ISO yyyy-mm-dd, empty = unset
  purchase_value: string;
  currency: string;
  useful_life_years: string;
  residual_value: string;
  hour_meter: string;
  odometer_km: string;
  location_lat: string;
  location_lng: string;
  notes: string;
}

function _toFormState(eq: Equipment | undefined): EquipmentFormState {
  // Decimal/numeric columns come back as ``number | string`` from the
  // backend (depending on JSON serialiser). Normalise to string so the
  // <input> stays controlled and round-trips losslessly.
  const numStr = (v: number | string | null | undefined): string =>
    v === null || v === undefined || v === '' ? '' : String(v);
  return {
    code: eq?.code ?? '',
    name: eq?.name ?? '',
    type_code: eq?.type_code ?? 'other',
    manufacturer: eq?.manufacturer ?? '',
    model: eq?.model ?? '',
    serial: eq?.serial ?? '',
    ownership: (eq?.ownership ?? 'owned') as Ownership,
    status: (eq?.status ?? 'active') as EquipmentStatus,
    year: eq?.year ? String(eq.year) : '',
    purchase_date: eq?.purchase_date ?? '',
    purchase_value: numStr(eq?.purchase_value),
    currency: eq?.currency ?? '',
    useful_life_years: eq?.useful_life_years
      ? String(eq.useful_life_years)
      : '',
    residual_value: numStr(eq?.residual_value),
    hour_meter: numStr(eq?.hour_meter),
    odometer_km: numStr(eq?.odometer_km),
    location_lat: numStr(eq?.location_lat),
    location_lng: numStr(eq?.location_lng),
    notes: eq?.notes ?? '',
  };
}

function _toPayload(
  form: EquipmentFormState,
): CreateEquipmentPayload {
  // Empty-string → undefined so backend models leave server-managed
  // defaults (e.g. depreciation_method, decimal columns) alone.
  const toOptStr = (v: string): string | undefined =>
    v.trim() === '' ? undefined : v.trim();
  const toOptNum = (v: string): number | undefined => {
    if (v.trim() === '') return undefined;
    const n = Number(v.replace(',', '.'));
    return Number.isFinite(n) ? n : undefined;
  };
  return {
    code: form.code.trim(),
    name: form.name.trim(),
    type_code: form.type_code.trim() || 'other',
    manufacturer: toOptStr(form.manufacturer),
    model: toOptStr(form.model),
    serial: toOptStr(form.serial),
    year: toOptNum(form.year),
    ownership: form.ownership,
    status: form.status,
    location_lat: toOptNum(form.location_lat),
    location_lng: toOptNum(form.location_lng),
    hour_meter: toOptNum(form.hour_meter),
    odometer_km: toOptNum(form.odometer_km),
    purchase_date: toOptStr(form.purchase_date),
    purchase_value: toOptNum(form.purchase_value),
    // Required by depreciation_value_at — previously collected by the
    // form but silently dropped here, so depreciation never computed and
    // the lat/lng inputs were inert. Now round-tripped.
    useful_life_years: toOptNum(form.useful_life_years),
    residual_value: toOptNum(form.residual_value),
    currency: toOptStr(form.currency),
    notes: toOptStr(form.notes),
  };
}

interface EquipmentFormModalProps {
  mode: 'create' | 'edit';
  existing?: Equipment;
  onClose: () => void;
}

function EquipmentFormModal({
  mode,
  existing,
  onClose,
}: EquipmentFormModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<EquipmentFormState>(() =>
    _toFormState(existing),
  );

  // Close on Escape — symmetric with the rest of the modal stack so
  // keyboard users get a predictable dismissal.
  // No focus trap here (the existing CreateModal didn't have one
  // either) — handled separately when we add the design-system Modal.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () =>
      document.removeEventListener('keydown', handler, { capture: true });
  }, [busy, onClose]);

  const submit = async () => {
    if (!form.code.trim() || !form.name.trim()) {
      addToast({
        type: 'error',
        title: t('equipment.code_name_required', {
          defaultValue: 'Code and name are required',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      const payload = _toPayload(form);
      if (mode === 'edit' && existing) {
        // Diff against the original so server-managed columns aren't
        // touched when only the name was changed. This also keeps PATCH
        // requests small and audit logs readable.
        const originalPayload = _toPayload(_toFormState(existing));
        const diff: Partial<CreateEquipmentPayload> = {};
        // Index through ``unknown`` first to satisfy strict-mode TS —
        // CreateEquipmentPayload doesn't carry an index signature, so
        // we explicitly opt into property-bag semantics for the diff.
        const originalRecord = originalPayload as unknown as Record<
          string,
          unknown
        >;
        const newRecord = payload as unknown as Record<string, unknown>;
        const diffRecord = diff as unknown as Record<string, unknown>;
        (Object.keys(payload) as (keyof CreateEquipmentPayload)[]).forEach(
          (k) => {
            if (originalRecord[k] !== newRecord[k]) {
              diffRecord[k] = newRecord[k];
            }
          },
        );
        if (Object.keys(diff).length === 0) {
          // Nothing changed — close without surprising the user with a
          // toast that says "updated" when nothing actually changed.
          onClose();
          return;
        }
        await updateEquipment(existing.id, diff);
        addToast({
          type: 'success',
          title: t('equipment.updated', {
            defaultValue: '{{name}} updated',
            name: form.name.trim(),
          }),
        });
      } else {
        await createEquipment(payload);
        addToast({
          type: 'success',
          title: t('equipment.created', { defaultValue: 'Equipment created' }),
        });
      }
      // Invalidate the whole equipment query family so every dashboard
      // (list view + detail drawer + fleet kpis) re-fetches.
      qc.invalidateQueries({ queryKey: ['equipment'] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const set = <K extends keyof EquipmentFormState>(
    key: K,
    value: EquipmentFormState[K],
  ): void => setForm((prev) => ({ ...prev, [key]: value }));

  const isEdit = mode === 'edit';

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-3"
      onClick={() => !busy && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="equipment-form-title"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
      <div
        className="relative w-full max-w-2xl max-h-[92vh] overflow-y-auto rounded-xl bg-surface-elevated p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2
            id="equipment-form-title"
            className="text-lg font-semibold text-content-primary"
          >
            {isEdit
              ? t('equipment.edit_title', {
                  defaultValue: 'Edit equipment',
                })
              : t('equipment.new', { defaultValue: 'New Asset' })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded p-1 hover:bg-surface-secondary disabled:opacity-50"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4">
          {/* ── Section: Identity ─────────────────────────────────── */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('equipment.section_identity', {
                defaultValue: 'Identity',
              })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>
                  {t('equipment.col_code', { defaultValue: 'Code' })}{' '}
                  <span className="text-rose-500">*</span>
                </label>
                <input
                  value={form.code}
                  onChange={(e) => set('code', e.target.value)}
                  className={inputCls}
                  placeholder="EXC-001"
                  // Code is the human-readable handle for the asset and
                  // is also used in URLs / barcodes — disallow editing
                  // on existing records to keep cross-references stable.
                  disabled={isEdit}
                  title={
                    isEdit
                      ? t('equipment.code_immutable_hint', {
                          defaultValue:
                            'Asset code is immutable after creation to keep barcodes / external references stable.',
                        })
                      : undefined
                  }
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.col_type', { defaultValue: 'Type code' })}
                </label>
                <input
                  value={form.type_code}
                  onChange={(e) => set('type_code', e.target.value)}
                  className={inputCls}
                  placeholder="excavator, crane, generator…"
                />
              </div>
              <div className="sm:col-span-2">
                <label className={labelCls}>
                  {t('equipment.col_name', { defaultValue: 'Name' })}{' '}
                  <span className="text-rose-500">*</span>
                </label>
                <input
                  value={form.name}
                  onChange={(e) => set('name', e.target.value)}
                  className={inputCls}
                  placeholder={t('equipment.name_placeholder', {
                    defaultValue: 'CAT 320 Excavator – Site A',
                  })}
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.manufacturer', { defaultValue: 'Manufacturer' })}
                </label>
                <input
                  value={form.manufacturer}
                  onChange={(e) => set('manufacturer', e.target.value)}
                  className={inputCls}
                  placeholder="Caterpillar"
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.model', { defaultValue: 'Model' })}
                </label>
                <input
                  value={form.model}
                  onChange={(e) => set('model', e.target.value)}
                  className={inputCls}
                  placeholder="320 GC"
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.serial', { defaultValue: 'Serial number' })}
                </label>
                <input
                  value={form.serial}
                  onChange={(e) => set('serial', e.target.value)}
                  className={inputCls}
                  placeholder="VIN / serial / asset number"
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.year', { defaultValue: 'Year of manufacture' })}
                </label>
                <input
                  type="number"
                  inputMode="numeric"
                  min={1900}
                  max={new Date().getFullYear() + 1}
                  value={form.year}
                  onChange={(e) => set('year', e.target.value)}
                  className={inputCls}
                  placeholder="2022"
                />
              </div>
            </div>
          </section>

          {/* ── Section: Lifecycle ──────────────────────────────── */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('equipment.section_lifecycle', {
                defaultValue: 'Lifecycle & status',
              })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>
                  {t('equipment.ownership', { defaultValue: 'Ownership' })}
                </label>
                <select
                  value={form.ownership}
                  onChange={(e) =>
                    set('ownership', e.target.value as Ownership)
                  }
                  className={inputCls}
                >
                  {(['owned', 'rented', 'leased'] as Ownership[]).map((o) => (
                    <option key={o} value={o}>
                      {t(`equipment.ownership_${o}`, {
                        defaultValue: o,
                      })}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.col_status', { defaultValue: 'Status' })}
                </label>
                <select
                  value={form.status}
                  onChange={(e) =>
                    set('status', e.target.value as EquipmentStatus)
                  }
                  className={inputCls}
                >
                  {(
                    [
                      'active',
                      'under_maintenance',
                      'decommissioned',
                      'reserved',
                    ] as EquipmentStatus[]
                  ).map((s) => (
                    <option key={s} value={s}>
                      {t(`equipment.status_${s}`, {
                        defaultValue: s,
                      })}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.purchase_date', {
                    defaultValue: 'Purchase / start date',
                  })}
                </label>
                <input
                  type="date"
                  value={form.purchase_date}
                  onChange={(e) => set('purchase_date', e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.useful_life_years', {
                    defaultValue: 'Useful life (years)',
                  })}
                </label>
                <input
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={100}
                  value={form.useful_life_years}
                  onChange={(e) => set('useful_life_years', e.target.value)}
                  className={inputCls}
                  placeholder="10"
                />
              </div>
            </div>
          </section>

          {/* ── Section: Financial ─────────────────────────────── */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('equipment.section_financial', {
                defaultValue: 'Financial',
              })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className={labelCls}>
                  {t('equipment.purchase_value', {
                    defaultValue: 'Purchase value',
                  })}
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.purchase_value}
                  onChange={(e) => set('purchase_value', e.target.value)}
                  className={inputCls}
                  placeholder="125000"
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.residual_value', {
                    defaultValue: 'Residual value',
                  })}
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.residual_value}
                  onChange={(e) => set('residual_value', e.target.value)}
                  className={inputCls}
                  placeholder="15000"
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.currency', { defaultValue: 'Currency' })}
                </label>
                <input
                  value={form.currency}
                  onChange={(e) => set('currency', e.target.value.toUpperCase().slice(0, 3))}
                  className={inputCls}
                  placeholder="EUR"
                  maxLength={3}
                />
              </div>
            </div>
          </section>

          {/* ── Section: Telemetry & location ───────────────── */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('equipment.section_telemetry', {
                defaultValue: 'Telemetry & location',
              })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>
                  {t('equipment.hour_meter', { defaultValue: 'Hour meter' })}
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.hour_meter}
                  onChange={(e) => set('hour_meter', e.target.value)}
                  className={inputCls}
                  placeholder="1234"
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.odometer_km', { defaultValue: 'Odometer (km)' })}
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.odometer_km}
                  onChange={(e) => set('odometer_km', e.target.value)}
                  className={inputCls}
                  placeholder="42000"
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.location_lat', {
                    defaultValue: 'Location latitude',
                  })}
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.location_lat}
                  onChange={(e) => set('location_lat', e.target.value)}
                  className={inputCls}
                  placeholder="52.5200"
                />
              </div>
              <div>
                <label className={labelCls}>
                  {t('equipment.location_lng', {
                    defaultValue: 'Location longitude',
                  })}
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.location_lng}
                  onChange={(e) => set('location_lng', e.target.value)}
                  className={inputCls}
                  placeholder="13.4050"
                />
              </div>
            </div>
          </section>

          {/* ── Section: Notes ───────────────────────────────── */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('equipment.section_notes', { defaultValue: 'Notes' })}
            </h3>
            <textarea
              value={form.notes}
              onChange={(e) => set('notes', e.target.value)}
              className={clsx(inputCls, 'min-h-[80px] py-2 leading-snug')}
              placeholder={t('equipment.notes_placeholder', {
                defaultValue:
                  'Operator notes, warranty contact, attachments, certificate IDs…',
              })}
              maxLength={2000}
              rows={3}
            />
          </section>
        </div>

        <div className="flex justify-end gap-2 mt-5 sticky bottom-0 pt-3 -mx-5 -mb-5 px-5 pb-3 bg-surface-elevated border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={
              busy ? (
                <Loader2 size={14} />
              ) : isEdit ? (
                <Save size={14} />
              ) : (
                <Plus size={14} />
              )
            }
          >
            {isEdit
              ? t('common.save', { defaultValue: 'Save changes' })
              : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
