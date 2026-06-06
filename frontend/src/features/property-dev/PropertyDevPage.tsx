import { useState, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  useQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Building2,
  Grid3X3,
  Home,
  Users,
  Key,
  ShieldAlert,
  Plus,
  Search,
  Loader2,
  Check,
  Clock,
  AlertOctagon,
  Pencil,
  Globe2,
  LayoutDashboard,
  Wallet,
  ArrowRight,
  FileSignature,
  Trash2,
  XCircle,
  UserPlus,
  ArrowRightCircle,
  Filter,
  Layers,
  Briefcase,
  ChevronDown,
  BookmarkCheck,
  Lock,
  Receipt,
  FileText,
  Send,
  DollarSign,
  House,
  LayoutGrid,
  MapPin,
  CalendarClock,
  UserCircle2,
  Link as LinkIcon,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  DismissibleInfo,
  SkeletonTable,
  SideDrawer,
  ConfirmDialog,
  ModuleHelpButton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useToastStore } from '@/stores/useToastStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage, ApiError } from '@/shared/lib/api';
import { EditBuyerModal } from './EditBuyerModal';
import { BuyerAccessLinkPanel } from '@/features/buyer-portal/BuyerAccessLinkPanel';
import { DocumentPreviewModal } from './DocumentPreviewModal';
import { SnagsBlock } from './SnagsBlock';
import { HandoverDocumentsSection } from './HandoverDocumentsSection';
import type { PropDevDocType } from './api';
import {
  listDevelopments,
  createDevelopment,
  listPlots,
  createPlot,
  updatePlot,
  deletePlot,
  reservePlot,
  listHouseTypes,
  createHouseType,
  fetchHouseTypes,
  createHouseTypeCatalogue,
  type HouseTypeCatalogueEntry,
  listBuyers,
  createBuyer,
  contractBuyer,
  deleteBuyer,
  cancelBuyer,
  listSelections,
  listHandovers,
  createHandover,
  deleteHandover,
  completeHandover,
  listWarrantyClaims,
  createWarrantyClaim,
  acceptWarrantyClaim,
  rejectWarrantyClaim,
  closeWarrantyClaim,
  updateWarrantyClaim,
  downloadWarrantyClaimPdf,
  listLeads,
  getLead,
  createLead,
  updateLead,
  deleteLead,
  convertLeadToReservation,
  allowedLeadTransitions,
  type Buyer,
  type BuyerStatus,
  type Development,
  type DevelopmentSalesPhase,
  type DevelopmentType,
  type Handover,
  type HouseType,
  type Lead,
  type LeadSource,
  type LeadStatus,
  type Plot,
  type PlotStatus,
  type WarrantyCategory,
  type WarrantyClaim,
  type WarrantySeverity,
  type WarrantyStatus,
  // R6 reservation / SPA / payment-schedule / instalment
  listReservations,
  createReservation,
  cancelReservation,
  expireReservation,
  convertReservationToSpa,
  listSalesContracts,
  sendSpaForSignature,
  signSalesContract,
  cancelSalesContract,
  listPaymentSchedules,
  listPaymentScheduleTemplates,
  generatePaymentScheduleFromTemplate,
  activatePaymentSchedule,
  suspendPaymentSchedule,
  listInstalments,
  markInstalmentPaid,
  issueInstalmentDemand,
  waiveInstalment,
  type Reservation,
  type ReservationStatus,
  type SalesContract,
  type SpaStatus,
  type PaymentSchedule,
  type PaymentScheduleStatus,
  type Instalment,
  type InstalmentStatus,
} from './api';
import {
  PhasesTab,
  BlocksTab,
  BrokersTab,
  PriceMatrixTab,
  EscrowTab,
} from './PropDevSubEntityTabs';
import { OverviewTab } from './tabs/OverviewTab';
import { DevelopmentsGrid } from './tabs/DevelopmentsTab';
import { PlotsTab } from './tabs/PlotsTab';
import { HouseTypesTab } from './tabs/HouseTypesTab';

// Order matters — arrow-key navigation walks the list in this order.
const PROPDEV_TAB_IDS = [
  'overview',
  'developments',
  'phases',
  'blocks',
  'plots',
  'house_types',
  'leads',
  'buyers',
  'reservations',
  'spa',
  'payment_schedule',
  'brokers',
  'price_matrix',
  'escrow',
  'handovers',
  'warranty',
] as const;
type Tab = (typeof PROPDEV_TAB_IDS)[number];

const PLOT_STATUS_VARIANT: Record<PlotStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  planned: 'neutral',
  reserved: 'warning',
  under_construction: 'blue',
  ready: 'blue',
  sold: 'success',
  handed_over: 'success',
  held: 'warning',
  blocked: 'error',
};

const BUYER_STAGE_ORDER: BuyerStatus[] = ['lead', 'reserved', 'contracted', 'completed'];
const BUYER_VARIANT: Record<BuyerStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  lead: 'neutral',
  reserved: 'warning',
  contracted: 'blue',
  completed: 'success',
  cancelled: 'error',
};

const WARRANTY_VARIANT: Record<WarrantyStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  raised: 'warning',
  under_review: 'blue',
  accepted: 'success',
  rejected: 'error',
  closed: 'neutral',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const inputErrCls =
  'h-9 w-full rounded-lg border border-semantic-error bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-semantic-error/30';

const ISO_CURRENCY_RE = /^[A-Z]{3}$/;

// labelCls is still used by a couple of small inline modals (e.g.
// BuyerContract date-pair) that were not migrated to WideModal because
// they're tiny confirmation panels rather than full forms.
const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

/* ─── helpers ─── */

function toNumber(v: number | string | null | undefined): number {
  if (v == null) return 0;
  if (typeof v === 'number') return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function todayIso(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return null;
  const now = new Date();
  const diff = (target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
  return Math.ceil(diff);
}

/* ─── Page ─── */

export function PropertyDevPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('overview');
  const [selectedDevId, setSelectedDevId] = useState<string>('');
  const [search, setSearch] = useState('');
  // Arrow-key navigation for the 16-tab strip (WCAG 2.1.1).
  const onTabKeyDown = useTabKeyboardNav<Tab>({
    ids: PROPDEV_TAB_IDS,
    activeId: tab,
    onChange: (next) => {
      setTab(next);
      setSearch('');
    },
    orientation: 'horizontal',
  });
  const [createOpen, setCreateOpen] = useState(false);
  const [activePlotId, setActivePlotId] = useState<string | null>(null);
  const [activeBuyerId, setActiveBuyerId] = useState<string | null>(null);
  const [activeLeadId, setActiveLeadId] = useState<string | null>(null);
  // When the user clicks the Convert-to-Reservation button on a Lead
  // card we open a dedicated modal at the page level (not inside the
  // drawer, because the user often wants to dismiss the drawer first).
  const [convertingLead, setConvertingLead] = useState<Lead | null>(null);
  // Cross-tab filter preset — set by Overview KPI tiles so clicks land
  // on a pre-narrowed Warranty view ("Open warranty (3)" → 3 rows).
  const [warrantyStatusPreset, setWarrantyStatusPreset] = useState<string>('');

  // Deep link from Contacts (and elsewhere): /property-dev?tab=leads&leadId=…
  // or ?tab=buyers&buyerId=…. We honour ?tab= to switch the active tab, and
  // a leadId/buyerId to open the matching detail drawer. The param set is
  // read once on mount and cleared with replace so a refresh / share keeps
  // the user wherever they navigated next. Leads are not development-scoped,
  // so a leadId resolves directly; buyers resolve against the auto-selected
  // development's loaded list (best effort).
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkConsumedRef = useRef(false);

  const developmentsQ = useQuery({
    queryKey: ['propdev', 'developments'],
    queryFn: () => listDevelopments({ limit: 100 }),
  });
  const developments = developmentsQ.data ?? [];

  useEffect(() => {
    if (!selectedDevId && developments.length > 0) {
      const first = developments[0];
      if (first) setSelectedDevId(first.id);
    }
  }, [developments, selectedDevId]);

  useEffect(() => {
    if (deepLinkConsumedRef.current) return;
    const requestedTab = searchParams.get('tab');
    const leadId = searchParams.get('leadId');
    const buyerId = searchParams.get('buyerId');
    if (!requestedTab && !leadId && !buyerId) return;
    deepLinkConsumedRef.current = true;

    if (leadId) {
      setTab('leads');
      setActiveLeadId(leadId);
    } else if (buyerId) {
      setTab('buyers');
      setActiveBuyerId(buyerId);
    } else if (
      requestedTab &&
      (PROPDEV_TAB_IDS as readonly string[]).includes(requestedTab)
    ) {
      setTab(requestedTab as Tab);
    }

    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('tab');
        next.delete('leadId');
        next.delete('buyerId');
        return next;
      },
      { replace: true },
    );
    // Read once on mount; cleared immediately after.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const plotsQ = useQuery({
    queryKey: ['propdev', 'plots', selectedDevId],
    queryFn: () => listPlots({ development_id: selectedDevId, limit: 500 }),
    // Handovers + Warranty tabs both need the plot list (HandoversTab filters
    // candidate plots; WarrantyTab joins claims to plot context). Without
    // 'handovers' / 'warranty' here those tabs rendered as if there were no
    // plots at all — root cause of "Handovers вообще не работает".
    // The Buyers tab also needs plots now (new ``Plot`` column resolves
    // ``buyer.plot_id`` against this list).
    enabled:
      !!selectedDevId &&
      (tab === 'plots' ||
        tab === 'developments' ||
        tab === 'handovers' ||
        tab === 'warranty' ||
        tab === 'buyers' ||
        tab === 'reservations' ||
        tab === 'spa' ||
        tab === 'payment_schedule'),
  });
  const houseTypesQ = useQuery({
    queryKey: ['propdev', 'house-types', selectedDevId],
    queryFn: () => listHouseTypes(selectedDevId),
    enabled: !!selectedDevId && (tab === 'house_types' || tab === 'plots'),
  });
  const buyersQ = useQuery({
    queryKey: ['propdev', 'buyers', selectedDevId],
    queryFn: () => listBuyers({ development_id: selectedDevId, limit: 500 }),
    enabled:
      !!selectedDevId &&
      (tab === 'buyers' ||
        tab === 'handovers' ||
        tab === 'warranty' ||
        tab === 'reservations' ||
        tab === 'spa' ||
        tab === 'payment_schedule'),
  });
  // Leads are top-of-funnel: a lead may exist without a development_id
  // (e.g. an inbound web-form before the agent has triaged it). When a
  // development is selected we scope the list to it, otherwise we fetch
  // every lead the caller owns. Either way it's enabled only on the
  // /leads tab so we don't burn requests elsewhere.
  const leadsQ = useQuery({
    queryKey: ['propdev', 'leads', selectedDevId],
    queryFn: () =>
      listLeads(
        selectedDevId
          ? { development_id: selectedDevId, limit: 500 }
          : { limit: 500 },
      ),
    enabled: tab === 'leads',
  });

  const allPlots = plotsQ.data ?? [];
  const allBuyers = buyersQ.data ?? [];
  const allLeads = leadsQ.data ?? [];

  const filteredBuyers = useMemo(() => {
    const s = search.toLowerCase();
    if (!s) return allBuyers;
    return allBuyers.filter(
      (b) =>
        (b.full_name || '').toLowerCase().includes(s) ||
        (b.email || '').toLowerCase().includes(s),
    );
  }, [allBuyers, search]);

  const isLoading =
    developmentsQ.isLoading ||
    (tab === 'plots' && plotsQ.isLoading) ||
    (tab === 'house_types' && houseTypesQ.isLoading) ||
    (tab === 'buyers' && buyersQ.isLoading) ||
    (tab === 'leads' && leadsQ.isLoading);

  // A failed list query must NOT fall through to the "nothing here yet"
  // empty state — that hides real backend/permission failures behind a
  // success-looking screen. Surface it with a retry instead.
  const activeQuery =
    tab === 'plots'
      ? plotsQ
      : tab === 'house_types'
        ? houseTypesQ
        : tab === 'buyers' || tab === 'handovers' || tab === 'warranty'
          ? buyersQ
          : tab === 'leads'
            ? leadsQ
            : developmentsQ;
  const loadError =
    developmentsQ.isError
      ? developmentsQ.error
      : activeQuery.isError
        ? activeQuery.error
        : null;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('propdev.title', { defaultValue: 'Property Development' }) },
        ]}
      />

      <PageHeader
        srTitle={t('propdev.title', { defaultValue: 'Property Development' })}
        subtitle={t('propdev.subtitle', {
          defaultValue:
            'Developments, plots, buyer journeys, handovers and warranty claims.',
        })}
        actions={
          <>
          <Button
            variant="primary"
            icon={<Plus size={14} />}
            data-testid="propdev-tour-new-button"
            onClick={() => {
              // From the overview tab, opening the primary CTA falls
              // through to creating a development — the natural first
              // step for a brand-new tenant. From every other tab the
              // CTA matches the entity that tab edits.
              if (tab === 'overview' || tab === 'handovers' || tab === 'warranty') {
                // overview/handovers/warranty don't have their own
                // create-modal; route the user to the developments tab
                // and open the creator there.
                setTab('developments');
              }
              // SPA + Payment Schedule rows are always created
              // downstream of a Reservation — the global CTA on those
              // tabs bounces the user to the Reservations tab where
              // the real flow starts.
              if (tab === 'spa' || tab === 'payment_schedule') {
                setTab('reservations');
                return;
              }
              // Sub-entity tabs (phases/blocks/brokers/price-matrix/escrow/reservations)
              // own their own create UI — the global CTA broadcasts via a
              // window event picked up by the relevant tab.
              if (
                tab === 'phases' ||
                tab === 'blocks' ||
                tab === 'brokers' ||
                tab === 'price_matrix' ||
                tab === 'escrow' ||
                tab === 'reservations'
              ) {
                window.dispatchEvent(
                  new CustomEvent('propdev:new-sub-entity', { detail: { tab } }),
                );
                return;
              }
              setCreateOpen(true);
            }}
          >
            {tab === 'overview'
              ? t('propdev.new_development', { defaultValue: 'New Development' })
              : tab === 'developments'
                ? t('propdev.new_development', { defaultValue: 'New Development' })
                : tab === 'phases'
                  ? t('propdev.new_phase', { defaultValue: 'New Phase' })
                  : tab === 'blocks'
                    ? t('propdev.new_block', { defaultValue: 'New Block' })
                    : tab === 'plots'
                      ? t('propdev.new_plot', { defaultValue: 'New Plot' })
                      : tab === 'house_types'
                        ? t('propdev.new_house_type', { defaultValue: 'New House Type' })
                        : tab === 'leads'
                          ? t('propdev.new_lead', { defaultValue: 'New Lead' })
                          : tab === 'buyers'
                            ? t('propdev.new_buyer', { defaultValue: 'New Buyer' })
                            : tab === 'reservations'
                              ? t('propdev.new_reservation', { defaultValue: 'New Reservation' })
                              : tab === 'spa'
                                ? t('propdev.go_to_reservations', { defaultValue: 'Start from Reservations' })
                                : tab === 'payment_schedule'
                                  ? t('propdev.go_to_reservations', { defaultValue: 'Start from Reservations' })
                                  : tab === 'brokers'
                              ? t('propdev.new_broker', { defaultValue: 'New Broker' })
                              : tab === 'price_matrix'
                                ? t('propdev.new_price_matrix', { defaultValue: 'New Price Matrix' })
                                : tab === 'escrow'
                                  ? t('propdev.new_escrow_account', { defaultValue: 'New Escrow Account' })
                                  : t('propdev.new_development', { defaultValue: 'New Development' })}
          </Button>
          <Button
            variant="ghost"
            icon={<LayoutDashboard size={14} />}
            onClick={() => navigate('/property-dev/dashboards')}
            aria-label={t('propdev.open_dashboards', {
              defaultValue: 'Open analytics dashboards',
            })}
            data-testid="propdev-tour-dashboards-button"
          >
            {t('propdev.dashboards_short', { defaultValue: 'Dashboards' })}
          </Button>
          {/* Per-module Tour CTA — launches the PropDev guided tour. */}
          <ModuleHelpButton tourId="propdev" />
          </>
        }
      />

      <div data-testid="propdev-tour-pipeline">
        <DismissibleInfo
          storageKey="property-dev"
          title={t('propdev.intro_title', {
            defaultValue: 'Take a buyer from first enquiry to handover',
          })}
          links={[
            {
              label: t('nav.contracts', { defaultValue: 'Contracts' }),
              onClick: () => navigate('/contracts'),
            },
            {
              label: t('finance.title', { defaultValue: 'Finance' }),
              onClick: () => navigate('/finance'),
            },
            {
              label: t('nav.accommodation', { defaultValue: 'Accommodation' }),
              onClick: () => navigate('/accommodation'),
            },
          ]}
        >
          {t('propdev.intro_body', {
            defaultValue:
              'Lay out a development of plots and house types, then move buyers from lead to reservation to contract to handover and service warranty claims afterwards. Signed contract values flow into Finance, so the sales pipeline and the project books stay in step.',
          })}
        </DismissibleInfo>
      </div>

      {/* Tabs — all 16 icon buttons in a single wrap row. Group boundaries
          shown via a thin vertical divider so the master-data → sales →
          operations lifecycle is still discoverable without consuming
          three separate rows on wide screens.

          v4.9 — tabs are now rendered as three labelled blocks
          (Master data / Sales / Operations) so the navigation reads
          as a structured taxonomy instead of one undifferentiated
          row. Each block carries its own header + subtle background. */}
      {(() => {
        const allTabs: { id: Tab; group: 'master_data' | 'sales' | 'operations'; label: string; icon: React.ElementType; tip: string }[] = [
          { id: 'overview',         group: 'master_data', label: t('propdev.overview',         { defaultValue: 'Overview' }),         icon: Home,           tip: t('propdev.tab.overview.tooltip',         { defaultValue: 'Portfolio KPIs and pipeline snapshot' }) },
          { id: 'developments',     group: 'master_data', label: t('propdev.developments',     { defaultValue: 'Developments' }),     icon: Building2,      tip: t('propdev.tab.developments.tooltip',     { defaultValue: 'Top-level real-estate projects' }) },
          { id: 'phases',           group: 'master_data', label: t('propdev.phases',           { defaultValue: 'Phases' }),           icon: Layers,         tip: t('propdev.tab.phases.tooltip',           { defaultValue: 'Construction & sales phases within a development' }) },
          { id: 'blocks',           group: 'master_data', label: t('propdev.blocks',           { defaultValue: 'Blocks' }),           icon: LayoutGrid,     tip: t('propdev.tab.blocks.tooltip',           { defaultValue: 'Building blocks / towers per phase' }) },
          { id: 'plots',            group: 'master_data', label: t('propdev.plots',            { defaultValue: 'Plots' }),            icon: MapPin,         tip: t('propdev.tab.plots.tooltip',            { defaultValue: 'Inventory of sellable units' }) },
          { id: 'house_types',      group: 'master_data', label: t('propdev.house_types',      { defaultValue: 'House Types' }),      icon: House,          tip: t('propdev.tab.house_types.tooltip',      { defaultValue: 'Reusable unit templates and variants' }) },
          { id: 'leads',            group: 'sales',       label: t('propdev.leads',            { defaultValue: 'Leads' }),            icon: UserPlus,       tip: t('propdev.tab.leads.tooltip',            { defaultValue: 'Inbound prospects before becoming buyers' }) },
          { id: 'buyers',           group: 'sales',       label: t('propdev.buyers',           { defaultValue: 'Buyers' }),           icon: Users,          tip: t('propdev.tab.buyers.tooltip',           { defaultValue: 'Qualified buyers and KYC records' }) },
          { id: 'reservations',     group: 'sales',       label: t('propdev.reservations',     { defaultValue: 'Reservations' }),     icon: BookmarkCheck,  tip: t('propdev.tab.reservations.tooltip',     { defaultValue: 'Unit holds and deposit reservations' }) },
          { id: 'spa',              group: 'sales',       label: t('propdev.spa',              { defaultValue: 'Sales Contracts' }),  icon: FileSignature,  tip: t('propdev.tab.spa.tooltip',              { defaultValue: 'Sale & Purchase Agreements (SPAs)' }) },
          { id: 'payment_schedule', group: 'sales',       label: t('propdev.payment_schedule', { defaultValue: 'Payment Schedules' }), icon: CalendarClock, tip: t('propdev.tab.payment_schedule.tooltip', { defaultValue: 'Milestone-based buyer installments' }) },
          { id: 'brokers',          group: 'operations',  label: t('propdev.brokers',          { defaultValue: 'Brokers' }),          icon: Briefcase,      tip: t('propdev.tab.brokers.tooltip',          { defaultValue: 'External agents and commission tracking' }) },
          { id: 'price_matrix',     group: 'operations',  label: t('propdev.price_matrix',     { defaultValue: 'Price Matrix' }),     icon: Grid3X3,        tip: t('propdev.tab.price_matrix.tooltip',     { defaultValue: 'Floor / view / orientation price factors' }) },
          { id: 'escrow',           group: 'operations',  label: t('propdev.escrow',           { defaultValue: 'Escrow' }),           icon: Lock,           tip: t('propdev.tab.escrow.tooltip',           { defaultValue: 'Trust accounts and released funds' }) },
          { id: 'handovers',        group: 'operations',  label: t('propdev.handovers',        { defaultValue: 'Handovers' }),        icon: Key,            tip: t('propdev.tab.handovers.tooltip',        { defaultValue: 'Unit handover events and snags' }) },
          { id: 'warranty',         group: 'operations',  label: t('propdev.warranty',         { defaultValue: 'Warranty Claims' }),  icon: ShieldAlert,    tip: t('propdev.tab.warranty.tooltip',         { defaultValue: 'Post-handover defect claims' }) },
        ];

        const groups: { id: 'master_data' | 'sales' | 'operations'; label: string; accent: string }[] = [
          { id: 'master_data', label: t('propdev.group.master_data', { defaultValue: 'Master data' }), accent: 'from-sky-50/60 to-transparent' },
          { id: 'sales',       label: t('propdev.group.sales',       { defaultValue: 'Sales' }),       accent: 'from-emerald-50/60 to-transparent' },
          { id: 'operations',  label: t('propdev.group.operations',  { defaultValue: 'Operations' }),  accent: 'from-amber-50/60 to-transparent' },
        ];

        return (
          <div
            className="grid gap-3 lg:grid-cols-3"
            data-testid="propdev-tour-tabs"
            aria-label={t('propdev.tabs_aria', { defaultValue: 'Property development sections' })}
          >
            {groups.map((g) => {
              const tabsInGroup = allTabs.filter((x) => x.group === g.id);
              return (
                <section
                  key={g.id}
                  className={clsx(
                    'rounded-xl border border-border-light bg-gradient-to-br',
                    g.accent,
                    'backdrop-blur-sm px-3 pt-2 pb-3',
                  )}
                  aria-labelledby={`propdev-group-${g.id}`}
                >
                  <h3
                    id={`propdev-group-${g.id}`}
                    className="px-1 pb-1.5 text-2xs font-semibold uppercase tracking-[0.08em] text-content-tertiary"
                  >
                    {g.label}
                  </h3>
                  <nav
                    className="flex flex-wrap items-stretch gap-1.5"
                    role="tablist"
                    aria-label={g.label}
                    onKeyDown={onTabKeyDown}
                  >
                    {tabsInGroup.map((tabItem) => {
                      const Icon = tabItem.icon;
                      const active = tab === tabItem.id;
                      return (
                        <button
                          key={tabItem.id}
                          type="button"
                          role="tab"
                          aria-selected={active}
                          aria-label={tabItem.label}
                          aria-controls={`propdev-panel-${tabItem.id}`}
                          id={`propdev-tab-${tabItem.id}`}
                          tabIndex={active ? 0 : -1}
                          title={`${tabItem.label} - ${tabItem.tip}`}
                          onClick={() => {
                            setTab(tabItem.id);
                            setSearch('');
                          }}
                          data-testid={
                            tabItem.id === 'house_types'
                              ? 'propdev-tour-house-types-tab'
                              : tabItem.id === 'handovers'
                                ? 'propdev-tour-handovers-tab'
                                : tabItem.id === 'leads'
                                  ? 'propdev-tour-leads-tab'
                                  : undefined
                          }
                          className={clsx(
                            'group relative flex flex-col items-center justify-center gap-1',
                            'h-[64px] w-[64px] md:h-[68px] md:w-[72px]',
                            'rounded-xl border text-center transition-all duration-150',
                            'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60 focus-visible:ring-offset-1',
                            active
                              ? 'border-oe-blue bg-oe-blue text-white shadow-sm shadow-oe-blue/30'
                              : 'border-transparent bg-white/60 text-content-secondary hover:bg-white hover:text-content-primary hover:border-border-light hover:-translate-y-px',
                          )}
                        >
                          <Icon
                            size={20}
                            className={clsx(
                              'transition-colors',
                              active ? 'text-white' : 'text-content-secondary group-hover:text-oe-blue',
                            )}
                            aria-hidden="true"
                          />
                          <span
                            className={clsx(
                              'text-[10px] leading-tight font-medium line-clamp-2 px-1',
                              active ? 'text-white' : 'text-content-secondary group-hover:text-content-primary',
                            )}
                          >
                            {tabItem.label}
                          </span>
                        </button>
                      );
                    })}
                  </nav>
                </section>
              );
            })}
          </div>
        );
      })()}

      {/* Filters */}
      {tab !== 'developments' && tab !== 'overview' && tab !== 'brokers' && developments.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={selectedDevId}
            onChange={(e) => setSelectedDevId(e.target.value)}
            className={clsx(inputCls, 'max-w-[320px]')}
          >
            {developments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.code} — {d.name || t('propdev.untitled', { defaultValue: 'Untitled' })}
              </option>
            ))}
          </select>
          {tab === 'buyers' && (
            <div className="relative flex-1 min-w-[200px] max-w-md">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                type="text"
                placeholder={t('common.search', { defaultValue: 'Search…' })}
                aria-label={t('common.search', { defaultValue: 'Search' })}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className={clsx(inputCls, 'pl-8')}
              />
            </div>
          )}
          {selectedDevId && (
            <button
              type="button"
              onClick={() =>
                // Pass the development id on the query string in addition to
                // the path param so deep-links surviving redirects (e.g. via
                // the global Geo Hub) can still resolve the focus context.
                navigate(
                  `/property-dev/developments/${selectedDevId}/geo?development=${encodeURIComponent(selectedDevId)}`,
                )
              }
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
              title={t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
              aria-label={t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
              data-testid="propdev-view-on-map"
            >
              <Globe2 size={13} />
              {t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
            </button>
          )}
          {selectedDevId && (
            <Link
              to={`/property-dev/developments/${selectedDevId}/inventory-map`}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
              title={t('propdev.inventory_map.cta', {
                defaultValue: 'Inventory Map',
              })}
              aria-label={t('propdev.inventory_map.cta', {
                defaultValue: 'Inventory Map',
              })}
              data-testid="propdev-inventory-map-link"
            >
              <LayoutGrid size={13} />
              {t('propdev.inventory_map.cta', {
                defaultValue: 'Inventory Map',
              })}
            </Link>
          )}
        </div>
      )}

      {/* Body */}
      <div
        role="tabpanel"
        id={`propdev-panel-${tab}`}
        aria-labelledby={`propdev-tab-${tab}`}
      >
      {isLoading ? (
        <Card padding="md"><SkeletonTable rows={6} columns={4} /></Card>
      ) : loadError ? (
        <Card padding="md">
          <EmptyState
            icon={<AlertOctagon size={22} />}
            title={t('propdev.load_error', {
              defaultValue: 'Could not load property data',
            })}
            description={getErrorMessage(loadError)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => {
                developmentsQ.refetch();
                activeQuery.refetch();
              },
            }}
          />
        </Card>
      ) : tab === 'overview' ? (
        <OverviewTab
          developments={developments}
          onJumpToDevelopment={(id) => {
            setSelectedDevId(id);
            setTab('plots');
          }}
          onJumpTo={(target, filter) => {
            setTab(target);
            // Tile presets — for warranty/handovers we want the click
            // to land the user on the right tab AND pre-narrow the
            // filter so "Open warranty (3)" actually shows 3 rows.
            if (target === 'warranty' && filter?.warrantyStatus) {
              setWarrantyStatusPreset(filter.warrantyStatus);
            } else {
              setWarrantyStatusPreset('');
            }
          }}
          onCreate={() => {
            setTab('developments');
            setCreateOpen(true);
          }}
        />
      ) : tab === 'developments' ? (
        <DevelopmentsGrid
          rows={developments}
          onSelect={(id) => {
            setSelectedDevId(id);
            setTab('plots');
          }}
          onCreate={() => setCreateOpen(true)}
        />
      ) : tab === 'plots' ? (
        <PlotsTab
          plots={allPlots}
          houseTypes={houseTypesQ.data ?? []}
          onSelect={(id) => setActivePlotId(id)}
          onCreate={() => setCreateOpen(true)}
        />
      ) : tab === 'house_types' ? (
        <HouseTypesTab
          rows={houseTypesQ.data ?? []}
          onCreate={() => setCreateOpen(true)}
        />
      ) : tab === 'leads' ? (
        <LeadsTab
          rows={allLeads}
          onSelect={(id) => setActiveLeadId(id)}
          onCreate={() => setCreateOpen(true)}
          onConvert={(lead) => setConvertingLead(lead)}
        />
      ) : tab === 'buyers' ? (
        <BuyersTab
          rows={filteredBuyers}
          plots={allPlots}
          onSelect={(id) => setActiveBuyerId(id)}
          onCreate={() => setCreateOpen(true)}
        />
      ) : tab === 'phases' ? (
        <PhasesTab developmentId={selectedDevId} onJumpToBlocks={() => setTab('blocks')} />
      ) : tab === 'blocks' ? (
        <BlocksTab developmentId={selectedDevId} plots={allPlots} onJumpToPlots={() => setTab('plots')} />
      ) : tab === 'brokers' ? (
        <BrokersTab />
      ) : tab === 'reservations' ? (
        <ReservationsTab
          developmentId={selectedDevId}
          plots={allPlots}
          buyers={allBuyers}
        />
      ) : tab === 'spa' ? (
        <SpaTab
          developmentId={selectedDevId}
          plots={allPlots}
          onJumpToReservations={() => setTab('reservations')}
          onJumpToPaymentSchedules={() => setTab('payment_schedule')}
        />
      ) : tab === 'payment_schedule' ? (
        <PaymentScheduleTab
          developmentId={selectedDevId}
          plots={allPlots}
          onJumpToReservations={() => setTab('reservations')}
          onJumpToSpa={() => setTab('spa')}
        />
      ) : tab === 'price_matrix' ? (
        <PriceMatrixTab
          developmentId={selectedDevId}
          plots={allPlots}
          defaultCurrency={
            developments.find((d) => d.id === selectedDevId)?.currency
          }
        />
      ) : tab === 'escrow' ? (
        <EscrowTab
          developmentId={selectedDevId}
          defaultCurrency={
            developments.find((d) => d.id === selectedDevId)?.currency
          }
        />
      ) : tab === 'handovers' ? (
        <HandoversTab plots={allPlots} buyers={allBuyers} />
      ) : (
        <WarrantyTab
          buyers={allBuyers}
          plots={allPlots}
          developmentId={selectedDevId}
          initialStatus={warrantyStatusPreset}
          onConsumedPreset={() => setWarrantyStatusPreset('')}
        />
      )}
      </div>


      {/* Plot detail */}
      {activePlotId && (
        <PlotDetailDrawer
          plotId={activePlotId}
          plots={allPlots}
          houseTypes={houseTypesQ.data ?? []}
          onClose={() => setActivePlotId(null)}
        />
      )}

      {/* Buyer detail */}
      {activeBuyerId && (
        <BuyerDetailDrawer
          buyerId={activeBuyerId}
          buyers={allBuyers}
          plots={allPlots}
          developmentId={selectedDevId}
          onClose={() => setActiveBuyerId(null)}
        />
      )}

      {/* Lead detail */}
      {activeLeadId && (
        <LeadDetailDrawer
          leadId={activeLeadId}
          leads={allLeads}
          onClose={() => setActiveLeadId(null)}
          onConvert={(lead) => setConvertingLead(lead)}
        />
      )}

      {/* Convert lead → reservation modal. Opened from the Leads tab
          or the Lead detail drawer. The plot list comes from the
          currently-selected development so the picker is always
          relevant. */}
      {convertingLead && (
        <ConvertLeadModal
          lead={convertingLead}
          plots={allPlots}
          developmentId={selectedDevId}
          onClose={() => setConvertingLead(null)}
          onSuccess={() => {
            setConvertingLead(null);
            setActiveLeadId(null);
          }}
        />
      )}

      {/* Create modal */}
      {createOpen && (
        <CreateModal
          kind={tab}
          developmentId={selectedDevId}
          developments={developments}
          houseTypes={houseTypesQ.data ?? []}
          onClose={() => setCreateOpen(false)}
        />
      )}

      {/* PropDev guided walkthrough — the global <ProductTour /> mounted
       *  in App.tsx already listens for the `oe:start-tour` event with a
       *  `tourId: 'propdev'` detail. The Tour pill rendered by the
       *  ModuleHelpButton (next to the page title above) fires that event
       *  via `dispatchEvent`. Per-tour dismissal already persists via
       *  ``/api/v1/users/me/tour-state/`` so there is nothing to wire up
       *  here — the 7-step PROPDEV_TOUR_STEPS playlist is auto-resolved
       *  from the TOUR_REGISTRY. The auto-start behaviour stays scoped to
       *  the dashboard route only; on /property-dev the tour is purely
       *  opt-in. Leaving this comment as a breadcrumb for the next
       *  refactor — duplicating ProductTour here would double-render the
       *  spotlight overlay. */}
    </div>
  );
}

/* ─── Buyers tab ─── */

/**
 * Buyer table with a stage-summary chipbar on top. The chipbar
 * counts buyers by status so the user gets a funnel view at a
 * glance even before scrolling the table. Clicking a chip filters
 * the table to that stage; clicking again clears.
 *
 * The table also gained:
 *  - A ``Plot`` column (plot_id resolved against the plots list)
 *  - Sticky header for long lists
 *  - Aria-sort affordance on the freeze-deadline column (sorted by
 *    deadline asc when present — overdue first)
 *  - Empty-filter fallback when a chip filter zeroes the result
 */
function BuyersTab({
  rows,
  plots,
  onSelect,
  onCreate,
}: {
  rows: Buyer[];
  plots: Plot[];
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const [stageFilter, setStageFilter] = useState<BuyerStatus | null>(null);
  const plotMap = useMemo(
    () => new Map(plots.map((p) => [p.id, p])),
    [plots],
  );
  const summary = useMemo(() => {
    const out: Record<BuyerStatus, number> = {
      lead: 0,
      reserved: 0,
      contracted: 0,
      completed: 0,
      cancelled: 0,
    };
    for (const b of rows) out[b.status] = (out[b.status] ?? 0) + 1;
    return out;
  }, [rows]);
  const filteredRows = useMemo(() => {
    const filtered = stageFilter
      ? rows.filter((r) => r.status === stageFilter)
      : rows;
    // Sort: rows with a freeze deadline come first (closest deadline
    // → most urgent), then everything else by newest contract or
    // creation date. Stable so identical timestamps preserve order.
    return [...filtered].sort((a, b) => {
      const aFd = a.freeze_deadline ? new Date(a.freeze_deadline).getTime() : Infinity;
      const bFd = b.freeze_deadline ? new Date(b.freeze_deadline).getTime() : Infinity;
      return aFd - bFd;
    });
  }, [rows, stageFilter]);

  if (rows.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Users size={22} />}
          title={t('propdev.empty_buyers', { defaultValue: 'No buyers yet' })}
          description={t('propdev.empty_buyers_desc', {
            defaultValue:
              'Register leads, track contracts and configure buyer selections.',
          })}
          action={{
            label: t('propdev.new_buyer', { defaultValue: 'New Buyer' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {/* Stage funnel chipbar — clicking toggles the filter. */}
      <div
        className="flex flex-wrap items-center gap-2"
        role="toolbar"
        aria-label={t('propdev.stage_filter', {
          defaultValue: 'Filter buyers by stage',
        })}
      >
        {(BUYER_STAGE_ORDER as BuyerStatus[]).map((s) => {
          const active = stageFilter === s;
          const count = summary[s] ?? 0;
          return (
            <button
              key={s}
              type="button"
              onClick={() => setStageFilter(active ? null : s)}
              aria-pressed={active}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                'focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
                active
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue hover:text-oe-blue',
              )}
            >
              <Badge variant={BUYER_VARIANT[s]} dot>
                {t(`propdev.stage_${s}`, {
                  defaultValue: s.charAt(0).toUpperCase() + s.slice(1),
                })}
              </Badge>
              <span className="font-mono tabular-nums text-content-tertiary">
                {count}
              </span>
            </button>
          );
        })}
        {stageFilter != null && (
          <button
            type="button"
            onClick={() => setStageFilter(null)}
            className="text-xs text-content-tertiary hover:text-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/40 rounded"
          >
            {t('common.clear', { defaultValue: 'Clear' })}
          </button>
        )}
      </div>

      <Card padding="none">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide sticky top-0">
              <tr>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.buyer', { defaultValue: 'Buyer' })}
                </th>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.email', { defaultValue: 'Email' })}
                </th>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.plot', { defaultValue: 'Plot' })}
                </th>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.stage', { defaultValue: 'Stage' })}
                </th>
                <th className="px-4 py-2.5 text-right">
                  {t('propdev.contract_value', { defaultValue: 'Contract' })}
                </th>
                <th
                  className="px-4 py-2.5 text-left"
                  aria-sort="ascending"
                >
                  {t('propdev.freeze_deadline', { defaultValue: 'Freeze' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-8 text-center text-sm text-content-tertiary"
                  >
                    {t('propdev.no_buyers_for_stage', {
                      defaultValue: 'No buyers in this stage.',
                    })}
                  </td>
                </tr>
              ) : (
                filteredRows.map((b) => {
                  const days = daysUntil(b.freeze_deadline);
                  const plot = b.plot_id ? plotMap.get(b.plot_id) : null;
                  return (
                    <tr
                      key={b.id}
                      onClick={() => onSelect(b.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          onSelect(b.id);
                        }
                      }}
                      tabIndex={0}
                      role="button"
                      aria-label={t('propdev.open_buyer_aria', {
                        defaultValue: 'Open buyer {{name}}',
                        name: b.full_name || b.email || b.id,
                      })}
                      className="border-t border-border-light hover:bg-surface-secondary cursor-pointer focus:bg-surface-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue/40"
                    >
                      <td className="px-4 py-2 font-medium">
                        <span className="inline-flex items-center gap-1.5">
                          {b.full_name || '—'}
                          {b.contact_id && (
                            <span
                              title={t('propdev.linked_contact_hint', {
                                defaultValue:
                                  'Linked to a Contacts directory entry',
                              })}
                              className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-oe-blue/10 text-oe-blue"
                              aria-label={t('propdev.linked_contact_aria', {
                                defaultValue: 'Linked to Contacts',
                              })}
                            >
                              <UserCircle2 size={11} aria-hidden="true" />
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs text-content-secondary">
                        {b.email}
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {plot ? (
                          <span className="inline-flex items-center gap-1 font-mono text-content-secondary">
                            {plot.plot_number}
                          </span>
                        ) : (
                          <span className="text-content-tertiary">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2">
                        <Badge variant={BUYER_VARIANT[b.status]} dot>
                          {t(`propdev.stage_${b.status}`, {
                            defaultValue:
                              b.status.charAt(0).toUpperCase() +
                              b.status.slice(1),
                          })}
                        </Badge>
                      </td>
                      <td className="px-4 py-2 text-right">
                        <MoneyDisplay
                          amount={toNumber(b.contract_value)}
                          currency={b.currency || undefined}
                        />
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {b.freeze_deadline ? (
                          <span
                            className={clsx(
                              'inline-flex items-center gap-1',
                              days != null && days < 7
                                ? 'text-rose-600 font-medium'
                                : 'text-content-secondary',
                            )}
                          >
                            <Clock size={11} aria-hidden="true" />
                            {days != null ? (
                              days > 0 ? (
                                t('propdev.in_days', {
                                  defaultValue: 'in {{n}}d',
                                  n: days,
                                })
                              ) : (
                                t('propdev.overdue_days', {
                                  defaultValue: '{{n}}d overdue',
                                  n: Math.abs(days),
                                })
                              )
                            ) : (
                              <DateDisplay value={b.freeze_deadline} />
                            )}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* ─── Leads tab ─────────────────────────────────────────────────────────
 *
 * Top-of-funnel inbound contacts. A Lead is created BEFORE we know which
 * plot they want — once a plot is identified the user clicks "Convert"
 * which materialises a Reservation (+ optional Buyer shadow). The
 * conversion is the gate that turns the Lead pipeline into the Buyer
 * pipeline; until it happens the lead never appears on the Buyers tab.
 *
 * FSM-allowed status transitions are enforced both client-side (only
 * legal next states are rendered in the dropdown) and server-side
 * (PATCH /leads/{id} returns 409 if the user races the dropdown).
 */

const LEAD_STAGE_ORDER: LeadStatus[] = [
  'new',
  'qualified',
  'viewing_scheduled',
  'visited',
  'quotation_sent',
  'negotiating',
  'converted',
  'lost',
  'disqualified',
];

const LEAD_VARIANT: Record<
  LeadStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  new: 'neutral',
  qualified: 'blue',
  viewing_scheduled: 'blue',
  visited: 'blue',
  quotation_sent: 'warning',
  negotiating: 'warning',
  converted: 'success',
  lost: 'error',
  disqualified: 'error',
};

const LEAD_SOURCES: LeadSource[] = [
  'web_form',
  'walk_in',
  'broker',
  'referral',
  'portal',
  'other',
];

function leadStatusLabel(
  s: LeadStatus,
  t: (k: string, o?: Record<string, unknown>) => string,
): string {
  return t(`propdev.lead_status_${s}`, {
    defaultValue: s
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' '),
  });
}

function LeadsTab({
  rows,
  onSelect,
  onCreate,
  onConvert,
}: {
  rows: Lead[];
  onSelect: (id: string) => void;
  onCreate: () => void;
  onConvert: (lead: Lead) => void;
}) {
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState<LeadStatus | null>(null);
  const [sourceFilter, setSourceFilter] = useState<LeadSource | null>(null);

  const summary = useMemo(() => {
    const out: Record<string, number> = {};
    for (const r of rows) out[r.status] = (out[r.status] ?? 0) + 1;
    return out;
  }, [rows]);

  const filteredRows = useMemo(() => {
    let out = rows;
    if (statusFilter) out = out.filter((r) => r.status === statusFilter);
    if (sourceFilter) out = out.filter((r) => r.source === sourceFilter);
    // Newest first — leads are inbound so chronological recency is the
    // most useful default sort.
    return [...out].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
  }, [rows, statusFilter, sourceFilter]);

  if (rows.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<UserPlus size={22} />}
          title={t('propdev.empty_leads', { defaultValue: 'No leads yet' })}
          description={t('propdev.empty_leads_desc', {
            defaultValue:
              'Leads are inbound contacts at the top of the sales funnel. Once a lead picks a plot, convert them into a reservation.',
          })}
          action={{
            label: t('propdev.new_lead', { defaultValue: 'New Lead' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {/* Status funnel chipbar. Clicking toggles the filter. */}
      <div
        className="flex flex-wrap items-center gap-2"
        role="toolbar"
        aria-label={t('propdev.lead_stage_filter', {
          defaultValue: 'Filter leads by status',
        })}
      >
        {LEAD_STAGE_ORDER.map((s) => {
          const active = statusFilter === s;
          const count = summary[s] ?? 0;
          if (count === 0 && !active) return null;
          return (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(active ? null : s)}
              aria-pressed={active}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                'focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
                active
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue hover:text-oe-blue',
              )}
            >
              <Badge variant={LEAD_VARIANT[s]} dot>
                {leadStatusLabel(s, t)}
              </Badge>
              <span className="font-mono tabular-nums text-content-tertiary">
                {count}
              </span>
            </button>
          );
        })}
        {(statusFilter != null || sourceFilter != null) && (
          <button
            type="button"
            onClick={() => {
              setStatusFilter(null);
              setSourceFilter(null);
            }}
            className="text-xs text-content-tertiary hover:text-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/40 rounded"
          >
            {t('common.clear', { defaultValue: 'Clear' })}
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Filter size={12} className="text-content-tertiary" />
          <select
            value={sourceFilter ?? ''}
            onChange={(e) =>
              setSourceFilter(
                e.target.value ? (e.target.value as LeadSource) : null,
              )
            }
            className={clsx(inputCls, 'h-7 py-0 text-xs w-auto')}
          >
            <option value="">
              {t('propdev.all_sources', { defaultValue: 'All sources' })}
            </option>
            {LEAD_SOURCES.map((src) => (
              <option key={src} value={src}>
                {t(`propdev.lead_source_${src}`, {
                  defaultValue: src.replace('_', ' '),
                })}
              </option>
            ))}
          </select>
        </div>
      </div>

      <Card padding="none">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide sticky top-0">
              <tr>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.lead_name', { defaultValue: 'Lead' })}
                </th>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.email', { defaultValue: 'Email' })}
                </th>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.lead_source', { defaultValue: 'Source' })}
                </th>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.lead_score', { defaultValue: 'Score' })}
                </th>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.status', { defaultValue: 'Status' })}
                </th>
                <th className="px-4 py-2.5 text-right">
                  {t('propdev.actions', { defaultValue: 'Actions' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-8 text-center text-sm text-content-tertiary"
                  >
                    {t('propdev.no_leads_for_filter', {
                      defaultValue: 'No leads match the current filter.',
                    })}
                  </td>
                </tr>
              ) : (
                filteredRows.map((l) => {
                  const convertible =
                    l.status !== 'converted' &&
                    l.status !== 'lost' &&
                    l.status !== 'disqualified';
                  return (
                    <tr
                      key={l.id}
                      onClick={() => onSelect(l.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          onSelect(l.id);
                        }
                      }}
                      tabIndex={0}
                      role="button"
                      aria-label={t('propdev.open_lead_aria', {
                        defaultValue: 'Open lead {{name}}',
                        name: l.full_name || l.email || l.id,
                      })}
                      className="border-t border-border-light hover:bg-surface-secondary cursor-pointer focus:bg-surface-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue/40"
                    >
                      <td className="px-4 py-2 font-medium">
                        <span className="inline-flex items-center gap-1.5">
                          {l.full_name || '—'}
                          {l.contact_id && (
                            <span
                              title={t('propdev.linked_contact_hint', {
                                defaultValue:
                                  'Linked to a Contacts directory entry',
                              })}
                              className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-oe-blue/10 text-oe-blue"
                              aria-label={t('propdev.linked_contact_aria', {
                                defaultValue: 'Linked to Contacts',
                              })}
                            >
                              <UserCircle2 size={11} aria-hidden="true" />
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs text-content-secondary">
                        {l.email || '—'}
                      </td>
                      <td className="px-4 py-2 text-xs text-content-secondary">
                        {t(`propdev.lead_source_${l.source}`, {
                          defaultValue: l.source.replace('_', ' '),
                        })}
                      </td>
                      <td className="px-4 py-2 text-xs font-mono tabular-nums">
                        {toNumber(l.lead_score).toFixed(0)}
                      </td>
                      <td className="px-4 py-2">
                        <Badge variant={LEAD_VARIANT[l.status]} dot>
                          {leadStatusLabel(l.status, t)}
                        </Badge>
                      </td>
                      <td className="px-4 py-2 text-right">
                        {convertible && (
                          <button
                            type="button"
                            onClick={(e) => {
                              // Don't bubble into the row click handler;
                              // the convert action is independent of the
                              // detail-drawer open.
                              e.stopPropagation();
                              onConvert(l);
                            }}
                            className="inline-flex items-center gap-1 rounded-md border border-oe-blue/40 bg-oe-blue/5 px-2 py-1 text-xs font-medium text-oe-blue hover:bg-oe-blue/10 focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                            data-testid="convert-lead-btn"
                            title={t('propdev.convert_lead_hint', {
                              defaultValue:
                                'Convert lead into a reservation on a chosen plot',
                            })}
                          >
                            <ArrowRightCircle size={12} />
                            {t('propdev.convert', {
                              defaultValue: 'Convert',
                            })}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* ─── Lead detail drawer ────────────────────────────────────────────────
 *
 * Inline edit of source / status / score / notes plus a destructive
 * delete (confirm-gated). Status dropdown is FSM-aware: only valid next
 * states are shown. Convert button is duplicated here so the user can
 * convert without leaving the drawer (handy when they're reading notes
 * before deciding).
 */

function LeadDetailDrawer({
  leadId,
  leads,
  onClose,
  onConvert,
}: {
  leadId: string;
  leads: Lead[];
  onClose: () => void;
  onConvert: (lead: Lead) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const canEdit = useMemo(() => {
    if (!userRole) return false;
    const normalized = userRole.toLowerCase();
    return ['admin', 'superuser', 'owner', 'manager', 'editor'].includes(
      normalized,
    );
  }, [userRole]);
  const canDelete = useMemo(() => {
    if (!userRole) return false;
    const normalized = userRole.toLowerCase();
    return ['admin', 'superuser', 'owner', 'manager'].includes(normalized);
  }, [userRole]);

  const leadFromList = leads.find((l) => l.id === leadId);
  // Deep links (e.g. /property-dev?tab=leads&leadId=… from a Contact's
  // linked-records list) may target a lead that is filtered out of the
  // currently-loaded development-scoped list. Fall back to a by-id fetch so
  // the drawer still opens on the exact record. Leads are not strictly
  // development-bound, so this is safe.
  const leadFetch = useQuery({
    queryKey: ['propdev', 'lead', leadId],
    queryFn: () => getLead(leadId),
    enabled: !leadFromList && !!leadId,
    retry: false,
  });
  const lead = leadFromList ?? leadFetch.data;
  const [form, setForm] = useState<{
    full_name: string;
    email: string;
    phone: string;
    source: LeadSource;
    status: LeadStatus;
    lead_score: string;
    notes: string;
  } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Initialise the form whenever a different lead is opened. We
  // intentionally don't reset on every props change — that would clobber
  // unsaved edits while the user is typing.
  useEffect(() => {
    if (lead) {
      setForm({
        full_name: lead.full_name ?? '',
        email: lead.email ?? '',
        phone: lead.phone ?? '',
        source: lead.source,
        status: lead.status,
        lead_score: String(toNumber(lead.lead_score)),
        notes: lead.notes ?? '',
      });
    } else {
      setForm(null);
    }
  }, [leadId, lead]);

  const updateMut = useMutation({
    mutationFn: () => {
      if (!form || !lead) throw new Error('No form state');
      return updateLead(lead.id, {
        full_name: form.full_name !== (lead.full_name ?? '') ? form.full_name : undefined,
        email: form.email !== (lead.email ?? '') ? form.email : undefined,
        phone: form.phone !== (lead.phone ?? '') ? form.phone || null : undefined,
        source: form.source !== lead.source ? form.source : undefined,
        status: form.status !== lead.status ? form.status : undefined,
        lead_score:
          Number(form.lead_score) !== toNumber(lead.lead_score)
            ? form.lead_score
            : undefined,
        notes: form.notes !== (lead.notes ?? '') ? form.notes : undefined,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'leads'] });
      addToast({
        type: 'success',
        title: t('propdev.lead_saved', { defaultValue: 'Lead saved' }),
      });
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteLead(leadId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'leads'] });
      addToast({
        type: 'success',
        title: t('propdev.lead_deleted', { defaultValue: 'Lead deleted' }),
      });
      setConfirmDelete(false);
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!lead || !form) {
    return (
      <SideDrawer
        open={!!lead}
        onClose={onClose}
        widthClass="max-w-xl"
        title=""
      >
        <div />
      </SideDrawer>
    );
  }

  const statusOptions: LeadStatus[] = Array.from(
    new Set<LeadStatus>([
      lead.status,
      ...(allowedLeadTransitions[lead.status] ?? []),
    ]),
  );

  const convertible =
    lead.status !== 'converted' &&
    lead.status !== 'lost' &&
    lead.status !== 'disqualified';

  const headerActions = (
    <div className="flex items-center gap-1">
      {convertible && (
        <button
          type="button"
          onClick={() => onConvert(lead)}
          className="inline-flex items-center gap-1 rounded-md border border-oe-blue/40 bg-oe-blue/5 px-2 py-1 text-xs font-medium text-oe-blue hover:bg-oe-blue/10"
          data-testid="drawer-convert-lead-btn"
        >
          <ArrowRightCircle size={12} />
          {t('propdev.convert', { defaultValue: 'Convert' })}
        </button>
      )}
      {canDelete && (
        <button
          type="button"
          onClick={() => setConfirmDelete(true)}
          className="inline-flex items-center gap-1 rounded-md border border-rose-200 px-2 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50"
          data-testid="delete-lead-btn"
        >
          <Trash2 size={12} />
          {t('common.delete', { defaultValue: 'Delete' })}
        </button>
      )}
    </div>
  );

  return (
    <SideDrawer
      open
      onClose={onClose}
      widthClass="max-w-xl"
      busy={confirmDelete}
      title={lead.full_name || lead.email || t('propdev.lead', { defaultValue: 'Lead' })}
      subtitle={lead.email}
      headerActions={headerActions}
    >
      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => deleteMut.mutate()}
        loading={deleteMut.isPending}
        variant="danger"
        title={t('propdev.delete_lead_title', { defaultValue: 'Delete lead?' })}
        message={t('propdev.delete_lead_msg', {
          defaultValue:
            'This permanently removes the lead. Any reservations or buyers materialised from it stay intact.',
        })}
      />
      <div className="space-y-4 p-5">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className={labelCls}>
              {t('propdev.full_name', { defaultValue: 'Full name' })}
            </span>
            <input
              className={inputCls}
              value={form.full_name}
              disabled={!canEdit}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>
              {t('propdev.email', { defaultValue: 'Email' })}
            </span>
            <input
              type="email"
              className={inputCls}
              value={form.email}
              disabled={!canEdit}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>
              {t('propdev.phone', { defaultValue: 'Phone' })}
            </span>
            <input
              className={inputCls}
              value={form.phone}
              disabled={!canEdit}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>
              {t('propdev.lead_source', { defaultValue: 'Source' })}
            </span>
            <select
              className={inputCls}
              value={form.source}
              disabled={!canEdit}
              onChange={(e) =>
                setForm({ ...form, source: e.target.value as LeadSource })
              }
            >
              {LEAD_SOURCES.map((src) => (
                <option key={src} value={src}>
                  {t(`propdev.lead_source_${src}`, {
                    defaultValue: src.replace('_', ' '),
                  })}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>
              {t('propdev.lead_score', { defaultValue: 'Score (0-100)' })}
            </span>
            <input
              type="number"
              min={0}
              max={100}
              className={inputCls}
              value={form.lead_score}
              disabled={!canEdit}
              onChange={(e) =>
                setForm({ ...form, lead_score: e.target.value })
              }
              title={t('propdev.lead_score_hint', {
                defaultValue:
                  'Your qualification confidence - 0 = cold, 50 = warm, 100 = hot. Drives the Leads list sort order.',
              })}
            />
            <span className="mt-0.5 text-2xs text-content-tertiary">
              {t('propdev.lead_score_hint_short', {
                defaultValue: '0 = cold · 50 = warm · 100 = hot',
              })}
            </span>
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>
              {t('propdev.status', { defaultValue: 'Status' })}
            </span>
            <select
              className={inputCls}
              value={form.status}
              disabled={!canEdit}
              onChange={(e) =>
                setForm({ ...form, status: e.target.value as LeadStatus })
              }
            >
              {statusOptions.map((s) => (
                <option key={s} value={s}>
                  {leadStatusLabel(s, t)}
                  {s === lead.status
                    ? ` (${t('propdev.current', { defaultValue: 'current' })})`
                    : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>
            {t('propdev.notes', { defaultValue: 'Notes' })}
          </span>
          <textarea
            rows={4}
            className={clsx(inputCls, 'h-auto py-2')}
            value={form.notes}
            disabled={!canEdit}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </label>

        {canEdit && (
          <div className="flex justify-end">
            <Button
              variant="primary"
              icon={updateMut.isPending ? <Loader2 size={14} /> : <Check size={14} />}
              loading={updateMut.isPending}
              onClick={() => updateMut.mutate()}
              data-testid="save-lead-btn"
            >
              {t('common.save', { defaultValue: 'Save changes' })}
            </Button>
          </div>
        )}

        {lead.converted_to_buyer_id && (
          <Card padding="sm">
            <p className="text-xs text-content-secondary">
              {t('propdev.lead_already_converted', {
                defaultValue:
                  'This lead has already been converted to a buyer.',
              })}
            </p>
          </Card>
        )}

        <LinkedContactCard
          contactId={lead.contact_id ?? null}
          fallbackName={lead.full_name || lead.email}
        />
      </div>
    </SideDrawer>
  );
}

/* ─── Linked Contact card ──────────────────────────────────────────
 *
 * Shared between Lead + Buyer detail drawers. When the row carries a
 * ``contact_id`` we surface a small card with the canonical contact
 * label + module tags + a direct "Open in Contacts" link. When
 * ``contact_id`` is null we hide the card entirely (legacy rows or
 * portal-anonymous buyers).
 *
 * The contact data is fetched lazily — the drawer renders fine
 * without the bridge data; the card only lights up once the fetch
 * completes. A 404 (contact deleted) is treated as "no link" and the
 * card hides itself.
 */
function LinkedContactCard({
  contactId,
  fallbackName,
}: {
  contactId: string | null;
  fallbackName: string;
}) {
  const { t } = useTranslation();
  // Lazy-import the contacts API to avoid a hard module-load coupling
  // when the contacts feature isn't bundled.
  const contactQuery = useQuery({
    queryKey: ['contact-bridge', contactId],
    enabled: !!contactId,
    queryFn: async () => {
      const { apiGet } = await import('@/shared/lib/api');
      return apiGet<{
        id: string;
        contact_type: string;
        first_name: string | null;
        last_name: string | null;
        company_name: string | null;
        primary_email: string | null;
        primary_phone: string | null;
        country_code: string | null;
        module_tags: string[];
      }>(`/v1/contacts/${contactId}`);
    },
    retry: false,
    staleTime: 30_000,
  });

  if (!contactId) return null;

  const contact = contactQuery.data;
  const displayName = contact
    ? [contact.first_name, contact.last_name].filter(Boolean).join(' ') ||
      contact.company_name ||
      contact.primary_email ||
      fallbackName
    : fallbackName;

  return (
    <Card padding="sm">
      <div className="flex items-start gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue shrink-0">
          <UserCircle2 size={16} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
              {t('propdev.linked_contact', {
                defaultValue: 'Linked Contact',
              })}
            </span>
            <Link
              to={`/contacts?contactId=${encodeURIComponent(contactId)}`}
              className="ml-auto inline-flex items-center gap-1 text-xs text-oe-blue hover:underline"
            >
              {t('propdev.open_in_contacts', {
                defaultValue: 'Open in Contacts',
              })}
              <ArrowRight size={11} aria-hidden="true" />
            </Link>
          </div>
          <p className="text-sm font-medium truncate">{displayName}</p>
          {contact?.primary_email && (
            <p className="text-xs text-content-secondary truncate">
              {contact.primary_email}
            </p>
          )}
          {contact?.module_tags && contact.module_tags.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {contact.module_tags.map((tag) => (
                <Badge key={tag} size="sm" variant="neutral">
                  {t(`contacts.module_tag_${tag}`, {
                    defaultValue: tag.replace(/_/g, ' '),
                  })}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

/* ─── Convert Lead → Reservation modal ─────────────────────────────────
 *
 * Wires the frontend up to ``POST /property-dev/leads/{id}/convert-to-
 * reservation``. The backend creates a Reservation row, optionally
 * materialises a Buyer (default: yes), and flips the lead status to
 * 'converted'. On success we toast + refresh both lists; the parent
 * resets the activeLeadId so the drawer underneath the modal closes too.
 */

function ConvertLeadModal({
  lead,
  plots,
  developmentId,
  onClose,
  onSuccess,
}: {
  lead: Lead;
  plots: Plot[];
  developmentId: string;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const prefCurrency = usePreferencesStore((s) => s.currency);

  // Only show plots that are still convertible (not sold / handed_over /
  // already reserved by someone else). The backend re-checks at POST
  // time and returns 409 if a race makes our pick stale, but filtering
  // up front keeps the picker readable.
  const eligiblePlots = useMemo(
    () =>
      plots.filter(
        (p) =>
          p.development_id === developmentId &&
          (p.status === 'planned' || p.status === 'ready'),
      ),
    [plots, developmentId],
  );

  const [form, setForm] = useState({
    plot_id: eligiblePlots[0]?.id ?? '',
    deposit_amount: '0',
    currency: lead.currency || prefCurrency || 'EUR',
    cooling_off_days: '7',
    expires_at: todayIso(30),
    create_buyer: true,
  });

  const mut = useMutation({
    mutationFn: () =>
      convertLeadToReservation(lead.id, {
        plot_id: form.plot_id,
        deposit_amount: form.deposit_amount.trim() || '0',
        currency: form.currency,
        cooling_off_days: Number(form.cooling_off_days) || 0,
        expires_at: form.expires_at || undefined,
        create_buyer: form.create_buyer,
      }),
    onSuccess: () => {
      // Three different lists are dirty after a conversion: leads (the
      // source row flips to 'converted'), buyers (a fresh row was
      // materialised when create_buyer=true), and plots (the picked
      // plot moved to 'reserved'). Invalidate all three.
      qc.invalidateQueries({ queryKey: ['propdev', 'leads'] });
      qc.invalidateQueries({ queryKey: ['propdev', 'buyers'] });
      qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
      addToast({
        type: 'success',
        title: t('propdev.lead_converted', {
          defaultValue: 'Lead converted to reservation',
        }),
      });
      onSuccess();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const disabled =
    !form.plot_id ||
    mut.isPending ||
    !ISO_CURRENCY_RE.test(form.currency);

  return (
    <WideModal
      open
      onClose={() => !mut.isPending && onClose()}
      title={t('propdev.convert_lead_title', {
        defaultValue: 'Convert lead to reservation',
      })}
      subtitle={lead.full_name || lead.email}
      size="lg"
      busy={mut.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            icon={mut.isPending ? <Loader2 size={14} /> : <ArrowRightCircle size={14} />}
            loading={mut.isPending}
            onClick={() => mut.mutate()}
            disabled={disabled}
            data-testid="convert-lead-submit"
          >
            {t('propdev.convert', { defaultValue: 'Convert' })}
          </Button>
        </>
      }
    >
      {eligiblePlots.length === 0 ? (
        <EmptyState
          icon={<AlertOctagon size={22} />}
          title={t('propdev.no_eligible_plots', {
            defaultValue: 'No eligible plots',
          })}
          description={t('propdev.no_eligible_plots_desc', {
            defaultValue:
              'There are no planned or ready plots in this development. Add a plot first, then come back to convert this lead.',
          })}
        />
      ) : (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('propdev.plot', { defaultValue: 'Plot' })}
            required
            span={2}
          >
            <select
              className={inputCls}
              value={form.plot_id}
              onChange={(e) => setForm({ ...form, plot_id: e.target.value })}
              data-testid="convert-lead-plot"
            >
              {eligiblePlots.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.plot_number} — {p.status}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('propdev.deposit_amount', { defaultValue: 'Deposit amount' })}
            required
          >
            <input
              type="number"
              step="0.01"
              min="0"
              className={inputCls}
              value={form.deposit_amount}
              onChange={(e) =>
                setForm({ ...form, deposit_amount: e.target.value })
              }
              data-testid="convert-lead-deposit"
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.currency', { defaultValue: 'Currency (ISO)' })}
            required
            error={
              form.currency && !ISO_CURRENCY_RE.test(form.currency)
                ? t('propdev.currency_invalid', {
                    defaultValue: 'Currency must be a 3-letter ISO code (e.g. EUR)',
                  })
                : undefined
            }
          >
            <input
              className={
                form.currency && !ISO_CURRENCY_RE.test(form.currency)
                  ? inputErrCls
                  : inputCls
              }
              value={form.currency}
              maxLength={3}
              onChange={(e) =>
                setForm({
                  ...form,
                  currency: e.target.value
                    .toUpperCase()
                    .replace(/[^A-Z]/g, '')
                    .slice(0, 3),
                })
              }
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.cooling_off_days', {
              defaultValue: 'Cooling-off days',
            })}
            hint={t('propdev.cooling_off_hint', {
              defaultValue: 'Statutory rescission window (0-90).',
            })}
          >
            <input
              type="number"
              min={0}
              max={90}
              className={inputCls}
              value={form.cooling_off_days}
              onChange={(e) =>
                setForm({ ...form, cooling_off_days: e.target.value })
              }
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.expires_at', { defaultValue: 'Expires at' })}
            hint={t('propdev.expires_at_hint', {
              defaultValue:
                'Date the reservation auto-expires unless converted to SPA. Defaults to today + 30 days.',
            })}
          >
            <input
              type="date"
              className={inputCls}
              value={form.expires_at}
              onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.options', { defaultValue: 'Options' })}
            span={2}
          >
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.create_buyer}
                onChange={(e) =>
                  setForm({ ...form, create_buyer: e.target.checked })
                }
              />
              <span>
                {t('propdev.create_buyer_shadow', {
                  defaultValue:
                    'Also materialise a Buyer row (recommended - downstream modules need it).',
                })}
              </span>
            </label>
          </WideModalField>
        </WideModalSection>
      )}
    </WideModal>
  );
}

/* ─── Reservations / SPA / Payment-Schedule status helpers ─── */

const RESERVATION_VARIANT: Record<
  ReservationStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  active: 'warning',
  expired: 'neutral',
  converted: 'success',
  cancelled: 'error',
  refunded: 'neutral',
};

const SPA_VARIANT: Record<SpaStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  sent_for_signature: 'warning',
  partially_signed: 'warning',
  signed: 'blue',
  countersigned: 'success',
  registered: 'success',
  cancelled: 'error',
};

const SCHEDULE_VARIANT: Record<
  PaymentScheduleStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  active: 'blue',
  completed: 'success',
  suspended: 'warning',
  cancelled: 'error',
};

const INSTALMENT_VARIANT: Record<
  InstalmentStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  pending: 'neutral',
  due: 'warning',
  overdue: 'error',
  paid: 'success',
  waived: 'neutral',
  cancelled: 'error',
};

const RESERVATION_STATUS_OPTIONS: ReservationStatus[] = [
  'active',
  'expired',
  'converted',
  'cancelled',
  'refunded',
];

const SPA_STATUS_OPTIONS: SpaStatus[] = [
  'draft',
  'sent_for_signature',
  'partially_signed',
  'signed',
  'countersigned',
  'registered',
  'cancelled',
];

const SCHEDULE_STATUS_OPTIONS: PaymentScheduleStatus[] = [
  'active',
  'completed',
  'suspended',
  'cancelled',
];

/* ─── Reservations tab ─── */

function ReservationsTab({
  developmentId,
  plots,
  buyers,
}: {
  developmentId: string;
  plots: Plot[];
  buyers: Buyer[];
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [statusFilter, setStatusFilter] = useState<ReservationStatus | ''>('');
  const [createOpen, setCreateOpen] = useState(false);
  const [convertId, setConvertId] = useState<string | null>(null);
  const [docId, setDocId] = useState<string | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  // The global header CTA broadcasts ``propdev:new-sub-entity`` when the
  // user clicks "New Reservation" — pick it up and open the modal.
  useEffect(() => {
    const handler = (ev: Event) => {
      const detail = (ev as CustomEvent<{ tab?: string }>).detail;
      if (detail?.tab === 'reservations') setCreateOpen(true);
    };
    window.addEventListener('propdev:new-sub-entity', handler);
    return () => window.removeEventListener('propdev:new-sub-entity', handler);
  }, []);

  const q = useQuery({
    queryKey: ['propdev', 'reservations', developmentId, statusFilter],
    queryFn: () =>
      listReservations({
        development_id: developmentId,
        status: statusFilter || undefined,
        limit: 500,
      }),
    enabled: !!developmentId,
  });
  const rows = q.data ?? [];

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['propdev', 'reservations', developmentId] });
    qc.invalidateQueries({ queryKey: ['propdev', 'plots', developmentId] });
    qc.invalidateQueries({ queryKey: ['propdev', 'sales-contracts', developmentId] });
  };

  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelReservation(id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.reservation_cancelled', { defaultValue: 'Reservation cancelled' }) });
      invalidate();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const expireMut = useMutation({
    mutationFn: (id: string) => expireReservation(id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.reservation_expired', { defaultValue: 'Reservation expired' }) });
      invalidate();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!developmentId) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<BookmarkCheck size={22} />}
          title={t('propdev.no_dev_selected', { defaultValue: 'Select a development to view reservations' })}
        />
      </Card>
    );
  }

  if (q.isLoading) return <Card padding="md"><SkeletonTable rows={6} columns={5} /></Card>;
  if (q.isError)
    return (
      <Card padding="md">
        <EmptyState
          icon={<AlertOctagon size={22} />}
          title={t('propdev.load_error', { defaultValue: 'Could not load reservations' })}
          description={getErrorMessage(q.error)}
          action={{ label: t('common.retry', { defaultValue: 'Retry' }), onClick: () => q.refetch() }}
        />
      </Card>
    );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as ReservationStatus | '')}
          className={clsx(inputCls, 'max-w-[200px]')}
        >
          <option value="">{t('propdev.all_statuses', { defaultValue: 'All statuses' })}</option>
          {RESERVATION_STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <span className="text-xs text-content-tertiary">
          {t('propdev.n_rows', { defaultValue: '{{n}} rows', n: rows.length })}
        </span>
        <div className="ml-auto">
          <Button
            variant="primary"
            icon={<Plus size={14} />}
            onClick={() => setCreateOpen(true)}
          >
            {t('propdev.new_reservation', { defaultValue: 'New Reservation' })}
          </Button>
        </div>
      </div>

      {rows.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<BookmarkCheck size={22} />}
            title={t('propdev.no_reservations', { defaultValue: 'No reservations yet' })}
            description={t('propdev.no_reservations_desc', {
              defaultValue:
                'A reservation freezes a plot for a buyer with a deposit. Convert it to a Sales Contract when both parties are ready.',
            })}
            action={{
              label: t('propdev.new_reservation', { defaultValue: 'New Reservation' }),
              onClick: () => setCreateOpen(true),
            }}
          />
        </Card>
      ) : (
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-secondary">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">{t('propdev.reservation_number', { defaultValue: 'No.' })}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('propdev.plot', { defaultValue: 'Plot' })}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('propdev.buyer', { defaultValue: 'Buyer' })}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('propdev.deposit', { defaultValue: 'Deposit' })}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('propdev.expires_at', { defaultValue: 'Expires' })}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('common.status', { defaultValue: 'Status' })}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('common.actions', { defaultValue: 'Actions' })}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const plot = plots.find((p) => p.id === r.plot_id);
                  const buyer = r.buyer_id ? buyers.find((b) => b.id === r.buyer_id) : null;
                  const isActive = r.status === 'active';
                  return (
                    <tr key={r.id} className="border-t border-border-light">
                      <td className="px-3 py-2 font-mono text-xs">{r.reservation_number}</td>
                      <td className="px-3 py-2">{plot?.plot_number ?? '—'}</td>
                      <td className="px-3 py-2">{buyer?.full_name ?? buyer?.email ?? '—'}</td>
                      <td className="px-3 py-2 text-right">
                        <MoneyDisplay amount={toNumber(r.deposit_amount)} currency={r.currency || undefined} />
                      </td>
                      <td className="px-3 py-2">{r.expires_at ? <DateDisplay value={r.expires_at} /> : '—'}</td>
                      <td className="px-3 py-2">
                        <Badge variant={RESERVATION_VARIANT[r.status]} dot>{r.status}</Badge>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => setDocId(r.id)}
                            className="rounded p-1 text-content-secondary hover:bg-surface-secondary hover:text-oe-blue"
                            title={t('propdev.reservation_receipt', { defaultValue: 'Reservation receipt PDF' })}
                            aria-label={t('propdev.reservation_receipt', { defaultValue: 'Reservation receipt PDF' })}
                          >
                            <FileText size={14} />
                          </button>
                          {isActive && (
                            <>
                              <button
                                type="button"
                                onClick={() => setConvertId(r.id)}
                                className="inline-flex items-center gap-1 rounded border border-oe-blue/40 bg-oe-blue/5 px-2 py-1 text-[11px] font-medium text-oe-blue hover:bg-oe-blue/10"
                                title={t('propdev.convert_to_spa', { defaultValue: 'Convert to SPA' })}
                              >
                                <ArrowRightCircle size={12} />
                                {t('propdev.convert_to_spa', { defaultValue: 'Convert to SPA' })}
                              </button>
                              <button
                                type="button"
                                disabled={expireMut.isPending}
                                onClick={() => expireMut.mutate(r.id)}
                                className="rounded p-1 text-content-secondary hover:bg-amber-100 hover:text-amber-700"
                                title={t('propdev.expire', { defaultValue: 'Expire now' })}
                                aria-label={t('propdev.expire', { defaultValue: 'Expire now' })}
                              >
                                <Clock size={14} />
                              </button>
                              <button
                                type="button"
                                disabled={cancelMut.isPending}
                                onClick={async () => {
                                  const ok = await confirm({
                                    title: t('propdev.cancel_reservation_title', { defaultValue: 'Cancel reservation?' }),
                                    message: t('propdev.confirm_cancel_reservation', { defaultValue: 'Cancel this reservation? The plot will return to planned.' }),
                                    confirmLabel: t('propdev.cancel', { defaultValue: 'Cancel' }),
                                    cancelLabel: t('common.back', { defaultValue: 'Back' }),
                                    variant: 'danger',
                                  });
                                  if (!ok) return;
                                  cancelMut.mutate(r.id);
                                }}
                                className="rounded p-1 text-content-secondary hover:bg-rose-100 hover:text-rose-700"
                                title={t('propdev.cancel', { defaultValue: 'Cancel' })}
                                aria-label={t('propdev.cancel', { defaultValue: 'Cancel' })}
                              >
                                <XCircle size={14} />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {createOpen && (
        <CreateReservationModal
          developmentId={developmentId}
          plots={plots}
          buyers={buyers}
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            invalidate();
          }}
        />
      )}
      {convertId && (
        <ConvertReservationModal
          reservationId={convertId}
          reservation={rows.find((r) => r.id === convertId) ?? null}
          plots={plots}
          onClose={() => setConvertId(null)}
          onConverted={() => {
            setConvertId(null);
            invalidate();
            addToast({
              type: 'success',
              title: t('propdev.spa_created', { defaultValue: 'Sales Contract created' }),
            });
          }}
        />
      )}
      {docId && (
        <DocumentPreviewModal
          open
          onClose={() => setDocId(null)}
          docType="reservation_receipt"
          reservationId={docId}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

function CreateReservationModal({
  developmentId: _developmentId,
  plots,
  buyers,
  onClose,
  onCreated,
}: {
  developmentId: string;
  plots: Plot[];
  buyers: Buyer[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const prefCurrency = usePreferencesStore((s) => s.currency);
  const addToast = useToastStore((s) => s.addToast);
  const availablePlots = useMemo(
    () => plots.filter((p) => p.status === 'planned'),
    [plots],
  );
  const [form, setForm] = useState({
    plot_id: availablePlots[0]?.id ?? '',
    buyer_id: '',
    deposit_amount: '10000',
    currency: prefCurrency || 'EUR',
    cooling_off_days: '7',
    expires_at: todayIso(30),
  });
  const mut = useMutation({
    mutationFn: () =>
      createReservation({
        plot_id: form.plot_id,
        buyer_id: form.buyer_id || undefined,
        deposit_amount: form.deposit_amount,
        currency: form.currency.toUpperCase(),
        cooling_off_days: Number(form.cooling_off_days) || 0,
        expires_at: form.expires_at || undefined,
      }),
    onSuccess: () => {
      onCreated();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  return (
    <WideModal
      open
      onClose={onClose}
      title={t('propdev.new_reservation', { defaultValue: 'New Reservation' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button
            variant="primary"
            icon={mut.isPending ? <Loader2 size={14} /> : <Check size={14} />}
            loading={mut.isPending}
            disabled={!form.plot_id || !form.deposit_amount}
            onClick={() => mut.mutate()}
          >
            {t('propdev.reserve', { defaultValue: 'Reserve' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('propdev.plot', { defaultValue: 'Plot' })} required>
          <select
            value={form.plot_id}
            onChange={(e) => setForm({ ...form, plot_id: e.target.value })}
            className={inputCls}
          >
            {availablePlots.length === 0 && (
              <option value="" disabled>
                {t('propdev.no_planned_plots', { defaultValue: 'No planned plots available' })}
              </option>
            )}
            {availablePlots.map((p) => (
              <option key={p.id} value={p.id}>
                {p.plot_number} ({p.status})
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('propdev.buyer', { defaultValue: 'Buyer (optional)' })}>
          <select
            value={form.buyer_id}
            onChange={(e) => setForm({ ...form, buyer_id: e.target.value })}
            className={inputCls}
          >
            <option value="">{t('propdev.no_buyer', { defaultValue: 'No buyer yet' })}</option>
            {buyers.map((b) => (
              <option key={b.id} value={b.id}>{b.full_name || b.email}</option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('propdev.deposit_amount', { defaultValue: 'Deposit amount' })} required>
          <input
            type="number"
            min="0"
            step="0.01"
            value={form.deposit_amount}
            onChange={(e) => setForm({ ...form, deposit_amount: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('propdev.currency', { defaultValue: 'Currency' })} required>
          <input
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
            className={inputCls}
            maxLength={3}
          />
        </WideModalField>
        <WideModalField label={t('propdev.cooling_off_days', { defaultValue: 'Cooling-off days' })}>
          <input
            type="number"
            min="0"
            max="90"
            value={form.cooling_off_days}
            onChange={(e) => setForm({ ...form, cooling_off_days: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('propdev.freeze_until', { defaultValue: 'Freeze until' })}>
          <input
            type="date"
            value={form.expires_at}
            onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

function ConvertReservationModal({
  reservationId,
  reservation,
  plots,
  onClose,
  onConverted,
}: {
  reservationId: string;
  reservation: Reservation | null;
  plots: Plot[];
  onClose: () => void;
  onConverted: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const prefCurrency = usePreferencesStore((s) => s.currency);
  const plot = reservation ? plots.find((p) => p.id === reservation.plot_id) : null;
  const defaultValue = toNumber(plot?.price_base) || toNumber(reservation?.deposit_amount);
  const [form, setForm] = useState({
    signing_date: todayIso(),
    total_value: String(defaultValue || ''),
    currency: reservation?.currency || prefCurrency || 'EUR',
    governing_law: '',
    language: 'en',
  });
  const mut = useMutation({
    mutationFn: () =>
      convertReservationToSpa(reservationId, {
        signing_date: form.signing_date,
        total_value: form.total_value,
        currency: form.currency.toUpperCase(),
        governing_law: form.governing_law,
        language: form.language,
      }),
    onSuccess: () => onConverted(),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  return (
    <WideModal
      open
      onClose={onClose}
      title={t('propdev.convert_to_spa', { defaultValue: 'Convert to SPA' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button
            variant="primary"
            icon={mut.isPending ? <Loader2 size={14} /> : <ArrowRightCircle size={14} />}
            loading={mut.isPending}
            disabled={
              !form.total_value ||
              !form.signing_date ||
              !ISO_CURRENCY_RE.test(form.currency)
            }
            onClick={() => mut.mutate()}
          >
            {t('propdev.create_spa', { defaultValue: 'Create Sales Contract' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('propdev.signing_date', { defaultValue: 'Signing date' })} required>
          <input
            type="date"
            value={form.signing_date}
            onChange={(e) => setForm({ ...form, signing_date: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('propdev.total_value', { defaultValue: 'Total value' })} required>
          <input
            type="number"
            min="0"
            step="0.01"
            value={form.total_value}
            onChange={(e) => setForm({ ...form, total_value: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.currency', { defaultValue: 'Currency' })}
          required
          error={
            form.currency && !ISO_CURRENCY_RE.test(form.currency)
              ? t('propdev.currency_invalid', {
                  defaultValue: 'Currency must be a 3-letter ISO code (e.g. EUR)',
                })
              : undefined
          }
        >
          <input
            value={form.currency}
            onChange={(e) =>
              setForm({
                ...form,
                currency: e.target.value
                  .toUpperCase()
                  .replace(/[^A-Z]/g, '')
                  .slice(0, 3),
              })
            }
            className={
              form.currency && !ISO_CURRENCY_RE.test(form.currency)
                ? inputErrCls
                : inputCls
            }
            maxLength={3}
          />
        </WideModalField>
        <WideModalField label={t('propdev.governing_law', { defaultValue: 'Governing law (ISO 3166-2)' })}>
          <input
            value={form.governing_law}
            onChange={(e) => setForm({ ...form, governing_law: e.target.value.toUpperCase() })}
            className={inputCls}
            placeholder="DE-BE"
            maxLength={16}
          />
        </WideModalField>
        <WideModalField label={t('propdev.language', { defaultValue: 'Contract language' })}>
          <select
            value={form.language}
            onChange={(e) => setForm({ ...form, language: e.target.value })}
            className={inputCls}
          >
            {['en', 'de', 'ru', 'fr', 'es', 'ar'].map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── SPA (Sales Contracts) tab ─── */

function SpaTab({
  developmentId,
  plots,
  onJumpToReservations,
  onJumpToPaymentSchedules,
}: {
  developmentId: string;
  plots: Plot[];
  onJumpToReservations?: () => void;
  onJumpToPaymentSchedules?: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [statusFilter, setStatusFilter] = useState<SpaStatus | ''>('');
  const [activeSpaId, setActiveSpaId] = useState<string | null>(null);
  const [docId, setDocId] = useState<string | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  // Surface convertible reservations directly in the SPA tab so the user
  // is never stuck on a blank list with no actionable path. Previously the
  // empty state told them to "Start in the Reservations tab" but offered
  // no way to get there — the source of "Sales Contracts не работает".
  const reservationsQ = useQuery({
    queryKey: ['propdev', 'reservations', developmentId, 'active-for-spa'],
    queryFn: () =>
      listReservations({
        development_id: developmentId,
        status: 'active',
        limit: 100,
      }),
    enabled: !!developmentId,
  });
  const convertibleReservations = reservationsQ.data ?? [];
  const [convertReservationId, setConvertReservationId] = useState<string | null>(
    null,
  );

  const q = useQuery({
    queryKey: ['propdev', 'sales-contracts', developmentId, statusFilter],
    queryFn: () =>
      listSalesContracts({
        development_id: developmentId,
        status: statusFilter || undefined,
      }),
    enabled: !!developmentId,
  });
  const rows = q.data ?? [];

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['propdev', 'sales-contracts', developmentId] });
    qc.invalidateQueries({ queryKey: ['propdev', 'payment-schedules', developmentId] });
    qc.invalidateQueries({
      queryKey: ['propdev', 'reservations', developmentId],
    });
  };

  const sendMut = useMutation({
    mutationFn: (id: string) => sendSpaForSignature(id, {}),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.spa_sent', { defaultValue: 'Sent for signature' }) });
      invalidate();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const signMut = useMutation({
    mutationFn: (id: string) => signSalesContract(id, { signing_date: todayIso() }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.spa_signed_toast', { defaultValue: 'SPA signed' }) });
      invalidate();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const voidMut = useMutation({
    mutationFn: (id: string) => cancelSalesContract(id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.spa_voided', { defaultValue: 'SPA voided' }) });
      invalidate();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!developmentId) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<FileSignature size={22} />}
          title={t('propdev.no_dev_selected', { defaultValue: 'Select a development to view sales contracts' })}
        />
      </Card>
    );
  }

  if (q.isLoading) return <Card padding="md"><SkeletonTable rows={6} columns={5} /></Card>;
  if (q.isError)
    return (
      <Card padding="md">
        <EmptyState
          icon={<AlertOctagon size={22} />}
          title={t('propdev.load_error', { defaultValue: 'Could not load sales contracts' })}
          description={getErrorMessage(q.error)}
          action={{ label: t('common.retry', { defaultValue: 'Retry' }), onClick: () => q.refetch() }}
        />
      </Card>
    );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as SpaStatus | '')}
          className={clsx(inputCls, 'max-w-[220px]')}
        >
          <option value="">{t('propdev.all_statuses', { defaultValue: 'All statuses' })}</option>
          {SPA_STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <span className="text-xs text-content-tertiary">
          {t('propdev.n_rows', { defaultValue: '{{n}} rows', n: rows.length })}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {convertibleReservations.length > 0 && (
            <Button
              variant="primary"
              size="sm"
              icon={<ArrowRightCircle size={14} />}
              onClick={() => {
                const first = convertibleReservations[0];
                if (first) setConvertReservationId(first.id);
              }}
              title={t('propdev.convert_first_reservation', {
                defaultValue:
                  'Convert the most recent active reservation into a Sales Contract',
              })}
            >
              {t('propdev.convert_reservation_short', {
                defaultValue: 'Convert reservation ({{n}})',
                n: convertibleReservations.length,
              })}
            </Button>
          )}
          {onJumpToReservations && (
            <Button
              variant="ghost"
              size="sm"
              icon={<BookmarkCheck size={14} />}
              onClick={onJumpToReservations}
            >
              {t('propdev.go_to_reservations_short', {
                defaultValue: 'Reservations tab',
              })}
            </Button>
          )}
        </div>
      </div>

      {rows.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<FileSignature size={22} />}
            title={t('propdev.no_spas', { defaultValue: 'No sales contracts yet' })}
            description={
              convertibleReservations.length > 0
                ? t('propdev.no_spas_desc_with_reservations', {
                    defaultValue:
                      'There are {{n}} active reservations ready to be converted into a Sales Contract.',
                    n: convertibleReservations.length,
                  })
                : t('propdev.no_spas_desc', {
                    defaultValue:
                      'Sales contracts are created by converting an active Reservation. Create one in the Reservations tab first.',
                  })
            }
            action={
              convertibleReservations.length > 0
                ? {
                    label: t('propdev.convert_to_spa', {
                      defaultValue: 'Convert to SPA',
                    }),
                    onClick: () => {
                      const first = convertibleReservations[0];
                      if (first) setConvertReservationId(first.id);
                    },
                  }
                : onJumpToReservations
                  ? {
                      label: t('propdev.go_to_reservations_cta', {
                        defaultValue: 'Open Reservations tab',
                      }),
                      onClick: onJumpToReservations,
                    }
                  : undefined
            }
          />
        </Card>
      ) : (
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-secondary">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">{t('propdev.contract_number', { defaultValue: 'No.' })}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('propdev.plot', { defaultValue: 'Plot' })}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('propdev.signed', { defaultValue: 'Signed' })}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('propdev.total_value', { defaultValue: 'Total' })}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('common.status', { defaultValue: 'Status' })}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('common.actions', { defaultValue: 'Actions' })}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const plot = plots.find((p) => p.id === s.plot_id);
                  const canSend = s.status === 'draft';
                  const canSign = s.status === 'sent_for_signature' || s.status === 'partially_signed' || s.status === 'signed';
                  const canVoid = !['cancelled', 'registered'].includes(s.status);
                  return (
                    <tr
                      key={s.id}
                      className="border-t border-border-light cursor-pointer hover:bg-surface-secondary/30"
                      onClick={() => setActiveSpaId(s.id)}
                    >
                      <td className="px-3 py-2 font-mono text-xs">{s.contract_number}</td>
                      <td className="px-3 py-2">{plot?.plot_number ?? '—'}</td>
                      <td className="px-3 py-2">{s.signing_date ? <DateDisplay value={s.signing_date} /> : '—'}</td>
                      <td className="px-3 py-2 text-right">
                        <MoneyDisplay amount={toNumber(s.total_value)} currency={s.currency || undefined} />
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant={SPA_VARIANT[s.status]} dot>{s.status}</Badge>
                      </td>
                      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => setDocId(s.id)}
                            className="rounded p-1 text-content-secondary hover:bg-surface-secondary hover:text-oe-blue"
                            title={t('propdev.spa_pdf', { defaultValue: 'Download SPA PDF' })}
                            aria-label={t('propdev.spa_pdf', { defaultValue: 'Download SPA PDF' })}
                          >
                            <FileText size={14} />
                          </button>
                          {canSend && (
                            <button
                              type="button"
                              disabled={sendMut.isPending}
                              onClick={() => sendMut.mutate(s.id)}
                              className="rounded p-1 text-content-secondary hover:bg-amber-100 hover:text-amber-700"
                              title={t('propdev.send_for_signature', { defaultValue: 'Send for signature' })}
                              aria-label={t('propdev.send_for_signature', { defaultValue: 'Send for signature' })}
                            >
                              <Send size={14} />
                            </button>
                          )}
                          {canSign && (
                            <button
                              type="button"
                              disabled={signMut.isPending}
                              onClick={() => signMut.mutate(s.id)}
                              className="rounded p-1 text-content-secondary hover:bg-emerald-100 hover:text-emerald-700"
                              title={t('propdev.sign', { defaultValue: 'Sign / countersign' })}
                              aria-label={t('propdev.sign', { defaultValue: 'Sign / countersign' })}
                            >
                              <Check size={14} />
                            </button>
                          )}
                          {canVoid && (
                            <button
                              type="button"
                              disabled={voidMut.isPending}
                              onClick={async () => {
                                const ok = await confirm({
                                  title: t('propdev.void_spa_title', { defaultValue: 'Void contract?' }),
                                  message: t('propdev.confirm_void_spa', { defaultValue: 'Void this contract? This is irreversible.' }),
                                  confirmLabel: t('propdev.void', { defaultValue: 'Void' }),
                                  variant: 'danger',
                                });
                                if (!ok) return;
                                voidMut.mutate(s.id);
                              }}
                              className="rounded p-1 text-content-secondary hover:bg-rose-100 hover:text-rose-700"
                              title={t('propdev.void', { defaultValue: 'Void' })}
                              aria-label={t('propdev.void', { defaultValue: 'Void' })}
                            >
                              <XCircle size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {activeSpaId && (
        <SpaDetailDrawer
          spaId={activeSpaId}
          spas={rows}
          plots={plots}
          onClose={() => setActiveSpaId(null)}
          onChanged={invalidate}
          onJumpToPaymentSchedules={onJumpToPaymentSchedules}
        />
      )}
      {convertReservationId && (
        <ConvertReservationModal
          reservationId={convertReservationId}
          reservation={
            convertibleReservations.find((r) => r.id === convertReservationId) ??
            null
          }
          plots={plots}
          onClose={() => setConvertReservationId(null)}
          onConverted={() => {
            setConvertReservationId(null);
            invalidate();
            addToast({
              type: 'success',
              title: t('propdev.spa_created', {
                defaultValue: 'Sales Contract created',
              }),
            });
          }}
        />
      )}
      {docId && (
        <DocumentPreviewModal
          open
          onClose={() => setDocId(null)}
          docType="sales_contract"
          contractId={docId}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

function SpaDetailDrawer({
  spaId,
  spas,
  plots,
  onClose,
  onChanged,
  onJumpToPaymentSchedules,
}: {
  spaId: string;
  spas: SalesContract[];
  plots: Plot[];
  onClose: () => void;
  onChanged: () => void;
  onJumpToPaymentSchedules?: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const spa = spas.find((s) => s.id === spaId) ?? null;
  const plot = spa ? plots.find((p) => p.id === spa.plot_id) : null;
  const [generateOpen, setGenerateOpen] = useState(false);

  const scheduleQ = useQuery({
    queryKey: ['propdev', 'spa-schedule', spaId],
    queryFn: () => listPaymentSchedules({ sales_contract_id: spaId }),
    enabled: !!spaId,
  });
  const schedule = scheduleQ.data?.[0] ?? null;
  const instalmentsQ = useQuery({
    queryKey: ['propdev', 'spa-instalments', spaId],
    queryFn: () => listInstalments({ sales_contract_id: spaId }),
    enabled: !!spaId,
  });
  const instalments = instalmentsQ.data ?? [];

  const suspendMut = useMutation({
    mutationFn: (id: string) => suspendPaymentSchedule(id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.schedule_suspended', { defaultValue: 'Schedule suspended' }) });
      qc.invalidateQueries({ queryKey: ['propdev', 'spa-schedule', spaId] });
      qc.invalidateQueries({ queryKey: ['propdev', 'spa-instalments', spaId] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const activateMut = useMutation({
    mutationFn: (id: string) => activatePaymentSchedule(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'spa-schedule', spaId] });
      qc.invalidateQueries({ queryKey: ['propdev', 'spa-instalments', spaId] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <SideDrawer
      open={!!spa}
      onClose={onClose}
      widthClass="max-w-2xl"
      title={spa?.contract_number ?? ''}
      subtitle={spa ? `${plot?.plot_number ?? ''} · ${spa.status}` : ''}
    >
      {spa && (
        <div className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Field
              label={t('propdev.total_value', { defaultValue: 'Total value' })}
              value={<MoneyDisplay amount={toNumber(spa.total_value)} currency={spa.currency || undefined} />}
            />
            <Field
              label={t('propdev.signed', { defaultValue: 'Signed' })}
              value={spa.signing_date ? <DateDisplay value={spa.signing_date} /> : '—'}
            />
            <Field
              label={t('propdev.governing_law', { defaultValue: 'Governing law' })}
              value={spa.governing_law || '—'}
            />
            <Field
              label={t('common.status', { defaultValue: 'Status' })}
              value={<Badge variant={SPA_VARIANT[spa.status]} dot>{spa.status}</Badge>}
            />
          </div>

          <div className="border-t border-border-light pt-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('propdev.payment_schedule', { defaultValue: 'Payment Schedule' })}
              </p>
              <div className="flex items-center gap-1">
                {schedule && schedule.status === 'active' && (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Clock size={12} />}
                    onClick={() => suspendMut.mutate(schedule.id)}
                  >
                    {t('propdev.suspend', { defaultValue: 'Suspend' })}
                  </Button>
                )}
                {schedule && schedule.status === 'suspended' && (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Check size={12} />}
                    onClick={() => activateMut.mutate(schedule.id)}
                  >
                    {t('propdev.activate', { defaultValue: 'Activate' })}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="primary"
                  icon={<Receipt size={12} />}
                  onClick={() => setGenerateOpen(true)}
                >
                  {t('propdev.generate_schedule', { defaultValue: 'Generate Schedule' })}
                </Button>
                {schedule && onJumpToPaymentSchedules && (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<ArrowRight size={12} />}
                    onClick={() => {
                      onClose();
                      onJumpToPaymentSchedules();
                    }}
                    title={t('propdev.open_in_schedules_tab', {
                      defaultValue: 'Open in Payment Schedules tab',
                    })}
                  >
                    {t('propdev.open_in_schedules', {
                      defaultValue: 'Schedules tab',
                    })}
                  </Button>
                )}
              </div>
            </div>
            {schedule ? (
              <div className="mb-2 text-xs text-content-secondary">
                <Badge variant={SCHEDULE_VARIANT[schedule.status]}>{schedule.status}</Badge>
                <span className="ml-2">
                  <MoneyDisplay amount={toNumber(schedule.total_amount)} currency={schedule.currency || undefined} />
                  {' · '}
                  {t('propdev.late_fee_pct', { defaultValue: 'Late fee {{n}}%', n: String(schedule.late_fee_pct) })}
                </span>
              </div>
            ) : (
              <p className="text-sm text-content-tertiary mb-2">
                {t('propdev.no_schedule', { defaultValue: 'No payment schedule yet. Generate one to break the SPA value into milestones.' })}
              </p>
            )}
            {instalments.length > 0 && (
              <InstalmentsTable instalments={instalments} currency={spa.currency} onChanged={() => {
                qc.invalidateQueries({ queryKey: ['propdev', 'spa-instalments', spaId] });
                onChanged();
              }} />
            )}
          </div>
        </div>
      )}

      {generateOpen && spa && (
        <GenerateScheduleModal
          spaId={spa.id}
          totalValue={spa.total_value}
          currency={spa.currency}
          signingDate={spa.signing_date}
          existingSchedule={schedule}
          onClose={() => setGenerateOpen(false)}
          onGenerated={() => {
            setGenerateOpen(false);
            qc.invalidateQueries({ queryKey: ['propdev', 'spa-schedule', spaId] });
            qc.invalidateQueries({ queryKey: ['propdev', 'spa-instalments', spaId] });
            onChanged();
            addToast({ type: 'success', title: t('propdev.schedule_generated', { defaultValue: 'Schedule generated' }) });
          }}
        />
      )}
    </SideDrawer>
  );
}

function InstalmentsTable({
  instalments,
  currency,
  onChanged,
}: {
  instalments: Instalment[];
  currency: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [payingId, setPayingId] = useState<string | null>(null);
  const [docId, setDocId] = useState<string | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  const demandMut = useMutation({
    mutationFn: (id: string) => issueInstalmentDemand(id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.demand_sent', { defaultValue: 'Demand letter queued' }) });
      onChanged();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const waiveMut = useMutation({
    mutationFn: (id: string) => waiveInstalment(id, { reason: 'Goodwill waiver' }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.waived', { defaultValue: 'Instalment waived' }) });
      onChanged();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <>
      <div className="overflow-x-auto rounded border border-border-light">
        <table className="w-full text-xs">
          <thead className="bg-surface-secondary text-content-secondary">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium">#</th>
              <th className="px-2 py-1.5 text-left font-medium">{t('propdev.milestone', { defaultValue: 'Milestone' })}</th>
              <th className="px-2 py-1.5 text-left font-medium">{t('propdev.due', { defaultValue: 'Due' })}</th>
              <th className="px-2 py-1.5 text-right font-medium">{t('propdev.amount', { defaultValue: 'Amount' })}</th>
              <th className="px-2 py-1.5 text-right font-medium">{t('propdev.paid', { defaultValue: 'Paid' })}</th>
              <th className="px-2 py-1.5 text-left font-medium">{t('common.status', { defaultValue: 'Status' })}</th>
              <th className="px-2 py-1.5 text-right font-medium">{t('common.actions', { defaultValue: 'Actions' })}</th>
            </tr>
          </thead>
          <tbody>
            {instalments.map((ins) => {
              const open = !['paid', 'waived', 'cancelled'].includes(ins.status);
              return (
                <tr key={ins.id} className="border-t border-border-light">
                  <td className="px-2 py-1.5 font-mono">{ins.sequence}</td>
                  <td className="px-2 py-1.5">{ins.milestone_label}</td>
                  <td className="px-2 py-1.5">{ins.due_date ? <DateDisplay value={ins.due_date} /> : '—'}</td>
                  <td className="px-2 py-1.5 text-right">
                    <MoneyDisplay amount={toNumber(ins.amount)} currency={currency || undefined} />
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <MoneyDisplay amount={toNumber(ins.amount_paid)} currency={currency || undefined} />
                  </td>
                  <td className="px-2 py-1.5">
                    <Badge variant={INSTALMENT_VARIANT[ins.status]}>{ins.status}</Badge>
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex items-center justify-end gap-0.5">
                      <button
                        type="button"
                        onClick={() => setDocId(ins.id)}
                        className="rounded p-1 text-content-secondary hover:bg-surface-secondary hover:text-oe-blue"
                        title={t('propdev.payment_receipt', { defaultValue: 'Payment receipt PDF' })}
                        aria-label={t('propdev.payment_receipt', { defaultValue: 'Payment receipt PDF' })}
                      >
                        <FileText size={12} />
                      </button>
                      {open && (
                        <>
                          <button
                            type="button"
                            onClick={() => setPayingId(ins.id)}
                            className="inline-flex items-center gap-1 rounded border border-emerald-300 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-800 hover:bg-emerald-100"
                            title={t('propdev.mark_paid', { defaultValue: 'Mark paid' })}
                          >
                            <DollarSign size={10} />
                            {t('propdev.mark_paid', { defaultValue: 'Mark paid' })}
                          </button>
                          <button
                            type="button"
                            disabled={demandMut.isPending}
                            onClick={() => demandMut.mutate(ins.id)}
                            className="rounded p-1 text-content-secondary hover:bg-amber-100 hover:text-amber-700"
                            title={t('propdev.send_demand', { defaultValue: 'Send demand' })}
                            aria-label={t('propdev.send_demand', { defaultValue: 'Send demand' })}
                          >
                            <Send size={12} />
                          </button>
                          <button
                            type="button"
                            disabled={waiveMut.isPending}
                            onClick={async () => {
                              const ok = await confirm({
                                title: t('propdev.waive_title', { defaultValue: 'Waive instalment?' }),
                                message: t('propdev.confirm_waive', { defaultValue: 'Waive this instalment?' }),
                                confirmLabel: t('propdev.waive', { defaultValue: 'Waive' }),
                                variant: 'warning',
                              });
                              if (!ok) return;
                              waiveMut.mutate(ins.id);
                            }}
                            className="rounded p-1 text-content-secondary hover:bg-amber-100 hover:text-amber-700"
                            title={t('propdev.waive', { defaultValue: 'Waive' })}
                            aria-label={t('propdev.waive', { defaultValue: 'Waive' })}
                          >
                            <XCircle size={12} />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {payingId && (
        <MarkPaidModal
          instalment={instalments.find((i) => i.id === payingId) ?? null}
          currency={currency}
          onClose={() => setPayingId(null)}
          onPaid={() => {
            setPayingId(null);
            onChanged();
          }}
        />
      )}
      {docId && (
        <DocumentPreviewModal
          open
          onClose={() => setDocId(null)}
          docType="payment_receipt"
          instalmentId={docId}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </>
  );
}

function MarkPaidModal({
  instalment,
  currency,
  onClose,
  onPaid,
}: {
  instalment: Instalment | null;
  currency: string;
  onClose: () => void;
  onPaid: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const outstanding = instalment
    ? toNumber(instalment.amount) - toNumber(instalment.amount_paid)
    : 0;
  const [form, setForm] = useState({
    amount: String(outstanding.toFixed(2)),
    paid_at: todayIso(),
    invoice_ref: '',
  });
  const mut = useMutation({
    mutationFn: () =>
      markInstalmentPaid(instalment!.id, {
        amount: form.amount,
        paid_at: form.paid_at ? `${form.paid_at}T00:00:00Z` : undefined,
        invoice_ref: form.invoice_ref || undefined,
      }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.instalment_paid', { defaultValue: 'Instalment marked paid' }) });
      onPaid();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  return (
    <WideModal
      open={!!instalment}
      onClose={onClose}
      title={t('propdev.mark_instalment_paid', { defaultValue: 'Mark instalment paid' })}
      subtitle={instalment?.milestone_label}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button
            variant="primary"
            icon={mut.isPending ? <Loader2 size={14} /> : <DollarSign size={14} />}
            loading={mut.isPending}
            disabled={!form.amount || Number(form.amount) <= 0}
            onClick={() => mut.mutate()}
          >
            {t('propdev.confirm_payment', { defaultValue: 'Confirm payment' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('propdev.amount', { defaultValue: 'Amount' })} required>
          <input
            type="number"
            min="0"
            step="0.01"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
            className={inputCls}
          />
          <p className="mt-1 text-[11px] text-content-tertiary">
            {t('propdev.outstanding', { defaultValue: 'Outstanding' })}:{' '}
            <MoneyDisplay amount={outstanding} currency={currency || undefined} />
          </p>
        </WideModalField>
        <WideModalField label={t('propdev.paid_on', { defaultValue: 'Paid on' })}>
          <input
            type="date"
            value={form.paid_at}
            onChange={(e) => setForm({ ...form, paid_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('propdev.invoice_ref', { defaultValue: 'Invoice / bank ref (optional)' })} span={2}>
          <input
            value={form.invoice_ref}
            onChange={(e) => setForm({ ...form, invoice_ref: e.target.value })}
            className={inputCls}
            maxLength={255}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

function GenerateScheduleModal({
  spaId,
  totalValue,
  currency,
  signingDate,
  existingSchedule,
  onClose,
  onGenerated,
}: {
  spaId: string;
  totalValue: number | string;
  currency: string;
  signingDate: string | null;
  existingSchedule: PaymentSchedule | null;
  onClose: () => void;
  onGenerated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [templateKey, setTemplateKey] = useState<string>('10_40_50');
  const [startDate, setStartDate] = useState<string>(signingDate || todayIso());
  const [lateFeePct, setLateFeePct] = useState<string>('0');
  const [graceDays, setGraceDays] = useState<string>('0');

  const tmplQ = useQuery({
    queryKey: ['propdev', 'payment-templates'],
    queryFn: () => listPaymentScheduleTemplates(),
  });
  const templates = tmplQ.data ?? [];

  const mut = useMutation({
    mutationFn: () =>
      generatePaymentScheduleFromTemplate({
        sales_contract_id: spaId,
        template_key: templateKey,
        start_date: startDate,
        late_fee_pct: lateFeePct || '0',
        grace_period_days: Number(graceDays) || 0,
      }),
    onSuccess: () => onGenerated(),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const blockedByActive =
    existingSchedule && (existingSchedule.status === 'active' || existingSchedule.status === 'completed');

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('propdev.generate_schedule', { defaultValue: 'Generate Payment Schedule' })}
      subtitle={
        <MoneyDisplay amount={toNumber(totalValue)} currency={currency || undefined} />
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button
            variant="primary"
            icon={mut.isPending ? <Loader2 size={14} /> : <Receipt size={14} />}
            loading={mut.isPending}
            disabled={!templateKey || !!blockedByActive}
            onClick={() => mut.mutate()}
          >
            {t('propdev.generate', { defaultValue: 'Generate' })}
          </Button>
        </>
      }
    >
      {blockedByActive && (
        <div className="mx-5 mt-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {t('propdev.suspend_first', {
            defaultValue: 'This contract already has an active schedule. Suspend it before generating a new one.',
          })}
        </div>
      )}
      <WideModalSection columns={2}>
        <WideModalField label={t('propdev.template', { defaultValue: 'Milestone template' })} required span={2}>
          {tmplQ.isLoading ? (
            <SkeletonTable rows={1} columns={1} />
          ) : (
            <div className="space-y-1.5">
              {templates.map((tmpl) => (
                <label
                  key={tmpl.key}
                  className={clsx(
                    'flex cursor-pointer items-start gap-2 rounded border px-3 py-2 text-sm',
                    templateKey === tmpl.key
                      ? 'border-oe-blue bg-oe-blue/5'
                      : 'border-border-light hover:bg-surface-secondary',
                  )}
                >
                  <input
                    type="radio"
                    name="template_key"
                    value={tmpl.key}
                    checked={templateKey === tmpl.key}
                    onChange={() => setTemplateKey(tmpl.key)}
                    className="mt-1"
                  />
                  <div>
                    <p className="font-medium">{tmpl.label}</p>
                    <p className="text-xs text-content-secondary">{tmpl.description}</p>
                    <p className="mt-1 text-[10px] text-content-tertiary">
                      {tmpl.milestone_count} × {tmpl.splits.join(' / ')}%
                    </p>
                  </div>
                </label>
              ))}
            </div>
          )}
        </WideModalField>
        <WideModalField label={t('propdev.start_date', { defaultValue: 'Start date' })}>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('propdev.late_fee_pct_label', { defaultValue: 'Late fee % p.a.' })}>
          <input
            type="number"
            min="0"
            max="100"
            step="0.01"
            value={lateFeePct}
            onChange={(e) => setLateFeePct(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('propdev.grace_days', { defaultValue: 'Grace period (days)' })}>
          <input
            type="number"
            min="0"
            max="365"
            value={graceDays}
            onChange={(e) => setGraceDays(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── Payment Schedules tab ─── */

function PaymentScheduleTab({
  developmentId,
  plots,
  onJumpToReservations,
  onJumpToSpa,
}: {
  developmentId: string;
  plots: Plot[];
  onJumpToReservations?: () => void;
  onJumpToSpa?: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [statusFilter, setStatusFilter] = useState<PaymentScheduleStatus | ''>('');
  const [activeScheduleSpaId, setActiveScheduleSpaId] = useState<string | null>(null);

  const schedulesQ = useQuery({
    queryKey: ['propdev', 'payment-schedules', developmentId, statusFilter],
    queryFn: () =>
      listPaymentSchedules({
        development_id: developmentId,
        status: statusFilter || undefined,
      }),
    enabled: !!developmentId,
  });
  const spasQ = useQuery({
    queryKey: ['propdev', 'sales-contracts', developmentId, 'for-schedules'],
    queryFn: () => listSalesContracts({ development_id: developmentId }),
    enabled: !!developmentId,
  });
  const schedules = schedulesQ.data ?? [];
  const spas = spasQ.data ?? [];

  // SPAs that *could* have a schedule but don't yet — surfaces directly
  // as a "Generate schedule" CTA so the user is never stuck looking at
  // a half-populated tab without any way to act.
  const scheduledSpaIds = useMemo(
    () => new Set(schedules.map((sch) => sch.sales_contract_id)),
    [schedules],
  );
  const spasWithoutSchedule = useMemo(
    () =>
      spas.filter(
        (s) => !scheduledSpaIds.has(s.id) && s.status !== 'cancelled',
      ),
    [spas, scheduledSpaIds],
  );
  const [generateForSpa, setGenerateForSpa] = useState<SalesContract | null>(
    null,
  );

  const suspendMut = useMutation({
    mutationFn: (id: string) => suspendPaymentSchedule(id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.schedule_suspended', { defaultValue: 'Schedule suspended' }) });
      qc.invalidateQueries({ queryKey: ['propdev', 'payment-schedules', developmentId] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const activateMut = useMutation({
    mutationFn: (id: string) => activatePaymentSchedule(id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('propdev.schedule_activated', { defaultValue: 'Schedule activated' }) });
      qc.invalidateQueries({ queryKey: ['propdev', 'payment-schedules', developmentId] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!developmentId) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Receipt size={22} />}
          title={t('propdev.no_dev_selected', { defaultValue: 'Select a development to view payment schedules' })}
        />
      </Card>
    );
  }
  if (schedulesQ.isLoading)
    return <Card padding="md"><SkeletonTable rows={6} columns={5} /></Card>;
  if (schedulesQ.isError)
    return (
      <Card padding="md">
        <EmptyState
          icon={<AlertOctagon size={22} />}
          title={t('propdev.load_error', { defaultValue: 'Could not load payment schedules' })}
          description={getErrorMessage(schedulesQ.error)}
          action={{ label: t('common.retry', { defaultValue: 'Retry' }), onClick: () => schedulesQ.refetch() }}
        />
      </Card>
    );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as PaymentScheduleStatus | '')}
          className={clsx(inputCls, 'max-w-[200px]')}
        >
          <option value="">{t('propdev.all_statuses', { defaultValue: 'All statuses' })}</option>
          {SCHEDULE_STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <span className="text-xs text-content-tertiary">
          {t('propdev.n_rows', { defaultValue: '{{n}} rows', n: schedules.length })}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {spasWithoutSchedule.length > 0 && (
            <Button
              variant="primary"
              size="sm"
              icon={<Receipt size={14} />}
              onClick={() => setGenerateForSpa(spasWithoutSchedule[0] ?? null)}
              title={t('propdev.generate_schedule_for_spa_help', {
                defaultValue:
                  '{{n}} SPA(s) have no payment schedule yet - generate one',
                n: spasWithoutSchedule.length,
              })}
            >
              {t('propdev.generate_schedule_short', {
                defaultValue: 'Generate schedule ({{n}})',
                n: spasWithoutSchedule.length,
              })}
            </Button>
          )}
          {onJumpToSpa && (
            <Button
              variant="ghost"
              size="sm"
              icon={<FileSignature size={14} />}
              onClick={onJumpToSpa}
            >
              {t('propdev.go_to_spa_tab', {
                defaultValue: 'Sales Contracts tab',
              })}
            </Button>
          )}
        </div>
      </div>

      {/* SPAs missing a schedule — surfaced as quick-action chips so the
          user sees exactly what needs to be done next, without drilling
          into the SPA detail drawer. */}
      {spasWithoutSchedule.length > 0 && schedules.length > 0 && (
        <Card padding="sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
            {t('propdev.spas_missing_schedule', {
              defaultValue: 'SPAs without a payment schedule',
            })}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {spasWithoutSchedule.slice(0, 12).map((s) => {
              const plot = plots.find((p) => p.id === s.plot_id);
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setGenerateForSpa(s)}
                  className="inline-flex items-center gap-1.5 rounded border border-oe-blue/40 bg-oe-blue/5 px-2 py-1 text-[11px] font-medium text-oe-blue hover:bg-oe-blue/10"
                >
                  <Receipt size={11} />
                  {s.contract_number}
                  {plot?.plot_number ? ` · ${plot.plot_number}` : ''}
                </button>
              );
            })}
            {spasWithoutSchedule.length > 12 && (
              <span className="text-[11px] text-content-tertiary self-center">
                {t('propdev.and_n_more', {
                  defaultValue: '… and {{n}} more',
                  n: spasWithoutSchedule.length - 12,
                })}
              </span>
            )}
          </div>
        </Card>
      )}

      {schedules.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<Receipt size={22} />}
            title={t('propdev.no_schedules', { defaultValue: 'No payment schedules yet' })}
            description={
              spasWithoutSchedule.length > 0
                ? t('propdev.no_schedules_desc_with_spa', {
                    defaultValue:
                      'There are {{n}} signed SPAs ready for a payment schedule. Generate one to break the contract value into milestones.',
                    n: spasWithoutSchedule.length,
                  })
                : spas.length === 0
                  ? t('propdev.no_schedules_no_spa', {
                      defaultValue:
                        'Schedules are created from a Sales Contract. Convert an active Reservation into an SPA first.',
                    })
                  : t('propdev.no_schedules_desc', {
                      defaultValue:
                        'Schedules are created automatically when a reservation is converted to an SPA, or via "Generate Schedule" on the SPA detail.',
                    })
            }
            action={
              spasWithoutSchedule.length > 0
                ? {
                    label: t('propdev.generate_schedule', {
                      defaultValue: 'Generate Schedule',
                    }),
                    onClick: () =>
                      setGenerateForSpa(spasWithoutSchedule[0] ?? null),
                  }
                : onJumpToReservations
                  ? {
                      label: t('propdev.go_to_reservations_cta', {
                        defaultValue: 'Open Reservations tab',
                      }),
                      onClick: onJumpToReservations,
                    }
                  : undefined
            }
          />
        </Card>
      ) : (
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-secondary">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">{t('propdev.contract_number', { defaultValue: 'SPA' })}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('propdev.plot', { defaultValue: 'Plot' })}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('propdev.total', { defaultValue: 'Total' })}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('propdev.late_fee_pct_short', { defaultValue: 'Late %' })}</th>
                  <th className="px-3 py-2 text-left font-medium">{t('common.status', { defaultValue: 'Status' })}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('common.actions', { defaultValue: 'Actions' })}</th>
                </tr>
              </thead>
              <tbody>
                {schedules.map((sch) => {
                  const spa = spas.find((s) => s.id === sch.sales_contract_id);
                  const plot = spa ? plots.find((p) => p.id === spa.plot_id) : null;
                  return (
                    <tr key={sch.id} className="border-t border-border-light">
                      <td className="px-3 py-2 font-mono text-xs">{spa?.contract_number ?? sch.sales_contract_id.slice(0, 8)}</td>
                      <td className="px-3 py-2">{plot?.plot_number ?? '—'}</td>
                      <td className="px-3 py-2 text-right">
                        <MoneyDisplay amount={toNumber(sch.total_amount)} currency={sch.currency || undefined} />
                      </td>
                      <td className="px-3 py-2 text-right text-xs">{String(sch.late_fee_pct)}%</td>
                      <td className="px-3 py-2">
                        <Badge variant={SCHEDULE_VARIANT[sch.status]} dot>{sch.status}</Badge>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => spa && setActiveScheduleSpaId(spa.id)}
                            disabled={!spa}
                            className="rounded p-1 text-content-secondary hover:bg-surface-secondary hover:text-oe-blue disabled:opacity-50"
                            title={t('propdev.view_instalments', { defaultValue: 'View instalments' })}
                            aria-label={t('propdev.view_instalments', { defaultValue: 'View instalments' })}
                          >
                            <ArrowRight size={14} />
                          </button>
                          {sch.status === 'active' && (
                            <button
                              type="button"
                              disabled={suspendMut.isPending}
                              onClick={() => suspendMut.mutate(sch.id)}
                              className="rounded p-1 text-content-secondary hover:bg-amber-100 hover:text-amber-700"
                              title={t('propdev.suspend', { defaultValue: 'Suspend' })}
                              aria-label={t('propdev.suspend', { defaultValue: 'Suspend' })}
                            >
                              <Clock size={14} />
                            </button>
                          )}
                          {sch.status === 'suspended' && (
                            <button
                              type="button"
                              disabled={activateMut.isPending}
                              onClick={() => activateMut.mutate(sch.id)}
                              className="rounded p-1 text-content-secondary hover:bg-emerald-100 hover:text-emerald-700"
                              title={t('propdev.activate', { defaultValue: 'Activate' })}
                              aria-label={t('propdev.activate', { defaultValue: 'Activate' })}
                            >
                              <Check size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {activeScheduleSpaId && (
        <SpaDetailDrawer
          spaId={activeScheduleSpaId}
          spas={spas}
          plots={plots}
          onClose={() => setActiveScheduleSpaId(null)}
          onChanged={() => {
            qc.invalidateQueries({ queryKey: ['propdev', 'payment-schedules', developmentId] });
          }}
        />
      )}
      {generateForSpa && (
        <GenerateScheduleModal
          spaId={generateForSpa.id}
          totalValue={generateForSpa.total_value}
          currency={generateForSpa.currency}
          signingDate={generateForSpa.signing_date}
          existingSchedule={null}
          onClose={() => setGenerateForSpa(null)}
          onGenerated={() => {
            setGenerateForSpa(null);
            qc.invalidateQueries({
              queryKey: ['propdev', 'payment-schedules', developmentId],
            });
            qc.invalidateQueries({
              queryKey: ['propdev', 'sales-contracts', developmentId, 'for-schedules'],
            });
            addToast({
              type: 'success',
              title: t('propdev.schedule_generated', {
                defaultValue: 'Schedule generated',
              }),
            });
          }}
        />
      )}
    </div>
  );
}

/* ─── Handovers tab ─── */

function HandoversTab({ plots, buyers }: { plots: Plot[]; buyers: Buyer[] }) {
  const { t } = useTranslation();
  // Plots eligible for handover: anything past 'planned'. We intentionally
  // include reserved + under_construction so users can SCHEDULE a future
  // handover before the plot is physically ready (real-world workflow).
  const candidatePlots = plots.filter((p) =>
    ['reserved', 'under_construction', 'ready', 'sold', 'handed_over'].includes(p.status),
  );
  if (plots.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Key size={22} />}
          title={t('propdev.empty_handovers_no_plots', {
            defaultValue: 'No plots in this development yet',
          })}
          description={t('propdev.empty_handovers_no_plots_desc', {
            defaultValue:
              'Create plots first (under the Plots tab) - handovers are scheduled per plot once a buyer is assigned.',
          })}
        />
      </Card>
    );
  }
  if (candidatePlots.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Key size={22} />}
          title={t('propdev.empty_handovers', { defaultValue: 'No handovers scheduled' })}
          description={t('propdev.empty_handovers_desc', {
            defaultValue:
              'Handovers appear here once plots leave "planned" status. Move a plot to reserved or further and schedule its handover here.',
          })}
        />
      </Card>
    );
  }
  return (
    <div className="space-y-3">
      {candidatePlots.map((p) => {
        const buyer = buyers.find((b) => b.plot_id === p.id);
        return <HandoverPlotRow key={p.id} plot={p} buyer={buyer} />;
      })}
    </div>
  );
}

function HandoverPlotRow({ plot, buyer }: { plot: Plot; buyer: Buyer | undefined }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const handoversQ = useQuery({
    queryKey: ['propdev', 'handovers', plot.id],
    queryFn: () => listHandovers(plot.id),
    staleTime: 60_000,
  });
  const handovers = handoversQ.data ?? [];

  const [docModal, setDocModal] = useState<{
    type: PropDevDocType;
    handoverId?: string;
    contractId?: string;
  } | null>(null);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [completeOpen, setCompleteOpen] = useState<string | null>(null);
  const [scheduledAt, setScheduledAt] = useState('');
  const [notes, setNotes] = useState('');
  const { confirm, ...confirmProps } = useConfirm();

  const handoverId = handovers[0]?.id;

  const createMu = useMutation({
    mutationFn: () =>
      createHandover({
        plot_id: plot.id,
        scheduled_at: scheduledAt || undefined,
        notes: notes || undefined,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.handover_scheduled', { defaultValue: 'Handover scheduled' }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'handovers', plot.id] });
      setScheduleOpen(false);
      setScheduledAt('');
      setNotes('');
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMu = useMutation({
    mutationFn: (id: string) => deleteHandover(id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.handover_deleted', { defaultValue: 'Handover removed' }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'handovers', plot.id] });
      qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <Card padding="md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold">
            {t('propdev.plot_n', { defaultValue: 'Plot {{n}}', n: plot.plot_number })}
          </p>
          <p className="text-xs text-content-tertiary">
            {buyer ? buyer.full_name : t('propdev.no_buyer', { defaultValue: 'No buyer assigned' })}
          </p>
        </div>
        <Badge variant={PLOT_STATUS_VARIANT[plot.status]} dot>{plot.status}</Badge>
      </div>
      {handoversQ.isLoading ? (
        <p className="mt-2 text-xs text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading…' })}
        </p>
      ) : handovers.length === 0 ? (
        <div className="mt-2 flex items-center justify-between gap-3">
          <p className="text-xs text-content-tertiary">
            {t('propdev.no_handovers', { defaultValue: 'No handover scheduled yet.' })}
          </p>
          <Button
            size="sm"
            variant="primary"
            icon={<Plus size={12} />}
            onClick={() => setScheduleOpen(true)}
          >
            {t('propdev.schedule_handover', { defaultValue: 'Schedule handover' })}
          </Button>
        </div>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {handovers.map((h: Handover) => (
            <li
              key={h.id}
              className="flex flex-wrap items-center gap-2 text-xs"
            >
              {h.completed_at ? (
                <Badge variant="success" dot>
                  {t('propdev.completed', { defaultValue: 'Completed' })}
                </Badge>
              ) : (
                <Badge variant="warning" dot>
                  {t('propdev.scheduled', { defaultValue: 'Scheduled' })}
                </Badge>
              )}
              <span className="text-content-secondary">
                {h.scheduled_at ? <DateDisplay value={h.scheduled_at} /> : '—'}
              </span>
              {h.completed_at && (
                <span className="text-content-tertiary">
                  → <DateDisplay value={h.completed_at} />
                </span>
              )}
              {h.snag_count_at_handover > 0 && (
                <span className="text-amber-600">
                  · {h.snag_count_at_handover} {t('propdev.snags', { defaultValue: 'snags' })}
                </span>
              )}
              {!h.completed_at && (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => setCompleteOpen(h.id)}
                >
                  {t('propdev.mark_completed', { defaultValue: 'Mark completed' })}
                </Button>
              )}
              {!h.completed_at && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    const ok = await confirm({
                      title: t('propdev.delete_handover_title', {
                        defaultValue: 'Delete handover?',
                      }),
                      message: t('propdev.confirm_delete_handover', {
                        defaultValue:
                          'Delete this scheduled handover? Linked snags will cascade.',
                      }),
                      confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
                      variant: 'danger',
                    });
                    if (!ok) return;
                    deleteMu.mutate(h.id);
                  }}
                  disabled={deleteMu.isPending}
                >
                  {t('common.delete', { defaultValue: 'Delete' })}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {/* Document-generation actions (R6 follow-up). Only shown when a
          handover record exists — that's the trigger for all three docs. */}
      {handoverId && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              setDocModal({ type: 'handover_certificate', handoverId })
            }
          >
            {t('propdev.documents.generate_handover_certificate', {
              defaultValue: 'Generate handover certificate',
            })}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              setDocModal({ type: 'warranty_certificate', handoverId })
            }
          >
            {t('propdev.documents.generate_warranty_certificate', {
              defaultValue: 'Generate warranty certificate',
            })}
          </Button>
        </div>
      )}
      {/* Per-handover blocks: the digital closeout package (item #25 —
          warranty / manuals / key receipt + ZIP export) sits above the
          snags block. Snags drive the snag → warranty promote flow on
          completed handovers; on scheduled handovers we still allow
          adding both so site engineers can prepare ahead of completion. */}
      {handovers.map((h: Handover) => (
        <div key={`handover-blocks-${h.id}`}>
          <HandoverDocumentsSection handover={h} />
          <SnagsBlock handover={h} buyer={buyer} plotId={plot.id} />
        </div>
      ))}
      {scheduleOpen && (
        <WideModal
          open
          onClose={() => setScheduleOpen(false)}
          title={t('propdev.schedule_handover', {
            defaultValue: 'Schedule handover',
          })}
          size="md"
          busy={createMu.isPending}
          footer={
            <>
              <Button
                variant="ghost"
                onClick={() => setScheduleOpen(false)}
                disabled={createMu.isPending}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                onClick={() => createMu.mutate()}
                loading={createMu.isPending}
                icon={<Plus size={14} />}
              >
                {t('propdev.schedule_handover', {
                  defaultValue: 'Schedule handover',
                })}
              </Button>
            </>
          }
        >
          <WideModalSection columns={2}>
            <WideModalField
              label={t('propdev.scheduled_date', { defaultValue: 'Scheduled date' })}
              span={2}
            >
              <input
                type="date"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('propdev.notes', { defaultValue: 'Notes' })}
              span={2}
            >
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className={inputCls}
                rows={3}
              />
            </WideModalField>
          </WideModalSection>
        </WideModal>
      )}
      {completeOpen && (
        <CompleteHandoverModal
          handoverId={completeOpen}
          plotId={plot.id}
          onClose={() => setCompleteOpen(null)}
        />
      )}
      {docModal && (
        <DocumentPreviewModal
          open
          onClose={() => setDocModal(null)}
          docType={docModal.type}
          handoverId={docModal.handoverId}
          contractId={docModal.contractId}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}

function CompleteHandoverModal({
  handoverId,
  plotId,
  onClose,
}: {
  handoverId: string;
  plotId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({
    completed_at: today,
    customer_signature_ref: '',
    keys_handed_over_at: today,
    final_check_passed: true,
    snag_count_at_handover: 0,
    notes: '',
  });
  const mu = useMutation({
    mutationFn: () =>
      completeHandover(handoverId, {
        completed_at: form.completed_at,
        customer_signature_ref: form.customer_signature_ref.trim(),
        keys_handed_over_at: form.keys_handed_over_at || undefined,
        final_check_passed: form.final_check_passed,
        snag_count_at_handover: Number(form.snag_count_at_handover) || 0,
        notes: form.notes || undefined,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.handover_completed', {
          defaultValue: 'Handover marked complete',
        }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'handovers', plotId] });
      qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
      qc.invalidateQueries({ queryKey: ['propdev', 'buyers'] });
      onClose();
    },
    onError: (err) => {
      // The closeout gate (item #25) blocks completion with a 409 when a
      // required handover document is still undelivered. Surface the
      // missing-doc list so the user knows exactly what to deliver first.
      if (err instanceof ApiError && err.status === 409) {
        const detail = (err.body as { detail?: { missing_required?: string[] } })
          ?.detail;
        const missing = detail?.missing_required ?? [];
        addToast({
          type: 'error',
          title: t('propdev.handover_blocked_docs', {
            defaultValue: 'Required documents missing',
          }),
          message:
            missing.length > 0
              ? t('propdev.handover_blocked_docs_list', {
                  defaultValue: 'Deliver these first: {{docs}}',
                  docs: missing.join(', '),
                })
              : getErrorMessage(err),
        });
        return;
      }
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });
  const canSubmit =
    !!form.completed_at && form.customer_signature_ref.trim().length > 0;
  return (
    <WideModal
      open
      onClose={onClose}
      title={t('propdev.complete_handover', {
        defaultValue: 'Complete handover',
      })}
      size="lg"
      busy={mu.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mu.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => mu.mutate()}
            loading={mu.isPending}
            disabled={!canSubmit}
            icon={<Check size={14} />}
          >
            {t('propdev.confirm_completion', {
              defaultValue: 'Confirm completion',
            })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('propdev.completed_at', { defaultValue: 'Completed at' })}
          required
        >
          <input
            type="date"
            value={form.completed_at}
            onChange={(e) => setForm({ ...form, completed_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.keys_handed_over_at', {
            defaultValue: 'Keys handed over at',
          })}
        >
          <input
            type="date"
            value={form.keys_handed_over_at}
            onChange={(e) =>
              setForm({ ...form, keys_handed_over_at: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.customer_signature_ref', {
            defaultValue: 'Customer signature ref',
          })}
          required
          span={2}
        >
          <input
            value={form.customer_signature_ref}
            onChange={(e) =>
              setForm({ ...form, customer_signature_ref: e.target.value })
            }
            className={inputCls}
            placeholder="SIG-2026-001 / DocuSign envelope id"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.snag_count_at_handover', {
            defaultValue: 'Snag count at handover',
          })}
        >
          <input
            type="number"
            min={0}
            value={form.snag_count_at_handover}
            onChange={(e) =>
              setForm({
                ...form,
                snag_count_at_handover: Number(e.target.value) || 0,
              })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.final_check_passed', {
            defaultValue: 'Final check passed',
          })}
        >
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.final_check_passed}
              onChange={(e) =>
                setForm({ ...form, final_check_passed: e.target.checked })
              }
            />
            <span>
              {t('propdev.final_check_passed_help', {
                defaultValue:
                  'All required handover docs delivered & sign-off complete',
              })}
            </span>
          </label>
        </WideModalField>
        <WideModalField
          label={t('propdev.notes', { defaultValue: 'Notes' })}
          span={2}
        >
          <textarea
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            className={inputCls}
            rows={3}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── Warranty tab ─── */

function WarrantyTab({
  buyers,
  plots,
  developmentId,
  initialStatus = '',
  onConsumedPreset,
}: {
  buyers: Buyer[];
  plots: Plot[];
  developmentId: string;
  initialStatus?: string;
  onConsumedPreset?: () => void;
}) {
  const { t } = useTranslation();
  const [filterBuyerId, setFilterBuyerId] = useState<string>('');
  const [filterStatus, setFilterStatus] = useState<string>(initialStatus);
  const [filterSeverity, setFilterSeverity] = useState<string>('');
  const [createOpen, setCreateOpen] = useState(false);

  // Re-honour a fresh tile preset if the user navigates Overview→Warranty
  // a second time with a different status filter. Single-shot consumption:
  // we clear the parent's preset so a manual filter change isn't reverted
  // by the next render. Skip the empty-preset case so the parent's "clear"
  // pass doesn't wipe a manually-chosen filter.
  useEffect(() => {
    if (initialStatus) {
      setFilterStatus(initialStatus);
      onConsumedPreset?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialStatus]);

  // Development-wide listing by default so the page always shows
  // something useful as soon as the user lands on it. The buyer
  // dropdown lets them narrow the slice without losing context.
  const claimsQ = useQuery({
    queryKey: [
      'propdev',
      'warranty',
      developmentId,
      filterBuyerId,
      filterStatus,
      filterSeverity,
    ],
    queryFn: () =>
      filterBuyerId
        ? listWarrantyClaims({
            buyer_id: filterBuyerId,
            status: filterStatus || undefined,
          })
        : listWarrantyClaims({
            development_id: developmentId,
            status: filterStatus || undefined,
            severity: filterSeverity || undefined,
          }),
    enabled: !!developmentId,
  });
  const claims = claimsQ.data ?? [];
  const plotMap = new Map(plots.map((p) => [p.id, p]));
  const buyerMap = new Map(buyers.map((b) => [b.id, b]));
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const action = useMutation({
    mutationFn: async ({
      id,
      kind,
    }: {
      id: string;
      kind: 'accept' | 'reject' | 'close' | 'review';
    }) => {
      if (kind === 'accept') return acceptWarrantyClaim(id);
      if (kind === 'reject') return rejectWarrantyClaim(id);
      if (kind === 'review') return updateWarrantyClaim(id, { status: 'under_review' });
      return closeWarrantyClaim(id);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'warranty'] });
      addToast({
        type: 'success',
        title: t('propdev.warranty_updated', { defaultValue: 'Claim updated' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  // The PDF endpoint is bearer-token guarded, so a plain ``<a href>``
  // navigation 401s. Fetch the blob with the auth header and trigger a
  // temporary download anchor instead.
  const pdfMut = useMutation({
    mutationFn: (id: string) => downloadWarrantyClaimPdf(id),
    onSuccess: (blob, id) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `warranty-claim-${id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Revoke after a tick so the navigation/download has started.
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!developmentId) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<ShieldAlert size={22} />}
          title={t('propdev.warranty.pick_dev_title', {
            defaultValue: 'Pick a development first',
          })}
          description={t('propdev.warranty.pick_dev_desc', {
            defaultValue:
              'Warranty claims are listed per development - pick one from the Developments tab to see its open claims.',
          })}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-content-tertiary">
            <span className="block mb-1">
              {t('propdev.warranty.filter_buyer', { defaultValue: 'Buyer' })}
            </span>
            <select
              value={filterBuyerId}
              onChange={(e) => setFilterBuyerId(e.target.value)}
              className={clsx(inputCls, 'max-w-[260px]')}
            >
              <option value="">
                {t('propdev.warranty.filter_all_buyers', {
                  defaultValue: 'All buyers',
                })}
              </option>
              {buyers.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.full_name} — {b.email}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-content-tertiary">
            <span className="block mb-1">
              {t('propdev.warranty.filter_status', { defaultValue: 'Status' })}
            </span>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className={clsx(inputCls, 'max-w-[180px]')}
            >
              <option value="">{t('propdev.warranty.filter_all', { defaultValue: 'All' })}</option>
              <option value="raised">{t('propdev.warranty.status_raised', { defaultValue: 'Raised' })}</option>
              <option value="under_review">{t('propdev.warranty.status_under_review', { defaultValue: 'Under review' })}</option>
              <option value="accepted">{t('propdev.warranty.status_accepted', { defaultValue: 'Accepted' })}</option>
              <option value="rejected">{t('propdev.warranty.status_rejected', { defaultValue: 'Rejected' })}</option>
              <option value="closed">{t('propdev.warranty.status_closed', { defaultValue: 'Closed' })}</option>
            </select>
          </label>
          {!filterBuyerId && (
            <label className="text-xs text-content-tertiary">
              <span className="block mb-1">
                {t('propdev.warranty.filter_severity', {
                  defaultValue: 'Severity',
                })}
              </span>
              <select
                value={filterSeverity}
                onChange={(e) => setFilterSeverity(e.target.value)}
                className={clsx(inputCls, 'max-w-[160px]')}
              >
                <option value="">{t('propdev.warranty.filter_all', { defaultValue: 'All' })}</option>
                <option value="minor">{t('propdev.warranty.severity_minor', { defaultValue: 'Minor' })}</option>
                <option value="major">{t('propdev.warranty.severity_major', { defaultValue: 'Major' })}</option>
                <option value="critical">{t('propdev.warranty.severity_critical', { defaultValue: 'Critical' })}</option>
              </select>
            </label>
          )}
        </div>
        <Button
          variant="primary"
          onClick={() => setCreateOpen(true)}
          disabled={buyers.length === 0 || plots.length === 0}
        >
          <Plus size={14} className="mr-1" />
          {t('propdev.warranty.new_claim', { defaultValue: 'New claim' })}
        </Button>
      </div>

      {claimsQ.isLoading ? (
        <Card padding="md">
          <SkeletonTable rows={3} columns={6} />
        </Card>
      ) : claims.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<ShieldAlert size={22} />}
            title={t('propdev.warranty.empty_title', {
              defaultValue: 'No warranty claims',
            })}
            description={t('propdev.warranty.empty_desc', {
              defaultValue:
                'No claims match the current filters. Use "New claim" to raise one for a buyer.',
            })}
          />
        </Card>
      ) : (
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-2.5 text-left">{t('propdev.plot', { defaultValue: 'Plot' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('propdev.warranty.buyer', { defaultValue: 'Buyer' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('propdev.category', { defaultValue: 'Category' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('propdev.warranty.severity', { defaultValue: 'Severity' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('propdev.description', { defaultValue: 'Description' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('propdev.status', { defaultValue: 'Status' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('propdev.warranty.in_warranty', { defaultValue: 'In warranty' })}</th>
                  <th className="px-4 py-2.5 text-right">{t('common.actions', { defaultValue: 'Actions' })}</th>
                </tr>
              </thead>
              <tbody>
                {claims.map((c: WarrantyClaim) => {
                  const plot = plotMap.get(c.plot_id);
                  const buyer = buyerMap.get(c.buyer_id);
                  return (
                    <tr key={c.id} className="border-t border-border-light">
                      <td className="px-4 py-2 text-xs">{plot?.plot_number ?? '—'}</td>
                      <td className="px-4 py-2 text-xs">{buyer?.full_name ?? '—'}</td>
                      <td className="px-4 py-2 text-xs">
                        {t(`propdev.warranty.cat_${c.category}`, {
                          defaultValue: c.category,
                        })}
                      </td>
                      <td className="px-4 py-2 text-xs">
                        <Badge
                          variant={
                            c.severity === 'critical'
                              ? 'error'
                              : c.severity === 'major'
                                ? 'warning'
                                : 'neutral'
                          }
                          dot
                        >
                          {t(`propdev.warranty.severity_${c.severity}`, {
                            defaultValue: c.severity,
                          })}
                        </Badge>
                      </td>
                      <td className="px-4 py-2 max-w-[320px] truncate" title={c.description}>
                        {c.description}
                      </td>
                      <td className="px-4 py-2">
                        <Badge variant={WARRANTY_VARIANT[c.status]} dot>
                          {t(`propdev.warranty.status_${c.status}`, {
                            defaultValue: c.status,
                          })}
                        </Badge>
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {c.is_in_warranty ? (
                          <Badge variant="success" dot>
                            {t('propdev.warranty.in_warranty_yes', { defaultValue: 'Yes' })}
                          </Badge>
                        ) : (
                          <span className="text-content-tertiary">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <div className="inline-flex gap-1 items-center">
                          <Button
                            variant="ghost"
                            onClick={() => pdfMut.mutate(c.id)}
                            disabled={pdfMut.isPending && pdfMut.variables === c.id}
                            title={t('propdev.warranty.pdf', { defaultValue: 'Download PDF' })}
                          >
                            PDF
                          </Button>
                          {c.status === 'raised' && (
                            <>
                              <Button variant="secondary" onClick={() => action.mutate({ id: c.id, kind: 'accept' })}>
                                {t('propdev.accept', { defaultValue: 'Accept' })}
                              </Button>
                              <Button variant="ghost" onClick={() => action.mutate({ id: c.id, kind: 'review' })}>
                                {t('propdev.warranty.triage', { defaultValue: 'Triage' })}
                              </Button>
                              <Button variant="ghost" onClick={() => action.mutate({ id: c.id, kind: 'reject' })}>
                                {t('propdev.reject', { defaultValue: 'Reject' })}
                              </Button>
                            </>
                          )}
                          {(c.status === 'accepted' || c.status === 'under_review') && (
                            <Button variant="secondary" onClick={() => action.mutate({ id: c.id, kind: 'close' })}>
                              {t('propdev.close', { defaultValue: 'Close' })}
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {createOpen && (
        <CreateWarrantyClaimModal
          buyers={buyers}
          plots={plots}
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            qc.invalidateQueries({ queryKey: ['propdev', 'warranty'] });
          }}
        />
      )}
    </div>
  );
}

function CreateWarrantyClaimModal({
  buyers,
  plots,
  onClose,
  onCreated,
}: {
  buyers: Buyer[];
  plots: Plot[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<{
    buyer_id: string;
    plot_id: string;
    category: WarrantyCategory;
    severity: WarrantySeverity;
    description: string;
    sla_deadline: string;
  }>({
    buyer_id: buyers[0]?.id ?? '',
    plot_id: '',
    category: 'defect',
    severity: 'minor',
    description: '',
    sla_deadline: '',
  });

  const buyer = buyers.find((b) => b.id === form.buyer_id);
  const buyerPlots =
    buyer?.plot_id
      ? plots.filter((p) => p.id === buyer.plot_id)
      : plots;

  useEffect(() => {
    if (!form.plot_id && buyer?.plot_id) {
      setForm((f) => ({ ...f, plot_id: buyer.plot_id ?? '' }));
    }
  }, [form.plot_id, buyer?.plot_id]);

  const mut = useMutation({
    mutationFn: () =>
      createWarrantyClaim({
        buyer_id: form.buyer_id,
        plot_id: form.plot_id,
        category: form.category,
        severity: form.severity,
        description: form.description,
        sla_deadline: form.sla_deadline || null,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.warranty.created', { defaultValue: 'Claim created' }),
      });
      onCreated();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const canSubmit =
    !!form.buyer_id &&
    !!form.plot_id &&
    form.description.trim().length > 0 &&
    !mut.isPending;

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('propdev.warranty.new_claim', { defaultValue: 'New claim' })}
    >
      <div className="space-y-3 p-5">
        <label className="block text-sm">
          <span className="block mb-1 text-content-secondary">
            {t('propdev.warranty.buyer', { defaultValue: 'Buyer' })}
          </span>
          <select
            value={form.buyer_id}
            onChange={(e) =>
              setForm((f) => ({ ...f, buyer_id: e.target.value, plot_id: '' }))
            }
            className={clsx(inputCls, 'w-full')}
          >
            {buyers.map((b) => (
              <option key={b.id} value={b.id}>
                {b.full_name} — {b.email}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="block mb-1 text-content-secondary">
            {t('propdev.warranty.plot', { defaultValue: 'Plot' })}
          </span>
          <select
            value={form.plot_id}
            onChange={(e) => setForm((f) => ({ ...f, plot_id: e.target.value }))}
            className={clsx(inputCls, 'w-full')}
          >
            <option value="">
              {t('propdev.warranty.pick_plot', { defaultValue: 'Pick a plot…' })}
            </option>
            {buyerPlots.map((p) => (
              <option key={p.id} value={p.id}>
                {p.plot_number}
              </option>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm">
            <span className="block mb-1 text-content-secondary">
              {t('propdev.category', { defaultValue: 'Category' })}
            </span>
            <select
              value={form.category}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  category: e.target.value as WarrantyCategory,
                }))
              }
              className={clsx(inputCls, 'w-full')}
            >
              <option value="defect">{t('propdev.warranty.cat_defect', { defaultValue: 'Defect' })}</option>
              <option value="structural">{t('propdev.warranty.cat_structural', { defaultValue: 'Structural' })}</option>
              <option value="cosmetic">{t('propdev.warranty.cat_cosmetic', { defaultValue: 'Cosmetic' })}</option>
              <option value="mep">{t('propdev.warranty.cat_mep', { defaultValue: 'MEP' })}</option>
              <option value="service">{t('propdev.warranty.cat_service', { defaultValue: 'Service' })}</option>
            </select>
          </label>
          <label className="block text-sm">
            <span className="block mb-1 text-content-secondary">
              {t('propdev.warranty.severity', { defaultValue: 'Severity' })}
            </span>
            <select
              value={form.severity}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  severity: e.target.value as WarrantySeverity,
                }))
              }
              className={clsx(inputCls, 'w-full')}
            >
              <option value="minor">{t('propdev.warranty.severity_minor', { defaultValue: 'Minor' })}</option>
              <option value="major">{t('propdev.warranty.severity_major', { defaultValue: 'Major' })}</option>
              <option value="critical">{t('propdev.warranty.severity_critical', { defaultValue: 'Critical' })}</option>
            </select>
          </label>
        </div>
        <label className="block text-sm">
          <span className="block mb-1 text-content-secondary">
            {t('propdev.description', { defaultValue: 'Description' })}
          </span>
          <textarea
            value={form.description}
            onChange={(e) =>
              setForm((f) => ({ ...f, description: e.target.value }))
            }
            rows={4}
            className={clsx(inputCls, 'w-full')}
            placeholder={t('propdev.warranty.describe', {
              defaultValue: 'Describe the defect, observed symptoms, location…',
            })}
          />
        </label>
        <label className="block text-sm">
          <span className="block mb-1 text-content-secondary">
            {t('propdev.warranty.sla_deadline', { defaultValue: 'SLA deadline (optional)' })}
          </span>
          <input
            type="date"
            value={form.sla_deadline}
            onChange={(e) =>
              setForm((f) => ({ ...f, sla_deadline: e.target.value }))
            }
            className={clsx(inputCls, 'w-full max-w-[220px]')}
          />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose} disabled={mut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => mut.mutate()}
            disabled={!canSubmit}
          >
            {mut.isPending ? (
              <Loader2 size={14} className="animate-spin mr-1" />
            ) : (
              <Plus size={14} className="mr-1" />
            )}
            {t('propdev.warranty.file_claim', { defaultValue: 'File claim' })}
          </Button>
        </div>
      </div>
    </WideModal>
  );
}

/* ─── Plot detail drawer ─── */

// Per-plot status transitions. Mirrors the backend
// ``allowed_plot_transitions`` table — keep in sync if it changes.
const PLOT_STATUS_TRANSITIONS: Record<PlotStatus, PlotStatus[]> = {
  planned: ['reserved', 'under_construction', 'ready', 'held', 'blocked'],
  reserved: ['planned', 'sold', 'under_construction', 'ready', 'held'],
  under_construction: ['ready', 'reserved', 'blocked'],
  ready: ['sold', 'reserved', 'held'],
  sold: ['handed_over'],
  handed_over: [],
  held: ['planned', 'reserved', 'ready'],
  blocked: ['planned'],
};

function PlotDetailDrawer({
  plotId,
  plots,
  houseTypes,
  onClose,
}: {
  plotId: string;
  plots: Plot[];
  houseTypes: HouseType[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const canEdit = useMemo(() => {
    if (!userRole) return false;
    const n = userRole.toLowerCase();
    return ['admin', 'superuser', 'owner', 'manager', 'editor'].includes(n);
  }, [userRole]);
  const canDelete = useMemo(() => {
    if (!userRole) return false;
    const n = userRole.toLowerCase();
    return ['admin', 'superuser', 'owner', 'manager'].includes(n);
  }, [userRole]);

  const plot = plots.find((p) => p.id === plotId);
  const ht = plot?.house_type_id ? houseTypes.find((h) => h.id === plot.house_type_id) : null;

  const [editOpen, setEditOpen] = useState(false);
  const [statusMenuOpen, setStatusMenuOpen] = useState(false);
  const { confirm, ...confirmProps } = useConfirm();

  const statusMu = useMutation({
    mutationFn: (next: PlotStatus) => updatePlot(plotId, { status: next }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.plot_status_changed', { defaultValue: 'Plot status updated' }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMu = useMutation({
    mutationFn: () => deletePlot(plotId),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('propdev.plot_deleted', { defaultValue: 'Plot deleted' }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const transitions = plot ? PLOT_STATUS_TRANSITIONS[plot.status] : [];
  const canChangeStatus = canEdit && transitions.length > 0;

  const headerActions = (plot && (canEdit || canDelete)) ? (
    <div className="inline-flex items-center gap-1">
      {canEdit && (
        <button
          type="button"
          onClick={() => setEditOpen(true)}
          className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary"
          data-testid="open-edit-plot"
        >
          <Pencil size={12} />
          {t('common.edit', { defaultValue: 'Edit' })}
        </button>
      )}
      {canDelete && plot.status !== 'sold' && plot.status !== 'handed_over' && (
        <button
          type="button"
          onClick={async () => {
            const ok = await confirm({
              title: t('propdev.delete_plot_title', {
                defaultValue: 'Delete plot?',
              }),
              message: t('propdev.confirm_delete_plot', {
                defaultValue: 'Delete plot {{n}}? This cannot be undone.',
                n: plot.plot_number,
              }),
              confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
              variant: 'danger',
            });
            if (!ok) return;
            deleteMu.mutate();
          }}
          className="inline-flex items-center gap-1 rounded-md border border-rose-200 px-2 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50"
          disabled={deleteMu.isPending}
          data-testid="delete-plot"
        >
          <Trash2 size={12} />
          {t('common.delete', { defaultValue: 'Delete' })}
        </button>
      )}
    </div>
  ) : null;

  return (
    <>
    <SideDrawer
      open={!!plot}
      onClose={onClose}
      widthClass="max-w-lg"
      busy={editOpen}
      aria-labelledby="propdev-plot-drawer-title"
      title={
        plot
          ? t('propdev.plot_n', { defaultValue: 'Plot {{n}}', n: plot.plot_number })
          : ''
      }
      headerActions={headerActions}
    >
      {plot && (
        <>
          {editOpen && (
            <EditPlotModal
              plot={plot}
              houseTypes={houseTypes}
              onClose={() => setEditOpen(false)}
            />
          )}
          <div className="space-y-3 p-5">
            <div className="flex items-center justify-between gap-2">
              {canChangeStatus ? (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setStatusMenuOpen((v) => !v)}
                    className="inline-flex items-center gap-1 rounded-md focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                    aria-haspopup="menu"
                    aria-expanded={statusMenuOpen}
                    data-testid="plot-status-pill"
                  >
                    <Badge variant={PLOT_STATUS_VARIANT[plot.status]} dot>{plot.status}</Badge>
                    <ChevronDown size={12} className="text-content-tertiary" />
                  </button>
                  {statusMenuOpen && (
                    <div role="menu" className="absolute left-0 z-10 mt-1 min-w-[200px] rounded-md border border-border-light bg-surface-primary shadow-lg">
                      <div className="border-b border-border-light px-3 py-1.5 text-[10px] uppercase tracking-wide text-content-tertiary">
                        {t('propdev.move_to', { defaultValue: 'Move to' })}
                      </div>
                      {transitions.map((next) => (
                        <button
                          key={next}
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setStatusMenuOpen(false);
                            statusMu.mutate(next);
                          }}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-surface-secondary focus:bg-surface-secondary focus:outline-none"
                          disabled={statusMu.isPending}
                        >
                          <Badge variant={PLOT_STATUS_VARIANT[next]} dot>{next.replace('_', ' ')}</Badge>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <Badge variant={PLOT_STATUS_VARIANT[plot.status]} dot>{plot.status}</Badge>
              )}
              <span className="text-xs text-content-tertiary">
                {Math.round(toNumber(plot.construction_status_percent))}% {t('propdev.built', { defaultValue: 'built' })}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Field label={t('propdev.house_type', { defaultValue: 'House Type' })} value={ht?.name || ht?.code || plot.house_type_label || '—'} />
              <Field label={t('propdev.area', { defaultValue: 'Area' })} value={`${toNumber(plot.area_m2).toFixed(1)} m²`} />
              <Field label={t('propdev.orientation', { defaultValue: 'Orientation' })} value={plot.orientation || '—'} />
              <Field
                label={t('propdev.garden', { defaultValue: 'Garden' })}
                value={plot.garden_area_m2 != null ? `${toNumber(plot.garden_area_m2).toFixed(1)} m²` : '—'}
              />
              <Field
                label={t('propdev.base_price', { defaultValue: 'Base price' })}
                value={<MoneyDisplay amount={toNumber(plot.price_base)} currency={plot.currency || undefined} />}
              />
              <Field
                label={t('propdev.reserved_until', { defaultValue: 'Reserved until' })}
                value={plot.reservation_deadline ? <DateDisplay value={plot.reservation_deadline} /> : '—'}
              />
            </div>
            {plot.status === 'planned' && (
              <ReserveBlock plotId={plot.id} onSuccess={onClose} />
            )}
            <PlotHandoverSummary plotId={plot.id} />
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                {t('propdev.related', { defaultValue: 'Related records' })}
              </p>
              <ul className="grid grid-cols-1 gap-2">
                <li>
                  <Link
                    to={`/property-dev/developments/${plot.development_id}/geo?plot=${encodeURIComponent(plot.id)}`}
                    className="group flex items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                  >
                    <span className="flex items-center gap-2">
                      <Globe2 size={12} className="text-content-tertiary group-hover:text-oe-blue" />
                      <span>{t('propdev.view_plot_on_map', { defaultValue: 'Plot {{n}} on map', n: plot.plot_number })}</span>
                    </span>
                    <ArrowRight size={11} className="text-content-tertiary group-hover:text-oe-blue" />
                  </Link>
                </li>
                <li>
                  <Link
                    to="/contracts"
                    className="group flex items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                  >
                    <span className="flex items-center gap-2">
                      <FileSignature size={12} className="text-content-tertiary group-hover:text-oe-blue" />
                      <span>{t('propdev.view_contracts', { defaultValue: 'Sales contracts' })}</span>
                    </span>
                    <ArrowRight size={11} className="text-content-tertiary group-hover:text-oe-blue" />
                  </Link>
                </li>
              </ul>
            </div>
          </div>
        </>
      )}
    </SideDrawer>
    <ConfirmDialog {...confirmProps} />
    </>
  );
}

/**
 * Compact handover + warranty summary for the Plot drawer. Always
 * makes the user aware of the live state without opening the
 * Handovers tab: shows # scheduled, # completed, open snag count
 * across the linked handover(s), and open warranty count on the plot.
 */
function PlotHandoverSummary({ plotId }: { plotId: string }) {
  const { t } = useTranslation();
  const handoversQ = useQuery({
    queryKey: ['propdev', 'handovers', plotId],
    queryFn: () => listHandovers(plotId),
    staleTime: 60_000,
  });
  const warrantyQ = useQuery({
    queryKey: ['propdev', 'warranty', 'by-plot', plotId],
    queryFn: () => listWarrantyClaims({ plot_id: plotId }),
    staleTime: 60_000,
  });
  const handovers = handoversQ.data ?? [];
  const claims = warrantyQ.data ?? [];
  const scheduled = handovers.filter((h) => !h.completed_at).length;
  const completed = handovers.filter((h) => !!h.completed_at).length;
  const openClaims = claims.filter(
    (c) => c.status === 'raised' || c.status === 'under_review' || c.status === 'accepted',
  ).length;
  if (handoversQ.isLoading) {
    return (
      <div className="text-xs text-content-tertiary">
        {t('common.loading', { defaultValue: 'Loading…' })}
      </div>
    );
  }
  if (handovers.length === 0 && claims.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
        {t('propdev.handover_state', { defaultValue: 'Handover state' })}
      </p>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-center">
          <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
            {t('propdev.scheduled', { defaultValue: 'Scheduled' })}
          </p>
          <p className="text-lg font-semibold tabular-nums">{scheduled}</p>
        </div>
        <div className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-center">
          <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
            {t('propdev.completed', { defaultValue: 'Completed' })}
          </p>
          <p className="text-lg font-semibold tabular-nums">{completed}</p>
        </div>
        <div className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-center">
          <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
            {t('propdev.warranty_open_label', {
              defaultValue: 'Warranty open',
            })}
          </p>
          <p
            className={
              'text-lg font-semibold tabular-nums ' +
              (openClaims > 0 ? 'text-rose-700' : '')
            }
          >
            {openClaims}
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * Inline edit modal for an existing plot. Pre-fills every field from
 * the current plot and submits a partial PATCH so untouched fields
 * round-trip unchanged. Status transitions go through the separate
 * status-pill menu so the rules in ``PLOT_STATUS_TRANSITIONS`` apply.
 */
function EditPlotModal({
  plot,
  houseTypes,
  onClose,
}: {
  plot: Plot;
  houseTypes: HouseType[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    house_type_id: plot.house_type_id || '',
    house_type_label: plot.house_type_label || '',
    level_in_block: plot.level_in_block != null ? String(plot.level_in_block) : '',
    position_on_floor: plot.position_on_floor || '',
    area_m2: String(toNumber(plot.area_m2)),
    balcony_area_m2: plot.balcony_area_m2 != null ? String(toNumber(plot.balcony_area_m2)) : '',
    garden_area_m2: plot.garden_area_m2 != null ? String(toNumber(plot.garden_area_m2)) : '',
    storage_area_m2: plot.storage_area_m2 != null ? String(toNumber(plot.storage_area_m2)) : '',
    bedrooms: String(plot.bedrooms ?? 0),
    bathrooms: String(plot.bathrooms ?? 0),
    parking_spaces: String(plot.parking_spaces ?? 0),
    orientation: plot.orientation || '',
    view_type: plot.view_type || '',
    sun_exposure_hours: plot.sun_exposure_hours != null ? String(toNumber(plot.sun_exposure_hours)) : '',
    price_base: String(toNumber(plot.price_base)),
    currency: plot.currency || '',
  });
  const submit = async () => {
    setBusy(true);
    const optNum = (v: string): number | undefined => {
      const tt = v.trim();
      if (!tt) return undefined;
      const n = Number(tt);
      return Number.isFinite(n) ? n : undefined;
    };
    const optStr = (v: string): string | undefined => {
      const tt = v.trim();
      return tt ? tt : undefined;
    };
    try {
      await updatePlot(plot.id, {
        house_type_id: form.house_type_id || undefined,
        house_type_label: optStr(form.house_type_label),
        level_in_block: optNum(form.level_in_block),
        position_on_floor: optStr(form.position_on_floor),
        orientation: optStr(form.orientation),
        view_type: optStr(form.view_type),
        area_m2: Number(form.area_m2) || 0,
        balcony_area_m2: optNum(form.balcony_area_m2),
        garden_area_m2: optNum(form.garden_area_m2),
        storage_area_m2: optNum(form.storage_area_m2),
        bedrooms: Number(form.bedrooms) || 0,
        bathrooms: Number(form.bathrooms) || 0,
        parking_spaces: Number(form.parking_spaces) || 0,
        sun_exposure_hours: optNum(form.sun_exposure_hours),
        price_base: form.price_base.trim() || '0',
        currency: optStr(form.currency),
      });
      addToast({ type: 'success', title: t('propdev.plot_updated', { defaultValue: 'Plot updated' }) });
      qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
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
      title={t('propdev.edit_plot', { defaultValue: 'Edit plot {{n}}', n: plot.plot_number })}
      size="xl"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button variant="primary" onClick={submit} loading={busy}>{t('common.save', { defaultValue: 'Save' })}</Button>
        </>
      }
    >
      <WideModalSection columns={3}>
        <WideModalField label={t('propdev.house_type', { defaultValue: 'House type' })}>
          <select
            value={form.house_type_id}
            onChange={(e) => setForm((s) => ({ ...s, house_type_id: e.target.value }))}
            className={inputCls}
          >
            <option value="">— {t('common.none', { defaultValue: 'None' })} —</option>
            {houseTypes.map((h) => (
              <option key={h.id} value={h.id}>{h.code} — {h.name}</option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('property_dev.house_type.title', { defaultValue: 'House type (catalogue)' })} span={2}>
          <input
            value={form.house_type_label}
            onChange={(e) => setForm((s) => ({ ...s, house_type_label: e.target.value }))}
            className={inputCls}
            maxLength={120}
          />
        </WideModalField>
        <WideModalField label={t('propdev.plot.level_in_block', { defaultValue: 'Floor / level' })}>
          <input type="number" value={form.level_in_block} onChange={(e) => setForm((s) => ({ ...s, level_in_block: e.target.value }))} className={inputCls} min={-10} max={200} />
        </WideModalField>
        <WideModalField label={t('propdev.plot.position_on_floor', { defaultValue: 'Position on floor' })} span={2}>
          <input value={form.position_on_floor} onChange={(e) => setForm((s) => ({ ...s, position_on_floor: e.target.value }))} className={inputCls} maxLength={40} />
        </WideModalField>
        <WideModalField label={t('propdev.plot.area_m2', { defaultValue: 'Area (m²)' })}>
          <input type="number" value={form.area_m2} onChange={(e) => setForm((s) => ({ ...s, area_m2: e.target.value }))} className={inputCls} min={0} step="0.01" />
        </WideModalField>
        <WideModalField label={t('propdev.plot.balcony_area_m2', { defaultValue: 'Balcony (m²)' })}>
          <input type="number" value={form.balcony_area_m2} onChange={(e) => setForm((s) => ({ ...s, balcony_area_m2: e.target.value }))} className={inputCls} min={0} step="0.01" />
        </WideModalField>
        <WideModalField label={t('propdev.plot.garden_area_m2', { defaultValue: 'Garden (m²)' })}>
          <input type="number" value={form.garden_area_m2} onChange={(e) => setForm((s) => ({ ...s, garden_area_m2: e.target.value }))} className={inputCls} min={0} step="0.01" />
        </WideModalField>
        <WideModalField label={t('propdev.plot.storage_area_m2', { defaultValue: 'Storage (m²)' })}>
          <input type="number" value={form.storage_area_m2} onChange={(e) => setForm((s) => ({ ...s, storage_area_m2: e.target.value }))} className={inputCls} min={0} step="0.01" />
        </WideModalField>
        <WideModalField label={t('propdev.plot.bedrooms', { defaultValue: 'Bedrooms' })}>
          <input type="number" value={form.bedrooms} onChange={(e) => setForm((s) => ({ ...s, bedrooms: e.target.value }))} className={inputCls} min={0} max={20} />
        </WideModalField>
        <WideModalField label={t('propdev.plot.bathrooms', { defaultValue: 'Bathrooms' })}>
          <input type="number" value={form.bathrooms} onChange={(e) => setForm((s) => ({ ...s, bathrooms: e.target.value }))} className={inputCls} min={0} max={20} />
        </WideModalField>
        <WideModalField label={t('propdev.plot.parking_spaces', { defaultValue: 'Parking spaces' })}>
          <input type="number" value={form.parking_spaces} onChange={(e) => setForm((s) => ({ ...s, parking_spaces: e.target.value }))} className={inputCls} min={0} max={20} />
        </WideModalField>
        <WideModalField label={t('propdev.plot.orientation', { defaultValue: 'Orientation' })}>
          <select value={form.orientation} onChange={(e) => setForm((s) => ({ ...s, orientation: e.target.value }))} className={inputCls}>
            <option value="">— {t('common.none', { defaultValue: 'None' })} —</option>
            {PLOT_ORIENTATIONS.map((o) => (<option key={o} value={o}>{o}</option>))}
          </select>
        </WideModalField>
        <WideModalField label={t('propdev.plot.view_type', { defaultValue: 'View type' })}>
          <select value={form.view_type} onChange={(e) => setForm((s) => ({ ...s, view_type: e.target.value }))} className={inputCls}>
            <option value="">— {t('common.none', { defaultValue: 'None' })} —</option>
            {PLOT_VIEW_TYPES.map((v) => (<option key={v} value={v}>{v}</option>))}
          </select>
        </WideModalField>
        <WideModalField label={t('propdev.plot.sun_exposure_hours', { defaultValue: 'Sun exposure (h)' })}>
          <input type="number" value={form.sun_exposure_hours} onChange={(e) => setForm((s) => ({ ...s, sun_exposure_hours: e.target.value }))} className={inputCls} min={0} max={24} step="0.1" />
        </WideModalField>
        <WideModalField label={t('propdev.base_price', { defaultValue: 'Base price' })}>
          <input type="number" value={form.price_base} onChange={(e) => setForm((s) => ({ ...s, price_base: e.target.value }))} className={inputCls} min={0} step="0.01" />
        </WideModalField>
        <WideModalField label={t('propdev.plot.currency', { defaultValue: 'Currency' })}>
          <input value={form.currency} onChange={(e) => setForm((s) => ({ ...s, currency: e.target.value.toUpperCase().slice(0, 3) }))} className={inputCls} maxLength={3} placeholder="EUR" />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

function ReserveBlock({ plotId, onSuccess }: { plotId: string; onSuccess: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    full_name: '',
    email: '',
    reservation_deadline: todayIso(30),
  });
  const mut = useMutation({
    mutationFn: () => reservePlot(plotId, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
      qc.invalidateQueries({ queryKey: ['propdev', 'buyers'] });
      addToast({ type: 'success', title: t('propdev.plot_reserved', { defaultValue: 'Plot reserved' }) });
      onSuccess();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  return (
    <Card padding="sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
        {t('propdev.reserve_plot', { defaultValue: 'Reserve plot' })}
      </p>
      <div className="space-y-2">
        <input
          value={form.full_name}
          onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          placeholder={t('propdev.full_name', { defaultValue: 'Full name' })}
          className={inputCls}
        />
        <input
          type="email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          placeholder={t('propdev.email', { defaultValue: 'Email' })}
          className={inputCls}
        />
        <input
          type="date"
          value={form.reservation_deadline}
          onChange={(e) => setForm({ ...form, reservation_deadline: e.target.value })}
          className={inputCls}
        />
        <Button
          variant="primary"
          icon={mut.isPending ? <Loader2 size={14} /> : <Check size={14} />}
          loading={mut.isPending}
          onClick={() => mut.mutate()}
          disabled={!form.full_name || !form.email}
        >
          {t('propdev.reserve', { defaultValue: 'Reserve' })}
        </Button>
      </div>
    </Card>
  );
}

/* ─── Buyer detail drawer with stage progression ─── */

function BuyerDetailDrawer({
  buyerId,
  buyers,
  plots,
  developmentId,
  onClose,
}: {
  buyerId: string;
  buyers: Buyer[];
  plots: Plot[];
  developmentId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  // Role-gated edit affordance. The backend ``property_dev.update``
  // permission resolves to EDITOR+ via the central permission registry —
  // mirror that gate here so viewers don't even see the button.
  // Mirrors the check used in /admin/permissions and elsewhere; admins,
  // managers and editors get write access.
  const userRole = useAuthStore((s) => s.userRole);
  const canEdit = useMemo(() => {
    if (!userRole) return false;
    const normalized = userRole.toLowerCase();
    return ['admin', 'superuser', 'owner', 'manager', 'editor'].includes(normalized);
  }, [userRole]);
  const canDelete = useMemo(() => {
    if (!userRole) return false;
    const normalized = userRole.toLowerCase();
    return ['admin', 'superuser', 'owner', 'manager'].includes(normalized);
  }, [userRole]);
  const [editOpen, setEditOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const buyer = buyers.find((b) => b.id === buyerId);
  const plot = buyer?.plot_id ? plots.find((p) => p.id === buyer.plot_id) : null;
  const selectionsQ = useQuery({
    queryKey: ['propdev', 'selections', buyerId],
    queryFn: () => listSelections(buyerId),
    enabled: !!buyer,
  });
  const items = selectionsQ.data ?? [];
  const freezeDays = daysUntil(buyer?.freeze_deadline);
  // Delete + cancel mutations. Both invalidate the buyers list so the
  // table refreshes immediately. Delete also closes the drawer; cancel
  // leaves it open so the forfeiture summary stays on screen.
  const deleteMut = useMutation({
    mutationFn: () => deleteBuyer(buyerId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'buyers'] });
      addToast({
        type: 'success',
        title: t('propdev.buyer_deleted', { defaultValue: 'Buyer deleted' }),
      });
      setConfirmDelete(false);
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const cancelMut = useMutation({
    mutationFn: () =>
      cancelBuyer(buyerId, {
        cancelled_at: todayIso(),
        reason: t('propdev.cancel_reason_default', {
          defaultValue: 'Cancelled via UI',
        }),
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['propdev', 'buyers'] });
      addToast({
        type: 'success',
        title: t('propdev.buyer_cancelled', { defaultValue: 'Buyer cancelled' }),
        // The forfeiture summary is the most important piece of info
        // after a cancel — surface it inline so the user does not have
        // to click into Finance to find out what they just signed off.
        message: t('propdev.forfeiture_summary', {
          defaultValue: 'Forfeited {{f}} / refundable {{r}}',
          f: String(res.forfeited_amount),
          r: String(res.refundable_amount),
        }),
      });
      setConfirmCancel(false);
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  // SideDrawer owns Escape; suppress it via ``busy`` while the
  // EditBuyerModal or a confirm dialog is open so the nested Escape
  // handler closes them first instead of collapsing the drawer
  // underneath. EditBuyerModal still attaches its handler at capture
  // phase so it wins the race for the keystroke.
  const headerActions = (
    <div className="flex items-center gap-1">
      {canEdit && (
        <button
          type="button"
          onClick={() => setEditOpen(true)}
          className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary"
          data-testid="open-edit-buyer"
        >
          <Pencil size={12} />
          {t('propdev.edit_buyer', { defaultValue: 'Edit' })}
        </button>
      )}
      {canEdit &&
        buyer &&
        buyer.status !== 'cancelled' &&
        buyer.status !== 'completed' && (
          <button
            type="button"
            onClick={() => setConfirmCancel(true)}
            className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-xs font-medium text-amber-700 hover:bg-amber-50 hover:border-amber-300"
            data-testid="cancel-buyer-btn"
            title={t('propdev.cancel_buyer_hint', {
              defaultValue: 'Cancel buyer and compute deposit forfeiture',
            })}
          >
            <XCircle size={12} />
            {t('propdev.cancel_buyer', { defaultValue: 'Cancel' })}
          </button>
        )}
      {canDelete && (
        <button
          type="button"
          onClick={() => setConfirmDelete(true)}
          className="inline-flex items-center gap-1 rounded-md border border-rose-200 px-2 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50"
          data-testid="delete-buyer-btn"
        >
          <Trash2 size={12} />
          {t('common.delete', { defaultValue: 'Delete' })}
        </button>
      )}
    </div>
  );
  return (
    <SideDrawer
      open={!!buyer}
      onClose={onClose}
      widthClass="max-w-xl"
      busy={editOpen || confirmDelete || confirmCancel}
      aria-labelledby="propdev-buyer-drawer-title"
      title={buyer ? buyer.full_name || buyer.email : ''}
      subtitle={buyer?.email}
      headerActions={headerActions}
    >
      {buyer && (
        <>
          {editOpen && (
            <EditBuyerModal
              open={editOpen}
              buyer={buyer}
              plots={plots}
              developmentId={developmentId}
              onClose={() => setEditOpen(false)}
            />
          )}
          <ConfirmDialog
            open={confirmDelete}
            onCancel={() => setConfirmDelete(false)}
            onConfirm={() => deleteMut.mutate()}
            loading={deleteMut.isPending}
            variant="danger"
            title={t('propdev.delete_buyer_title', {
              defaultValue: 'Delete buyer?',
            })}
            message={t('propdev.delete_buyer_msg', {
              defaultValue:
                'This permanently removes the buyer and any unbilled selections. Contracts and finance entries are kept. This cannot be undone.',
            })}
          />
          <ConfirmDialog
            open={confirmCancel}
            onCancel={() => setConfirmCancel(false)}
            onConfirm={() => cancelMut.mutate()}
            loading={cancelMut.isPending}
            variant="warning"
            confirmLabel={t('propdev.cancel_buyer_confirm', {
              defaultValue: 'Cancel buyer',
            })}
            title={t('propdev.cancel_buyer_title', {
              defaultValue: 'Cancel buyer?',
            })}
            message={t('propdev.cancel_buyer_msg', {
              defaultValue:
                'Marks the buyer as cancelled, releases the plot back to inventory and computes jurisdiction-specific deposit forfeiture. Reversible only by an admin.',
            })}
          />
          <div className="space-y-4 p-5">
          <StageProgress current={buyer.status} />

          <div className="grid grid-cols-2 gap-3 text-sm">
            <Field
              label={t('propdev.plot', { defaultValue: 'Plot' })}
              value={plot ? plot.plot_number : '—'}
            />
            <Field
              label={t('propdev.contract_value', { defaultValue: 'Contract' })}
              value={
                <MoneyDisplay
                  amount={toNumber(buyer.contract_value)}
                  currency={buyer.currency || undefined}
                />
              }
            />
            <Field
              label={t('propdev.signed', { defaultValue: 'Signed' })}
              value={buyer.contract_signed_at ? <DateDisplay value={buyer.contract_signed_at} /> : '—'}
            />
            <Field
              label={t('propdev.deposit', { defaultValue: 'Deposit' })}
              value={buyer.deposit_paid_at ? <DateDisplay value={buyer.deposit_paid_at} /> : '—'}
            />
          </div>

          {buyer.freeze_deadline && freezeDays != null && (
            <Card padding="sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                    {t('propdev.freeze_deadline', { defaultValue: 'Freeze deadline' })}
                  </p>
                  <p className="mt-0.5 text-sm">
                    <DateDisplay value={buyer.freeze_deadline} />
                  </p>
                </div>
                <div className={clsx(
                  'rounded-lg px-3 py-2 text-center',
                  freezeDays < 0
                    ? 'bg-rose-100 text-rose-800'
                    : freezeDays < 7
                      ? 'bg-amber-100 text-amber-800'
                      : 'bg-sky-100 text-sky-800',
                )}>
                  <p className="text-2xl font-semibold leading-none">
                    {Math.abs(freezeDays)}
                  </p>
                  <p className="mt-0.5 text-[10px] uppercase tracking-wide">
                    {freezeDays < 0
                      ? t('propdev.days_overdue', { defaultValue: 'days overdue' })
                      : t('propdev.days_left', { defaultValue: 'days left' })}
                  </p>
                </div>
              </div>
            </Card>
          )}

          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
              {t('propdev.selections', { defaultValue: 'Buyer selections' })}
            </p>
            {selectionsQ.isLoading ? (
              <SkeletonTable rows={2} columns={3} />
            ) : items.length === 0 ? (
              <p className="text-sm text-content-tertiary">
                {t('propdev.no_selections', { defaultValue: 'No selections recorded yet.' })}
              </p>
            ) : (
              <ul className="space-y-1.5">
                {items.map((s) => (
                  <li key={s.id} className="flex items-center justify-between rounded border border-border-light px-3 py-2 text-sm">
                    <span>
                      <Badge variant={s.status === 'locked' ? 'success' : 'neutral'}>{s.status}</Badge>
                      <span className="ml-2 text-content-secondary text-xs">
                        <DateDisplay value={s.created_at} />
                      </span>
                    </span>
                    <span className="font-medium">
                      <MoneyDisplay amount={toNumber(s.total_options_value)} currency={buyer.currency || undefined} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Cross-module quick-links — the buyer record sits at the
              centre of a small graph (plot ↔ contract ↔ finance ↔
              handover). Surface that graph as a stack of links so the
              user can jump across modules without leaving the drawer.
              Each link uses ``react-router`` so the SPA navigates
              client-side. */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
              {t('propdev.related', { defaultValue: 'Related records' })}
            </p>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {plot && (
                <li>
                  <Link
                    to={`/property-dev/developments/${developmentId}/geo?plot=${encodeURIComponent(plot.id)}`}
                    className="group flex items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                  >
                    <span className="flex items-center gap-2">
                      <Grid3X3
                        size={12}
                        className="text-content-tertiary group-hover:text-oe-blue"
                      />
                      <span>
                        {t('propdev.view_plot_on_map', {
                          defaultValue: 'Plot {{n}} on map',
                          n: plot.plot_number,
                        })}
                      </span>
                    </span>
                    <ArrowRight
                      size={11}
                      className="text-content-tertiary group-hover:text-oe-blue"
                    />
                  </Link>
                </li>
              )}
              <li>
                {/* Scope the Finance jump to this buyer (and plot when set)
                    so the target can land on the buyer's invoices/payments
                    once it consumes the params. The query is harmless to a
                    target that ignores it - it still opens Finance. */}
                <Link
                  to={`/finance?buyer=${encodeURIComponent(buyer.id)}${
                    plot ? `&plot=${encodeURIComponent(plot.id)}` : ''
                  }`}
                  className="group flex items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                >
                  <span className="flex items-center gap-2">
                    <Wallet
                      size={12}
                      className="text-content-tertiary group-hover:text-oe-blue"
                    />
                    <span>
                      {t('propdev.view_finance', {
                        defaultValue: 'Finance & payments',
                      })}
                    </span>
                  </span>
                  <ArrowRight
                    size={11}
                    className="text-content-tertiary group-hover:text-oe-blue"
                  />
                </Link>
              </li>
              <li>
                {/* Carry plot + buyer so Contracts can pre-filter to this
                    sale once it reads the params. */}
                <Link
                  to={`/contracts?buyer=${encodeURIComponent(buyer.id)}${
                    plot ? `&plot=${encodeURIComponent(plot.id)}` : ''
                  }`}
                  className="group flex items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                >
                  <span className="flex items-center gap-2">
                    <FileSignature
                      size={12}
                      className="text-content-tertiary group-hover:text-oe-blue"
                    />
                    <span>
                      {t('propdev.view_contracts', {
                        defaultValue: 'Sales contracts',
                      })}
                    </span>
                  </span>
                  <ArrowRight
                    size={11}
                    className="text-content-tertiary group-hover:text-oe-blue"
                  />
                </Link>
              </li>
              <li>
                {/* When the buyer is bridged to a Contacts record, the most
                    useful "open in CRM" target is that exact contact card.
                    The Contacts page already consumes ?contactId (scroll +
                    flash). Fall back to the CRM landing if unbridged. */}
                <Link
                  to={
                    buyer.contact_id
                      ? `/contacts?contactId=${encodeURIComponent(buyer.contact_id)}`
                      : '/crm'
                  }
                  className="group flex items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                >
                  <span className="flex items-center gap-2">
                    <Users
                      size={12}
                      className="text-content-tertiary group-hover:text-oe-blue"
                    />
                    <span>
                      {buyer.contact_id
                        ? t('propdev.view_contact', {
                            defaultValue: 'Open buyer contact',
                          })
                        : t('propdev.view_crm', {
                            defaultValue: 'Open in CRM',
                          })}
                    </span>
                  </span>
                  <ArrowRight
                    size={11}
                    className="text-content-tertiary group-hover:text-oe-blue"
                  />
                </Link>
              </li>
            </ul>
          </div>

          {buyer.status === 'reserved' && (
            <ContractBuyerBlock buyer={buyer} />
          )}

          {/* Buyer self-service portal magic-link panel (manager+ only) */}
          <BuyerAccessLinkPanel buyerId={buyer.id} />

          <LinkedContactCard
            contactId={buyer.contact_id ?? null}
            fallbackName={buyer.full_name || buyer.email}
          />
        </div>
        </>
      )}
    </SideDrawer>
  );
}

function StageProgress({ current }: { current: BuyerStatus }) {
  const { t } = useTranslation();
  const labels: Record<BuyerStatus, string> = {
    lead: t('propdev.stage_lead', { defaultValue: 'Lead' }),
    reserved: t('propdev.stage_reserved', { defaultValue: 'Reserved' }),
    contracted: t('propdev.stage_contracted', { defaultValue: 'Contracted' }),
    completed: t('propdev.stage_handover', { defaultValue: 'Handover' }),
    cancelled: t('propdev.stage_cancelled', { defaultValue: 'Cancelled' }),
  };
  if (current === 'cancelled') {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-center text-sm text-rose-800">
        {labels.cancelled}
      </div>
    );
  }
  const idx = BUYER_STAGE_ORDER.indexOf(current);
  return (
    <div className="flex items-center justify-between gap-1">
      {BUYER_STAGE_ORDER.map((s, i) => {
        const active = i <= idx;
        const reached = i < idx;
        return (
          <div key={s} className="flex items-center flex-1 min-w-0">
            <div className="flex flex-col items-center flex-1 min-w-0">
              <div className={clsx(
                'flex h-7 w-7 items-center justify-center rounded-full border-2 text-xs font-semibold',
                active
                  ? 'border-oe-blue bg-oe-blue text-white'
                  : 'border-border bg-surface-primary text-content-tertiary',
              )}>
                {reached ? <Check size={12} /> : i + 1}
              </div>
              <span className={clsx(
                'mt-1 text-[10px] uppercase tracking-wide truncate max-w-full',
                active ? 'text-content-primary font-medium' : 'text-content-tertiary',
              )}>
                {labels[s]}
              </span>
            </div>
            {i < BUYER_STAGE_ORDER.length - 1 && (
              <div className={clsx(
                'h-0.5 flex-1 -mt-4',
                i < idx ? 'bg-oe-blue' : 'bg-border',
              )} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function ContractBuyerBlock({ buyer }: { buyer: Buyer }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const prefCurrency = usePreferencesStore((s) => s.currency);
  const [form, setForm] = useState({
    contract_value: String(toNumber(buyer.contract_value)),
    currency: buyer.currency || prefCurrency,
    contract_signed_at: todayIso(),
    freeze_deadline: todayIso(60),
  });
  const mut = useMutation({
    mutationFn: () =>
      contractBuyer(buyer.id, {
        contract_value: form.contract_value.trim() || '0',
        currency: form.currency,
        contract_signed_at: form.contract_signed_at,
        freeze_deadline: form.freeze_deadline,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['propdev', 'buyers'] });
      addToast({ type: 'success', title: t('propdev.contract_signed', { defaultValue: 'Contract signed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  return (
    <Card padding="sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
        {t('propdev.sign_contract', { defaultValue: 'Sign contract' })}
      </p>
      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <input
            type="number"
            value={form.contract_value}
            onChange={(e) => setForm({ ...form, contract_value: e.target.value })}
            placeholder={t('propdev.contract_value', { defaultValue: 'Contract value' })}
            className={inputCls}
          />
          <input
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
            placeholder={prefCurrency}
            className={inputCls}
            maxLength={3}
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={labelCls}>{t('propdev.signed', { defaultValue: 'Signed' })}</label>
            <input
              type="date"
              value={form.contract_signed_at}
              onChange={(e) => setForm({ ...form, contract_signed_at: e.target.value })}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>{t('propdev.freeze_deadline', { defaultValue: 'Freeze deadline' })}</label>
            <input
              type="date"
              value={form.freeze_deadline}
              onChange={(e) => setForm({ ...form, freeze_deadline: e.target.value })}
              className={inputCls}
            />
          </div>
        </div>
        <Button
          variant="primary"
          icon={mut.isPending ? <Loader2 size={14} /> : <Check size={14} />}
          loading={mut.isPending}
          onClick={() => mut.mutate()}
        >
          {t('propdev.contract', { defaultValue: 'Contract' })}
        </Button>
      </div>
    </Card>
  );
}

function Field({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
    </div>
  );
}

/* ─── Create modal ─── */

function CreateModal({
  kind,
  developmentId,
  developments,
  houseTypes,
  onClose,
}: {
  kind: Tab;
  developmentId: string;
  developments: Development[];
  houseTypes: HouseType[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const prefCurrency = usePreferencesStore((s) => s.currency);
  const [busy, setBusy] = useState(false);

  // The active project comes from the global app-shell context (top of
  // the page) — the user already picked one there. Reading it lets us
  // drop the duplicate project picker from the development create form
  // entirely, which was the friction the user explicitly called out
  // ("зачем выбирать проект — если он уже выбран в верхнем меню").
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  // Development create form. project_id is implicit (taken from the
  // app-shell context at submit time); only the fields we actually
  // surface in the modal live here. Everything is a string until submit
  // so empty inputs map to "no value" rather than "explicit zero" — the
  // backend keeps its own defaults intact when fields are omitted.
  const [devForm, setDevForm] = useState({
    code: '',
    name: '',
    description: '',
    dev_type: 'residential' as DevelopmentType,
    // Location
    location_address: '',
    country_code: '',
    latitude: '',
    longitude: '',
    // Scope
    total_plots: '',
    total_area_m2: '',
    total_floors: '',
    // Timeline (ISO date strings, validated by the backend pattern)
    start_date: '',
    launch_date: '',
    completion_date: '',
    sales_phase: 'planning' as Development['sales_phase'],
    // Commercial
    sales_target_amount: '',
    currency: prefCurrency,
    // People (free-form names; FK to Companies module is out of scope here)
    developer_name: '',
    architect_name: '',
    general_contractor_name: '',
    // Marketing assets (URLs only — file uploads belong in the Documents module)
    cover_image_url: '',
    brochure_url: '',
    website_url: '',
  });
  // Plot form. development_id is implicit (taken from the page's
  // selected development at submit time) — the picker UI was removed
  // because the user already chooses a development at the top of the
  // page, and forcing them to re-pick it inside every create form is a
  // friction the user explicitly called out.
  const [plotForm, setPlotForm] = useState({
    plot_number: '',
    house_type_id: '',
    house_type_label: '',
    status: 'planned' as PlotStatus,
    // Position
    level_in_block: '',
    position_on_floor: '',
    // Dimensions
    area_m2: '0',
    balcony_area_m2: '',
    garden_area_m2: '',
    storage_area_m2: '',
    bedrooms: '0',
    bathrooms: '0',
    parking_spaces: '0',
    // Orientation / view
    orientation: '',
    view_type: '',
    sun_exposure_hours: '',
    // Pricing
    price_base: '0',
    currency: prefCurrency,
  });
  const [htForm, setHtForm] = useState({
    development_id: developmentId,
    code: '',
    name: '',
    bedrooms: 3,
    total_area_m2: '120',
    base_price: '0',
    currency: prefCurrency,
  });
  const [buyerForm, setBuyerForm] = useState({
    development_id: developmentId,
    full_name: '',
    email: '',
    phone: '',
  });
  // Lead create form. development_id is implicit (from page picker) but
  // optional — inbound web-form leads frequently arrive before the
  // agent has picked which development they belong to.
  const [leadForm, setLeadForm] = useState({
    development_id: developmentId,
    full_name: '',
    email: '',
    phone: '',
    source: 'other' as LeadSource,
    lead_score: '0',
    notes: '',
  });
  // ── Contacts-bridge opt-in (v3117) ──────────────────────────────
  // Default ON: every new Lead / Buyer also creates/links a Contacts
  // directory entry with the appropriate module tag. The user can
  // toggle this off for portal-driven anonymous signups where the
  // legal entity hasn't been disclosed yet. See the bridge module
  // doc for the full sync semantics.
  const [syncToContacts, setSyncToContacts] = useState(true);

  const submit = async () => {
    setBusy(true);
    try {
      if (kind === 'developments') {
        if (!activeProjectId) {
          throw new Error(
            t('propdev.select_project_first', {
              defaultValue: 'Select a project at the top of the page first.',
            }),
          );
        }
        if (!devForm.code.trim()) {
          throw new Error(
            t('propdev.code_required', { defaultValue: 'Code is required.' }),
          );
        }
        // Only send optional fields when the user actually typed
        // something. An empty string in a numeric input would otherwise
        // serialize as 0 and overwrite the server default ("no floors
        // planned" vs "explicit 0 floors").
        const optNum = (v: string): number | undefined => {
          const trimmed = v.trim();
          if (!trimmed) return undefined;
          const n = Number(trimmed);
          return Number.isFinite(n) ? n : undefined;
        };
        const optStr = (v: string): string | undefined => {
          const trimmed = v.trim();
          return trimmed ? trimmed : undefined;
        };
        await createDevelopment({
          project_id: activeProjectId,
          code: devForm.code.trim(),
          name: optStr(devForm.name),
          description: optStr(devForm.description),
          dev_type: devForm.dev_type,
          location_address: optStr(devForm.location_address),
          country_code: optStr(devForm.country_code.toUpperCase()),
          latitude: optNum(devForm.latitude),
          longitude: optNum(devForm.longitude),
          total_plots: optNum(devForm.total_plots),
          total_area_m2: optNum(devForm.total_area_m2),
          total_floors: optNum(devForm.total_floors),
          sales_phase: devForm.sales_phase,
          start_date: optStr(devForm.start_date),
          launch_date: optStr(devForm.launch_date),
          completion_date: optStr(devForm.completion_date),
          sales_target_amount: optNum(devForm.sales_target_amount),
          // Currency: only send when it's non-default-blank. Empty string
          // means "fall back to the parent project's currency" on read.
          currency: optStr(devForm.currency),
          developer_name: optStr(devForm.developer_name),
          architect_name: optStr(devForm.architect_name),
          general_contractor_name: optStr(devForm.general_contractor_name),
          cover_image_url: optStr(devForm.cover_image_url),
          brochure_url: optStr(devForm.brochure_url),
          website_url: optStr(devForm.website_url),
        });
        addToast({ type: 'success', title: t('propdev.development_created', { defaultValue: 'Development created' }) });
        qc.invalidateQueries({ queryKey: ['propdev', 'developments'] });
      } else if (kind === 'plots') {
        // development_id is taken from the page-level selection (the
        // user picks a development at the top of the page; we do not
        // ask them to pick it again here).
        if (!developmentId) {
          throw new Error(
            t('propdev.select_development_first', {
              defaultValue: 'Select a development at the top of the page first.',
            }),
          );
        }
        if (!plotForm.plot_number) {
          throw new Error(
            t('propdev.plot_number_required', {
              defaultValue: 'Plot number is required.',
            }),
          );
        }
        // Only send optional fields when the user actually entered
        // something. An empty string in a numeric input would otherwise
        // serialize as 0 and overwrite the model default (e.g.
        // "no balcony" vs "0 m² balcony"). For numeric fields with a
        // 0 default (bedrooms etc.) we keep sending 0 so the explicit
        // zero round-trips.
        const optNum = (v: string): number | undefined => {
          const trimmed = v.trim();
          if (!trimmed) return undefined;
          const n = Number(trimmed);
          return Number.isFinite(n) ? n : undefined;
        };
        const optStr = (v: string): string | undefined => {
          const trimmed = v.trim();
          return trimmed ? trimmed : undefined;
        };
        await createPlot({
          development_id: developmentId,
          plot_number: plotForm.plot_number,
          house_type_id: plotForm.house_type_id || undefined,
          house_type_label: optStr(plotForm.house_type_label),
          status: plotForm.status,
          level_in_block: optNum(plotForm.level_in_block),
          position_on_floor: optStr(plotForm.position_on_floor),
          orientation: optStr(plotForm.orientation),
          view_type: optStr(plotForm.view_type),
          area_m2: Number(plotForm.area_m2) || 0,
          balcony_area_m2: optNum(plotForm.balcony_area_m2),
          garden_area_m2: optNum(plotForm.garden_area_m2),
          storage_area_m2: optNum(plotForm.storage_area_m2),
          bedrooms: Number(plotForm.bedrooms) || 0,
          bathrooms: Number(plotForm.bathrooms) || 0,
          parking_spaces: Number(plotForm.parking_spaces) || 0,
          sun_exposure_hours: optNum(plotForm.sun_exposure_hours),
          price_base: plotForm.price_base.trim() || '0',
          currency: plotForm.currency,
        });
        addToast({ type: 'success', title: t('propdev.plot_created', { defaultValue: 'Plot created' }) });
        qc.invalidateQueries({ queryKey: ['propdev', 'plots'] });
      } else if (kind === 'house_types') {
        if (!htForm.development_id) throw new Error('Development required');
        if (!htForm.code) throw new Error('Code required');
        await createHouseType({
          development_id: htForm.development_id,
          code: htForm.code,
          name: htForm.name,
          bedrooms: htForm.bedrooms,
          total_area_m2: Number(htForm.total_area_m2) || 0,
          base_price: htForm.base_price.trim() || '0',
          currency: htForm.currency,
        });
        addToast({ type: 'success', title: t('propdev.house_type_created', { defaultValue: 'House type created' }) });
        qc.invalidateQueries({ queryKey: ['propdev', 'house-types'] });
      } else if (kind === 'buyers') {
        if (!buyerForm.development_id) throw new Error('Development required');
        if (!buyerForm.email) throw new Error('Email required');
        await createBuyer(
          {
            development_id: buyerForm.development_id,
            full_name: buyerForm.full_name,
            email: buyerForm.email,
            phone: buyerForm.phone || undefined,
          },
          { syncToContacts },
        );
        addToast({ type: 'success', title: t('propdev.buyer_created', { defaultValue: 'Buyer created' }) });
        qc.invalidateQueries({ queryKey: ['propdev', 'buyers'] });
        // Invalidate the Contacts list too — the new mirror entry shows up
        // in the directory immediately when sync_to_contacts is on.
        if (syncToContacts) qc.invalidateQueries({ queryKey: ['contacts'] });
      } else if (kind === 'leads') {
        if (!leadForm.email && !leadForm.full_name) {
          throw new Error(
            t('propdev.lead_identity_required', {
              defaultValue: 'Either email or full name is required.',
            }),
          );
        }
        await createLead(
          {
            development_id: leadForm.development_id || undefined,
            full_name: leadForm.full_name || undefined,
            email: leadForm.email || undefined,
            phone: leadForm.phone || undefined,
            source: leadForm.source,
            lead_score: Number(leadForm.lead_score) || 0,
            notes: leadForm.notes || undefined,
          },
          { syncToContacts },
        );
        addToast({
          type: 'success',
          title: t('propdev.lead_created', { defaultValue: 'Lead created' }),
        });
        qc.invalidateQueries({ queryKey: ['propdev', 'leads'] });
        if (syncToContacts) qc.invalidateQueries({ queryKey: ['contacts'] });
      } else {
        throw new Error('Not supported');
      }
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const title =
    kind === 'developments'
      ? t('propdev.new_development', { defaultValue: 'New Development' })
      : kind === 'plots'
        ? t('propdev.new_plot', { defaultValue: 'New Plot' })
        : kind === 'house_types'
          ? t('propdev.new_house_type', { defaultValue: 'New House Type' })
          : kind === 'leads'
            ? t('propdev.new_lead', { defaultValue: 'New Lead' })
            : kind === 'buyers'
              ? t('propdev.new_buyer', { defaultValue: 'New Buyer' })
              : t('common.create', { defaultValue: 'Create' });

  // house_types uses a triplet (bedrooms/area/base_price); xl gives it
  // room. The plots form has 5 sections (ID / position / dimensions /
  // view / pricing). The developments form now has 6 sections
  // (Identification / Location / Scope / Timeline / Sales / People +
  // marketing) so it also wants xl. The remaining variant (buyers) is
  // only 4 short fields — lg is plenty.
  const size =
    kind === 'house_types' || kind === 'plots' || kind === 'developments'
      ? 'xl'
      : 'lg';

  return (
    <WideModal
      open
      onClose={onClose}
      title={title}
      size={size}
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
      {kind === 'developments' && (
        <DevelopmentFormBody
          devForm={devForm}
          setDevForm={setDevForm}
          activeProjectId={activeProjectId}
          activeProjectName={activeProjectName}
        />
      )}
      {kind === 'plots' && (
        <PlotFormBody
          plotForm={plotForm}
          setPlotForm={setPlotForm}
          houseTypes={houseTypes}
          activeDevelopment={developments.find((d) => d.id === developmentId)}
          hasDevelopment={!!developmentId}
        />
      )}
      {kind === 'house_types' && (
        <WideModalSection columns={3}>
          <WideModalField
            label={t('propdev.code', { defaultValue: 'Code' })}
            required
          >
            <input
              value={htForm.code}
              onChange={(e) => setHtForm({ ...htForm, code: e.target.value })}
              className={inputCls}
              placeholder="TYPE-A"
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.name', { defaultValue: 'Name' })}
            span={2}
          >
            <input
              value={htForm.name}
              onChange={(e) => setHtForm({ ...htForm, name: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.bedrooms', { defaultValue: 'Bedrooms' })}
          >
            <input
              type="number"
              value={htForm.bedrooms}
              onChange={(e) => setHtForm({ ...htForm, bedrooms: Number(e.target.value) || 0 })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('propdev.area', { defaultValue: 'Area' })}>
            <input
              type="number"
              value={htForm.total_area_m2}
              onChange={(e) => setHtForm({ ...htForm, total_area_m2: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.base_price', { defaultValue: 'Base price' })}
          >
            <input
              type="number"
              value={htForm.base_price}
              onChange={(e) => setHtForm({ ...htForm, base_price: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
        </WideModalSection>
      )}
      {kind === 'buyers' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('propdev.full_name', { defaultValue: 'Full name' })}
            span={2}
          >
            <input
              value={buyerForm.full_name}
              onChange={(e) => setBuyerForm({ ...buyerForm, full_name: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.email', { defaultValue: 'Email' })}
            required
          >
            <input
              type="email"
              value={buyerForm.email}
              onChange={(e) => setBuyerForm({ ...buyerForm, email: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('propdev.phone', { defaultValue: 'Phone' })}>
            <input
              value={buyerForm.phone}
              onChange={(e) => setBuyerForm({ ...buyerForm, phone: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <div className="sm:col-span-2">
            <SyncToContactsToggle
              checked={syncToContacts}
              onChange={setSyncToContacts}
            />
          </div>
        </WideModalSection>
      )}
      {kind === 'leads' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('propdev.full_name', { defaultValue: 'Full name' })}
            span={2}
          >
            <input
              value={leadForm.full_name}
              onChange={(e) =>
                setLeadForm({ ...leadForm, full_name: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.email', { defaultValue: 'Email' })}
            hint={t('propdev.lead_email_hint', {
              defaultValue: 'Either email or full name is required.',
            })}
          >
            <input
              type="email"
              value={leadForm.email}
              onChange={(e) =>
                setLeadForm({ ...leadForm, email: e.target.value })
              }
              className={inputCls}
              data-testid="new-lead-email"
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.phone', { defaultValue: 'Phone' })}
          >
            <input
              value={leadForm.phone}
              onChange={(e) =>
                setLeadForm({ ...leadForm, phone: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.lead_source', { defaultValue: 'Source' })}
          >
            <select
              value={leadForm.source}
              onChange={(e) =>
                setLeadForm({
                  ...leadForm,
                  source: e.target.value as LeadSource,
                })
              }
              className={inputCls}
            >
              {LEAD_SOURCES.map((src) => (
                <option key={src} value={src}>
                  {t(`propdev.lead_source_${src}`, {
                    defaultValue: src.replace('_', ' '),
                  })}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('propdev.lead_score', { defaultValue: 'Score (0-100)' })}
            hint={t('propdev.lead_score_hint', {
              defaultValue:
                'Your qualification confidence - 0 = cold, 50 = warm, 100 = hot. Drives the Leads list sort order.',
            })}
          >
            <input
              type="number"
              min={0}
              max={100}
              value={leadForm.lead_score}
              onChange={(e) =>
                setLeadForm({ ...leadForm, lead_score: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('propdev.notes', { defaultValue: 'Notes' })}
            span={2}
          >
            <textarea
              rows={3}
              value={leadForm.notes}
              onChange={(e) =>
                setLeadForm({ ...leadForm, notes: e.target.value })
              }
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
          <div className="sm:col-span-2">
            <SyncToContactsToggle
              checked={syncToContacts}
              onChange={setSyncToContacts}
            />
          </div>
        </WideModalSection>
      )}
    </WideModal>
  );
}

/* ─── Sync-to-contacts toggle ─────────────────────────────────────
 *
 * Tiny reusable inline checkbox + explanatory copy. Used by the
 * CreateLead / CreateBuyer modals so the user can opt out of the
 * Contacts directory mirror (rare; portal-driven anonymous signups).
 * Default ON because the directory should normally be authoritative.
 */
function SyncToContactsToggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <label className="flex items-start gap-2.5 rounded-md border border-border-light bg-surface-secondary/60 p-2.5 cursor-pointer hover:bg-surface-secondary">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-border-light text-oe-blue focus:ring-2 focus:ring-oe-blue/40"
        data-testid="sync-to-contacts-toggle"
      />
      <div className="min-w-0">
        <p className="text-xs font-medium text-content-primary inline-flex items-center gap-1.5">
          <LinkIcon size={11} aria-hidden="true" />
          {t('propdev.sync_to_contacts', {
            defaultValue: 'Sync to Contacts directory',
          })}
        </p>
        <p className="text-[11px] text-content-tertiary mt-0.5 leading-snug">
          {t('propdev.sync_to_contacts_hint', {
            defaultValue:
              'Mirrors this entry into the Contacts module. If a contact with the same email already exists it is linked, otherwise a new contact is created and tagged.',
          })}
        </p>
      </div>
    </label>
  );
}

/* ─── Development create form body ─── */

// Shape of the development create form. project_id is intentionally
// absent — it comes from the global app-shell project context, so the
// user does not get re-asked to pick a project they already chose.
// Every numeric/date input is a string until submit so empty values map
// to "no value" rather than "explicit zero / today".
interface DevelopmentFormState {
  code: string;
  name: string;
  description: string;
  dev_type: DevelopmentType;
  location_address: string;
  country_code: string;
  latitude: string;
  longitude: string;
  total_plots: string;
  total_area_m2: string;
  total_floors: string;
  start_date: string;
  launch_date: string;
  completion_date: string;
  sales_phase: Development['sales_phase'];
  sales_target_amount: string;
  currency: string;
  developer_name: string;
  architect_name: string;
  general_contractor_name: string;
  cover_image_url: string;
  brochure_url: string;
  website_url: string;
}

const DEV_TYPES: DevelopmentType[] = [
  'residential',
  'mixed_use',
  'commercial',
  'industrial',
  'hospitality',
  'resort',
  'senior_living',
  'student_housing',
  'retail',
  'office',
  'logistics',
  'other',
];

// Shared between this form and the Plot catalogue picker — keeping the
// list inline avoids a circular import vs the catalogue picker which
// owns the more elaborate localised labels.
const DEV_COUNTRY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: '—' },
  { value: 'DE', label: 'Deutschland (DE)' },
  { value: 'US', label: 'United States (US)' },
  { value: 'UK', label: 'United Kingdom (UK)' },
  { value: 'RU', label: 'Россия (RU)' },
  { value: 'TR', label: 'Türkiye (TR)' },
  { value: 'FR', label: 'France (FR)' },
  { value: 'ES', label: 'España (ES)' },
  { value: 'IT', label: 'Italia (IT)' },
  { value: 'PL', label: 'Polska (PL)' },
  { value: 'JP', label: '日本 (JP)' },
  { value: 'CN', label: '中国 (CN)' },
  { value: 'SA', label: 'السعودية (SA)' },
];

const DEV_SALES_PHASES: DevelopmentSalesPhase[] = [
  'planning',
  'launch',
  'sales',
  'handover',
  'closed',
];

function DevelopmentFormBody({
  devForm,
  setDevForm,
  activeProjectId,
  activeProjectName,
}: {
  devForm: DevelopmentFormState;
  setDevForm: React.Dispatch<React.SetStateAction<DevelopmentFormState>>;
  activeProjectId: string | null;
  activeProjectName: string;
}) {
  const { t } = useTranslation();
  const set = <K extends keyof DevelopmentFormState>(
    key: K,
    value: DevelopmentFormState[K],
  ) => setDevForm((prev) => ({ ...prev, [key]: value }));

  // No active project → the user has nothing to attach the development
  // to. Show a single banner with a clear next step and bail; the
  // Create button will still fire submit() which raises the same
  // message, so we are belt-and-suspenders here.
  if (!activeProjectId) {
    return (
      <div
        className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-3 text-xs text-amber-900"
        role="alert"
      >
        {t('propdev.select_project_first', {
          defaultValue: 'Select a project at the top of the page first.',
        })}
      </div>
    );
  }

  return (
    <>
      {/* Context banner — mirrors the plot form so the user knows which
        project this development will be attached to. */}
      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs">
        <span className="font-semibold uppercase tracking-wide text-content-tertiary">
          {t('propdev.project', { defaultValue: 'Project' })}
        </span>
        <span className="font-medium text-content-primary">
          {activeProjectName ||
            t('propdev.unknown_project', { defaultValue: 'Selected project' })}
        </span>
      </div>

      {/* Identification */}
      <WideModalSection
        columns={2}
        title={t('propdev.development.section_id', {
          defaultValue: 'Identification',
        })}
      >
        <WideModalField
          label={t('propdev.development.code', { defaultValue: 'Code' })}
          required
          hint={t('propdev.development.code_hint', {
            defaultValue: 'Short machine-readable identifier (e.g. DEV-001).',
          })}
        >
          <input
            value={devForm.code}
            onChange={(e) => set('code', e.target.value)}
            className={inputCls}
            placeholder="DEV-001"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.name', { defaultValue: 'Name' })}
        >
          <input
            value={devForm.name}
            onChange={(e) => set('name', e.target.value)}
            className={inputCls}
            placeholder={t('propdev.development.name_placeholder', {
              defaultValue: 'Marketing name (e.g. Riverside Gardens)',
            })}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.type', { defaultValue: 'Type' })}
        >
          <select
            value={devForm.dev_type}
            onChange={(e) => set('dev_type', e.target.value as DevelopmentType)}
            className={inputCls}
          >
            {DEV_TYPES.map((dt) => (
              <option key={dt} value={dt}>
                {t(`propdev.development.type.${dt}`, {
                  defaultValue: dt.replace('_', ' '),
                })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.development.sales_phase', {
            defaultValue: 'Sales phase',
          })}
        >
          <select
            value={devForm.sales_phase}
            onChange={(e) =>
              set('sales_phase', e.target.value as Development['sales_phase'])
            }
            className={inputCls}
          >
            {DEV_SALES_PHASES.map((p) => (
              <option key={p} value={p}>
                {t(`propdev.development.sales_phase.${p}`, { defaultValue: p })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.development.description', {
            defaultValue: 'Description',
          })}
          span={2}
        >
          <textarea
            value={devForm.description}
            onChange={(e) => set('description', e.target.value)}
            className={`${inputCls} h-20 py-2`}
            rows={3}
          />
        </WideModalField>
      </WideModalSection>

      {/* Location & country */}
      <WideModalSection
        columns={2}
        title={t('propdev.development.section_location', {
          defaultValue: 'Location & country',
        })}
      >
        <WideModalField
          label={t('propdev.development.address', { defaultValue: 'Address' })}
          span={2}
        >
          <input
            value={devForm.location_address}
            onChange={(e) => set('location_address', e.target.value)}
            className={inputCls}
            placeholder={t('propdev.development.address_placeholder', {
              defaultValue: 'Street, city, postcode',
            })}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.country', { defaultValue: 'Country' })}
          hint={t('propdev.development.country_hint', {
            defaultValue:
              'Drives the house-type catalogue and the tax engine.',
          })}
        >
          <select
            value={devForm.country_code}
            onChange={(e) => set('country_code', e.target.value)}
            className={inputCls}
          >
            {DEV_COUNTRY_OPTIONS.map((c) => (
              <option key={c.value || 'none'} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.development.currency', {
            defaultValue: 'Currency',
          })}
          hint={t('propdev.development.currency_hint', {
            defaultValue:
              'Default currency for plots & sales targets. Leave blank to inherit from the project.',
          })}
        >
          <input
            value={devForm.currency}
            onChange={(e) => set('currency', e.target.value.toUpperCase().slice(0, 3))}
            className={inputCls}
            placeholder="EUR"
            maxLength={3}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.latitude', { defaultValue: 'Latitude' })}
        >
          <input
            type="number"
            step="0.0000001"
            value={devForm.latitude}
            onChange={(e) => set('latitude', e.target.value)}
            className={inputCls}
            placeholder="52.5200"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.longitude', { defaultValue: 'Longitude' })}
        >
          <input
            type="number"
            step="0.0000001"
            value={devForm.longitude}
            onChange={(e) => set('longitude', e.target.value)}
            className={inputCls}
            placeholder="13.4050"
          />
        </WideModalField>
      </WideModalSection>

      {/* Scope */}
      <WideModalSection
        columns={3}
        title={t('propdev.development.section_scope', {
          defaultValue: 'Scope',
        })}
      >
        <WideModalField
          label={t('propdev.development.total_plots', {
            defaultValue: 'Total plots / units',
          })}
        >
          <input
            type="number"
            min={0}
            value={devForm.total_plots}
            onChange={(e) => set('total_plots', e.target.value)}
            className={inputCls}
            placeholder="0"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.total_area_m2', {
            defaultValue: 'Total area (m²)',
          })}
        >
          <input
            type="number"
            min={0}
            step="0.01"
            value={devForm.total_area_m2}
            onChange={(e) => set('total_area_m2', e.target.value)}
            className={inputCls}
            placeholder="0"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.total_floors', {
            defaultValue: 'Floors',
          })}
        >
          <input
            type="number"
            min={0}
            value={devForm.total_floors}
            onChange={(e) => set('total_floors', e.target.value)}
            className={inputCls}
            placeholder="0"
          />
        </WideModalField>
      </WideModalSection>

      {/* Timeline */}
      <WideModalSection
        columns={3}
        title={t('propdev.development.section_timeline', {
          defaultValue: 'Timeline',
        })}
      >
        <WideModalField
          label={t('propdev.development.start_date', {
            defaultValue: 'Construction start',
          })}
        >
          <input
            type="date"
            value={devForm.start_date}
            onChange={(e) => set('start_date', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.launch_date', {
            defaultValue: 'Sales launch',
          })}
        >
          <input
            type="date"
            value={devForm.launch_date}
            onChange={(e) => set('launch_date', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.completion_date', {
            defaultValue: 'Expected completion',
          })}
        >
          <input
            type="date"
            value={devForm.completion_date}
            onChange={(e) => set('completion_date', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>

      {/* Sales target */}
      <WideModalSection
        columns={2}
        title={t('propdev.development.section_sales', {
          defaultValue: 'Sales target',
        })}
      >
        <WideModalField
          label={t('propdev.development.sales_target_amount', {
            defaultValue: 'Total sales target',
          })}
          hint={t('propdev.development.sales_target_hint', {
            defaultValue:
              'Used by the dashboard progress bar and the cashflow forecast.',
          })}
          span={2}
        >
          <div className="flex gap-2">
            <input
              type="number"
              min={0}
              step="0.01"
              value={devForm.sales_target_amount}
              onChange={(e) => set('sales_target_amount', e.target.value)}
              className={`${inputCls} flex-1`}
              placeholder="0"
            />
            <input
              value={devForm.currency}
              onChange={(e) => set('currency', e.target.value.toUpperCase().slice(0, 3))}
              className={`${inputCls} w-24`}
              placeholder="EUR"
              maxLength={3}
              aria-label={t('propdev.development.currency', {
                defaultValue: 'Currency',
              })}
            />
          </div>
        </WideModalField>
      </WideModalSection>

      {/* People & marketing */}
      <WideModalSection
        columns={2}
        title={t('propdev.development.section_people', {
          defaultValue: 'People & marketing',
        })}
      >
        <WideModalField
          label={t('propdev.development.developer_name', {
            defaultValue: 'Developer / sponsor',
          })}
        >
          <input
            value={devForm.developer_name}
            onChange={(e) => set('developer_name', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.architect_name', {
            defaultValue: 'Architect',
          })}
        >
          <input
            value={devForm.architect_name}
            onChange={(e) => set('architect_name', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.general_contractor_name', {
            defaultValue: 'General contractor',
          })}
          span={2}
        >
          <input
            value={devForm.general_contractor_name}
            onChange={(e) => set('general_contractor_name', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.cover_image_url', {
            defaultValue: 'Cover image URL',
          })}
          span={2}
        >
          <input
            type="url"
            value={devForm.cover_image_url}
            onChange={(e) => set('cover_image_url', e.target.value)}
            className={inputCls}
            placeholder="https://…"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.brochure_url', {
            defaultValue: 'Brochure URL',
          })}
        >
          <input
            type="url"
            value={devForm.brochure_url}
            onChange={(e) => set('brochure_url', e.target.value)}
            className={inputCls}
            placeholder="https://…"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.development.website_url', {
            defaultValue: 'Website',
          })}
        >
          <input
            type="url"
            value={devForm.website_url}
            onChange={(e) => set('website_url', e.target.value)}
            className={inputCls}
            placeholder="https://…"
          />
        </WideModalField>
      </WideModalSection>
    </>
  );
}

/* ─── Plot create form body ─── */

// Shape of the plot create form. Kept inline (instead of API-shape) so
// every numeric/text input stays a string until submit — empty strings
// matter for "no value" vs "explicit zero".
interface PlotFormState {
  plot_number: string;
  house_type_id: string;
  house_type_label: string;
  status: PlotStatus;
  level_in_block: string;
  position_on_floor: string;
  area_m2: string;
  balcony_area_m2: string;
  garden_area_m2: string;
  storage_area_m2: string;
  bedrooms: string;
  bathrooms: string;
  parking_spaces: string;
  orientation: string;
  view_type: string;
  sun_exposure_hours: string;
  price_base: string;
  currency: string;
}

const PLOT_ORIENTATIONS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const;
const PLOT_VIEW_TYPES = [
  'sea',
  'mountain',
  'garden',
  'courtyard',
  'street',
  'park',
  'forest',
  'lake',
  'river',
  'city',
  'other',
] as const;
const PLOT_STATUSES: PlotStatus[] = [
  'planned',
  'reserved',
  'under_construction',
  'ready',
  'sold',
  'handed_over',
];

function PlotFormBody({
  plotForm,
  setPlotForm,
  houseTypes,
  activeDevelopment,
  hasDevelopment,
}: {
  plotForm: PlotFormState;
  setPlotForm: React.Dispatch<React.SetStateAction<PlotFormState>>;
  houseTypes: HouseType[];
  activeDevelopment: Development | undefined;
  hasDevelopment: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const set = <K extends keyof PlotFormState>(
    key: K,
    value: PlotFormState[K],
  ) => setPlotForm((prev) => ({ ...prev, [key]: value }));

  // House-type catalogue picker — country-scoped presets + tenant
  // entries. The dropdown is populated by /property-dev/house-type-catalogue
  // and the catalogue entry name is mirrored into ``house_type_label`` so
  // the existing Plot.house_type_label column persists the choice
  // without needing a schema change.
  const projectId = activeDevelopment?.project_id;
  const devCountry =
    ((activeDevelopment?.metadata as Record<string, unknown> | undefined)
      ?.country_code as string | undefined) ?? '';
  const [catalogueCountry, setCatalogueCountry] = useState<string>(devCountry);
  useEffect(() => {
    setCatalogueCountry(devCountry);
  }, [devCountry]);

  const catalogueQ = useQuery({
    queryKey: [
      'propdev',
      'house-type-catalogue',
      catalogueCountry || 'all',
      projectId || 'none',
    ],
    queryFn: () =>
      fetchHouseTypes(catalogueCountry || undefined, projectId || undefined),
    staleTime: 60_000,
  });
  const catalogue: HouseTypeCatalogueEntry[] = catalogueQ.data ?? [];

  const [addingNewType, setAddingNewType] = useState(false);
  const [newTypeForm, setNewTypeForm] = useState({ code: '', name: '' });
  const [creatingType, setCreatingType] = useState(false);

  const submitNewType = async () => {
    if (!projectId) {
      addToast({
        type: 'error',
        title: t('property_dev.house_type.no_project_for_new_type', {
          defaultValue:
            'Select a development tied to a project before creating a custom house type.',
        }),
      });
      return;
    }
    const code = newTypeForm.code
      .trim()
      .toUpperCase()
      .replace(/[^A-Z0-9_]/g, '_');
    const name = newTypeForm.name.trim();
    if (!code || !name) {
      addToast({
        type: 'error',
        title: t('property_dev.house_type.code_and_name_required', {
          defaultValue: 'Both code and name are required.',
        }),
      });
      return;
    }
    setCreatingType(true);
    try {
      const created = await createHouseTypeCatalogue({
        project_id: projectId,
        country_code: catalogueCountry || null,
        code,
        name,
      });
      addToast({
        type: 'success',
        title: t('property_dev.house_type.created', {
          defaultValue: 'House type added',
        }),
      });
      await qc.invalidateQueries({
        queryKey: ['propdev', 'house-type-catalogue'],
      });
      // Auto-select the new entry — mirror its name into the label
      // field which is what the backend persists for catalogue picks.
      set('house_type_label', created.name);
      setAddingNewType(false);
      setNewTypeForm({ code: '', name: '' });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setCreatingType(false);
    }
  };

  const COUNTRY_OPTIONS: Array<{ value: string; label: string }> = [
    {
      value: '',
      label: t('property_dev.house_type.country_all', {
        defaultValue: 'All countries',
      }),
    },
    { value: 'DE', label: 'Deutschland (DE)' },
    { value: 'US', label: 'United States (US)' },
    { value: 'UK', label: 'United Kingdom (UK)' },
    { value: 'RU', label: 'Россия (RU)' },
    { value: 'TR', label: 'Türkiye (TR)' },
    { value: 'FR', label: 'France (FR)' },
    { value: 'ES', label: 'España (ES)' },
    { value: 'IT', label: 'Italia (IT)' },
    { value: 'PL', label: 'Polska (PL)' },
    { value: 'JP', label: '日本 (JP)' },
    { value: 'CN', label: '中国 (CN)' },
    { value: 'SA', label: 'السعودية (SA)' },
  ];

  return (
    <>
      {/* Context banner: confirms which development the plot will be
        attached to, removing the need for an in-form picker. */}
      {hasDevelopment ? (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs">
          <span className="font-semibold uppercase tracking-wide text-content-tertiary">
            {t('propdev.development', { defaultValue: 'Development' })}
          </span>
          <span className="font-medium text-content-primary">
            {activeDevelopment
              ? `${activeDevelopment.code}${activeDevelopment.name ? ` - ${activeDevelopment.name}` : ''}`
              : t('propdev.unknown_development', { defaultValue: 'Selected development' })}
          </span>
        </div>
      ) : (
        <div
          className="mb-4 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
          role="alert"
        >
          {t('propdev.select_development_first', {
            defaultValue: 'Select a development at the top of the page first.',
          })}
        </div>
      )}

      {/* Identification */}
      <WideModalSection
        columns={2}
        title={t('propdev.plot.section_id', { defaultValue: 'Identification' })}
      >
        <WideModalField
          label={t('propdev.plot_number', { defaultValue: 'Plot number' })}
          required
        >
          <input
            value={plotForm.plot_number}
            onChange={(e) => set('plot_number', e.target.value)}
            className={inputCls}
            placeholder="P-001"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.status', { defaultValue: 'Status' })}
        >
          <select
            value={plotForm.status}
            onChange={(e) => set('status', e.target.value as PlotStatus)}
            className={inputCls}
          >
            {PLOT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`propdev.plot.status.${s}`, { defaultValue: s.replace('_', ' ') })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.house_type', { defaultValue: 'House type' })}
        >
          <select
            value={plotForm.house_type_id}
            onChange={(e) => set('house_type_id', e.target.value)}
            className={inputCls}
          >
            <option value="">— {t('common.none', { defaultValue: 'None' })} —</option>
            {houseTypes.map((h) => (
              <option key={h.id} value={h.id}>
                {h.code} — {h.name}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('property_dev.house_type.title', {
            defaultValue: 'House type (catalogue)',
          })}
          hint={t('property_dev.house_type.picker_hint', {
            defaultValue:
              'Pick a country preset or create your own. The label is stored on the plot.',
          })}
          span={2}
        >
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <select
                value={catalogueCountry}
                onChange={(e) => setCatalogueCountry(e.target.value)}
                className={clsx(inputCls, 'max-w-[200px]')}
                aria-label={t('property_dev.house_type.country_label', {
                  defaultValue: 'Country',
                })}
              >
                {COUNTRY_OPTIONS.map((c) => (
                  <option key={c.value || '_all_'} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
              <select
                value={plotForm.house_type_label}
                onChange={(e) => set('house_type_label', e.target.value)}
                className={clsx(inputCls, 'min-w-[200px] flex-1')}
              >
                <option value="">
                  — {t('property_dev.house_type.none', { defaultValue: 'None' })} —
                </option>
                {catalogue.map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.is_preset ? '★ ' : ''}
                    {c.name}
                    {c.country_code ? ` (${c.country_code})` : ''}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="secondary"
                icon={<Plus size={12} />}
                onClick={() => setAddingNewType((v) => !v)}
                disabled={!projectId}
                title={
                  projectId
                    ? undefined
                    : t('property_dev.house_type.no_project_for_new_type', {
                        defaultValue:
                          'Select a development tied to a project before creating a custom house type.',
                      })
                }
              >
                {t('property_dev.house_type.add_new', {
                  defaultValue: 'Add new...',
                })}
              </Button>
            </div>
            {addingNewType && (
              <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div>
                    <label className={labelCls}>
                      {t('property_dev.house_type.code_label', {
                        defaultValue: 'Code',
                      })}
                    </label>
                    <input
                      value={newTypeForm.code}
                      onChange={(e) =>
                        setNewTypeForm((s) => ({ ...s, code: e.target.value }))
                      }
                      className={inputCls}
                      placeholder="MY_TOWNHOUSE"
                      maxLength={40}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>
                      {t('property_dev.house_type.name_label', {
                        defaultValue: 'Display name',
                      })}
                    </label>
                    <input
                      value={newTypeForm.name}
                      onChange={(e) =>
                        setNewTypeForm((s) => ({ ...s, name: e.target.value }))
                      }
                      className={inputCls}
                      placeholder={t('property_dev.house_type.name_placeholder', {
                        defaultValue: 'e.g. Modern Townhouse',
                      })}
                      maxLength={120}
                    />
                  </div>
                </div>
                <div className="mt-2 flex gap-2">
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={submitNewType}
                    loading={creatingType}
                    disabled={creatingType}
                  >
                    {t('property_dev.house_type.save', {
                      defaultValue: 'Save & select',
                    })}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setAddingNewType(false);
                      setNewTypeForm({ code: '', name: '' });
                    }}
                    disabled={creatingType}
                  >
                    {t('common.cancel', { defaultValue: 'Cancel' })}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </WideModalField>
      </WideModalSection>

      {/* Position inside block */}
      <WideModalSection
        columns={2}
        title={t('propdev.plot.section_position', { defaultValue: 'Position' })}
        description={t('propdev.plot.section_position_desc', {
          defaultValue:
            'Floor and position on the floor plan. Block linkage can be set later.',
        })}
      >
        <WideModalField
          label={t('propdev.plot.level_in_block', { defaultValue: 'Floor / level' })}
        >
          <input
            type="number"
            value={plotForm.level_in_block}
            onChange={(e) => set('level_in_block', e.target.value)}
            className={inputCls}
            placeholder="0"
            min={-10}
            max={200}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.position_on_floor', {
            defaultValue: 'Position on floor',
          })}
          hint={t('propdev.plot.position_on_floor_hint', {
            defaultValue: 'e.g. NE corner, unit A, left wing',
          })}
        >
          <input
            value={plotForm.position_on_floor}
            onChange={(e) => set('position_on_floor', e.target.value)}
            className={inputCls}
            maxLength={40}
          />
        </WideModalField>
      </WideModalSection>

      {/* Dimensions & layout */}
      <WideModalSection
        columns={3}
        title={t('propdev.plot.section_dimensions', {
          defaultValue: 'Dimensions & layout',
        })}
      >
        <WideModalField
          label={t('propdev.plot.area_m2', { defaultValue: 'Area (m²)' })}
        >
          <input
            type="number"
            value={plotForm.area_m2}
            onChange={(e) => set('area_m2', e.target.value)}
            className={inputCls}
            min={0}
            step="0.01"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.balcony_area_m2', {
            defaultValue: 'Balcony (m²)',
          })}
        >
          <input
            type="number"
            value={plotForm.balcony_area_m2}
            onChange={(e) => set('balcony_area_m2', e.target.value)}
            className={inputCls}
            min={0}
            step="0.01"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.garden_area_m2', {
            defaultValue: 'Garden (m²)',
          })}
        >
          <input
            type="number"
            value={plotForm.garden_area_m2}
            onChange={(e) => set('garden_area_m2', e.target.value)}
            className={inputCls}
            min={0}
            step="0.01"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.storage_area_m2', {
            defaultValue: 'Storage unit (m²)',
          })}
          hint={t('propdev.plot.storage_area_m2_hint', {
            defaultValue: 'Leave blank if no storage is included.',
          })}
        >
          <input
            type="number"
            value={plotForm.storage_area_m2}
            onChange={(e) => set('storage_area_m2', e.target.value)}
            className={inputCls}
            min={0}
            step="0.01"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.bedrooms', { defaultValue: 'Bedrooms' })}
        >
          <input
            type="number"
            value={plotForm.bedrooms}
            onChange={(e) => set('bedrooms', e.target.value)}
            className={inputCls}
            min={0}
            max={20}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.bathrooms', { defaultValue: 'Bathrooms' })}
        >
          <input
            type="number"
            value={plotForm.bathrooms}
            onChange={(e) => set('bathrooms', e.target.value)}
            className={inputCls}
            min={0}
            max={20}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.parking_spaces', {
            defaultValue: 'Parking spaces',
          })}
        >
          <input
            type="number"
            value={plotForm.parking_spaces}
            onChange={(e) => set('parking_spaces', e.target.value)}
            className={inputCls}
            min={0}
            max={20}
          />
        </WideModalField>
      </WideModalSection>

      {/* Orientation / view */}
      <WideModalSection
        columns={3}
        title={t('propdev.plot.section_view', {
          defaultValue: 'Orientation & view',
        })}
      >
        <WideModalField
          label={t('propdev.plot.orientation', { defaultValue: 'Orientation' })}
          hint={t('propdev.plot.orientation_hint', {
            defaultValue: 'Compass direction the main façade faces.',
          })}
        >
          <select
            value={plotForm.orientation}
            onChange={(e) => set('orientation', e.target.value)}
            className={inputCls}
          >
            <option value="">— {t('common.none', { defaultValue: 'None' })} —</option>
            {PLOT_ORIENTATIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.view_type', { defaultValue: 'View type' })}
        >
          <select
            value={plotForm.view_type}
            onChange={(e) => set('view_type', e.target.value)}
            className={inputCls}
          >
            <option value="">— {t('common.none', { defaultValue: 'None' })} —</option>
            {PLOT_VIEW_TYPES.map((v) => (
              <option key={v} value={v}>
                {t(`propdev.plot.view.${v}`, { defaultValue: v })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.sun_exposure_hours', {
            defaultValue: 'Sun exposure (h / day)',
          })}
        >
          <input
            type="number"
            value={plotForm.sun_exposure_hours}
            onChange={(e) => set('sun_exposure_hours', e.target.value)}
            className={inputCls}
            min={0}
            max={24}
            step="0.1"
          />
        </WideModalField>
      </WideModalSection>

      {/* Pricing */}
      <WideModalSection
        columns={2}
        title={t('propdev.plot.section_pricing', { defaultValue: 'Pricing' })}
      >
        <WideModalField
          label={t('propdev.base_price', { defaultValue: 'Base price' })}
        >
          <input
            type="number"
            value={plotForm.price_base}
            onChange={(e) => set('price_base', e.target.value)}
            className={inputCls}
            min={0}
            step="0.01"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.plot.currency', { defaultValue: 'Currency' })}
        >
          <input
            value={plotForm.currency}
            onChange={(e) =>
              set('currency', e.target.value.toUpperCase().slice(0, 3))
            }
            className={inputCls}
            maxLength={3}
            placeholder="EUR"
          />
        </WideModalField>
      </WideModalSection>
    </>
  );
}
