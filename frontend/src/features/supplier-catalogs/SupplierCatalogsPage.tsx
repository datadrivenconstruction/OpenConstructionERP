import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
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
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  DismissibleInfo,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import {
  listVendors,
  listCatalogItems,
  listWarehouses,
  listWarehouseBalances,
  comparePrices,
  createVendor,
  createCatalogItem,
  createWarehouse,
  type Vendor,
  type CatalogItem,
  type Warehouse,
  type StockBalance,
  type PriceComparisonRow,
  type VendorStatus,
} from './api';

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

export function SupplierCatalogsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('vendors');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [priceItem, setPriceItem] = useState<CatalogItem | null>(null);
  const [selectedWarehouseId, setSelectedWarehouseId] = useState<string>('');

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
    if (Array.isArray(itemLookupQ.data)) {
      for (const it of itemLookupQ.data) map.set(it.id, it);
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
  // from a previous session), which would crash ``.filter()`` below.
  const vendorsArr = Array.isArray(vendorsQ.data) ? vendorsQ.data : [];
  const itemsArr = Array.isArray(itemsQ.data) ? itemsQ.data : [];
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

  return (
    <div className="space-y-5 animate-fade-in">
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
          canCreateHere && (
            <Button variant="primary" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>
              {createLabel(tab, t)}
            </Button>
          )
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
          <VendorTable rows={filteredVendors} onAction={() => setCreateOpen(true)} />
        ) : tab === 'catalog' ? (
          <CatalogTable rows={filteredItems} onSelectPrice={(it) => setPriceItem(it)} onAction={() => setCreateOpen(true)} />
        ) : tab === 'procurement' ? (
          <ProcurementHandoffPanel />
        ) : (
          <WarehousePanel
            warehouses={warehousesArr}
            selectedId={effectiveWarehouseId}
            balances={balancesArr}
            itemLookup={itemLookup}
            onAction={() => setCreateOpen(true)}
          />
        )}
      </Card>

      {createOpen && canCreateHere && (
        <CreateModal kind={tab} onClose={() => setCreateOpen(false)} />
      )}
      {priceItem && (
        <PriceComparisonModal
          item={priceItem}
          vendors={vendorsQ.data ?? []}
          onClose={() => setPriceItem(null)}
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

function VendorTable({ rows, onAction }: { rows: Vendor[]; onAction: () => void }) {
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
}: {
  rows: CatalogItem[];
  onSelectPrice: (item: CatalogItem) => void;
  onAction: () => void;
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
              <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[320px]">{r.name}</td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.unit_of_measure}</td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.manufacturer || '—'}</td>
              <td className="px-4 py-2 text-right text-xs tabular-nums">{String(r.reorder_point)}</td>
              <td className="px-4 py-2 text-right">
                <Button variant="ghost" size="sm" onClick={() => onSelectPrice(r)}>
                  {t('supplier_catalogs.compare_prices', { defaultValue: 'Compare prices' })}
                </Button>
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
}: {
  warehouses: Warehouse[];
  selectedId: string;
  balances: StockBalance[];
  itemLookup: Map<string, CatalogItem>;
  onAction: () => void;
}) {
  const { t } = useTranslation();
  // StockBalance carries no currency field; warehouses themselves are
  // currency-agnostic. Fall back to the user's preferred currency so
  // the column shows a unit instead of a post-Wave2 em-dash.
  const prefCurrency = usePreferencesStore((s) => s.currency);
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
                  <td className="px-4 py-2 text-right text-xs tabular-nums">
                    <MoneyDisplay amount={Number(b.unit_cost_avg) || 0} currency={prefCurrency} />
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

