// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One call-off order: frozen lines with measured quantities, extras raised on it, and the
 * issue / progress / close actions. Claims are made on the order in Contracts.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge, Button, SideDrawer, Skeleton } from '@/shared/ui';
import { TabBar } from '@/shared/ui/TabBar';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fwkApi, fwkKeys, type AgreementDetail } from './api';
import { FindingList } from './NewOrderModal';
import { statusVariant } from './status';

interface Props {
  orderId: string;
  agreement: AgreementDetail;
  canIssue: boolean;
  canOverride: boolean;
  onClose: () => void;
}

type Tab = 'lines' | 'extras';

export function OrderDrawer({ orderId, agreement, canIssue, canOverride, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [tab, setTab] = useState<Tab>('lines');
  const [measured, setMeasured] = useState<Record<string, string>>({});
  const [reason, setReason] = useState('');
  const [extra, setExtra] = useState({ title: '', amount: '' });
  const order = useQuery({ queryKey: fwkKeys.order(orderId), queryFn: () => fwkApi.order(orderId) });
  const extras = useQuery({
    queryKey: [...fwkKeys.order(orderId), 'extras'],
    queryFn: () => fwkApi.extras(orderId),
    enabled: tab === 'extras',
  });
  const refresh = () => qc.invalidateQueries({ queryKey: fwkKeys.all });
  const onError = (err: unknown) => addToast({ type: 'error', title: getErrorMessage(err) });

  const issue = useMutation({ mutationFn: () => fwkApi.issueOrder(orderId, reason.trim() || undefined), onSuccess: refresh, onError });
  const status = useMutation({
    mutationFn: (s: 'in_progress' | 'closed' | 'cancelled') => fwkApi.setOrderStatus(orderId, s),
    onSuccess: refresh,
    onError,
  });
  const measure = useMutation({
    mutationFn: () => fwkApi.measure(orderId, measured),
    onSuccess: () => {
      setMeasured({});
      refresh();
    },
    onError,
  });
  const raise = useMutation({
    mutationFn: () => fwkApi.raiseExtra(orderId, { title: extra.title.trim(), amount: extra.amount || '0' }),
    onSuccess: () => {
      setExtra({ title: '', amount: '' });
      refresh();
    },
    onError,
  });

  const o = order.data;
  const cur = agreement.currency;
  const draft = o?.order_status === 'draft';
  const overCap = Boolean(o?.findings.some((f) => f.code === 'FWK_CAP_EXCEEDED'));

  return (
    <SideDrawer
      open
      onClose={onClose}
      widthClass="max-w-3xl"
      title={o ? <bdi>{o.order_no}</bdi> : t('framework.term.order', { defaultValue: 'Call-off order' })}
      subtitle={o?.site_label}
    >
      {!o ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Badge variant={statusVariant(o.order_status)}>
              {t(`framework.status.${o.order_status}`, { defaultValue: o.order_status })}
            </Badge>
            <span className="text-content-tertiary"><DateDisplay value={o.ordered_at} /></span>
            <span className="ms-auto font-medium tabular-nums"><MoneyDisplay amount={o.net} currency={cur} /></span>
            <Link to={`/projects/${o.project_id}/contracts`} className="text-oe-blue hover:underline">
              {t('framework.order.open_contracts', { defaultValue: 'Open in Contracts' })}
            </Link>
          </div>
          {o.terms.cap_override && (
            <p className="rounded-lg bg-semantic-warning-bg p-2 text-xs text-semantic-warning">
              {t('framework.order.override_note', {
                defaultValue: 'Issued over the cap by {{overrun}}: {{reason}}',
                overrun: o.terms.cap_override.overrun,
                reason: o.terms.cap_override.reason,
              })}
            </p>
          )}
          <FindingList findings={o.findings} />

          {canIssue && (
            <div className="flex flex-wrap items-end gap-2">
              {draft && overCap && (canOverride || agreement.terms.override_policy === 'warn') && (
                <label className="flex min-w-[260px] flex-1 flex-col gap-1">
                  <span className="oe-label">{t('framework.cap.override_reason', { defaultValue: 'Reason for exceeding the cap' })}</span>
                  <input className="oe-input" value={reason} onChange={(e) => setReason(e.target.value)} />
                </label>
              )}
              {draft && (
                <Button
                  variant="primary"
                  loading={issue.isPending}
                  disabled={overCap && reason.trim().length < 20}
                  onClick={() => issue.mutate()}
                >
                  {overCap
                    ? t('framework.cap.override', { defaultValue: 'Issue with override' })
                    : t('framework.order.issue', { defaultValue: 'Issue order' })}
                </Button>
              )}
              {o.order_status === 'issued' && (
                <Button variant="secondary" onClick={() => status.mutate('in_progress')}>
                  {t('framework.order.start', { defaultValue: 'Start work' })}
                </Button>
              )}
              {!draft && o.order_status !== 'closed' && o.order_status !== 'cancelled' && (
                <Button variant="secondary" onClick={() => status.mutate('closed')}>
                  {t('framework.order.close', { defaultValue: 'Close order' })}
                </Button>
              )}
              {o.order_status !== 'closed' && o.order_status !== 'cancelled' && (
                <Button variant="ghost" onClick={() => status.mutate('cancelled')}>
                  {t('framework.order.cancel', { defaultValue: 'Cancel order' })}
                </Button>
              )}
            </div>
          )}

          <TabBar<Tab>
            ariaLabel={t('framework.term.order', { defaultValue: 'Call-off order' })}
            activeId={tab}
            onChange={setTab}
            tabs={[
              { id: 'lines', label: t('framework.order.tab_lines', { defaultValue: 'Lines and measurement' }) },
              { id: 'extras', label: t('framework.order.tab_extras', { defaultValue: 'Extras' }) },
            ]}
          />

          {tab === 'lines' && (
            <div className="space-y-3">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light text-xs text-content-tertiary">
                    <th scope="col" className="py-1.5 text-start font-medium">{t('framework.col.code', { defaultValue: 'Code' })}</th>
                    <th scope="col" className="py-1.5 text-start font-medium">{t('framework.col.description', { defaultValue: 'Description' })}</th>
                    <th scope="col" className="py-1.5 text-end font-medium">{t('framework.col.qty', { defaultValue: 'Qty' })}</th>
                    <th scope="col" className="py-1.5 text-end font-medium">{t('framework.col.measured', { defaultValue: 'Measured' })}</th>
                    <th scope="col" className="py-1.5 text-end font-medium">{t('framework.col.rate', { defaultValue: 'Rate' })}</th>
                    <th scope="col" className="py-1.5 text-end font-medium">{t('framework.col.total', { defaultValue: 'Total' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {o.lines.map((l) => {
                    const over = l.measured_qty != null && Number(l.measured_qty) > Number(l.quantity);
                    const editable = !draft && l.origin === 'framework_item' && canIssue;
                    return (
                      <tr key={l.id} className="border-b border-border-light">
                        <td className="py-1.5">
                          <bdi className="font-mono text-xs">{l.code}</bdi>
                          {l.origin !== 'framework_item' && (
                            <Badge variant="purple" size="sm" className="ms-1">{t('framework.order.extra_chip', { defaultValue: 'Extra' })}</Badge>
                          )}
                        </td>
                        <td className="py-1.5">{l.description}</td>
                        <td className="py-1.5 text-end tabular-nums">{l.quantity} {l.unit}</td>
                        <td className={`py-1.5 text-end tabular-nums ${over ? 'text-semantic-warning' : ''}`}>
                          {editable ? (
                            <input
                              aria-label={t('framework.col.measured', { defaultValue: 'Measured' })}
                              inputMode="decimal"
                              className="oe-input-sm w-20 text-end"
                              placeholder={l.measured_qty ?? ''}
                              value={measured[l.id] ?? ''}
                              onChange={(e) => setMeasured((m) => ({ ...m, [l.id]: e.target.value.replace(',', '.') }))}
                            />
                          ) : (
                            (l.measured_qty ?? '-')
                          )}
                        </td>
                        <td className="py-1.5 text-end tabular-nums"><MoneyDisplay amount={l.unit_rate} currency={cur} /></td>
                        <td className="py-1.5 text-end tabular-nums"><MoneyDisplay amount={l.total_value} currency={cur} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {Object.keys(measured).length > 0 && (
                <Button variant="primary" size="sm" loading={measure.isPending} onClick={() => measure.mutate()}>
                  {t('framework.order.save_measurement', { defaultValue: 'Save measurement' })}
                </Button>
              )}
              {agreement.pack.measurement_preset && (
                <p className="text-xs text-content-tertiary">
                  {t('framework.order.measurement_preset', {
                    defaultValue: 'Measurement rules: {{preset}}',
                    preset: agreement.pack.measurement_preset,
                  })}
                </p>
              )}
            </div>
          )}

          {tab === 'extras' && (
            <div className="space-y-3">
              {extras.data?.length ? (
                <ul className="divide-y divide-border-light text-sm">
                  {extras.data.map((x) => (
                    <li key={x.id} className="flex items-center gap-3 py-2">
                      <bdi className="font-mono text-xs">{x.code}</bdi>
                      <span className="flex-1">{x.title}</span>
                      <Badge variant={x.status === 'approved' ? 'success' : 'neutral'} size="sm">{x.status}</Badge>
                      <span className="tabular-nums"><MoneyDisplay amount={x.amount} currency={cur} /></span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-content-tertiary">{t('framework.empty.extras', { defaultValue: 'No extras on this order.' })}</p>
              )}
              {canIssue && !draft && (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="flex min-w-[220px] flex-1 flex-col gap-1">
                    <span className="oe-label">{t('framework.raise_extra', { defaultValue: 'Raise extra' })}</span>
                    <input className="oe-input" value={extra.title} onChange={(e) => setExtra((x) => ({ ...x, title: e.target.value }))} />
                  </label>
                  <label className="flex w-32 flex-col gap-1">
                    <span className="oe-label">{t('framework.col.amount', { defaultValue: 'Amount' })}</span>
                    <input className="oe-input" inputMode="decimal" value={extra.amount} onChange={(e) => setExtra((x) => ({ ...x, amount: e.target.value }))} />
                  </label>
                  <Button variant="secondary" disabled={!extra.title.trim()} loading={raise.isPending} onClick={() => raise.mutate()}>
                    {t('framework.raise_extra', { defaultValue: 'Raise extra' })}
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </SideDrawer>
  );
}
