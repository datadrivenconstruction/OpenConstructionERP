// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Asset Register page (v2.3.0).
 *
 * Lists every BIM element flagged ``is_tracked_asset=true`` in the active
 * project. Supports free-text search across manufacturer / model /
 * serial / notes and an operational-status filter. Edit an asset row to
 * open a modal that patches the ``asset_info`` JSON on the underlying
 * BIMElement.
 *
 * URL conventions:
 *   - `?search=...`        — restores the search box
 *   - `?status=operational`— restores the status filter
 *
 * Clears state when the active project changes so you never see stale
 * rows from a previous project.
 */
import { Fragment, useCallback, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  ClipboardList,
  Cuboid,
  Download,
  Edit3,
  FileSpreadsheet,
  Network,
  Package,
  Search,
  X,
} from 'lucide-react';

import { Badge, Breadcrumb, Button, Card, CollapsibleSection, DismissibleInfo, IntroRichText, EmptyState, Input } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { AssetOperationsToolbar, AssetPortfolioStrip } from '@/features/assets';
import {
  listAssets,
  type AssetRow,
  type MaintenanceStatus,
  type WarrantyStatus,
} from '@/features/assets/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import { AssetDetailDrawer } from './AssetDetailDrawer';
import { AssetEditModal } from './AssetEditModal';
import {
  downloadCobieXlsx,
  listTrackedAssets,
  type AssetInfoPayload,
  type AssetListResponse,
  type AssetSummary,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

const OPERATIONAL_STATUSES: Array<{ value: string; labelKey: string; tone: string }> = [
  { value: 'operational', labelKey: 'assets.status.operational', tone: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  { value: 'under_maintenance', labelKey: 'assets.status.under_maintenance', tone: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  { value: 'decommissioned', labelKey: 'assets.status.decommissioned', tone: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  { value: 'planned', labelKey: 'assets.status.planned', tone: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
];

/**
 * Rows fetched per request.
 *
 * The register used to ask for one slab and render whatever came back. The
 * count beside the heading is the server's total for the whole matching set,
 * so a project past the cap showed a number and a shorter list and said
 * nothing about the difference. Paging makes the shortfall visible and gives
 * the user a way to close it, rather than only confessing to it.
 *
 * 200 rather than the endpoint's 500 ceiling: a page has to be small enough
 * that a second one exists to be asked for, otherwise the control that proves
 * the rest are reachable never appears on any real project.
 */
const REGISTER_PAGE_SIZE = 200;

/** Labels for the active-tile-filter chip, keyed to the tiles themselves. */
const TILE_FILTER_LABELS = {
  attention: { key: 'assets.kpi.needs_attention', fallback: 'Needs attention' },
  maintenance_overdue: { key: 'assets.kpi.maintenance_overdue', fallback: 'Maintenance overdue' },
  warranty_expired: { key: 'assets.kpi.warranty_expired', fallback: 'Warranty expired' },
  warranty_expiring: { key: 'assets.kpi.warranty_expiring', fallback: 'Expiring soon' },
} as const;

function statusTone(status?: string | null): string {
  return (
    OPERATIONAL_STATUSES.find((s) => s.value === status)?.tone ??
    'bg-neutral-700/40 text-neutral-300 border-neutral-600/50'
  );
}

/* ── How-it-works flow + module integrations ───────────────────────────── */

/** A compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer of what the asset register is and how it connects: it
 * carries the BIM model through to operations, so elements become tracked
 * assets with operational data and a COBie handover. Every connected module is
 * a link so the workflow is obvious.
 */
function HowAssetsWork() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Cuboid size={14} className="text-oe-blue" />,
      title: t('assets.flow_1_title', { defaultValue: 'Extract from the model' }),
      desc: t('assets.flow_1_desc', {
        defaultValue: 'Elements flagged as tracked assets in your BIM models appear here.',
      }),
    },
    {
      icon: <ClipboardList size={14} className="text-oe-blue" />,
      title: t('assets.flow_2_title', { defaultValue: 'Record details' }),
      desc: t('assets.flow_2_desc', {
        defaultValue: 'Add manufacturer, model, serial and warranty to each asset.',
      }),
    },
    {
      icon: <Activity size={14} className="text-oe-blue" />,
      title: t('assets.flow_3_title', { defaultValue: 'Track status' }),
      desc: t('assets.flow_3_desc', {
        defaultValue: 'Set operational status as assets move through maintenance and service.',
      }),
    },
    {
      icon: <FileSpreadsheet size={14} className="text-oe-blue" />,
      title: t('assets.flow_4_title', { defaultValue: 'Hand over' }),
      desc: t('assets.flow_4_desc', {
        defaultValue: 'Export the register as COBie for facilities management at handover.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="assets.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('assets.flow_title', { defaultValue: 'How the asset register fits together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('assets.flow_intro', {
          defaultValue:
            'The asset register carries your BIM model through to operations: model elements become tracked assets with manufacturer, warranty and status, ready for a COBie handover to facilities management.',
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
            {t('assets.flow_connects', { defaultValue: 'Connects with:' })}
          </span>{' '}
          <ModLink to="/bim">
            {t('assets.mod_bim', { defaultValue: 'BIM viewer' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/quantities">
            {t('assets.mod_quantities', { defaultValue: 'Quantity takeoff' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/match-elements">
            {t('assets.mod_match', { defaultValue: 'Match elements' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/equipment">
            {t('assets.mod_equipment', { defaultValue: 'Equipment & Fleet' })}
          </ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

/* ── AssetsPage ────────────────────────────────────────────────────────── */

/** Filters the register can be narrowed by, including the KPI-tile ones. */
interface RegisterFilters {
  search: string;
  status: string;
  warranty: string;
  maintenance: string;
  attention: boolean;
}

/** Shape an Asset Operations row into the BIM Hub row this page renders. */
function toAssetSummary(row: AssetRow): AssetSummary {
  return {
    id: row.id,
    stable_id: row.stable_id,
    element_type: row.element_type ?? '',
    name: row.name,
    model_id: row.model_id,
    model_name: row.model_name,
    project_id: row.project_id,
    // Both endpoints return the same stored blob - `dict(element.asset_info)`
    // on one side, `_summarise_asset` on the other - so the columns read the
    // same values whichever source answered.
    asset_info: row.asset_info as AssetInfoPayload,
  };
}

/**
 * List through Asset Operations, falling back to the BIM Hub.
 *
 * Asset Operations is the better source: it owns the warranty and maintenance
 * filters the KPI tiles need, and it computes per-asset health. It is also
 * optional. The module can be switched off, and the endpoint sits behind the
 * `assets.read` permission, while the BIM Hub list has neither restriction and
 * is what this page used before. Falling back keeps the register working for
 * everyone who can open it today instead of trading a working page for a 403.
 *
 * The fallback deliberately does not run when a tile filter is set. The BIM
 * Hub cannot filter by warranty, maintenance or attention, so answering a
 * filtered request from it would show the wrong rows under the right heading -
 * worse than an error, because nothing on screen would look wrong.
 */
async function loadRegister(
  projectId: string,
  f: RegisterFilters,
  offset: number,
): Promise<AssetListResponse> {
  const opsOnlyFilter = !!(f.warranty || f.maintenance || f.attention);
  try {
    const resp = await listAssets(projectId, {
      search: f.search || undefined,
      operationalStatus: f.status || undefined,
      warrantyStatus: (f.warranty || undefined) as WarrantyStatus | undefined,
      maintenanceStatus: (f.maintenance || undefined) as MaintenanceStatus | undefined,
      needsAttention: f.attention || undefined,
      offset,
      limit: REGISTER_PAGE_SIZE,
    });
    return { items: resp.items.map(toAssetSummary), total: resp.total };
  } catch (err) {
    if (opsOnlyFilter) throw err;
    return listTrackedAssets(projectId, {
      search: f.search || undefined,
      operationalStatus: f.status || undefined,
      offset,
      limit: REGISTER_PAGE_SIZE,
    });
  }
}

export function AssetsPage() {
  const { t } = useTranslation();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToastStore((s) => s.addToast);

  const search = searchParams.get('search') ?? '';
  const status = searchParams.get('status') ?? '';
  // Tile filters live in the URL like the other two, so a narrowed register
  // survives a reload and can be shared.
  const warranty = searchParams.get('warranty') ?? '';
  const maintenance = searchParams.get('maintenance') ?? '';
  const attention = searchParams.get('attention') === '1';

  const [editing, setEditing] = useState<AssetSummary | null>(null);
  const [detailing, setDetailing] = useState<AssetSummary | null>(null);

  const patchSearch = useCallback(
    (next: Partial<Record<'search' | 'status' | 'warranty' | 'maintenance' | 'attention', string>>) => {
      const updated = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(next)) {
        if (!value) updated.delete(key);
        else updated.set(key, value);
      }
      setSearchParams(updated, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const assetsQuery = useInfiniteQuery<AssetListResponse, Error>({
    queryKey: ['bim-assets', activeProjectId, search, status, warranty, maintenance, attention],
    queryFn: ({ pageParam }) =>
      loadRegister(
        activeProjectId!,
        { search, status, warranty, maintenance, attention },
        (pageParam as number) ?? 0,
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.items.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
    enabled: !!activeProjectId,
    staleTime: 30_000,
    // Avoids an edge-case re-render that detaches filter-chip / edit
    // buttons when a focus event lands between the user's click and
    // Playwright's click-retry. Harmless in prod — users rarely tab
    // out of this page, and the 30 s staleTime still forces a refresh.
    refetchOnWindowFocus: false,
  });

  const items = assetsQuery.data?.pages.flatMap((page) => page.items) ?? [];
  // The server filters the whole set before slicing a page out of it, so every
  // page carries the same total: the size of the matching set, not of the page.
  const total = assetsQuery.data?.pages[0]?.total ?? 0;
  const remaining = Math.max(0, total - items.length);

  // Which KPI tile the register is currently narrowed by, labelled with that
  // tile's own key so the chip and the tile can never word it differently.
  const tileFilter = attention
    ? TILE_FILTER_LABELS.attention
    : maintenance === 'overdue'
      ? TILE_FILTER_LABELS.maintenance_overdue
      : warranty === 'expired'
        ? TILE_FILTER_LABELS.warranty_expired
        : warranty === 'expiring'
          ? TILE_FILTER_LABELS.warranty_expiring
          : null;

  if (!activeProjectId) {
    return (
      <div className="p-6">
        <Breadcrumb items={[{ label: t('nav.assets', { defaultValue: 'Assets' }) }]} />
        <EmptyState
          icon={<Package size={48} />}
          title={t('assets.no_project.title', { defaultValue: 'No active project' })}
          description={t('assets.no_project.desc', {
            defaultValue: 'Pick a project first from the Projects page to see its tracked assets.',
          })}
          action={
            <Button onClick={() => navigate('/projects')}>
              {t('assets.cta.go_projects', { defaultValue: 'Go to Projects' })}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-4 space-y-5">
        <Breadcrumb
          items={[
            { label: activeProjectName || t('nav.project', { defaultValue: 'Project' }), to: `/projects/${activeProjectId}` },
            { label: t('nav.assets', { defaultValue: 'Assets' }) },
          ]}
        />

        {/* ── Header ───────────────────────────────────────────────────── */}
        <PageHeader
          srTitle={t('assets.title', { defaultValue: 'Asset Register' })}
          subtitle={t('assets.subtitle', {
            defaultValue: 'Equipment, fixtures and systems extracted from your BIM models.',
          })}
          actions={<Badge variant="neutral">{total}</Badge>}
        />

        {/* ── Purpose intro ─────────────────────────────────────────────── */}
        <DismissibleInfo
          storageKey="assets"
          title={t('assets.intro_title', {
            defaultValue: 'Carry the model through to handover',
          })}
          more={
            t('assets.intro_more', { defaultValue: '' })
              ? <IntroRichText text={t('assets.intro_more')} />
              : undefined
          }
          links={[
            { label: t('assets.intro_link_bim', { defaultValue: 'BIM viewer' }), onClick: () => navigate('/bim') },
            {
              label: t('assets.intro_link_equipment', {
                defaultValue: 'Equipment & Fleet',
              }),
              onClick: () => navigate('/equipment'),
            },
          ]}
        >
          {t('assets.intro_body', {
            defaultValue:
              'Lists every BIM element flagged as a tracked asset in the active project, with search across manufacturer, model and serial and a status filter. Edit a row to record operational data on the element, open it in the 3D viewer, or export the register as COBie for facilities handover. This register is for installed building assets and fixtures from the model; for plant, vehicles and movable machinery use Equipment & Fleet.',
          })}
        </DismissibleInfo>

        <HowAssetsWork />
      </div>

      {/* ── Portfolio roll-up ────────────────────────────────────────────
          Warranty / maintenance / attention counts computed by the Asset
          Operations module. Renders nothing until the project has tracked
          assets, so it stays out of the way on an empty register.

          Each tile narrows the list to the set it counts. The counts and the
          rows come from the same server-side computation, so a tile reading
          twelve lists twelve; see lifecycle.needs_attention on the backend.
          Selecting one tile clears the others, because the endpoint would
          intersect them and a user who clicks two counts in turn means the
          second one. */}
      <AssetPortfolioStrip
        projectId={activeProjectId}
        onFilter={(f) =>
          patchSearch({
            warranty: f.warrantyStatus ?? '',
            maintenance: f.maintenanceStatus ?? '',
            attention: f.attention ? '1' : '',
          })
        }
      />

      {/* ── Filters ──────────────────────────────────────────────────── */}
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-3 p-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
            />
            <Input
              value={search}
              onChange={(e) => patchSearch({ search: e.target.value })}
              placeholder={t('assets.search_placeholder', {
                defaultValue: 'Search manufacturer, model, serial…',
              })}
              className="pl-9"
              data-testid="asset-search"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => patchSearch({ status: '' })}
              className={`rounded-md border px-3 py-1 text-xs ${
                status === ''
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border-medium text-content-secondary hover:bg-surface-secondary'
              }`}
              data-testid="asset-status-all"
            >
              {t('assets.status.all', { defaultValue: 'All statuses' })}
            </button>
            {OPERATIONAL_STATUSES.map((s) => (
              <button
                key={s.value}
                type="button"
                onClick={() => patchSearch({ status: s.value })}
                className={`rounded-md border px-3 py-1 text-xs ${
                  status === s.value
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border-medium text-content-secondary hover:bg-surface-secondary'
                }`}
                data-testid={`asset-status-${s.value}`}
              >
                {t(s.labelKey, { defaultValue: s.value.replace('_', ' ') })}
              </button>
            ))}

            {/* A tile filter is set from the roll-up above, so the control
                that clears it has to live down here with the other filters -
                otherwise the only way back to the full register is editing
                the URL. Labelled with the tile's own key, so the chip and
                the tile cannot describe the same filter differently. */}
            {tileFilter && (
              <button
                type="button"
                onClick={() => patchSearch({ warranty: '', maintenance: '', attention: '' })}
                title={t('common.clear_filters', { defaultValue: 'Clear filters' })}
                className="flex items-center gap-1 rounded-md border border-oe-blue bg-oe-blue/10 px-3 py-1 text-xs text-oe-blue"
                data-testid="asset-kpi-filter-clear"
              >
                {t(tileFilter.key, { defaultValue: tileFilter.fallback })}
                <X size={12} />
              </button>
            )}
          </div>

          {/* Discover candidates from the BIM models and scan warranties.
              A bulk promotion adds rows to this register, so refetch once
              the modal reports it changed something. */}
          <AssetOperationsToolbar
            projectId={activeProjectId}
            onChanged={() => {
              void assetsQuery.refetch();
            }}
          />
        </div>
      </Card>

      {/* ── Table ───────────────────────────────────────────────────── */}
      <Card className="flex-1 overflow-auto">
        {assetsQuery.isLoading ? (
          <div className="p-6 text-sm text-content-secondary">
            {t('common.loading', { defaultValue: 'Loading…' })}
          </div>
        ) : assetsQuery.isError ? (
          <EmptyState
            icon={<AlertTriangle size={40} />}
            title={t('assets.load_error', {
              defaultValue: 'Could not load assets',
            })}
            description={t('assets.load_error_desc', {
              defaultValue:
                'The asset register could not be loaded. Check your connection and try again.',
            })}
            action={
              <Button
                variant="secondary"
                onClick={() => {
                  void assetsQuery.refetch();
                }}
              >
                {t('common.retry', { defaultValue: 'Retry' })}
              </Button>
            }
          />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Package size={40} />}
            title={t('assets.empty.title', { defaultValue: 'No tracked assets yet' })}
            description={t('assets.empty.desc', {
              defaultValue:
                'Open a BIM model, pick an element, and set a manufacturer or serial to register it as an asset.',
            })}
            action={
              <Button variant="secondary" onClick={() => navigate('/bim')}>
                {t('assets.cta.open_bim', { defaultValue: 'Open CAD-BIM Viewer' })}
              </Button>
            }
          />
        ) : (
          <table className="w-full text-sm" data-testid="asset-table">
            <thead className="sticky top-0 z-10 bg-surface-primary text-xs uppercase tracking-wider text-content-tertiary shadow-sm">
              <tr>
                <th className="w-10 px-2 py-2"></th>
                <th className="px-3 py-2 text-left">{t('assets.col.element', { defaultValue: 'Element' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.manufacturer', { defaultValue: 'Manufacturer' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.model', { defaultValue: 'Model' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.serial', { defaultValue: 'Serial' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.status', { defaultValue: 'Status' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.warranty', { defaultValue: 'Warranty until' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.model_file', { defaultValue: 'BIM model' })}</th>
                <th className="px-3 py-2 text-right">{t('assets.col.actions', { defaultValue: 'Actions' })}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((asset) => (
                <tr
                  key={asset.id}
                  className="cursor-pointer border-t border-border-light transition-colors hover:bg-surface-secondary"
                  data-testid={`asset-row-${asset.id}`}
                  onClick={() => setDetailing(asset)}
                >
                  <td className="px-2 py-2">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetailing(asset);
                      }}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border-medium text-oe-blue hover:border-oe-blue hover:bg-oe-blue/10"
                      title={t('assets.view_geometry', {
                        defaultValue: 'View geometry & properties',
                      })}
                      aria-label={t('assets.view_geometry', {
                        defaultValue: 'View geometry & properties',
                      })}
                      data-testid={`asset-view-${asset.id}`}
                    >
                      <Cuboid size={14} />
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <div className="font-medium text-content-primary">
                      {asset.name || asset.element_type}
                    </div>
                    <div className="text-xs text-content-tertiary">{asset.stable_id}</div>
                  </td>
                  <td className="px-3 py-2 text-content-primary">
                    {asset.asset_info.manufacturer ?? <span className="text-content-quaternary">—</span>}
                  </td>
                  <td className="px-3 py-2 text-content-primary">
                    {asset.asset_info.model ?? <span className="text-content-quaternary">—</span>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-content-secondary">
                    {asset.asset_info.serial_number ?? <span className="text-content-quaternary">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    {asset.asset_info.operational_status ? (
                      <span
                        className={`inline-block rounded-md border px-2 py-0.5 text-xs ${statusTone(
                          asset.asset_info.operational_status,
                        )}`}
                      >
                        {t(`assets.status.${asset.asset_info.operational_status}`, {
                          defaultValue:
                            asset.asset_info.operational_status.replace('_', ' '),
                        })}
                      </span>
                    ) : (
                      <span className="text-content-quaternary">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {asset.asset_info.warranty_until ?? <span className="text-content-quaternary">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-col items-start gap-0.5">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/bim/${asset.model_id}?element=${asset.id}`);
                        }}
                        className="inline-flex max-w-[180px] items-center gap-1 truncate text-oe-blue hover:underline"
                        title={t('assets.open_in_bim', {
                          defaultValue: 'Open in 3D Viewer',
                        })}
                      >
                        <span className="truncate">{asset.model_name}</span>
                        <ArrowUpRight size={12} className="shrink-0 opacity-60" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          downloadCobieXlsx(
                            asset.model_id,
                            `${asset.model_name || 'model'}-cobie.xlsx`,
                          ).catch((err) => {
                            toast({
                              type: 'error',
                              title: t('assets.cobie_failed', {
                                defaultValue: 'COBie export failed',
                              }),
                              message: err instanceof Error ? err.message : undefined,
                            });
                          });
                        }}
                        className="inline-flex items-center gap-1 text-2xs text-content-tertiary hover:text-oe-blue"
                        title={t('assets.cobie_export', {
                          defaultValue: 'Download COBie (XLSX) for this model',
                        })}
                      >
                        <Download size={11} /> COBie
                      </button>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setEditing(asset)}
                      data-testid={`asset-edit-${asset.id}`}
                    >
                      <Edit3 size={14} />
                      {t('common.edit')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* The count beside the heading is the whole matching set. When the
            list is shorter than that, say so and hand over the difference,
            rather than leaving two numbers on screen that disagree in
            silence.

            Gated on `hasNextPage` rather than on `remaining > 0`, even though
            the two agree: `hasNextPage` is what decides whether the click
            does anything, so gating on the arithmetic instead would let the
            button promise rows it cannot fetch. `hasNextPage` is false while
            loading and on error, so this cannot appear over an empty or
            failed table either. */}
        {assetsQuery.hasNextPage && (
          <div className="flex justify-center border-t border-border-light p-3">
            <Button
              variant="secondary"
              size="sm"
              data-testid="asset-load-more"
              disabled={assetsQuery.isFetchingNextPage}
              onClick={() => {
                void assetsQuery.fetchNextPage();
              }}
            >
              {assetsQuery.isFetchingNextPage
                ? t('common.loading', { defaultValue: 'Loading…' })
                : t('bim.load_more', {
                    defaultValue: 'Load more ({{remaining}} remaining)',
                    remaining,
                  })}
            </Button>
          </div>
        )}
      </Card>

      {editing && (
        <AssetEditModal
          asset={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            toast({
              type: 'success',
              title: t('assets.saved', { defaultValue: 'Asset info saved' }),
            });
            setEditing(null);
          }}
        />
      )}

      {detailing && (
        <AssetDetailDrawer
          asset={detailing}
          onClose={() => setDetailing(null)}
        />
      )}
    </div>
  );
}

export default AssetsPage;
