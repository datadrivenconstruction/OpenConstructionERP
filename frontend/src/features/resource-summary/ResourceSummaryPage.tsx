// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Resource Summary - one procurement-ready statement for the whole estimate.
// Rolls up the resource split stored on every priced position into total
// labour-hours and cost, and the total quantity and cost of each material,
// machine and subcontract line, so a buyer sees a single schedule of what the
// estimate implies they must procure. A second "Buy-list" tab distils just the
// material lines into a purchase list grouped by material, with a client-side
// CSV export. Reads existing per-position splits; it never edits the estimate.

import { useState } from 'react';
import { useMutation, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { LucideIcon } from 'lucide-react';
import {
  Boxes,
  ClipboardList,
  Download,
  FilePlus,
  HardHat,
  Layers,
  Package,
  ShoppingCart,
  Truck,
  Users,
  Wrench,
} from 'lucide-react';
import { Button, Card, EmptyState, ErrorState, PageHeader, SkeletonTable, StatCard, TabBar, tabIds } from '@/shared/ui';
import { CreateRequisitionModal } from './CreateRequisitionModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { QuantityDisplay } from '@/shared/ui/QuantityDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  downloadBuyListCsv,
  downloadResourceStatementCsv,
  getMaterialBuyList,
  getResourceStatement,
  isEmptyBuyList,
  isEmptyStatement,
  kindAccentClass,
  statementCurrency,
  type MaterialBuyListResponse,
  type ResourceStatementGroup,
} from './api';

const KIND_ICON: Record<string, LucideIcon> = {
  labor: HardHat,
  material: Package,
  machinery: Wrench,
  equipment: Boxes,
  subcontractor: Users,
  other: Layers,
};

type ResourceTab = 'statement' | 'buy-list';

const TAB_IDS = tabIds('resource-summary');

export function ResourceSummaryPage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [activeTab, setActiveTab] = useState<ResourceTab>('statement');

  const query = useQuery({
    queryKey: ['resource-summary', activeProjectId],
    queryFn: () => getResourceStatement(activeProjectId as string),
    enabled: !!activeProjectId,
    staleTime: 30_000,
  });

  // The buy-list is a second read of the same positions; fetch it lazily the
  // first time its tab is opened so the default view stays as light as before.
  const buyListQuery = useQuery({
    queryKey: ['resource-buy-list', activeProjectId],
    queryFn: () => getMaterialBuyList(activeProjectId as string),
    enabled: !!activeProjectId && activeTab === 'buy-list',
    staleTime: 30_000,
  });

  const download = useMutation({
    mutationFn: () => downloadResourceStatementCsv(activeProjectId as string),
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('resourceSummary.exportFailed', { defaultValue: 'Could not export the statement' }),
        message: getErrorMessage(e),
      });
    },
  });

  const data = query.data;
  const currency = statementCurrency(data);
  const buyListData = buyListQuery.data;

  // The export button follows the active tab: the statement pulls a server CSV,
  // the buy-list is built on the client from the rows already in hand.
  const canExport =
    activeTab === 'statement'
      ? !!data && !isEmptyStatement(data)
      : !!buyListData && !isEmptyBuyList(buyListData);
  const exporting = activeTab === 'statement' && download.isPending;

  const handleExport = () => {
    if (activeTab === 'statement') {
      download.mutate();
    } else if (buyListData) {
      downloadBuyListCsv(buyListData);
    }
  };

  const header = (
    <PageHeader
      srTitle={t('resourceSummary.title', { defaultValue: 'Resource summary' })}
      subtitle={t('resourceSummary.subtitle', {
        defaultValue:
          'Resource splits from every position rolled up into one procurement statement: labour-hours and the quantity and cost of each material, machine and subcontract line.',
      })}
      actions={
        canExport ? (
          <Button
            variant="secondary"
            size="sm"
            icon={<Download size={14} />}
            onClick={handleExport}
            disabled={exporting}
          >
            {exporting
              ? t('resourceSummary.exporting', { defaultValue: 'Exporting...' })
              : t('resourceSummary.exportCsv', { defaultValue: 'Export CSV' })}
          </Button>
        ) : null
      }
    />
  );

  if (!activeProjectId) {
    return (
      <div className="space-y-5">
        {header}
        <EmptyState
          icon={<Boxes className="h-6 w-6" />}
          title={t('resourceSummary.noProject.title', { defaultValue: 'No project selected' })}
          description={t('resourceSummary.noProject.description', {
            defaultValue: 'Open a project to see the resources and quantities its estimate implies you must procure.',
          })}
        />
      </div>
    );
  }

  const statementBody =
    query.isLoading ? (
      <Card padding="sm">
        <SkeletonTable rows={8} columns={5} />
      </Card>
    ) : query.isError ? (
      <ErrorState
        title={t('resourceSummary.loadError', { defaultValue: 'Could not load the resource summary' })}
        hint={t('resourceSummary.loadErrorHint', {
          defaultValue: 'Refresh to try again. If it keeps failing, the estimate may still be loading.',
        })}
        onRetry={() => query.refetch()}
      />
    ) : !data || isEmptyStatement(data) ? (
      <EmptyState
        icon={<Package className="h-6 w-6" />}
        title={t('resourceSummary.empty.title', { defaultValue: 'No resources to summarise yet' })}
        description={t('resourceSummary.empty.description', {
          defaultValue:
            'Add a resource split to positions (or apply assemblies) and this statement will roll them up across the whole estimate.',
        })}
      />
    ) : (
      <>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard
            label={t('resourceSummary.kpi.laborHours', { defaultValue: 'Labour hours' })}
            value={<QuantityDisplay value={data.labor_hours} unit="h" precision={1} />}
            icon={HardHat}
            tone="blue"
            tintValue
          />
          <StatCard
            label={t('resourceSummary.kpi.totalCost', { defaultValue: 'Total resource cost' })}
            value={<MoneyDisplay amount={data.total_cost} currency={currency} compact />}
            icon={Truck}
            tone="success"
            tintValue
          />
          <StatCard
            label={t('resourceSummary.kpi.distinctResources', { defaultValue: 'Distinct resources' })}
            value={data.line_count}
            icon={Boxes}
          />
          <StatCard
            label={t('resourceSummary.kpi.positionsCovered', { defaultValue: 'Positions covered' })}
            value={data.position_count}
            icon={Layers}
          />
        </div>

        {data.groups.map((group) => (
          <ResourceGroupCard key={group.kind} group={group} currency={currency} />
        ))}

        <p className="text-xs text-content-tertiary">
          {t('resourceSummary.generatedAt', { defaultValue: 'Generated' })}{' '}
          <DateDisplay value={data.generated_at} format="datetime" />
        </p>
      </>
    );

  return (
    <div className="space-y-5">
      {header}

      <TabBar<ResourceTab>
        ariaLabel={t('resourceSummary.tabs.aria', { defaultValue: 'Resource summary views' })}
        idPrefix="resource-summary"
        activeId={activeTab}
        onChange={setActiveTab}
        tabs={[
          {
            id: 'statement',
            label: t('resourceSummary.tabs.statement', { defaultValue: 'Statement' }),
            icon: <Layers size={14} aria-hidden />,
          },
          {
            id: 'buy-list',
            label: t('resourceSummary.tabs.buyList', { defaultValue: 'Buy-list' }),
            icon: <ShoppingCart size={14} aria-hidden />,
          },
        ]}
      />

      <div
        role="tabpanel"
        id={TAB_IDS.panelId(activeTab)}
        aria-labelledby={TAB_IDS.tabId(activeTab)}
        className="space-y-5"
      >
        {activeTab === 'statement' ? (
          statementBody
        ) : (
          <BuyListView query={buyListQuery} projectId={activeProjectId ?? null} />
        )}
      </div>
    </div>
  );
}

interface ResourceGroupCardProps {
  group: ResourceStatementGroup;
  currency: string | undefined;
}

function ResourceGroupCard({ group, currency }: ResourceGroupCardProps) {
  const { t } = useTranslation();
  const Icon = KIND_ICON[group.kind] ?? Layers;

  return (
    <Card padding="sm">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Icon size={16} className={kindAccentClass(group.kind)} aria-hidden />
          <h3 className="text-sm font-semibold text-content-primary">
            {t(`resourceSummary.kind.${group.kind}`, { defaultValue: group.label })}
          </h3>
          <span className="text-xs text-content-tertiary">
            {t('resourceSummary.lineCount', { defaultValue: '{{count}} lines', count: group.line_count })}
          </span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          {group.total_hours != null && (
            <span className="text-content-secondary">
              <QuantityDisplay value={group.total_hours} unit="h" precision={1} />
            </span>
          )}
          <span className="font-semibold tabular-nums text-content-primary">
            <MoneyDisplay amount={group.total_cost} currency={currency} />
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
              <th className="py-1.5 pr-3 font-medium">{t('resourceSummary.col.resource', { defaultValue: 'Resource' })}</th>
              <th className="py-1.5 pr-3 font-medium">{t('resourceSummary.col.unit', { defaultValue: 'Unit' })}</th>
              <th className="py-1.5 pr-3 text-right font-medium">
                {t('resourceSummary.col.quantity', { defaultValue: 'Quantity' })}
              </th>
              <th className="py-1.5 pr-3 text-right font-medium">
                {t('resourceSummary.col.cost', { defaultValue: 'Cost' })}
              </th>
              <th className="py-1.5 text-right font-medium">
                {t('resourceSummary.col.positions', { defaultValue: 'Positions' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {group.lines.map((line, idx) => (
              <tr key={`${line.name}-${line.unit}-${idx}`} className="border-b border-border-light/60 last:border-0">
                <td className="py-1.5 pr-3 text-content-primary">{line.name}</td>
                <td className="py-1.5 pr-3 text-content-tertiary">{line.unit || '-'}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                  <QuantityDisplay value={line.quantity} unit={line.unit} precision={2} />
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-content-primary">
                  <MoneyDisplay amount={line.cost} currency={currency} />
                </td>
                <td className="py-1.5 text-right tabular-nums text-content-tertiary">{line.position_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

interface BuyListViewProps {
  query: UseQueryResult<MaterialBuyListResponse>;
  projectId: string | null;
}

function BuyListView({ query, projectId }: BuyListViewProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const data = query.data;
  const currency = data?.currency?.trim() || undefined;
  // Rows picked for a requisition, by index into the served list.
  const [selected, setSelected] = useState<number[]>([]);
  const [requisitionOpen, setRequisitionOpen] = useState(false);

  if (query.isLoading) {
    return (
      <Card padding="sm">
        <SkeletonTable rows={8} columns={5} />
      </Card>
    );
  }

  if (query.isError) {
    return (
      <ErrorState
        title={t('resourceSummary.buyList.loadError', { defaultValue: 'Could not load the buy-list' })}
        hint={t('resourceSummary.loadErrorHint', {
          defaultValue: 'Refresh to try again. If it keeps failing, the estimate may still be loading.',
        })}
        onRetry={() => query.refetch()}
      />
    );
  }

  if (!data || isEmptyBuyList(data)) {
    return (
      <EmptyState
        icon={<ShoppingCart className="h-6 w-6" />}
        title={t('resourceSummary.buyList.empty.title', { defaultValue: 'Nothing to procure yet' })}
        description={t('resourceSummary.buyList.empty.description', {
          defaultValue:
            'Add material resource lines to positions (or apply assemblies) and they will roll up here into one purchase list.',
        })}
      />
    );
  }

  // F4 interop: hand the buy-list to Procurement as a pre-filled draft PO.
  // Only description / unit / quantity travel; the buyer picks a supplier and
  // negotiates rates in the existing PO-create flow. Quantities are the exact
  // Decimal strings the backend served - passed through verbatim, never float.
  const handleCreateDraftPo = () => {
    navigate('/procurement', {
      state: {
        buyList: data.items.map((item) => ({
          description: item.name,
          unit: item.unit,
          quantity: item.quantity,
        })),
      },
    });
  };

  return (
    <>
      <Card padding="sm">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShoppingCart size={16} className="text-semantic-success" aria-hidden />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('resourceSummary.buyList.heading', { defaultValue: 'Materials to purchase' })}
            </h3>
            <span className="text-xs text-content-tertiary">
              {t('resourceSummary.buyList.itemCount', { defaultValue: '{{count}} materials', count: data.item_count })}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="font-semibold tabular-nums text-content-primary">
              <MoneyDisplay amount={data.total_cost} currency={currency} />
            </span>
            <Button
              variant="primary"
              size="sm"
              icon={<ClipboardList size={14} />}
              onClick={() => setRequisitionOpen(true)}
              disabled={selected.length === 0 || !projectId}
              title={t('resourceSummary.buyList.createRequisitionHint', {
                defaultValue: 'Select the materials to request, then raise one requisition for them.',
              })}
            >
              {t('resourceSummary.buyList.createRequisition', { defaultValue: 'Create requisition' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<FilePlus size={14} />}
              onClick={handleCreateDraftPo}
            >
              {t('resourceSummary.buyList.createDraftPo', { defaultValue: 'Create draft PO' })}
            </Button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] text-sm">
            <thead>
              <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="w-8 py-1.5 pr-2">
                  <input
                    type="checkbox"
                    aria-label={t('resourceSummary.buyList.selectAll', { defaultValue: 'Select all materials' })}
                    checked={selected.length === data.items.length}
                    onChange={(e) => setSelected(e.target.checked ? data.items.map((_, i) => i) : [])}
                  />
                </th>
                <th className="py-1.5 pr-3 font-medium">
                  {t('resourceSummary.buyList.col.material', { defaultValue: 'Material' })}
                </th>
                <th className="py-1.5 pr-3 font-medium">{t('resourceSummary.col.unit', { defaultValue: 'Unit' })}</th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t('resourceSummary.buyList.col.quantity', { defaultValue: 'Total quantity' })}
                </th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t('resourceSummary.buyList.col.covered', { defaultValue: 'On requisitions' })}
                </th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t('resourceSummary.buyList.col.remaining', { defaultValue: 'Remaining' })}
                </th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t('resourceSummary.buyList.col.cost', { defaultValue: 'Est. cost' })}
                </th>
                <th className="py-1.5 text-right font-medium">
                  {t('resourceSummary.buyList.col.positions', { defaultValue: 'Used in' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item, idx) => (
                <tr key={`${item.name}-${item.unit}-${idx}`} className="border-b border-border-light/60 last:border-0">
                  <td className="py-1.5 pr-2">
                    <input
                      type="checkbox"
                      aria-label={t('resourceSummary.buyList.selectRow', {
                        defaultValue: 'Select {{name}}',
                        name: item.name,
                      })}
                      checked={selected.includes(idx)}
                      onChange={(e) =>
                        setSelected((prev) => (e.target.checked ? [...prev, idx] : prev.filter((i) => i !== idx)))
                      }
                    />
                  </td>
                  <td className="py-1.5 pr-3 text-content-primary">{item.name}</td>
                  <td className="py-1.5 pr-3 text-content-tertiary">{item.unit || '-'}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                    <QuantityDisplay value={item.quantity} unit={item.unit} precision={2} />
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                    {item.covered_quantity != null ? (
                      <QuantityDisplay value={item.covered_quantity} unit={item.unit} precision={2} />
                    ) : (
                      '-'
                    )}
                  </td>
                  <td
                    className={`py-1.5 pr-3 text-right tabular-nums ${
                      item.remaining_quantity != null && item.remaining_quantity.startsWith('-')
                        ? 'text-semantic-warning'
                        : 'text-content-secondary'
                    }`}
                  >
                    {item.remaining_quantity != null ? (
                      <QuantityDisplay value={item.remaining_quantity} unit={item.unit} precision={2} />
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-content-primary">
                    <MoneyDisplay amount={item.cost} currency={currency} />
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-content-tertiary">{item.position_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="text-xs text-content-tertiary">
        {t('resourceSummary.buyList.grossNote', {
          defaultValue: 'Quantities are gross (waste included where a factor is set). Estimated cost is indicative.',
        })}{' '}
        {t('resourceSummary.generatedAt', { defaultValue: 'Generated' })}{' '}
        <DateDisplay value={data.generated_at} format="datetime" />
      </p>

      {projectId && (
        <CreateRequisitionModal
          open={requisitionOpen}
          projectId={projectId}
          rows={selected.map((i) => data.items[i]).filter((row) => row !== undefined)}
          onClose={() => setRequisitionOpen(false)}
          onCreated={(id) => {
            setRequisitionOpen(false);
            setSelected([]);
            navigate(`/procurement?requisition=${encodeURIComponent(id)}`);
          }}
        />
      )}
    </>
  );
}
