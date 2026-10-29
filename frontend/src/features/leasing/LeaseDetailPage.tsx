// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One lease: terms, rent schedule, documents and the event trail, with the
 * lifecycle actions (activate, give notice or terminate, renew, delete a draft).
 */
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { ArrowLeft, CheckCircle2, FileText, KeyRound, RefreshCw, Repeat, Trash2, XCircle } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtCurrency, fmtDate } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  activateLease,
  deleteLease,
  fetchLease,
  fetchProjectDocuments,
  fetchSchedule,
  linkDocument,
  regenerateSchedule,
  renewLease,
  terminateLease,
  unlinkDocument,
  validateLease,
} from './api';
import { escalationLabel, eventLabel, frequencyLabel, ruleLabel, statusLabel } from './leasingLabels';
import { STATUS_VARIANT } from './LeasingPage';

type Tab = 'overview' | 'schedule' | 'documents' | 'events';

const inputCls =
  'rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

export function LeaseDetailPage() {
  const { t } = useTranslation();
  const { leaseId = '' } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [tab, setTab] = useState<Tab>('overview');
  const [effective, setEffective] = useState('');
  const [renewEnd, setRenewEnd] = useState('');
  const [renewRent, setRenewRent] = useState('');
  const [docId, setDocId] = useState('');

  const detailQ = useQuery({ queryKey: ['leasing', 'detail', leaseId], queryFn: () => fetchLease(leaseId), enabled: !!leaseId });
  const scheduleQ = useQuery({
    queryKey: ['leasing', 'schedule', leaseId],
    queryFn: () => fetchSchedule(leaseId),
    enabled: !!leaseId && tab === 'schedule',
  });
  const checksQ = useQuery({ queryKey: ['leasing', 'checks', leaseId], queryFn: () => validateLease(leaseId), enabled: !!leaseId });
  const lease = detailQ.data?.lease;
  const docsQ = useQuery({
    queryKey: ['leasing', 'project-docs', lease?.project_id],
    queryFn: () => fetchProjectDocuments(lease?.project_id ?? ''),
    enabled: !!lease && tab === 'documents',
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ['leasing'] });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('leasing.action_failed', { defaultValue: 'That did not work' }), message: getErrorMessage(e) });
  const act = useMutation({
    mutationFn: async (kind: 'activate' | 'terminate' | 'renew' | 'delete' | 'regen' | 'link' | 'unlink' | string) => {
      if (kind === 'activate') return activateLease(leaseId);
      if (kind === 'terminate') return terminateLease(leaseId, { effective });
      if (kind === 'renew') {
        const created = await renewLease(leaseId, { end_date: renewEnd, rent_amount: renewRent || undefined });
        navigate(`/leasing/${created.id}`);
        return created;
      }
      if (kind === 'delete') {
        await deleteLease(leaseId);
        navigate('/leasing');
        return null;
      }
      if (kind === 'regen') return regenerateSchedule(leaseId);
      if (kind === 'link') return linkDocument(leaseId, docId);
      return unlinkDocument(leaseId, kind.slice('unlink:'.length));
    },
    onSuccess: () => {
      addToast({ type: 'success', title: t('leasing.saved', { defaultValue: 'Saved' }) });
      refresh();
    },
    onError,
  });

  if (detailQ.isLoading) return <SkeletonTable rows={6} columns={4} />;
  if (!lease) {
    return (
      <EmptyState
        icon={<FileText size={20} />}
        title={t('leasing.not_found', { defaultValue: 'Lease not found' })}
        action={
          <Link className="text-oe-blue hover:underline" to="/leasing">
            {t('leasing.back', { defaultValue: 'Back to leases' })}
          </Link>
        }
      />
    );
  }

  const live = lease.status === 'active' || lease.status === 'notice';
  const failed = checksQ.data?.results ?? [];
  const tabs: [Tab, string][] = [
    ['overview', t('leasing.tab_overview', { defaultValue: 'Terms' })],
    ['schedule', t('leasing.tab_schedule', { defaultValue: 'Rent schedule' })],
    ['documents', t('leasing.tab_documents', { defaultValue: 'Documents' })],
    ['events', t('leasing.tab_events', { defaultValue: 'History' })],
  ];
  const term = (label: string, value: ReactNode) => (
    <div>
      <dt className="text-2xs text-content-tertiary">{label}</dt>
      <dd className="text-sm text-content-primary">{value}</dd>
    </div>
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <Link to="/leasing" className="inline-flex items-center gap-1 text-xs text-oe-blue hover:underline">
        <ArrowLeft size={14} className="rtl:rotate-180" />
        {t('leasing.back', { defaultValue: 'Back to leases' })}
      </Link>
      <PageHeader
        srTitle={lease.code}
        subtitle={`${lease.unit_label || lease.unit_ref} · ${statusLabel(lease.status, t)}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {lease.status === 'draft' && (
              <>
                <Button variant="primary" size="sm" icon={<KeyRound size={14} />} disabled={act.isPending} onClick={() => act.mutate('activate')}>
                  {t('leasing.activate', { defaultValue: 'Activate' })}
                </Button>
                <Button variant="danger" size="sm" icon={<Trash2 size={14} />} disabled={act.isPending} onClick={() => act.mutate('delete')}>
                  {t('leasing.delete', { defaultValue: 'Delete draft' })}
                </Button>
              </>
            )}
          </div>
        }
      />

      <Card padding="sm">
        {failed.length === 0 ? (
          <p className="flex items-center gap-2 text-xs text-semantic-success">
            <CheckCircle2 size={14} />
            {t('leasing.checks_passed', { defaultValue: 'All lease checks pass' })}
          </p>
        ) : (
          <ul className="space-y-1">
            {failed.map((r) => (
              <li key={r.rule_id} className="flex items-start gap-2 text-xs text-semantic-error">
                <XCircle size={14} className="mt-0.5 shrink-0" />
                {ruleLabel(r.rule_id, r.message, t)}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="inline-flex rounded-lg border border-border bg-surface-secondary p-0.5" role="tablist">
        {tabs.map(([v, label]) => (
          <button
            key={v}
            role="tab"
            aria-selected={tab === v}
            onClick={() => setTab(v)}
            className={clsx(
              'rounded-md px-3 py-1.5 text-xs font-medium',
              tab === v ? 'bg-surface-primary text-content-primary shadow-sm' : 'text-content-tertiary hover:text-content-primary',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card padding="sm" className="lg:col-span-2">
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {term(t('leasing.col_status', { defaultValue: 'Status' }), <Badge variant={STATUS_VARIANT[lease.status]} size="sm">{statusLabel(lease.status, t)}</Badge>)}
              {term(t('leasing.col_start', { defaultValue: 'Start' }), fmtDate(lease.start_date))}
              {term(t('leasing.col_end', { defaultValue: 'End' }), fmtDate(lease.end_date))}
              {term(t('leasing.col_term_months', { defaultValue: 'Term (months)' }), lease.term_months)}
              {term(t('leasing.col_rent', { defaultValue: 'Rent per period' }), fmtCurrency(lease.rent_amount, lease.currency))}
              {term(t('leasing.col_frequency', { defaultValue: 'Billed' }), frequencyLabel(lease.frequency, t))}
              {term(t('leasing.col_deposit', { defaultValue: 'Deposit' }), fmtCurrency(lease.deposit, lease.currency))}
              {term(
                t('leasing.f_escalation', { defaultValue: 'Escalation' }),
                lease.escalation_kind === 'fixed' && lease.escalation_rate
                  ? `${escalationLabel(lease.escalation_kind, t)} · ${lease.escalation_rate}%`
                  : escalationLabel(lease.escalation_kind, t),
              )}
              {term(t('leasing.col_break', { defaultValue: 'Break date' }), lease.break_date ? fmtDate(lease.break_date) : '–')}
            </dl>
          </Card>
          {live && (
            <Card padding="sm" className="space-y-4">
              <div className="space-y-2">
                <p className="text-xs font-semibold text-content-primary">{t('leasing.terminate_title', { defaultValue: 'Notice or termination' })}</p>
                <input type="date" className={clsx(inputCls, 'w-full')} value={effective} onChange={(e) => setEffective(e.target.value)} aria-label={t('leasing.effective', { defaultValue: 'Effective on' })} />
                <Button variant="secondary" size="sm" icon={<XCircle size={14} />} disabled={!effective || act.isPending} onClick={() => act.mutate('terminate')}>
                  {t('leasing.terminate', { defaultValue: 'Give notice' })}
                </Button>
              </div>
              <div className="space-y-2 border-t border-border-light pt-3">
                <p className="text-xs font-semibold text-content-primary">{t('leasing.renew_title', { defaultValue: 'Renew' })}</p>
                <input type="date" className={clsx(inputCls, 'w-full')} value={renewEnd} onChange={(e) => setRenewEnd(e.target.value)} aria-label={t('leasing.col_end', { defaultValue: 'End' })} />
                <input inputMode="decimal" dir="ltr" className={clsx(inputCls, 'w-full')} value={renewRent} placeholder={lease.rent_amount} onChange={(e) => setRenewRent(e.target.value)} aria-label={t('leasing.col_rent', { defaultValue: 'Rent per period' })} />
                <Button variant="secondary" size="sm" icon={<Repeat size={14} />} disabled={!renewEnd || act.isPending} onClick={() => act.mutate('renew')}>
                  {t('leasing.renew', { defaultValue: 'Create renewal draft' })}
                </Button>
              </div>
            </Card>
          )}
        </div>
      )}

      {tab === 'schedule' && (
        <Card padding="none" className="overflow-x-auto">
          <div className="flex items-center justify-between p-3">
            <p className="text-xs text-content-tertiary">
              {t('leasing.schedule_hint', { defaultValue: 'Invoiced lines stay as they are; the rest follows the lease terms.' })}
            </p>
            <Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} disabled={act.isPending || lease.status === 'draft'} onClick={() => act.mutate('regen')}>
              {t('leasing.regenerate', { defaultValue: 'Rebuild' })}
            </Button>
          </div>
          {scheduleQ.isLoading ? (
            <SkeletonTable rows={6} columns={5} />
          ) : (scheduleQ.data?.items ?? []).length === 0 ? (
            <EmptyState
              icon={<FileText size={20} />}
              title={t('leasing.schedule_empty', { defaultValue: 'No schedule yet' })}
              description={t('leasing.schedule_empty_desc', { defaultValue: 'The schedule is built when the lease is activated.' })}
            />
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs text-content-tertiary">
                <tr className="border-b border-border-light">
                  <th className="px-3 py-2 text-start">#</th>
                  <th className="px-3 py-2 text-start">{t('leasing.col_period', { defaultValue: 'Period' })}</th>
                  <th className="px-3 py-2 text-start">{t('leasing.col_due_date', { defaultValue: 'Due' })}</th>
                  <th className="px-3 py-2 text-end">{t('leasing.col_amount', { defaultValue: 'Rent' })}</th>
                  <th className="px-3 py-2 text-end">{t('leasing.col_tax', { defaultValue: 'Tax' })}</th>
                  <th className="px-3 py-2 text-start">{t('leasing.col_invoice', { defaultValue: 'Invoice' })}</th>
                </tr>
              </thead>
              <tbody>
                {(scheduleQ.data?.items ?? []).map((x) => (
                  <tr key={x.id} className="border-b border-border-light last:border-0">
                    <td className="px-3 py-2 tabular-nums">{x.seq}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {fmtDate(x.period_start)} – {fmtDate(x.period_end)}
                    </td>
                    <td className="px-3 py-2">{fmtDate(x.due_date)}</td>
                    <td className="px-3 py-2 text-end tabular-nums">{fmtCurrency(x.amount, lease.currency)}</td>
                    <td className="px-3 py-2 text-end tabular-nums">{fmtCurrency(x.tax_amount, lease.currency)}</td>
                    <td className="px-3 py-2">
                      {x.invoice_id ? (
                        <Badge variant="success" size="sm">{t('leasing.invoiced', { defaultValue: 'Invoiced' })}</Badge>
                      ) : (
                        <Badge variant="neutral" size="sm">{t('leasing.planned', { defaultValue: 'Planned' })}</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="font-semibold">
                  <td className="px-3 py-2" colSpan={3}>{t('leasing.total', { defaultValue: 'Total' })}</td>
                  <td className="px-3 py-2 text-end tabular-nums" colSpan={2}>{fmtCurrency(scheduleQ.data?.total ?? '0', lease.currency)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          )}
        </Card>
      )}

      {tab === 'documents' && (
        <Card padding="sm" className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <select className={inputCls} value={docId} onChange={(e) => setDocId(e.target.value)} aria-label={t('leasing.pick_document', { defaultValue: 'Pick a project document' })}>
              <option value="">{t('leasing.pick_document', { defaultValue: 'Pick a project document' })}</option>
              {(docsQ.data ?? [])
                .filter((d) => !lease.document_ids.includes(d.id))
                .map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
            </select>
            <Button variant="secondary" size="sm" disabled={!docId || act.isPending} onClick={() => act.mutate('link')}>
              {t('leasing.attach', { defaultValue: 'Attach' })}
            </Button>
          </div>
          {(detailQ.data?.documents ?? []).length === 0 ? (
            <p className="text-xs text-content-tertiary">{t('leasing.no_documents', { defaultValue: 'No documents attached yet.' })}</p>
          ) : (
            <ul className="divide-y divide-border-light">
              {(detailQ.data?.documents ?? []).map((d) => (
                <li key={d.id} className="flex items-center justify-between py-2 text-sm">
                  <span className="flex items-center gap-2">
                    <FileText size={14} className="text-content-tertiary" />
                    {d.name}
                  </span>
                  <Button variant="ghost" size="sm" icon={<Trash2 size={14} />} onClick={() => act.mutate(`unlink:${d.id}`)}>
                    {t('leasing.detach', { defaultValue: 'Remove' })}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === 'events' && (
        <Card padding="sm">
          <ol className="space-y-2">
            {(detailQ.data?.events ?? []).map((e) => (
              <li key={e.id} className="flex items-center gap-3 text-sm">
                <span className="w-24 shrink-0 text-xs text-content-tertiary">{fmtDate(e.event_date)}</span>
                <span className="text-content-primary">{eventLabel(e.kind, t)}</span>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}
