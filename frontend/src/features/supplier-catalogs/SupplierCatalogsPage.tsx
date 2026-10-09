// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState, useMemo, Fragment, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  ShoppingCart,
  Boxes,
  ClipboardList,
  FileCheck,
  Warehouse as WarehouseIcon,
  Search,
  Plus,
  Loader2,
  Star,
  AlertOctagon,
  Truck,
  ArrowUpRight,
  Network,
  ArrowRight,
  Coins,
  Pencil,
  Trash2,
  PauseCircle,
  Ban,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  DismissibleInfo,
  ModuleGuideButton,
  CollapsibleSection,
  ConfirmDialog,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  listVendors,
  listCatalogItems,
  listWarehouses,
  listWarehouseBalances,
  comparePrices,
  createVendor,
  createCatalogItem,
  createWarehouse,
  updateVendor,
  updateCatalogItem,
  updateWarehouse,
  deleteVendor,
  deleteCatalogItem,
  deleteWarehouse,
  suspendVendor,
  blacklistVendor,
  rateVendor,
  type Vendor,
  type CatalogItem,
  type Warehouse,
  type StockBalance,
  type PriceComparisonRow,
  type VendorStatus,
} from './api';
import { supplierCatalogsGuide } from './supplierCatalogsGuide';

// CONN-46: the old prs / pos / match tabs were three dead tabs that each
// only rendered a hand-off banner (this module has no list endpoints for
// those records and they never surface in /procurement). They are demoted to
// a single 'procurement' tab carrying one consolidated banner.
type Tab = 'vendors' | 'catalog' | 'procurement' | 'warehouses';

const VENDOR_VARIANT: Record<VendorStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  active: 'success',
  suspended: 'warning',
  blacklisted: 'error',
  pending: 'neutral',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── How it works + module connections ─────────────────────────────────── */

/** Compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer of what the supplier library does and how it feeds
 * the buying and estimating workflow. Every connected module is a link so
 * the next step is one click away.
 */
function HowSupplierCatalogsWork() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Truck size={14} className="text-oe-blue" />,
      title: t('supplier_catalogs.flow_1_title', { defaultValue: 'Register vendors' }),
      desc: t('supplier_catalogs.flow_1_desc', {
        defaultValue: 'Suppliers with payment terms, currency and category coverage.',
      }),
    },
    {
      icon: <Boxes size={14} className="text-oe-blue" />,
      title: t('supplier_catalogs.flow_2_title', { defaultValue: 'Build the catalog' }),
      desc: t('supplier_catalogs.flow_2_desc', {
        defaultValue: 'The SKUs you order, tied to vendors for price comparison.',
      }),
    },
    {
      icon: <Coins size={14} className="text-oe-blue" />,
      title: t('supplier_catalogs.flow_3_title', { defaultValue: 'Compare prices' }),
      desc: t('supplier_catalogs.flow_3_desc', {
        defaultValue: 'Rank vendor prices per item and start a purchase order from the best.',
      }),
    },
    {
      icon: <WarehouseIcon size={14} className="text-oe-blue" />,
      title: t('supplier_catalogs.flow_4_title', { defaultValue: 'Track stock' }),
      desc: t('supplier_catalogs.flow_4_desc', {
        defaultValue: 'Warehouse balances, reservations and average cost on hand.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="supplier_catalogs.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('supplier_catalogs.flow_title', {
        defaultValue: 'How the supplier library fits together',
      })}
    >
      <p className="text-xs text-content-tertiary">
        {t('supplier_catalogs.flow_intro', {
          defaultValue:
            'Build up your supply base step by step - vendors, then the items they sell, then the stock you hold - and hand off to Procurement when it is time to buy.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('supplier_catalogs.flow_connects', { defaultValue: 'Connects with:' })}
          </span>{' '}
          <ModLink to="/procurement">
            {t('nav.procurement', { defaultValue: 'Procurement' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/cost-explorer">
            {t('nav.cost_explorer', { defaultValue: 'Cost Explorer' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/boq">{t('nav.boq', { defaultValue: 'BOQ' })}</ModLink> ·{' '}
          <ModLink to="/subcontractors">
            {t('nav.subcontractors', { defaultValue: 'Subcontractors' })}
          </ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

interface SupplierCatalogsPageProps {
  /**
   * Render one tab inside another page (Procurement shows Vendors and Catalog
   * this way). The page's own header, guide and tab bar are left out; the
   * standalone /supplier-catalogs page keeps all four tabs.
   */
  embeddedTab?: 'vendors' | 'catalog';
}

export function SupplierCatalogsPage({ embeddedTab }: SupplierCatalogsPageProps = {}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>(embeddedTab ?? 'vendors');
  useEffect(() => {
    if (embeddedTab) setTab(embeddedTab);
  }, [embeddedTab]);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [priceItem, setPriceItem] = useState<CatalogItem | null>(null);
  const [selectedWarehouseId, setSelectedWarehouseId] = useState<string>('');
  const [editVendor, setEditVendor] = useState<Vendor | null>(null);
  const [editItem, setEditItem] = useState<CatalogItem | null>(null);
  const [editWarehouse, setEditWarehouse] = useState<Warehouse | null>(null);
  const [statusTarget, setStatusTarget] = useState<VendorStatusTarget | null>(null);
  const [ratingVendor, setRatingVendor] = useState<Vendor | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const vendorsQ = useQuery({
    queryKey: ['sc', 'vendors', statusFilter],
    queryFn: () => listVendors({ status: statusFilter || undefined, limit: 200 }),
    enabled: tab === 'vendors' || tab === 'catalog',
  });
  const itemsQ = useQuery({
    queryKey: ['sc', 'items', search],
    queryFn: () => listCatalogItems({ search: search || undefined, limit: 200 }),
    enabled: tab === 'catalog',
  });
  const warehousesQ = useQuery({
    queryKey: ['sc', 'warehouses'],
    queryFn: () => listWarehouses(),
    enabled: tab === 'warehouses',
  });
  // Lookup of catalog items used by the warehouse stock table to resolve a
  // stock row's catalog_item_id to a human SKU + name (the raw id is a UUID).
  const itemLookupQ = useQuery({
    queryKey: ['sc', 'items', 'lookup'],
    // Backend caps limit at 200; items not in the page slice fall back to a
    // clear "Unknown item" label rather than the banned UUID slice.
    queryFn: () => listCatalogItems({ limit: 200 }),
    enabled: tab === 'warehouses',
    staleTime: 60_000,
  });
  const itemLookup = useMemo(() => {
    const map = new Map<string, CatalogItem>();
    if (Array.isArray(itemLookupQ.data?.items)) {
      for (const it of itemLookupQ.data.items) map.set(it.id, it);
    }
    return map;
  }, [itemLookupQ.data]);
  // The select visually defaults to the first warehouse, so balances must
  // fetch for it even before the user explicitly picks one (otherwise the
  // first warehouse looks selected but its stock never loads).
  const effectiveWarehouseId =
    selectedWarehouseId ||
    (Array.isArray(warehousesQ.data) ? (warehousesQ.data[0]?.id ?? '') : '');
  const balancesQ = useQuery({
    queryKey: ['sc', 'balances', effectiveWarehouseId],
    queryFn: () => listWarehouseBalances(effectiveWarehouseId),
    enabled: tab === 'warehouses' && !!effectiveWarehouseId,
  });

  // PRs / POs / 3-way-match: the supplier_catalogs backend exposes only
  // create/lifecycle actions for these and NO list endpoints, and the records
  // it stores never surface in /procurement either. Rather than create into a
  // void, those tabs are honest read-only summaries that hand off to the
  // /procurement module, which owns the live purchasing workflow.
  // Defensive coerce — the offline-cache layer can occasionally hydrate
  // the query with a non-array value (e.g. a stale FastAPI error envelope
  // from a previous session), which would crash ``.filter()`` below. The two
  // paged registers carry an envelope, so the guard is on `items` rather than
  // on the body: a body that is not the envelope leaves `items` undefined and
  // falls through to the same empty array.
  const vendorsArr = Array.isArray(vendorsQ.data?.items) ? vendorsQ.data.items : [];
  const itemsArr = Array.isArray(itemsQ.data?.items) ? itemsQ.data.items : [];
  const warehousesArr = Array.isArray(warehousesQ.data) ? warehousesQ.data : [];
  const balancesArr = Array.isArray(balancesQ.data) ? balancesQ.data : [];
  const filteredVendors = useMemo(
    () => filterByText(vendorsArr, search, (v) => `${v.code} ${v.name} ${v.country_code ?? ''}`),
    [vendorsArr, search],
  );
  const filteredItems = itemsArr;

  const isLoading =
    (tab === 'vendors' && vendorsQ.isLoading) ||
    (tab === 'catalog' && itemsQ.isLoading) ||
    (tab === 'warehouses' && (warehousesQ.isLoading || balancesQ.isLoading));

  // Surface fetch failures explicitly — a failed query must NOT render as
  // an empty success ("No vendors yet"), which silently hides outages.
  const activeError =
    tab === 'vendors'
      ? vendorsQ.error
      : tab === 'catalog'
        ? itemsQ.error
        : tab === 'warehouses'
          ? (warehousesQ.error ?? balancesQ.error)
          : null;
  const refetchActive = () => {
    if (tab === 'vendors') void vendorsQ.refetch();
    else if (tab === 'catalog') void itemsQ.refetch();
    else if (tab === 'warehouses') {
      void warehousesQ.refetch();
      if (effectiveWarehouseId) void balancesQ.refetch();
    }
  };

  // Vendors / catalog items / warehouses are real reference records owned by
  // this module, so they keep a create action. PR / PO / match are read-only
  // summaries here (the records belong to /procurement), so no create button.
  const canCreateHere = tab === 'vendors' || tab === 'catalog' || tab === 'warehouses';

  /* Deletion is the only action here that cannot be taken back, so it is the
     only one that asks first - through the shared ConfirmDialog, never a
     native prompt, because a browser dialog is unstyled, untranslated and
     cannot say what the record is.

     The backend refuses to delete a record other records point at and answers
     with a sentence naming what holds it and what to do instead. That
     sentence is what the toast carries: `getErrorMessage` reads the
     structured 409 body, so replacing it with a generic "could not delete"
     would throw away the only part a buyer can act on. */
  const deleteMutation = useMutation({
    mutationFn: (target: DeleteTarget) =>
      target.kind === 'vendors'
        ? deleteVendor(target.id)
        : target.kind === 'catalog'
          ? deleteCatalogItem(target.id)
          : deleteWarehouse(target.id),
    onSuccess: (_result, target) => {
      addToast({ type: 'success', title: deletedLabel(target.kind, t) });
      if (target.kind === 'vendors') {
        qc.invalidateQueries({ queryKey: ['sc', 'vendors'] });
      } else if (target.kind === 'catalog') {
        // The warehouse tab resolves stock rows to a SKU through the same
        // ['sc','items'] prefix, so both readers refresh from one call.
        qc.invalidateQueries({ queryKey: ['sc', 'items'] });
        qc.invalidateQueries({ queryKey: ['sc', 'balances'] });
      } else {
        qc.invalidateQueries({ queryKey: ['sc', 'warehouses'] });
        qc.invalidateQueries({ queryKey: ['sc', 'balances'] });
        // The picker holds the id of a warehouse that no longer exists; left
        // set, the balances query would keep asking the server for it.
        setSelectedWarehouseId('');
      }
      setDeleteTarget(null);
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
      setDeleteTarget(null);
    },
  });

  return (
    <div className="space-y-5 animate-fade-in">
      {embeddedTab ? (
        canCreateHere && (
          <div className="flex justify-end">
            <Button variant="primary" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>
              {createLabel(tab, t)}
            </Button>
          </div>
        )
      ) : (
      <>
      <Breadcrumb items={[{ label: t('nav.supplier_catalogs', { defaultValue: 'Supplier Catalogs' }) }]} />

      {/* Header — the module name + icon live in the global top bar; the
          page renders only its subtitle on one shared midline with actions. */}
      <PageHeader
        srTitle={t('nav.supplier_catalogs', { defaultValue: 'Supplier Catalogs' })}
        subtitle={t('supplier_catalogs.subtitle', {
          defaultValue:
            'The vendor and item reference library: suppliers, priced catalogs, price comparison and warehouse stock.',
        })}
        actions={
          <>
            <ModuleGuideButton content={supplierCatalogsGuide} />
            {canCreateHere && (
              <Button variant="primary" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>
                {createLabel(tab, t)}
              </Button>
            )}
          </>
        }
      />

      <DismissibleInfo
        storageKey="supplier-catalogs"
        title={t('supplier_catalogs.info_title', {
          defaultValue: 'Vendor & catalog reference library',
        })}
        links={[
          {
            label: t('supplier_catalogs.open_procurement_pill', {
              defaultValue: 'Open Procurement',
            }),
            onClick: () => navigate('/procurement'),
          },
          {
            label: t('supplier_catalogs.open_costs_pill', {
              defaultValue: 'Cost Database',
            }),
            onClick: () => navigate('/costs'),
          },
        ]}
      >
        {t('supplier_catalogs.info_body', {
          defaultValue:
            'This page is your reference library of vendors, priced catalog items and warehouse stock. Live purchasing - raising requisitions, issuing purchase orders and three-way matching invoices - happens in the Procurement module.',
        })}
      </DismissibleInfo>

      <HowSupplierCatalogsWork />

      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px overflow-x-auto">
          {tabsDef(t).map((it) => {
            const Icon = it.icon;
            return (
              <button
                key={it.id}
                type="button"
                onClick={() => {
                  setTab(it.id);
                  setStatusFilter('');
                  setSearch('');
                }}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap',
                  tab === it.id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {it.label}
              </button>
            );
          })}
        </nav>
      </div>
      </>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
          <input
            type="text"
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={clsx(inputCls, 'pl-8')}
          />
        </div>
        {tab === 'vendors' && (
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className={clsx(inputCls, 'max-w-[180px]')}
          >
            <option value="">{t('common.all_statuses', { defaultValue: 'All statuses' })}</option>
            {(['active', 'suspended', 'blacklisted', 'pending'] as VendorStatus[]).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
        {tab === 'warehouses' && warehousesArr.length > 0 && (
          <select
            value={effectiveWarehouseId}
            onChange={(e) => setSelectedWarehouseId(e.target.value)}
            className={clsx(inputCls, 'max-w-[280px]')}
          >
            {warehousesArr.map((w) => (
              <option key={w.id} value={w.id}>
                {w.code} — {w.name}
              </option>
            ))}
          </select>
        )}
      </div>

      <Card padding="none">
        {activeError ? (
          <EmptyState
            icon={<AlertOctagon size={22} />}
            title={t('supplier_catalogs.load_failed', {
              defaultValue: 'Could not load data',
            })}
            description={getErrorMessage(activeError)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: refetchActive,
            }}
          />
        ) : isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} columns={5} />
          </div>
        ) : tab === 'vendors' ? (
          <VendorTable
            rows={filteredVendors}
            onAction={() => setCreateOpen(true)}
            onEdit={(v) => setEditVendor(v)}
            onRate={(v) => setRatingVendor(v)}
            onStatus={(vendor, action) => setStatusTarget({ vendor, action })}
            onDelete={(v) => setDeleteTarget({ kind: 'vendors', id: v.id, label: `${v.code} - ${v.name}` })}
          />
        ) : tab === 'catalog' ? (
          <CatalogTable
            rows={filteredItems}
            onSelectPrice={(it) => setPriceItem(it)}
            onAction={() => setCreateOpen(true)}
            onEdit={(it) => setEditItem(it)}
            onDelete={(it) => setDeleteTarget({ kind: 'catalog', id: it.id, label: `${it.sku} - ${it.name}` })}
          />
        ) : tab === 'procurement' ? (
          <ProcurementHandoffPanel />
        ) : (
          <WarehousePanel
            warehouses={warehousesArr}
            selectedId={effectiveWarehouseId}
            balances={balancesArr}
            itemLookup={itemLookup}
            onAction={() => setCreateOpen(true)}
            onEdit={(w) => setEditWarehouse(w)}
            onDelete={(w) => setDeleteTarget({ kind: 'warehouses', id: w.id, label: `${w.code} - ${w.name}` })}
          />
        )}
      </Card>
      {/* Both registers ask for exactly the route's ceiling of 200, so a full
          page is the one case that means "there is more" rather than "that is
          all". The search box narrows what arrived, not the catalog. */}
      {tab === 'vendors' && vendorsQ.data && (
        <TruncationNotice page={vendorsQ.data} className="mt-2" />
      )}
      {tab === 'catalog' && itemsQ.data && (
        <TruncationNotice page={itemsQ.data} className="mt-2" />
      )}

      {createOpen && canCreateHere && (
        <CreateModal kind={tab} onClose={() => setCreateOpen(false)} />
      )}
      {priceItem && (
        <PriceComparisonModal
          item={priceItem}
          vendors={vendorsQ.data?.items ?? []}
          onClose={() => setPriceItem(null)}
        />
      )}
      {editVendor && <EditVendorModal vendor={editVendor} onClose={() => setEditVendor(null)} />}
      {editItem && <EditItemModal item={editItem} onClose={() => setEditItem(null)} />}
      {editWarehouse && (
        <EditWarehouseModal warehouse={editWarehouse} onClose={() => setEditWarehouse(null)} />
      )}
      {statusTarget && (
        <VendorStatusModal
          vendor={statusTarget.vendor}
          action={statusTarget.action}
          onClose={() => setStatusTarget(null)}
        />
      )}
      {ratingVendor && (
        <VendorRatingModal vendor={ratingVendor} onClose={() => setRatingVendor(null)} />
      )}
      {deleteTarget && (
        <ConfirmDialog
          open
          title={deleteTitle(deleteTarget.kind, t)}
          message={deleteMessage(deleteTarget, t)}
          confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
          cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
          loading={deleteMutation.isPending}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
        />
      )}
    </div>
  );
}

function tabsDef(t: (k: string, opts?: Record<string, unknown>) => string) {
  return [
    { id: 'vendors' as const, label: t('supplier_catalogs.tab_vendors', { defaultValue: 'Vendors' }), icon: Truck },
    { id: 'catalog' as const, label: t('supplier_catalogs.tab_catalog', { defaultValue: 'Catalog' }), icon: Boxes },
    // CONN-46: one Procurement tab replaces the three dead PR / PO / Match
    // tabs. It is a hand-off banner into the /procurement module, which owns
    // the live requisition, purchase order and three-way-match workflows.
    { id: 'procurement' as const, label: t('supplier_catalogs.tab_procurement', { defaultValue: 'Procurement' }), icon: ShoppingCart },
    { id: 'warehouses' as const, label: t('supplier_catalogs.tab_warehouses', { defaultValue: 'Warehouses' }), icon: WarehouseIcon },
  ];
}

function createLabel(tab: Tab, t: (k: string, opts?: Record<string, unknown>) => string): string {
  switch (tab) {
    case 'vendors':
      return t('supplier_catalogs.new_vendor', { defaultValue: 'New Vendor' });
    case 'catalog':
      return t('supplier_catalogs.new_item', { defaultValue: 'New Item' });
    case 'warehouses':
      return t('supplier_catalogs.new_warehouse', { defaultValue: 'New Warehouse' });
    // CONN-46: the procurement tab is a hand-off banner with no create flow
    // here (records belong to /procurement), so it never reaches a button.
    case 'procurement':
      return '';
  }
}

/** What the confirm dialog is about to delete, and how to name it on screen. */
type DeleteTarget = { kind: CreateTab; id: string; label: string };

/** Which of the vendor's two closing actions a modal is collecting a reason for. */
type VendorStatusTarget = { vendor: Vendor; action: 'suspend' | 'blacklist' };

function deletedLabel(kind: CreateTab, t: (k: string, opts?: Record<string, unknown>) => string): string {
  switch (kind) {
    case 'vendors':
      return t('supplier_catalogs.vendor_deleted', { defaultValue: 'Vendor deleted' });
    case 'catalog':
      return t('supplier_catalogs.item_deleted', { defaultValue: 'Item deleted' });
    case 'warehouses':
      return t('supplier_catalogs.warehouse_deleted', { defaultValue: 'Warehouse deleted' });
  }
}

function deleteTitle(kind: CreateTab, t: (k: string, opts?: Record<string, unknown>) => string): string {
  switch (kind) {
    case 'vendors':
      return t('supplier_catalogs.delete_vendor_title', { defaultValue: 'Delete this vendor?' });
    case 'catalog':
      return t('supplier_catalogs.delete_item_title', { defaultValue: 'Delete this item?' });
    case 'warehouses':
      return t('supplier_catalogs.delete_warehouse_title', { defaultValue: 'Delete this warehouse?' });
  }
}

/**
 * What the dialog says before the request goes out.
 *
 * It names the record and states the rule the server will apply, so the
 * refusal that may follow is not a surprise. The record's own name is an
 * interpolation value rather than part of the sentence: a translator has to
 * be able to put it where their language puts it.
 */
function deleteMessage(
  target: DeleteTarget,
  t: (k: string, opts?: Record<string, unknown>) => string,
): string {
  switch (target.kind) {
    case 'vendors':
      return t('supplier_catalogs.delete_vendor_body', {
        name: target.label,
        defaultValue:
          '{{name}} will be removed for good. A vendor with price lists, orders, invoices or compliance documents against it is kept instead, and the refusal will say what holds it - suspend or blacklist that vendor rather than deleting it.',
      });
    case 'catalog':
      return t('supplier_catalogs.delete_item_body', {
        name: target.label,
        defaultValue:
          '{{name}} will be removed for good. An item quoted on a requisition line, an order line or a vendor price list, or one that still has stock on hand, is kept instead and the refusal will say what holds it.',
      });
    case 'warehouses':
      return t('supplier_catalogs.delete_warehouse_body', {
        name: target.label,
        defaultValue:
          '{{name}} will be removed for good. A location that still holds stock, or that goods were received into, is kept instead and the refusal will say what holds it.',
      });
  }
}

function filterByText<T>(rows: T[], search: string, getter: (r: T) => string): T[] {
  if (!search.trim()) return rows;
  const q = search.toLowerCase();
  return rows.filter((r) => getter(r).toLowerCase().includes(q));
}

/* ── Stars ─────────────────────────────────────────────────────────────── */

function StarRating({ rating }: { rating: number | null }) {
  const value = rating ?? 0;
  return (
    <div className="inline-flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          size={12}
          className={
            i <= value
              ? 'fill-[#f59e0b] text-[#f59e0b]'
              : 'fill-transparent text-content-quaternary'
          }
        />
      ))}
      <span className="ml-1 text-2xs text-content-tertiary tabular-nums">{value}/5</span>
    </div>
  );
}

/* ── Tables ────────────────────────────────────────────────────────────── */

function VendorTable({
  rows,
  onAction,
  onEdit,
  onRate,
  onStatus,
  onDelete,
}: {
  rows: Vendor[];
  onAction: () => void;
  onEdit: (vendor: Vendor) => void;
  onRate: (vendor: Vendor) => void;
  onStatus: (vendor: Vendor, action: 'suspend' | 'blacklist') => void;
  onDelete: (vendor: Vendor) => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Truck size={22} />}
        title={t('supplier_catalogs.empty_vendors', { defaultValue: 'No vendors yet' })}
        description={t('supplier_catalogs.empty_vendors_desc', {
          defaultValue: 'Register suppliers with payment terms and category coverage to buy from.',
        })}
        action={{ label: t('supplier_catalogs.new_vendor', { defaultValue: 'New Vendor' }), onClick: onAction }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.code', { defaultValue: 'Code' })}</th>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.name', { defaultValue: 'Name' })}</th>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.country', { defaultValue: 'Country' })}</th>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.rating', { defaultValue: 'Rating' })}</th>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.payment_terms', { defaultValue: 'Terms' })}</th>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2.5 text-right">{t('supplier_catalogs.actions', { defaultValue: 'Actions' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-border-light hover:bg-surface-secondary">
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.code}</td>
              <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[320px]">{r.name}</td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.country_code || '—'}</td>
              <td className="px-4 py-2">
                <StarRating rating={r.rating} />
              </td>
              <td className="px-4 py-2 text-content-secondary text-xs tabular-nums">
                {r.payment_terms_days}d · {r.currency}
              </td>
              <td className="px-4 py-2">
                <Badge variant={VENDOR_VARIANT[r.status] || 'neutral'} dot>
                  {r.status}
                </Badge>
              </td>
              {/* Suspend and blacklist are shown only where the backend's own
                  transition table allows them: blacklist is terminal, and a
                  button that can only ever return an error is worse than no
                  button. Reactivation is deliberately absent - the service has
                  the operation but no route exposes it, so there is nothing to
                  call yet. */}
              <td className="px-4 py-2">
                <div className="flex items-center justify-end gap-1 whitespace-nowrap">
                  <Button variant="ghost" size="sm" icon={<Pencil size={13} />} onClick={() => onEdit(r)}>
                    {t('common.edit', { defaultValue: 'Edit' })}
                  </Button>
                  <Button variant="ghost" size="sm" icon={<Star size={13} />} onClick={() => onRate(r)}>
                    {t('supplier_catalogs.rate', { defaultValue: 'Rate' })}
                  </Button>
                  {r.status === 'active' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<PauseCircle size={13} />}
                      onClick={() => onStatus(r, 'suspend')}
                    >
                      {t('supplier_catalogs.suspend', { defaultValue: 'Suspend' })}
                    </Button>
                  )}
                  {(r.status === 'active' || r.status === 'suspended') && (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Ban size={13} />}
                      onClick={() => onStatus(r, 'blacklist')}
                    >
                      {t('supplier_catalogs.blacklist', { defaultValue: 'Blacklist' })}
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" icon={<Trash2 size={13} />} onClick={() => onDelete(r)}>
                    {t('common.delete', { defaultValue: 'Delete' })}
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CatalogTable({
  rows,
  onSelectPrice,
  onAction,
  onEdit,
  onDelete,
}: {
  rows: CatalogItem[];
  onSelectPrice: (item: CatalogItem) => void;
  onAction: () => void;
  onEdit: (item: CatalogItem) => void;
  onDelete: (item: CatalogItem) => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Boxes size={22} />}
        title={t('supplier_catalogs.empty_catalog', { defaultValue: 'No catalog items yet' })}
        description={t('supplier_catalogs.empty_catalog_desc', {
          defaultValue: 'SKUs you order - pipe, fittings, materials. Tie to multiple vendors for price comparison.',
        })}
        action={{ label: t('supplier_catalogs.new_item', { defaultValue: 'New Item' }), onClick: onAction }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.sku', { defaultValue: 'SKU' })}</th>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.name', { defaultValue: 'Name' })}</th>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.uom', { defaultValue: 'UoM' })}</th>
            <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.manufacturer', { defaultValue: 'Manufacturer' })}</th>
            <th className="px-4 py-2.5 text-right">{t('supplier_catalogs.reorder', { defaultValue: 'Reorder' })}</th>
            <th className="px-4 py-2.5 text-right">{t('supplier_catalogs.actions', { defaultValue: 'Actions' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-border-light hover:bg-surface-secondary">
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.sku}</td>
              {/* The inactive marker is the visible half of the Active box in
                  the edit modal. Without it the flag would be a setting the
                  user can change and never see again. */}
              <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[320px]">
                <span className="inline-flex items-center gap-2">
                  {r.name}
                  {r.active === false && (
                    <Badge variant="neutral">
                      {t('supplier_catalogs.inactive', { defaultValue: 'Inactive' })}
                    </Badge>
                  )}
                </span>
              </td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.unit_of_measure}</td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.manufacturer || '—'}</td>
              <td className="px-4 py-2 text-right text-xs tabular-nums">{String(r.reorder_point)}</td>
              <td className="px-4 py-2 text-right">
                <div className="flex items-center justify-end gap-1 whitespace-nowrap">
                  <Button variant="ghost" size="sm" onClick={() => onSelectPrice(r)}>
                    {t('supplier_catalogs.compare_prices', { defaultValue: 'Compare prices' })}
                  </Button>
                  <Button variant="ghost" size="sm" icon={<Pencil size={13} />} onClick={() => onEdit(r)}>
                    {t('common.edit', { defaultValue: 'Edit' })}
                  </Button>
                  <Button variant="ghost" size="sm" icon={<Trash2 size={13} />} onClick={() => onDelete(r)}>
                    {t('common.delete', { defaultValue: 'Delete' })}
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * CONN-46: one consolidated hand-off banner for the whole live purchasing
 * workflow (requisitions, purchase orders and three-way matching).
 *
 * The supplier_catalogs backend has no list endpoints for these records and
 * they never surface in /procurement, so creating them here would be a
 * create-into-the-void. Rather than three dead tabs that each said the same
 * thing, this single banner names the three stages and deep-links to
 * /procurement, which owns them.
 */
function ProcurementHandoffPanel() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const stages = [
    {
      icon: <ClipboardList size={16} className="text-content-tertiary" />,
      title: t('supplier_catalogs.stage_prs', {
        defaultValue: 'Requisitions',
      }),
      desc: t('supplier_catalogs.stage_prs_desc', {
        defaultValue:
          'Raise, approve and convert purchase requisitions into purchase orders.',
      }),
    },
    {
      icon: <ShoppingCart size={16} className="text-content-tertiary" />,
      title: t('supplier_catalogs.stage_pos', {
        defaultValue: 'Purchase orders',
      }),
      desc: t('supplier_catalogs.stage_pos_desc', {
        defaultValue:
          'Issue orders to vendors and follow the draft, sent, acknowledged, received and closed flow.',
      }),
    },
    {
      icon: <FileCheck size={16} className="text-content-tertiary" />,
      title: t('supplier_catalogs.stage_match', {
        defaultValue: 'Three-way match',
      }),
      desc: t('supplier_catalogs.stage_match_desc', {
        defaultValue:
          'Match vendor invoices against their purchase order and goods receipt, resolving tolerance exceptions.',
      }),
    },
  ];

  return (
    <div className="p-6">
      <div className="mx-auto max-w-2xl text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-surface-secondary text-content-tertiary">
          <ShoppingCart size={22} />
        </div>
        <h3 className="text-base font-semibold text-content-primary">
          {t('supplier_catalogs.procurement_handoff_title', {
            defaultValue: 'Live purchasing lives in Procurement',
          })}
        </h3>
        <p className="mt-1.5 text-sm text-content-secondary">
          {t('supplier_catalogs.procurement_handoff_desc', {
            defaultValue:
              'This page is the vendor and item reference library that purchasing draws from. Requisitions, purchase orders and three-way invoice matching all run in the Procurement module.',
          })}
        </p>
      </div>

      <div className="mx-auto mt-5 grid max-w-3xl gap-3 sm:grid-cols-3">
        {stages.map((s) => (
          <div
            key={s.title}
            className="rounded-xl border border-border-light bg-surface-secondary/40 p-4 text-left"
          >
            <div className="mb-2 flex items-center gap-2">
              {s.icon}
              <p className="text-sm font-medium text-content-primary">{s.title}</p>
            </div>
            <p className="text-xs text-content-secondary">{s.desc}</p>
          </div>
        ))}
      </div>

      <div className="mt-5 flex justify-center">
        <Button
          variant="primary"
          icon={<ArrowUpRight size={14} />}
          onClick={() => navigate('/procurement')}
        >
          {t('supplier_catalogs.go_to_procurement', {
            defaultValue: 'Go to Procurement',
          })}
        </Button>
      </div>
    </div>
  );
}

function WarehousePanel({
  warehouses,
  selectedId,
  balances,
  itemLookup,
  onAction,
  onEdit,
  onDelete,
}: {
  warehouses: Warehouse[];
  selectedId: string;
  balances: StockBalance[];
  itemLookup: Map<string, CatalogItem>;
  onAction: () => void;
  onEdit: (warehouse: Warehouse) => void;
  onDelete: (warehouse: Warehouse) => void;
}) {
  const { t } = useTranslation();
  if (warehouses.length === 0) {
    return (
      <EmptyState
        icon={<WarehouseIcon size={22} />}
        title={t('supplier_catalogs.empty_warehouses', { defaultValue: 'No warehouses yet' })}
        description={t('supplier_catalogs.empty_warehouses_desc', {
          defaultValue: 'Register storage locations to track stock on hand, reservations and movements.',
        })}
        action={{
          label: t('supplier_catalogs.new_warehouse', { defaultValue: 'New Warehouse' }),
          onClick: onAction,
        }}
      />
    );
  }
  const selected = warehouses.find((w) => w.id === selectedId) || warehouses[0];
  return (
    <div>
      <div className="px-5 py-3 border-b border-border-light flex items-center gap-3 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-wide text-content-tertiary">
            {t('supplier_catalogs.warehouse', { defaultValue: 'Warehouse' })}
          </p>
          <p className="text-sm font-semibold text-content-primary">
            {selected?.code} — {selected?.name}
          </p>
        </div>
        {selected?.address && (
          <div>
            <p className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('supplier_catalogs.address', { defaultValue: 'Address' })}
            </p>
            <p className="text-xs text-content-secondary truncate max-w-[320px]">{selected.address}</p>
          </div>
        )}
        {/* The warehouses tab shows one location at a time through the picker
            above, so its row actions belong to the selected one rather than
            to a table row. */}
        {selected && (
          <div className="ml-auto flex items-center gap-1 whitespace-nowrap">
            <Button variant="ghost" size="sm" icon={<Pencil size={13} />} onClick={() => onEdit(selected)}>
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
            <Button variant="ghost" size="sm" icon={<Trash2 size={13} />} onClick={() => onDelete(selected)}>
              {t('common.delete', { defaultValue: 'Delete' })}
            </Button>
          </div>
        )}
      </div>
      {balances.length === 0 ? (
        <div className="p-6 text-center text-sm text-content-tertiary">
          {t('supplier_catalogs.no_stock', { defaultValue: 'No stock balances recorded.' })}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.item', { defaultValue: 'Item' })}</th>
                <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.batch', { defaultValue: 'Batch' })}</th>
                <th className="px-4 py-2.5 text-right">{t('supplier_catalogs.on_hand', { defaultValue: 'On hand' })}</th>
                <th className="px-4 py-2.5 text-right">{t('supplier_catalogs.reserved', { defaultValue: 'Reserved' })}</th>
                <th className="px-4 py-2.5 text-right">{t('supplier_catalogs.unit_cost_avg', { defaultValue: 'Avg cost' })}</th>
                <th className="px-4 py-2.5 text-left">{t('supplier_catalogs.last_moved', { defaultValue: 'Last moved' })}</th>
              </tr>
            </thead>
            <tbody>
              {balances.map((b) => {
                const item = itemLookup.get(b.catalog_item_id);
                return (
                <tr key={b.id} className="border-t border-border-light hover:bg-surface-secondary">
                  <td className="px-4 py-2 max-w-[320px]">
                    {item ? (
                      <div className="min-w-0">
                        <p className="font-medium text-content-primary truncate">{item.name}</p>
                        <p className="font-mono text-2xs text-content-tertiary truncate">{item.sku}</p>
                      </div>
                    ) : (
                      <span className="text-xs text-content-tertiary">
                        {t('supplier_catalogs.unknown_item', { defaultValue: 'Unknown item' })}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-content-secondary text-xs">{b.batch_lot || '—'}</td>
                  <td className="px-4 py-2 text-right text-xs tabular-nums">{String(b.quantity_on_hand)}</td>
                  <td className="px-4 py-2 text-right text-xs tabular-nums">{String(b.quantity_reserved)}</td>
                  {/* The average is money and carries its own ISO currency,
                      which is not the currency the operator picked in
                      settings. When the backend has no single-currency
                      average we say so rather than rendering a number under
                      a label that would be wrong either way. */}
                  <td className="px-4 py-2 text-right text-xs tabular-nums">
                    {b.unit_cost_avg !== null && b.currency ? (
                      <MoneyDisplay amount={Number(b.unit_cost_avg)} currency={b.currency} />
                    ) : (
                      <span className="text-content-tertiary">
                        {b.cost_state === 'mixed'
                          ? t('supplier_catalogs.avg_cost_mixed', { defaultValue: 'Mixed currencies' })
                          : t('supplier_catalogs.avg_cost_unknown', { defaultValue: 'Not available' })}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-content-secondary">
                    {b.last_movement_at ? <DateDisplay value={b.last_movement_at} /> : '—'}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ── Price comparison modal ────────────────────────────────────────────── */

function PriceComparisonModal({
  item,
  vendors,
  onClose,
}: {
  item: CatalogItem;
  vendors: Vendor[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // CONN-47: turn a compared vendor price into a draft purchase order in the
  // Procurement module, which owns the live purchasing workflow. We emit a
  // prefill query contract (a single line item: description / unit / rate /
  // currency, plus a vendor display hint) and navigate there. The consumer on
  // /procurement (ProcurementPage) parses these params to open its New PO
  // modal prefilled - that side lands in a separate batch, so until then the
  // user reaches Procurement with the New-PO intent and fills it manually.
  const createPoFromRow = (row: PriceComparisonRow) => {
    const params = new URLSearchParams({
      new_po: '1',
      vendor: row.vendor_name || row.vendor_code || '',
      line_desc: `${item.sku} - ${item.name}`.trim(),
      line_unit: item.unit_of_measure || '',
      line_rate: String(row.unit_price ?? ''),
      currency: row.currency || '',
    });
    onClose();
    navigate(`/procurement?${params.toString()}`);
  };

  const q = useQuery({
    queryKey: ['sc', 'price-compare', item.id],
    queryFn: () => comparePrices(item.id),
  });
  const rows = q.data ?? [];
  // Money bug fix: each vendor price list carries its own ISO currency, so a
  // raw Number(unit_price) comparison across rows would crown e.g. 100 JPY
  // "cheaper" than 5 EUR. We may only pick a single cheapest when every
  // compared row shares one currency. When currencies differ we never crown a
  // cross-currency winner — the UI shows a "mixed currencies" note instead.
  const distinctCurrencies = useMemo(
    () => new Set(rows.map((r) => r.currency)),
    [rows],
  );
  const singleCurrency = distinctCurrencies.size <= 1;
  const cheapest = useMemo(() => {
    if (rows.length === 0) return null;
    // Only a same-currency comparison is meaningful; otherwise no winner.
    if (!singleCurrency) return null;
    return rows.reduce<PriceComparisonRow | null>((best, r) => {
      if (!best) return r;
      // Decimal-serialized strings: wrap in Number() before comparing.
      return Number(r.unit_price) < Number(best.unit_price) ? r : best;
    }, null);
  }, [rows, singleCurrency]);

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('supplier_catalogs.price_comparison', { defaultValue: 'Price Comparison' })}
      subtitle={`${item.sku} · ${item.name} · ${item.unit_of_measure}`}
      size="xl"
    >
      <div>
        {q.isLoading ? (
          <SkeletonTable rows={5} columns={4} />
        ) : q.isError ? (
          <EmptyState
            icon={<AlertOctagon size={20} />}
            title={t('supplier_catalogs.load_failed', { defaultValue: 'Could not load data' })}
            description={getErrorMessage(q.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => void q.refetch(),
            }}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Boxes size={20} />}
            title={t('supplier_catalogs.no_prices', { defaultValue: 'No vendor prices for this item' })}
            description={t('supplier_catalogs.no_prices_desc', {
              defaultValue: 'Import a price list against a vendor or add a catalog entry.',
            })}
          />
        ) : (
          <>
            {/* Money bug fix: when vendors quote in different ISO currencies we
                cannot rank them by raw number, so we suppress the "Cheapest"
                crown and tell the buyer the prices are not directly comparable. */}
            {!singleCurrency && rows.length > 1 && (
              <div className="mt-1 mb-3 flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning/10 px-3 py-2 text-xs text-content-secondary">
                <AlertOctagon size={14} className="mt-0.5 shrink-0 text-semantic-warning" />
                <span>
                  {t('supplier_catalogs.mixed_currencies', {
                    defaultValue:
                      'Vendors quote in different currencies - prices are not directly comparable, so no cheapest is highlighted.',
                  })}
                </span>
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {rows.map((r) => {
              const vendor = vendors.find((v) => v.id === r.vendor_id);
              const isCheapest = cheapest && cheapest.vendor_id === r.vendor_id && rows.length > 1;
              return (
                <div
                  key={r.vendor_id + r.price_list_id}
                  className={clsx(
                    'rounded-xl border bg-surface-primary p-4 transition-all',
                    isCheapest ? 'border-semantic-success ring-2 ring-semantic-success/30' : 'border-border-light',
                  )}
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="min-w-0">
                      <p className="text-xs font-mono text-content-tertiary">{r.vendor_code}</p>
                      <p className="font-semibold text-content-primary truncate">{r.vendor_name}</p>
                    </div>
                    {isCheapest && (
                      <Badge variant="success">
                        {t('supplier_catalogs.cheapest', { defaultValue: 'Cheapest' })}
                      </Badge>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <div>
                      <p className="text-xs uppercase tracking-wide text-content-tertiary">
                        {t('supplier_catalogs.unit_price', { defaultValue: 'Unit price' })}
                      </p>
                      <p className="text-xl font-bold text-content-primary">
                        <MoneyDisplay amount={Number(r.unit_price)} currency={r.currency} />
                      </p>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <p className="uppercase tracking-wide text-content-tertiary">
                          {t('supplier_catalogs.lead_time', { defaultValue: 'Lead time' })}
                        </p>
                        <p className="text-content-primary tabular-nums">{r.lead_time_days}d</p>
                      </div>
                      <div>
                        <p className="uppercase tracking-wide text-content-tertiary">
                          {t('supplier_catalogs.moq', { defaultValue: 'MOQ' })}
                        </p>
                        <p className="text-content-primary tabular-nums">{String(r.min_order_qty)}</p>
                      </div>
                    </div>
                    <div className="pt-1 border-t border-border-light">
                      <p className="text-xs uppercase tracking-wide text-content-tertiary">
                        {t('supplier_catalogs.rating', { defaultValue: 'Rating' })}
                      </p>
                      <StarRating rating={r.rating ?? vendor?.rating ?? null} />
                    </div>
                    {/* CONN-47: buy from this vendor - hand off to Procurement
                        with the line prefilled from this catalog item + price. */}
                    <div className="pt-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        className="w-full"
                        icon={<ShoppingCart size={14} />}
                        onClick={() => createPoFromRow(r)}
                      >
                        {t('supplier_catalogs.create_po', { defaultValue: 'Create PO' })}
                      </Button>
                    </div>
                  </div>
                </div>
              );
              })}
            </div>
          </>
        )}
      </div>
    </WideModal>
  );
}

/* ── Create modal ──────────────────────────────────────────────────────── */

/** Tabs that own a real create flow on this page. PR/PO/match hand off to
 *  /procurement, so they never reach the create modal. */
type CreateTab = 'vendors' | 'catalog' | 'warehouses';

function CreateModal({
  kind,
  onClose,
}: {
  kind: CreateTab;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  // Vendor currency is the vendor's OWN trading currency, not a project
  // currency, so there is no sensible default to pre-fill: leave it blank
  // (the backend treats an empty value as "unset") rather than hardcoding EUR.
  const [vendorForm, setVendorForm] = useState({
    code: '',
    name: '',
    legal_name: '',
    currency: '',
    payment_terms_days: '30',
    country_code: '',
  });
  const [itemForm, setItemForm] = useState({
    sku: '',
    name: '',
    description: '',
    unit_of_measure: 'pcs',
    manufacturer: '',
  });
  const [warehouseForm, setWarehouseForm] = useState({ code: '', name: '', address: '' });

  const submit = async () => {
    setBusy(true);
    try {
      if (kind === 'vendors') {
        if (!vendorForm.code.trim() || !vendorForm.name.trim()) throw new Error('Code and name required');
        await createVendor({
          code: vendorForm.code,
          name: vendorForm.name,
          legal_name: vendorForm.legal_name || undefined,
          currency: vendorForm.currency || undefined,
          payment_terms_days: Number(vendorForm.payment_terms_days) || 30,
          country_code: vendorForm.country_code || undefined,
        });
        addToast({ type: 'success', title: t('supplier_catalogs.vendor_created', { defaultValue: 'Vendor created' }) });
        qc.invalidateQueries({ queryKey: ['sc', 'vendors'] });
      } else if (kind === 'catalog') {
        if (!itemForm.sku.trim() || !itemForm.name.trim()) throw new Error('SKU and name required');
        await createCatalogItem({
          sku: itemForm.sku,
          name: itemForm.name,
          description: itemForm.description || undefined,
          unit_of_measure: itemForm.unit_of_measure || 'pcs',
          manufacturer: itemForm.manufacturer || undefined,
        });
        addToast({ type: 'success', title: t('supplier_catalogs.item_created', { defaultValue: 'Item created' }) });
        qc.invalidateQueries({ queryKey: ['sc', 'items'] });
      } else if (kind === 'warehouses') {
        if (!warehouseForm.code.trim() || !warehouseForm.name.trim()) throw new Error('Code and name required');
        await createWarehouse({
          code: warehouseForm.code,
          name: warehouseForm.name,
          address: warehouseForm.address || undefined,
        });
        addToast({ type: 'success', title: t('supplier_catalogs.warehouse_created', { defaultValue: 'Warehouse created' }) });
        qc.invalidateQueries({ queryKey: ['sc', 'warehouses'] });
      }
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={createLabel(kind, t)}
      size="lg"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      {kind === 'vendors' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('supplier_catalogs.code', { defaultValue: 'Code' })}
            required
          >
            <input
              value={vendorForm.code}
              onChange={(e) => setVendorForm({ ...vendorForm, code: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.country', { defaultValue: 'Country' })}
          >
            <input
              value={vendorForm.country_code}
              onChange={(e) => setVendorForm({ ...vendorForm, country_code: e.target.value })}
              className={inputCls}
              maxLength={3}
              placeholder="DE / FR / US"
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.name', { defaultValue: 'Name' })}
            required
            span={2}
          >
            <input
              value={vendorForm.name}
              onChange={(e) => setVendorForm({ ...vendorForm, name: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.legal_name', { defaultValue: 'Legal name' })}
            span={2}
          >
            <input
              value={vendorForm.legal_name}
              onChange={(e) => setVendorForm({ ...vendorForm, legal_name: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('common.currency', { defaultValue: 'Currency' })}
          >
            <input
              value={vendorForm.currency}
              onChange={(e) => setVendorForm({ ...vendorForm, currency: e.target.value })}
              className={inputCls}
              maxLength={3}
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.payment_terms', { defaultValue: 'Payment terms (days)' })}
          >
            <input
              type="number"
              value={vendorForm.payment_terms_days}
              onChange={(e) => setVendorForm({ ...vendorForm, payment_terms_days: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'catalog' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('supplier_catalogs.sku', { defaultValue: 'SKU' })}
            required
          >
            <input
              value={itemForm.sku}
              onChange={(e) => setItemForm({ ...itemForm, sku: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.uom', { defaultValue: 'UoM' })}
          >
            <input
              value={itemForm.unit_of_measure}
              onChange={(e) => setItemForm({ ...itemForm, unit_of_measure: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.name', { defaultValue: 'Name' })}
            required
            span={2}
          >
            <input
              value={itemForm.name}
              onChange={(e) => setItemForm({ ...itemForm, name: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.description_field', { defaultValue: 'Description' })}
            span={2}
          >
            <textarea
              value={itemForm.description}
              onChange={(e) => setItemForm({ ...itemForm, description: e.target.value })}
              rows={2}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.manufacturer', { defaultValue: 'Manufacturer' })}
            span={2}
          >
            <input
              value={itemForm.manufacturer}
              onChange={(e) => setItemForm({ ...itemForm, manufacturer: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'warehouses' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('supplier_catalogs.code', { defaultValue: 'Code' })}
            required
          >
            <input
              value={warehouseForm.code}
              onChange={(e) => setWarehouseForm({ ...warehouseForm, code: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.name', { defaultValue: 'Name' })}
            required
          >
            <input
              value={warehouseForm.name}
              onChange={(e) => setWarehouseForm({ ...warehouseForm, name: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('supplier_catalogs.address', { defaultValue: 'Address' })}
            span={2}
          >
            <textarea
              value={warehouseForm.address}
              onChange={(e) => setWarehouseForm({ ...warehouseForm, address: e.target.value })}
              rows={2}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
        </WideModalSection>
      )}
    </WideModal>
  );
}

/* ── Edit modals ───────────────────────────────────────────────────────── */

/*
 * One modal per record kind rather than one parameterised over three, because
 * the three field sets share nothing but the shape of the form. Each owns its
 * own mutation: the record it edits is the record it invalidates, and a
 * failure is answered where it happened.
 *
 * A note on blanks. Free-text fields are sent exactly as typed, empty string
 * included, so clearing a value in the form clears it on the record. Currency
 * and payment terms are the exceptions: their columns cannot be null, and an
 * empty box means "leave it alone" rather than "set it to nothing".
 */

function EditVendorModal({ vendor, onClose }: { vendor: Vendor; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    name: vendor.name,
    legal_name: vendor.legal_name ?? '',
    tax_id: vendor.tax_id ?? '',
    currency: vendor.currency ?? '',
    payment_terms_days: String(vendor.payment_terms_days ?? ''),
    country_code: vendor.country_code ?? '',
    notes: vendor.notes ?? '',
  });

  const save = useMutation({
    mutationFn: () =>
      updateVendor(vendor.id, {
        name: form.name.trim(),
        legal_name: form.legal_name,
        tax_id: form.tax_id,
        country_code: form.country_code,
        notes: form.notes,
        currency: form.currency.trim() || undefined,
        payment_terms_days: form.payment_terms_days.trim()
          ? Number(form.payment_terms_days)
          : undefined,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('supplier_catalogs.vendor_updated', { defaultValue: 'Vendor updated' }),
      });
      qc.invalidateQueries({ queryKey: ['sc', 'vendors'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('supplier_catalogs.edit_vendor', { defaultValue: 'Edit vendor' })}
      subtitle={vendor.code}
      size="lg"
      busy={save.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            loading={save.isPending}
            disabled={!form.name.trim()}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('supplier_catalogs.name', { defaultValue: 'Name' })}
          required
          span={2}
        >
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.legal_name', { defaultValue: 'Legal name' })} span={2}>
          <input
            value={form.legal_name}
            onChange={(e) => setForm({ ...form, legal_name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.tax_id', { defaultValue: 'Tax ID' })}>
          <input
            value={form.tax_id}
            onChange={(e) => setForm({ ...form, tax_id: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.country', { defaultValue: 'Country' })}>
          <input
            value={form.country_code}
            onChange={(e) => setForm({ ...form, country_code: e.target.value })}
            className={inputCls}
            maxLength={3}
            placeholder="DE / FR / US"
          />
        </WideModalField>
        <WideModalField label={t('common.currency', { defaultValue: 'Currency' })}>
          <input
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value })}
            className={inputCls}
            maxLength={3}
          />
        </WideModalField>
        <WideModalField
          label={t('supplier_catalogs.payment_terms', { defaultValue: 'Payment terms (days)' })}
        >
          <input
            type="number"
            value={form.payment_terms_days}
            onChange={(e) => setForm({ ...form, payment_terms_days: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.notes', { defaultValue: 'Notes' })} span={2}>
          <textarea
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
      {/* The code is what every other record quotes, so it is shown and not
          offered for editing. Saying so is better than a disabled box with no
          explanation. */}
      <p className="mt-3 text-2xs text-content-tertiary">
        {t('supplier_catalogs.code_not_editable', {
          defaultValue:
            'The vendor code cannot be changed here: price lists, orders and invoices are all filed under it.',
        })}
      </p>
    </WideModal>
  );
}

function EditItemModal({ item, onClose }: { item: CatalogItem; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    name: item.name,
    description: item.description ?? '',
    unit_of_measure: item.unit_of_measure ?? '',
    manufacturer: item.manufacturer ?? '',
    mpn: item.mpn ?? '',
    reorder_point: String(item.reorder_point ?? ''),
    active: item.active !== false,
  });

  const save = useMutation({
    mutationFn: () =>
      updateCatalogItem(item.id, {
        name: form.name.trim(),
        description: form.description,
        manufacturer: form.manufacturer,
        mpn: form.mpn,
        unit_of_measure: form.unit_of_measure.trim() || undefined,
        reorder_point: form.reorder_point.trim() || undefined,
        active: form.active,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('supplier_catalogs.item_updated', { defaultValue: 'Item updated' }),
      });
      qc.invalidateQueries({ queryKey: ['sc', 'items'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('supplier_catalogs.edit_item', { defaultValue: 'Edit item' })}
      subtitle={item.sku}
      size="lg"
      busy={save.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            loading={save.isPending}
            disabled={!form.name.trim()}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('supplier_catalogs.name', { defaultValue: 'Name' })} required span={2}>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.uom', { defaultValue: 'UoM' })}>
          <input
            value={form.unit_of_measure}
            onChange={(e) => setForm({ ...form, unit_of_measure: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.reorder', { defaultValue: 'Reorder' })}>
          <input
            type="number"
            value={form.reorder_point}
            onChange={(e) => setForm({ ...form, reorder_point: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.manufacturer', { defaultValue: 'Manufacturer' })}>
          <input
            value={form.manufacturer}
            onChange={(e) => setForm({ ...form, manufacturer: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.mpn', { defaultValue: 'Manufacturer part number' })}>
          <input
            value={form.mpn}
            onChange={(e) => setForm({ ...form, mpn: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('supplier_catalogs.description_field', { defaultValue: 'Description' })}
          span={2}
        >
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
        <WideModalField
          span={2}
          hint={t('supplier_catalogs.active_hint', {
            defaultValue:
              'An inactive item is marked as no longer bought and shows as Inactive in the catalog list. It stays on the records that already quote it.',
          })}
        >
          <label className="flex items-center gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(e) => setForm({ ...form, active: e.target.checked })}
              className="h-4 w-4 rounded border-border"
            />
            {t('common.active', { defaultValue: 'Active' })}
          </label>
        </WideModalField>
      </WideModalSection>
      <p className="mt-3 text-2xs text-content-tertiary">
        {t('supplier_catalogs.sku_not_editable', {
          defaultValue:
            'The SKU cannot be changed here: requisition lines, order lines and vendor price lists all quote it.',
        })}
      </p>
    </WideModal>
  );
}

function EditWarehouseModal({
  warehouse,
  onClose,
}: {
  warehouse: Warehouse;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    name: warehouse.name,
    address: warehouse.address ?? '',
  });

  const save = useMutation({
    mutationFn: () =>
      updateWarehouse(warehouse.id, { name: form.name.trim(), address: form.address }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('supplier_catalogs.warehouse_updated', { defaultValue: 'Warehouse updated' }),
      });
      qc.invalidateQueries({ queryKey: ['sc', 'warehouses'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('supplier_catalogs.edit_warehouse', { defaultValue: 'Edit warehouse' })}
      subtitle={warehouse.code}
      size="lg"
      busy={save.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            loading={save.isPending}
            disabled={!form.name.trim()}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('supplier_catalogs.name', { defaultValue: 'Name' })} required span={2}>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.address', { defaultValue: 'Address' })} span={2}>
          <textarea
            value={form.address}
            onChange={(e) => setForm({ ...form, address: e.target.value })}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
      <p className="mt-3 text-2xs text-content-tertiary">
        {t('supplier_catalogs.warehouse_code_not_editable', {
          defaultValue:
            'The code and the project a warehouse belongs to are fixed here: the project decides who may see its stock.',
        })}
      </p>
    </WideModal>
  );
}

/* ── Vendor status & rating ────────────────────────────────────────────── */

/**
 * Suspend or blacklist, with the optional reason the backend records.
 *
 * The two actions share a modal because they differ only in the sentence
 * above the box and in which endpoint is called; splitting them would
 * duplicate the reason field and the failure handling for no gain.
 */
function VendorStatusModal({
  vendor,
  action,
  onClose,
}: {
  vendor: Vendor;
  action: 'suspend' | 'blacklist';
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [reason, setReason] = useState('');

  const apply = useMutation({
    mutationFn: () =>
      action === 'suspend'
        ? suspendVendor(vendor.id, reason.trim() || undefined)
        : blacklistVendor(vendor.id, reason.trim() || undefined),
    onSuccess: () => {
      addToast({
        type: 'success',
        title:
          action === 'suspend'
            ? t('supplier_catalogs.vendor_suspended', { defaultValue: 'Vendor suspended' })
            : t('supplier_catalogs.vendor_blacklisted', { defaultValue: 'Vendor blacklisted' }),
      });
      qc.invalidateQueries({ queryKey: ['sc', 'vendors'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={
        action === 'suspend'
          ? t('supplier_catalogs.suspend_vendor_title', { defaultValue: 'Suspend vendor' })
          : t('supplier_catalogs.blacklist_vendor_title', { defaultValue: 'Blacklist vendor' })
      }
      subtitle={`${vendor.code} · ${vendor.name}`}
      size="md"
      busy={apply.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={apply.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={() => apply.mutate()} loading={apply.isPending}>
            {action === 'suspend'
              ? t('supplier_catalogs.suspend', { defaultValue: 'Suspend' })
              : t('supplier_catalogs.blacklist', { defaultValue: 'Blacklist' })}
          </Button>
        </>
      }
    >
      <p className="text-sm text-content-secondary">
        {action === 'suspend'
          ? t('supplier_catalogs.suspend_vendor_desc', {
              defaultValue:
                'A suspended vendor keeps its history and stops being offered for new orders. It can be made active again.',
            })
          : t('supplier_catalogs.blacklist_vendor_desc', {
              defaultValue:
                'Blacklisting closes the vendor. Its history is kept and it cannot be suspended afterwards, only reopened deliberately.',
            })}
      </p>
      <div className="mt-4">
        <WideModalSection columns={1}>
          <WideModalField
            label={t('supplier_catalogs.reason', { defaultValue: 'Reason' })}
            hint={t('supplier_catalogs.reason_hint', {
              defaultValue: 'Optional. Recorded with the status change so the decision can be traced.',
            })}
          >
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
        </WideModalSection>
      </div>
    </WideModal>
  );
}

function VendorRatingModal({ vendor, onClose }: { vendor: Vendor; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [rating, setRating] = useState(vendor.rating ?? 3);
  const [comment, setComment] = useState('');

  const submit = useMutation({
    mutationFn: () => rateVendor(vendor.id, rating, comment.trim() || undefined),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('supplier_catalogs.vendor_rated', { defaultValue: 'Rating saved' }),
      });
      qc.invalidateQueries({ queryKey: ['sc', 'vendors'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('supplier_catalogs.rate_vendor_title', { defaultValue: 'Rate vendor' })}
      subtitle={`${vendor.code} · ${vendor.name}`}
      size="md"
      busy={submit.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submit.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={() => submit.mutate()} loading={submit.isPending}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('supplier_catalogs.rating', { defaultValue: 'Rating' })}
          required
          hint={t('supplier_catalogs.rate_vendor_hint', {
            defaultValue: 'One to five. It shows on the vendor list and beside every quoted price.',
          })}
        >
          <div className="flex items-center gap-3">
            <select
              value={String(rating)}
              onChange={(e) => setRating(Number(e.target.value))}
              className={clsx(inputCls, 'max-w-[120px]')}
              aria-label={t('supplier_catalogs.rating', { defaultValue: 'Rating' })}
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <StarRating rating={rating} />
          </div>
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.rating_comment', { defaultValue: 'Comment' })}>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={3}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
