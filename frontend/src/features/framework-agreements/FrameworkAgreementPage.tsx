// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One framework agreement. Overview answers "can I still order?" with the cap meter and the
 * server's findings; Orders lists call-offs from one roll-up; Price list, Rates and escalation,
 * Conditions and Terms hold the agreed basis. The tab sits in ?tab= so links can deep-link.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  EmptyState,
  ErrorState,
  KpiBand,
  ModuleGuideButton,
  PageHeader,
  Skeleton,
  SkeletonTable,
} from '@/shared/ui';
import type { KpiBandItem } from '@/shared/ui';
import { TabBar } from '@/shared/ui/TabBar';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtNumber } from '@/shared/lib/formatters';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useToastStore } from '@/stores/useToastStore';
import { fwkApi, fwkKeys, type AgreementDetail, type OrderSummary } from './api';
import { CapMeter } from './CapMeter';
import { FindingList, NewOrderModal } from './NewOrderModal';
import { OrderDrawer } from './OrderDrawer';
import { frameworkGuide } from './frameworkGuide';
import { agreementPackInputs, statusVariant } from './status';

const TABS = ['overview', 'orders', 'price_list', 'rates', 'conditions', 'terms'] as const;
type Tab = (typeof TABS)[number];

const TAB_DEFAULTS: Record<Tab, string> = {
  overview: 'Overview',
  orders: 'Orders',
  price_list: 'Price list',
  rates: 'Rates and escalation',
  conditions: 'Conditions',
  terms: 'Terms and documents',
};

export function FrameworkAgreementPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get('tab') ?? '') ? (params.get('tab') as Tab) : 'overview';
  const setTab = (next: Tab) => setParams((p) => ({ ...Object.fromEntries(p), tab: next }), { replace: true });
  const [ordering, setOrdering] = useState(false);
  const [openOrder, setOpenOrder] = useState<string | null>(null);
  const canIssue = useHasPermission('framework.issue_order');
  const canOverride = useHasPermission('framework.override_cap');
  const canEditRates = useHasPermission('framework.edit_rates');
  const canAccept = useHasPermission('framework.accept_order');
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const detail = useQuery({ queryKey: fwkKeys.detail(id), queryFn: () => fwkApi.get(id), enabled: Boolean(id) });
  const activate = useMutation({
    mutationFn: (s: 'active' | 'closed') => fwkApi.setStatus(id, s),
    onSuccess: () => qc.invalidateQueries({ queryKey: fwkKeys.all }),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const a = detail.data;
  if (detail.isError) {
    return (
      <ErrorState
        title={t('framework.error.load_one', { defaultValue: 'The agreement could not be loaded.' })}
        onRetry={() => detail.refetch()}
      />
    );
  }
  if (!a) return <Skeleton className="h-64 w-full" />;

  const exhausted = a.status === 'exhausted';
  const orderingOpen = (a.status === 'active' || a.status === 'signed') && canIssue;
  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('framework.title', { defaultValue: 'Framework agreements' }), to: '/framework-agreements' },
          { label: a.code },
        ]}
      />
      <PageHeader
        srTitle={t('framework.title', { defaultValue: 'Framework agreements' })}
        subtitle={
          <span>
            {a.title} · {a.client_name} · <DateDisplay value={a.start_date} /> - <DateDisplay value={a.end_date} />
          </span>
        }
        actions={
          <>
            {orderingOpen && (
              <Button variant="primary" icon={<Plus size={16} />} onClick={() => setOrdering(true)}>
                {t('framework.new_order', { defaultValue: 'New order' })}
              </Button>
            )}
            {a.status === 'draft' && canAccept && (
              <Button variant="primary" loading={activate.isPending} onClick={() => activate.mutate('active')}>
                {t('framework.activate', { defaultValue: 'Activate' })}
              </Button>
            )}
            <ModuleGuideButton content={frameworkGuide} />
          </>
        }
      />
      <div className="flex items-center gap-2">
        <Badge variant={statusVariant(a.status)}>{t(`framework.status.${a.status}`, { defaultValue: a.status })}</Badge>
        {exhausted && (
          <span className="text-sm text-semantic-warning">
            {t('framework.exhausted', { defaultValue: 'This agreement is used up.' })}
          </span>
        )}
      </div>

      <TabBar<Tab>
        ariaLabel={t('framework.title', { defaultValue: 'Framework agreements' })}
        activeId={tab}
        onChange={setTab}
        tabs={TABS.map((x) => ({
          id: x,
          label: t(`framework.tab.${x}`, { defaultValue: TAB_DEFAULTS[x] }),
          badge: x === 'orders' ? a.consumption.orders : undefined,
        }))}
      />

      {tab === 'overview' && <Overview a={a} />}
      {tab === 'orders' && <OrdersTab a={a} onOpen={setOpenOrder} onNew={orderingOpen ? () => setOrdering(true) : undefined} />}
      {tab === 'price_list' && <PriceListTab a={a} />}
      {tab === 'rates' && <RatesTab a={a} editable={canEditRates} />}
      {tab === 'conditions' && <ConditionsTab a={a} editable={canEditRates} />}
      {tab === 'terms' && <TermsTab a={a} />}

      {ordering && (
        <NewOrderModal
          agreement={a}
          canOverride={canOverride}
          onClose={() => setOrdering(false)}
          onCreated={(orderId) => {
            setTab('orders');
            setOpenOrder(orderId);
          }}
        />
      )}
      {openOrder && (
        <OrderDrawer
          orderId={openOrder}
          agreement={a}
          canIssue={canIssue}
          canOverride={canOverride}
          onClose={() => setOpenOrder(null)}
        />
      )}
    </div>
  );
}

function Overview({ a }: { a: AgreementDetail }) {
  const { t } = useTranslation();
  const [by, setBy] = useState<'site' | 'item' | 'month'>('site');
  const c = a.consumption;
  const breakdown = useQuery({ queryKey: [...fwkKeys.detail(a.id), 'breakdown', by], queryFn: () => fwkApi.breakdown(a.id, by) });
  const money = (v: string | null) => (v == null ? '-' : <MoneyDisplay amount={v} currency={a.currency} />);
  const kpis: KpiBandItem[] = [
    { key: 'cap', label: t('framework.kpi.cap', { defaultValue: 'Cap' }), value: money(c.cap) },
    { key: 'committed', label: t('framework.kpi.committed', { defaultValue: 'Committed' }), value: money(c.committed) },
    { key: 'certified', label: t('framework.kpi.certified', { defaultValue: 'Certified' }), value: money(c.certified) },
    { key: 'invoiced', label: t('framework.kpi.invoiced', { defaultValue: 'Invoiced' }), value: money(c.invoiced) },
    {
      key: 'headroom',
      label: t('framework.kpi.headroom', { defaultValue: 'Headroom' }),
      value: money(c.headroom),
      tone: c.pct != null && Number(c.pct) >= Number(c.threshold_pct) ? 'warning' : undefined,
      tintValue: c.pct != null && Number(c.pct) >= Number(c.threshold_pct),
    },
  ];
  const capFinding = a.findings.find((f) => f.code === 'FWK_CAP_THRESHOLD' || f.code === 'FWK_CAP_EXCEEDED');
  const sentence = capFinding?.message ?? (c.pct != null ? `${c.pct} %` : '');
  return (
    <div className="space-y-4">
      <KpiBand items={kpis} />
      <Card>
        <div className="space-y-3">
          {c.cap != null ? (
            <>
              {c.headroom != null && (
                <p className="text-sm text-content-primary">
                  {t('framework.cap.sentence', {
                    defaultValue: 'Headroom {{amount}} at {{pct}} % of the cap.',
                    amount: `${fmtNumber(c.headroom, 2)} ${a.currency}`,
                    pct: c.pct,
                  })}
                </p>
              )}
              <CapMeter
                cap={c.cap}
                committed={c.committed}
                certified={c.certified}
                threshold_pct={c.threshold_pct}
                min_value={c.min_value}
                term_elapsed_pct={c.term_elapsed_pct}
                valueText={sentence}
              />
              <p className="text-xs text-content-tertiary">
                {t('framework.cap.tested_on', {
                  defaultValue: 'Cap tested on: {{basis}}',
                  basis: t(`framework.kpi.${c.cap_basis}`, { defaultValue: c.cap_basis }),
                })}
                {c.term_elapsed_pct != null &&
                  ` · ${t('framework.term_elapsed', { defaultValue: 'Term elapsed {{pct}} %', pct: c.term_elapsed_pct })}`}
              </p>
            </>
          ) : (
            <p className="text-sm text-content-secondary">{t('framework.cap.no_cap_text', { defaultValue: 'This agreement has no cap.' })}</p>
          )}
          <FindingList findings={a.findings} />
          {a.pack.notes?.includes('cjeu_c_23_20') && exhaustedOrNear(a) && (
            <p className="text-xs text-content-tertiary">
              {t('framework.note.cjeu', {
                defaultValue: 'EU: once the stated maximum is reached, the framework agreement has no further effect (CJEU C-23/20).',
              })}
            </p>
          )}
        </div>
      </Card>
      <Card padding="none">
        <div className="flex items-center gap-1 border-b border-border-light p-2" role="group">
          {(['site', 'item', 'month'] as const).map((x) => (
            <button
              key={x}
              type="button"
              aria-pressed={by === x}
              onClick={() => setBy(x)}
              className={`rounded-md px-3 py-1 text-xs font-medium ${by === x ? 'bg-surface-secondary text-content-primary' : 'text-content-secondary'}`}
            >
              {t(`framework.by.${x}`, { defaultValue: { site: 'By site', item: 'By item', month: 'By month' }[x] })}
            </button>
          ))}
        </div>
        {breakdown.isLoading ? (
          <SkeletonTable rows={4} columns={5} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light text-xs text-content-tertiary">
                <th scope="col" className="px-4 py-2 text-start font-medium">{t(`framework.by.${by}`, { defaultValue: by })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.orders', { defaultValue: 'Orders' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.kpi.committed', { defaultValue: 'Committed' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.kpi.certified', { defaultValue: 'Certified' })}</th>
                {by === 'item' && (
                  <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.qty_max', { defaultValue: 'Ordered / max qty' })}</th>
                )}
              </tr>
            </thead>
            <tbody>
              {(breakdown.data?.rows ?? []).map((r) => (
                <tr key={r.key} className="border-b border-border-light last:border-0">
                  <td className="px-4 py-2">{r.label}</td>
                  <td className="px-4 py-2 text-end tabular-nums">{r.orders}</td>
                  <td className="px-4 py-2 text-end tabular-nums"><MoneyDisplay amount={r.committed} currency={a.currency} /></td>
                  <td className="px-4 py-2 text-end tabular-nums"><MoneyDisplay amount={r.certified} currency={a.currency} /></td>
                  {by === 'item' && (
                    <td className="px-4 py-2 text-end tabular-nums">
                      {r.quantity ?? '-'}
                      {r.max_qty ? ` / ${r.max_qty}` : ''}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function exhaustedOrNear(a: AgreementDetail): boolean {
  return a.status === 'exhausted' || (a.consumption.pct != null && Number(a.consumption.pct) >= Number(a.consumption.threshold_pct));
}

const ORDER_FILTERS = ['all', 'draft', 'issued', 'in_progress', 'measured', 'claimed', 'closed', 'cancelled'] as const;

function OrdersTab({ a, onOpen, onNew }: { a: AgreementDetail; onOpen: (id: string) => void; onNew?: () => void }) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<(typeof ORDER_FILTERS)[number]>('all');
  const [flag, setFlag] = useState<'extras' | 'over' | null>(null);
  const orders = useQuery({ queryKey: fwkKeys.orders(a.id), queryFn: () => fwkApi.orders(a.id) });
  const rows = useMemo(
    () =>
      (orders.data?.items ?? []).filter(
        (o: OrderSummary) =>
          (filter === 'all' || o.order_status === filter) &&
          (flag !== 'extras' || o.has_extras) &&
          (flag !== 'over' || o.measured_over_ordered),
      ),
    [orders.data, filter, flag],
  );
  if (orders.isLoading) return <SkeletonTable rows={6} columns={8} />;
  if (!orders.data?.items.length) {
    return (
      <EmptyState
        title={t('framework.empty.orders', { defaultValue: 'No orders yet. Price the first job from the agreement rates.' })}
        action={
          onNew ? (
            <Button variant="primary" icon={<Plus size={16} />} onClick={onNew}>
              {t('framework.new_order', { defaultValue: 'New order' })}
            </Button>
          ) : undefined
        }
      />
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {ORDER_FILTERS.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={filter === s}
            onClick={() => setFilter(s)}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${filter === s ? 'border-oe-blue bg-oe-blue/10 text-oe-blue' : 'border-border-light text-content-secondary'}`}
          >
            {s === 'all' ? t('framework.filter.all', { defaultValue: 'All' }) : t(`framework.status.${s}`, { defaultValue: s })}
          </button>
        ))}
        {(['extras', 'over'] as const).map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={flag === f}
            onClick={() => setFlag((x) => (x === f ? null : f))}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${flag === f ? 'border-semantic-warning bg-semantic-warning-bg text-semantic-warning' : 'border-border-light text-content-secondary'}`}
          >
            {f === 'extras'
              ? t('framework.filter.has_extras', { defaultValue: 'Has extras' })
              : t('framework.filter.measured_over', { defaultValue: 'Measured over ordered' })}
          </button>
        ))}
      </div>
      <Card padding="none">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light text-xs text-content-tertiary">
                <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.order_no', { defaultValue: 'Order no' })}</th>
                <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.order.site', { defaultValue: 'Site' })}</th>
                <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.order.ordered_at', { defaultValue: 'Ordered' })}</th>
                <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.order.conditions', { defaultValue: 'Conditions' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.lines', { defaultValue: 'Lines' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.order.net', { defaultValue: 'Net' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.order.tab_extras', { defaultValue: 'Extras' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.measured_pct', { defaultValue: 'Measured %' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.claimed', { defaultValue: 'Claimed' })}</th>
                <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.status', { defaultValue: 'Status' })}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <tr
                  key={o.id}
                  tabIndex={0}
                  onClick={() => onOpen(o.id)}
                  onKeyDown={(e) => e.key === 'Enter' && onOpen(o.id)}
                  className="cursor-pointer border-b border-border-light last:border-0 hover:bg-surface-secondary"
                >
                  <td className="px-4 py-2 font-medium"><bdi>{o.order_no}</bdi></td>
                  <td className="px-4 py-2">{o.site_label || '-'}</td>
                  <td className="whitespace-nowrap px-4 py-2"><DateDisplay value={o.ordered_at} /></td>
                  <td className="px-4 py-2">
                    <div className="flex flex-wrap gap-1">
                      {o.tags.map((tag) => (
                        <Badge key={tag} size="sm">{t(`framework.tag.${tag}`, { defaultValue: tag.replace(/_/g, ' ') })}</Badge>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-end tabular-nums">{o.line_count}</td>
                  <td className="px-4 py-2 text-end tabular-nums"><MoneyDisplay amount={o.net} currency={a.currency} /></td>
                  <td className="px-4 py-2 text-end tabular-nums">{o.has_extras ? <MoneyDisplay amount={o.extras} currency={a.currency} /> : '-'}</td>
                  <td className={`px-4 py-2 text-end tabular-nums ${o.measured_over_ordered ? 'text-semantic-warning' : ''}`}>
                    {o.measured_pct != null ? `${o.measured_pct} %` : '-'}
                  </td>
                  <td className="px-4 py-2 text-end tabular-nums">{Number(o.claimed) ? <MoneyDisplay amount={o.claimed} currency={a.currency} /> : '-'}</td>
                  <td className="px-4 py-2">
                    <Badge variant={statusVariant(o.order_status)} size="sm">
                      {t(`framework.status.${o.order_status}`, { defaultValue: o.order_status })}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function PriceListTab({ a }: { a: AgreementDetail }) {
  const { t } = useTranslation();
  const items = useQuery({ queryKey: [...fwkKeys.detail(a.id), 'items'], queryFn: () => fwkApi.items(a.id) });
  if (items.isLoading) return <SkeletonTable rows={6} columns={7} />;
  return (
    <Card padding="none">
      <p className="border-b border-border-light px-4 py-2 text-xs text-content-tertiary">
        {t('framework.price_list.cited_note', {
          defaultValue: 'A new rate on an item already ordered starts a new rate period draft; issued orders keep their rates.',
        })}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-xs text-content-tertiary">
              <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.code', { defaultValue: 'Code' })}</th>
              <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.description', { defaultValue: 'Description' })}</th>
              <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.unit', { defaultValue: 'Unit' })}</th>
              <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.base_rate', { defaultValue: 'Base rate' })}</th>
              <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.effective_rate', { defaultValue: 'Rate today' })}</th>
              <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.estimated', { defaultValue: 'Est. qty' })}</th>
              <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.ordered', { defaultValue: 'Ordered' })}</th>
              <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.max', { defaultValue: 'Max qty' })}</th>
            </tr>
          </thead>
          <tbody>
            {(items.data ?? []).map((i) => (
              <tr key={i.id} className={`border-b border-border-light last:border-0 ${i.is_active ? '' : 'opacity-50'}`}>
                <td className="px-4 py-2"><bdi className="font-mono text-xs">{i.code}</bdi></td>
                <td className="px-4 py-2">{i.description}</td>
                <td className="px-4 py-2 text-content-tertiary">{i.unit}</td>
                <td className="px-4 py-2 text-end tabular-nums"><MoneyDisplay amount={i.base_rate} currency={a.currency} /></td>
                <td className="px-4 py-2 text-end tabular-nums">
                  {i.effective_rate ? <MoneyDisplay amount={i.effective_rate} currency={a.currency} /> : '-'}
                </td>
                <td className="px-4 py-2 text-end tabular-nums">{i.estimated_qty ?? '-'}</td>
                <td className="px-4 py-2 text-end tabular-nums">{i.ordered_qty}</td>
                <td className="px-4 py-2 text-end tabular-nums">{i.max_qty ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function RatesTab({ a, editable }: { a: AgreementDetail; editable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const periods = useQuery({ queryKey: [...fwkKeys.detail(a.id), 'periods'], queryFn: () => fwkApi.periods(a.id) });
  const activate = useMutation({
    mutationFn: (p: Parameters<typeof fwkApi.activatePeriod>[1]) => fwkApi.activatePeriod(a.id, p),
    onSuccess: () => qc.invalidateQueries({ queryKey: fwkKeys.detail(a.id) }),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  if (periods.isLoading) return <SkeletonTable rows={3} columns={4} />;
  const templates = a.pack.escalation_templates ?? [];
  return (
    <div className="space-y-3">
      <div className="flex gap-3 overflow-x-auto pb-1">
        {(periods.data ?? []).map((p) => (
          <Card key={p.id} className="min-w-[240px]">
            <div className="space-y-1 text-sm">
              <div className="flex items-center justify-between gap-2">
                <strong>{p.label || <DateDisplay value={p.effective_from} />}</strong>
                <Badge size="sm" variant={p.status === 'active' ? 'blue' : 'neutral'}>
                  {t(`framework.period.${p.status}`, { defaultValue: p.status })}
                </Badge>
              </div>
              <div className="text-xs text-content-tertiary">
                <DateDisplay value={p.effective_from} /> - {p.effective_to ? <DateDisplay value={p.effective_to} /> : '…'}
              </div>
              <div>{t(`framework.method.${p.method}`, { defaultValue: p.method })}</div>
              {p.fixed_price_until && (
                <div className="text-xs">
                  {t('framework.period.fixed_until', { defaultValue: 'Fixed prices until' })} <DateDisplay value={p.fixed_price_until} />
                </div>
              )}
              <div className="text-xs">
                {p.factor_error ? (
                  <span className="text-semantic-error">{p.factor_error}</span>
                ) : (
                  t('framework.period.factor_today', { defaultValue: 'Factor today: {{factor}}', factor: p.factor_today ?? '1' })
                )}
              </div>
              {p.status === 'draft' && editable && (
                <Button size="sm" variant="secondary" loading={activate.isPending} onClick={() => activate.mutate(p)}>
                  {t('framework.period.activate', { defaultValue: 'Activate period' })}
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>
      {templates.length > 0 && (
        <Card>
          <p className="oe-label mb-2">{t('framework.period.templates', { defaultValue: 'Escalation templates in this market' })}</p>
          <ul className="space-y-1 text-sm">
            {templates.map((tpl) => (
              <li key={tpl.code} className="flex items-center gap-2">
                <span>{tpl.label}</span>
                {tpl.verified === false && (
                  <Badge size="sm" variant="warning">
                    {t('framework.period.unverified', { defaultValue: 'Template, thresholds not verified' })}
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function ConditionsTab({ a, editable }: { a: AgreementDetail; editable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const key = [...fwkKeys.detail(a.id), 'adjustments'];
  const adjustments = useQuery({ queryKey: key, queryFn: () => fwkApi.adjustments(a.id) });
  const [draft, setDraft] = useState({ code: '', label: '', kind: 'multiplier', value: '', condition: '' });
  const onError = (err: unknown) => addToast({ type: 'error', title: getErrorMessage(err) });
  const add = useMutation({
    mutationFn: () => fwkApi.addAdjustment(a.id, { ...draft, scope: 'all' }),
    onSuccess: () => {
      setDraft({ code: '', label: '', kind: 'multiplier', value: '', condition: '' });
      qc.invalidateQueries({ queryKey: key });
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: (adjId: string) => fwkApi.deleteAdjustment(a.id, adjId),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
    onError,
  });
  const suggestions = a.pack.condition_tags ?? [];
  return (
    <Card padding="none">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-xs text-content-tertiary">
            <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.code', { defaultValue: 'Code' })}</th>
            <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.label', { defaultValue: 'Label' })}</th>
            <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.kind', { defaultValue: 'Kind' })}</th>
            <th scope="col" className="px-4 py-2 text-end font-medium">{t('framework.col.value', { defaultValue: 'Value' })}</th>
            <th scope="col" className="px-4 py-2 text-start font-medium">{t('framework.col.condition', { defaultValue: 'Condition' })}</th>
            <th scope="col" className="w-10"><span className="sr-only">{t('common.actions', { defaultValue: 'Actions' })}</span></th>
          </tr>
        </thead>
        <tbody>
          {(adjustments.data ?? []).map((x) => (
            <tr key={x.id} className="border-b border-border-light">
              <td className="px-4 py-2 font-mono text-xs">{x.code}</td>
              <td className="px-4 py-2">{x.label}</td>
              <td className="px-4 py-2">{t(`framework.kind.${x.kind}`, { defaultValue: x.kind })}</td>
              <td className="px-4 py-2 text-end tabular-nums">{x.value}</td>
              <td className="px-4 py-2">{x.condition ? t(`framework.tag.${x.condition}`, { defaultValue: x.condition }) : '-'}</td>
              <td className="px-2 py-2 text-end">
                {editable && (
                  <button
                    type="button"
                    aria-label={t('common.remove', { defaultValue: 'Remove' })}
                    onClick={() => remove.mutate(x.id)}
                    className="rounded p-1 text-content-tertiary hover:text-semantic-error"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </td>
            </tr>
          ))}
          {editable && (
            <tr>
              <td className="px-4 py-2">
                <input aria-label={t('framework.col.code', { defaultValue: 'Code' })} className="oe-input h-8 w-20" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
              </td>
              <td className="px-4 py-2">
                <input aria-label={t('framework.col.label', { defaultValue: 'Label' })} className="oe-input h-8" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
              </td>
              <td className="px-4 py-2">
                <select aria-label={t('framework.col.kind', { defaultValue: 'Kind' })} className="oe-input h-8" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
                  <option value="multiplier">{t('framework.kind.multiplier', { defaultValue: 'Multiplier' })}</option>
                  <option value="add_per_unit">{t('framework.kind.add_per_unit', { defaultValue: 'Add per unit' })}</option>
                  <option value="lump_sum">{t('framework.kind.lump_sum', { defaultValue: 'Lump sum' })}</option>
                </select>
              </td>
              <td className="px-4 py-2">
                <input aria-label={t('framework.col.value', { defaultValue: 'Value' })} inputMode="decimal" className="oe-input h-8 w-24 text-end" value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value.replace(',', '.') })} />
              </td>
              <td className="px-4 py-2">
                <input aria-label={t('framework.col.condition', { defaultValue: 'Condition' })} list="fwk-tags" className="oe-input h-8" value={draft.condition} onChange={(e) => setDraft({ ...draft, condition: e.target.value })} />
                <datalist id="fwk-tags">
                  {suggestions.map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
              </td>
              <td className="px-2 py-2 text-end">
                <Button size="sm" variant="secondary" disabled={!draft.code || !draft.value} loading={add.isPending} onClick={() => add.mutate()}>
                  {t('common.add', { defaultValue: 'Add' })}
                </Button>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

function TermsTab({ a }: { a: AgreementDetail }) {
  const { t } = useTranslation();
  const overrides = a.terms.cap_overrides ?? [];
  const packValues = (a.terms.pack_values ?? {}) as Record<string, unknown>;
  const visibleFields = agreementPackInputs(a.pack.pack_fields);
  return (
    <div className="space-y-4">
      <Card>
        <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="oe-label">{t('framework.field.override_policy', { defaultValue: 'Over the cap' })}</dt>
            <dd>{t(`framework.policy.${a.terms.override_policy ?? 'block'}`, { defaultValue: a.terms.override_policy ?? 'block' })}</dd>
          </div>
          <div>
            <dt className="oe-label">{t('framework.field.rounding', { defaultValue: 'Rounding' })}</dt>
            <dd>{t(`framework.rounding.${a.terms.rounding ?? 'per_rate'}`, { defaultValue: a.terms.rounding ?? 'per_rate' })}</dd>
          </div>
          {a.pack.term_limit && (
            <div>
              <dt className="oe-label">{t('framework.field.term_limit', { defaultValue: 'Usual maximum term' })}</dt>
              <dd>
                {a.pack.term_limit.years} · {a.pack.term_limit.source}
              </dd>
            </div>
          )}
          {visibleFields.map((f) => (
            <div key={f}>
              <dt className="oe-label">{t(`framework.pack_field.${f}`, { defaultValue: f.replace(/_/g, ' ') })}</dt>
              <dd className="break-words">
                {typeof packValues[f] === 'object' ? JSON.stringify(packValues[f]) : String(packValues[f] ?? '-')}
              </dd>
            </div>
          ))}
        </dl>
      </Card>
      <Card>
        <p className="oe-label mb-2">{t('framework.terms.override_audit', { defaultValue: 'Cap overrides' })}</p>
        {overrides.length === 0 ? (
          <p className="text-sm text-content-tertiary">{t('framework.terms.no_overrides', { defaultValue: 'No order has been issued over the cap.' })}</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {overrides.map((o, i) => (
              <li key={`${o.order_no}-${i}`}>
                <bdi className="font-medium">{o.order_no}</bdi> · <MoneyDisplay amount={o.overrun} currency={a.currency} /> ·{' '}
                <DateDisplay value={o.at} /> · {o.reason}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
